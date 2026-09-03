"""Experiment tracking: provenance, run lifecycle and the ergonomic wrappers.

Runs execute with ``wandb.mode="disabled"``, so nothing touches the network while
the whole code path is still exercised.
"""

from __future__ import annotations

import subprocess

import matplotlib.pyplot as plt
import pytest

from packagename.tracking import (
    ExperimentTracker,
    active_tracker,
    git_metadata,
    start_run,
    track,
)


class TestGitMetadata:
    def test_reports_commit_branch_and_dirtiness(self):
        meta = git_metadata()
        assert set(meta) == {"git_commit", "git_branch", "git_dirty"}
        assert meta["git_dirty"] in {"true", "false", "unknown"}

    def test_commit_is_a_short_hash(self):
        commit = git_metadata()["git_commit"]
        assert commit == "unknown" or (commit.isalnum() and len(commit) <= 12)

    def test_degrades_gracefully_without_git(self, monkeypatch):
        def _no_git(*_args, **_kwargs):
            raise FileNotFoundError("git")

        monkeypatch.setattr(subprocess, "run", _no_git)
        assert git_metadata() == {
            "git_commit": "unknown",
            "git_branch": "unknown",
            "git_dirty": "unknown",
        }

    def test_failed_git_command_is_not_fatal(self, monkeypatch):
        def _fail(*_args, **_kwargs):
            raise subprocess.CalledProcessError(128, "git")

        monkeypatch.setattr(subprocess, "run", _fail)
        assert git_metadata()["git_commit"] == "unknown"


@pytest.mark.integration
class TestStartRun:
    def test_yields_a_tracker_and_closes_the_run(self, settings):
        with start_run("unit", settings=settings) as tracker:
            assert isinstance(tracker, ExperimentTracker)
            assert active_tracker() is tracker
        assert active_tracker() is None

    def test_records_provenance_in_the_run_config(self, settings):
        with start_run("unit", settings=settings) as tracker:
            assert "git_commit" in tracker.run.config
            assert "git_dirty" in tracker.run.config

    def test_records_the_resolved_settings(self, settings):
        with start_run("unit", settings=settings) as tracker:
            assert tracker.run.config["project_name"] == "test-project"
            assert tracker.run.config["wandb.mode"] == "disabled"

    def test_settings_logging_can_be_switched_off(self, settings):
        with start_run("unit", settings=settings, log_settings=False) as tracker:
            assert "project_name" not in tracker.run.config

    def test_explicit_config_wins_over_the_settings(self, settings):
        with start_run("unit", settings=settings, config={"project_name": "override"}) as tracker:
            assert tracker.run.config["project_name"] == "override"

    def test_disabled_mode_reports_itself_as_disabled(self, settings):
        with start_run("unit", settings=settings) as tracker:
            assert tracker.enabled is False
            assert tracker.url is None

    def test_exceptions_propagate_and_mark_the_run_as_failed(self, settings, monkeypatch):
        exit_codes: list[int] = []
        original = ExperimentTracker.finish

        def spy(self: ExperimentTracker, exit_code: int = 0) -> None:
            exit_codes.append(exit_code)
            original(self, exit_code)

        monkeypatch.setattr(ExperimentTracker, "finish", spy)

        with pytest.raises(RuntimeError, match="boom"), start_run("unit", settings=settings):
            raise RuntimeError("boom")

        assert exit_codes == [1], "a failed run must be finished with a non-zero exit code"
        assert active_tracker() is None

    def test_successful_runs_finish_cleanly(self, settings, monkeypatch):
        exit_codes: list[int] = []
        original = ExperimentTracker.finish

        def spy(self: ExperimentTracker, exit_code: int = 0) -> None:
            exit_codes.append(exit_code)
            original(self, exit_code)

        monkeypatch.setattr(ExperimentTracker, "finish", spy)

        with start_run("unit", settings=settings):
            pass

        assert exit_codes == [0]


