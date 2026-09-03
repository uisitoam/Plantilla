# Snapshot condensado del repo

## Árbol de directors (podado)
```
Wave-regionalisation
├── configs
│   └── config.yaml
├── docs
│   ├── configuration.md
│   ├── CONTEXT_SNAPSHOT.md
│   ├── etl.md
│   ├── guia.tsx
│   ├── logging.md
│   ├── README.md
│   ├── renaming-the-package.md
│   ├── tracking.md
│   ├── viz.md
│   └── workflow.md
├── src
│   └── packagename
│       ├── cli
│       │   ├── __init__.py
│       │   ├── _hydra.py
│       │   ├── data.py
│       │   ├── stage.py
│       │   └── train.py
│       ├── data
│       │   ├── __init__.py
│       │   └── sample.py
│       ├── etl
│       │   ├── __init__.py
│       │   ├── io.py
│       │   ├── pipeline.py
│       │   └── registry.py
│       ├── features
│       │   └── __init__.py
│       ├── viz
│       │   ├── __init__.py
│       │   ├── latex.py
│       │   ├── palette.py
│       │   ├── save.py
│       │   ├── style.py
│       │   └── utils.py
│       ├── __init__.py
│       ├── config.py
│       ├── log.py
│       ├── py.typed
│       ├── seed.py
│       └── tracking.py
├── tests
│   ├── __init__.py
│   ├── conftest.py
│   ├── test_cli.py
│   ├── test_config.py
│   ├── test_etl.py
│   ├── test_sample.py
│   ├── test_seed_and_log.py
│   ├── test_tracking.py
│   └── test_viz.py
├── _typos.toml
├── CHANGELOG.md
├── git-conventional-commits.yaml
├── justfile
├── LICENSE
├── pyproject.toml
├── README.md
├── release-please-config.json
└── uv.lock
```

## Firmas de código en `src/` (sin cuerpos)

### `src/packagename/__init__.py`
```python
"""PACKAGENAME: Machine Learning project with a medallion ETL pipeline."""
```

### `src/packagename/cli/__init__.py`
```python
"""Command-line entrypoints, driven by Hydra."""
```

### `src/packagename/cli/_hydra.py`
```python
"""Shared Hydra wiring for every command-line entrypoint."""
def hydra_entrypoint(fn: Callable[[Settings], R])  # Turn a function of ``Settings`` into a Hydra-driven entrypoint.
def command_line_overrides(composed: Any)  # Return only the settings the user named on the command line.
```

### `src/packagename/cli/data.py`
```python
"""Manage the local data samples. This is the command behind ``just subsample``."""
def main(argv: Sequence[str] | None=None)  # Regenerate the samples and manifest, or check the datasets against it.
```

### `src/packagename/cli/stage.py`
```python
"""Run ETL stages. This is the command behind ``just etl``."""
def main(argv: Sequence[str] | None=None)  # Run one stage, every stage in registration order, or list the names.
```

### `src/packagename/cli/train.py`
```python
"""Train a model inside a tracked experiment run."""
def main(settings: Settings)  # Open a tracked run and hand control to the training routine.
```

