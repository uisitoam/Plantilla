# Configuration

Everything configurable lives in one file, `configs/config.yaml`, which has two
readers: `packagename.config.Settings` (notebooks, library code, tests) and Hydra
(the `packagename-train` entrypoint). Keeping a single file means both see the
same values, so a knob you change for a script also changes for a notebook — and,
for the ETL parameters, the change is a commit `git log` can explain. Anything
under `hydra:` belongs to Hydra alone and is ignored by Settings.

## Reading settings

`get_settings()` is the normal way in. Inside an entrypoint it returns the config
Hydra composed, overrides included; everywhere else it loads the file once and
caches the result.

```python
from packagename import get_settings

settings = get_settings()
settings.project_name
settings.random_seed
settings.paths.gold          # absolute
settings.etl.threshold       # an ETL parameter from the versioned file
settings.sample.seed         # the seed of the committed data samples
settings.wandb.mode
settings.logging.level
```



Use `load_settings()` when you want an independent object rather than the shared
one — mostly in tests, or to read a different file:

```python
from packagename.config import load_settings

load_settings()                                   # a fresh instance
load_settings("configs/experiment.yaml")          # a different file
load_settings(random_seed=7)                      # override in code
load_settings(paths={"root": "/scratch/run1"})    # override a whole section
```

## Where values come from

Five sources, **later ones win**:

1. Field defaults in `src/packagename/config.py`
2. `configs/config.yaml`
3. `.env` at the repository root
4. Process environment variables
5. Values passed explicitly: keyword arguments to `load_settings()`, or a Hydra
   command-line override

Environment variables carry the `PACKAGENAME_` prefix and use `__` to descend into
a section:

```bash
PACKAGENAME_RANDOM_SEED=7 uv run packagename-train
PACKAGENAME_WANDB__MODE=online uv run packagename-train
PACKAGENAME_LOGGING__LEVEL=DEBUG uv run packagename-train
```

This order is the same whether the settings are built by a library caller or by
an entrypoint. Getting there for the Hydra path takes some care, because the
config Hydra hands over is already a *merge* of the YAML file and the overrides
typed on the command line. Feeding that merged mapping in as explicit values
would give the YAML's own defaults precedence over the environment, which would
quietly make ``.env`` useless for exactly the commands people run most.
`settings_from_mapping()` from `src/packagename/config.py` therefore takes the two apart: the merged mapping
enters at file precedence, and only the keys the user actually typed enter as
explicit values.

### Secrets

No secret is ever a settings field. `WANDB_API_KEY` goes in `.env` and W&B reads
it from the environment directly, so there is no code path along which a
credential could end up in a run config or a log line. Start from
`.env.example`, which `just setup` copies for you.

### Typos are errors

A misspelled key is rejected rather than silently ignored — in the YAML file, in
a `load_settings()` override, and in a Hydra command-line override:

```
Unknown configuration key(s) ['randon_seed'] in configs/config.yaml.
Known keys are: etl, logging, paths, project_name, random_seed, wandb.
```

This matters more than it looks. A silently ignored `randon_seed: 7` means an
experiment that claims a seed it never used.

## Paths

`Settings.paths` holds the filesystem layout, and every attribute is absolute by
the time you can read it. Relative values in the YAML are resolved against
`paths.root`, and `root: null` means the repository root, derived from where the
package is installed rather than from the working directory.

```python
paths = get_settings().paths

paths.root         # repository root
paths.raw          # <root>/data/raw
paths.bronze       # <root>/data/bronze
paths.silver       # <root>/data/silver
paths.gold         # <root>/data/gold
paths.models       # <root>/models
paths.reports      # <root>/reports          -- tables the notebooks produce
paths.figures      # <root>/reports/figures  -- figures only
paths.logs         # <root>/logs

paths.layer("silver")   # lookup by medallion layer name
paths.ensure()          # create every directory
```

`layer()` accepts only `raw`, `bronze`, `silver` and `gold`, and raises on
anything else, so a typo in a layer name fails at the call rather than by
creating a stray directory.

Entrypoints call `paths.ensure()` before running anything, so a stage can assume
its output directory exists.

Point the whole tree somewhere else with a single override:

```bash
uv run packagename-train paths.root=/scratch/experiment-42
```

That works for the training entrypoint. It is deliberately not available for ETL
stages: a stage's paths come from the versioned file, so redirecting them would
let a run leave no trace in `git log`. If you need scratch space, point the whole
checkout there.

### Why absolute paths are the load-bearing decision

Because nothing resolves against the working directory, `hydra.job.chdir` can
stay at its default of `false` and Hydra's per-run output directories are safe to
use. Run `packagename-train` from `/tmp` and it still reads and writes inside the
repository, and creates nothing where you launched it.

## Adding a setting

Two edits, in this order:

1. **`src/packagename/config.py`** — add the field to `Settings` or to one of the
   nested models (`Paths`, `EtlSettings`, `WandbSettings`, `LoggingSettings`), with
   a type and a default. For a new group, subclass `_StrictModel` so unknown keys
   are rejected there too.
2. **`configs/config.yaml`** — spell the key out with its default value.

