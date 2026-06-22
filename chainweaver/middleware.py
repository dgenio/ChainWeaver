"""Lifecycle hook / middleware API for :class:`~chainweaver.executor.FlowExecutor` (issue #131).

A :class:`FlowExecutorMiddleware` is a plain-old class that implements any
subset of four lifecycle hooks::

    on_flow_start  → fires once at the start of every flow execution
        for each step:
            on_step_start  → fires after inputs are resolved
            on_step_end    → fires once the step's ``StepRecord`` is built
                            (success *or* failure)
    on_flow_end    → fires once after the ``ExecutionResult`` is built

Middlewares are registered via the ``middleware=`` keyword on
:class:`~chainweaver.executor.FlowExecutor` (or later via
:meth:`~chainweaver.executor.FlowExecutor.add_middleware`) and are invoked
in **registration order**.

Failure semantics — guaranteed
------------------------------

An exception raised from any hook is caught by the executor, logged at
``WARNING`` level via the ``chainweaver.middleware`` logger, and the flow
execution continues uninterrupted.  Observability bugs must never abort
production flows.

Contexts are Pydantic models with everything a middleware might need.
They carry plain strings for error reporting (``error_type`` /
``error_message``) — never live :class:`Exception` instances — so the
contexts round-trip through ``model_dump_json`` just like
:class:`~chainweaver.executor.StepRecord` and
:class:`~chainweaver.executor.ExecutionResult`.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict

from chainweaver.tools import ToolChunk

if TYPE_CHECKING:  # pragma: no cover — import-cycle guard
    from chainweaver.executor import ExecutionResult, StepRecord


class FlowStartContext(BaseModel):
    """Context passed to :meth:`FlowExecutorMiddleware.on_flow_start`.

    Attributes:
        trace_id: UUID4 hex string that correlates every hook fired during
            this execution.
        flow_name: Name of the flow about to execute.
        flow_version: PEP 440 version string of the flow being executed.
        initial_input: The initial context dictionary passed to
            :meth:`~chainweaver.executor.FlowExecutor.execute_flow`.
        started_at: UTC timestamp recorded at the very top of the execution.
        total_steps: Number of steps in the flow (``len(flow.steps)``).
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    trace_id: str
    flow_name: str
    flow_version: str
    initial_input: dict[str, Any]
    started_at: datetime
    total_steps: int


class StepStartContext(BaseModel):
    """Context passed to :meth:`FlowExecutorMiddleware.on_step_start`.

    Fired **after** the step's inputs have been resolved against the
    current execution context.  Steps that fail before input resolution
    (tool-not-found, input-mapping errors) do not produce an
    ``on_step_start`` call — their :class:`StepStartContext` would have
    no resolved inputs to carry.  ``on_step_end`` still fires for those
    failures, so a middleware can always rely on seeing the final
    :class:`~chainweaver.executor.StepRecord`.

    Attributes:
        trace_id: UUID4 hex string matching the parent flow's trace id.
        flow_name: Name of the flow being executed.
        step_index: Zero-based position of the step in the flow.
        tool_name: Name of the tool about to be invoked.
        inputs: The resolved inputs that will be passed to the tool's
            ``input_schema`` validator and then to its callable.
        started_at: UTC timestamp recorded at the start of the step.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    trace_id: str
    flow_name: str
    step_index: int
    tool_name: str
    inputs: dict[str, Any]
    started_at: datetime


class StepEndContext(BaseModel):
    """Context passed to :meth:`FlowExecutorMiddleware.on_step_end`.

    Fired exactly once per step, on both the success and failure paths.
    The ``step_record`` field carries the immutable record that will be
    appended to ``ExecutionResult.execution_log``; inspect
    ``step_record.success`` to branch.

    Attributes:
        trace_id: UUID4 hex string matching the parent flow's trace id.
        flow_name: Name of the flow being executed.
        step_record: The :class:`~chainweaver.executor.StepRecord` for
            this step, complete with timing, retry counts, and any
            error strings.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    trace_id: str
    flow_name: str
    step_record: StepRecord


