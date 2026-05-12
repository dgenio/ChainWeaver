"""Tests for the Cost Avoided calculator (issue #74)."""

from __future__ import annotations

from typing import Any

from helpers import (
    NumberInput,
    ValueInput,
    ValueOutput,
    _add_ten_fn,
    _double_fn,
)
from pydantic import BaseModel

from chainweaver.cost import CostProfile, CostReport, compute_cost_report
from chainweaver.executor import FlowExecutor
from chainweaver.flow import Flow, FlowStep
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool


def _build_two_step_executor(*, cost_profile: CostProfile | None = None) -> FlowExecutor:
    flow = Flow(
        name="cost_two_step",
        version="0.1.0",
        description="Two-step flow.",
        steps=[
            FlowStep(tool_name="double", input_mapping={"number": "number"}),
            FlowStep(tool_name="add_ten", input_mapping={"value": "value"}),
        ],
    )
    registry = FlowRegistry()
    registry.register_flow(flow)
    ex = FlowExecutor(registry=registry, cost_profile=cost_profile)
    ex.register_tool(
        Tool(
            name="double",
            description="Doubles a number.",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=_double_fn,
        )
    )
    ex.register_tool(
        Tool(
            name="add_ten",
            description="Adds 10.",
            input_schema=ValueInput,
            output_schema=ValueOutput,
            fn=_add_ten_fn,
        )
    )
    return ex


# ---------------------------------------------------------------------------
# Pure compute_cost_report
# ---------------------------------------------------------------------------


class TestComputeCostReport:
    def test_two_steps_one_call_avoided(self) -> None:
        report = compute_cost_report(
            steps_executed=2,
            actual_execution_ms=10.0,
            profile=CostProfile(),
        )
        assert report.steps_executed == 2
        assert report.llm_calls_avoided == 1

    def test_zero_steps_zero_calls_avoided(self) -> None:
        report = compute_cost_report(
            steps_executed=0,
            actual_execution_ms=0.0,
            profile=CostProfile(),
        )
        assert report.llm_calls_avoided == 0
        assert report.latency_saved_ms == 0.0
        assert report.cost_saved_usd == 0.0

    def test_single_step_zero_calls_avoided(self) -> None:
        report = compute_cost_report(
            steps_executed=1,
            actual_execution_ms=5.0,
            profile=CostProfile(),
        )
        assert report.llm_calls_avoided == 0

    def test_custom_profile_drives_savings(self) -> None:
        profile = CostProfile(
            avg_llm_latency_ms=400.0,
            avg_tokens_per_call=1000.0,
            cost_per_token_usd=0.0001,
        )
        report = compute_cost_report(
            steps_executed=5,
            actual_execution_ms=15.0,
            profile=profile,
        )
        assert report.llm_calls_avoided == 4
        assert report.latency_saved_ms == 4 * 400.0
        # 4 calls * 1000 tokens * $0.0001/token = $0.40
        assert report.cost_saved_usd == 0.4

    def test_str_contains_estimate_label(self) -> None:
        report = compute_cost_report(
            steps_executed=3,
            actual_execution_ms=12.0,
            profile=CostProfile(),
        )
        assert "estimate" in str(report)

    def test_to_dict_round_trip(self) -> None:
        report = compute_cost_report(
            steps_executed=4,
            actual_execution_ms=8.0,
            profile=CostProfile(avg_llm_latency_ms=200.0),
        )
        as_dict = report.to_dict()
        assert as_dict["steps_executed"] == 4
        assert as_dict["llm_calls_avoided"] == 3
        rebuilt = CostReport.model_validate(as_dict)
        assert rebuilt == report


# ---------------------------------------------------------------------------
# Executor integration
# ---------------------------------------------------------------------------


class TestExecutorIntegration:
    def test_no_profile_no_report(self) -> None:
        ex = _build_two_step_executor()
        result = ex.execute_flow("cost_two_step", {"number": 1})
        assert result.cost_report is None

    def test_profile_set_attaches_report(self) -> None:
        ex = _build_two_step_executor(cost_profile=CostProfile())
        result = ex.execute_flow("cost_two_step", {"number": 1})
        assert result.cost_report is not None
        assert result.cost_report.steps_executed == 2
        assert result.cost_report.llm_calls_avoided == 1

    def test_actual_execution_ms_matches_total(self) -> None:
        ex = _build_two_step_executor(cost_profile=CostProfile())
        result = ex.execute_flow("cost_two_step", {"number": 1})
        assert result.cost_report is not None
        assert result.cost_report.actual_execution_ms == result.total_duration_ms

    def test_failed_flow_still_has_report(self) -> None:
        class Inp(BaseModel):
            x: int

        class Out(BaseModel):
            x: int

        def boom(_: Inp) -> dict[str, Any]:
            raise RuntimeError("boom")

        flow = Flow(
            name="cost_boom",
            version="0.1.0",
            description="Always-failing flow.",
            steps=[FlowStep(tool_name="boom", input_mapping={"x": "x"})],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry, cost_profile=CostProfile())
        ex.register_tool(
            Tool(
                name="boom",
                description="Raises.",
                input_schema=Inp,
                output_schema=Out,
                fn=boom,
            )
        )

        result = ex.execute_flow("cost_boom", {"x": 1})
        assert result.success is False
        assert result.cost_report is not None
        # One step executed before failure; zero calls avoided.
        assert result.cost_report.steps_executed == 1
        assert result.cost_report.llm_calls_avoided == 0

    def test_report_serializes_with_result(self) -> None:
        ex = _build_two_step_executor(cost_profile=CostProfile())
        result = ex.execute_flow("cost_two_step", {"number": 1})
        payload = result.model_dump_json()
        assert "cost_report" in payload
        assert "llm_calls_avoided" in payload
