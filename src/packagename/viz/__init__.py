"""Plotting: a consistent Matplotlib style and helpers for common touch-ups."""

from packagename.viz.latex import write_latex_table
from packagename.viz.palette import COLOR_NAMES, NEUTRALS
from packagename.viz.save import savefig
from packagename.viz.style import PRESETS, apply_style, rc_params, style_context
from packagename.viz.utils import annotate_bars, lighten_spines, remove_grid

__all__ = [
    "COLOR_NAMES",
    "NEUTRALS",
    "PRESETS",
    "annotate_bars",
    "apply_style",
    "lighten_spines",
    "rc_params",
    "remove_grid",
    "savefig",
    "style_context",
    "write_latex_table",
]
