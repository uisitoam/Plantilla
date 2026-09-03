"""Shared Hydra wiring for every command-line entrypoint.

Factored out so that each entrypoint is only its own logic: the boilerplate of
composing the config, validating it, configuring logging, seeding and creating
directories happens exactly once, in the same order, for all of them.
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Mapping, Sequence
from typing import Any

import hydra
from hydra.core.hydra_config import HydraConfig
from omegaconf import DictConfig, OmegaConf

from packagename.config import (
    CONFIG_DIR,
    HYDRA_KEYS,
    PROJECT_ROOT,
    Settings,
    settings_from_mapping,
    use_settings,
)
from packagename.log import setup_logging
from packagename.seed import set_seed

__all__ = ["command_line_overrides", "hydra_entrypoint"]

#: Sentinel for "this key is not in the composed config", distinct from a real None.
_ABSENT = object()

#: Lets `configs/config.yaml` write `${project_root:}` so that even Hydra's own
#: output directories are absolute and independent of the launch directory.
if not OmegaConf.has_resolver("project_root"):
    OmegaConf.register_new_resolver("project_root", lambda: str(PROJECT_ROOT))


def hydra_entrypoint[R](fn: Callable[[Settings], R]) -> Callable[[], R]:
    """Turn a function of ``Settings`` into a Hydra-driven entrypoint.

    The wrapped function receives fully validated settings rather than an
    untyped ``DictConfig``: Hydra composes the config and handles command-line
    overrides and ``--multirun`` sweeps, while Pydantic guarantees the result is
    well formed before any work begins.

    Because ``hydra.job.chdir`` is false and every path is anchored to the
    repository root, the process never changes directory.

    Args:
        fn: The entrypoint body.

    Returns:
        A zero-argument callable suitable for ``[project.scripts]``.
    """

    @hydra.main(version_base=None, config_path=str(CONFIG_DIR), config_name="config")
    @functools.wraps(fn)
    def wrapper(cfg: DictConfig) -> R:
        composed = OmegaConf.to_container(cfg, resolve=True)
        settings = settings_from_mapping(composed, explicit=command_line_overrides(composed))
        # Binding the composed config is what makes a `paths.figures=...` override
        # reach helpers that resolve relative paths through get_settings().
        with use_settings(settings):
            setup_logging(settings)
            set_seed(settings.random_seed)
            settings.paths.ensure()
            return fn(settings)

    return wrapper


def command_line_overrides(composed: Any) -> dict[str, Any]:
    """Return only the settings the user named on the command line.

    Hydra hands over a single mapping in which the YAML defaults and the typed
    overrides are already merged, and it does not distinguish them. It does,
    however, record the raw override strings, so the keys they mention can be
    read back out of the merged mapping — which reuses Hydra's own parsing of the
    values instead of re-implementing it.

    The distinction matters for precedence: only what the user typed should
    outrank the environment. See :mod:`packagename.config`.

    Args:
        composed: The resolved container of the composed config.

    Returns:
        A nested dict holding just the overridden leaves.
    """
    explicit: dict[str, Any] = {}
    for override in HydraConfig.get().overrides.task:
        # Strip Hydra's append (`+`, `++`) and delete (`~`) prefixes.
        key = override.split("=", 1)[0].lstrip("+~")
        path = key.split(".")
        if path[0] in HYDRA_KEYS:
            continue
        value = _dig(composed, path)
        if value is _ABSENT:
            continue  # A `~key=` deletion leaves nothing to carry over.
        _plant(explicit, path, value)
    return explicit


def _dig(data: Any, path: Sequence[str]) -> Any:
    for key in path:
        if not isinstance(data, Mapping) or key not in data:
            return _ABSENT
        data = data[key]
    return data


def _plant(target: dict[str, Any], path: Sequence[str], value: Any) -> None:
    *branches, leaf = path
    for key in branches:
        node = target.setdefault(key, {})
        if not isinstance(node, dict):
            # An outer key was overridden wholesale, so it already carries this leaf.
            return
        target = node
    target[leaf] = value
