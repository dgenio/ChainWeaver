"""Tests for decision-callback audit records and policy controls.

Covers the determinism-level downgrade and ``StepRecord.decision`` audit
trail (issue #369) and the ``DecisionPolicy`` timeout / budget guardrails
(issue #370).
"""

from __future__ import annotations

import time

import pytest
from helpers import NumberInput, ValueInput, ValueOutput, _add_ten_fn, _double_fn

from chainweaver.contracts import DeterminismLevel
from chainweaver.decisions import (
    DecisionCallable,
    DecisionContext,
    DecisionPolicy,
    DecisionRecord,
)
from chainweaver.exceptions import DecisionBudgetExceededError
from chainweaver.executor import ExecutionResult, FlowExecutor
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


def _one_decision_flow(name: str = "picky") -> Flow:
    return Flow(
        name=name,
        version="0.1.0",
        description="Single decision step, default double.",
        steps=[
            FlowStep(
                tool_name="double",
                input_mapping={"number": "number"},
                decision_candidates=["double", "add_ten"],
            ),
        ],
    )


def _executor(
    callback: DecisionCallable | None = None, policy: DecisionPolicy | None = None
) -> FlowExecutor:
    reg = FlowRegistry()
    reg.register_flow(_one_decision_flow())
    ex = FlowExecutor(registry=reg, decision_callback=callback, decision_policy=policy)
    for tool in _build_two_tools():
        ex.register_tool(tool)
    return ex


# --------------------------------------------------------------------------
# #369 — determinism level matrix
# --------------------------------------------------------------------------


def test_linear_flow_without_candidates_is_full() -> None:
    flow = Flow(
        name="plain",
        version="0.1.0",
        description="No decision points.",
        steps=[FlowStep(tool_name="double")],
    )
    assert flow.determinism_level is DeterminismLevel.FULL


def test_linear_flow_with_candidates_is_partial() -> None:
    assert _one_decision_flow().determinism_level is DeterminismLevel.PARTIAL


def test_linear_flow_with_candidates_and_nondeterministic_is_none() -> None:
    flow = Flow(
        name="picky",
        version="0.1.0",
        description="Opted out of determinism.",
        deterministic=False,
        steps=[FlowStep(tool_name="double", decision_candidates=["double", "add_ten"])],
    )
    assert flow.determinism_level is DeterminismLevel.NONE


def test_dag_flow_with_candidates_is_partial() -> None:
    dag = DAGFlow(
        name="dag_picky",
        version="0.1.0",
        description="DAG with a decision step.",
        steps=[
            DAGFlowStep(
                tool_name="double",
                step_id="pick",
                decision_candidates=["double", "add_ten"],
            ),
        ],
    )
    assert dag.determinism_level is DeterminismLevel.PARTIAL


def test_dag_flow_without_candidates_is_full() -> None:
    dag = DAGFlow(
        name="dag_plain",
        version="0.1.0",
        description="DAG with no decision step.",
        steps=[DAGFlowStep(tool_name="double", step_id="only")],
    )
    assert dag.determinism_level is DeterminismLevel.FULL


# --------------------------------------------------------------------------
# #369 — StepRecord.decision audit trail
# --------------------------------------------------------------------------


def test_decision_record_populated_on_callback_success() -> None:
    ex = _executor(callback=lambda ctx: "double")
    result = ex.execute_flow("picky", {"number": 5})
    assert result.success is True
    decision = result.execution_log[0].decision
    assert isinstance(decision, DecisionRecord)
    assert decision.candidates == ["double", "add_ten"]
    assert decision.chosen == "double"
    assert decision.default_tool_name == "double"
    assert decision.timed_out is False
    assert decision.duration_ms >= 0.0


def test_decision_record_captures_overridden_choice() -> None:
    flow = Flow(
        name="picky",
        version="0.1.0",
        description="Default double, callback picks add_ten.",
        steps=[
            FlowStep(
                tool_name="double",
                input_mapping={"value": "number"},
                decision_candidates=["double", "add_ten"],
            ),
        ],
    )
    reg = FlowRegistry()
    reg.register_flow(flow)
    ex = FlowExecutor(registry=reg, decision_callback=lambda ctx: "add_ten")
    for tool in _build_two_tools():
        ex.register_tool(tool)
    result = ex.execute_flow("picky", {"number": 5})
    rec = result.execution_log[0]
    assert rec.tool_name == "add_ten"
    assert rec.decision is not None
    assert rec.decision.chosen == "add_ten"
    assert rec.decision.default_tool_name == "double"


def test_decision_record_absent_on_static_fallback() -> None:
    # decision_candidates set but no callback registered → static fallback,
    # no decision recorded (the callback never ran).
    ex = _executor(callback=None)
    result = ex.execute_flow("picky", {"number": 5})
    assert result.success is True
    assert result.execution_log[0].decision is None


def test_decision_record_absent_without_candidates() -> None:
    flow = Flow(
        name="plain",
        version="0.1.0",
        description="No candidates.",
        steps=[FlowStep(tool_name="double", input_mapping={"number": "number"})],
    )
    reg = FlowRegistry()
    reg.register_flow(flow)
    ex = FlowExecutor(registry=reg, decision_callback=lambda ctx: "double")
    for tool in _build_two_tools():
        ex.register_tool(tool)
    result = ex.execute_flow("plain", {"number": 5})
    assert result.execution_log[0].decision is None


