"""Tests for flow composition — flows as steps inside other flows (issue #75)."""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from chainweaver import (
    CancellationToken,
    DAGFlow,
    DAGFlowStep,
    Flow,
    FlowExecutor,
    FlowRegistry,
    FlowStep,
    Tool,
)
from chainweaver.cost import CostProfile
from chainweaver.exceptions import (
    AsyncLaneUnsupportedError,
    FlowCancelledError,
    FlowCompositionError,
)

# Upper bound for the deterministic cancel-barrier waits (#244). Generous enough
# never to trip on a loaded CI runner, yet bounded so a logic error fails fast
# instead of hanging the suite.
_BARRIER_TIMEOUT_S = 5.0

# ---------------------------------------------------------------------------
# Schemas + tools
# ---------------------------------------------------------------------------


class _NIn(BaseModel):
    n: int


class _AOut(BaseModel):
    a: int


class _AIn(BaseModel):
    a: int


class _BOut(BaseModel):
    b: int


def _inc(inp: _NIn) -> dict[str, Any]:
    return {"a": inp.n + 1}


def _plus(inp: _AIn) -> dict[str, Any]:
    return {"b": inp.a + 1}


def _base_executor() -> FlowExecutor:
    """Executor with two tools and a reusable ``inc`` sub-flow (a = n + 1)."""
    registry = FlowRegistry()
    registry.register_flow(
        Flow(
            name="inc",
            version="1.0.0",
            description="Increment n into a.",
            steps=[FlowStep(tool_name="t_inc", input_mapping={"n": "n"})],
        )
    )
    executor = FlowExecutor(registry=registry)
    executor.register_tool(
        Tool(name="t_inc", description="inc", input_schema=_NIn, output_schema=_AOut, fn=_inc)
    )
    executor.register_tool(
        Tool(name="t_plus", description="plus", input_schema=_AIn, output_schema=_BOut, fn=_plus)
    )
    return executor


# ---------------------------------------------------------------------------
# FlowStep model: mutual exclusivity (issue #75)
# ---------------------------------------------------------------------------


class TestFlowStepValidation:
    def test_tool_only_is_valid(self) -> None:
        step = FlowStep(tool_name="t")
        assert step.tool_name == "t"
        assert step.flow_name is None

    def test_flow_only_is_valid(self) -> None:
        step = FlowStep(flow_name="sub")
        assert step.flow_name == "sub"
        assert step.tool_name is None

    def test_both_set_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="exactly one of 'tool_name' or 'flow_name'"):
            FlowStep(tool_name="t", flow_name="sub")

    def test_neither_set_is_rejected(self) -> None:
        with pytest.raises(ValidationError, match="exactly one of 'tool_name' or 'flow_name'"):
            FlowStep()

    def test_flow_step_rejects_decision_candidates(self) -> None:
        with pytest.raises(ValidationError, match="only valid for tool steps"):
            FlowStep(flow_name="sub", decision_candidates=["a", "b"])

    def test_display_name_prefers_tool_then_flow(self) -> None:
        assert FlowStep(tool_name="t").display_name == "t"
        assert FlowStep(flow_name="sub").display_name == "sub"


# ---------------------------------------------------------------------------
# Basic composition
# ---------------------------------------------------------------------------


