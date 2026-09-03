# Figures

`implacost.viz` is a consistent Matplotlib style, a `savefig` that knows where
figures belong, and a couple of helpers for finishing an axis.

## Style presets

```python
from implacost.viz import apply_style, style_context

apply_style("paper")     # for the rest of the session
```

Three presets — `paper`, `talk`, `poster` — differing only in sizes: fonts, line
widths, marker sizes, DPI. Colours, the muted grid, the hidden top and right
spines and the colour cycle are shared, so the same figure is recognisably from
the same project at every size.

For one figure at a different size without disturbing the rest of a notebook:

```python
with style_context("talk"):
    fig, ax = plt.subplots()
    ax.plot(x, y)
```

`rc_params("poster")` returns the mapping without applying it, if you want to
merge it into something else. Adding a preset is one entry in `PRESETS`.

The palette is in `implacost.viz.palette` as `COLOR_NAMES` (the cycle) and
`NEUTRALS` (text, grid, background).

## Saving

```python
from implacost.viz import savefig

savefig(fig, "loss.png")                    # -> reports/figures/loss.png
savefig(fig, "sub/loss.pdf")                # -> reports/figures/sub/loss.pdf
savefig(fig, "/tmp/scratch.png")            # absolute paths are left alone
savefig(fig, "loss.png", close=True)        # worth it in a loop
savefig(fig, "loss.png", dpi=600)           # extra kwargs go to Figure.savefig
```

A relative path is resolved under `paths.figures`, so a bare filename lands in
`reports/figures/` from a notebook, a script or a Hydra job alike. Missing parent
directories are created. The absolute path written to is returned.

By default `savefig` trims surrounding whitespace, and runs `tight_layout` only
when the figure has no layout engine of its own — calling it on a
constrained-layout figure warns and does nothing. Pass `tight=False` to opt out
of both.

Inside an entrypoint, a relative path follows any `paths.*` override you gave on
the command line, because `savefig` resolves through the settings the entrypoint
bound. If you drive the pipeline from a script instead, wrap the work in
`use_settings` to get the same behaviour — see
[configuration.md](configuration.md#binding-settings-yourself).

To log a figure to W&B and keep a local copy in one call, use
`tracker.log_figure(fig, "residuals", save_as="residuals.png")` instead.

## Finishing an axis

```python
from implacost.viz import annotate_bars, lighten_spines, remove_grid

fig, ax = plt.subplots()
ax.bar(labels, values)
annotate_bars(ax, "{:.1%}")
lighten_spines(ax)
remove_grid(ax)
```

All three return the axis, so they chain.

`annotate_bars` labels every bar with its value. `fmt` is a format string, so
`"{:.0f}"`, `"{:.2f}"` and `"{:.1%}"` all work; `padding` is the gap in points and
extra keyword arguments reach `bar_label`, which is how you get
`label_type="center"`. It handles vertical and horizontal bars, and raises if the
axis holds no bars — which means they were drawn with something other than
`ax.bar` or `ax.barh`.

It delegates to Matplotlib's `bar_label` rather than reading the geometry of the
patches, and that is deliberate. In a vertical bar chart the patch *width* is the
bar's thickness in data coordinates, so any attempt to guess the orientation by
comparing width against height mislabels every chart whose values are smaller
than that thickness — proportions, accuracies, error rates. `bar_label` uses the
values and orientation Matplotlib recorded when the bars were drawn.
