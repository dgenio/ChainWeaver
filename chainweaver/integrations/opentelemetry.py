"""OpenTelemetry trace exporter for ChainWeaver flows (issue #126).

Bridges :class:`~chainweaver.executor.ExecutionResult` and the
:class:`~chainweaver.middleware.FlowExecutorMiddleware` lifecycle hooks
to OpenTelemetry spans.  Two consumption paths are supported:

1. **Live emission via middleware** — :class:`OTelTraceExporter`
   implements the :class:`FlowExecutorMiddleware` Protocol.  Register
   it on the executor and a parent flow span + one child step span
   per :class:`StepRecord` are emitted as the flow runs.

2. **After-the-fact export** — :func:`export_result_to_otel` walks a
   completed :class:`ExecutionResult` and emits spans with the
   recorded timestamps.  Useful for replayed traces, batch
   reconstruction, and anything that didn't run through the live
   middleware path.

Both paths preserve the original ``ExecutionResult.trace_id`` as a
``chainweaver.trace_id`` attribute, so spans link back to the
ChainWeaver execution log unambiguously.

Optional extra
--------------

This module requires ``opentelemetry-api``.  Install with::

    pip install 'chainweaver[otel]'

The third-party import is guarded so importing this module without the
extra raises a clear :class:`ImportError` instead of a cryptic
``ModuleNotFoundError`` deep in execution.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

try:  # Optional dependency.
    from opentelemetry.trace import (
        Status,
        StatusCode,
        Tracer,
    )
except ImportError as exc:  # pragma: no cover — depends on install layout
    raise ImportError(
        "chainweaver.integrations.opentelemetry requires opentelemetry-api. "
        "Install with: pip install 'chainweaver[otel]'."
    ) from exc

from chainweaver.middleware import (
    BaseMiddleware,
    FlowEndContext,
    FlowStartContext,
    StepEndContext,
    StepStartContext,
)

if TYPE_CHECKING:  # pragma: no cover — type-only references
    from opentelemetry.trace import Span

    from chainweaver.executor import ExecutionResult


_FLOW_SPAN_PREFIX = "chainweaver.flow."
_STEP_SPAN_PREFIX = "chainweaver.tool."


def _datetime_to_ns(dt: datetime) -> int:
    """Convert a timezone-aware ``datetime`` to nanoseconds since the epoch.

    ChainWeaver uses timezone-aware UTC datetimes throughout
    (``_now_utc`` in :mod:`chainweaver.executor`), so naive datetimes
    should never reach this module.  We assert explicitly rather than
    silently calling ``dt.replace(tzinfo=timezone.utc)``, which would
    reinterpret the wall-clock value as UTC and skew span timestamps
    by the local timezone offset if the input was actually local
    time.  A surfaced assertion is easier to debug than wrong spans.
    """
    assert dt.tzinfo is not None, (
        "_datetime_to_ns expects timezone-aware datetimes — ChainWeaver "
        "uses tz-aware UTC everywhere; a naive datetime here indicates a "
        "bug in the caller."
    )
    return int(dt.timestamp() * 1_000_000_000)


def _set_step_attributes(
    span: Span,
    *,
    trace_id: str,
    flow_name: str,
    step_index: int,
    tool_name: str,
    inputs: dict[str, Any] | None = None,
) -> None:
    span.set_attribute("chainweaver.trace_id", trace_id)
    span.set_attribute("chainweaver.flow_name", flow_name)
    span.set_attribute("chainweaver.step_index", step_index)
    span.set_attribute("chainweaver.tool_name", tool_name)
    if inputs is not None:
        # input_keys is reported because logging the raw inputs is a
        # privacy and cardinality hazard; downstream consumers can
        # capture the keys themselves and tail-correlate with the
        # ExecutionResult.execution_log when full input bodies are
        # required.
        span.set_attribute("chainweaver.step.input_keys", sorted(inputs.keys()))


def _finalize_step_span(
    span: Span,
    *,
    step_record: Any,
) -> None:
    """Apply the ``StepRecord``'s tail data to a step span and end it."""
    span.set_attribute("chainweaver.step.success", step_record.success)
    span.set_attribute("chainweaver.step.duration_ms", step_record.duration_ms)
    span.set_attribute("chainweaver.step.retry_count", step_record.retry_count)
    span.set_attribute("chainweaver.step.cached", step_record.cached)
    span.set_attribute("chainweaver.step.skipped", step_record.skipped)
    if not step_record.success:
        span.set_attribute("chainweaver.step.error_type", step_record.error_type or "")
        span.set_status(Status(StatusCode.ERROR, step_record.error_message or ""))
    end_ns = _datetime_to_ns(step_record.ended_at)
    span.end(end_time=end_ns)


