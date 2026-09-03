"""Plot helpers, including a regression test for bar labelling."""

from __future__ import annotations

import matplotlib.pyplot as plt
import pytest

from packagename.viz import PRESETS, annotate_bars, apply_style, rc_params, savefig
from packagename.viz.style import style_context
from packagename.viz.utils import lighten_spines, remove_grid


@pytest.fixture
def fig_ax():
    fig, ax = plt.subplots()
    yield fig, ax
    plt.close(fig)


@pytest.fixture
def ax(fig_ax):
    return fig_ax[1]


def _labels(axes) -> list[str]:
    return [text.get_text() for text in axes.texts]


class TestAnnotateBars:
    def test_vertical_bars(self, ax):
        ax.bar(["a", "b", "c"], [1.0, 2.0, 3.0])
        annotate_bars(ax, "{:.1f}")
        assert _labels(ax) == ["1.0", "2.0", "3.0"]

    def test_values_smaller_than_the_bar_width(self, ax):
        """Regression: proportions are narrower than the default 0.8 bar width.

        The previous implementation inferred orientation by comparing patch width
        against patch height, so every value below 0.8 was labelled with the bar
        thickness instead of the value.
        """
        ax.bar(["a", "b", "c"], [0.25, 0.5, 0.75])
        annotate_bars(ax, "{:.2f}")
        assert _labels(ax) == ["0.25", "0.50", "0.75"]

    def test_horizontal_bars(self, ax):
        ax.barh(["a", "b"], [0.3, 0.9])
        annotate_bars(ax, "{:.1f}")
        assert _labels(ax) == ["0.3", "0.9"]

    def test_negative_values(self, ax):
        ax.bar(["a", "b"], [-0.5, 0.5])
        annotate_bars(ax, "{:.1f}")
        assert _labels(ax) == ["-0.5", "0.5"]

    def test_percentage_format(self, ax):
        ax.bar(["a"], [0.42])
        annotate_bars(ax, "{:.0%}")
        assert _labels(ax) == ["42%"]

    def test_grouped_bars_label_every_series(self, ax):
        ax.bar([0, 1], [0.1, 0.2], width=0.4, label="first")
        ax.bar([0.4, 1.4], [0.3, 0.4], width=0.4, label="second")
        annotate_bars(ax, "{:.1f}")
        assert _labels(ax) == ["0.1", "0.2", "0.3", "0.4"]

    def test_line_plot_is_an_explicit_error(self, ax):
        """Better a loud failure than silently labelling nothing."""
        ax.plot([0, 1], [0, 1])
        with pytest.raises(ValueError, match="No bar containers"):
            annotate_bars(ax)


class TestStyle:
    @pytest.mark.parametrize("preset", sorted(PRESETS))
    def test_every_preset_is_applicable(self, preset):
        apply_style(preset)
        assert plt.rcParams["font.size"] == PRESETS[preset].font_size

    def test_unknown_preset_lists_the_valid_ones(self):
        with pytest.raises(ValueError, match="Unknown preset"):
            rc_params("comic-sans")

    def test_style_context_restores_the_previous_state(self):
        apply_style("paper")
        before = plt.rcParams["font.size"]
        with style_context("poster"):
            assert plt.rcParams["font.size"] == PRESETS["poster"].font_size
        assert plt.rcParams["font.size"] == before


class TestSavefig:
    def test_relative_paths_land_in_the_figures_directory(self, fig_ax, settings, monkeypatch):
        monkeypatch.setattr("packagename.config.get_settings", lambda: settings)
        fig, _ = fig_ax
        written = savefig(fig, "plot.png")
        assert written == settings.paths.figures / "plot.png"
        assert written.exists()

    def test_absolute_paths_are_used_as_given(self, fig_ax, tmp_path):
        fig, _ = fig_ax
        target = tmp_path / "nested" / "plot.png"
        assert savefig(fig, target) == target
        assert target.exists()

    def test_close_releases_the_figure(self, tmp_path):
        fig, _ = plt.subplots()
        savefig(fig, tmp_path / "plot.png", close=True)
        assert not plt.fignum_exists(fig.number)

    def test_constrained_layout_does_not_warn(self, tmp_path, recwarn):
        """tight_layout must be skipped when the figure manages its own layout."""
        fig, _ = plt.subplots(layout="constrained")
        savefig(fig, tmp_path / "plot.png", close=True)
        assert not [w for w in recwarn if "tight_layout" in str(w.message)]


def test_axis_touch_ups_return_the_axis(ax):
    assert remove_grid(ax) is ax
    assert lighten_spines(ax) is ax
