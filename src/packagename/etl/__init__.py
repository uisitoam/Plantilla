"""ETL over the medallion layout (``raw -> bronze -> silver -> gold``).

This package holds the transformations (:mod:`packagename.etl.pipeline`), the
registry that maps a stage name to one of them
(:mod:`packagename.etl.registry`), and tabular IO with atomic writes
(:mod:`packagename.etl.io`). Stages run one per process through the
``packagename-stage`` command, in registration order when run with ``--all``.
"""

from packagename.etl.io import read_table, write_table
from packagename.etl.pipeline import aggregate_measurements, generate_measurements
from packagename.etl.registry import (
    StageFunction,
    UnknownStageError,
    registered_stages,
    run_stage,
    stage,
)

__all__ = [
    "StageFunction",
    "UnknownStageError",
    "aggregate_measurements",
    "generate_measurements",
    "read_table",
    "registered_stages",
    "run_stage",
    "stage",
    "write_table",
]
