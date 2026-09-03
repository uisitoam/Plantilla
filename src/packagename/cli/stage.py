"""Run ETL stages. This is the command behind ``just etl``.

Usage:
    packagename-stage --list
    packagename-stage --all
    packagename-stage generate_measurements

Deliberately *not* a Hydra entrypoint, for two reasons that are worth stating
because the rest of the project is Hydra-driven:

* **A stage takes an argument Hydra cannot express.** Hydra's parser rejects
  flags it does not know, and an override like ``stage=ingest`` has to name a key
  that exists in the composed config *and* a field of ``Settings`` -- which an
  orchestration detail has no business being.
* **A stage's parameters come from the versioned file and nowhere else.** A
  value injected on the command line would leave no trace in ``git log``, and
  the committed samples and manifest describe data produced by the file's
  values. To change a parameter, edit ``configs/config.yaml`` and rerun.

Everything else the entrypoints do is kept: settings are validated, logging is
configured, the seed is applied, the directories are created, and the settings
are bound so helpers that call ``get_settings()`` see the same object.
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Mapping, Sequence

from packagename.config import load_settings, use_settings
from packagename.etl import StageFunction, registered_stages, run_stage
from packagename.log import get_logger, setup_logging
from packagename.seed import set_seed

logger = get_logger(__name__)


def main(argv: Sequence[str] | None = None) -> int:
    """Run one stage, every stage in registration order, or list the names.

    Args:
        argv: Arguments to parse. Defaults to ``sys.argv[1:]``.

    Returns:
        A process exit code: 0 on success. A stage that fails raises, which the
        console script turns into a non-zero exit.
    """
    stages = registered_stages()
    parser = _parser(stages)
    arguments = parser.parse_args(argv)

    settings = load_settings()
    with use_settings(settings):
        setup_logging(settings)

        if arguments.list:
            for name in stages:
                print(name)
            return 0

        if arguments.all:
            names = list(stages)
        elif arguments.stage is not None:
            if arguments.stage not in stages:
                parser.error(f"unknown stage {arguments.stage!r}; run --list to see the names")
            names = [arguments.stage]
        else:
            parser.error("a stage name is required unless --list or --all is given")

        set_seed(settings.random_seed)
        settings.paths.ensure()

        for name in names:
            started = time.perf_counter()
            logger.info("Running stage %s", name)
            run_stage(name, settings)
            logger.info("Stage %s finished in %.2fs", name, time.perf_counter() - started)

    return 0


def _parser(stages: Mapping[str, StageFunction]) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="packagename-stage",
        description="Run ETL stages, one by name or all in registration order.",
    )
    parser.add_argument(
        "stage",
        nargs="?",
        help=f"name of the stage to run (one of: {', '.join(sorted(stages))})",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="print the registered stage names, one per line, and exit",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="run every stage, in registration order",
    )
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
