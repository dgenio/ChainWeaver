"""Tests for the OpenTelemetry metrics integration (issue #435).

Skipped when ``opentelemetry-sdk`` is not installed; CI's ``[dev]`` extra
provides it.
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("opentelemetry")
pytest.importorskip("opentelemetry.sdk")

from helpers import (
    NumberInput,
    ValueInput,
    ValueOutput,
    _add_ten_fn,
    _double_fn,
)
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from chainweaver.executor import FlowExecutor
from chainweaver.flow import Flow, FlowStep
from chainweaver.integrations.opentelemetry import (
    OTelMetricsMiddleware,
    export_result_to_otel_metrics,
)
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool


@pytest.fixture()
def meter_and_reader() -> tuple[Any, InMemoryMetricReader]:
    reader = InMemoryMetricReader()
    provider = MeterProvider(metric_readers=[reader])
    return provider.get_meter("chainweaver-tests"), reader


def _collect(reader: InMemoryMetricReader) -> dict[str, list[tuple[float, dict[str, Any]]]]:
    """Return ``{metric_name: [(value, attributes), ...]}`` from the reader."""
    data = reader.get_metrics_data()
    out: dict[str, list[tuple[float, dict[str, Any]]]] = {}
    if data is None:
        return out
    for resource_metric in data.resource_metrics:
        for scope_metric in resource_metric.scope_metrics:
            for metric in scope_metric.metrics:
                points = out.setdefault(metric.name, [])
                for dp in metric.data.data_points:
                    value = getattr(dp, "value", None)
                    if value is None:  # histogram data point
                        value = dp.sum
                    points.append((value, dict(dp.attributes or {})))
    return out


def _double_tool() -> Tool:
    return Tool(
        name="double",
        description="Doubles.",
        input_schema=NumberInput,
        output_schema=ValueOutput,
        fn=_double_fn,
    )


def _add_ten_tool() -> Tool:
    return Tool(
        name="add_ten",
        description="Adds ten.",
        input_schema=ValueInput,
        output_schema=ValueOutput,
        fn=_add_ten_fn,
    )


def _two_step_flow() -> Flow:
    return Flow(
        name="metrics_flow",
        version="0.1.0",
        description="two-step",
        steps=[
            FlowStep(tool_name="double", input_mapping={}),
            FlowStep(tool_name="add_ten", input_mapping={}),
        ],
    )


class TestMetricsMiddleware:
    def test_successful_run_emits_flow_and_step_metrics(
        self, meter_and_reader: tuple[Any, InMemoryMetricReader]
    ) -> None:
        meter, reader = meter_and_reader
        registry = FlowRegistry()
        registry.register_flow(_two_step_flow())
        executor = FlowExecutor(registry=registry, middleware=[OTelMetricsMiddleware(meter=meter)])
        executor.register_tool(_double_tool())
        executor.register_tool(_add_ten_tool())

        result = executor.execute_flow("metrics_flow", {"number": 5})
        assert result.success

        metrics = _collect(reader)
        # One flow execution recorded, tagged success=True.
        flow_points = metrics["chainweaver.flow.executions"]
        assert len(flow_points) == 1
        value, attrs = flow_points[0]
        assert value == 1
        assert attrs["chainweaver.flow_name"] == "metrics_flow"
        assert attrs["chainweaver.success"] is True
        # Flow duration histogram recorded exactly one measurement.
        assert "chainweaver.flow.duration" in metrics
        # Two step executions recorded.
        step_total = sum(v for v, _ in metrics["chainweaver.step.executions"])
        assert step_total == 2
        # Cache counter emitted per executed step, all cache_hit=False here.
        cache_points = metrics["chainweaver.step.cache"]
        assert sum(v for v, _ in cache_points) == 2
        assert all(a["chainweaver.cache_hit"] is False for _, a in cache_points)

    def test_failure_is_tagged_success_false(
        self, meter_and_reader: tuple[Any, InMemoryMetricReader]
    ) -> None:
        meter, reader = meter_and_reader

        def _boom(_: NumberInput) -> dict[str, Any]:
            raise ValueError("boom")

        failing = Tool(
            name="boom",
            description="Always fails.",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=_boom,
        )
        registry = FlowRegistry()
        registry.register_flow(
            Flow(
                name="failing_flow",
                version="0.1.0",
                description="d",
                steps=[FlowStep(tool_name="boom", input_mapping={})],
            )
        )
        executor = FlowExecutor(registry=registry, middleware=[OTelMetricsMiddleware(meter=meter)])
        executor.register_tool(failing)

        result = executor.execute_flow("failing_flow", {"number": 1})
        assert not result.success

        metrics = _collect(reader)
        _, flow_attrs = metrics["chainweaver.flow.executions"][0]
        assert flow_attrs["chainweaver.success"] is False
        # The step counter records the failed step with success=False.
        assert any(
            a["chainweaver.success"] is False for _, a in metrics["chainweaver.step.executions"]
        )


class TestExportResultToMetrics:
    def test_records_metrics_from_completed_result(
        self, meter_and_reader: tuple[Any, InMemoryMetricReader]
    ) -> None:
        meter, reader = meter_and_reader
        registry = FlowRegistry()
        registry.register_flow(_two_step_flow())
        # Run WITHOUT the middleware, then export after the fact.
        executor = FlowExecutor(registry=registry)
        executor.register_tool(_double_tool())
        executor.register_tool(_add_ten_tool())
        result = executor.execute_flow("metrics_flow", {"number": 3})

        export_result_to_otel_metrics(result, meter=meter)

        metrics = _collect(reader)
        assert sum(v for v, _ in metrics["chainweaver.flow.executions"]) == 1
        assert sum(v for v, _ in metrics["chainweaver.step.executions"]) == 2
