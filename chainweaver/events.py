"""Streamable flow lifecycle events (issue #134).

:class:`FlowEvent` is the payload yielded by
:meth:`~chainweaver.executor.FlowExecutor.stream_flow`.  Events are
emitted at the same boundaries the
:class:`~chainweaver.middleware.FlowExecutorMiddleware` hooks fire,
so there is a single source of truth for the step boundary — no
parallel "streaming executor" to drift out of sync.

Event order
-----------

For every successful or failed flow execution the stream emits::

    FlowEvent(kind="flow_start", ...)
    FlowEvent(kind="step_start", step_index=0, tool_name="...", inputs={...})
    FlowEvent(kind="step_end",   step_index=0, step_record=StepRecord(...))
    FlowEvent(kind="step_start", step_index=1, ...)
    FlowEvent(kind="step_end",   step_index=1, ...)
    ...
    FlowEvent(kind="flow_end",   result=ExecutionResult(...))

``flow_end`` always fires, even on failure.  Steps that fail before
input resolution (tool-not-found, input-mapping) emit ``step_end``
without a preceding ``step_start`` — see the middleware module for
the underlying lifecycle contract.

Cancellation
------------

The sync :meth:`~chainweaver.executor.FlowExecutor.stream_flow`
generator does **not** cancel in-flight execution when the consumer
stops iterating: a background worker thread drives the flow to
completion, then exits.  Document this loudly in any UI you build.
The async variant (gated on issue #80) is expected to support
:class:`asyncio.CancelledError`-driven cancellation cleanly.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:  # pragma: no cover — import-cycle guard
    from chainweaver.executor import ExecutionResult, StepRecord


FlowEventKind = Literal["flow_start", "step_start", "step_end", "flow_end"]


class FlowEvent(BaseModel):
    """One streamable lifecycle event from :meth:`FlowExecutor.stream_flow`.

    A single flat model carries every event variant so the JSON shape is
    trivially consumable from non-Python clients (TypeScript UIs,
    arbitrary HTTP consumers, etc.).  The ``kind`` field discriminates;
    exactly which of the optional fields are populated depends on
    ``kind``:

    +--------------+--------------------------------------------------------------+
    | ``kind``     | Populated fields                                             |
    +==============+==============================================================+
    | flow_start   | ``flow_version``, ``initial_input``, ``total_steps``,        |
    |              | ``is_resume``                                                |
    +--------------+--------------------------------------------------------------+
    | step_start   | ``step_index``, ``tool_name``, ``inputs``                    |
    +--------------+--------------------------------------------------------------+
    | step_end     | ``step_index``, ``tool_name``, ``step_record``               |
    +--------------+--------------------------------------------------------------+
    | flow_end     | ``result``                                                   |
    +--------------+--------------------------------------------------------------+

    All variants populate ``flow_name``, ``trace_id``, and ``timestamp``.

    Attributes:
        kind: One of ``"flow_start"`` / ``"step_start"`` /
            ``"step_end"`` / ``"flow_end"``.
        flow_name: Name of the flow being executed.
        trace_id: UUID4 hex string correlating every event in this
            stream with logs and middleware contexts.
        timestamp: UTC timestamp when the event was emitted by the
            executor.
        flow_version: PEP 440 flow version (``flow_start`` only).
        initial_input: Initial context dictionary (``flow_start`` only).
        total_steps: ``len(flow.steps)`` (``flow_start`` only).
        is_resume: ``True`` when the event was emitted by
            :meth:`FlowExecutor.resume_flow` (``flow_start`` only).
            Mirrors the field of the same name on
            :class:`~chainweaver.middleware.FlowStartContext`.
        step_index: Zero-based step position (``step_start`` /
            ``step_end`` only).
        tool_name: Name of the tool being invoked (``step_start`` /
            ``step_end`` only).
        inputs: Resolved inputs about to be passed to the tool
            (``step_start`` only).
        step_record: Final :class:`~chainweaver.executor.StepRecord`
            for the step (``step_end`` only) — inspect
            ``step_record.success`` to branch.
        result: Full :class:`~chainweaver.executor.ExecutionResult`
            (``flow_end`` only).
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    kind: FlowEventKind
    flow_name: str
    trace_id: str
    timestamp: datetime
    flow_version: str | None = None
    initial_input: dict[str, Any] | None = None
    total_steps: int | None = None
    is_resume: bool | None = None
    step_index: int | None = None
    tool_name: str | None = None
    inputs: dict[str, Any] | None = None
    step_record: StepRecord | None = None
    result: ExecutionResult | None = None


__all__ = ["FlowEvent", "FlowEventKind"]
