# PACKAGENAME

Template for Machine Learning projects with a medallion ETL pipeline.

Configuration is typed and validated, every path is absolute, experiments are
tracked with provenance, and the quality gates run before anything reaches CI.

## Quickstart

Requires Python 3.12+, [uv](https://docs.astral.sh/uv/getting-started/installation/)
and [just](https://just.systems/man/en/packages.html) as the command runner.

```bash
just setup   # install dependencies, create .env
just hooks   # install the git hooks
just check   # lint, type check, dependency check, tests
```

Then run the pipeline or a training job:

```bash
just etl                                    # every stage, in registration order
uv run packagename-train
uv run packagename-train --multirun random_seed=1,2,3
```

The pipeline works immediately in a fresh clone, with no data to download: the
example stages synthesise their own inputs.

No credentials are needed for any of that: the shipped config records runs
offline, so a fresh clone works before you have a W&B account. Set
`WANDB_API_KEY` in `.env` and `wandb.mode=online` when you want them uploaded,
or push the offline ones later with `wandb sync`.

This README is the tour. [ARCHITECTURE.md](ARCHITECTURE.md) is how the pieces fit
together. [`docs/`](docs/README.md) is the reference:
[configuration](docs/configuration.md), [ETL and data samples](docs/etl.md),
[tracking](docs/tracking.md), [logging](docs/logging.md),
[figures](docs/viz.md), the [development workflow](docs/workflow.md), and
[renaming the package](docs/renaming-the-package.md).

## Structure

```
├── configs/
│   └── config.yaml          # Single source of truth: settings, params, Hydra
├── data/
│   ├── raw/                 # Original data (immutable); local only, git-ignored
│   ├── bronze/              # Ingested, untransformed
│   ├── silver/              # Cleaned and normalised
│   ├── gold/                # Ready for modelling
│   ├── sample/              # One small seeded sample per region (committed)
│   └── manifest.yaml        # Fingerprints of the full datasets (committed)
├── models/                  # Trained model artifacts
├── notebooks/               # Exploration and prototypes
├── reports/figures/         # Generated plots
├── src/packagename/
│   ├── config.py            # Typed settings (YAML + .env + env vars)
│   ├── log.py               # Centralised logging setup
│   ├── seed.py              # set_seed for Python, NumPy, torch, TensorFlow
│   ├── tracking.py          # W&B: tracker, context manager, @track decorator
│   ├── cli/                 # Entrypoints: stages, data samples, Hydra training
│   ├── etl/                 # Stage implementations, registry, tabular IO
│   ├── data/                # Dataset access, subsampling and the manifest
│   ├── features/            # Feature engineering
│   ├── models/              # Training and inference
│   └── viz/                 # Matplotlib style and helpers
├── docs/                    # Reference documentation
└── tests/
```

## Tools

| Tool | Purpose |
|---|---|
| [uv](https://docs.astral.sh/uv/) | Dependencies and virtual environment |
| [just](https://just.systems/) | Command runner: every project command lives in `justfile` |
| [Hydra](https://hydra.cc/) | Config composition, CLI overrides, sweeps |
| [Pydantic](https://docs.pydantic.dev/) | Config validation and typing |
| [W&B](https://wandb.ai/) | Experiment tracking |
| [Ruff](https://docs.astral.sh/ruff/) | Linting and formatting |
| [ty](https://docs.astral.sh/ty/) | Static type checking |
| [pytest](https://docs.pytest.org/) | Testing, with coverage gate |
| [pre-commit](https://pre-commit.com/) | Quality gates on commit and push |

## Configuration

Everything lives in `configs/config.yaml`. Values are resolved from several
sources; **later sources win**:

1. Field defaults in `src/packagename/config.py`
2. `configs/config.yaml`
3. `.env`
4. Environment variables
5. Values passed explicitly: arguments in code, or a command-line override

```bash
# Environment variables are prefixed and use `__` to enter a section
PACKAGENAME_RANDOM_SEED=7 uv run packagename-train
PACKAGENAME_WANDB__PROJECT=other uv run packagename-train

# A command-line override outranks all of the above
uv run packagename-train random_seed=7 wandb.mode=online paths.root=/scratch/run1
```

The order is the same whether the settings are built in a notebook or by an
entrypoint. That takes some care on the Hydra path, because Hydra hands over the
YAML file and the typed overrides already merged into one mapping: passing that
along wholesale would let the YAML's own defaults outrank the environment, and
`.env` would go quietly dead for the commands you actually run. The two are
therefore separated — see [docs/configuration.md](docs/configuration.md).

Unknown or misspelled keys are an error rather than a silently ignored line, in
the YAML file, in a command-line override and in code. Note also that Hydra can
only override a key that already exists, which is why `configs/config.yaml`
spells out every setting, including the ones whose value is `null`.

Secrets never pass through the config object. `WANDB_API_KEY` goes in `.env` and
is read by W&B directly, so no settings field can ever hold a credential.

### Paths are always absolute

`Settings.paths` anchors every directory to the repository root, which is derived
from the package location rather than the working directory:

```python
from packagename import get_settings

paths = get_settings().paths
paths.gold      # /abs/path/to/repo/data/gold
paths.layer("silver")
paths.ensure()  # create every directory
```

This is why `hydra.job.chdir` can safely stay at its default of `false`, and why
`savefig(fig, "loss.png")` lands in `reports/figures/` from a notebook, a script
or a Hydra job alike.

Entrypoints bind the settings they were given, so a `paths.root=/scratch`
override on the command line also reaches helpers that resolve relative paths
through `get_settings()`. To get the same behaviour in a script, wrap the work in
`use_settings` — see [docs/configuration.md](docs/configuration.md).

## Experiment tracking

Every run records the git commit, the branch, whether the working tree was dirty,
and the fully resolved config. A dirty tree also adds a `dirty` tag, so runs that
cannot be reproduced are easy to filter out.

Three ways to use it, from most to least explicit:

```python
from packagename.tracking import ExperimentTracker, active_tracker, start_run, track

# 1. Context manager: guarantees the run closes, and marks failures as failed
with start_run("baseline", tags=["xgboost"]) as tracker:
    tracker.log_params({"n_estimators": 300})
    tracker.log_metrics({"val/rmse": rmse})
    tracker.log_summary({"best/val_rmse": rmse})
    tracker.log_figure(fig, "residuals", save_as="residuals.png")
    tracker.log_model(paths.models / "model.joblib")

# 2. Decorator: "this function is one run". Declare `tracker` with a default and
#    it is injected; the run is named after the function.
@track(tags=["xgboost"])
def train(settings, tracker: ExperimentTracker | None = None) -> float:
    ...

# 3. From deep in a call stack, with nothing threaded through the signatures
def compute_metrics(y_true, y_pred) -> None:
    if (tracker := active_tracker()) is not None:
        tracker.log_metrics({"val/f1": f1})
```

Set `wandb.mode` to `offline` to work without a network, or `disabled` to turn
tracking into a no-op without touching the code.

## ETL and data samples

A stage is a plain function that always does its work, registered under a name
and run one per process:

```python
# src/packagename/etl/pipeline.py
@stage("aggregate_measurements")
def aggregate_measurements(settings: Settings) -> None:
    measurements = read_table(settings.paths.raw / "measurements.csv")
    kept = measurements[measurements["value"] > settings.etl.threshold]
    write_table(kept, settings.paths.silver / "measurements.parquet")
```

`just etl` runs every stage in registration order; `uv run packagename-stage
<name>` runs one. Anything that decides what a stage writes lives in
`configs/config.yaml`, so a parameter change is a commit, visible in `git log`.

Large datasets never enter Git: the full data stays on the machine that runs the
real workloads. What Git carries instead is one small seeded **sample per
region** under `data/sample/` — enough for local test runs to exercise the same
code — plus `data/manifest.yaml`, a sha256 fingerprint of every full dataset:

```bash
just subsample    # draw the samples and refresh the manifest
just check-data   # warn if a full dataset changed, went missing or is new
```

`check-data` is cheap: it only rehashes a file whose size or mtime moved, and on
a machine without the raw data — a fresh clone, CI — it has nothing to check and
says so. See [docs/etl.md](docs/etl.md).

## Commands

`just` on its own lists every recipe. [docs/workflow.md](docs/workflow.md)
explains when to reach for which.

```bash
just setup && just hooks   # once, after cloning
just test-fast             # the tight loop while writing code
just check                 # everything CI runs

just etl                   # run the pipeline: every stage, in order
just subsample             # regenerate the per-region samples and the manifest
just check-data            # warn if a full dataset drifted from the manifest
```

## Quality gates

| When | What runs |
|---|---|
| commit | whitespace, YAML/TOML/JSON, large files, ruff, secret scan, typos, actionlint, `uv.lock` freshness, notebook output stripping |
| commit message | Conventional Commits |
| push | ty, deptry, the test suite except anything marked `slow` |
| CI | the commit hooks over *all* files, then ty, deptry, the full suite with an 85% coverage floor on Python 3.12 and 3.13, and a run of the whole example pipeline from scratch |
| weekly, and on any lock change | `pip-audit` over the locked runtime dependencies |

CI runs the same hooks a commit does, through `pre-commit run --all-files`,
rather than a hand-copied subset that can quietly fall behind. Hook revisions
are pinned so everyone gets the same linters, and `just update-hooks` bumps them
as a reviewable commit. Ruff is the exception: it runs through `uv run`, so its
version lives only in `uv.lock` and cannot disagree with `just lint`.

Actions are pinned to commit SHAs, which a tag takeover cannot repoint;
Dependabot moves those pins monthly.

### Type checking

Enforcement is split between two tools. Ruff's `ANN` rules require the
annotations to be there; `ty` checks that they are consistent. That division
matters because `ty` has no strict mode yet, so on its own it would not complain
about an unannotated function.

`ty` is in beta and its diagnostics can change between any two releases, so the
version range in `pyproject.toml` is deliberately narrow — bump it deliberately
rather than letting CI break on an unrelated push. Suppressions use
`# ty: ignore[rule-name]`; `respect-type-ignore-comments` is off so that a stray
`# type: ignore` from another tool cannot silence anything, and
`blanket-ignore-comment` forces every suppression to name the rule it silences.

## Releases and versioning

[Release Please](https://github.com/googleapis/release-please) automates releases
and `CHANGELOG.md`:

1. Commit using Conventional Commits
2. Release Please opens a PR with the new version and changelog
3. Merging it creates the tag and the GitHub Release

Only `feat:` and `fix:` bump the version (`MINOR` and `PATCH`). `feat!:` or
`fix!:` bump `MAJOR`.

```
<type>(scope): description

feat:     New feature
fix:      Bug fix
refactor: Restructuring without behaviour change
docs:     Documentation only
test:     Add or fix tests
build:    Build system, CI, dependencies
chore:    Maintenance
perf:     Performance improvement
ops:      Infrastructure or deployment
revert:   Revert a previous commit
```

## Using this template for a new project

1. **Enable GitHub Actions permissions** so Release Please can open PRs:
   `Settings → Actions → General → Workflow permissions` → "Read and write
   permissions", and enable "Allow GitHub Actions to create and approve pull
   requests".
2. **Rename the package**: `src/packagename/` is an importable module, so this is
   more than renaming a directory. Follow
   [docs/renaming-the-package.md](docs/renaming-the-package.md).
3. **Run** `just setup && just hooks`. This copies `.env.example` to `.env`;
   fill in `WANDB_API_KEY` and set `wandb.mode: online` whenever you want runs
   uploaded, which is not needed to get started.
4. **Replace the licence.** `LICENSE` is MIT with a placeholder copyright
   holder, which is a default, not a recommendation. Change both it and the
   `license` field in `pyproject.toml` to whatever your situation calls for, and
   drop the `Private :: Do Not Upload` classifier if you intend to publish.
5. **Declare your ETL stages** in `src/packagename/etl/pipeline.py`, replacing
   the two example stages, and put your training code in
   `src/packagename/models/`.
6. **Lay out your raw data** as one directory per region under `data/raw/` and
   run `just subsample`, so the committed samples and the manifest describe it.

## Licence

[MIT](LICENSE).
