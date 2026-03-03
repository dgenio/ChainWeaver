"""Shared test fixtures for ChainWeaver."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from chainweaver.executor import FlowExecutor
from chainweaver.flow import Flow, FlowStep
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool

# ---------------------------------------------------------------------------
# Shared Pydantic schemas
# ---------------------------------------------------------------------------


class NumberInput(BaseModel):
    number: int


class ValueOutput(BaseModel):
    value: int


class ValueInput(BaseModel):
    value: int


class FormattedOutput(BaseModel):
    result: str


# ---------------------------------------------------------------------------
# Shared tool functions
# ---------------------------------------------------------------------------


def _double_fn(inp: NumberInput) -> dict:
    return {"value": inp.number * 2}


def _add_ten_fn(inp: ValueInput) -> dict:
    return {"value": inp.value + 10}


def _format_fn(inp: ValueInput) -> dict:
    return {"result": f"Final value: {inp.value}"}


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
