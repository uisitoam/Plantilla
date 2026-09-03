"""The stages ``packagename-stage`` can invoke, and how a name reaches one.

A stage is a plain function of :class:`~packagename.config.Settings`,
registered under the name the command line will use:

    @stage("aggregate_measurements")
    def aggregate_measurements(settings: Settings) -> None:
        ...

The registry is deliberately thin. It maps names to functions and nothing more:
no inputs, no outputs, no freshness. A stage always does its work when invoked;
deciding *whether* the work is worth doing is the caller's business, and in this
project the caller is a human running ``just etl`` or naming one stage.
Registration order is the pipeline order: ``packagename-stage --all`` runs the
stages in the order their modules register them, so the example below is also
the example of how to chain stages -- register the producer before its consumer.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from packagename.config import Settings

__all__ = ["StageFunction", "UnknownStageError", "registered_stages", "run_stage", "stage"]

#: A stage receives the resolved settings and returns nothing; its result is the
#: files it wrote.
StageFunction = Callable[[Settings], None]

_STAGES: dict[str, StageFunction] = {}


class UnknownStageError(KeyError):
    """Raised when a name matches no registered stage."""


def stage(name: str) -> Callable[[StageFunction], StageFunction]:
    """Register a function as the implementation of a stage.

    Args:
        name: The stage name, as it will be passed to ``packagename-stage``.

    Returns:
        A decorator that registers the function and returns it unchanged, so it
        stays directly callable from a test or a notebook.

    Raises:
        ValueError: If the name is already registered. Two implementations under
            one name would make the command ambiguous, and which one won would
            depend on import order.
    """

    def register(fn: StageFunction) -> StageFunction:
        if name in _STAGES:
            raise ValueError(f"A stage named {name!r} is already registered.")
        _STAGES[name] = fn
        return fn

    return register


def registered_stages() -> Mapping[str, StageFunction]:
    """Return every registered stage, keyed by name, in registration order.

    Returns:
        A copy, so that callers listing the stages cannot mutate the registry.
    """
    return dict(_STAGES)


def run_stage(name: str, settings: Settings) -> None:
    """Run one stage, unconditionally.

    Args:
        name: Name of the stage to run.
        settings: Resolved settings, passed to the stage function.

    Raises:
        UnknownStageError: If no stage is registered under that name.
    """
    try:
        implementation = _STAGES[name]
    except KeyError:
        known = ", ".join(sorted(_STAGES)) or "none"
        raise UnknownStageError(f"Unknown stage {name!r}. Registered stages: {known}.") from None
    implementation(settings)
