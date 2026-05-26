"""Cookbook recipe 3 — OpenTelemetry tracing for a compiled flow.

Demonstrates the ``OTelTraceExporter`` middleware shipped under ``chainweaver[otel]``.
Once registered on a ``FlowExecutor``, every flow run emits:

* one parent span ``chainweaver.flow.{flow_name}``
* one child span ``chainweaver.tool.{tool_name}`` per executed step

The example uses an in-process ``InMemorySpanExporter`` so the recipe asserts the spans
it emitted itself — no external collector is required.

Run from the repository root (after ``pip install -e ".[otel]"``)::

    python examples/cookbook/recipe_03_otel_tracing.py
"""

from __future__ import annotations

from pydantic import BaseModel

from chainweaver import Flow, FlowExecutor, FlowRegistry, FlowStep, Tool


class NumberInput(BaseModel):
    number: int


class ValueOutput(BaseModel):
    value: int


def double_fn(inp: NumberInput) -> dict:
    return {"value": inp.number * 2}


def add_ten_fn(inp: ValueOutput) -> dict:
    return {"value": inp.value + 10}


def build_executor() -> tuple[FlowExecutor, object]:
    """Build a flow + executor wired to an in-memory OTel exporter.

    Imports are deferred so this script does not crash at import time when the
    ``otel`` extra is not installed; instead we surface a clear message in
    ``main``.
    """
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (
        InMemorySpanExporter,
    )

    from chainweaver.integrations.opentelemetry import OTelTraceExporter

    provider = TracerProvider()
    span_exporter = InMemorySpanExporter()
    provider.add_span_processor(SimpleSpanProcessor(span_exporter))
    trace.set_tracer_provider(provider)
    tracer = trace.get_tracer("chainweaver.cookbook.recipe_03")

    double = Tool(
        name="double",
        description="Doubles a number.",
        input_schema=NumberInput,
        output_schema=ValueOutput,
        fn=double_fn,
    )
    add_ten = Tool(
        name="add_ten",
        description="Adds 10.",
        input_schema=ValueOutput,
        output_schema=ValueOutput,
        fn=add_ten_fn,
    )

    flow = Flow(
        name="double_add_ten",
        version="0.1.0",
        description="Double a number then add ten.",
        steps=[
            FlowStep(tool_name="double", input_mapping={"number": "number"}),
            FlowStep(tool_name="add_ten", input_mapping={"value": "value"}),
        ],
    )

    registry = FlowRegistry()
    registry.register_flow(flow)
    executor = FlowExecutor(
        registry=registry,
        middleware=[OTelTraceExporter(tracer=tracer)],
    )
    executor.register_tool(double)
    executor.register_tool(add_ten)
    return executor, span_exporter


def main() -> None:
    try:
        executor, span_exporter = build_executor()
    except ImportError as exc:
        print(
            "OpenTelemetry SDK is not installed. "
            "Install with: pip install -e '.[otel]' opentelemetry-sdk\n"
            f"(import failed: {exc})"
        )
        return

    result = executor.execute_flow("double_add_ten", {"number": 5})
    assert result.success
    assert result.final_output == {"number": 5, "value": 20}

    spans = span_exporter.get_finished_spans()  # type: ignore[attr-defined]
    flow_spans = [s for s in spans if s.name == "chainweaver.flow.double_add_ten"]
    tool_spans = [s for s in spans if s.name.startswith("chainweaver.tool.")]

    print(f"Captured {len(spans)} OTel spans:")
    for s in spans:
        print(f"  {s.name} ({(s.end_time - s.start_time) / 1_000_000:.2f} ms)")

    assert len(flow_spans) == 1, f"expected 1 flow span, got {len(flow_spans)}"
    assert len(tool_spans) == 2, f"expected 2 tool spans, got {len(tool_spans)}"


if __name__ == "__main__":
    main()
