"""A consistent Matplotlib style, in a couple of sizes."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

import matplotlib.pyplot as plt
from cycler import cycler
from matplotlib.typing import RcKeyType

from packagename.viz.palette import COLOR_NAMES, NEUTRALS

__all__ = ["PRESETS", "StyleSpec", "apply_style", "style_context"]


@dataclass(frozen=True, slots=True)
class StyleSpec:
    """The sizes that differ between presets.

    Colours and structural choices are shared by every preset, so only the
    dimensions that actually change with the medium live here. Adding a preset is
    one entry in :data:`PRESETS`.
    """

    font_size: float
    title_size: float
    label_size: float
    tick_size: float
    legend_size: float
    figure_dpi: float
    line_width: float
    marker_size: float
    savefig_dpi: float = 300


#: Available presets, keyed by the name passed to :func:`apply_style`.
PRESETS: Mapping[str, StyleSpec] = {
    "paper": StyleSpec(
        font_size=10,
        title_size=12,
        label_size=10,
        tick_size=9,
        legend_size=9,
        figure_dpi=100,
        line_width=1.0,
        marker_size=5,
    ),
    "talk": StyleSpec(
        font_size=14,
        title_size=16,
        label_size=14,
        tick_size=12,
        legend_size=12,
        figure_dpi=120,
        line_width=1.6,
        marker_size=6.5,
    ),
    "poster": StyleSpec(
        font_size=18,
        title_size=22,
        label_size=18,
        tick_size=15,
        legend_size=15,
        figure_dpi=150,
        line_width=2.2,
        marker_size=8,
    ),
}


def apply_style(preset: str = "paper") -> None:
    """Apply a style globally, for the rest of the session.

    Args:
        preset: One of the keys of :data:`PRESETS`.

    Raises:
        ValueError: If the preset is unknown.
    """
    plt.rcParams.update(rc_params(preset))


@contextmanager
def style_context(preset: str = "paper") -> Iterator[None]:
    """Apply a style only inside the block, then restore the previous one.

    Useful for producing one figure at a different size without disturbing the
    rest of a notebook.

    Args:
        preset: One of the keys of :data:`PRESETS`.

    Yields:
        None.
    """
    with plt.rc_context(rc_params(preset)):
        yield


def rc_params(preset: str = "paper") -> dict[RcKeyType, Any]:
    """Return the Matplotlib rcParams for a preset, without applying them.

    ``RcKeyType`` is Matplotlib's literal union of every valid rc key, so a
    misspelled setting here is a type error rather than a silently ignored entry.

    Args:
        preset: One of the keys of :data:`PRESETS`.

    Returns:
        A mapping suitable for ``plt.rcParams.update`` or ``plt.rc_context``.

    Raises:
        ValueError: If the preset is unknown.
    """
    try:
        spec = PRESETS[preset]
    except KeyError:
        raise ValueError(f"Unknown preset {preset!r}; expected one of {sorted(PRESETS)}.") from None

    dark = NEUTRALS["dark_slate"]
    return {
        "font.family": "sans-serif",
        "font.sans-serif": ["DejaVu Sans", "Arial", "Helvetica"],
        "font.size": spec.font_size,
        "axes.titlesize": spec.title_size,
        "axes.labelsize": spec.label_size,
        "xtick.labelsize": spec.tick_size,
        "ytick.labelsize": spec.tick_size,
        "legend.fontsize": spec.legend_size,
        "text.color": dark,
        "axes.labelcolor": dark,
        "axes.edgecolor": dark,
        "xtick.color": dark,
        "ytick.color": dark,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.color": NEUTRALS["light"],
        "grid.linewidth": 0.5,
        "grid.alpha": 0.2,
        "axes.axisbelow": True,
        "axes.facecolor": NEUTRALS["background"],
        "figure.facecolor": NEUTRALS["background"],
        "savefig.facecolor": NEUTRALS["background"],
        "figure.dpi": spec.figure_dpi,
        "savefig.dpi": spec.savefig_dpi,
        "lines.linewidth": spec.line_width,
        "lines.markersize": spec.marker_size,
        "axes.prop_cycle": cycler(color=list(COLOR_NAMES.values())),
    }
