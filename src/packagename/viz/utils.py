"""Small touch-ups for finished axes."""

from __future__ import annotations

from typing import Any

from matplotlib.axes import Axes
from matplotlib.container import BarContainer

__all__ = ["annotate_bars", "lighten_spines", "remove_grid"]


def remove_grid(ax: Axes) -> Axes:
    """Hide the grid on an axis.

    Args:
        ax: The axis to modify.

    Returns:
        The same axis, for chaining.
    """
    ax.grid(visible=False)
    return ax


def lighten_spines(ax: Axes, color: str = "#6b7280", linewidth: float = 0.8) -> Axes:
    """Soften the left and bottom spines so the data stands out.

    Args:
        ax: The axis to modify.
        color: Spine colour.
        linewidth: Spine width in points.

    Returns:
        The same axis, for chaining.
    """
    for side in ("left", "bottom"):
        ax.spines[side].set_color(color)
        ax.spines[side].set_linewidth(linewidth)
    return ax


def annotate_bars(
    ax: Axes,
    fmt: str = "{:.2f}",
    *,
    padding: float = 3,
    color: str | None = None,
    fontsize: float | None = None,
    **kwargs: Any,
) -> Axes:
    """Label every bar with its value.

    Delegates to :meth:`~matplotlib.axes.Axes.bar_label`, which reads the values
    and the orientation that Matplotlib recorded when the bars were drawn.
    Inferring either of those from patch geometry is not possible: in a vertical
    bar chart the patch width is the bar thickness in data coordinates, so any
    comparison against the bar height mislabels charts whose values happen to be
    smaller than that thickness (proportions, accuracies, error rates).

    Args:
        ax: Axis holding the bars.
        fmt: Format string for the label, e.g. ``"{:.1f}"`` or ``"{:.0%}"``.
        padding: Distance in points between bar and label.
        color: Label colour. Defaults to the axis label colour.
        fontsize: Label size. Defaults to the global size.
        **kwargs: Forwarded to ``bar_label``, e.g. ``label_type="center"``.

    Returns:
        The same axis, for chaining.

    Raises:
        ValueError: If the axis holds no bar containers, which means the bars
            were not drawn with ``ax.bar`` or ``ax.barh``.
    """
    containers = [c for c in ax.containers if isinstance(c, BarContainer)]
    if not containers:
        raise ValueError(
            "No bar containers on this axis; annotate_bars needs bars drawn with "
            "ax.bar() or ax.barh()."
        )

    for container in containers:
        ax.bar_label(
            container,
            fmt=fmt,
            padding=padding,
            color=color or ax.xaxis.label.get_color(),
            fontsize=fontsize,
            **kwargs,
        )
    return ax