Step 2 is not redundant. Hydra can only override keys that already exist in the
composed config, so a field that is absent from the YAML cannot be set from the
command line without Hydra's `+` append syntax. Writing every key out is what
keeps `paths.root=/scratch` working as a plain override.

A parameter that changes what an ETL stage writes belongs in the `etl` section.
The sampler's knobs have their own `sample` section — `rows` and `seed` — which
`packagename-data` reads the same way.

### Why ETL stages ignore the environment

`.env` and `PACKAGENAME_*` outrank the YAML file, which is right for a training
run and wrong for a pipeline stage: the committed samples and manifest describe
data produced by the versioned file's values, and a value injected from the
environment would leave no trace of which one actually ran. `packagename-stage`
therefore builds its settings from the file and takes no overrides at all. To
change a parameter, edit the YAML and rerun `just etl`.

## Hydra

The entrypoints are wrapped in `hydra_entrypoint`, which composes the config,
validates it into `Settings`, sets up logging, seeds the random generators,
creates the project directories, and binds the settings so the rest of the
process sees them:

```python
from packagename.cli._hydra import hydra_entrypoint
from packagename.config import Settings

@hydra_entrypoint
def main(settings: Settings) -> None:
    """Receives validated settings, not an untyped DictConfig."""
```

Register a new entrypoint under `[project.scripts]` in `pyproject.toml`:

```toml
[project.scripts]
packagename-evaluate = "packagename.cli.evaluate:main"
```

### Overrides and sweeps

```bash
uv run packagename-train random_seed=7
uv run packagename-train wandb.mode=offline paths.root=/scratch/run1
uv run packagename-train --multirun random_seed=1,2,3
uv run packagename-train --cfg job          # print the composed config and exit
uv run packagename-train --help
```

A sweep runs the entrypoint once per combination. Each run gets its own W&B run,
and grouping them is worth doing:

```bash
uv run packagename-train --multirun random_seed=1,2,3 wandb.group=seed-sweep
```

Hydra writes its own bookkeeping to `outputs/` for single runs and `multirun/`
for sweeps, both under the repository root and both git-ignored. Nothing the
project itself produces goes there — your data and models go where
`settings.paths` says.

### How the Hydra path keeps the same precedence

The order is identical whether settings are built in a notebook or by an
entrypoint: defaults, then `configs/config.yaml`, then `.env`, then environment
variables, then anything passed explicitly. So

```bash
PACKAGENAME_RANDOM_SEED=7 uv run packagename-train              # 7, from the environment
PACKAGENAME_RANDOM_SEED=7 uv run packagename-train random_seed=9 # 9, because you typed it
```

Getting there takes some care, and it is worth knowing why. Hydra hands the
entrypoint a single mapping in which the YAML file and the command-line overrides
are *already merged*, with no record of which value came from where. Passing that
mapping along as explicit values — the obvious implementation — gives every key
the YAML spells out precedence over the environment. Since `config.yaml`
deliberately spells out all of them, the effect is that `.env` and `PACKAGENAME_*`
stop working entirely for the commands people actually run, and nothing anywhere
reports a problem.

So the two are taken apart. `command_line_overrides` reads the raw override
strings Hydra records in `HydraConfig`, pulls just those keys back out of the
merged mapping, and `settings_from_mapping` feeds them in as explicit values while
the merged mapping enters at file precedence:

```python
composed = OmegaConf.to_container(cfg, resolve=True)
settings = settings_from_mapping(composed, explicit=command_line_overrides(composed))
```

Two details make this work. Values are read back out of the merged mapping rather
than parsed from the override strings, so Hydra's own typing is reused instead of
reimplemented. And the merge happens leaf by leaf, so `wandb.mode=disabled` on the
command line does not drag the rest of the `wandb` section up with it —
`PACKAGENAME_WANDB__PROJECT` still decides the project.

### Overriding values with special characters

Hydra parses override values with its own grammar, which rejects characters like
`(`. Quote the value *inside* the override, not just for the shell:

```bash
uv run packagename-train "logging.format='%(message)s'"
```

### Config groups

Add a Hydra group only for something genuinely swappable as a unit — a model
family, a dataset variant:

```
configs/
├── config.yaml
└── model/
    ├── xgboost.yaml
    └── linear.yaml
```

List it under `defaults:` in `config.yaml`, add the matching field to `Settings`,
and select it with `model=linear` on the command line. For a plain scalar a group
is overkill; just override the key.

## Binding settings yourself

`get_settings()` returns whatever `use_settings` has bound, which is how an
entrypoint's overrides reach helpers that resolve relative paths for you. You
rarely need it directly, but it is the right tool when you drive the pipeline
from a script or a notebook and want a non-default config to apply throughout:

```python
from packagename.config import load_settings, use_settings
from packagename.etl import aggregate_measurements

settings = load_settings(paths={"root": "/scratch/experiment-42"})
with use_settings(settings):
    aggregate_measurements(settings)
    # savefig("loss.png") now lands under /scratch/experiment-42 too
```

Bindings nest, and are undone on exit even if the block raises.
