# Documentation

The [top-level README](../README.md) is the tour: what the template contains and
how to start it. [ARCHITECTURE.md](../ARCHITECTURE.md) is the structural view: how
the pieces depend on each other, who decides what, and which invariants hold
everywhere. These pages are the reference for actually working in it.

| Page | What it covers |
|---|---|
| [configuration.md](configuration.md) | `Settings`, where values come from, absolute paths, Hydra overrides and sweeps |
| [etl.md](etl.md) | Stages, the per-region data samples, the manifest, reading and writing tables |
| [tracking.md](tracking.md) | Weights & Biases: the context manager, the `@track` decorator, artifacts, provenance |
| [logging.md](logging.md) | Using the configured logger, log levels, and seeding the random generators |
| [viz.md](viz.md) | Matplotlib presets, saving figures, labelling bars |
| [workflow.md](workflow.md) | The loop: write, test, commit, push, CI, release |
| [renaming-the-package.md](renaming-the-package.md) | Everything to change when `packagename` becomes another name |

## Where does my code go?

Most work lands in one of four places:

| I want to… | Edit |
|---|---|
| add an ETL stage | `src/packagename/etl/pipeline.py` (see [etl.md](etl.md)) |
| write training code | `src/packagename/models/`, called from `src/packagename/cli/train.py` |
| load or query a dataset | `src/packagename/data/` |
| build features | `src/packagename/features/` |
| add a configuration knob | `configs/config.yaml` **and** `src/packagename/config.py` (see [configuration.md](configuration.md)) |
| refresh the samples after a dataset changed | `just subsample`, then commit `data/sample/` and `data/manifest.yaml` (see [etl.md](etl.md)) |

The `data/`, `features/` and `models/` subpackages ship empty on purpose: they
mark where the domain code goes without guessing at its shape.

## The three ideas worth knowing first

**One settings object, and every path in it is absolute.** Paths are anchored to
the repository root, derived from the package's own location rather than the
working directory. That is why `savefig(fig, "loss.png")` writes to
`reports/figures/` whether it runs from a notebook, a script, or a Hydra job in a
per-run output directory.

**Python owns the pipeline, and the versioned config owns the parameters.** A
stage is a plain function that always runs when invoked, in registration order;
anything that decides what it writes lives in `configs/config.yaml`, so a
parameter change is a commit `git log` can explain. The full datasets stay off
Git — one seeded sample per region and a manifest of fingerprints is what a
clone carries instead.

**A result you cannot trace is not a result.** Every tracked run records the
commit, the branch, whether the tree was dirty, and the fully resolved config.
