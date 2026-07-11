"""OpenTelemetry trace + metrics integration for ChainWeaver flows (issues #126, #435).

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

For **aggregate** signals (throughput, latency percentiles, cache-hit rate,
failure rate) rather than individual traces, :class:`OTelMetricsMiddleware`
(issue #435) emits OpenTelemetry *metrics* — counters and duration histograms
for flows and steps — via the same middleware seam, and
:func:`export_result_to_otel_metrics` records the same instruments from a
completed :class:`ExecutionResult`.  Attributes are deliberately low-cardinality
(``flow_name`` / ``tool_name`` / boolean ``success`` / boolean cache-``hit``);
raw inputs and ``trace_id`` are never attached to metrics, where high
cardinality would blow up the time-series backend.

Optional extra
--------------

This module requires ``opentelemetry-api``.  Install with::

    pip install 'chainweaver[otel]'

The third-party import is guarded so importing this module without the
extra raises a clear :class:`ImportError` instead of a cryptic
``ModuleNotFoundError`` deep in execution.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

try:  # Optional dependency.
    from opentelemetry.metrics import Meter
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
        start_ns = _datetime_to_ns(ctx.started_at)
        span = self._tracer.start_span(
            f"{_FLOW_SPAN_PREFIX}{ctx.flow_name}",
            start_time=start_ns,
        )
        span.set_attribute("chainweaver.trace_id", ctx.trace_id)
        span.set_attribute("chainweaver.flow_name", ctx.flow_name)
        span.set_attribute("chainweaver.flow_version", ctx.flow_version)
        span.set_attribute("chainweaver.total_steps", ctx.total_steps)
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


# ---------------------------------------------------------------------------
# Metrics (issue #435)
# ---------------------------------------------------------------------------

# Instrument names — namespaced under ``chainweaver.*`` to match the span names.
_FLOW_EXECUTIONS = "chainweaver.flow.executions"
_FLOW_DURATION = "chainweaver.flow.duration"
_STEP_EXECUTIONS = "chainweaver.step.executions"
_STEP_DURATION = "chainweaver.step.duration"
_STEP_CACHE = "chainweaver.step.cache"
_STEP_RETRIES = "chainweaver.step.retries"


def _flow_metric_attrs(flow_name: str, *, success: bool) -> dict[str, Any]:
    return {"chainweaver.flow_name": flow_name, "chainweaver.success": success}


def _step_metric_attrs(flow_name: str, tool_name: str, *, success: bool) -> dict[str, Any]:
    return {
        "chainweaver.flow_name": flow_name,
        "chainweaver.tool_name": tool_name,
        "chainweaver.success": success,
    }


class _OTelMetrics:
    """Shared instrument set + recording logic for the two metrics entry points."""

    def __init__(self, meter: Meter) -> None:
        self._flow_executions = meter.create_counter(
            _FLOW_EXECUTIONS,
            unit="1",
            description="Count of flow executions, tagged by flow_name and success.",
        )
        self._flow_duration = meter.create_histogram(
            _FLOW_DURATION,
            unit="ms",
            description="Wall-clock flow execution duration in milliseconds.",
        )
        self._step_executions = meter.create_counter(
            _STEP_EXECUTIONS,
            unit="1",
            description="Count of step executions, tagged by flow_name, tool_name, success.",
        )
        self._step_duration = meter.create_histogram(
            _STEP_DURATION,
            unit="ms",
            description="Wall-clock step execution duration in milliseconds.",
        )
        self._step_cache = meter.create_counter(
            _STEP_CACHE,
            unit="1",
            description=(
                "Count of executed steps tagged by cache hit=true (served from "
                "the step cache) or hit=false (the tool actually ran)."
            ),
        )
        self._step_retries = meter.create_counter(
            _STEP_RETRIES,
            unit="1",
            description="Total retry attempts across steps (retry_count summed).",
        )

    def record_step(self, record: Any, *, flow_name: str) -> None:
        """Record metrics for one :class:`StepRecord`.

        Skipped steps (a branch not taken) are ignored: they never executed, so
        counting them would distort throughput and cache-rate signals.
        """
        if getattr(record, "skipped", False):
            return
        attrs = _step_metric_attrs(flow_name, record.tool_name, success=record.success)
        self._step_executions.add(1, attrs)
        self._step_duration.record(record.duration_ms, attrs)
        self._step_cache.add(
            1,
            {
                "chainweaver.flow_name": flow_name,
                "chainweaver.tool_name": record.tool_name,
                "chainweaver.cache_hit": bool(record.cached),
            },
        )
        if record.retry_count:
            self._step_retries.add(
                record.retry_count,
                {"chainweaver.flow_name": flow_name, "chainweaver.tool_name": record.tool_name},
            )

    def record_flow(self, *, flow_name: str, success: bool, duration_ms: float) -> None:
        """Record the flow-level counter + duration histogram."""
        attrs = _flow_metric_attrs(flow_name, success=success)
        self._flow_executions.add(1, attrs)
        self._flow_duration.record(duration_ms, {"chainweaver.flow_name": flow_name})


class OTelMetricsMiddleware(BaseMiddleware):
    """Emit OpenTelemetry metrics for every flow execution via the middleware seam (#435).

    Complements :class:`OTelTraceExporter` (which emits per-run spans) with
    aggregate instruments an SRE can build dashboards and SLO alerts on::

        from opentelemetry import metrics
        from chainweaver.integrations.opentelemetry import OTelMetricsMiddleware

        meter = metrics.get_meter("my-app")
        executor = FlowExecutor(
            registry=registry,
            middleware=[OTelMetricsMiddleware(meter=meter)],
        )

    Instruments emitted:

    - ``chainweaver.flow.executions`` (counter) — one per run, attributes
      ``flow_name`` + boolean ``success`` (the failure rate is the
      ``success=false`` slice).
    - ``chainweaver.flow.duration`` (histogram, ms) — end-to-end wall clock.
    - ``chainweaver.step.executions`` (counter) — one per executed step,
      attributes ``flow_name`` + ``tool_name`` + ``success``.
    - ``chainweaver.step.duration`` (histogram, ms) — per-step wall clock.
    - ``chainweaver.step.cache`` (counter) — one per executed step, attribute
      boolean ``cache_hit`` (served from cache vs actually ran) → cache-hit rate.
    - ``chainweaver.step.retries`` (counter) — total retry attempts.

    Attributes are low-cardinality by design; ``trace_id`` and raw inputs are
    intentionally never attached to metrics. Skipped (branch-not-taken) steps
    are not counted. Register alongside :class:`OTelTraceExporter` for both
    traces and metrics from one execution.
    """

    def __init__(self, meter: Meter) -> None:
        self._metrics = _OTelMetrics(meter)

    def on_step_end(self, ctx: StepEndContext) -> None:
        self._metrics.record_step(ctx.step_record, flow_name=ctx.flow_name)

    def on_flow_end(self, ctx: FlowEndContext) -> None:
        self._metrics.record_flow(
            flow_name=ctx.result.flow_name,
            success=ctx.result.success,
            duration_ms=ctx.result.total_duration_ms,
        )


def export_result_to_otel_metrics(result: ExecutionResult, *, meter: Meter) -> None:
    """Record OpenTelemetry metrics for a completed :class:`ExecutionResult` (#435).

    The after-the-fact counterpart of :class:`OTelMetricsMiddleware`, mirroring
    :func:`export_result_to_otel` for the trace path. Records the same flow- and
    step-level instruments from a finished result, so replayed or
    batch-reconstructed traces feed the same dashboards.

    Args:
        result: A completed :class:`ExecutionResult` (success or failure).
        meter: An ``opentelemetry.metrics.Meter`` acquired via
            :func:`opentelemetry.metrics.get_meter`.
    """
    metrics = _OTelMetrics(meter)
    for record in result.execution_log:
        metrics.record_step(record, flow_name=result.flow_name)
    metrics.record_flow(
        flow_name=result.flow_name,
        success=result.success,
        duration_ms=result.total_duration_ms,
    )


__all__ = [
    "OTelMetricsMiddleware",
    "OTelTraceExporter",
    "export_result_to_otel",
    "export_result_to_otel_metrics",
]
