"""Tests for the flow visualization API (issue #79)."""

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

from chainweaver.executor import FlowExecutor
from chainweaver.flow import DAGFlow, DAGFlowStep, Flow, FlowStep
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool
from chainweaver.viz import flow_to_ascii, flow_to_mermaid, result_to_mermaid

# ---------------------------------------------------------------------------
# Linear flow ASCII
# ---------------------------------------------------------------------------


class TestLinearAscii:
    def test_three_step_linear(self) -> None:
        flow = Flow(
            name="three",
            version="0.1.0",
            description="Three-step.",
            steps=[
                FlowStep(tool_name="a"),
                FlowStep(tool_name="b"),
                FlowStep(tool_name="c"),
            ],
        )
        assert flow_to_ascii(flow) == "[a] --> [b] --> [c]"

    def test_single_step(self) -> None:
        flow = Flow(
            name="one",
            version="0.1.0",
            description="single step.",
            steps=[FlowStep(tool_name="lone")],
        )
        assert flow_to_ascii(flow) == "[lone]"

    def test_empty_flow(self) -> None:
        flow = Flow(name="empty", version="0.1.0", description="empty", steps=[])
        assert flow_to_ascii(flow) == "(empty flow)"

    def test_method_on_flow(self) -> None:
        flow = Flow(name="x", version="0.1.0", description="y", steps=[FlowStep(tool_name="t")])
        assert flow.to_ascii() == "[t]"


# ---------------------------------------------------------------------------
# DAG ASCII
# ---------------------------------------------------------------------------


class TestDagAscii:
    def test_diamond(self) -> None:
        dag = DAGFlow(
            name="diamond",
            version="0.1.0",
            description="A->B,A->C,B->D,C->D",
            steps=[
                DAGFlowStep(tool_name="a", step_id="A", depends_on=[]),
                DAGFlowStep(tool_name="b", step_id="B", depends_on=["A"]),
                DAGFlowStep(tool_name="c", step_id="C", depends_on=["A"]),
                DAGFlowStep(tool_name="d", step_id="D", depends_on=["B", "C"]),
            ],
        )
        rendered = flow_to_ascii(dag)
        assert "[a] --> [b]" in rendered
        assert "[a] --> [c]" in rendered
        assert "[b] --> [d]" in rendered
        assert "[c] --> [d]" in rendered

    def test_independent_dag_steps(self) -> None:
        dag = DAGFlow(
            name="indep",
            version="0.1.0",
            description="Two independent steps.",
            steps=[
                DAGFlowStep(tool_name="a", step_id="A", depends_on=[]),
                DAGFlowStep(tool_name="b", step_id="B", depends_on=[]),
            ],
        )
        rendered = flow_to_ascii(dag)
        assert "[a]" in rendered
        assert "[b]" in rendered

    def test_dag_method_call(self) -> None:
        dag = DAGFlow(
            name="x",
            version="0.1.0",
            description="x",
            steps=[DAGFlowStep(tool_name="t", step_id="T", depends_on=[])],
        )
        # Single-step DAG → empty edges → still renders the node.
        assert "[t]" in dag.to_ascii()


# ---------------------------------------------------------------------------
# Mermaid output
# ---------------------------------------------------------------------------


class TestMermaidLinear:
    def test_basic_graph(self) -> None:
        flow = Flow(
            name="three",
            version="0.1.0",
            description="three.",
            steps=[
                FlowStep(tool_name="a"),
                FlowStep(tool_name="b"),
                FlowStep(tool_name="c"),
            ],
        )
        out = flow_to_mermaid(flow)
        assert out.startswith("graph LR")
        assert "S0[a]" in out
        assert "S1[b]" in out
        assert "S2[c]" in out
        assert "S0 --> S1" in out
        assert "S1 --> S2" in out

    def test_direction_td(self) -> None:
        flow = Flow(name="t", version="0.1.0", description="t", steps=[FlowStep(tool_name="x")])
        out = flow_to_mermaid(flow, direction="TD")
        assert out.startswith("graph TD")

    def test_empty_flow(self) -> None:
        flow = Flow(name="empty", version="0.1.0", description="empty", steps=[])
        out = flow_to_mermaid(flow)
        assert "graph LR" in out
        assert "empty" in out

    def test_method_on_flow(self) -> None:
        flow = Flow(name="t", version="0.1.0", description="t", steps=[FlowStep(tool_name="m")])
        assert "S0[m]" in flow.to_mermaid()


