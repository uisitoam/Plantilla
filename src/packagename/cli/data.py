"""Manage the local data samples. This is the command behind ``just subsample``.

Usage:
    packagename-data subsample
    packagename-data check

``subsample`` draws one small, seeded sample per region out of ``data/raw/``
into ``data/sample/`` -- which is committed to Git, so that a local test run
exercises the same code the full run will -- and fingerprints every full
dataset into ``data/manifest.yaml``. ``check`` compares that manifest against
whatever is on disk now, and exits non-zero when a dataset changed, went
missing or is new: that is the "your samples are stale" warning, meant to be
cheap enough to run before pushing.

Like ``packagename-stage``, this is deliberately *not* a Hydra entrypoint and
accepts no overrides: the parameters that shape the samples live in
``configs/config.yaml`` (the ``sample`` section), because a sample drawn from a
value typed on the command line would not match the one committed.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from packagename.config import load_settings, use_settings
from packagename.data import check_datasets, subsample_datasets
from packagename.log import get_logger, setup_logging

logger = get_logger(__name__)


def main(argv: Sequence[str] | None = None) -> int:
    """Regenerate the samples and manifest, or check the datasets against it.

    Args:
        argv: Arguments to parse. Defaults to ``sys.argv[1:]``.

    Returns:
        A process exit code: 0 on success, 1 when ``check`` finds drift.
    """
    parser = _parser()
    arguments = parser.parse_args(argv)

    settings = load_settings()
    with use_settings(settings):
        setup_logging(settings)
        settings.paths.ensure()

        if arguments.command == "subsample":
            subsample_datasets(settings)
            return 0

        drift = check_datasets(settings)
        for message in drift:
            logger.warning("Drift: %s", message)
        if drift:
            logger.warning(
                "%d dataset(s) differ from the manifest; rerun `just subsample` "
                "if the change is intended.",
                len(drift),
            )
            return 1
        logger.info("Every dataset matches the manifest.")
        return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="packagename-data",
        description="Sample the raw datasets per region, or check them against the manifest.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser(
        "subsample",
        help="draw one sample per region and rewrite data/manifest.yaml",
    )
    commands.add_parser(
        "check",
        help="report datasets that changed, went missing or are new since the manifest",
    )
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
