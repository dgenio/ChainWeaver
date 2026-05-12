"""Tests for FlowExecutor.explain_flow / dry-run mode (issue #73)."""

from __future__ import annotations

from typing import Any

import pytest
from helpers import (
    NumberInput,
    ValueInput,
    ValueOutput,
)
from pydantic import BaseModel

from chainweaver.exceptions import FlowNotFoundError
from chainweaver.executor import ExecutionPlan, FlowExecutor, StepPlan
from chainweaver.flow import Flow, FlowStep
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool


def _double_tool() -> Tool:
    return Tool(
        name="double",
        description="Doubles a number.",
        input_schema=NumberInput,
        output_schema=ValueOutput,
        fn=lambda inp: {"value": inp.number * 2},
    )


def _add_ten_tool() -> Tool:
    return Tool(
        name="add_ten",
        description="Adds 10.",
        input_schema=ValueInput,
        output_schema=ValueOutput,
        fn=lambda inp: {"value": inp.value + 10},
    )


def _build_executor(*tools: Tool, flow: Flow) -> FlowExecutor:
    registry = FlowRegistry()
    registry.register_flow(flow)
    ex = FlowExecutor(registry=registry)
    for t in tools:
        ex.register_tool(t)
    return ex


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


class TestValidPlan:
    def test_returns_execution_plan(self) -> None:
        flow = Flow(
            name="double_add",
            version="0.1.0",
            description="Double then add 10.",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "number"}),
                FlowStep(tool_name="add_ten", input_mapping={"value": "value"}),
            ],
        )
        ex = _build_executor(_double_tool(), _add_ten_tool(), flow=flow)
        plan = ex.explain_flow("double_add", {"number": 5})
        assert isinstance(plan, ExecutionPlan)
        assert plan.flow_name == "double_add"
        assert plan.step_count == 2
        assert len(plan.steps) == 2

    def test_steps_carry_schema_shapes(self) -> None:
        flow = Flow(
            name="double_only",
            version="0.1.0",
            description="Double.",
            steps=[FlowStep(tool_name="double", input_mapping={"number": "number"})],
        )
        ex = _build_executor(_double_tool(), flow=flow)
        plan = ex.explain_flow("double_only", {"number": 5})
        step = plan.steps[0]
        assert step.input_schema == {"number": "int"}
        assert step.output_schema == {"value": "int"}

    def test_input_sources_for_context_lookup(self) -> None:
        flow = Flow(
            name="double_only",
            version="0.1.0",
            description="Double.",
            steps=[FlowStep(tool_name="double", input_mapping={"number": "number"})],
        )
        ex = _build_executor(_double_tool(), flow=flow)
        plan = ex.explain_flow("double_only", {"number": 5})
        assert plan.steps[0].input_sources == {"number": "context['number']"}

    def test_input_sources_for_literal_constant(self) -> None:
        class Inp(BaseModel):
            number: int
            factor: int

        class Out(BaseModel):
            value: int

        scale = Tool(
            name="scale",
            description="Scale.",
            input_schema=Inp,
            output_schema=Out,
            fn=lambda inp: {"value": inp.number * inp.factor},
        )
        flow = Flow(
            name="scale_flow",
            version="0.1.0",
            description="Scale by 3.",
            steps=[
                FlowStep(
                    tool_name="scale",
                    input_mapping={"number": "number", "factor": 3},
                )
            ],
        )
        ex = _build_executor(scale, flow=flow)
        plan = ex.explain_flow("scale_flow", {"number": 4})
        assert plan.steps[0].input_sources == {
            "number": "context['number']",
            "factor": "literal(3)",
        }
        assert plan.all_resolvable is True

    def test_empty_mapping_documented(self) -> None:
        flow = Flow(
            name="passthrough_flow",
            version="0.1.0",
            description="No mapping.",
            steps=[FlowStep(tool_name="double")],
        )
        ex = _build_executor(_double_tool(), flow=flow)
        plan = ex.explain_flow("passthrough_flow", {"number": 1})
        assert plan.steps[0].input_sources == {"<all>": "context (full)"}

    def test_final_context_shape_accumulates(self) -> None:
        flow = Flow(
            name="double_add",
            version="0.1.0",
            description="Double then add 10.",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "number"}),
                FlowStep(tool_name="add_ten", input_mapping={"value": "value"}),
            ],
        )
        ex = _build_executor(_double_tool(), _add_ten_tool(), flow=flow)
        plan = ex.explain_flow("double_add", {"number": 5})
        # Initial context plus value (from double + add_ten which both produce 'value').
        assert "number" in plan.final_context_shape
        assert "value" in plan.final_context_shape