class TestBasicComposition:
    def test_subflow_runs_and_merges_output(self) -> None:
        executor = _base_executor()
        executor._registry.register_flow(
            Flow(
                name="parent",
                version="1.0.0",
                description="inc then plus.",
                steps=[
                    FlowStep(flow_name="inc", input_mapping={"n": "n"}),
                    FlowStep(tool_name="t_plus", input_mapping={"a": "a"}),
                ],
            )
        )
        result = executor.execute_flow("parent", {"n": 1})
        assert result.success is True
        assert result.final_output is not None
        # inc: a = 2; plus: b = 3
        assert result.final_output["a"] == 2
        assert result.final_output["b"] == 3

    def test_subflow_record_carries_nested_result(self) -> None:
        executor = _base_executor()
        executor._registry.register_flow(
            Flow(
                name="parent",
                version="1.0.0",
                description="just inc.",
                steps=[FlowStep(flow_name="inc", input_mapping={"n": "n"})],
            )
        )
        result = executor.execute_flow("parent", {"n": 5})
        rec = result.execution_log[0]
        assert rec.flow_name == "inc"
        assert rec.tool_name == "inc"  # display mirror
        assert rec.sub_result is not None
        assert rec.sub_result.success is True
        assert rec.sub_result.flow_version == "1.0.0"
        # The nested log holds the sub-flow's own tool step.
        assert rec.sub_result.execution_log[0].tool_name == "t_inc"
        # Parent's flow_version is unaffected by the recursion.
        assert result.flow_version == "1.0.0"

    def test_tool_only_flow_unchanged(self) -> None:
        executor = _base_executor()
        executor._registry.register_flow(
            Flow(
                name="plain",
                version="1.0.0",
                description="single tool.",
                steps=[FlowStep(tool_name="t_inc", input_mapping={"n": "n"})],
            )
        )
        result = executor.execute_flow("plain", {"n": 9})
        assert result.success is True
        assert result.final_output is not None
        assert result.final_output["a"] == 10
        assert result.execution_log[0].flow_name is None
        assert result.execution_log[0].sub_result is None

    def test_subflow_failure_aborts_parent(self) -> None:
        executor = _base_executor()
        # 'inc' input_mapping references a missing context key, so the sub-flow
        # fails its first step → the parent step fails → parent aborts.
        executor._registry.register_flow(
            Flow(
                name="parent_bad",
                version="1.0.0",
                description="sub-flow gets no usable input.",
                steps=[
                    FlowStep(flow_name="inc", input_mapping={"n": "missing"}),
                    FlowStep(tool_name="t_plus", input_mapping={"a": "a"}),
                ],
            )
        )
        result = executor.execute_flow("parent_bad", {"n": 1})
        assert result.success is False
        # Only the failed composite step is recorded; the second never runs.
        assert len(result.execution_log) == 1
        assert result.execution_log[0].success is False
        assert result.execution_log[0].flow_name == "inc"


# ---------------------------------------------------------------------------
# Nesting depth
# ---------------------------------------------------------------------------


class TestNesting:
    def test_three_level_nesting(self) -> None:
        executor = _base_executor()
        # level3 -> inc (tool); level2 -> level3; level1 -> level2
        executor._registry.register_flow(
            Flow(
                name="level3",
                version="1.0.0",
                description="wraps inc.",
                steps=[FlowStep(flow_name="inc", input_mapping={"n": "n"})],
            )
        )
        executor._registry.register_flow(
            Flow(
                name="level2",
                version="1.0.0",
                description="wraps level3.",
                steps=[FlowStep(flow_name="level3", input_mapping={"n": "n"})],
            )
        )
        executor._registry.register_flow(
            Flow(
                name="level1",
                version="1.0.0",
                description="wraps level2.",
                steps=[FlowStep(flow_name="level2", input_mapping={"n": "n"})],
            )
        )
        result = executor.execute_flow("level1", {"n": 1})
        assert result.success is True
        assert result.final_output is not None
        assert result.final_output["a"] == 2
        # Nested results chain three levels deep down to the tool step.
        deepest = result.execution_log[0].sub_result
        assert deepest is not None and deepest.execution_log[0].sub_result is not None

    def test_depth_limit_enforced(self) -> None:
        registry = FlowRegistry()
        # Chain f0 -> f1 -> f2 -> f3 (3 levels of nesting under f0).
        for i in range(3):
            registry.register_flow(
                Flow(
                    name=f"f{i}",
                    version="1.0.0",
                    description=f"f{i} wraps f{i + 1}.",
                    steps=[FlowStep(flow_name=f"f{i + 1}", input_mapping={"n": "n"})],
                )
            )
        registry.register_flow(
            Flow(
                name="f3",
                version="1.0.0",
                description="leaf.",
                steps=[FlowStep(tool_name="t_inc", input_mapping={"n": "n"})],
            )
        )
        executor = FlowExecutor(registry=registry, max_composition_depth=2)
        executor.register_tool(
            Tool(name="t_inc", description="inc", input_schema=_NIn, output_schema=_AOut, fn=_inc)
        )
        with pytest.raises(FlowCompositionError) as exc_info:
            executor.execute_flow("f0", {"n": 1})
        assert exc_info.value.reason == "max_depth_exceeded"


