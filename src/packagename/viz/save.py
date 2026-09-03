"""Saving figures to a predictable location."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import matplotlib.pyplot as plt
from matplotlib.figure import Figure

__all__ = ["savefig"]


def savefig(
    fig: Figure,
    path: str | Path,
    *,
    create_dirs: bool = True,
    tight: bool = True,
    close: bool = False,
    **savefig_kwargs: Any,
) -> Path:
    """Save a figure, resolving relative paths under ``paths.figures``.

    A bare filename therefore always lands in ``reports/figures``, whatever the
    working directory is, which matters for notebooks and for Hydra runs.

    Args:
        fig: The figure to save.
        path: Destination. Relative values are resolved against
            ``Settings.paths.figures``.
        create_dirs: Create missing parent directories.
        tight: Trim surrounding whitespace and, when the figure has no layout
            engine of its own, also run ``tight_layout``.
        close: Close the figure afterwards. Worth enabling in loops.
        **savefig_kwargs: Forwarded to ``Figure.savefig``, e.g. ``dpi``.

    Returns:
        The absolute path written to.
    """
    destination = Path(path)
    if not destination.is_absolute():
        from packagename.config import get_settings

        destination = get_settings().paths.figures / destination

    if create_dirs:
        destination.parent.mkdir(parents=True, exist_ok=True)

    if tight:
        # A figure with its own layout engine (constrained, compressed) already
        # manages spacing; calling tight_layout there warns and does nothing.
        if fig.get_layout_engine() is None:
            fig.tight_layout()
        savefig_kwargs.setdefault("bbox_inches", "tight")

    fig.savefig(destination, **savefig_kwargs)

    if close:
        plt.close(fig)

    return destination
