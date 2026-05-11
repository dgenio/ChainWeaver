"""Tests for tool execution guardrails — timeout + output-size (issue #43)."""

from __future__ import annotations

import time
from typing import Any

import pytest
from helpers import NumberInput, ValueOutput
from pydantic import BaseModel

from chainweaver.exceptions import ToolOutputSizeError, ToolTimeoutError
from chainweaver.executor import FlowExecutor
from chainweaver.flow import Flow, FlowStep
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool

# ---------------------------------------------------------------------------
# Direct Tool.run() behaviour
# ---------------------------------------------------------------------------


class TestToolRunGuardrails:
    def test_no_guardrails_unchanged(self) -> None:
        tool = Tool(
            name="double",
            description="Doubles.",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=lambda inp: {"value": inp.number * 2},
        )
        assert tool.run({"number": 7}) == {"value": 14}

    def test_timeout_unset_does_not_use_thread(self) -> None:
        # Sanity check: the simple path doesn't go through the thread pool.
        tool = Tool(
            name="passthrough",
            description="Returns x.",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=lambda inp: {"value": inp.number},
        )
        assert tool.timeout_seconds is None
        assert tool.run({"number": 3}) == {"value": 3}

    def test_timeout_fires_for_slow_fn(self) -> None:
        def slow(_: NumberInput) -> dict[str, Any]:
            time.sleep(0.5)
            return {"value": 1}

        tool = Tool(
            name="slow",
            description="Sleeps then returns.",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=slow,
            timeout_seconds=0.05,
        )
        with pytest.raises(ToolTimeoutError) as exc_info:
            tool.run({"number": 1})
        assert exc_info.value.tool_name == "slow"
        assert exc_info.value.timeout_seconds == 0.05

    def test_timeout_not_triggered_for_fast_fn(self) -> None:
        tool = Tool(
            name="fast",
            description="Fast.",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=lambda inp: {"value": inp.number * 2},
            timeout_seconds=5.0,
        )
        assert tool.run({"number": 3}) == {"value": 6}

    def test_output_size_check_fires(self) -> None:
        class BigOut(BaseModel):
            payload: str

        big = "x" * 5000

        def fn(_: NumberInput) -> dict[str, Any]:
            return {"payload": big}

        tool = Tool(
            name="big",
            description="Large output.",
            input_schema=NumberInput,
            output_schema=BigOut,
            fn=fn,
            max_output_size=100,
        )
        with pytest.raises(ToolOutputSizeError) as exc_info:
            tool.run({"number": 1})
        assert exc_info.value.tool_name == "big"
        assert exc_info.value.size > exc_info.value.max_size
        assert exc_info.value.max_size == 100

    def test_output_size_not_triggered_for_small_payload(self) -> None:
        class SmallOut(BaseModel):
            payload: str

        tool = Tool(
            name="small",
            description="Small output.",
            input_schema=NumberInput,
            output_schema=SmallOut,
            fn=lambda inp: {"payload": "ok"},
            max_output_size=1024,
        )
        assert tool.run({"number": 1}) == {"payload": "ok"}

    def test_both_guardrails_set_normal_path(self) -> None:
        tool = Tool(
            name="ok",
            description="ok.",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=lambda inp: {"value": inp.number},
            timeout_seconds=5.0,
            max_output_size=1024,
        )
        assert tool.run({"number": 9}) == {"value": 9}


# ---------------------------------------------------------------------------
# Executor integration: errors land in StepRecord with the right error_type
# ---------------------------------------------------------------------------


def _build_executor(tool: Tool) -> FlowExecutor:
    flow = Flow(
        name="guardrail_flow",
        description="One-step flow used for guardrail integration.",
        steps=[FlowStep(tool_name=tool.name, input_mapping={"number": "number"})],
    )
    registry = FlowRegistry()
    registry.register_flow(flow)
    ex = FlowExecutor(registry=registry)
    ex.register_tool(tool)
    return ex


class TestExecutorRecordsGuardrailErrors:
    def test_timeout_recorded_with_specific_error_type(self) -> None:
        def slow(_: NumberInput) -> dict[str, Any]:
            time.sleep(0.5)
            return {"value": 1}

        tool = Tool(
            name="slow",
            description="Sleeps.",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=slow,
            timeout_seconds=0.05,
        )
        ex = _build_executor(tool)
        result = ex.execute_flow("guardrail_flow", {"number": 1})
        assert result.success is False
        record = result.execution_log[0]
        assert record.error_type == "ToolTimeoutError"
        assert record.error_message is not None
        assert "exceeded timeout" in record.error_message

    def test_output_size_recorded_with_specific_error_type(self) -> None:
        class BigOut(BaseModel):
            payload: str

        def big_fn(_: NumberInput) -> dict[str, Any]:
            return {"payload": "x" * 5000}

        tool = Tool(
            name="big",
            description="Large output.",
            input_schema=NumberInput,
            output_schema=BigOut,
            fn=big_fn,
            max_output_size=100,
        )
        ex = _build_executor(tool)
        result = ex.execute_flow("guardrail_flow", {"number": 1})
        assert result.success is False
        record = result.execution_log[0]
        assert record.error_type == "ToolOutputSizeError"
        assert record.error_message is not None
        assert "exceeds max" in record.error_message
