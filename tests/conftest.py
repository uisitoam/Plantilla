"""Shared fixtures and test-suite isolation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import matplotlib
import pytest

from packagename.config import Settings, load_settings, reset_settings_cache

# No test may reach the network or write to a real W&B project.
os.environ["WANDB_MODE"] = "disabled"
os.environ["WANDB_SILENT"] = "true"
# Headless backend, chosen before any pyplot import pulls in a GUI toolkit.
matplotlib.use("Agg")


@pytest.fixture(autouse=True)
def _isolate_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Isolate each test from the developer's machine.

    Ambient ``PACKAGENAME_*`` variables would silently change the configuration
    under test, and W&B and Matplotlib both default to caches under the user's
    home directory, which a test suite has no business writing to.
    """
    for name in list(os.environ):
        if name.startswith("PACKAGENAME_"):
            monkeypatch.delenv(name, raising=False)

    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "mpl"))
    for variable in ("WANDB_DIR", "WANDB_DATA_DIR", "WANDB_CACHE_DIR", "WANDB_CONFIG_DIR"):
        monkeypatch.setenv(variable, str(tmp_path / "wandb" / variable.lower()))

    reset_settings_cache()


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings rooted at a temporary directory, with tracking disabled."""
    return load_settings(
        project_name="test-project",
        paths={"root": tmp_path},
        wandb={"mode": "disabled", "project": "test"},
    )


@pytest.fixture
def wandb_init_spy(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """Record the keyword arguments passed to ``wandb.init``.

    In disabled mode W&B substitutes a no-op run that invents its own name, so
    assertions about what we asked for have to look at the call itself.
    """
    import wandb

    calls: list[dict[str, Any]] = []
    original = wandb.init

    def spy(**kwargs: Any) -> Any:
        calls.append(kwargs)
        return original(**kwargs)

    monkeypatch.setattr(wandb, "init", spy)
    return calls
