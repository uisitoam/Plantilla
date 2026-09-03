"""Project colour palette, shared by every preset in :mod:`packagename.viz.style`."""

from __future__ import annotations

from typing import Final

#: Categorical colours, in the order they enter the Matplotlib property cycle.
COLOR_NAMES: Final[dict[str, str]] = {
    "crimson": "#DC143C",
    "orange-red": "#FF4500",
    "ochre-gold": "#C9A84C",
    "mint-green": "#52B788",
    "evergreen": "#285E46",
    "capri-turquoise": "#2EC4B6",
    "cornflower blue": "#6495ED",
    "navy": "#000080",
    "soft-lavender": "#9B89C4",
    "deep-purple": "#681A9C",
    "orchid": "#DA70D6",
}

#: Structural colours: text, spines, grid, background.
NEUTRALS: Final[dict[str, str]] = {
    "dark_slate": "#1e293b",
    "mid": "#6b7280",
    "light": "#d1d5db",
    "background": "#ffffff",
    "cocoa": "#523828",
    "hazelnut": "#A67B5B",
    "latte": "#C8AD7F",
}
