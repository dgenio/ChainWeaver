"""Guided decision points for hybrid flow execution (issue #102).

A :class:`DecisionCallback` is the executor's single extension point for
**runtime tool narrowing** — picking which of several candidate tools to
invoke for a given step based on the live execution context.  It is the
contract that lets ChainWeaver integrate with LLM-driven routers
(contextweaver's ``RoutingDecision``), feature-flag systems, A/B
experiments, or any other deterministic-or-otherwise selector — without
the executor itself becoming an LLM client.

Three executor invariants are preserved:

1. No LLM, network I/O, or randomness lives in :mod:`chainweaver.executor`.
   The callback is the seam through which those concerns can be injected
   from outside; the executor only knows how to *call* the callback.
2. A step with no :attr:`~chainweaver.flow.FlowStep.decision_candidates`
   never invokes the callback — existing flows behave identically.
3. A step with ``decision_candidates`` set but no registered callback
   falls back to the step's own ``tool_name``, so the flow stays runnable
   even without the integration.

Implementing a callback
-----------------------

Two equivalent shapes are supported — pick whichever matches your code
style.

Class-based (recommended for stateful adapters)::

    class MyCallback:
        def decide(self, ctx: DecisionContext) -> str:
            # ctx.candidates is the list to choose from
            return ctx.candidates[0]

    executor = FlowExecutor(registry=reg, decision_callback=MyCallback())

Plain callable (zero ceremony)::

    def pick_first(ctx: DecisionContext) -> str:
        return ctx.candidates[0]

    executor = FlowExecutor(registry=reg, decision_callback=pick_first)

The executor accepts either shape: anything with a ``decide(ctx)`` method
is treated as a structural :class:`DecisionCallback`; a bare callable is
wrapped automatically.

Failure semantics
-----------------

If the callback raises or returns a name that is not in
:attr:`DecisionContext.candidates`, the step fails with
:class:`~chainweaver.exceptions.DecisionCallbackError` — the same
abort-the-step path tool failures take.  The decision point does not
silently fall through to ``tool_name``: a misbehaving callback should be
loud, not silent.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict


class DecisionContext(BaseModel):
    """Snapshot of execution state passed to a :class:`DecisionCallback`.

    Attributes:
        trace_id: UUID4 hex string for the running execution.
        flow_name: Name of the flow being executed.
        step_index: Zero-based position of the step inside the flow.
        step_id: ``DAGFlowStep.step_id`` when the executor is running a
            ``DAGFlow``; ``None`` for linear ``Flow`` execution.
        default_tool_name: The step's static ``tool_name`` — the tool
            that would run if no callback were registered.  Always
            present in :attr:`candidates`.
        candidates: Non-empty list of candidate tool names the callback
            must pick from.  Includes ``default_tool_name``.
        context: Read-only snapshot of the merged execution context at
            the moment the decision is made.  Mutating this dict has no
            effect on the running flow.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    trace_id: str
    flow_name: str
    step_index: int
    step_id: str | None
    default_tool_name: str
    candidates: list[str]
    context: dict[str, Any]


@runtime_checkable
class DecisionCallback(Protocol):
    """Structural protocol for runtime tool-narrowing callbacks (issue #102).

    Implementers expose a single :meth:`decide` method that returns the
    tool name to invoke for a step whose
    :attr:`~chainweaver.flow.FlowStep.decision_candidates` is set.
    """

    def decide(self, ctx: DecisionContext) -> str:
        """Return the tool name to invoke for this step.

        Args:
            ctx: Snapshot of the flow execution state at the decision
                point.  Read-only — mutating ``ctx.context`` has no effect.

        Returns:
            One of the strings in ``ctx.candidates``.  Returning a name
            outside ``ctx.candidates`` causes the step to fail with
            :class:`~chainweaver.exceptions.DecisionCallbackError`.

        Raises:
            Exception: Any exception is caught by the executor, converted
                to a :class:`~chainweaver.exceptions.DecisionCallbackError`,
                and aborts the step like any other tool failure.
        """
        ...


class BaseDecisionCallback:
    """Convenience base class for class-based :class:`DecisionCallback`.

    Subclass and override :meth:`decide`.  Stateful adapters (caching
    decisions, batching upstream RPC calls, etc.) typically inherit from
    this; pure stateless picks can use a plain function and skip the
    class entirely.

    Example::

        class FirstCandidate(BaseDecisionCallback):
            def decide(self, ctx: DecisionContext) -> str:
                return ctx.candidates[0]
    """

    def decide(self, ctx: DecisionContext) -> str:  # pragma: no cover — abstract
        raise NotImplementedError("BaseDecisionCallback subclasses must override 'decide'.")


# Type alias for accepted callback shapes.  The executor wraps plain
# callables into a class-based callback at register time so the call
# site stays uniform.
DecisionCallable = Callable[[DecisionContext], str]


class _CallableDecisionCallback:
    """Adapter that wraps a bare callable into a :class:`DecisionCallback`."""

    __slots__ = ("_fn",)

    def __init__(self, fn: DecisionCallable) -> None:
        self._fn = fn

    def decide(self, ctx: DecisionContext) -> str:
        return self._fn(ctx)


def coerce_decision_callback(
    cb: DecisionCallback | DecisionCallable | None,
) -> DecisionCallback | None:
    """Normalize *cb* into a :class:`DecisionCallback`, or ``None``.

    Accepts either an object implementing ``decide(ctx)`` or a bare
    callable with the equivalent signature.  Bare callables are wrapped
    in an adapter so the executor can call ``cb.decide(ctx)``
    uniformly.

    Args:
        cb: A :class:`DecisionCallback`, a bare callable, or ``None``.

    Returns:
        A :class:`DecisionCallback` instance, or ``None`` if *cb* was
        ``None``.

    Raises:
        TypeError: If *cb* is neither a :class:`DecisionCallback` nor a
            callable.
    """
    if cb is None:
        return None
    if isinstance(cb, DecisionCallback):
        return cb
    if callable(cb):
        return _CallableDecisionCallback(cb)
    raise TypeError(
        f"decision_callback must implement DecisionCallback or be callable; "
        f"got {type(cb).__name__}."
    )
