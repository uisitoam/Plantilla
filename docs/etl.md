# ETL

The medallion layout is four directories:

| Layer | Contents |
|---|---|
| `data/raw` | Original data, treated as immutable |
| `data/bronze` | Ingested, not yet transformed |
| `data/silver` | Cleaned, typed, normalised |
| `data/gold` | Ready for modelling |

Plus a fifth, `data/sample`, which is not a layer: it holds one small sample per
region of the raw data, committed to Git, and it is what makes the pipeline
runnable on a machine that does not hold the full datasets. See
[Data samples and the manifest](#data-samples-and-the-manifest).

Two rules do the work a heavier tool would:

- **A stage always does its work.** Deciding whether the work is worth doing is
  the caller's business, not the code's. The caller here is a human running
  `just etl`; nothing skips stages, so nothing can skip a stage it should have
  run.
- **Whatever decides an output lives in the versioned config.** A parameter as a
  literal in the code is a change `git log` cannot explain. The `etl` section of
  `configs/config.yaml` is where those values belong.

## The shape of a stage

A plain function registered under a name:

```python
# src/packagename/etl/pipeline.py
from packagename.config import Settings
from packagename.etl.io import read_table, write_table
from packagename.etl.registry import stage


@stage("aggregate_measurements")
def aggregate_measurements(settings: Settings) -> None:
    measurements = read_table(settings.paths.raw / "measurements.csv")
    kept = measurements[measurements["value"] > settings.etl.threshold]
    write_table(kept, settings.paths.silver / "measurements.parquet")
```

Registration order is the pipeline order: `packagename-stage --all` runs the
stages in the order their module registers them, so a producer is declared
before its consumer. One process per stage, so no stage can depend on something
the previous one left in memory.

## Running it

```bash
just etl                                    # every stage, in registration order
uv run packagename-stage --list             # the names
uv run packagename-stage aggregate_measurements   # one stage, for debugging
```

Note what the command does *not* accept: Hydra-style overrides. A stage reads
its parameters from `configs/config.yaml` and nowhere else, because a value
injected on the command line would leave no trace in `git log`. To change a
parameter, edit the YAML and rerun. `packagename-train` remains a Hydra
entrypoint, with overrides and `--multirun`, because experiments are not stages.

## Raw data does not come from a stage

Real raw data arrives from outside the project, one directory per region under
`data/raw/`:

```
data/raw/
├── medsea/        # one or more large, homogeneous datasets
├── canarias/
└── golfo_bizkaia/
```

The whole tree is git-ignored: the datasets are too large for Git and their
source of truth is wherever they were downloaded or generated. What Git tracks
about them is the manifest (below).

The example pipeline that ships is the exception, deliberately: its first stage
*synthesises* its raw data directly under `data/raw/`, so a fresh clone can run
`just etl` end to end with nothing to download. Replace both stages with your
own.

## Data samples and the manifest

The full datasets live only on the machine that runs the real workloads. For
everything else — a local test run, a colleague's clone, CI — the project
carries a small stand-in:

```bash
just subsample    # packagename-data subsample
just check-data   # packagename-data check
```

`subsample` does three things in one pass, so the pieces can never describe
different moments:

1. **Discovers the regions** — the subdirectories of `data/raw/` holding at
   least one file in a format the sampler understands (the tabular formats of
   `read_table`, plus `.nc` through xarray).
2. **Draws one sample per region** — `sample.rows` observations from one dataset
   of the region, seeded with `sample.seed`, written to
   `data/sample/<region>_sample.<ext>`. The source file is stable across runs:
   the one the previous manifest recorded while it exists, otherwise the
   region's first file by name. Both parameters live in `configs/config.yaml`;
   change the seed and every committed sample is stale.
3. **Fingerprints every dataset** — sha256, size and mtime of every file of
   every region, into `data/manifest.yaml`. Hashing is incremental: a file
   whose size and mtime match the previous manifest keeps its recorded hash, so
   re-running over terabytes costs seconds, not half an hour.

`check` compares the manifest against whatever is on disk *now* and exits
non-zero when a file changed, went missing, or is new — the "your samples are
stale" warning. It is cheap on purpose: size and mtime are checked first and
only a file whose pair moved is rehashed, because a check that takes half an
hour is a check nobody runs. Two cases are deliberately *not* errors: a machine
with no raw data at all (a fresh clone has nothing to check), and a manifest
that does not exist yet (run `just subsample` first).

Granularity note: one sample per region is enough to prove the code runs, which
is all the samples are for. If the datasets of a region ever stop being
homogeneous — different variables or sampling across years — that is the moment
to sample from more than one file, not before.

## Adding a stage

1. Write the function in `src/packagename/etl/pipeline.py` and decorate it with
   `@stage("its_name")`. Take every path and every parameter from `settings`,
   and register producers before their consumers.
2. Add any parameter it needs to `configs/config.yaml` and to `EtlSettings` in
   `src/packagename/config.py` (see [configuration.md](configuration.md)).
3. `just etl`, and commit the code and the config together.

## Reading and writing tables

```python
from packagename.etl import read_table, write_table

frame = read_table(settings.paths.bronze / "sales.parquet")
write_table(frame, settings.paths.silver / "sales.parquet")
```

The reader and writer are chosen from the extension: `.parquet`/`.pq`,
`.csv`/`.tsv`, `.jsonl`/`.ndjson`. Anything else is a `ValueError`. Extra keyword
arguments go to the underlying pandas function.

`write_table` creates parent directories and **writes atomically**: to a temporary
file in the destination directory, renamed into place at the end, with the
temporary removed even if the write raises. For anything that is not a dataframe,
write it yourself — and keep the same pattern, as the NetCDF sampler in
`packagename.data.sample` does.

One caveat worth stating plainly: rename-atomicity protects against an interrupted
*process*. It is not a guarantee against a power cut or a network mount
disappearing mid-write, because nothing here calls `fsync`.

## Determinism

Seed anything random from `settings.random_seed` (stages) or `settings.sample.seed`
(the samples). An output whose bytes change on every run makes every change
detection downstream — the manifest's fingerprints included — meaningless:

```python
generator = np.random.default_rng(settings.random_seed)
```

If a stage genuinely cannot be deterministic — it reads a clock, or a service —
say so, and expect its consumers to rerun.

## Testing a stage

The transformations are plain functions, so what is worth checking needs no data:

```python
def test_aggregate_summarises_per_station(settings):
    generate_measurements(settings)
    aggregate_measurements(settings)

    summary = read_table(settings.paths.silver / "measurements.parquet")
    assert (summary["mean_value"] > settings.etl.threshold).all()
```

The `settings` fixture in `tests/conftest.py` is rooted at `tmp_path` with tracking
disabled, so a test writes into its own directory and never touches `data/`.
`tests/test_sample.py` shows the same pattern for the sampler: build a region in
`tmp_path`, subsample it, and assert against the manifest.
