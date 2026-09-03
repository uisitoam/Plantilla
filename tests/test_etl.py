"""The stage registry, the example stages, and tabular IO."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from packagename.config import EtlSettings
from packagename.etl import (
    UnknownStageError,
    aggregate_measurements,
    generate_measurements,
    read_table,
    registered_stages,
    run_stage,
    stage,
    write_table,
)
from packagename.etl import registry as registry_module
from packagename.etl.pipeline import raw_measurements, summary_table


class TestRegistry:
    """A stage name on the command line has to reach exactly one function."""

    def test_the_shipped_stages_are_registered(self):
        assert set(registered_stages()) == {"generate_measurements", "aggregate_measurements"}

    def test_run_stage_calls_the_registered_function(self, settings, monkeypatch):
        calls: list[str] = []
        # Registered through the private mapping so that monkeypatch removes it
        # again: a name leaking out of one test would change what the others see.
        monkeypatch.setitem(registry_module._STAGES, "only_here", lambda _s: calls.append("ran"))

        run_stage("only_here", settings)

        assert calls == ["ran"]

    def test_an_unknown_name_names_the_alternatives(self, settings):
        with pytest.raises(UnknownStageError, match="generate_measurements"):
            run_stage("no_such_stage", settings)

    def test_a_duplicate_name_is_refused(self):
        """Two implementations under one name would resolve by import order."""
        with pytest.raises(ValueError, match="already registered"):
            stage("generate_measurements")(lambda _settings: None)

    def test_the_accessor_hands_out_a_copy(self):
        """Listing the stages must not be a way to edit the registry."""
        assert registered_stages() is not registry_module._STAGES


class TestExampleStages:
    """They ship as the worked example, so they are also what proves the wiring works."""

    def test_generate_writes_the_configured_number_of_rows(self, settings):
        generate_measurements(settings)

        written = read_table(raw_measurements(settings))
        assert len(written) == settings.etl.rows
        assert list(written.columns) == ["station", "value"]

    def test_generate_is_deterministic(self, settings):
        """An output whose bytes moved every run would rebuild everything downstream."""
        generate_measurements(settings)
        first = raw_measurements(settings).read_bytes()

        generate_measurements(settings)

        assert raw_measurements(settings).read_bytes() == first

    def test_the_seed_is_what_changes_the_data(self, settings):
        generate_measurements(settings)
        seeded = raw_measurements(settings).read_bytes()

        generate_measurements(settings.model_copy(update={"random_seed": 7}))

        assert raw_measurements(settings).read_bytes() != seeded

    def test_aggregate_summarises_per_station(self, settings):
        generate_measurements(settings)
        aggregate_measurements(settings)

        summary = read_table(summary_table(settings))
        assert list(summary.columns) == ["station", "observations", "mean_value"]
        assert summary["station"].is_monotonic_increasing
        assert (summary["mean_value"] > settings.etl.threshold).all()

    def test_the_threshold_changes_the_output(self, settings):
        """The behaviour the `etl` section of the config exists to parameterise."""
        generate_measurements(settings)
        aggregate_measurements(settings)
        permissive = read_table(summary_table(settings))["observations"].sum()

        stricter = settings.model_copy(update={"etl": EtlSettings(threshold=2.0)})
        aggregate_measurements(stricter)
        strict = read_table(summary_table(settings))["observations"].sum()

        assert strict < permissive

    def test_a_missing_input_is_an_error(self, settings):
        """A stage must not invent data its predecessor never wrote."""
        with pytest.raises(FileNotFoundError, match="No such table"):
            aggregate_measurements(settings)


class TestTableIO:
    @pytest.mark.parametrize("suffix", [".parquet", ".csv", ".tsv", ".jsonl"])
    def test_round_trip(self, tmp_path, suffix):
        df = pd.DataFrame({"a": [1, 2], "b": ["x", "y"]})
        written = write_table(df, tmp_path / f"table{suffix}")
        pd.testing.assert_frame_equal(read_table(written), df)

    def test_parent_directories_are_created(self, tmp_path):
        target = write_table(pd.DataFrame({"a": [1]}), tmp_path / "deep" / "nested" / "t.parquet")
        assert target.exists()

    def test_no_staging_file_is_left_behind(self, tmp_path):
        write_table(pd.DataFrame({"a": [1]}), tmp_path / "t.parquet")
        assert [p.name for p in tmp_path.iterdir()] == ["t.parquet"]

    def test_a_failed_write_leaves_no_partial_output(self, tmp_path, monkeypatch):
        """An interrupted stage must not leave a half-written file behind.

        A writer that can do so turns a crashed run into a plausible-looking
        output, and the manifest fingerprints would record garbage as if it were
        data. Any writer added for another format -- NetCDF, Zarr -- has to
        follow this pattern.
        """

        def explode(self, path, **kwargs):  # noqa: ARG001
            Path(path).write_bytes(b"partial")
            raise OSError("disk full")

        monkeypatch.setattr(pd.DataFrame, "to_parquet", explode)
        target = tmp_path / "t.parquet"
        with pytest.raises(OSError, match="disk full"):
            write_table(pd.DataFrame({"a": [1]}), target)

        assert not target.exists()
        assert list(tmp_path.iterdir()) == [], "the staging file must be cleaned up"

    def test_unsupported_write_format(self, tmp_path):
        with pytest.raises(ValueError, match="Unsupported table format"):
            write_table(pd.DataFrame({"a": [1]}), tmp_path / "t.xlsx")

    def test_unsupported_read_format(self, tmp_path):
        (tmp_path / "t.xlsx").write_text("x", encoding="utf-8")
        with pytest.raises(ValueError, match="Unsupported table format"):
            read_table(tmp_path / "t.xlsx")

    def test_missing_file(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="No such table"):
            read_table(tmp_path / "absent.parquet")
