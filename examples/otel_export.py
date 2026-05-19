"""OpenTelemetry tracing example for ChainWeaver (issue #126).

Demonstrates :class:`OTelTraceExporter` — register it as a middleware
on a :class:`FlowExecutor` and a parent flow span + one child step
span per :class:`StepRecord` are emitted to your OTel pipeline.  This
example uses the in-process ``ConsoleSpanExporter`` so you can see the
spans on stdout; in production you'd swap that for an OTLP exporter
pointing at Jaeger / Tempo / Honeycomb / Datadog / Grafana / Logfire.

Install OTel support and run from the repository root::

    pip install 'chainweaver[otel]' opentelemetry-sdk
    python examples/otel_export.py
"""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from pydantic import BaseModel

from chainweaver import Flow, FlowExecutor, FlowRegistry, FlowStep, Tool
from chainweaver.integrations.opentelemetry import OTelTraceExporter


class NumberInput(BaseModel):
    number: int


class ValueOutput(BaseModel):
    value: int


class ValueInput(BaseModel):
    value: int


def double_fn(inp: NumberInput) -> dict:
    return {"value": inp.number * 2}


def add_ten_fn(inp: ValueInput) -> dict:
    return {"value": inp.value + 10}


flow = Flow(
    name="otel_demo",
    version="0.1.0",
    description="Two-step flow used to demonstrate OTel emission.",
    steps=[
        FlowStep(tool_name="double", input_mapping={"number": "number"}),
        FlowStep(tool_name="add_ten", input_mapping={"value": "value"}),
    ],
)


def main() -> None:
    # Wire OTel: ConsoleSpanExporter prints spans to stdout.  Swap for
    # OTLPSpanExporter in production.
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(provider)
    tracer = trace.get_tracer("chainweaver-otel-example")

    # Hand the tracer to the exporter and register as middleware.
    registry = FlowRegistry()
    registry.register_flow(flow)
    executor = FlowExecutor(
        registry=registry,
        middleware=[OTelTraceExporter(tracer=tracer)],
    )
    executor.register_tool(
        Tool(
            name="double",
            description="Doubles a number.",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=double_fn,
        )
    )
    executor.register_tool(
        Tool(
            name="add_ten",
            description="Adds 10.",
            input_schema=ValueInput,
            output_schema=ValueOutput,
            fn=add_ten_fn,
        )
    )

    result = executor.execute_flow("otel_demo", {"number": 5})
    print(f"\nflow result: success={result.success} output={result.final_output}")


if __name__ == "__main__":
    main()
