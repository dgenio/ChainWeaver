"""Content-safety guardrail seam for flow steps (issue #317).

Production deployments (regulated telco / finance, etc.) often require that
**every** tool invocation pass content-safety checks — block prompt injection or
disallowed inputs before a tool runs, and moderate outputs after. Today the only
way to enforce that is to embed the check inside every tool function, which is
boilerplate and easy to forget.

A :class:`GuardrailCallback` is the opt-in executor seam that lifts the check out
of the tool: when a ``guardrail_callback`` is registered on the executor, it is
consulted at each guardrail *stage* and may **block** the step by raising (any
exception is normalised to
:class:`~chainweaver.exceptions.GuardrailViolationError`, aborting the step with
a failed ``StepRecord`` — the same abort path a denied approval takes).

The seam deliberately mirrors :class:`~chainweaver.approvals.ApprovalCallback`
(issue #356) and :class:`~chainweaver.decisions.DecisionCallback` (#102): the
executor only ever *calls* a user-supplied callback, so the three hard executor
invariants (no LLM, no network I/O, no randomness in
:mod:`chainweaver.executor`) are preserved — the callback is where a host injects
a moderation model, a PII detector, or an injection classifier, none of which the
executor performs itself.

Two callback shapes are accepted, exactly like the approval seam::

    # Class-based
    class BillingGuardrails:
        def check(self, ctx: GuardrailContext) -> None:
            if ctx.stage == "input" and _looks_like_injection(ctx.inputs):
                raise ValueError("possible prompt injection")

    # Plain callable
    def block_ssn(ctx: GuardrailContext) -> None:
        if "ssn" in ctx.inputs:
            raise ValueError("SSN not allowed in tool input")

    FlowExecutor(registry, guardrail_callback=block_ssn)

Stage scope (issue #317): the executor currently invokes the callback at the
``"input"`` stage — before each tool runs, and before the step cache is
consulted, so a blocked input can never even return a cached result. The
:class:`GuardrailContext` carries a ``stage`` field (``"input"`` / ``"output"``)
so output-stage moderation can be added at the same seam without an API change;
until then a callback is only ever called with ``stage="input"``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

GuardrailStage = Literal["input", "output"]


class GuardrailContext(BaseModel):
    """Snapshot of execution state passed to a :class:`GuardrailCallback`.

    Attributes:
        trace_id: UUID4 hex string for the running execution.
        flow_name: Name of the flow being executed.
        step_index: Zero-based position of the step inside the flow.
        step_id: ``DAGFlowStep.step_id`` when running a ``DAGFlow``; ``None``
            for linear ``Flow`` execution.
        tool_name: Name of the tool the step is about to run (input stage).
        stage: The guardrail stage: ``"input"`` (before the tool runs) or
            ``"output"`` (after — reserved for a future release).
        inputs: The step's resolved inputs (already redacted when a redaction
            policy is configured). Read-only — mutating has no effect.
        outputs: The tool's validated outputs at the ``"output"`` stage;
            ``None`` at the ``"input"`` stage.
    """

    model_config = ConfigDict(frozen=True)

    trace_id: str
    flow_name: str
    step_index: int
    step_id: str | None
    tool_name: str
    stage: GuardrailStage
    inputs: dict[str, Any]
    outputs: dict[str, Any] | None = None


@runtime_checkable
class GuardrailCallback(Protocol):
    """Structural protocol for content-safety guardrail callbacks (issue #317)."""

    def check(self, ctx: GuardrailContext) -> None:
        """Inspect *ctx* and raise to block the step, or return ``None`` to allow it.

        Args:
            ctx: Snapshot of the flow execution state at the guardrail point.

        Raises:
            Exception: Any exception blocks the step; the executor normalises it
                to :class:`~chainweaver.exceptions.GuardrailViolationError` and
                aborts the step like any other failure.
        """
        ...


class BaseGuardrailCallback:
    """Convenience base class for class-based :class:`GuardrailCallback`.

    Subclass and override :meth:`check`. Stateful guardrails (a cached
    classifier, a policy client) typically inherit from this; a pure stateless
    guardrail can use a plain function and skip the class entirely.
    """

    def check(self, ctx: GuardrailContext) -> None:  # pragma: no cover — abstract
        raise NotImplementedError("BaseGuardrailCallback subclasses must override 'check'.")


# Type alias for accepted callback shapes; bare callables are wrapped so the
# executor's call site stays uniform (``cb.check(ctx)``).
GuardrailCallable = Callable[[GuardrailContext], None]


class _CallableGuardrailCallback:
    """Adapter that wraps a bare callable into a :class:`GuardrailCallback`."""

    __slots__ = ("_fn",)

    def __init__(self, fn: GuardrailCallable) -> None:
        self._fn = fn

    def check(self, ctx: GuardrailContext) -> None:
        self._fn(ctx)


def coerce_guardrail_callback(
    cb: GuardrailCallback | GuardrailCallable | None,
) -> GuardrailCallback | None:
    """Normalize *cb* into a :class:`GuardrailCallback`, or ``None``.

    Accepts either an object implementing ``check(ctx)`` or a bare callable with
    the equivalent signature. Bare callables are wrapped so the executor can call
    ``cb.check(ctx)`` uniformly.

    Args:
        cb: A :class:`GuardrailCallback`, a bare callable, or ``None``.

    Returns:
        A :class:`GuardrailCallback` instance, or ``None`` if *cb* was ``None``.

    Raises:
        TypeError: If *cb* is neither a :class:`GuardrailCallback` nor callable.
    """
    if cb is None:
        return None
    if isinstance(cb, GuardrailCallback):
        return cb
    if callable(cb):
        return _CallableGuardrailCallback(cb)
    raise TypeError(
        f"guardrail_callback must implement GuardrailCallback or be callable; "
        f"got {type(cb).__name__}."
    )


__all__ = [
    "BaseGuardrailCallback",
    "GuardrailCallable",
    "GuardrailCallback",
    "GuardrailContext",
    "GuardrailStage",
    "coerce_guardrail_callback",
]
