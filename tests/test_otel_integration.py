"""Tests for the OpenTelemetry integration (issue #126).

Tests are skipped if ``opentelemetry-api`` / ``opentelemetry-sdk`` are
not installed.  CI installs the ``[dev]`` extra which pulls both in.
"""

from __future__ import annotations

from typing import Any

import pytest

# Skip the whole module if the optional extras are not available.
opentelemetry = pytest.importorskip("opentelemetry")
pytest.importorskip("opentelemetry.sdk")

from helpers import (  # noqa: E402
    NumberInput,
    ValueInput,
    ValueOutput,
    _add_ten_fn,
    _double_fn,
)
from opentelemetry.sdk.trace import TracerProvider  # noqa: E402
from opentelemetry.sdk.trace.export import SimpleSpanProcessor  # noqa: E402
from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: E402
    InMemorySpanExporter,
)
from opentelemetry.trace import StatusCode  # noqa: E402

from chainweaver.executor import FlowExecutor  # noqa: E402
from chainweaver.flow import Flow, FlowStep  # noqa: E402
from chainweaver.integrations.opentelemetry import (  # noqa: E402
    OTelTraceExporter,
    export_result_to_otel,
)
from chainweaver.registry import FlowRegistry  # noqa: E402
from chainweaver.tools import Tool  # noqa: E402


@pytest.fixture()
def in_memory_tracer() -> tuple[Any, InMemorySpanExporter]:
    """Yield (tracer, exporter); exporter.get_finished_spans() reads the captured spans."""
    provider = TracerProvider()
    exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("chainweaver-tests")
    return tracer, exporter


def _attrs(span: Any) -> dict[str, Any]:
    """Helper: assert ``span.attributes`` is non-None and return it as a dict."""
    assert span.attributes is not None
    return dict(span.attributes)


def _build_two_step_executor(middleware: list[Any] | None = None) -> FlowExecutor:
    flow = Flow(
        name="otel_two_step",
        version="0.1.0",
        description="Two-step flow for OTel tests.",
        steps=[
            FlowStep(tool_name="double", input_mapping={"number": "number"}),
            FlowStep(tool_name="add_ten", input_mapping={"value": "value"}),
        ],
    )
    registry = FlowRegistry()
    registry.register_flow(flow)
    ex = FlowExecutor(registry=registry, middleware=middleware)
    ex.register_tool(
        Tool(
            name="double",
            description="",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=_double_fn,
        )
    )
    ex.register_tool(
        Tool(
            name="add_ten",
            description="",
            input_schema=ValueInput,
            output_schema=ValueOutput,
            fn=_add_ten_fn,
        )
    )
    return ex


# ---------------------------------------------------------------------------
# Live middleware emission
# ---------------------------------------------------------------------------


def test_middleware_emits_parent_and_child_spans(
    in_memory_tracer: tuple[Any, InMemorySpanExporter],
) -> None:
    tracer, exporter = in_memory_tracer
    ex = _build_two_step_executor(middleware=[OTelTraceExporter(tracer=tracer)])

    ex.execute_flow("otel_two_step", {"number": 5})

    spans = exporter.get_finished_spans()
    names = sorted(span.name for span in spans)
    assert names == [
        "chainweaver.flow.otel_two_step",
        "chainweaver.tool.add_ten",
        "chainweaver.tool.double",
    ]


def test_parent_span_carries_flow_attributes(
    in_memory_tracer: tuple[Any, InMemorySpanExporter],
) -> None:
    tracer, exporter = in_memory_tracer
    ex = _build_two_step_executor(middleware=[OTelTraceExporter(tracer=tracer)])

    result = ex.execute_flow("otel_two_step", {"number": 4})

    parent = next(
        s for s in exporter.get_finished_spans() if s.name.startswith("chainweaver.flow.")
    )
    attrs = _attrs(parent)
    assert attrs["chainweaver.trace_id"] == result.trace_id
    assert attrs["chainweaver.flow_name"] == "otel_two_step"
    assert attrs["chainweaver.flow_version"] == "0.1.0"
    assert attrs["chainweaver.total_steps"] == 2
    assert attrs["chainweaver.success"] is True


def test_step_spans_carry_step_attributes(
    in_memory_tracer: tuple[Any, InMemorySpanExporter],
) -> None:
    tracer, exporter = in_memory_tracer
    ex = _build_two_step_executor(middleware=[OTelTraceExporter(tracer=tracer)])

    ex.execute_flow("otel_two_step", {"number": 4})

    step_spans = [
        s for s in exporter.get_finished_spans() if s.name.startswith("chainweaver.tool.")
    ]
    by_name = {s.name: s for s in step_spans}

    double_attrs = _attrs(by_name["chainweaver.tool.double"])
    assert double_attrs["chainweaver.step_index"] == 0
    assert double_attrs["chainweaver.tool_name"] == "double"
    assert double_attrs["chainweaver.step.success"] is True
    assert double_attrs["chainweaver.step.cached"] is False
    assert double_attrs["chainweaver.step.retry_count"] == 0
    assert "chainweaver.step.duration_ms" in double_attrs
    # input_keys is the key list, not the values — for privacy / cardinality.
    assert double_attrs["chainweaver.step.input_keys"] == ("number",)