# ---------------------------------------------------------------------------
# Cycle and dangling-reference detection
# ---------------------------------------------------------------------------


class TestCycleDetection:
    def test_direct_cycle_rejected(self) -> None:
        executor = _base_executor()
        executor._registry.register_flow(
            Flow(
                name="self_ref",
                version="1.0.0",
                description="references itself.",
                steps=[FlowStep(flow_name="self_ref", input_mapping={"n": "n"})],
            )
        )
        with pytest.raises(FlowCompositionError) as exc_info:
            executor.execute_flow("self_ref", {"n": 1})
        assert exc_info.value.reason == "cycle"

    def test_indirect_cycle_rejected(self) -> None:
        executor = _base_executor()
        executor._registry.register_flow(
            Flow(
                name="A",
                version="1.0.0",
                description="A -> B.",
                steps=[FlowStep(flow_name="B", input_mapping={"n": "n"})],
            )
        )
        executor._registry.register_flow(
            Flow(
                name="B",
                version="1.0.0",
                description="B -> A.",
                steps=[FlowStep(flow_name="A", input_mapping={"n": "n"})],
            )
        )
        with pytest.raises(FlowCompositionError) as exc_info:
            executor.execute_flow("A", {"n": 1})
        assert exc_info.value.reason == "cycle"

    def test_unknown_subflow_reference_rejected(self) -> None:
        executor = _base_executor()
        executor._registry.register_flow(
            Flow(
                name="dangling",
                version="1.0.0",
                description="references a missing flow.",
                steps=[FlowStep(flow_name="ghost", input_mapping={"n": "n"})],
            )
        )
        with pytest.raises(FlowCompositionError) as exc_info:
            executor.execute_flow("dangling", {"n": 1})
        assert exc_info.value.reason == "unknown_flow"


# ---------------------------------------------------------------------------
# DAG composition + async rejection
# ---------------------------------------------------------------------------


class TestDagAndAsync:
    def test_dag_step_can_reference_subflow(self) -> None:
        executor = _base_executor()
        executor._registry.register_flow(
            Flow(
                name="finish",
                version="1.0.0",
                description="plus as a sub-flow.",
                steps=[FlowStep(tool_name="t_plus", input_mapping={"a": "a"})],
            )
        )
        executor._registry.register_flow(
            DAGFlow(
                name="dag_parent",
                version="1.0.0",
                description="inc (sub-flow) then finish (sub-flow).",
                steps=[
                    DAGFlowStep(
                        flow_name="inc", step_id="A", depends_on=[], input_mapping={"n": "n"}
                    ),
                    DAGFlowStep(
                        flow_name="finish",
                        step_id="B",
                        depends_on=["A"],
                        input_mapping={"a": "a"},
                    ),
                ],
            )
        )
        result = executor.execute_flow("dag_parent", {"n": 1})
        assert result.success is True
        assert result.final_output is not None
        assert result.final_output["b"] == 3

    async def test_async_rejects_subflow_steps(self) -> None:
        executor = _base_executor()
        executor._registry.register_flow(
            Flow(
                name="parent_async",
                version="1.0.0",
                description="composite step, run on async lane.",
                steps=[FlowStep(flow_name="inc", input_mapping={"n": "n"})],
            )
        )
        with pytest.raises(AsyncLaneUnsupportedError, match=r"sub-flow"):
            await executor.execute_flow_async("parent_async", {"n": 1})


# ---------------------------------------------------------------------------
# Cancellation / deadline propagation into composed sub-flows (issue #142 ↔ #75)
# ---------------------------------------------------------------------------


