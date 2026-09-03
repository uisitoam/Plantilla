"""Tabular IO with format dispatch and atomic writes."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

__all__ = ["read_table", "write_table"]

logger = logging.getLogger(__name__)

_PARQUET = frozenset({".parquet", ".pq"})
_CSV = frozenset({".csv", ".tsv"})
_JSONL = frozenset({".jsonl", ".ndjson"})
SUPPORTED_SUFFIXES = _PARQUET | _CSV | _JSONL


def read_table(path: str | Path, **kwargs: Any) -> pd.DataFrame:
    """Read a dataframe, choosing the reader from the file extension.

    Args:
        path: File to read.
        **kwargs: Passed to the underlying pandas reader.

    Returns:
        The loaded dataframe.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the extension is not supported.
    """
    source = Path(path)
    if not source.exists():
        raise FileNotFoundError(f"No such table: {source}")

    suffix = source.suffix.lower()
    if suffix in _PARQUET:
        return pd.read_parquet(source, **kwargs)
    if suffix in _CSV:
        separator = "\t" if suffix == ".tsv" else ","
        return pd.read_csv(source, sep=separator, **kwargs)
    if suffix in _JSONL:
        return pd.read_json(source, lines=True, **kwargs)
    raise ValueError(_unsupported(suffix))


def write_table(df: pd.DataFrame, path: str | Path, **kwargs: Any) -> Path:
    """Write a dataframe atomically, creating parent directories as needed.

    Args:
        df: Dataframe to write.
        path: Destination file; the writer is chosen from its extension.
        **kwargs: Passed to the underlying pandas writer.

    Returns:
        The destination path.

    Raises:
        ValueError: If the extension is not supported.
    """
    destination = Path(path)
    suffix = destination.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(_unsupported(suffix))

    destination.parent.mkdir(parents=True, exist_ok=True)
    # Same directory as the destination, so the final rename stays on one
    # filesystem and is therefore atomic.
    staging = destination.with_name(f".{destination.name}.tmp")
    try:
        if suffix in _PARQUET:
            df.to_parquet(staging, index=False, **kwargs)
        elif suffix in _CSV:
            df.to_csv(staging, index=False, sep="\t" if suffix == ".tsv" else ",", **kwargs)
        else:
            df.to_json(staging, orient="records", lines=True, **kwargs)
        staging.replace(destination)
    finally:
        staging.unlink(missing_ok=True)

    logger.debug("Wrote %d row(s) to %s", len(df), destination)
    return destination


def _unsupported(suffix: str) -> str:
    return f"Unsupported table format {suffix!r}; expected one of {sorted(SUPPORTED_SUFFIXES)}."