# ---------------------------------------------------------------------------
# Warnings: unresolved keys, missing tool
# ---------------------------------------------------------------------------


class TestPlanWarnings:
    def test_unresolved_key_flagged_not_raised(self) -> None:
        flow = Flow(
            name="bad_mapping",
            version="0.1.0",
            description="Mapping references a key that won't exist.",
            steps=[FlowStep(tool_name="double", input_mapping={"number": "ghost"})],
        )
        ex = _build_executor(_double_tool(), flow=flow)
        # No exception — explain reports it as a warning.
        plan = ex.explain_flow("bad_mapping", {"number": 5})
        assert plan.all_resolvable is False
        step = plan.steps[0]
        assert "ghost" in step.unresolved_keys
        assert "(UNRESOLVED)" in step.input_sources["number"]

    def test_missing_tool_flagged_not_raised(self) -> None:
        flow = Flow(
            name="missing_tool_flow",
            version="0.1.0",
            description="References an unregistered tool.",
            steps=[FlowStep(tool_name="ghost_tool", input_mapping={"x": "x"})],
        )
        ex = _build_executor(flow=flow)  # no tools registered
        plan = ex.explain_flow("missing_tool_flow", {"x": 1})
        assert plan.all_resolvable is False
        step = plan.steps[0]
        assert any("not registered" in w for w in step.warnings)
        assert step.input_schema == {}
        assert step.output_schema == {}


class TestEmptyFlow:
    def test_zero_steps_plan(self) -> None:
        flow = Flow(
            name="empty",
            version="0.1.0",
            description="No steps.",
            steps=[],
        )
        ex = _build_executor(flow=flow)
        plan = ex.explain_flow("empty", {"x": 1})
        assert plan.step_count == 0
        assert plan.steps == []
        assert plan.all_resolvable is True
        assert plan.final_context_shape == {"x": "int"}


class TestNoToolFunctionInvoked:
    def test_explain_does_not_call_tool_fn(self) -> None:
        called: list[Any] = []

        def watcher(_: NumberInput) -> dict[str, Any]:
            called.append(1)
            return {"value": 0}

        watcher_tool = Tool(
            name="watcher",
            description="Records calls.",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=watcher,
        )
        flow = Flow(
            name="watcher_flow",
            version="0.1.0",
            description="Single watcher step.",
            steps=[FlowStep(tool_name="watcher", input_mapping={"number": "number"})],
        )
        ex = _build_executor(watcher_tool, flow=flow)
        ex.explain_flow("watcher_flow", {"number": 7})
        assert called == []  # explain must never invoke the function


class TestStringRepresentation:
    def test_str_contains_flow_name(self) -> None:
        flow = Flow(
            name="double_only",
            version="0.1.0",
            description="Double.",
            steps=[FlowStep(tool_name="double", input_mapping={"number": "number"})],
        )
        ex = _build_executor(_double_tool(), flow=flow)
        plan = ex.explain_flow("double_only", {"number": 5})
        rendered = str(plan)
        assert "double_only" in rendered
        assert "double" in rendered

    def test_unknown_flow_raises(self) -> None:
        ex = _build_executor(flow=Flow(name="x", version="0.1.0", description="x", steps=[]))
        with pytest.raises(FlowNotFoundError):
            ex.explain_flow("nope", {})


class TestStepPlanSerialization:
    def test_round_trip(self) -> None:
        flow = Flow(
            name="double_only",
            version="0.1.0",
            description="Double.",
            steps=[FlowStep(tool_name="double", input_mapping={"number": "number"})],
        )
        ex = _build_executor(_double_tool(), flow=flow)
        plan = ex.explain_flow("double_only", {"number": 5})
        payload = plan.model_dump_json()
        rebuilt = ExecutionPlan.model_validate_json(payload)
        assert rebuilt.flow_name == plan.flow_name
        assert rebuilt.step_count == plan.step_count
        assert isinstance(rebuilt.steps[0], StepPlan)
