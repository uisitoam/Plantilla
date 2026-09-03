"""Per-region subsampling and the dataset manifest."""

from __future__ import annotations

import os

import pandas as pd
import pytest

from packagename.config import SampleSettings
from packagename.data import check_datasets, discover_regions, manifest_path, subsample_datasets
from packagename.etl import read_table, write_table


def _region(settings, name, files):
    """Create a raw region directory with the given dataframes as CSV files."""
    directory = settings.paths.raw / name
    directory.mkdir(parents=True)
    for filename, frame in files.items():
        write_table(frame, directory / filename)
    return directory


def _frame(rows=20):
    return pd.DataFrame({"value": range(rows), "label": [f"r{i}" for i in range(rows)]})


@pytest.fixture
def sampled(settings):
    """Settings with two sampled regions and a manifest on disk."""
    _region(settings, "north", {"a.csv": _frame(), "b.csv": _frame()})
    _region(settings, "south", {"c.csv": _frame(), "d.csv": _frame()})
    subsample_datasets(settings)
    return settings


class TestDiscoverRegions:
    def test_no_raw_layer_means_no_regions(self, settings):
        assert discover_regions(settings.paths.raw) == {}

    def test_regions_map_to_their_sampleable_files_sorted(self, settings):
        _region(settings, "north", {"b.csv": _frame(), "a.csv": _frame(3)})

        regions = discover_regions(settings.paths.raw)

        assert [f.name for f in regions["north"]] == ["a.csv", "b.csv"]

    def test_files_at_the_top_level_are_not_a_region(self, settings):
        """A stray file under raw/ is a layout mistake, not a region."""
        settings.paths.raw.mkdir(parents=True)
        write_table(_frame(3), settings.paths.raw / "stray.csv")

        assert discover_regions(settings.paths.raw) == {}

    def test_unsupported_files_are_ignored(self, settings):
        directory = settings.paths.raw / "north"
        directory.mkdir(parents=True)
        (directory / "notes.txt").write_text("x", encoding="utf-8")

        assert discover_regions(settings.paths.raw) == {}


class TestSubsample:
    def test_writes_one_sample_per_region_and_the_manifest(self, sampled):
        assert (sampled.paths.sample / "north_sample.csv").is_file()
        assert (sampled.paths.sample / "south_sample.csv").is_file()

        manifest = manifest_path(sampled)
        assert manifest.is_file()
        assert manifest.parent == sampled.paths.raw.parent

    def test_the_sample_is_bounded_by_the_configured_rows(self, settings):
        _region(settings, "north", {"a.csv": _frame(20)})
        small = settings.model_copy(update={"sample": SampleSettings(rows=5, seed=26)})

        subsample_datasets(small)

        assert len(read_table(small.paths.sample / "north_sample.csv")) == 5

    def test_a_source_smaller_than_rows_is_copied_whole(self, settings):
        _region(settings, "north", {"a.csv": _frame(3)})

        subsample_datasets(settings)

        assert len(read_table(settings.paths.sample / "north_sample.csv")) == 3

    def test_the_draw_is_reproducible(self, settings):
        """The committed samples only make sense if anyone regenerates the same bytes."""
        _region(settings, "north", {"a.csv": _frame(50)})

        subsample_datasets(settings)
        first = (settings.paths.sample / "north_sample.csv").read_bytes()
        subsample_datasets(settings)

        assert (settings.paths.sample / "north_sample.csv").read_bytes() == first

    def test_the_seed_is_what_changes_the_sample(self, settings):
        _region(settings, "north", {"a.csv": _frame(50)})

        subsample_datasets(settings.model_copy(update={"sample": SampleSettings(rows=10, seed=26)}))
        seeded = (settings.paths.sample / "north_sample.csv").read_bytes()
        subsample_datasets(settings.model_copy(update={"sample": SampleSettings(rows=10, seed=7)}))

        assert (settings.paths.sample / "north_sample.csv").read_bytes() != seeded

    def test_the_source_is_stable_across_runs(self, sampled):
        """Re-running must not move the committed samples to another source file."""
        subsample_datasets(sampled)

        assert "source: data/raw/north/a.csv" in manifest_path(sampled).read_text(encoding="utf-8")

    def test_a_missing_recorded_source_falls_back_to_the_first_file(self, settings):
        _region(settings, "north", {"a.csv": _frame(), "b.csv": _frame()})
        subsample_datasets(settings)
        (settings.paths.raw / "north" / "a.csv").unlink()

        subsample_datasets(settings)

        assert "source: data/raw/north/b.csv" in manifest_path(settings).read_text(encoding="utf-8")

    def test_no_regions_still_writes_a_manifest(self, settings):
        """A fresh clone can run the command and get an honest empty manifest."""
        destination = subsample_datasets(settings)

        assert destination.is_file()
        assert check_datasets(settings) == []

    # The local netCDF4 build warns about a numpy ABI mismatch at import; the
    # warning is the environment's, not the sampler's, and the suite turns
    # warnings into errors.
    @pytest.mark.filterwarnings("ignore::RuntimeWarning")
    def test_netcdf_is_sampled_along_time(self, settings):
        xr = pytest.importorskip("xarray")
        directory = settings.paths.raw / "north"
        directory.mkdir(parents=True)
        dataset = xr.Dataset(
            {"hs": ("time", range(20))}, coords={"time": pd.date_range("2020", periods=20)}
        )
        dataset.to_netcdf(directory / "waves.nc")
        small = settings.model_copy(update={"sample": SampleSettings(rows=5, seed=26)})

        subsample_datasets(small)

        with xr.open_dataset(small.paths.sample / "north_sample.nc") as sample:
            assert sample.sizes["time"] == 5
            assert sample["time"].to_index().is_monotonic_increasing