class OTelTraceExporter(BaseMiddleware):
    """Emit OpenTelemetry spans for every flow execution via the middleware seam.

    Register on a :class:`FlowExecutor` to start streaming spans
    immediately::

        from opentelemetry import trace
        from chainweaver.integrations.opentelemetry import OTelTraceExporter

        tracer = trace.get_tracer("my-app")
        executor = FlowExecutor(
            registry=registry,
            middleware=[OTelTraceExporter(tracer=tracer)],
        )
        executor.execute_flow("my_flow", {"url": "https://..."})

    Each execution emits:

    - One parent span named ``chainweaver.flow.{flow_name}`` covering
      the whole run.  Attributes include ``chainweaver.trace_id``,
      ``chainweaver.flow_version``, ``chainweaver.total_steps``, and
      ``chainweaver.success`` (set at flow end).
    - One child span per :class:`StepRecord` named
      ``chainweaver.tool.{tool_name}``, with timing taken from the
      record's wall-clock timestamps and ``chainweaver.step.*``
      attributes describing inputs (keys only), success, duration,
      retry count, cache status, and skip status.
    - Failed steps set the span status to ``ERROR`` and record
      ``chainweaver.step.error_type`` + the error message in the
      status description.  Live exceptions are *not* attached to the
      span — :class:`StepRecord` uses the same string-based
      convention.

    Concurrency: state is keyed by ``trace_id`` (``self._flow_spans``
    and ``self._step_spans`` are dicts), so a single
    :class:`OTelTraceExporter` instance can be safely shared across
    sequential or interleaved executions on **distinct** trace ids —
    the parent span of run A is not stomped on when run B's
    ``on_flow_start`` fires.  Concurrent flows on the *same*
    :class:`FlowExecutor` are still not supported (see the executor's
    own concurrency note); concurrent flows on **distinct**
    executors sharing one exporter are fine.
    """

    def __init__(self, tracer: Tracer) -> None:
        self._tracer = tracer
        # Per-trace state.  Keyed by ``trace_id`` so two concurrent
        # flows (on distinct executors sharing this exporter) never
        # overwrite each other's span references — fixes the leak
        # mode where a shared global exporter wired into multiple
        # ``FlowExecutor``s ended the first flow's parent span never
        # because the second flow's ``on_flow_start`` overwrote the
        # scalar.
        self._flow_spans: dict[str, Span] = {}
        self._step_spans: dict[str, Span] = {}

    def on_flow_start(self, ctx: FlowStartContext) -> None:
        # On resume, ``ctx.started_at`` is the *original* run's start —
        # using it would produce a parent span that visually covers the
        # crash → resume gap as one giant span (potentially hours
        # long in Jaeger / Tempo / Honeycomb).  Anchor the resumed
        # parent span at wall-clock-now so the rendered duration
        # covers only the resume work; the original ``trace_id`` and
        # ``started_at`` remain on the ``chainweaver.*`` attributes
        # for correlation with the original ChainWeaver execution log.
        if ctx.is_resume:
            start_ns = _datetime_to_ns(datetime.now(timezone.utc))
        else:
            start_ns = _datetime_to_ns(ctx.started_at)
        span = self._tracer.start_span(
            f"{_FLOW_SPAN_PREFIX}{ctx.flow_name}",
            start_time=start_ns,
        )
        span.set_attribute("chainweaver.trace_id", ctx.trace_id)
        span.set_attribute("chainweaver.flow_name", ctx.flow_name)
        span.set_attribute("chainweaver.flow_version", ctx.flow_version)
        span.set_attribute("chainweaver.total_steps", ctx.total_steps)
        span.set_attribute("chainweaver.is_resume", ctx.is_resume)
        if ctx.is_resume:
            # Preserve the original wall-clock start for correlation
            # with the persisted ExecutionResult.started_at field
            # (which still carries the pre-crash timestamp).
            span.set_attribute("chainweaver.original_started_at", ctx.started_at.isoformat())
        self._flow_spans[ctx.trace_id] = span

    def on_step_start(self, ctx: StepStartContext) -> None:
        start_ns = _datetime_to_ns(ctx.started_at)
        span = self._tracer.start_span(
            f"{_STEP_SPAN_PREFIX}{ctx.tool_name}",
            start_time=start_ns,
        )
        _set_step_attributes(
            span,
            trace_id=ctx.trace_id,
            flow_name=ctx.flow_name,
            step_index=ctx.step_index,
            tool_name=ctx.tool_name,
            inputs=ctx.inputs,
        )
        self._step_spans[ctx.trace_id] = span

    def on_step_end(self, ctx: StepEndContext) -> None:
        step_span = self._step_spans.pop(ctx.trace_id, None)
        if step_span is None:
            # Pre-resolution failure (tool-not-found / input-mapping):
            # no preceding on_step_start fired.  Emit a 0-duration
            # span at the step's recorded boundary so the failure is
            # still visible in the trace.
            start_ns = _datetime_to_ns(ctx.step_record.started_at)
            step_span = self._tracer.start_span(
                f"{_STEP_SPAN_PREFIX}{ctx.step_record.tool_name}",
                start_time=start_ns,
            )
            _set_step_attributes(
                step_span,
                trace_id=ctx.trace_id,
                flow_name=ctx.flow_name,
                step_index=ctx.step_record.step_index,
                tool_name=ctx.step_record.tool_name,
            )
        _finalize_step_span(step_span, step_record=ctx.step_record)

    def on_flow_end(self, ctx: FlowEndContext) -> None:
        flow_span = self._flow_spans.pop(ctx.trace_id, None)
        if flow_span is None:
            return
        flow_span.set_attribute("chainweaver.success", ctx.result.success)
        flow_span.set_attribute("chainweaver.total_duration_ms", ctx.result.total_duration_ms)
        if not ctx.result.success:
            flow_span.set_status(Status(StatusCode.ERROR, "Flow did not complete successfully"))
        flow_span.end(end_time=_datetime_to_ns(ctx.result.ended_at))


