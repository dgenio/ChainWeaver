"""Tests for guided decision points (issue #102).

Covers the :class:`~chainweaver.decisions.DecisionCallback` protocol,
the executor's invocation seam, and the failure paths
(``DecisionCallbackError``).
"""

from __future__ import annotations

from typing import Any

import pytest
from helpers import NumberInput, ValueInput, ValueOutput, _add_ten_fn, _double_fn

from chainweaver.decisions import (
    BaseDecisionCallback,
    DecisionContext,
    coerce_decision_callback,
)
from chainweaver.executor import FlowExecutor
from chainweaver.flow import DAGFlow, DAGFlowStep, Flow, FlowStep
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool


def _build_two_tools() -> tuple[Tool, Tool]:
    return (
        Tool(
            name="double",
            description="Doubles the input.",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=_double_fn,
        ),
        Tool(
            name="add_ten",
            description="Adds ten to the input.",
            input_schema=ValueInput,
            output_schema=ValueOutput,
            fn=_add_ten_fn,
        ),
    )


def test_decision_context_is_frozen() -> None:
    from pydantic import ValidationError

    ctx = DecisionContext(
        trace_id="abc",
        flow_name="f",
        step_index=0,
        step_id=None,
        default_tool_name="t",
        candidates=["t", "u"],
        context={"k": 1},
    )
    with pytest.raises(ValidationError):
        ctx.step_index = 1


def test_coerce_decision_callback_accepts_callable() -> None:
    def pick_first(ctx: DecisionContext) -> str:
        return ctx.candidates[0]

    cb = coerce_decision_callback(pick_first)
    assert cb is not None
    ctx = DecisionContext(
        trace_id="t",
        flow_name="f",
        step_index=0,
        step_id=None,
        default_tool_name="a",
        candidates=["a", "b"],
        context={},
    )
    assert cb.decide(ctx) == "a"


def test_coerce_decision_callback_accepts_class() -> None:
    class PickLast(BaseDecisionCallback):
        def decide(self, ctx: DecisionContext) -> str:
            return ctx.candidates[-1]

    cb = coerce_decision_callback(PickLast())
    assert cb is not None
    ctx = DecisionContext(
        trace_id="t",
        flow_name="f",
        step_index=0,
        step_id=None,
        default_tool_name="a",
        candidates=["a", "b"],
        context={},
    )
    assert cb.decide(ctx) == "b"


def test_coerce_decision_callback_none_passes_through() -> None:
    assert coerce_decision_callback(None) is None


def test_coerce_decision_callback_rejects_garbage() -> None:
    with pytest.raises(TypeError):
        coerce_decision_callback("not a callback")  # type: ignore[arg-type]


def test_flow_step_rejects_empty_candidates() -> None:
    with pytest.raises(ValueError, match="at least one"):
        FlowStep(tool_name="t", decision_candidates=[])


def test_flow_step_rejects_duplicate_candidates() -> None:
    with pytest.raises(ValueError, match="duplicates"):
        FlowStep(tool_name="t", decision_candidates=["a", "b", "a"])


def _build_executor_with_decision(callback: Any = None) -> FlowExecutor:
    flow = Flow(
        name="picky",
        version="0.1.0",
        description="Picks between double and add_ten via callback.",
        steps=[
            FlowStep(
                tool_name="double",
                input_mapping={"number": "number"},
                decision_candidates=["double", "add_ten"],
            ),
        ],
    )
    reg = FlowRegistry()
    reg.register_flow(flow)
    ex = FlowExecutor(registry=reg, decision_callback=callback)
    for t in _build_two_tools():
        # add_ten reads "value" not "number", so we adapt by registering
        # add_ten with a wrapper that also accepts "number" for this test.
        ex.register_tool(t)
    return ex


def test_step_falls_back_to_static_tool_when_no_callback() -> None:
    ex = _build_executor_with_decision(callback=None)
    result = ex.execute_flow("picky", {"number": 5})
    assert result.success is True
    assert result.execution_log[0].tool_name == "double"
    assert result.execution_log[0].outputs == {"value": 10}