class TestCheck:
    def test_a_fresh_subsample_has_no_drift(self, sampled):
        assert check_datasets(sampled) == []

    def test_without_a_manifest_there_is_nothing_to_check(self, settings):
        assert check_datasets(settings) == []

    def test_changed_content_is_reported(self, sampled):
        target = sampled.paths.raw / "north" / "a.csv"
        frame = _frame(20)
        frame["value"] = frame["value"] + 1
        write_table(frame, target)

        drift = check_datasets(sampled)

        assert any("a.csv" in message and "changed" in message for message in drift)

    def test_a_same_size_change_is_caught_by_rehashing(self, sampled):
        """Size and mtime may skip work, but only the hash may declare a match."""
        target = sampled.paths.raw / "north" / "a.csv"
        frame = read_table(target)
        frame.loc[0, "value"] = 3  # same file size, different bytes
        write_table(frame, target)

        drift = check_datasets(sampled)

        assert any("a.csv" in message for message in drift)

    def test_a_touch_without_a_content_change_is_not_drift(self, sampled):
        """An innocent `cp` moves mtimes; that must not cry wolf."""
        target = sampled.paths.raw / "north" / "a.csv"
        os.utime(target, None)

        assert check_datasets(sampled) == []

    def test_a_new_file_is_reported(self, sampled):
        write_table(_frame(3), sampled.paths.raw / "north" / "new.csv")

        drift = check_datasets(sampled)

        assert any("new.csv" in message and "new" in message for message in drift)

    def test_a_missing_file_is_reported(self, sampled):
        (sampled.paths.raw / "south" / "c.csv").unlink()

        drift = check_datasets(sampled)

        assert any("c.csv" in message and "missing" in message for message in drift)

    def test_a_missing_region_is_reported(self, sampled):
        import shutil

        shutil.rmtree(sampled.paths.raw / "south")

        drift = check_datasets(sampled)

        assert any("south" in message and "region" in message for message in drift)

    def test_a_clone_without_data_is_not_drift(self, sampled):
        """The machine that only has the samples has nothing to check."""
        import shutil

        shutil.rmtree(sampled.paths.raw)

        assert check_datasets(sampled) == []


@pytest.mark.integration
class TestDataEntrypoint:
    """`packagename-data` is what the just recipes invoke, so it is a contract."""

    def _run(self, tmp_path, monkeypatch, *argv: str) -> int:
        from packagename.cli.data import main
        from packagename.config import reset_settings_cache

        monkeypatch.setenv("PACKAGENAME_PATHS__ROOT", str(tmp_path))
        reset_settings_cache()
        return main(list(argv))

    def test_subsample_then_check_is_clean(self, tmp_path, monkeypatch):
        region = tmp_path / "data" / "raw" / "north"
        region.mkdir(parents=True)
        _frame().to_csv(region / "a.csv", index=False)

        assert self._run(tmp_path, monkeypatch, "subsample") == 0
        assert (tmp_path / "data" / "manifest.yaml").is_file()
        assert self._run(tmp_path, monkeypatch, "check") == 0

    def test_check_exits_non_zero_on_drift(self, tmp_path, monkeypatch):
        """The just recipe has to fail loudly, not print a warning nobody reads."""
        region = tmp_path / "data" / "raw" / "north"
        region.mkdir(parents=True)
        _frame().to_csv(region / "a.csv", index=False)
        assert self._run(tmp_path, monkeypatch, "subsample") == 0

        _frame(30).to_csv(region / "a.csv", index=False)

        assert self._run(tmp_path, monkeypatch, "check") == 1

    def test_a_missing_subcommand_exits_non_zero(self):
        from packagename.cli.data import main

        with pytest.raises(SystemExit) as exited:
            main([])
        assert exited.value.code != 0

    def test_an_unknown_subcommand_exits_non_zero(self):
        from packagename.cli.data import main

        with pytest.raises(SystemExit) as exited:
            main(["frobnicate"])
        assert exited.value.code != 0