def export_result_to_otel(result: ExecutionResult, *, tracer: Tracer) -> None:
    """Emit OpenTelemetry spans for a completed :class:`ExecutionResult`.

    Useful for replayed traces, batch reconstruction, and any path
    that didn't run through the live :class:`OTelTraceExporter`
    middleware.  Span timestamps come from the recorded
    ``started_at`` / ``ended_at`` values, so the timeline view in
    Jaeger / Tempo / Honeycomb / Datadog matches what actually
    happened — not "now".

    Args:
        result: A completed :class:`ExecutionResult` (success or
            failure).
        tracer: An ``opentelemetry.trace.Tracer`` instance acquired
            via :func:`opentelemetry.trace.get_tracer`.
    """
    flow_span = tracer.start_span(
        f"{_FLOW_SPAN_PREFIX}{result.flow_name}",
        start_time=_datetime_to_ns(result.started_at),
    )
    try:
        flow_span.set_attribute("chainweaver.trace_id", result.trace_id)
        flow_span.set_attribute("chainweaver.flow_name", result.flow_name)
        flow_span.set_attribute("chainweaver.total_steps", len(result.execution_log))
        flow_span.set_attribute("chainweaver.success", result.success)
        flow_span.set_attribute("chainweaver.total_duration_ms", result.total_duration_ms)
        if not result.success:
            flow_span.set_status(Status(StatusCode.ERROR, "Flow did not complete successfully"))

        for record in result.execution_log:
            step_span = tracer.start_span(
                f"{_STEP_SPAN_PREFIX}{record.tool_name}",
                start_time=_datetime_to_ns(record.started_at),
            )
            try:
                _set_step_attributes(
                    step_span,
                    trace_id=result.trace_id,
                    flow_name=result.flow_name,
                    step_index=record.step_index,
                    tool_name=record.tool_name,
                    inputs=record.inputs,
                )
                _finalize_step_span(step_span, step_record=record)
            except BaseException:
                step_span.end(end_time=_datetime_to_ns(record.ended_at))
                raise
    finally:
        flow_span.end(end_time=_datetime_to_ns(result.ended_at))


__all__ = ["OTelTraceExporter", "export_result_to_otel"]