### `src/packagename/config.py`
```python
"""Typed project configuration."""
class _StrictModel(BaseModel):  # Base for config sections: unknown keys are an error, not a silent no-op.
class StrictYamlSource(YamlConfigSettingsSource):  # YAML source that drops Hydra's keys and rejects anything unrecognised.
    def __init__(self, settings_cls: type[BaseSettings], yaml_file: Path)
    def __call__(self)  # Return the YAML payload, minus Hydra's own sections.
class Paths(_StrictModel):  # Filesystem layout of the project.
    def layer(self, name: str)  # Return the directory of a medallion layer by name.
    def ensure(self)  # Create every configured directory, so pipeline steps can assume they exist.
class EtlSettings(_StrictModel):  # Parameters of the ETL stages.
class SampleSettings(_StrictModel):  # Parameters of the per-region subsamples written by ``packagename-data``.
class WandbSettings(_StrictModel):  # Weights & Biases options.
class LoggingSettings(_StrictModel):  # Logging options consumed by :func:`packagename.log.setup_logging`.
class Settings(BaseSettings):  # Root configuration object for the whole project.
    def settings_customise_sources(cls, settings_cls: type[BaseSettings], init_settings: PydanticBaseSettingsSource, env_settings: PydanticBaseSettingsSource, dotenv_settings: PydanticBaseSettingsSource, file_secret_settings: PydanticBaseSettingsSource)  # Order the sources so the environment wins over the config file.
    def as_flat_dict(self, *, separator: str='.')  # Flatten the settings into ``{"wandb.project": ...}`` form for tracking.
def load_settings(config_path: Path | str | None=None, **overrides: Any)  # Build a fresh :class:`Settings` instance.
def settings_from_mapping(data: Any, *, explicit: Mapping[str, Any] | None=None)  # Validate an already-composed mapping (e.g. Hydra's config) into settings.
def get_settings()  # Return the settings that library code should use.
def use_settings(settings: Settings)  # Make ``settings`` the value :func:`get_settings` returns inside this block.
def reset_settings_cache()  # Discard the cached default settings.
```

### `src/packagename/data/__init__.py`
```python
"""Dataset access: downloading, loading and splitting."""
```

### `src/packagename/data/sample.py`
```python
"""Per-region subsamples of the raw data, plus a manifest of the full datasets."""
def manifest_path(settings: Settings)  # Return the path of the manifest: ``data/manifest.yaml`` by default.
def discover_regions(raw: Path)  # Map each region of the raw layer to its sampleable files, sorted by name.
def subsample_datasets(settings: Settings)  # Draw one sample per region and refresh the manifest.
def check_datasets(settings: Settings)  # Compare the manifest against the datasets on disk.
```

### `src/packagename/etl/__init__.py`
```python
"""ETL over the medallion layout (``raw -> bronze -> silver -> gold``)."""
```

### `src/packagename/etl/io.py`
```python
"""Tabular IO with format dispatch and atomic writes."""
def read_table(path: str | Path, **kwargs: Any)  # Read a dataframe, choosing the reader from the file extension.
def write_table(df: pd.DataFrame, path: str | Path, **kwargs: Any)  # Write a dataframe atomically, creating parent directories as needed.
```

### `src/packagename/etl/pipeline.py`
```python
"""The project's ETL stages: one function per stage."""
def raw_measurements(settings: Settings)  # Return the path of the synthetic raw dataset.
def summary_table(settings: Settings)  # Return the path of the per-station summary derived from the raw dataset.
def generate_measurements(settings: Settings)  # Write a synthetic raw dataset, seeded so the bytes are reproducible.
def aggregate_measurements(settings: Settings)  # Summarise the raw measurements per station, above a threshold.
```

### `src/packagename/etl/registry.py`
```python
"""The stages ``packagename-stage`` can invoke, and how a name reaches one."""
class UnknownStageError(KeyError):  # Raised when a name matches no registered stage.
def stage(name: str)  # Register a function as the implementation of a stage.
def registered_stages()  # Return every registered stage, keyed by name, in registration order.
def run_stage(name: str, settings: Settings)  # Run one stage, unconditionally.
```

### `src/packagename/features/__init__.py`
```python
"""Feature engineering."""
```

### `src/packagename/log.py`
```python
"""Centralised logging configuration."""
def setup_logging(settings: Settings | None=None, *, level: str | None=None)  # Configure the root logger from settings.
def get_logger(name: str)  # Return a logger namespaced under the project.
```

### `src/packagename/models/__init__.py`
```python
"""Model definition, training and inference."""
```

### `src/packagename/seed.py`
```python
"""Seeding of every random number generator the project may touch."""
def set_seed(seed: int, *, deterministic: bool=False)  # Seed Python, NumPy and, when installed, PyTorch and TensorFlow.
```