def _slow_subflow_executor(
    *,
    sleep_a: float = 0.0,
    gate: tuple[threading.Event, threading.Event] | None = None,
) -> FlowExecutor:
    """Parent flows that compose a 2-step sub-flow whose first tool sleeps.

    ``t_slow`` sleeps ``sleep_a`` seconds so a deadline lands at the boundary
    *inside* the sub-flow — after its first step, before its second — which
    only the parent's forwarded ``deadline`` / ``cancel_token`` can observe.

    When ``gate`` is supplied, ``t_slow`` instead sets the first event on entry
    and blocks on the second before returning, so a test can drive a
    cross-thread cancel into the sub-flow deterministically — no sleep race
    (#244).
    """

    def _slow_inc(inp: _NIn) -> dict[str, Any]:
        if gate is not None:
            entered, proceed = gate
            entered.set()
            proceed.wait(timeout=_BARRIER_TIMEOUT_S)
        elif sleep_a:
            time.sleep(sleep_a)
        return {"a": inp.n + 1}

    def _plus(inp: _AIn) -> dict[str, Any]:
        return {"b": inp.a + 1}

    registry = FlowRegistry()
    registry.register_flow(
        Flow(
            name="sub_slow",
            version="1.0.0",
            description="slow inc, then plus.",
            steps=[
                FlowStep(tool_name="t_slow", input_mapping={"n": "n"}),
                FlowStep(tool_name="t_plus", input_mapping={"a": "a"}),
            ],
        )
    )
    registry.register_flow(
        Flow(
            name="parent_slow",
            version="1.0.0",
            description="compose sub_slow.",
            steps=[FlowStep(flow_name="sub_slow", input_mapping={"n": "n"})],
        )
    )
    registry.register_flow(
        DAGFlow(
            name="dag_parent_slow",
            version="1.0.0",
            description="compose sub_slow as the single DAG node.",
            steps=[
                DAGFlowStep(
                    flow_name="sub_slow", step_id="A", depends_on=[], input_mapping={"n": "n"}
                ),
            ],
        )
    )
    ex = FlowExecutor(registry=registry)
    ex.register_tool(
        Tool(
            name="t_slow",
            description="slow inc",
            input_schema=_NIn,
            output_schema=_AOut,
            fn=_slow_inc,
        )
    )
    ex.register_tool(
        Tool(name="t_plus", description="plus", input_schema=_AIn, output_schema=_BOut, fn=_plus)
    )
    return ex


