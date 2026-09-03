"""LaTeX tables in the project's default style.

The style is fixed on purpose: ``booktabs`` rules, bold header, caption and
label. It covers the tables that appear again and again in reports and
publications. Anything more exotic (multirow, coloured cells, rotated headers)
is written by hand and kept under ``reports/tables/manual/``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

__all__ = ["write_latex_table"]


def write_latex_table(
    data: pd.DataFrame | list[dict[str, Any]],
    path: str | Path,
    *,
    caption: str = "",
    label: str = "",
    column_format: str | None = None,
    bold_rows: list[int] | None = None,
    position: str = "htbp",
) -> Path:
    r"""Write a DataFrame as a LaTeX table in the project's default style.

    The output uses ``booktabs`` with doubled top and mid rules, a bold header,
    and centres every column after the first. Relative paths are resolved under
    ``settings.paths.reports / "tables"``.

    Args:
        data: DataFrame, or a list of row dicts that is converted into one.
        path: Destination ``.tex`` file. Relative paths land in the reports
            tables directory.
        caption: Table caption. Raw LaTeX is allowed (e.g. ``$R^2$``).
        label: Label for ``\\ref{...}``, without the ``tab:`` prefix.
        column_format: Explicit column spec, e.g. ``"lcc"``. Defaults to one
            left-aligned column followed by centred ones.
        bold_rows: Zero-based row indices to render in bold.
        position: Float placement specifier, e.g. ``"htbp"``.

    Returns:
        The absolute path written to.

    Raises:
        ValueError: If the path does not end in ``.tex``.

    Example:
        >>> df = pd.DataFrame({
        ...     "Model": ["XGBoost", "Neural"],
        ...     "RMSE": [0.42, 0.38],
        ... })
        >>> write_latex_table(
        ...     df,
        ...     "metrics.tex",
        ...     caption="Validation metrics.",
        ...     label="val_metrics",
        ... )
        PosixPath('.../reports/tables/metrics.tex')
    """
    from packagename.config import get_settings

    if isinstance(data, list):
        data = pd.DataFrame(data)

    destination = Path(path)
    if destination.suffix.lower() != ".tex":
        raise ValueError(f"Expected a .tex path, got {destination}")
    if not destination.is_absolute():
        destination = get_settings().paths.reports / "tables" / destination

    destination.parent.mkdir(parents=True, exist_ok=True)

    bold_rows = bold_rows or []
    n_cols = len(data.columns)
    column_format = column_format or ("l" + "c" * (n_cols - 1))

    lines = [
        f"\\begin{{table}}[{position}]",
        "\\centering",
        f"\\begin{{tabular}}{{{column_format}}}",
        "\\toprule\\toprule",
        _format_row([f"\\textbf{{{col}}}" for col in data.columns]),
        "\\midrule\\midrule",
    ]

    for index, row in data.iterrows():
        cells = [_format_cell(value) for value in row]
        if index in bold_rows:
            cells = [f"\\textbf{{{cell}}}" for cell in cells]
        lines.append(_format_row(cells))

    lines.extend(
        [
            "\\bottomrule",
            "\\end{tabular}",
        ]
    )
    if caption:
        lines.append(f"\\caption{{{caption}}}")
    if label:
        lines.append(f"\\label{{tab:{label}}}")
    lines.append("\\end{table}")

    destination.write_text("\n".join(lines) + "\n")
    return destination


def _format_row(cells: list[str]) -> str:
    """Join cells with LaTeX column separators and end the row."""
    return " & ".join(cells) + " \\\\"


def _format_cell(value: Any) -> str:
    """Convert a value to a LaTeX-safe string.

    Underscores are escaped so column names like ``val_loss`` do not raise
    missing-$ errors. Everything else is passed through unchanged so that
    intentional markup (e.g. ``$R^2$``) keeps working.
    """
    if isinstance(value, float):
        return f"{value:g}"
    return str(value).replace("_", "\\_")
