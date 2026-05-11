"""Runtime flow observation and trace capture (issue #11).

While ``ExecutionResult`` (issue #20) records *every* compiled flow run,
many tool sequences happen *outside* of registered flows: agents call tools
ad-hoc at runtime via LLM decisions.  ``TraceRecorder`` captures those
sequences so that recurring patterns can later be promoted into compiled
flows.

The recorder is opt-in.  When a :class:`~chainweaver.executor.FlowExecutor`
is constructed with a ``trace_recorder``, every ``execute_flow`` call also
emits a matching :class:`ObservedTrace` for parity between compiled and
ad-hoc traces.  Standalone usage (calling :meth:`TraceRecorder.start_trace`
/ :meth:`record_step` / :meth:`end_trace` directly) lets agents capture
sequences that don't go through a flow at all.

In-memory storage only — persistence is out of scope for v0.x.
"""

from __future__ import annotations

import time
import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _now_utc() -> datetime:
    """Return the current UTC time as a timezone-aware ``datetime``."""
    return datetime.now(timezone.utc)


class ObservedStep(BaseModel):
    """A single tool invocation captured by :class:`TraceRecorder`.

    Attributes:
        tool_name: Name of the tool that was called.
        inputs: Raw input dictionary as supplied to the tool.
        outputs: Raw output dictionary returned by the tool, or ``None`` if
            the call failed.
        recorded_at: UTC timestamp when the step was recorded.
        duration_ms: Wall-clock duration of the step in milliseconds.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    tool_name: str
    inputs: dict[str, Any]
    outputs: dict[str, Any] | None = None
    recorded_at: datetime
    duration_ms: float = 0.0


class ObservedTrace(BaseModel):
    """An ad-hoc tool sequence captured outside (or alongside) a compiled flow.

    Traces are immutable once :meth:`TraceRecorder.end_trace` has been
    called: the ``ended_at`` timestamp marks completion.

    Attributes:
        trace_id: UUID4 hex string identifying the trace.
        source: Free-form label describing where the trace came from
            (``"agent-v2"``, ``"manual-test"``, ``"executor"`` …).
        started_at: UTC timestamp when ``start_trace`` was called.
        ended_at: UTC timestamp when ``end_trace`` was called, or ``None``
            for in-progress traces.
        steps: Recorded :class:`ObservedStep` entries, in call order.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    trace_id: str
    source: str
    started_at: datetime
    ended_at: datetime | None = None
    steps: list[ObservedStep] = Field(default_factory=list)


class TraceRecorder:
    """In-memory recorder for runtime tool sequences.

    Typical usage by an agent capturing an ad-hoc sequence::

        recorder = TraceRecorder()
        trace_id = recorder.start_trace(source="agent-v2")
        recorder.record_step(trace_id, "fetch_data", inputs={...}, outputs={...})
        recorder.record_step(trace_id, "summarize", inputs={...}, outputs={...})
        finished = recorder.end_trace(trace_id)

    Or via :class:`~chainweaver.executor.FlowExecutor` integration: when an
    executor is created with ``trace_recorder=recorder``, every
    ``execute_flow`` call adds an :class:`ObservedTrace` automatically, so
    compiled flow runs and ad-hoc agent sequences share a uniform store.

    Storage is in-memory and intentionally simple; persistence is deferred
    (see issue #16 for a future protocol-based store).
    """

    def __init__(self) -> None:
        self._open: dict[str, ObservedTrace] = {}
        self._open_perf_starts: dict[str, float] = {}
        self._closed: list[ObservedTrace] = []
        self._step_perf_starts: dict[str, float] = {}

    # ------------------------------------------------------------------
    # Trace lifecycle
    # ------------------------------------------------------------------

    def start_trace(self, source: str) -> str:
        """Open a new trace and return its trace id."""
        trace_id = uuid.uuid4().hex
        self._open[trace_id] = ObservedTrace(
            trace_id=trace_id,
            source=source,
            started_at=_now_utc(),
        )
        self._open_perf_starts[trace_id] = time.perf_counter()
        return trace_id

    def record_step(
        self,
        trace_id: str,
        tool_name: str,
        *,
        inputs: dict[str, Any],
        outputs: dict[str, Any] | None = None,
        duration_ms: float | None = None,
    ) -> None:
        """Append a recorded step to the open trace identified by *trace_id*.

        Args:
            trace_id: Id returned by :meth:`start_trace`.
            tool_name: Name of the tool that was invoked.
            inputs: Raw input dictionary.
            outputs: Raw output dictionary, or ``None`` if the step failed.
            duration_ms: Optional wall-clock duration; otherwise computed
                relative to the previous ``record_step`` / ``start_trace``
                call.

        Raises:
            KeyError: When *trace_id* is not an open trace.
        """
        if trace_id not in self._open:
            raise KeyError(f"Unknown or closed trace_id '{trace_id}'.")
        now_perf = time.perf_counter()
        if duration_ms is None:
            previous = self._step_perf_starts.get(trace_id, self._open_perf_starts[trace_id])
            duration_ms = (now_perf - previous) * 1000.0
        self._step_perf_starts[trace_id] = now_perf
        self._open[trace_id].steps.append(
            ObservedStep(
                tool_name=tool_name,
                inputs=dict(inputs),
                outputs=dict(outputs) if outputs is not None else None,
                recorded_at=_now_utc(),
                duration_ms=duration_ms,
            )
        )

    def end_trace(self, trace_id: str) -> ObservedTrace:
        """Close *trace_id* and return the resulting :class:`ObservedTrace`.

        After this call the trace appears in :meth:`list_traces` and the
        ``trace_id`` is no longer accepted by :meth:`record_step`.

        Raises:
            KeyError: When *trace_id* is not an open trace.
        """
        if trace_id not in self._open:
            raise KeyError(f"Unknown or closed trace_id '{trace_id}'.")
        trace = self._open.pop(trace_id)
        self._open_perf_starts.pop(trace_id, None)
        self._step_perf_starts.pop(trace_id, None)
        trace.ended_at = _now_utc()
        self._closed.append(trace)
        return trace

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    def list_traces(self, *, include_open: bool = False) -> list[ObservedTrace]:
        """Return all traces.

        Args:
            include_open: When ``True`` also include in-progress traces.
                Defaults to ``False``: only completed traces are returned.
        """
        traces = list(self._closed)
        if include_open:
            traces.extend(self._open.values())
        return traces

    def __len__(self) -> int:
        return len(self._closed) + len(self._open)