### `src/packagename/tracking.py`
```python
"""Experiment tracking with Weights & Biases."""
def git_metadata()  # Return commit, branch and dirtiness of the working tree.
class ExperimentTracker:  # Facade over a single W&B run.
    def __init__(self, run: Run, settings: Settings)
    def run(self)  # The underlying W&B run, for anything this facade does not cover.
    def enabled(self)  # False when tracking is disabled, in which case logging is a no-op.
    def id(self)  # The run identifier assigned by W&B.
    def name(self)  # The human-readable run name, falling back to the id.
    def url(self)  # Link to the run in the W&B UI, or None when offline or disabled.
    def log_params(self, params: Mapping[str, Any], *, prefix: str='')  # Record hyperparameters. Existing keys may be overwritten.
    def log_metrics(self, metrics: Mapping[str, float], *, step: int | None=None, commit: bool | None=None, prefix: str='')  # Record metrics for the current step.
    def log_summary(self, values: Mapping[str, Any])  # Record final, single-valued results shown in the run overview table.
    def log_figure(self, fig: Figure, name: str, *, save_as: str | Path | None=None, close: bool=True)  # Log a Matplotlib figure, optionally also writing it to disk.
    def log_artifact(self, path: str | Path, *, name: str | None=None, kind: str='dataset', aliases: Sequence[str] | None=None, metadata: Mapping[str, Any] | None=None)  # Version a file or directory as a W&B artifact.
    def log_model(self, path: str | Path, *, name: str | None=None, aliases: Sequence[str] | None=None, metadata: Mapping[str, Any] | None=None)  # Version a trained model artifact. Thin wrapper over :meth:`log_artifact`.
    def finish(self, exit_code: int=0)  # Close the run. Called for you when using :func:`start_run`.
def active_tracker()  # Return the tracker of the innermost active run, if any.
def start_run(name: str | None=None, *, settings: Settings | None=None, config: Mapping[str, Any] | None=None, tags: Sequence[str]=(), group: str | None=None, job_type: str | None=None, notes: str | None=None, log_settings: bool=True, **wandb_kwargs: Any)  # Open a W&B run, yielding a tracker, and always close it.
def track(name: str | None=None, **run_kwargs: Any)  # Wrap a function so that each call is one tracked run.
```

### `src/packagename/viz/__init__.py`
```python
"""Plotting: a consistent Matplotlib style and helpers for common touch-ups."""
```

### `src/packagename/viz/palette.py`
```python
"""Project colour palette, shared by every preset in :mod:`packagename.viz.style`."""
```

### `src/packagename/viz/save.py`
```python
"""Saving figures to a predictable location."""
def savefig(fig: Figure, path: str | Path, *, create_dirs: bool=True, tight: bool=True, close: bool=False, **savefig_kwargs: Any)  # Save a figure, resolving relative paths under ``paths.figures``.
```

### `src/packagename/viz/style.py`
```python
"""A consistent Matplotlib style, in a couple of sizes."""
class StyleSpec:  # The sizes that differ between presets.
def apply_style(preset: str='paper')  # Apply a style globally, for the rest of the session.
def style_context(preset: str='paper')  # Apply a style only inside the block, then restore the previous one.
def rc_params(preset: str='paper')  # Return the Matplotlib rcParams for a preset, without applying them.
```

### `src/packagename/viz/utils.py`
```python
"""Small touch-ups for finished axes."""
def remove_grid(ax: Axes)  # Hide the grid on an axis.
def lighten_spines(ax: Axes, color: str='#6b7280', linewidth: float=0.8)  # Soften the left and bottom spines so the data stands out.
def annotate_bars(ax: Axes, fmt: str='{:.2f}', *, padding: float=3, color: str | None=None, fontsize: float | None=None, **kwargs: Any)  # Label every bar with its value.
```
