"""Dataset access: downloading, loading and splitting.

This layer reads from the medallion directories in ``Settings.paths`` and returns
in-memory datasets. Transformations between layers belong in
:mod:`packagename.etl`, not here. It also owns the per-region subsampling of the
raw layer (:mod:`packagename.data.sample`), which is dataset management rather
than a transformation: the samples under ``paths.sample`` are what local test
runs consume, and the manifest next to them is how a stale one is noticed.
"""

from packagename.data.sample import (
    check_datasets,
    discover_regions,
    manifest_path,
    subsample_datasets,
)

__all__ = [
    "check_datasets",
    "discover_regions",
    "manifest_path",
    "subsample_datasets",
]
