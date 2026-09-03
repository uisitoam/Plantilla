"""The project's ETL stages: one function per stage.

The two stages below are a worked example, not domain code. They exist so that a
fresh clone can run the pipeline end to end -- with no data to download -- and
see it work: the first stage synthesises a raw dataset, the second derives a
summary from it.

Replace them with real transformations. What has to stay is the shape:

* one function per stage, taking ``Settings`` and returning nothing;
* every value that decides what the stage writes read from ``settings``, so the
  value lives in the versioned ``configs/config.yaml`` and its change shows up
  in ``git log``. A literal buried in the code does neither;
* every file read or written passed as an explicit path, so the stage's inputs
  and outputs are visible in one reading.

Stages run in registration order: ``packagename-stage --all`` runs them in the
order this module registers them, so a producer has to be declared before its
consumer. Real raw data does not come from a stage; it arrives from outside the
project, and ``packagename-data subsample`` is what keeps a small committed
sample of it. See docs/etl.md.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from packagename.config import Settings
from packagename.etl.io import read_table, write_table
from packagename.etl.registry import stage
from packagename.log import get_logger

__all__ = ["aggregate_measurements", "generate_measurements", "raw_measurements", "summary_table"]

logger = get_logger(__name__)

#: Stations the synthetic dataset is spread over. Fixed, so that changing
#: ``etl.rows`` changes the number of observations and not the schema.
_STATIONS = ("north", "south", "east", "west")


def raw_measurements(settings: Settings) -> Path:
    """Return the path of the synthetic raw dataset.

    Declared as a function rather than written out twice, so that the producing
    stage and the consuming one cannot drift apart.
    """
    return settings.paths.raw / "measurements.csv"


def summary_table(settings: Settings) -> Path:
    """Return the path of the per-station summary derived from the raw dataset."""
    return settings.paths.silver / "measurements.parquet"


@stage("generate_measurements")
def generate_measurements(settings: Settings) -> None:
    """Write a synthetic raw dataset, seeded so the bytes are reproducible.

    Stands in for whatever brings raw data into the project. Determinism is the
    part worth copying: an output whose bytes change on every run would make
    every change detection downstream meaningless.

    Args:
        settings: Reads ``etl.rows`` and ``random_seed``.
    """
    generator = np.random.default_rng(settings.random_seed)
    rows = settings.etl.rows
    measurements = pd.DataFrame(
        {
            "station": generator.choice(_STATIONS, size=rows),
            "value": generator.normal(loc=0.0, scale=1.0, size=rows).round(6),
        }
    )
    destination = write_table(measurements, raw_measurements(settings))
    logger.info("Generated %d measurement(s) in %s", rows, destination)


@stage("aggregate_measurements")
def aggregate_measurements(settings: Settings) -> None:
    """Summarise the raw measurements per station, above a threshold.

    Args:
        settings: Reads ``etl.threshold`` from ``configs/config.yaml``.
    """
    measurements = read_table(raw_measurements(settings))
    kept = measurements[measurements["value"] > settings.etl.threshold]
    summary = (
        kept.groupby("station", as_index=False)
        .agg(observations=("value", "size"), mean_value=("value", "mean"))
        .sort_values("station", ignore_index=True)
    )
    destination = write_table(summary, summary_table(settings))
    logger.info(
        "Kept %d of %d measurement(s) above %.3f; wrote %s",
        len(kept),
        len(measurements),
        settings.etl.threshold,
        destination,
    )
