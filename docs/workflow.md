# Development workflow

## Once per machine

```bash
just setup   # install dependencies into .venv, copy .env.example to .env
just hooks   # install the pre-commit, commit-msg and pre-push hooks
```

Both need [just](https://just.systems/man/en/packages.html) and
[uv](https://docs.astral.sh/uv/getting-started/installation/) on the machine;
everything else installs itself from the lockfile.

`just hooks` matters more than it looks: without it none of the gates below run,
and the first thing you learn about a mistake is a red CI badge.

## The loop

```bash
git switch -c feat/ingest-waves

# write code, then:
just format      # ruff --fix and format, in place
just test-fast   # the quick tests
just check       # everything CI runs: lint, ty, deptry, full suite

git add -p
git commit -m "feat(etl): ingest the wave dataset into bronze"
git push -u origin feat/ingest-waves
gh pr create
```

`just check` before pushing is the habit worth building. It is the same set of
commands CI runs, so if it is green locally, CI has very little left to surprise
you with.

`just` with no arguments lists every recipe with a one-line description, read from
the comments in `justfile` itself so it cannot fall out of date. The ones worth
knowing by heart are `just test-fast` while writing, `just check` before pushing,
and `just etl` when the pipeline needs running.

## Running things

Every command goes through `uv run`, which uses the locked environment rather
than whatever happens to be active:

```bash
just etl                           # the ETL pipeline, every stage in order
uv run packagename-train wandb.mode=offline
uv run python -c "from packagename import get_settings; print(get_settings().paths.gold)"
uv run jupyter lab
```

## Working with data

The full datasets live only on the machine that runs the real workloads; Git
carries one seeded sample per region plus a manifest of fingerprints. That adds
one habit to the loop: when a dataset changes, refresh the samples *with* the
code change that needs them, in the same commit.

```bash
just check-data  # did any full dataset change, vanish or appear?
just subsample   # redraw the samples and rewrite the manifest
git add data/sample data/manifest.yaml
git commit -m "data: resample after the 2025 reanalysis arrived"
```

`just check-data` exits non-zero on drift, so it is safe to add to your own
routine before pushing. On a machine without the raw data — a fresh clone, CI —
it has nothing to check and says so, rather than failing.

## Dependencies

Always through `uv`, never by editing `pyproject.toml` by hand — the lockfile has
to move with it, and a hook will reject the commit if it does not:

```bash
uv add scikit-learn
uv add --group dev pytest-mock
uv remove scikit-learn
uv sync --upgrade            # refresh the lockfile
```

Commit `uv.lock` along with `pyproject.toml`. It is what makes CI and your machine
install the same versions.

`deptry` runs on push and catches the three ways a dependency list drifts: a
package imported but not declared, one declared but never imported, and one used
only because something else pulled it in. That last case is the subtle one — code
that imports a transitive dependency breaks the day the intermediate package
drops it.

## Tests

Tests live in `tests/`, mirroring the package. `pytest` is configured with a
coverage floor of 85%, and unexpected warnings are errors.

```bash
uv run pytest                             # everything, with coverage
uv run pytest tests/test_etl.py           # one file
uv run pytest -k "threshold"              # by name
uv run pytest -x -q -m "not slow"         # what pre-push runs
uv run pytest --lf                        # last failures only
just cov                                  # HTML report
```

Two markers are available, and `--strict-markers` means a typo in one is an error
rather than a silently ignored filter:

```python
@pytest.mark.integration   # drives several layers at once
@pytest.mark.slow          # too slow for the pre-push hook to wait for
```

`integration` is for tests that exercise a whole entrypoint or the W&B SDK rather
than one unit — about a fifth of the suite carries it. "Touches the filesystem"
would have been a useless criterion, since nearly every test here writes to
`tmp_path`; what is worth separating is breadth.

`slow` currently has no members: the whole suite runs in seconds. It is
registered so that the first genuinely slow test — a real training run — has
somewhere to go, and starts being excluded from `just test-fast` for free. Use
it as soon as one appears; the value of the pre-push hook is being fast enough
that nobody is tempted to skip it.

That gives three useful scopes: `just test-fast` runs the units only, the
pre-push hook adds the integration tests, and CI runs everything with the
coverage floor.

### Fixtures you already have

From `tests/conftest.py`:

- **`settings`** — settings rooted at `tmp_path` with tracking disabled. Start
  here rather than building a `Settings` by hand.
- **`wandb_init_spy`** — records the keyword arguments passed to `wandb.init`.
- An autouse fixture clears ambient `PACKAGENAME_*` variables and redirects the W&B
  and Matplotlib cache directories into `tmp_path`, so tests cannot be influenced
  by your shell or leave anything in your home directory.

### What is worth testing

The suite that ships is a working example. It leans on: verifying the contract
rather than the implementation, and a regression test for every bug found, named
after the symptom. Two of the tests in `tests/test_viz.py` and `tests/test_cli.py`
exist because of real bugs; that is the pattern to copy.

`tests/test_sample.py` shows the other pattern worth copying: build a fake
region in `tmp_path`, subsample it, and assert against the manifest — the whole
data-management loop, tested in milliseconds without touching a real dataset.

## Commits

[Conventional Commits](https://www.conventionalcommits.org/), enforced by a
`commit-msg` hook:

```
<type>(scope): description

feat:     New feature                  -> bumps MINOR
fix:      Bug fix                      -> bumps PATCH
refactor: Restructuring, no behaviour change
docs:     Documentation only
test:     Add or fix tests
build:    Build system, CI, dependencies
chore:    Maintenance
perf:     Performance improvement
ops:      Infrastructure or deployment
revert:   Revert a previous commit
```

Only `feat:` and `fix:` move the version. `feat!:` or `fix!:` (or a
`BREAKING CHANGE:` footer) bump `MAJOR`.

The format is not bureaucracy here: Release Please reads it to decide the next
version and to write `CHANGELOG.md`, so a `feat:` mislabelled as `chore:` is a
release that silently does not happen.

Write the description in the imperative and say why, not what — the diff already
says what.

## The gates

| When | What runs |
|---|---|
| commit | trailing whitespace, end-of-file, YAML/TOML/JSON validity, large files, merge conflicts, case conflicts, line endings, leftover `breakpoint()`, ruff check `--fix`, ruff format, notebook output stripping, gitleaks, typos, actionlint, `uv.lock` freshness |
| commit message | Conventional Commits |
| push | `ty`, `deptry`, the suite except anything marked `slow` |
| CI | every commit hook above over *all* files, then `ty`, `deptry`, and the full suite with the coverage floor, on Python 3.12 and 3.13 |
| weekly, and whenever the lock changes | `pip-audit` over the locked runtime dependencies |

Fast checks run on commit, slow ones on push. Anything a hook fixed in place has
to be staged again — re-run `git add` and commit.

CI runs `pre-commit run --all-files` rather than its own list of linters. A
hand-copied subset is a subset that falls behind: the point of the gate is that
CI cannot be laxer than what you already ran locally.

Hook revisions are pinned so everyone gets the same linters. `just update-hooks`
bumps them, as a reviewable commit rather than a silent drift. Ruff is the one
exception: it runs through `uv run`, so its version is recorded only in
`uv.lock`. A `rev:` for it would be a second number to keep in step, and `just
lint` and the hook would disagree the moment they drifted — which is what
happened before.

Notebook outputs are stripped before they reach a commit. That keeps diffs
readable and, more importantly, keeps whatever was in a dataframe preview out of
the repository history.

### When a gate is wrong

Suppress narrowly, and say why:

```python
np.random.seed(seed)  # noqa: NPY002 -- seeds the legacy global RNG that libraries still use
value = obj.attr      # ty: ignore[unresolved-attribute]
```

Always with a rule code — a blanket `# noqa` or a bare ignore is itself an error
here. `--no-verify` is not a solution; if a hook is wrong often enough to be
worth skipping, fix its configuration.

## CI and releases

CI runs on pull requests and on pushes to `main`, in three jobs: `hooks`
(`pre-commit run --all-files`), `typecheck` (`ty` and `deptry`, the two gates
pre-commit only runs on push) and `test` (the suite on 3.12 and 3.13, a check that
the console scripts start, and a run of the whole example pipeline). That last step
is only possible because the example stages synthesise their own inputs: CI has no
datasets and no credentials, and it should stay that way — pulling real data into
a hosted runner is not a check worth paying for. `uv sync --locked` means CI fails
rather than quietly testing a different dependency set than you have.
`WANDB_MODE=disabled` is set globally, so no test can reach the tracking backend.

A separate `Audit` workflow runs `pip-audit` against the locked runtime
dependencies — on any change to `uv.lock` or `pyproject.toml`, and weekly, because
an advisory can appear without anyone touching the repository. It audits the
runtime set and not the dev tools: a CVE in a linter is the kind of noise that
gets a red build ignored. When an advisory has no fix available, add
`--ignore-vuln GHSA-…` to the step with a comment saying why, rather than
disabling the job — and remove the flag the day a fixed version exists, because
an ignore left behind also hides the next advisory against that package.

Actions are pinned to commit SHAs. A tag can be repointed by whoever controls the
action's repository; a SHA cannot. Dependabot opens monthly PRs to move both those
pins and the Python dependencies, so pinning does not mean going stale.

Releases are automated by [Release Please](https://github.com/googleapis/release-please):

1. Merge conventional commits into `main`.
2. Release Please opens a PR with the version bump and the changelog.
3. Merging that PR creates the tag and the GitHub Release.

The behaviour is configured in `release-please-config.json`, with the current
version in `.release-please-manifest.json`. Both are passed to the action
explicitly. Note that supplying a `release-type` *input* instead makes the action
ignore both files and use its own defaults — a quiet way to end up maintaining
configuration nothing reads.

For this to work on a fresh repository, enable it once under
`Settings → Actions → General → Workflow permissions`: choose "Read and write
permissions" and allow Actions to create and approve pull requests. One caveat:
a PR opened with the default `GITHUB_TOKEN` does not trigger other workflows, so
CI will not run on the release PR unless you give the action a PAT or an App
token.

## Notebooks

`notebooks/` is for exploration. Import from the package rather than pasting code
in — that is what makes an experiment reproducible from the command line later:

```python
from packagename import get_settings, setup_logging
from packagename.etl import read_table
from packagename.viz import apply_style, savefig

setup_logging(level="DEBUG")
apply_style("talk")
settings = get_settings()

frame = read_table(settings.paths.gold / "train.parquet")
```

Paths resolve against the repository root, not the notebook's directory, so this
works from any subfolder. When a cell has earned its place, move it into
`src/packagename/` and call it from the notebook — and if it produces a file
something else depends on, make it a stage in `src/packagename/etl/pipeline.py`.

The numbered notebooks are a chain, and the numbering is the dependency order.
Each one reads what the previous wrote, so a change in `02` has to be followed by
re-running `03` onwards:

| Notebook | Reads | Writes |
|---|---|---|
| `01_eda` | any layer, via `LAYER` | `reports/eda/<layer>/variable_summary.csv`, figures |
| `02_preprocessing` | `data/silver/` | `data/gold/model_matrix.parquet`, `models/preprocessor.joblib` |
| `03_feature_selection` | `data/gold/`, `models/preprocessor.joblib` | `reports/selection/` |
| `04_baselines_evaluation` | `data/gold/`, `reports/selection/` | `reports/baselines/`, the chosen model |
| `05_interpretability` | the chosen model, `data/gold/` | `reports/interpretability/`, figures |

`01_eda` is the one that runs more than once. Its input layer is a parameter, and
it is meant to be run first over the uncleaned layer — that pass is what tells you
which preprocessing is needed — and again over `silver` to see what actually
reaches the model. Outputs are namespaced by layer so the two can be compared
rather than one overwriting the other. Anything fitted from the data, though,
belongs to the training split and not to those figures.

The `split` column of `model_matrix.parquet` is what makes that chain honest:
`02` decides the train/validation/test partition once and the other three inherit
it, instead of each recomputing a partition of its own and comparing numbers that
were never measured on the same rows.

The stack they import lives in the `analysis` dependency group rather than in
`dependencies`, because nothing under `src/` imports it yet and deptry would
report every entry as unused. `uv sync` installs it anyway — see
`[tool.uv] default-groups`. Move an entry into `dependencies` when the code that
needs it lands in the package.
