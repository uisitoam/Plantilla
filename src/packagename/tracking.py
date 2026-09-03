"""Experiment tracking with Weights & Biases.

Three layers are provided on top of the same core, so training code can pick
whichever fits:

* :class:`ExperimentTracker` — a facade over a live run, for explicit control.
* :func:`start_run` — a context manager that guarantees the run is closed and
  that failures are recorded as failures.
* :func:`track` — a decorator for the common case of "this function is one run".

Every run is tagged with the git commit and whether the working tree was dirty,
so a result can always be traced back to the code that produced it.

Example:
    >>> @track(name="baseline", tags=["xgboost"])
    ... def train(settings: Settings, tracker: ExperimentTracker | None = None) -> float:
    ...     assert tracker is not None
    ...     tracker.log_params({"n_estimators": 300})
    ...     tracker.log_metrics({"val/rmse": 0.42})
    ...     return 0.42
"""

from __future__ import annotations

import functools
import inspect
import logging
import subprocess
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import TYPE_CHECKING, Any, ParamSpec, TypeVar

from packagename.config import PROJECT_ROOT, Settings, get_settings

if TYPE_CHECKING:
    from matplotlib.figure import Figure
    from wandb.sdk.wandb_run import Run

__all__ = [
    "ExperimentTracker",
    "active_tracker",
    "git_metadata",
    "start_run",
    "track",
]

logger = logging.getLogger(__name__)

P = ParamSpec("P")
R = TypeVar("R")

#: Name of the parameter that :func:`track` injects, when the function declares it.
TRACKER_PARAMETER = "tracker"

_active: ContextVar[ExperimentTracker | None] = ContextVar("_active_tracker", default=None)


