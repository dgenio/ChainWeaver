"""Tests for FlowExecutor.replay_flow (issue #21)."""

from __future__ import annotations

from typing import Any

import pytest
from helpers import (
    NumberInput,
    ValueInput,
    ValueOutput,
    _add_ten_fn,
    _double_fn,
)
from pydantic import BaseModel

from chainweaver.executor import (
    ExecutionResult,
    FlowExecutor,
    ReplayMode,
    ReplayResult,
)
from chainweaver.flow import DAGFlow, DAGFlowStep, Flow, FlowStep
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool


def _build_executor() -> FlowExecutor:
    flow = Flow(
        name="replay_two_step",
        version="0.1.0",
        description="Two-step flow used for replay tests.",
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
            description="Doubles.",
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
# VERIFY mode: deterministic flows match
# ---------------------------------------------------------------------------


class TestVerifyMatch:
    def test_deterministic_replay_has_no_diffs(self) -> None:
        ex = _build_executor()
        original = ex.execute_flow("replay_two_step", {"number": 3})
        replay = ex.replay_flow(original, mode=ReplayMode.VERIFY)
        assert isinstance(replay, ReplayResult)
        assert replay.original_trace_id == original.trace_id
        assert replay.mode is ReplayMode.VERIFY
        assert replay.diffs == []
        assert replay.all_steps_match is True

    def test_initial_input_persisted_on_result(self) -> None:
        ex = _build_executor()
        result = ex.execute_flow("replay_two_step", {"number": 7})
        assert result.initial_input == {"number": 7}

    def test_new_result_has_distinct_trace_id(self) -> None:
        ex = _build_executor()
        original = ex.execute_flow("replay_two_step", {"number": 1})
        replay = ex.replay_flow(original)
        assert replay.new_result.trace_id != original.trace_id


# ---------------------------------------------------------------------------
# VERIFY mode: non-deterministic flows expose diffs
# ---------------------------------------------------------------------------


class TestVerifyDiff:
    def test_changing_tool_output_produces_diff(self) -> None:
        registry = FlowRegistry()
        registry.register_flow(
            Flow(
                name="moving_target",
                version="0.1.0",
                description="Tool output changes between runs.",
                steps=[FlowStep(tool_name="counter", input_mapping={"number": "number"})],
            )
        )
        # First version returns 1, then we swap the function so replay returns 2.
        state = {"v": 1}

        def counter(_: NumberInput) -> dict[str, Any]:
            return {"value": state["v"]}

        tool = Tool(
            name="counter",
            description="Returns whatever state['v'] is right now.",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=counter,
        )
        ex = FlowExecutor(registry=registry)
        ex.register_tool(tool)

        original = ex.execute_flow("moving_target", {"number": 0})
        state["v"] = 2  # change "the world" between runs
        replay = ex.replay_flow(original, mode=ReplayMode.VERIFY)
        assert replay.all_steps_match is False
        assert len(replay.diffs) == 1
        diff = replay.diffs[0]
        assert diff.step_index == 0
        assert diff.tool_name == "counter"
        assert diff.field == "value"
        assert diff.expected == 1
        assert diff.actual == 2


# ---------------------------------------------------------------------------
# EXECUTE mode never compares
# ---------------------------------------------------------------------------


class TestExecuteMode:
    def test_execute_mode_skips_diffs(self) -> None:
        ex = _build_executor()
        original = ex.execute_flow("replay_two_step", {"number": 3})
        replay = ex.replay_flow(original, mode=ReplayMode.EXECUTE)
        assert replay.diffs == []
        assert replay.all_steps_match is True
        assert replay.new_result.success is True

    def test_legacy_mode_aliases(self) -> None:
        assert ReplayMode.__members__["STRICT"] is ReplayMode.VERIFY
        assert ReplayMode.__members__["SKIP_VALIDATION"] is ReplayMode.EXECUTE


# ---------------------------------------------------------------------------
# resume_from_step
# ---------------------------------------------------------------------------


class TestResumeFromStep:
    def test_resume_skips_already_completed_steps(self) -> None:
        ex = _build_executor()
        original = ex.execute_flow("replay_two_step", {"number": 3})
        # Replay starting at step 1 — first step's output is reused from the
        # original log, second step is rerun.
        replay = ex.replay_flow(
            original,
            mode=ReplayMode.EXECUTE,
            resume_from_step=1,
        )
        new = replay.new_result
        # Only the second step should appear in the replay log.
        assert len(new.execution_log) == 1
        assert new.execution_log[0].tool_name == "add_ten"
        # The final output mirrors the full original (initial + double + add_ten).
        assert new.final_output == original.final_output

    def test_resume_with_verify_mode_reports_no_diffs_for_match(self) -> None:
        ex = _build_executor()
        original = ex.execute_flow("replay_two_step", {"number": 3})
        replay = ex.replay_flow(
            original,
            mode=ReplayMode.VERIFY,
            resume_from_step=1,
        )
        assert replay.all_steps_match is True
        assert replay.diffs == []

    def test_dag_flow_rejects_resume(self) -> None:
        registry = FlowRegistry()
        flow = DAGFlow(
            name="dag_replay",
            version="0.1.0",
            description="Linear DAG used to verify the rejection path.",
            steps=[DAGFlowStep(tool_name="double", step_id="A", depends_on=[])],
        )
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(
            Tool(
                name="double",
                description="Doubles.",
                input_schema=NumberInput,
                output_schema=ValueOutput,
                fn=_double_fn,
            )
        )
        original = ex.execute_flow("dag_replay", {"number": 1})
        with pytest.raises(ValueError):
            ex.replay_flow(original, resume_from_step=1)


# ---------------------------------------------------------------------------
# Replay with missing tool
# ---------------------------------------------------------------------------


class TestReplayWithMissingTool:
    def test_missing_tool_during_replay_records_failure(self) -> None:
        # Build executor with the tool, run, then rebuild without the tool
        # and replay the captured result.
        registry = FlowRegistry()
        flow = Flow(
            name="missing_tool",
            version="0.1.0",
            description="Single step.",
            steps=[FlowStep(tool_name="ephemeral", input_mapping={"x": "x"})],
        )
        registry.register_flow(flow)

        class Inp(BaseModel):
            x: int

        class Out(BaseModel):
            x: int

        ephemeral = Tool(
            name="ephemeral",
            description="Returns x.",
            input_schema=Inp,
            output_schema=Out,
            fn=lambda inp: {"x": inp.x},
        )
        ex_with = FlowExecutor(registry=registry)
        ex_with.register_tool(ephemeral)
        original = ex_with.execute_flow("missing_tool", {"x": 5})

        ex_without = FlowExecutor(registry=registry)
        replay = ex_without.replay_flow(original, mode=ReplayMode.EXECUTE)
        assert replay.new_result.success is False
        assert replay.new_result.execution_log[0].error_type == "ToolNotFoundError"


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


class TestReplayResultSerialization:
    def test_replay_result_round_trips(self) -> None:
        ex = _build_executor()
        original = ex.execute_flow("replay_two_step", {"number": 3})
        replay = ex.replay_flow(original)
        payload = replay.model_dump_json()
        rebuilt = ReplayResult.model_validate_json(payload)
        assert rebuilt.original_trace_id == replay.original_trace_id
        assert rebuilt.mode == replay.mode
        assert isinstance(rebuilt.new_result, ExecutionResult)
