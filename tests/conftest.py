"""Shared test fixtures for ChainWeaver."""

from __future__ import annotations

import pytest
from helpers import (
    FormattedOutput,
    NumberInput,
    ValueInput,
    ValueOutput,
    _add_ten_fn,
    _double_fn,
    _format_fn,
)

from chainweaver.executor import FlowExecutor
from chainweaver.flow import Flow, FlowStep
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def double_tool() -> Tool:
    return Tool(
        name="double",
        description="Doubles a number.",
        input_schema=NumberInput,
        output_schema=ValueOutput,
        fn=_double_fn,
    )


@pytest.fixture()
def add_ten_tool() -> Tool:
    return Tool(
        name="add_ten",
        description="Adds 10 to a value.",
        input_schema=ValueInput,
        output_schema=ValueOutput,
        fn=_add_ten_fn,
    )


@pytest.fixture()
def format_tool() -> Tool:
    return Tool(
        name="format_result",
        description="Formats a value.",
        input_schema=ValueInput,
        output_schema=FormattedOutput,
        fn=_format_fn,
    )


@pytest.fixture()
def linear_flow() -> Flow:
    return Flow(
        name="double_add_format",
        description="Doubles a number, adds 10, and formats the result.",
        steps=[
            FlowStep(tool_name="double", input_mapping={"number": "number"}),
            FlowStep(tool_name="add_ten", input_mapping={"value": "value"}),
            FlowStep(tool_name="format_result", input_mapping={"value": "value"}),
        ],
    )


@pytest.fixture()
def executor(
    linear_flow: Flow,
    double_tool: Tool,
    add_ten_tool: Tool,
    format_tool: Tool,
) -> FlowExecutor:
    registry = FlowRegistry()
    registry.register_flow(linear_flow)
    ex = FlowExecutor(registry=registry)
    ex.register_tool(double_tool)
    ex.register_tool(add_ten_tool)
    ex.register_tool(format_tool)
    return ex
