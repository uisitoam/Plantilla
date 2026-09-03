"""Typed project configuration.

That order is the same whether the settings are built by a library caller or by
an entrypoint. Getting there for the Hydra path takes some care, because the
config Hydra hands over is already a *merge* of the YAML file and the overrides
typed on the command line. Feeding that merged mapping in as explicit values
would give the YAML's own defaults precedence over the environment, which would
quietly make ``.env`` useless for exactly the commands people run most.
:func:`settings_from_mapping` therefore takes the two apart: the merged mapping
enters at file precedence, and only the keys the user actually typed enter as
explicit values.

Every filesystem path is anchored to :data:`PROJECT_ROOT`, which is derived from
this file's location. Nothing in the project depends on the current working
directory, which is what makes Hydra's per-run directories safe to enable.

There is one settings object in play at a time. :func:`get_settings` returns it,
and :func:`use_settings` is how an entrypoint binds the config Hydra composed so
that command-line overrides also reach code that reads the settings implicitly.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from functools import lru_cache
from pathlib import Path
from typing import Any, ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    InitSettingsSource,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

__all__ = [
    "CONFIG_DIR",
    "DEFAULT_CONFIG_FILE",
    "DEFAULT_ENV_FILE",
    "HYDRA_KEYS",
    "PROJECT_ROOT",
    "EtlSettings",
    "LoggingSettings",
    "Paths",
    "SampleSettings",
    "Settings",
    "WandbSettings",
    "get_settings",
    "load_settings",
    "reset_settings_cache",
    "settings_from_mapping",
    "use_settings",
]

#: Repository root, derived from this file so it never depends on the cwd.
PROJECT_ROOT: Path = Path(__file__).resolve().parents[2]
CONFIG_DIR: Path = PROJECT_ROOT / "configs"
DEFAULT_CONFIG_FILE: Path = CONFIG_DIR / "config.yaml"
DEFAULT_ENV_FILE: Path = PROJECT_ROOT / ".env"

#: Top-level keys owned by Hydra. They live in the same ``config.yaml`` but are
#: not part of :class:`Settings`, and may contain ``${...}`` interpolations that
#: only OmegaConf can resolve.
HYDRA_KEYS: frozenset[str] = frozenset({"defaults", "hydra"})

# Lets ``load_settings`` point the YAML source at a different file without
# having to declare a new Settings subclass.
_yaml_file_override: ContextVar[Path | None] = ContextVar("_yaml_file_override", default=None)

# An already-composed mapping to use *instead of* reading the YAML file, at the
# same precedence. This is how Hydra's composed config enters without displacing
# the environment.
_file_level_mapping: ContextVar[Mapping[str, Any] | None] = ContextVar(
    "_file_level_mapping", default=None
)

# Set by ``use_settings`` so that an entrypoint's composed config, and not a
# separately loaded one, is what ``get_settings`` hands to library code.
_active_settings: ContextVar[Settings | None] = ContextVar("_active_settings", default=None)


class _StrictModel(BaseModel):
    """Base for config sections: unknown keys are an error, not a silent no-op."""

    model_config = ConfigDict(extra="forbid")


class StrictYamlSource(YamlConfigSettingsSource):
    """YAML source that drops Hydra's keys and rejects anything unrecognised.

    Pydantic's ``extra="forbid"`` cannot be used on :class:`Settings` itself,
    because the ``.env`` file legitimately carries secrets that are not settings
    fields. Validating the YAML here keeps typo detection where typos happen.
    """

    def __init__(self, settings_cls: type[BaseSettings], yaml_file: Path) -> None:
        self._source = yaml_file
        super().__init__(settings_cls, yaml_file=yaml_file)

    def __call__(self) -> dict[str, Any]:
        """Return the YAML payload, minus Hydra's own sections."""
        data = super().__call__()
        payload = {key: value for key, value in data.items() if key not in HYDRA_KEYS}
        _reject_unknown_keys(payload, source=str(self._source))
        return payload


def _reject_unknown_keys(payload: dict[str, Any], *, source: str) -> None:
    unknown = sorted(set(payload) - set(Settings.model_fields))
    if unknown:
        known = ", ".join(sorted(Settings.model_fields))
        raise ValueError(
            f"Unknown configuration key(s) {unknown} in {source}. Known keys are: {known}."
        )