def test_failed_step_span_status_is_error(
    in_memory_tracer: tuple[Any, InMemorySpanExporter],
) -> None:
    tracer, exporter = in_memory_tracer

    def _explode(_inp: NumberInput) -> dict[str, Any]:
        raise ValueError("boom")

    flow = Flow(
        name="otel_failing",
        version="0.1.0",
        description="",
        steps=[FlowStep(tool_name="bad", input_mapping={"number": "number"})],
    )
    registry = FlowRegistry()
    registry.register_flow(flow)
    ex = FlowExecutor(registry=registry, middleware=[OTelTraceExporter(tracer=tracer)])
    ex.register_tool(
        Tool(
            name="bad",
            description="",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=_explode,
        )
    )

    ex.execute_flow("otel_failing", {"number": 1})

    spans = exporter.get_finished_spans()
    step_span = next(s for s in spans if s.name == "chainweaver.tool.bad")
    flow_span = next(s for s in spans if s.name == "chainweaver.flow.otel_failing")
    step_attrs = _attrs(step_span)
    flow_attrs = _attrs(flow_span)
    assert step_span.status.status_code == StatusCode.ERROR
    assert step_attrs["chainweaver.step.success"] is False
    assert step_attrs["chainweaver.step.error_type"] == "FlowExecutionError"
    assert flow_span.status.status_code == StatusCode.ERROR
    assert flow_attrs["chainweaver.success"] is False


def test_tool_not_found_emits_zero_duration_step_span(
    in_memory_tracer: tuple[Any, InMemorySpanExporter],
) -> None:
    """Pre-resolution failures emit a step span even without on_step_start."""
    tracer, exporter = in_memory_tracer
    flow = Flow(
        name="otel_missing_tool",
        version="0.1.0",
        description="",
        steps=[FlowStep(tool_name="ghost", input_mapping={"number": "number"})],
    )
    registry = FlowRegistry()
    registry.register_flow(flow)
    ex = FlowExecutor(registry=registry, middleware=[OTelTraceExporter(tracer=tracer)])

    ex.execute_flow("otel_missing_tool", {"number": 1})

    spans = exporter.get_finished_spans()
    step_span = next(s for s in spans if s.name == "chainweaver.tool.ghost")
    assert step_span.status.status_code == StatusCode.ERROR
    assert _attrs(step_span)["chainweaver.step.error_type"] == "ToolNotFoundError"


# ---------------------------------------------------------------------------
# After-the-fact export
# ---------------------------------------------------------------------------


def test_export_result_to_otel_emits_spans_from_an_executed_result(
    in_memory_tracer: tuple[Any, InMemorySpanExporter],
) -> None:
    tracer, exporter = in_memory_tracer

    # Run the flow without any middleware first to produce an
    # ExecutionResult.
    ex = _build_two_step_executor()
    result = ex.execute_flow("otel_two_step", {"number": 6})

    export_result_to_otel(result, tracer=tracer)

    spans = exporter.get_finished_spans()
    names = sorted(span.name for span in spans)
    assert names == [
        "chainweaver.flow.otel_two_step",
        "chainweaver.tool.add_ten",
        "chainweaver.tool.double",
    ]
    parent = next(s for s in spans if s.name.startswith("chainweaver.flow."))
    assert _attrs(parent)["chainweaver.trace_id"] == result.trace_id


def test_export_result_to_otel_for_failed_result_emits_error_status(
    in_memory_tracer: tuple[Any, InMemorySpanExporter],
) -> None:
    tracer, exporter = in_memory_tracer

    def _explode(_inp: NumberInput) -> dict[str, Any]:
        raise ValueError("boom")

    flow = Flow(
        name="otel_failing_export",
        version="0.1.0",
        description="",
        steps=[FlowStep(tool_name="bad", input_mapping={"number": "number"})],
    )
    registry = FlowRegistry()
    registry.register_flow(flow)
    ex = FlowExecutor(registry=registry)
    ex.register_tool(
        Tool(
            name="bad",
            description="",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=_explode,
        )
    )
    result = ex.execute_flow("otel_failing_export", {"number": 1})

    export_result_to_otel(result, tracer=tracer)

    spans = exporter.get_finished_spans()
    flow_span = next(s for s in spans if s.name == "chainweaver.flow.otel_failing_export")
    step_span = next(s for s in spans if s.name == "chainweaver.tool.bad")
    assert flow_span.status.status_code == StatusCode.ERROR
    assert step_span.status.status_code == StatusCode.ERROR


# ---------------------------------------------------------------------------
# Middleware exception isolation interop
# ---------------------------------------------------------------------------


def test_otel_middleware_failure_does_not_abort_flow(
    in_memory_tracer: tuple[Any, InMemorySpanExporter],
) -> None:
    """An OTel middleware that raises (e.g. backend down) must not break flows."""
    tracer, _exporter = in_memory_tracer
    exporter_with_bug = OTelTraceExporter(tracer=tracer)

    def _bad_hook(_ctx: Any) -> None:
        raise RuntimeError("OTel backend unreachable")

    exporter_with_bug.on_step_end = _bad_hook  # type: ignore[assignment,method-assign]

    ex = _build_two_step_executor(middleware=[exporter_with_bug])
    result = ex.execute_flow("otel_two_step", {"number": 2})

    # Flow still completes successfully despite the exporter raising.
    assert result.success is True
    assert result.final_output == {"number": 2, "value": 14}