class StepChunkContext(BaseModel):
    """Context passed to ``on_step_chunk`` for a streaming step (issue #320).

    Fired once per :class:`~chainweaver.tools.ToolChunk` produced by a
    :class:`~chainweaver.tools.StreamingTool` while it runs under
    :meth:`~chainweaver.executor.FlowExecutor.stream_flow_async` — interleaved
    between that step's ``on_step_start`` and ``on_step_end``.  Non-streaming
    tools and the non-streaming execution paths never fire it, so this hook is
    purely additive.

    Attributes:
        trace_id: UUID4 hex string matching the parent flow's trace id.
        flow_name: Name of the flow being executed.
        step_index: Zero-based position of the streaming step in the flow.
        tool_name: Name of the streaming tool producing the chunk.
        chunk: The :class:`~chainweaver.tools.ToolChunk` just produced.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    trace_id: str
    flow_name: str
    step_index: int
    tool_name: str
    chunk: ToolChunk


class FlowEndContext(BaseModel):
    """Context passed to :meth:`FlowExecutorMiddleware.on_flow_end`.

    Fired exactly once per :meth:`~chainweaver.executor.FlowExecutor.execute_flow`
    call, after the :class:`~chainweaver.executor.ExecutionResult` has
    been fully populated.

    Attributes:
        trace_id: UUID4 hex string matching the parent flow's trace id.
        flow_name: Name of the flow that just finished.
        result: The fully populated
            :class:`~chainweaver.executor.ExecutionResult`.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    trace_id: str
    flow_name: str
    result: ExecutionResult


@runtime_checkable
class FlowExecutorMiddleware(Protocol):
    """Lifecycle hook protocol consumed by :class:`~chainweaver.executor.FlowExecutor`.

    Implement any subset of the four hooks; each has a no-op default so
    middlewares can pick exactly what they need.  Hook exceptions are
    caught and logged by the executor — middlewares cannot abort a flow.

    Example::

        from chainweaver import FlowExecutor, FlowExecutorMiddleware

        class StepCounter:
            def __init__(self) -> None:
                self.successful_steps = 0

            def on_step_end(self, ctx):
                if ctx.step_record.success:
                    self.successful_steps += 1

        counter = StepCounter()
        executor = FlowExecutor(registry=registry, middleware=[counter])
        executor.execute_flow("etl", {"date": "2026-05-15"})
        assert counter.successful_steps >= 1
    """

    def on_flow_start(self, ctx: FlowStartContext) -> None:
        """Called once at the start of every flow execution."""
        ...

    def on_step_start(self, ctx: StepStartContext) -> None:
        """Called after a step's inputs are resolved, before tool invocation."""
        ...

    def on_step_end(self, ctx: StepEndContext) -> None:
        """Called once per step, on both success and failure paths."""
        ...

    def on_flow_end(self, ctx: FlowEndContext) -> None:
        """Called once after the ``ExecutionResult`` has been built."""
        ...


class BaseMiddleware:
    """No-op base class for :class:`FlowExecutorMiddleware` implementations.

    Inheriting from :class:`BaseMiddleware` lets you implement only the
    hooks you care about — the others default to no-ops.  Inheritance is
    optional; any class with the four method names satisfies the
    :class:`FlowExecutorMiddleware` :class:`~typing.Protocol`.
    """

    def on_flow_start(self, ctx: FlowStartContext) -> None:
        """Default no-op."""

    def on_step_start(self, ctx: StepStartContext) -> None:
        """Default no-op."""

    def on_step_end(self, ctx: StepEndContext) -> None:
        """Default no-op."""

    def on_step_chunk(self, ctx: StepChunkContext) -> None:
        """Default no-op (issue #320).

        Fired per :class:`~chainweaver.tools.ToolChunk` while a streaming step
        runs under ``stream_flow_async``.  Optional and additive — it is not
        part of the :class:`FlowExecutorMiddleware` Protocol, so existing
        middleware are unaffected; the executor dispatches it only to
        middleware that define it.
        """

    def on_flow_end(self, ctx: FlowEndContext) -> None:
        """Default no-op."""


__all__ = [
    "BaseMiddleware",
    "FlowEndContext",
    "FlowExecutorMiddleware",
    "FlowStartContext",
    "StepChunkContext",
    "StepEndContext",
    "StepStartContext",
]