class Paths(_StrictModel):
    """Filesystem layout of the project.

    Relative values are resolved against :attr:`root` at validation time, so
    every attribute is guaranteed to be absolute once the model exists.
    """

    root: Path = PROJECT_ROOT
    raw: Path = Path("data/raw")
    bronze: Path = Path("data/bronze")
    silver: Path = Path("data/silver")
    gold: Path = Path("data/gold")
    #: Small per-region subsamples of the raw data, committed to Git for local runs.
    sample: Path = Path("data/sample")
    models: Path = Path("models")
    reports: Path = Path("reports")
    figures: Path = Path("reports/figures")
    logs: Path = Path("logs")

    #: Medallion layers, in pipeline order.
    LAYERS: ClassVar[tuple[str, ...]] = ("raw", "bronze", "silver", "gold")

    @field_validator("root", mode="before")
    @classmethod
    def _default_root(cls, value: object) -> object:
        """Treat an explicit null in the config file as "the repository root".

        Letting the YAML spell out every key keeps ``paths.*`` overridable from
        the Hydra command line, which requires the key to exist in the config.
        """
        return PROJECT_ROOT if value is None else value

    @model_validator(mode="after")
    def _absolutize(self) -> Self:
        root = self.root.expanduser().resolve()
        self.root = root
        for name in type(self).model_fields:
            if name == "root":
                continue
            value: Path = getattr(self, name)
            resolved = value.expanduser()
            setattr(self, name, resolved if resolved.is_absolute() else (root / resolved))
        return self

    def layer(self, name: str) -> Path:
        """Return the directory of a medallion layer by name."""
        if name not in self.LAYERS:
            raise ValueError(f"Unknown layer {name!r}; expected one of {self.LAYERS}.")
        directory: Path = getattr(self, name)
        return directory

    def ensure(self) -> None:
        """Create every configured directory, so pipeline steps can assume they exist."""
        for name in type(self).model_fields:
            directory: Path = getattr(self, name)
            directory.mkdir(parents=True, exist_ok=True)


class EtlSettings(_StrictModel):
    """Parameters of the ETL stages.

    Anything that changes what a stage writes belongs here rather than as a
    literal in the stage body: a parameter that lives in the versioned config
    file is a parameter whose change is visible in ``git log``, which a buried
    literal is not.

    The two fields below belong to the example stages in
    :mod:`packagename.etl.pipeline`; replace them along with those.
    """

    #: Number of observations the ``generate_measurements`` stage synthesises.
    rows: int = 500
    #: Cutoff applied by the ``aggregate_measurements`` stage.
    threshold: float = 0.5


class SampleSettings(_StrictModel):
    """Parameters of the per-region subsamples written by ``packagename-data``.

    The full datasets live only on the machine that runs the real workloads;
    what Git carries is one small sample per region under ``paths.sample`` plus
    the manifest written next to it. These two fields decide how big a sample
    is and which seed draws it, so a sample regenerated anywhere is byte for
    byte the one committed.
    """

    #: Observations drawn per region sample.
    rows: int = 1000
    #: Seed of the draw. Fixed, so the committed sample is reproducible.
    seed: int = 26


class WandbSettings(_StrictModel):
    """Weights & Biases options.

    The API key is deliberately absent: W&B reads ``WANDB_API_KEY`` from the
    environment itself, so no secret ever passes through this object.
    """

    project: str = "packagename"
    entity: str | None = None
    # Offline by default, matching configs/config.yaml: a fresh clone has to run
    # without credentials, and an unattended `online` run blocks on a login prompt.
    mode: Literal["online", "offline", "disabled"] = "offline"
    group: str | None = None
    job_type: str | None = None
    tags: tuple[str, ...] = ()
    save_code: bool = True
    #: Parent directory for W&B's local run files. Defaults to the project root.
    run_dir: Path | None = None


class LoggingSettings(_StrictModel):
    """Logging options consumed by :func:`packagename.log.setup_logging`."""

    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    format: str = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    datefmt: str = "%H:%M:%S"
    #: Optional log file. Relative values are resolved against ``paths.logs``.
    file: Path | None = None
    #: Loggers demoted to WARNING to keep the output readable.
    quiet_loggers: tuple[str, ...] = ("matplotlib", "urllib3", "botocore", "fsspec")