class TestCompositionCancellation:
    def test_deadline_observed_between_subflow_steps(self) -> None:
        ex = _slow_subflow_executor(sleep_a=0.15)
        with pytest.raises(FlowCancelledError) as exc_info:
            ex.execute_flow("parent_slow", {"n": 1}, deadline=time.time() + 0.05)
        err = exc_info.value
        # The deadline fired *inside* the sub-flow, but the error is re-anchored
        # to the parent: parent name, parent step index, and a parent partial
        # whose composed step carries the sub-flow's partial as `sub_result`.
        assert err.deadline_exceeded is True
        assert err.token_cancelled is False
        assert err.flow_name == "parent_slow"
        assert err.step_index == 0
        assert len(err.result.execution_log) == 1
        composed = err.result.execution_log[0]
        assert composed.flow_name == "sub_slow"
        assert composed.success is False
        assert composed.sub_result is not None
        # The sub-flow's own partial holds its one completed step (a = n + 1).
        assert len(composed.sub_result.execution_log) == 1
        assert composed.sub_result.execution_log[0].outputs == {"a": 2}

    def test_token_cancel_observed_in_subflow(self) -> None:
        entered = threading.Event()
        proceed = threading.Event()
        ex = _slow_subflow_executor(gate=(entered, proceed))
        token = CancellationToken()

        # Deterministic barrier (#244): cancel while the sub-flow's first step
        # is in-flight, then release it so the request is guaranteed visible at
        # the boundary before the sub-flow's second step.
        def _cancel_in_step() -> None:
            entered.wait(timeout=_BARRIER_TIMEOUT_S)
            token.cancel()
            proceed.set()

        canceller = threading.Thread(target=_cancel_in_step)
        canceller.start()
        try:
            with pytest.raises(FlowCancelledError) as exc_info:
                ex.execute_flow("parent_slow", {"n": 1}, cancel_token=token)
        finally:
            canceller.join()
        err = exc_info.value
        assert err.token_cancelled is True
        assert err.deadline_exceeded is False
        assert err.flow_name == "parent_slow"
        assert err.result.execution_log[0].flow_name == "sub_slow"

    def test_dag_deadline_observed_in_subflow(self) -> None:
        ex = _slow_subflow_executor(sleep_a=0.15)
        with pytest.raises(FlowCancelledError) as exc_info:
            ex.execute_flow("dag_parent_slow", {"n": 1}, deadline=time.time() + 0.05)
        err = exc_info.value
        assert err.deadline_exceeded is True
        assert err.flow_name == "dag_parent_slow"
        composed = err.result.execution_log[0]
        assert composed.flow_name == "sub_slow"
        assert composed.sub_result is not None

    def test_parent_flow_end_fires_on_subflow_cancellation(self) -> None:
        # Regression for the audit finding: cancellation inside a composed
        # sub-flow must still fire the *parent's* on_flow_end (it pairs with
        # on_flow_start only via the partial result), and the nested sub-flow's
        # flow_end fires too.
        ended: list[str] = []

        class _RecordEnds:
            def on_flow_start(self, ctx: object) -> None:
                pass

            def on_step_start(self, ctx: object) -> None:
                pass

            def on_step_end(self, ctx: object) -> None:
                pass

            def on_flow_end(self, ctx: Any) -> None:
                ended.append(ctx.flow_name)

        ex = _slow_subflow_executor(sleep_a=0.15)
        ex.add_middleware(_RecordEnds())
        with pytest.raises(FlowCancelledError):
            ex.execute_flow("parent_slow", {"n": 1}, deadline=time.time() + 0.05)
        # Both the sub-flow and the parent must have fired flow_end exactly once.
        assert ended.count("sub_slow") == 1
        assert ended.count("parent_slow") == 1

    def test_no_cancel_composed_flow_completes(self) -> None:
        ex = _slow_subflow_executor(sleep_a=0.0)
        result = ex.execute_flow(
            "parent_slow",
            {"n": 1},
            deadline=time.time() + 100,
            cancel_token=CancellationToken(),
        )
        assert result.success is True
        assert result.final_output is not None
        assert result.final_output["b"] == 3


# ---------------------------------------------------------------------------
# Cost report accounts for nested tool invocations in composed flows (issue #75)
# ---------------------------------------------------------------------------


class TestCompositionCostReport:
    def test_composed_step_counts_nested_tool_invocations(self) -> None:
        # Sub-flow ``inc`` runs one tool; a parent that composes it plus one
        # direct tool ran two genuine tool invocations, not "one composed
        # step + one tool".
        ex = _base_executor()
        ex._cost_profile = CostProfile()
        ex._registry.register_flow(
            Flow(
                name="parent",
                version="1.0.0",
                description="inc (sub-flow) then plus (tool).",
                steps=[
                    FlowStep(flow_name="inc", input_mapping={"n": "n"}),
                    FlowStep(tool_name="t_plus", input_mapping={"a": "a"}),
                ],
            )
        )
        result = ex.execute_flow("parent", {"n": 1})
        assert result.success is True
        assert result.cost_report is not None
        # 1 nested tool (inc -> t_inc) + 1 direct tool (t_plus) = 2.
        assert result.cost_report.steps_executed == 2
        assert result.cost_report.llm_calls_avoided == 1

    def test_nested_composition_counts_recursively(self) -> None:
        # level1 -> level2 -> inc (tool). The whole tree ran exactly one tool,
        # so the composed containers must not each add a phantom invocation.
        ex = _base_executor()
        ex._cost_profile = CostProfile()
        ex._registry.register_flow(
            Flow(
                name="level2",
                version="1.0.0",
                description="wraps inc.",
                steps=[FlowStep(flow_name="inc", input_mapping={"n": "n"})],
            )
        )
        ex._registry.register_flow(
            Flow(
                name="level1",
                version="1.0.0",
                description="wraps level2.",
                steps=[FlowStep(flow_name="level2", input_mapping={"n": "n"})],
            )
        )
        result = ex.execute_flow("level1", {"n": 1})
        assert result.success is True
        assert result.cost_report is not None
        assert result.cost_report.steps_executed == 1
        assert result.cost_report.llm_calls_avoided == 0