class TestMermaidDag:
    def test_diamond_renders_all_edges(self) -> None:
        dag = DAGFlow(
            name="diamond",
            version="0.1.0",
            description="diamond",
            steps=[
                DAGFlowStep(tool_name="a", step_id="A", depends_on=[]),
                DAGFlowStep(tool_name="b", step_id="B", depends_on=["A"]),
                DAGFlowStep(tool_name="c", step_id="C", depends_on=["A"]),
                DAGFlowStep(tool_name="d", step_id="D", depends_on=["B", "C"]),
            ],
        )
        out = flow_to_mermaid(dag)
        assert "S_A --> S_B" in out
        assert "S_A --> S_C" in out
        assert "S_B --> S_D" in out
        assert "S_C --> S_D" in out


class TestMermaidEscaping:
    def test_dangerous_chars_escaped(self) -> None:
        flow = Flow(
            name="dangerous",
            version="0.1.0",
            description="x",
            steps=[FlowStep(tool_name="<bad>")],
        )
        out = flow_to_mermaid(flow)
        # The angle brackets must be HTML-escaped so Mermaid doesn't break.
        assert "&lt;bad&gt;" in out
        assert "<bad>" not in out


# ---------------------------------------------------------------------------
# ExecutionResult overlay
# ---------------------------------------------------------------------------


def _build_two_step_executor() -> FlowExecutor:
    flow = Flow(
        name="viz_two_step",
        version="0.1.0",
        description="two step",
        steps=[
            FlowStep(tool_name="double", input_mapping={"number": "number"}),
            FlowStep(tool_name="add_ten", input_mapping={"value": "value"}),
        ],
    )
    registry = FlowRegistry()
    registry.register_flow(flow)
    ex = FlowExecutor(registry=registry)
    ex.register_tool(
        Tool(
            name="double",
            description="d",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=_double_fn,
        )
    )
    ex.register_tool(
        Tool(
            name="add_ten",
            description="a",
            input_schema=ValueInput,
            output_schema=ValueOutput,
            fn=_add_ten_fn,
        )
    )
    return ex


class TestResultMermaid:
    def test_success_overlay(self) -> None:
        ex = _build_two_step_executor()
        result = ex.execute_flow("viz_two_step", {"number": 4})
        out = result_to_mermaid(result)
        assert "graph LR" in out
        assert "double ✓" in out
        assert "add_ten ✓" in out
        # No fail style for success.
        assert "fill:#f66" not in out

    def test_failure_overlay(self) -> None:
        class Inp(BaseModel):
            x: int

        class Out(BaseModel):
            x: int

        def boom(_: Inp) -> dict[str, Any]:
            raise RuntimeError("boom")

        flow = Flow(
            name="viz_fail",
            version="0.1.0",
            description="failing flow",
            steps=[FlowStep(tool_name="boom", input_mapping={"x": "x"})],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(
            Tool(
                name="boom",
                description="raises",
                input_schema=Inp,
                output_schema=Out,
                fn=boom,
            )
        )
        result = ex.execute_flow("viz_fail", {"x": 1})
        out = result_to_mermaid(result)
        assert "boom ✗" in out
        # Failure styled red.
        assert "fill:#f66" in out

    def test_method_on_result(self) -> None:
        ex = _build_two_step_executor()
        result = ex.execute_flow("viz_two_step", {"number": 1})
        assert "graph LR" in result.to_mermaid()

    def test_empty_log(self) -> None:
        from datetime import datetime, timezone

        from chainweaver.executor import ExecutionResult

        result = ExecutionResult(
            flow_name="empty",
            success=True,
            final_output={},
            execution_log=[],
            trace_id="x",
            started_at=datetime.now(timezone.utc),
            ended_at=datetime.now(timezone.utc),
            total_duration_ms=0.0,
        )
        out = result_to_mermaid(result)
        assert "no steps" in out
