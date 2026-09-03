# Experiment tracking

Runs are tracked with [Weights & Biases](https://wandb.ai/) through
`implacost.tracking`. Going through this module rather than calling `wandb`
directly keeps the path conventions in one place, makes disabled runs a no-op
without `if` statements scattered through the training code, and leaves a single
seam to replace if the backend ever changes.

## Setup

Nothing is needed to get started: the shipped config records runs **offline**, so
a fresh clone runs without an account, without credentials and without a network.
That is deliberate — a template whose first command blocks on a login prompt is a
template nobody gets past.

When you do want runs uploaded, put your key in `.env` and switch the mode:

```
WANDB_API_KEY=...          # from https://wandb.ai/authorize
IMPLACOST_WANDB__MODE=online
```

The key never passes through `Settings`; W&B reads it from the environment
itself. Offline runs are not lost either — `wandb sync wandb/offline-run-…`
uploads them after the fact. Everything else is configuration:

```yaml
wandb:
  project: implacost
  entity: null        # your user or team; null uses the account default
  mode: offline       # online | offline | disabled
  group: null         # collects related runs
  job_type: null      # this run's role within its group
  tags: []
  save_code: true
  run_dir: null       # where W&B writes locally; null means the repository root
```

`mode: disabled` makes tracking a complete no-op, which is what the test suite
uses. Any of these can be set per invocation:

```bash
uv run implacost-train wandb.mode=online wandb.group=seed-sweep
```

Every key is spelled out, `null` values included, because Hydra can only override
a key that already exists in the composed config.

## Three ways to open a run

All three sit on the same core; pick by how much control you want.

### 1. `start_run` — a context manager

The explicit option, and what the shipped `implacost-train` uses.

```python
from implacost.tracking import start_run

with start_run("baseline", tags=["xgboost"], job_type="train") as tracker:
    tracker.log_params({"n_estimators": 300, "max_depth": 6})
    tracker.log_metrics({"train/loss": loss, "val/rmse": rmse})
    tracker.log_summary({"best/val_rmse": rmse})
    tracker.log_model(settings.paths.models / "model.joblib")
```

The run is always closed, and a run that raises is finished with a non-zero exit
code — so a crashed experiment shows up as *failed* in the UI rather than merely
unfinished, which is the difference between noticing and not noticing.

Useful arguments: `settings` (defaults to the process-wide settings), `config`
(extra values merged over the settings), `tags`, `group`, `job_type`, `notes`.
Anything else is passed straight to `wandb.init`.

### 2. `@track` — a decorator

For the common case of "this function is one run".

```python
from implacost.tracking import ExperimentTracker, track

@track(tags=["xgboost"])
def train(settings: Settings, tracker: ExperimentTracker | None = None) -> float:
    assert tracker is not None
    tracker.log_params({"n_estimators": 300})
    tracker.log_metrics({"val/rmse": rmse})
    return rmse
```

Two rules:

- **Always call the decorator**, even with no arguments: `@track()`, not `@track`.
- If you declare a `tracker` parameter it is injected, and it **must have a
  default** (`tracker: ExperimentTracker | None = None`). Otherwise the decorated
  function looks to callers and to the type checker like it needs an argument that
  the decorator supplies. Forgetting the default raises a `TypeError` explaining
  this at decoration time, not at the first call.

The run is named after the function unless you pass `name=`. Any other keyword
goes to `start_run`.

### 3. `active_tracker` — from anywhere in the stack

When the code that computes a metric is three calls below the code that opened
the run, threading a tracker through every signature is worse than the problem it
solves.

```python
from implacost.tracking import active_tracker

def evaluate(y_true, y_pred) -> dict[str, float]:
    scores = {"val/f1": f1_score(y_true, y_pred)}
    if (tracker := active_tracker()) is not None:
        tracker.log_metrics(scores)
    return scores
```

Returns `None` when no run is open, so the same function works in a unit test or a
notebook with no special casing.

One limit worth knowing: the active tracker lives in a `ContextVar`, so it does not
cross a process boundary. Each ETL stage runs as its own process, which means a
stage cannot log into a training run that opened elsewhere. If you
want per-stage metrics in W&B, the stage has to open its own run — and then
grouping them explicitly through `wandb.group` is what ties them together.

## What a tracker can log

```python
tracker.log_params({"n_estimators": 300})            # hyperparameters
tracker.log_metrics({"train/loss": 0.31}, step=epoch)  # time series
tracker.log_summary({"best/val_rmse": 0.42})         # final values, in the overview table
tracker.log_figure(fig, "residuals", save_as="residuals.png")
tracker.log_artifact(path, kind="dataset", aliases=["v2"])
tracker.log_model(path, metadata={"framework": "xgboost"})
```

Name metrics `train/loss`, `val/rmse` and so on: W&B groups them into panels by
the part before the slash. Both `log_params` and `log_metrics` take a `prefix=`
argument if it is easier to add the group at the call.

`log_metrics` accepts `step=` for an explicit step, and `commit=False` to
accumulate several calls into one step.

`log_figure` optionally writes a local copy too. A relative `save_as` lands in
`paths.figures`. The figure is closed afterwards unless you pass `close=False`,
which matters in a loop.

`log_artifact` versions a file or a whole directory; `kind` is typically
`dataset`, `model` or `report`. Logging a path that does not exist is a
`FileNotFoundError` rather than an empty artifact.

Also available: `tracker.run` (the underlying W&B run, for anything not wrapped),
`tracker.enabled`, `tracker.id`, `tracker.name`, `tracker.url`.

## Provenance

Every run records, without being asked:

| Key | Meaning |
|---|---|
| `git_commit` | Short hash of `HEAD` |
| `git_branch` | Current branch |
| `git_dirty` | Whether the working tree had uncommitted changes |
| the whole config | Every resolved setting, flattened to `wandb.project`-style keys |

A dirty tree also adds a `dirty` tag, so runs that cannot be reproduced are one
filter away in the UI. This is the point of recording `git_dirty` separately: a
commit hash alone is misleading, because checking that commit out will not
reproduce a run made with uncommitted changes.

If git is unavailable the fields are `"unknown"` rather than an exception — a
missing checkout should not break a training run.

## Grouping runs

`group` collects related runs, `job_type` says what each one is within its group:

```python
for fold in range(5):
    with start_run(f"fold-{fold}", group="cv-baseline", job_type="train") as tracker:
        ...
```

For a sweep, set the group on the command line so every run lands together:

```bash
uv run implacost-train --multirun random_seed=1,2,3 wandb.group=seed-sweep
```

## In tests

`tests/conftest.py` sets `WANDB_MODE=disabled` before anything imports W&B, and
redirects the W&B cache directories into `tmp_path`. So tracking code is
exercised by the suite but never reaches the network or writes outside the
temporary directory.

Two consequences when writing tests:

- In disabled mode W&B substitutes a no-op run that invents its own name, so
  asserting on what you *asked for* means looking at the call. The
  `wandb_init_spy` fixture records the keyword arguments passed to `wandb.init`.
  Note also that `tracker.name` falls back to the run id when W&B has not
  assigned a name, which it does not do offline.
- The no-op run does not implement everything a real run does. To check that
  something was logged, spy on the tracker method rather than reading it back off
  the run object.