# ---------------------------------------------------------------------------
# Provenance
# ---------------------------------------------------------------------------
def _git(*args: str) -> str | None:
    """Run a git command in the project root, returning None if git is unusable."""
    try:
        # Fixed argument list, no shell, and pinned to the project root so the
        # answer does not depend on the caller's working directory.
        completed = subprocess.run(  # noqa: S603
            ["git", *args],  # noqa: S607 -- resolving git from PATH is intended
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return completed.stdout.strip()


def git_metadata() -> dict[str, str]:
    """Return commit, branch and dirtiness of the working tree.

    A commit hash alone can be misleading: if the tree had uncommitted changes,
    checking that commit out will not reproduce the run. ``git_dirty`` records
    that explicitly.
    """
    commit = _git("rev-parse", "--short", "HEAD")
    if commit is None:
        return {"git_commit": "unknown", "git_branch": "unknown", "git_dirty": "unknown"}
    return {
        "git_commit": commit,
        "git_branch": _git("rev-parse", "--abbrev-ref", "HEAD") or "unknown",
        "git_dirty": str(bool(_git("status", "--porcelain"))).lower(),
    }


# ---------------------------------------------------------------------------
# Tracker
# ---------------------------------------------------------------------------
class ExperimentTracker:
    """Facade over a single W&B run.

    Going through this object rather than calling ``wandb`` directly keeps the
    project's path conventions in one place, makes disabled runs a no-op without
    ``if`` statements in the training code, and leaves a single seam to replace
    if the tracking backend ever changes.
    """

    def __init__(self, run: Run, settings: Settings) -> None:
        self._run = run
        self._settings = settings

    @property
    def run(self) -> Run:
        """The underlying W&B run, for anything this facade does not cover."""
        return self._run

    @property
    def enabled(self) -> bool:
        """False when tracking is disabled, in which case logging is a no-op."""
        return self._settings.wandb.mode != "disabled"

    @property
    def id(self) -> str:
        """The run identifier assigned by W&B."""
        return str(self._run.id)

    @property
    def name(self) -> str:
        """The human-readable run name, falling back to the id.

        W&B invents a name for online runs but leaves it unset offline, so
        without the fallback anything that reports the name -- the log line
        :func:`start_run` writes, among others -- would say ``'None'``.
        """
        return str(self._run.name or self._run.id)

    @property
    def url(self) -> str | None:
        """Link to the run in the W&B UI, or None when offline or disabled."""
        return getattr(self._run, "url", None) if self.enabled else None

    def log_params(self, params: Mapping[str, Any], *, prefix: str = "") -> None:
        """Record hyperparameters. Existing keys may be overwritten."""
        self._run.config.update(_prefixed(params, prefix), allow_val_change=True)

    def log_metrics(
        self,
        metrics: Mapping[str, float],
        *,
        step: int | None = None,
        commit: bool | None = None,
        prefix: str = "",
    ) -> None:
        """Record metrics for the current step.

        Args:
            metrics: Metric names to values. Use ``train/loss`` style names; W&B
                groups them into panels by the part before the slash.
            step: Explicit step. When omitted, W&B uses its internal counter.
            commit: Whether to close the current step. Pass False to accumulate
                several calls into one step.
            prefix: Prepended to every key, e.g. ``"val/"``.
        """
        self._run.log(_prefixed(metrics, prefix), step=step, commit=commit)

    def log_summary(self, values: Mapping[str, Any]) -> None:
        """Record final, single-valued results shown in the run overview table."""
        for key, value in values.items():
            self._run.summary[key] = value

    def log_figure(
        self,
        fig: Figure,
        name: str,
        *,
        save_as: str | Path | None = None,
        close: bool = True,
    ) -> None:
        """Log a Matplotlib figure, optionally also writing it to disk.

        Args:
            fig: The figure to log.
            name: Key under which the figure appears in W&B.
            save_as: Filename for a local copy. Relative values land in
                ``paths.figures``; pass None to skip the local copy.
            close: Close the figure afterwards, which matters in loops.
        """
        if save_as is not None:
            from packagename.viz.save import savefig

            destination = Path(save_as)
            if not destination.is_absolute():
                destination = self._settings.paths.figures / destination
            savefig(fig, destination, close=False)

        self._run.log({name: fig})

        if close:
            import matplotlib.pyplot as plt

            plt.close(fig)

    def log_artifact(
        self,
        path: str | Path,
        *,
        name: str | None = None,
        kind: str = "dataset",
        aliases: Sequence[str] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        """Version a file or directory as a W&B artifact.

        Args:
            path: File or directory to upload.
            name: Artifact name. Defaults to the path's stem.
            kind: Artifact type, e.g. ``dataset``, ``model`` or ``report``.
            aliases: Extra aliases, on top of the implicit ``latest``.
            metadata: Free-form metadata attached to the artifact.
        """
        import wandb

        source = Path(path)
        if not source.exists():
            raise FileNotFoundError(f"Cannot log a missing artifact: {source}")

        artifact = wandb.Artifact(name or source.stem, type=kind, metadata=dict(metadata or {}))
        if source.is_dir():
            artifact.add_dir(str(source))
        else:
            artifact.add_file(str(source))
        self._run.log_artifact(artifact, aliases=list(aliases) if aliases else None)

    def log_model(
        self,
        path: str | Path,
        *,
        name: str | None = None,
        aliases: Sequence[str] | None = None,
        metadata: Mapping[str, Any] | None = None,
    ) -> None:
        """Version a trained model artifact. Thin wrapper over :meth:`log_artifact`."""
        self.log_artifact(path, name=name, kind="model", aliases=aliases, metadata=metadata)

    def finish(self, exit_code: int = 0) -> None:
        """Close the run. Called for you when using :func:`start_run`."""
        self._run.finish(exit_code=exit_code)


def _prefixed(values: Mapping[str, Any], prefix: str) -> dict[str, Any]:
    if not prefix:
        return dict(values)
    return {f"{prefix}{key}": value for key, value in values.items()}


def active_tracker() -> ExperimentTracker | None:
    """Return the tracker of the innermost active run, if any.

    Lets code deep in a call stack log to the current run without having the
    tracker threaded through every signature.
    """
    return _active.get()


# ---------------------------------------------------------------------------
# Run lifecycle
# ---------------------------------------------------------------------------
@contextmanager
def start_run(
    name: str | None = None,
    *,
    settings: Settings | None = None,
    config: Mapping[str, Any] | None = None,
    tags: Sequence[str] = (),
    group: str | None = None,
    job_type: str | None = None,
    notes: str | None = None,
    log_settings: bool = True,
    **wandb_kwargs: Any,
) -> Iterator[ExperimentTracker]:
    """Open a W&B run, yielding a tracker, and always close it.

    A run that raises is finished with a non-zero exit code, so failed
    experiments are visibly failed in the UI instead of looking merely unfinished.

    Args:
        name: Run name. W&B invents one when omitted.
        settings: Settings to configure the run from. Defaults to the
            process-wide settings.
        config: Extra values recorded as run config, merged over the settings.
        tags: Extra tags, on top of ``wandb.tags`` from the config.
        group: Groups related runs (e.g. the folds of one cross-validation).
        job_type: Role of this run within its group, e.g. ``train`` or ``eval``.
        notes: Free-text description.
        log_settings: Record the full resolved settings as run config. Keep this
            on: it is what makes a run self-describing.
        **wandb_kwargs: Passed straight through to ``wandb.init``.

    Yields:
        The tracker bound to the new run.
    """
    import wandb

    settings = settings or get_settings()
    options = settings.wandb

    run_config: dict[str, Any] = settings.as_flat_dict() if log_settings else {}
    provenance = git_metadata()
    run_config.update(provenance)
    run_config.update(config or {})

    all_tags = [*options.tags, *tags]
    if provenance["git_dirty"] == "true":
        # Surfaced as a tag so unreproducible runs are filterable in the UI.
        all_tags.append("dirty")

    run = wandb.init(
        project=options.project,
        entity=options.entity,
        mode=options.mode,
        dir=str(options.run_dir) if options.run_dir else None,
        save_code=options.save_code,
        name=name,
        group=group or options.group,
        job_type=job_type or options.job_type,
        notes=notes,
        tags=all_tags,
        config=run_config,
        **wandb_kwargs,
    )

    tracker = ExperimentTracker(run, settings)
    token = _active.set(tracker)
    logger.info(
        "Started run %r (mode=%s, commit=%s)", tracker.name, options.mode, provenance["git_commit"]
    )
    try:
        yield tracker
    except BaseException:
        logger.exception("Run %r failed", tracker.name)
        tracker.finish(exit_code=1)
        raise
    else:
        tracker.finish()
        if tracker.url:
            logger.info("Run finished: %s", tracker.url)
    finally:
        _active.reset(token)


def track(
    name: str | None = None,
    **run_kwargs: Any,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Wrap a function so that each call is one tracked run.

    If the function declares a ``tracker`` parameter, the active tracker is
    passed in. That parameter must have a default, so that the decorated
    function is still callable with no arguments as far as callers and type
    checkers are concerned. Functions that do not declare it can reach the
    tracker through :func:`active_tracker`.

    Note:
        Always call the decorator, even with no arguments: ``@track()``.

    Args:
        name: Run name. Defaults to the wrapped function's ``__name__``.
        **run_kwargs: Forwarded to :func:`start_run`.

    Returns:
        The decorator.

    Raises:
        TypeError: If ``tracker`` is declared without a default.
    """

    def decorator(fn: Callable[P, R]) -> Callable[P, R]:
        wants_tracker = _declares_injectable_tracker(fn)
        run_name = name or _callable_name(fn)

        @functools.wraps(fn)
        def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
            with start_run(run_name, **run_kwargs) as tracker:
                if wants_tracker and TRACKER_PARAMETER not in kwargs:
                    # Filling in a parameter by name is beyond what a ParamSpec can
                    # describe; the contract is enforced at decoration time instead.
                    kwargs[TRACKER_PARAMETER] = tracker  # ty: ignore[invalid-assignment]
                return fn(*args, **kwargs)

        return wrapper

    return decorator


def _callable_name(fn: Callable[..., object], *, qualified: bool = False) -> str:
    """Best-effort display name: not every callable object has ``__name__``."""
    attribute = "__qualname__" if qualified else "__name__"
    name = getattr(fn, attribute, None)
    return name if isinstance(name, str) else repr(fn)


def _declares_injectable_tracker(fn: Callable[..., object]) -> bool:
    parameter = inspect.signature(fn).parameters.get(TRACKER_PARAMETER)
    if parameter is None:
        return False
    if parameter.default is inspect.Parameter.empty:
        raise TypeError(
            f"{_callable_name(fn, qualified=True)}() declares a {TRACKER_PARAMETER!r} "
            f"parameter with no default, so it looks like a required argument. Declare it "
            f"as `{TRACKER_PARAMETER}: ExperimentTracker | None = None`; @track fills it in."
        )
    return True