def test_callback_overrides_default_tool() -> None:
    flow = Flow(
        name="picky2",
        version="0.1.0",
        description="Picks add_ten via callback.",
        steps=[
            FlowStep(
                tool_name="double",  # default
                input_mapping={"value": "number"},  # adapt for either tool
                decision_candidates=["double", "add_ten"],
            ),
        ],
    )
    reg = FlowRegistry()
    reg.register_flow(flow)

    def pick_add_ten(ctx: DecisionContext) -> str:
        return "add_ten"

    ex = FlowExecutor(registry=reg, decision_callback=pick_add_ten)
    for t in _build_two_tools():
        ex.register_tool(t)
    result = ex.execute_flow("picky2", {"number": 5})
    assert result.success is True
    assert result.execution_log[0].tool_name == "add_ten"
    assert result.execution_log[0].outputs == {"value": 15}


def test_callback_returning_unknown_tool_fails_step() -> None:
    flow = Flow(
        name="picky3",
        version="0.1.0",
        description="Callback returns invalid name.",
        steps=[
            FlowStep(
                tool_name="double",
                input_mapping={"number": "number"},
                decision_candidates=["double", "add_ten"],
            ),
        ],
    )
    reg = FlowRegistry()
    reg.register_flow(flow)

    def pick_unknown(ctx: DecisionContext) -> str:
        return "ghost"

    ex = FlowExecutor(registry=reg, decision_callback=pick_unknown)
    for t in _build_two_tools():
        ex.register_tool(t)
    result = ex.execute_flow("picky3", {"number": 5})
    assert result.success is False
    rec = result.execution_log[0]
    assert rec.error_type == "DecisionCallbackError"
    assert "ghost" in (rec.error_message or "")
    assert "decision_candidates" in (rec.error_message or "")


def test_callback_raising_fails_step() -> None:
    flow = Flow(
        name="picky4",
        version="0.1.0",
        description="Callback raises.",
        steps=[
            FlowStep(
                tool_name="double",
                input_mapping={"number": "number"},
                decision_candidates=["double", "add_ten"],
            ),
        ],
    )
    reg = FlowRegistry()
    reg.register_flow(flow)

    def pick_raises(ctx: DecisionContext) -> str:
        raise RuntimeError("upstream router exploded")

    ex = FlowExecutor(registry=reg, decision_callback=pick_raises)
    for t in _build_two_tools():
        ex.register_tool(t)
    result = ex.execute_flow("picky4", {"number": 5})
    assert result.success is False
    rec = result.execution_log[0]
    assert rec.error_type == "DecisionCallbackError"
    assert "RuntimeError" in (rec.error_message or "")
    assert "upstream router exploded" in (rec.error_message or "")


def test_decision_context_carries_step_id_for_dag() -> None:
    dag = DAGFlow(
        name="dag_picky",
        version="0.1.0",
        description="DAG decision point exposes step_id.",
        steps=[
            DAGFlowStep(
                tool_name="double",
                step_id="picker",
                input_mapping={"number": "number"},
                decision_candidates=["double", "add_ten"],
            ),
        ],
    )
    reg = FlowRegistry()
    reg.register_flow(dag)

    captured: list[DecisionContext] = []

    def capture(ctx: DecisionContext) -> str:
        captured.append(ctx)
        return ctx.default_tool_name

    ex = FlowExecutor(registry=reg, decision_callback=capture)
    for t in _build_two_tools():
        ex.register_tool(t)
    result = ex.execute_flow("dag_picky", {"number": 5})
    assert result.success is True
    assert len(captured) == 1
    assert captured[0].step_id == "picker"
    assert captured[0].candidates == ["double", "add_ten"]
    assert captured[0].default_tool_name == "double"


def test_decision_callback_is_skipped_when_step_has_no_candidates() -> None:
    """Steps without decision_candidates never invoke the callback."""
    called = []

    def watcher(ctx: DecisionContext) -> str:
        called.append(ctx)
        return ctx.default_tool_name

    flow = Flow(
        name="plain",
        version="0.1.0",
        description="No decision candidates.",
        steps=[FlowStep(tool_name="double", input_mapping={"number": "number"})],
    )
    reg = FlowRegistry()
    reg.register_flow(flow)
    ex = FlowExecutor(registry=reg, decision_callback=watcher)
    for t in _build_two_tools():
        ex.register_tool(t)
    result = ex.execute_flow("plain", {"number": 5})
    assert result.success is True
    assert called == []