class Settings(BaseSettings):
    """Root configuration object for the whole project."""

    model_config = SettingsConfigDict(
        env_file=DEFAULT_ENV_FILE,
        env_prefix="PACKAGENAME_",
        env_nested_delimiter="__",
        # No `yaml_file` here: the file is chosen per call in
        # settings_customise_sources, which also replaces the YAML source
        # altogether when an already-composed mapping is supplied.
        # Not "forbid": the .env file carries secrets that are not fields.
        # Unknown YAML keys are rejected by StrictYamlSource instead.
        extra="ignore",
        validate_default=True,
    )

    project_name: str = "packagename"
    random_seed: int = 42
    paths: Paths = Field(default_factory=Paths)
    etl: EtlSettings = Field(default_factory=EtlSettings)
    sample: SampleSettings = Field(default_factory=SampleSettings)
    wandb: WandbSettings = Field(default_factory=WandbSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Order the sources so the environment wins over the config file."""
        composed = _file_level_mapping.get()
        file_source: PydanticBaseSettingsSource
        if composed is not None:
            # Already parsed and validated as a whole; reuse it at file level
            # rather than re-reading the YAML.
            file_source = InitSettingsSource(settings_cls, dict(composed))
        else:
            override = _yaml_file_override.get()
            file_source = StrictYamlSource(
                settings_cls, yaml_file=override if override is not None else DEFAULT_CONFIG_FILE
            )
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            file_source,
            file_secret_settings,
        )

    @model_validator(mode="after")
    def _anchor_dependent_paths(self) -> Self:
        """Resolve paths that hang off other sections, keeping everything absolute."""
        if self.wandb.run_dir is None:
            self.wandb.run_dir = self.paths.root
        elif not self.wandb.run_dir.is_absolute():
            self.wandb.run_dir = self.paths.root / self.wandb.run_dir
        if self.logging.file is not None and not self.logging.file.is_absolute():
            self.logging.file = self.paths.logs / self.logging.file
        return self

    def as_flat_dict(self, *, separator: str = ".") -> dict[str, Any]:
        """Flatten the settings into ``{"wandb.project": ...}`` form for tracking."""
        return _flatten(self.model_dump(mode="json"), separator=separator)


def _flatten(data: dict[str, Any], *, separator: str, prefix: str = "") -> dict[str, Any]:
    flat: dict[str, Any] = {}
    for key, value in data.items():
        full_key = f"{prefix}{key}"
        if isinstance(value, dict):
            flat.update(_flatten(value, separator=separator, prefix=f"{full_key}{separator}"))
        else:
            flat[full_key] = value
    return flat


def load_settings(config_path: Path | str | None = None, **overrides: Any) -> Settings:
    """Build a fresh :class:`Settings` instance.

    Args:
        config_path: YAML file to read. Defaults to ``configs/config.yaml``.
        **overrides: Values that take precedence over every other source.

    Returns:
        A validated settings object with all paths absolute.

    Raises:
        ValueError: If an override or a YAML key does not name a settings field.
    """
    _reject_unknown_keys(overrides, source="load_settings() overrides")
    token = _yaml_file_override.set(Path(config_path) if config_path is not None else None)
    try:
        return Settings(**overrides)
    finally:
        _yaml_file_override.reset(token)


def settings_from_mapping(data: Any, *, explicit: Mapping[str, Any] | None = None) -> Settings:
    """Validate an already-composed mapping (e.g. Hydra's config) into settings.

    Hydra's own ``defaults`` and ``hydra`` keys are stripped from both arguments.

    Args:
        data: The composed configuration. Enters at the same precedence as the
            YAML file, so the environment still wins over it.
        explicit: The subset the user actually asked for — for Hydra, the keys
            named in command-line overrides. These outrank every other source.

    Returns:
        A validated settings object with all paths absolute.

    Raises:
        ValueError: If a key in either mapping does not name a settings field.
    """
    payload = _without_hydra_keys(data)
    _reject_unknown_keys(payload, source="the composed Hydra config")
    typed = _without_hydra_keys(explicit or {})
    _reject_unknown_keys(typed, source="the command-line overrides")

    token = _file_level_mapping.set(payload)
    try:
        return Settings(**typed)
    finally:
        _file_level_mapping.reset(token)


def _without_hydra_keys(data: Any) -> dict[str, Any]:
    return {key: value for key, value in dict(data).items() if key not in HYDRA_KEYS}


@lru_cache(maxsize=1)
def _default_settings() -> Settings:
    """Load the settings once, from the YAML file and the environment."""
    return load_settings()


def get_settings() -> Settings:
    """Return the settings that library code should use.

    Inside a block opened by :func:`use_settings` — which every entrypoint does —
    this is the config Hydra composed, command-line overrides included. Anywhere
    else (notebooks, library code, tests) it is loaded once and cached.

    Helpers that accept a relative path, such as
    :func:`packagename.viz.save.savefig`, resolve it through this function, so the
    distinction matters: without it, ``paths.figures=...`` on the command line
    would be honoured by the entrypoint and quietly ignored by the helper.
    """
    active = _active_settings.get()
    return active if active is not None else _default_settings()


@contextmanager
def use_settings(settings: Settings) -> Iterator[Settings]:
    """Make ``settings`` the value :func:`get_settings` returns inside this block.

    Args:
        settings: The settings to bind.

    Yields:
        The same settings, for convenience.
    """
    token = _active_settings.set(settings)
    try:
        yield settings
    finally:
        _active_settings.reset(token)


def reset_settings_cache() -> None:
    """Discard the cached default settings.

    Needed only by tests, which change the environment between cases and must
    not inherit a :class:`Settings` built under the previous one.
    """
    _default_settings.cache_clear()