def test_decision_record_round_trips_through_json() -> None:
    ex = _executor(callback=lambda ctx: "double")
    result = ex.execute_flow("picky", {"number": 5})
    restored = ExecutionResult.model_validate_json(result.model_dump_json())
    decision = restored.execution_log[0].decision
    assert decision is not None
    assert decision.chosen == "double"
    assert decision.candidates == ["double", "add_ten"]


# --------------------------------------------------------------------------
# #370 — DecisionPolicy validation
# --------------------------------------------------------------------------


def test_decision_policy_rejects_non_positive_timeout() -> None:
    with pytest.raises(ValueError, match="timeout_s must be positive"):
        DecisionPolicy(timeout_s=0)


def test_decision_policy_rejects_zero_budget() -> None:
    with pytest.raises(ValueError, match="max_decisions_per_flow must be >= 1"):
        DecisionPolicy(max_decisions_per_flow=0)


def test_decision_policy_defaults_to_error_on_timeout() -> None:
    assert DecisionPolicy(timeout_s=1.0).on_timeout == "error"


# --------------------------------------------------------------------------
# #370 — timeout behavior
# --------------------------------------------------------------------------


def _slow_callback(ctx: DecisionContext) -> str:
    time.sleep(0.3)
    return ctx.default_tool_name


def test_timeout_error_fails_the_step() -> None:
    ex = _executor(
        callback=_slow_callback,
        policy=DecisionPolicy(timeout_s=0.05, on_timeout="error"),
    )
    result = ex.execute_flow("picky", {"number": 5})
    assert result.success is False
    rec = result.execution_log[0]
    assert rec.error_type == "DecisionTimeoutError"
    assert rec.error_code == "CW-E049"


def test_timeout_default_falls_back_to_static_tool() -> None:
    ex = _executor(
        callback=_slow_callback,
        policy=DecisionPolicy(timeout_s=0.05, on_timeout="default"),
    )
    result = ex.execute_flow("picky", {"number": 5})
    assert result.success is True
    rec = result.execution_log[0]
    assert rec.tool_name == "double"
    assert rec.outputs == {"value": 10}
    assert rec.decision is not None
    assert rec.decision.timed_out is True
    assert rec.decision.chosen == "double"


def test_timed_out_callback_does_not_corrupt_later_runs() -> None:
    ex = _executor(
        callback=_slow_callback,
        policy=DecisionPolicy(timeout_s=0.05, on_timeout="default"),
    )
    first = ex.execute_flow("picky", {"number": 5})
    assert first.success is True
    # A second run on the same executor is unaffected by the orphaned thread.
    second = ex.execute_flow("picky", {"number": 7})
    assert second.success is True
    assert second.execution_log[0].outputs == {"value": 14}


# --------------------------------------------------------------------------
# #370 — decision budget
# --------------------------------------------------------------------------


def _two_decision_flow() -> Flow:
    return Flow(
        name="twopick",
        version="0.1.0",
        description="Two decision steps.",
        on_context_collision="overwrite",
        steps=[
            FlowStep(
                tool_name="double",
                input_mapping={"number": "number"},
                decision_candidates=["double", "add_ten"],
            ),
            FlowStep(
                tool_name="double",
                input_mapping={"number": "number"},
                decision_candidates=["double", "add_ten"],
            ),
        ],
    )


def _two_decision_executor(policy: DecisionPolicy | None) -> FlowExecutor:
    reg = FlowRegistry()
    reg.register_flow(_two_decision_flow())
    ex = FlowExecutor(
        registry=reg,
        decision_callback=lambda ctx: "double",
        decision_policy=policy,
    )
    for tool in _build_two_tools():
        ex.register_tool(tool)
    return ex


def test_budget_exhaustion_aborts_the_flow() -> None:
    ex = _two_decision_executor(DecisionPolicy(max_decisions_per_flow=1))
    with pytest.raises(DecisionBudgetExceededError) as excinfo:
        ex.execute_flow("twopick", {"number": 5})
    assert excinfo.value.flow_name == "twopick"
    assert excinfo.value.budget == 1


def test_budget_within_limit_runs_normally() -> None:
    ex = _two_decision_executor(DecisionPolicy(max_decisions_per_flow=2))
    result = ex.execute_flow("twopick", {"number": 5})
    assert result.success is True
    assert len(result.execution_log) == 2


def test_budget_resets_per_flow_execution() -> None:
    # A budget of 2 lets a two-decision flow run, and the counter resets on the
    # next execution rather than accumulating across runs.
    ex = _two_decision_executor(DecisionPolicy(max_decisions_per_flow=2))
    assert ex.execute_flow("twopick", {"number": 5}).success is True
    assert ex.execute_flow("twopick", {"number": 6}).success is True


# --------------------------------------------------------------------------
# #370 — policy-absent regression
# --------------------------------------------------------------------------


def test_no_policy_leaves_behavior_unchanged() -> None:
    ex = _executor(callback=lambda ctx: "double", policy=None)
    result = ex.execute_flow("picky", {"number": 5})
    assert result.success is True
    assert result.execution_log[0].outputs == {"value": 10}
    # The audit record is still written (that is #369, independent of policy).
    assert result.execution_log[0].decision is not None
