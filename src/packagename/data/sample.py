"""Per-region subsamples of the raw data, plus a manifest of the full datasets.

The full datasets are too large for Git, so they live only on the machine that
runs the real workloads. What Git carries instead is two small things:

* one **sample** per region under ``paths.sample`` -- a fixed-seed draw of
  ``sample.rows`` observations out of one dataset of the region, enough for
  local test runs to exercise the same code the full run will;
* one **manifest** at ``data/manifest.yaml`` -- a fingerprint (sha256, size,
  mtime) of every file of every region, written at sampling time.

The split of labour is deliberate. ``subsample_datasets`` regenerates the
samples and refreshes the manifest in one pass, so the two can never describe
different moments. ``check_datasets`` compares the manifest against whatever is
on disk *now* and reports the files that changed since, which is how a stale
sample is noticed before it quietly drives a wrong conclusion.

Hashing is incremental: a file whose size and mtime match the manifest keeps
its recorded hash, because re-reading terabytes to confirm "nothing moved" is
not a check anyone will run often -- and a check nobody runs is worse than none.
A changed file is rehashed in full; size and mtime together are only ever used
to *skip* work, never to declare a match.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import numpy as np
from omegaconf import OmegaConf

from packagename.config import Settings
from packagename.etl.io import SUPPORTED_SUFFIXES as TABLE_SUFFIXES
from packagename.etl.io import read_table, write_table
from packagename.log import get_logger

__all__ = [
    "check_datasets",
    "discover_regions",
    "manifest_path",
    "subsample_datasets",
]

logger = get_logger(__name__)

#: NetCDF is sampled through xarray, which is imported lazily inside the sampler:
#: it lives in the ``analysis`` dependency group, and importing it here would make
#: ``import packagename`` pay for it.
_NETCDF_SUFFIXES = frozenset({".nc"})

_SAMPLEABLE_SUFFIXES = TABLE_SUFFIXES | _NETCDF_SUFFIXES

#: Read size of the hashing loop. Large enough that hashing is bound by the disk,
#: not by Python.
_HASH_CHUNK = 8 * 1024 * 1024


def manifest_path(settings: Settings) -> Path:
    """Return the path of the manifest: ``data/manifest.yaml`` by default."""
    return settings.paths.raw.parent / "manifest.yaml"


def discover_regions(raw: Path) -> dict[str, list[Path]]:
    """Map each region of the raw layer to its sampleable files, sorted by name.

    A region is a direct subdirectory of ``raw`` containing at least one file
    whose format the sampler understands. Empty or file-less subdirectories are
    skipped, and so are files directly under ``raw``: the project layout is one
    directory per region, and a stray file at the top is a layout mistake worth
    noticing rather than a region of its own.

    Args:
        raw: The raw layer directory.

    Returns:
        Region names to sorted file lists. Empty if the raw layer holds no
        regions -- e.g. on a fresh clone, where the full data is absent.
    """
    if not raw.is_dir():
        return {}
    regions: dict[str, list[Path]] = {}
    for directory in sorted(raw.iterdir()):
        if not directory.is_dir():
            continue
        files = sorted(
            entry
            for entry in directory.iterdir()
            if entry.is_file() and entry.suffix.lower() in _SAMPLEABLE_SUFFIXES
        )
        if files:
            regions[directory.name] = files
    return regions


def subsample_datasets(settings: Settings) -> Path:
    """Draw one sample per region and refresh the manifest.

    The source of a region's sample is stable across runs: the file recorded in
    the previous manifest while it still exists, otherwise the region's first
    file by name. Picking a different source each run would change the committed
    samples for no reason.

    Args:
        settings: Reads ``paths.raw``, ``paths.sample`` and the ``sample``
            section (rows and seed).

    Returns:
        The path of the manifest written.
    """
    regions = discover_regions(settings.paths.raw)
    root = settings.paths.root
    previous = _load_manifest(manifest_path(settings))
    manifest: dict[str, Any] = {
        "seed": settings.sample.seed,
        "rows": settings.sample.rows,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "regions": {},
    }

    if not regions:
        logger.warning(
            "No regions found under %s; writing an empty manifest. "
            "This is expected on a fresh clone, where the full data is absent.",
            settings.paths.raw,
        )

    for region, files in regions.items():
        source = _choose_source(region, files, previous, root)
        sample_file = settings.paths.sample / f"{region}_sample{source.suffix.lower()}"
        drawn = _draw_sample(source, sample_file, settings)
        logger.info(
            "Sampled %d observation(s) from %s into %s",
            drawn,
            source.relative_to(root),
            sample_file.relative_to(root),
        )
        manifest["regions"][region] = {
            "source": source.relative_to(root).as_posix(),
            "sample": sample_file.relative_to(root).as_posix(),
            "files": {
                file.relative_to(root).as_posix(): _fingerprint(file, region, previous, root)
                for file in files
            },
        }

    destination = _write_manifest(manifest, manifest_path(settings))
    logger.info("Wrote the manifest of %d region(s) to %s", len(regions), destination)
    return destination


def check_datasets(settings: Settings) -> list[str]:
    """Compare the manifest against the datasets on disk.

    Args:
        settings: Reads ``paths.raw`` and the manifest next to it.

    Returns:
        One message per drift found: a file changed, went missing, or is new
        since the manifest was written. An empty list means everything matches.
        A clone without the raw data -- where there is nothing to check -- also
        returns an empty list, after logging why.
    """
    manifest_file = manifest_path(settings)
    manifest = _load_manifest(manifest_file)
    if manifest is None:
        logger.warning("No manifest at %s; run `packagename-data subsample` first.", manifest_file)
        return []

    regions = discover_regions(settings.paths.raw)
    recorded = manifest.get("regions", {})
    if not regions and recorded:
        logger.info(
            "No datasets found under %s; nothing to check on this machine.",
            settings.paths.raw,
        )
        return []

    root = settings.paths.root
    drift: list[str] = []
    for region, files in regions.items():
        known = recorded.get(region, {}).get("files", {})
        seen = {file.relative_to(root).as_posix() for file in files}
        for file in files:
            name = file.relative_to(root).as_posix()
            entry = known.get(name)
            if entry is None:
                drift.append(f"{name}: new since the manifest was written")
            elif not _matches(file, entry):
                drift.append(f"{name}: changed since the manifest was written")
        for name in sorted(set(known) - seen):
            drift.append(f"{name}: missing from disk")
    for region in sorted(set(recorded) - set(regions)):
        drift.append(f"{region}: whole region missing from disk")
    return drift


def _choose_source(
    region: str, files: list[Path], previous: dict[str, Any] | None, root: Path
) -> Path:
    """Pick the dataset a region's sample is drawn from.

    The file the previous manifest recorded wins while it still exists, so
    re-running the sampler does not move the committed samples around.
    """
    recorded = (previous or {}).get("regions", {}).get(region, {}).get("source")
    if recorded is not None:
        candidate = root / recorded
        if candidate in files:
            return candidate
        logger.warning(
            "The recorded source %s no longer exists; sampling from %s instead.",
            recorded,
            files[0].relative_to(root),
        )
    return files[0]


def _draw_sample(source: Path, destination: Path, settings: Settings) -> int:
    """Write ``sample.rows`` seeded observations of ``source`` to ``destination``.

    Returns the number of observations written, which is smaller than
    ``sample.rows`` when the source itself is smaller.
    """
    rows = settings.sample.rows
    seed = settings.sample.seed
    if source.suffix.lower() in _NETCDF_SUFFIXES:
        return _draw_netcdf(source, destination, rows, seed)
    frame = read_table(source)
    if len(frame) > rows:
        frame = frame.sample(n=rows, random_state=seed).sort_index()
    write_table(frame, destination)
    return len(frame)


def _draw_netcdf(source: Path, destination: Path, rows: int, seed: int) -> int:
    """Sample a NetCDF along its time dimension, or its first dimension."""
    import xarray as xr

    with xr.open_dataset(source) as dataset:
        dimension = "time" if "time" in dataset.sizes else next(iter(dataset.sizes))
        length = min(rows, dataset.sizes[dimension])
        chooser = np.random.default_rng(seed)
        indices = np.sort(chooser.choice(dataset.sizes[dimension], size=length, replace=False))
        sampled = dataset.isel({dimension: indices})
        # The same temp-and-rename pattern as write_table: an interrupted write
        # must never leave a half-written file that looks like a sample.
        destination.parent.mkdir(parents=True, exist_ok=True)
        staging = destination.with_name(f".{destination.name}.tmp{destination.suffix}")
        try:
            sampled.to_netcdf(staging)
            staging.replace(destination)
        finally:
            staging.unlink(missing_ok=True)
    return length


def _fingerprint(
    file: Path, region: str, previous: dict[str, Any] | None, root: Path
) -> dict[str, Any]:
    """Return the manifest entry of one file, rehashing only when it moved.

    A file whose size and mtime match the previous manifest keeps its recorded
    hash: that pair is enough to *skip* re-reading terabytes, though never to
    declare a match -- ``check_datasets`` rehashes anything whose pair differs.
    """
    stat = file.stat()
    name = file.relative_to(root).as_posix()
    recorded = (previous or {}).get("regions", {}).get(region, {}).get("files", {}).get(name)
    if (
        recorded is not None
        and recorded.get("size_bytes") == stat.st_size
        and recorded.get("mtime") == stat.st_mtime
    ):
        return dict(recorded)
    return {"sha256": _sha256(file), "size_bytes": stat.st_size, "mtime": stat.st_mtime}


def _matches(file: Path, entry: dict[str, Any]) -> bool:
    """Decide whether a file still matches its manifest entry.

    Size and mtime differing is only a hint: both change on an innocent ``cp``
    or ``touch``. The hash is what decides, and it is recomputed whenever the
    cheap pair disagrees.
    """
    stat = file.stat()
    if entry.get("size_bytes") == stat.st_size and entry.get("mtime") == stat.st_mtime:
        return True
    if entry.get("size_bytes") != stat.st_size:
        return False
    return bool(entry.get("sha256")) and _sha256(file) == entry["sha256"]


def _sha256(file: Path) -> str:
    digest = hashlib.sha256()
    with file.open("rb") as stream:
        for chunk in iter(lambda: stream.read(_HASH_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_manifest(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    loaded = OmegaConf.to_container(OmegaConf.load(path), resolve=True)
    if not isinstance(loaded, dict):
        raise ValueError(f"The manifest at {path} is not a mapping; regenerate it.")
    # OmegaConf types the keys of a loaded mapping as broadly as YAML allows;
    # this file is written by _write_manifest and always has string keys.
    return cast("dict[str, Any]", loaded)


def _write_manifest(manifest: dict[str, Any], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(f".{path.name}.tmp")
    try:
        OmegaConf.save(OmegaConf.create(manifest), staging)
        staging.replace(path)
    finally:
        staging.unlink(missing_ok=True)
    return path