@pytest.mark.integration
class TestLogging:
    def test_metrics_and_params_accept_a_prefix(self, settings):
        with start_run("unit", settings=settings) as tracker:
            tracker.log_params({"lr": 0.1}, prefix="model.")
            tracker.log_metrics({"loss": 1.0}, prefix="train/")
            assert tracker.run.config["model.lr"] == 0.1

    def test_summary_values_are_recorded(self, settings):
        with start_run("unit", settings=settings) as tracker:
            tracker.log_summary({"best/rmse": 0.3})
            assert tracker.run.summary["best/rmse"] == 0.3

    def test_figure_is_saved_next_to_the_other_figures(self, settings):
        fig, ax = plt.subplots()
        ax.plot([0, 1], [0, 1])
        with start_run("unit", settings=settings) as tracker:
            tracker.log_figure(fig, "curve", save_as="curve.png")
        assert (settings.paths.figures / "curve.png").exists()
        assert not plt.fignum_exists(fig.number), "log_figure closes the figure by default"

    def test_missing_artifact_is_reported_clearly(self, settings, tmp_path):
        with (
            start_run("unit", settings=settings) as tracker,
            pytest.raises(FileNotFoundError, match="missing artifact"),
        ):
            tracker.log_artifact(tmp_path / "absent.parquet")

    def test_artifact_from_a_file(self, settings, tmp_path):
        payload = tmp_path / "data.csv"
        payload.write_text("a,b\n1,2\n")
        with start_run("unit", settings=settings) as tracker:
            tracker.log_artifact(payload, kind="dataset")

    def test_model_artifact_uses_the_model_type(self, settings, tmp_path):
        payload = tmp_path / "model.joblib"
        payload.write_bytes(b"weights")
        with start_run("unit", settings=settings) as tracker:
            tracker.log_model(payload, aliases=["best"])


@pytest.mark.integration
class TestTrackDecorator:
    def test_injects_the_tracker_when_declared(self, settings):
        @track(settings=settings)
        def experiment(tracker: ExperimentTracker | None = None) -> ExperimentTracker | None:
            return tracker

        assert isinstance(experiment(), ExperimentTracker)

    def test_a_tracker_parameter_without_a_default_is_rejected(self, settings):
        """Otherwise the decorated function looks like it needs an argument."""
        with pytest.raises(TypeError, match="no default"):

            @track(settings=settings)
            def experiment(tracker: ExperimentTracker) -> None: ...

    def test_an_explicit_tracker_is_not_overwritten(self, settings):
        @track(settings=settings)
        def experiment(tracker: ExperimentTracker | None = None) -> str:
            return "sentinel" if tracker is None else "injected"

        assert experiment(tracker=None) == "sentinel"

    def test_works_without_the_parameter(self, settings):
        @track(settings=settings)
        def experiment() -> str:
            inner = active_tracker()
            assert inner is not None
            return "done"

        assert experiment() == "done"

    def test_preserves_metadata_and_arguments(self, settings):
        @track(settings=settings)
        def experiment(a: int, b: int = 2) -> int:
            """Add two numbers."""
            return a + b

        assert experiment(1, b=5) == 6
        assert experiment.__name__ == "experiment"
        assert experiment.__doc__ == "Add two numbers."

    def test_run_name_defaults_to_the_function_name(self, settings, wandb_init_spy):
        @track(settings=settings)
        def my_experiment() -> None: ...

        my_experiment()
        assert wandb_init_spy[-1]["name"] == "my_experiment"

    def test_explicit_name_overrides_the_default(self, settings, wandb_init_spy):
        @track(name="chosen", settings=settings)
        def my_experiment() -> None: ...

        my_experiment()
        assert wandb_init_spy[-1]["name"] == "chosen"

    def test_extra_arguments_reach_the_run(self, settings, wandb_init_spy):
        @track(settings=settings, tags=["smoke"], job_type="eval")
        def my_experiment() -> None: ...

        my_experiment()
        assert "smoke" in wandb_init_spy[-1]["tags"]
        assert wandb_init_spy[-1]["job_type"] == "eval"


def test_no_tracker_outside_a_run():
    assert active_tracker() is None
