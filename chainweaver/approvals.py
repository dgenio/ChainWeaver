"""Execution-time approval seam for ToolSafetyContract enforcement (issue #356).

ChainWeaver already ships a rich, composable safety vocabulary
(:mod:`chainweaver.contracts`): side-effect levels, approval flags, dry-run
support, and ``merge_safety()``.  In v1 the contract was purely *advisory* —
:class:`~chainweaver.executor.FlowExecutor` never acted on it.  An
:class:`ApprovalCallback` is the opt-in seam that makes the contract
*actionable*: when a step's effective contract has ``requires_approval=True``
and a callback is registered, the executor asks the callback to approve the
step **before** the tool function runs.

The seam deliberately mirrors :class:`~chainweaver.decisions.DecisionCallback`
(issue #102): the executor only ever *calls* a user-supplied callback, so the
three hard executor invariants (no LLM, no network I/O, no randomness in
:mod:`chainweaver.executor`) are preserved — the callback is where a host can
inject a human prompt, a policy service, or an RPC, none of which the executor
performs itself.

Two equivalent callback shapes are accepted, exactly like the decision seam::

    # Class-based
    class CliApprover:
        def approve(self, ctx: ApprovalContext) -> ApprovalDecision:
            return ApprovalDecision.APPROVE

    # Plain callable
    def approve_all(ctx: ApprovalContext) -> ApprovalDecision:
        return ApprovalDecision.APPROVE

    FlowExecutor(registry, approval_callback=approve_all)

Failure semantics: a ``DENY`` decision, a callback that raises, or a callback
that returns a non-:class:`ApprovalDecision` aborts the step with
:class:`~chainweaver.exceptions.ApprovalDeniedError` and a failed
``StepRecord`` — the same abort-the-step path tool failures take.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from chainweaver.contracts import ToolSafetyContract


class ApprovalDecision(str, Enum):
    """Explicit outcome of an :class:`ApprovalCallback` — no boolean ambiguity.

    Attributes:
        APPROVE: Allow the step's tool to run.
        DENY: Refuse the step; the executor aborts it with
            :class:`~chainweaver.exceptions.ApprovalDeniedError`.
    """

    APPROVE = "approve"
    DENY = "deny"


class ApprovalContext(BaseModel):
    """Snapshot of execution state passed to an :class:`ApprovalCallback`.

    Attributes:
        trace_id: UUID4 hex string for the running execution.
        flow_name: Name of the flow being executed.
        step_index: Zero-based position of the step inside the flow.
        step_id: ``DAGFlowStep.step_id`` when running a ``DAGFlow``; ``None``
            for linear ``Flow`` execution.
        tool_name: Name of the tool the step is about to run.
        inputs: The step's resolved (already redacted, when a redaction policy
            is configured) inputs.  Read-only — mutating has no effect.
        safety: The effective :class:`ToolSafetyContract` that triggered the
            approval gate.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    trace_id: str
    flow_name: str
    step_index: int
    step_id: str | None
    tool_name: str
    inputs: dict[str, Any]
    safety: ToolSafetyContract


class ApprovalRecord(BaseModel):
    """Audit record of an approval decision, attached to ``StepRecord.approval``.

    Persisted on the trace so a completed :class:`~chainweaver.executor.ExecutionResult`
    is a full record of which side-effecting steps were gated and how they were
    resolved.

    Attributes:
        decision: The :class:`ApprovalDecision` the callback returned (or
            ``DENY`` when the callback raised / no callback was registered under
            ``strict_safety``).
        reason: Optional human-readable explanation carried alongside the
            decision.
    """

    model_config = ConfigDict(frozen=True)

    decision: ApprovalDecision
    reason: str | None = None


@runtime_checkable
class ApprovalCallback(Protocol):
    """Structural protocol for execution-time approval callbacks (issue #356)."""

    def approve(self, ctx: ApprovalContext) -> ApprovalDecision:
        """Return :attr:`ApprovalDecision.APPROVE` or :attr:`ApprovalDecision.DENY`.

        Args:
            ctx: Snapshot of the flow execution state at the approval point.

        Returns:
            An :class:`ApprovalDecision`.  Returning anything else aborts the
            step with :class:`~chainweaver.exceptions.ApprovalDeniedError`.

        Raises:
            Exception: Any exception is caught by the executor, converted to an
                :class:`~chainweaver.exceptions.ApprovalDeniedError`, and aborts
                the step like any other tool failure.
        """
        ...


class BaseApprovalCallback:
    """Convenience base class for class-based :class:`ApprovalCallback`.

    Subclass and override :meth:`approve`.  Stateful approvers (batching
    prompts, caching policy decisions) typically inherit from this; pure
    stateless approvers can use a plain function and skip the class entirely.
    """

    def approve(self, ctx: ApprovalContext) -> ApprovalDecision:  # pragma: no cover — abstract
        raise NotImplementedError("BaseApprovalCallback subclasses must override 'approve'.")


# Type alias for accepted callback shapes; bare callables are wrapped so the
# executor's call site stays uniform (``cb.approve(ctx)``).
ApprovalCallable = Callable[[ApprovalContext], ApprovalDecision]


class _CallableApprovalCallback:
    """Adapter that wraps a bare callable into an :class:`ApprovalCallback`."""

    __slots__ = ("_fn",)

    def __init__(self, fn: ApprovalCallable) -> None:
        self._fn = fn

    def approve(self, ctx: ApprovalContext) -> ApprovalDecision:
        return self._fn(ctx)


def coerce_approval_callback(
    cb: ApprovalCallback | ApprovalCallable | None,
) -> ApprovalCallback | None:
    """Normalize *cb* into an :class:`ApprovalCallback`, or ``None``.

    Accepts either an object implementing ``approve(ctx)`` or a bare callable
    with the equivalent signature.  Bare callables are wrapped so the executor
    can call ``cb.approve(ctx)`` uniformly.

    Args:
        cb: An :class:`ApprovalCallback`, a bare callable, or ``None``.

    Returns:
        An :class:`ApprovalCallback` instance, or ``None`` if *cb* was ``None``.

    Raises:
        TypeError: If *cb* is neither an :class:`ApprovalCallback` nor callable.
    """
    if cb is None:
        return None
    if isinstance(cb, ApprovalCallback):
        return cb
    if callable(cb):
        return _CallableApprovalCallback(cb)
    raise TypeError(
        f"approval_callback must implement ApprovalCallback or be callable; "
        f"got {type(cb).__name__}."
    )
