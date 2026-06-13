"""Context key-collision policy across linear and DAG flows (issue #337).

A step output that overwrites an existing context key is governed by one shared
merge implementation (``chainweaver._execution.merge_step_outputs``) for both
flow kinds and both lanes. The flow-level ``on_context_collision`` setting
selects the behaviour: ``"overwrite"`` (silent last-write-wins), ``"warn"``
(default; log at WARNING), or ``"error"`` (abort with a typed error).
"""

from __future__ import annotations

import logging
from typing import Any

import pytest
from pydantic import BaseModel

from chainweaver.compiler import compile_flow
from chainweaver.exceptions import ContextKeyCollisionError
from chainweaver.executor import FlowExecutor
from chainweaver.flow import DAGFlow, DAGFlowStep, Flow, FlowStep
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool

_EXECUTOR_LOGGER = "chainweaver.executor"


# ---------------------------------------------------------------------------
# Tools: step 2 re-emits the ``value`` key produced by step 1 -> collision.
# ---------------------------------------------------------------------------


class NumIn(BaseModel):
    number: int


class ValOut(BaseModel):
    value: int


def _to_value(inp: NumIn) -> dict[str, Any]:
    return {"value": inp.number}


class ValIn(BaseModel):
    value: int


def _bump(inp: ValIn) -> dict[str, Any]:
    return {"value": inp.value + 1}


def _tools() -> list[Tool]:
    return [
        Tool(
            name="to_value",
            description="number -> value",
            input_schema=NumIn,
            output_schema=ValOut,
            fn=_to_value,
        ),
        Tool(
            name="bump",
            description="value -> value+1 (re-emits 'value')",
            input_schema=ValIn,
            output_schema=ValOut,
            fn=_bump,
        ),
    ]


def _linear_flow(policy: str) -> Flow:
    return Flow(
        name="collide_linear",
        version="1.0.0",
        description="Two steps both producing 'value'.",
        steps=[
            FlowStep(tool_name="to_value", input_mapping={"number": "number"}),
            FlowStep(tool_name="bump", input_mapping={"value": "value"}),
        ],
        on_context_collision=policy,  # type: ignore[arg-type]
    )


def _dag_flow(policy: str) -> DAGFlow:
    return DAGFlow(
        name="collide_dag",
        version="1.0.0",
        description="Level 2 re-emits the key produced at level 1.",
        steps=[
            DAGFlowStep(step_id="a", tool_name="to_value", input_mapping={"number": "number"}),
            DAGFlowStep(
                step_id="b",
                tool_name="bump",
                input_mapping={"value": "value"},
                depends_on=["a"],
            ),
        ],
        on_context_collision=policy,  # type: ignore[arg-type]
    )


def _executor(flow: Flow | DAGFlow) -> FlowExecutor:
    registry = FlowRegistry()
    registry.register_flow(flow)
    executor = FlowExecutor(registry=registry)
    for tool in _tools():
        executor.register_tool(tool)
    return executor


# ---------------------------------------------------------------------------
# Default + overwrite
# ---------------------------------------------------------------------------


def test_default_policy_is_warn() -> None:
    assert Flow(name="f", version="1.0.0", description="", steps=[]).on_context_collision == "warn"
    assert (
        DAGFlow(name="f", version="1.0.0", description="", steps=[]).on_context_collision == "warn"
    )


@pytest.mark.parametrize("make_flow", [_linear_flow, _dag_flow])
def test_overwrite_is_silent_last_write_wins(
    make_flow: Any, caplog: pytest.LogCaptureFixture
) -> None:
    executor = _executor(make_flow("overwrite"))
    with caplog.at_level(logging.WARNING, logger=_EXECUTOR_LOGGER):
        result = executor.execute_flow(make_flow("overwrite").name, {"number": 5})
    assert result.success
    assert result.final_output is not None and result.final_output["value"] == 6
    assert not [r for r in caplog.records if "overwritten" in r.message]


# ---------------------------------------------------------------------------
# warn
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("make_flow", [_linear_flow, _dag_flow])
def test_warn_logs_and_overwrites(make_flow: Any, caplog: pytest.LogCaptureFixture) -> None:
    flow = make_flow("warn")
    executor = _executor(flow)
    with caplog.at_level(logging.WARNING, logger=_EXECUTOR_LOGGER):
        result = executor.execute_flow(flow.name, {"number": 5})
    assert result.success
    assert result.final_output is not None and result.final_output["value"] == 6
    warnings = [
        r for r in caplog.records if "overwritten" in r.message and r.levelno == logging.WARNING
    ]
    assert warnings, "expected a WARNING-level collision log"


# ---------------------------------------------------------------------------
# error
# ---------------------------------------------------------------------------


def test_error_policy_aborts_linear_with_typed_error() -> None:
    flow = _linear_flow("error")
    executor = _executor(flow)
    with pytest.raises(ContextKeyCollisionError) as exc_info:
        executor.execute_flow(flow.name, {"number": 5})
    assert exc_info.value.keys == ["value"]
    assert exc_info.value.step_index == 1
    assert exc_info.value.flow_name == "collide_linear"


def test_error_policy_aborts_dag_with_typed_error() -> None:
    flow = _dag_flow("error")
    executor = _executor(flow)
    with pytest.raises(ContextKeyCollisionError) as exc_info:
        executor.execute_flow(flow.name, {"number": 5})
    assert exc_info.value.keys == ["value"]


async def test_error_policy_aborts_async_linear() -> None:
    flow = _linear_flow("error")
    executor = _executor(flow)
    with pytest.raises(ContextKeyCollisionError):
        await executor.execute_flow_async(flow.name, {"number": 5})


# ---------------------------------------------------------------------------
# compile-time static warning
# ---------------------------------------------------------------------------


def test_compile_flow_warns_on_static_collision() -> None:
    flow = _linear_flow("warn")
    tools = {tool.name: tool for tool in _tools()}
    result = compile_flow(flow, tools)
    collisions = [w for w in result.warnings if w.issue_type == "context_collision"]
    assert collisions and collisions[0].field_name == "value"


def test_compile_flow_suppresses_collision_warning_under_overwrite() -> None:
    flow = _linear_flow("overwrite")
    tools = {tool.name: tool for tool in _tools()}
    result = compile_flow(flow, tools)
    assert not [w for w in result.warnings if w.issue_type == "context_collision"]
