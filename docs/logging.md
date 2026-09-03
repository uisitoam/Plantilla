# Logging and seeding

Both are process-wide side effects configured from settings and applied once, at
startup, by `hydra_entrypoint`. You mostly consume them rather than set them up.

## Using the logger

One line at the top of a module, then use it:

```python
from implacost.log import get_logger

logger = get_logger(__name__)


def clean(df):
    logger.info("Cleaning %d row(s)", len(df))
    if df["amount"].isna().any():
        logger.warning("Dropping rows with a missing amount")
    logger.debug("Columns: %s", list(df.columns))
    return df.dropna(subset=["amount"])
```

`get_logger(__name__)` rather than a hand-written name: the module path is what
lets you turn the volume up on one subpackage without touching the rest.

**Pass values as arguments, not with an f-string.** `logger.debug("Rows: %s", df)`
does no formatting work when the level is above `DEBUG`; `logger.debug(f"Rows:
{df}")` formats the message every time, whether or not anyone will read it. On a
debug line inside a loop this is the difference between free and expensive.

Which level to use:

| Level | For |
|---|---|
| `DEBUG` | Detail useful while diagnosing, noise otherwise |
| `INFO` | What the program is doing: step started, N rows written |
| `WARNING` | Something surprising that did not stop the work |
| `ERROR` | An operation failed |

Use `logger.exception("…")` inside an `except` block rather than
`logger.error("…")`: it attaches the traceback, which is the part you will
actually want.

Never use `print` in library code. A print statement cannot be filtered by level,
carries no module or timestamp, and goes to stdout where it can corrupt piped
output.

## Configuration

```yaml
logging:
  level: INFO
  file: null   # e.g. "run.log" -> resolved under paths.logs
```

The full set of options is `level`, `format`, `datefmt`, `file` and
`quiet_loggers`, and all five are spelled out in `configs/config.yaml` — which is
what makes them overridable from the command line, since Hydra can only override
a key that already exists. Setting `file` adds a rotating file handler (10 MB,
3 backups) alongside the console one; a relative filename is resolved under
`paths.logs`, so the log lands in the same place no matter where you launched
from.

`quiet_loggers` holds libraries demoted to `WARNING` — by default `matplotlib`,
`urllib3`, `botocore` and `fsspec`, all of which are chatty at `DEBUG` and rarely
about anything you asked for.

Output goes to **stderr**, so redirecting stdout to capture a program's real
output does not swallow the logs.

Change the level per invocation:

```bash
uv run packagename-train logging.level=DEBUG
PACKAGENAME_LOGGING__LEVEL=DEBUG uv run packagename-train
uv run packagename-train logging.file=debug.log logging.level=DEBUG
```

ETL stages are the exception. `packagename-stage` takes no overrides — its
parameters have to be the ones in the versioned file — so raise the level for a
run through the config file or the environment instead:

```bash
PACKAGENAME_LOGGING__LEVEL=DEBUG just etl
```

That is safe because the log level cannot change what a stage writes, so letting
the environment steer it contradicts nothing.

## Setting it up outside an entrypoint

Entrypoints call `setup_logging` for you. In a notebook or a standalone script,
call it once yourself:

```python
from implacost.log import setup_logging

setup_logging()                  # from the process-wide settings
setup_logging(level="DEBUG")     # override just the level
setup_logging(settings)          # from a specific Settings object
```

It replaces the previous configuration rather than adding to it, so calling it
twice cannot duplicate log lines — which also means it overrides any handler a
framework installed earlier in the process.

Hydra's own job logging is disabled in `configs/config.yaml`
(`override hydra/job_logging: disabled`) so that there is exactly one owner of
logging configuration. If you re-enable it you will get every line twice.

## Seeding

`Settings.random_seed` does nothing on its own; `set_seed` applies it. Entrypoints
call it during startup, so a run already has its generators seeded before your
code begins.

```python
from implacost import set_seed

set_seed(42)
set_seed(42, deterministic=True)   # also disable non-deterministic GPU kernels
```

It seeds Python's `random`, NumPy's legacy global generator, and — only if they
are installed — PyTorch (including CUDA) and TensorFlow. It also exports
`PYTHONHASHSEED`. The return value is the seed, so you can log it in one
expression.

`deterministic=True` is opt-in because it makes results bit-reproducible at a
noticeable cost in throughput. Turn it on when you are chasing a discrepancy, not
by default.

Two limits worth knowing. First, seeding the *global* NumPy generator is what
libraries that call `np.random.*` internally need, but new code of your own is
better off with an explicit generator:

```python
rng = np.random.default_rng(settings.random_seed)
sample = rng.choice(len(df), size=100, replace=False)
```

Second, a seed alone does not buy reproducibility. Runs record `git_commit` and
`git_dirty` precisely because the code matters as much as the seed — see
[tracking.md](tracking.md).
