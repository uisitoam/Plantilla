"""Train a model inside a tracked experiment run.

Usage:
    packagename-train
    packagename-train wandb.mode=offline
    packagename-train --multirun random_seed=1,2,3

The run is opened here, around the training call, so that a crash is recorded as
a failed run and every override reaching Hydra is captured in the run config.
Library code deeper down can log to the same run via
:func:`packagename.tracking.active_tracker`, without passing the tracker along.
"""

from __future__ import annotations

from packagename.cli._hydra import hydra_entrypoint
from packagename.config import Settings
from packagename.log import get_logger
from packagename.tracking import ExperimentTracker, start_run

logger = get_logger(__name__)


@hydra_entrypoint
def main(settings: Settings) -> None:
    """Open a tracked run and hand control to the training routine."""
    with start_run(settings=settings, job_type="train") as tracker:
        _train(settings, tracker)


def _train(settings: Settings, tracker: ExperimentTracker) -> None:
    """Placeholder training routine.

    Replace the body with real training. The surrounding wiring — config,
    seeding, logging, tracking, artifact paths — is already in place:

        model = fit(read_table(settings.paths.gold / "train.parquet"))
        tracker.log_params({"n_estimators": 300})
        tracker.log_metrics({"val/rmse": rmse})
        tracker.log_summary({"best/val_rmse": rmse})
        tracker.log_model(settings.paths.models / "model.joblib")
    """
    del tracker  # Nothing to log until there is a model.
    logger.warning(
        "No training code yet. Implement packagename.models and call it from "
        "packagename.cli.train._train (project=%s).",
        settings.project_name,
    )


if __name__ == "__main__":
    main()
