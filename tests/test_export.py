"""Tests for export adapters (issue #25)."""

from __future__ import annotations

from typing import Any

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
from pydantic import BaseModel

from chainweaver.exceptions import FlowExecutionError, ToolDefinitionError
from chainweaver.executor import FlowExecutor
from chainweaver.export import (
    flow_to_anthropic_tool,
    flow_to_callable,
    flow_to_openai_function,
    tool_to_anthropic_tool,
    tool_to_callable,
    tool_to_openai_function,
)
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
        description="Adds 10.",
        input_schema=ValueInput,
        output_schema=ValueOutput,
        fn=_add_ten_fn,
    )


@pytest.fixture()
def format_tool() -> Tool:
    return Tool(
        name="format_result",
        description="Format the value.",
        input_schema=ValueInput,
        output_schema=FormattedOutput,
        fn=_format_fn,
    )


@pytest.fixture()
def linear_executor(
    double_tool: Tool,
    add_ten_tool: Tool,
    format_tool: Tool,
) -> FlowExecutor:
    flow = Flow(
        name="double_add_format",
        version="0.1.0",
        description="Doubles → adds 10 → formats the value.",
        steps=[
            FlowStep(tool_name="double", input_mapping={"number": "number"}),
            FlowStep(tool_name="add_ten", input_mapping={"value": "value"}),
            FlowStep(tool_name="format_result", input_mapping={"value": "value"}),
        ],
    )
    registry = FlowRegistry()
    registry.register_flow(flow)
    executor = FlowExecutor(registry=registry)
    executor.register_tool(double_tool)
    executor.register_tool(add_ten_tool)
    executor.register_tool(format_tool)
    return executor


# ---------------------------------------------------------------------------
# OpenAI export
# ---------------------------------------------------------------------------


class TestFlowToOpenAIFunction:
    def test_basic_shape(self, linear_executor: FlowExecutor) -> None:
        flow = linear_executor._registry.get_flow("double_add_format")
        payload = flow_to_openai_function(flow, linear_executor)

        assert payload["type"] == "function"
        assert payload["function"]["name"] == "double_add_format"
        assert payload["function"]["description"] == flow.description
        params = payload["function"]["parameters"]
        assert params["type"] == "object"
        # NumberInput has a single integer field ``number``.
        assert "number" in params["properties"]
        assert params["properties"]["number"]["type"] == "integer"
        # The Pydantic-emitted ``title`` is stripped from the top level.
        assert "title" not in params

    def test_name_and_description_overrides(self, linear_executor: FlowExecutor) -> None:
        flow = linear_executor._registry.get_flow("double_add_format")
        payload = flow_to_openai_function(
            flow,
            linear_executor,
            name="custom_name",
            description="custom desc",
        )
        assert payload["function"]["name"] == "custom_name"
        assert payload["function"]["description"] == "custom desc"

    def test_explicit_input_schema_overrides_derived(self, linear_executor: FlowExecutor) -> None:
        class _AltInput(BaseModel):
            alt: str

        flow = linear_executor._registry.get_flow("double_add_format")
        payload = flow_to_openai_function(flow, linear_executor, input_schema=_AltInput)
        assert "alt" in payload["function"]["parameters"]["properties"]

    def test_raises_when_first_tool_unregistered(
        self, linear_executor: FlowExecutor, double_tool: Tool
    ) -> None:
        # Construct an unregistered flow whose first step references an unknown tool.
        bad_flow = Flow(
            name="bad",
            version="0.1.0",
            description="references a tool nobody registered",
            steps=[FlowStep(tool_name="nonexistent", input_mapping={"x": "y"})],
        )
        with pytest.raises(ToolDefinitionError):
            flow_to_openai_function(bad_flow, linear_executor)


class TestToolToOpenAIFunction:
    def test_emits_function_spec(self, double_tool: Tool) -> None:
        payload = tool_to_openai_function(double_tool)
        assert payload["type"] == "function"
        assert payload["function"]["name"] == "double"
        assert payload["function"]["description"] == "Doubles a number."
        assert "number" in payload["function"]["parameters"]["properties"]


# ---------------------------------------------------------------------------
# Anthropic export
# ---------------------------------------------------------------------------


class TestFlowToAnthropicTool:
    def test_basic_shape(self, linear_executor: FlowExecutor) -> None:
        flow = linear_executor._registry.get_flow("double_add_format")
        payload = flow_to_anthropic_tool(flow, linear_executor)

        assert payload["name"] == "double_add_format"
        assert payload["description"] == flow.description
        schema = payload["input_schema"]
        assert schema["type"] == "object"
        assert "number" in schema["properties"]
        assert "title" not in schema

    def test_top_level_keys(self, linear_executor: FlowExecutor) -> None:
        flow = linear_executor._registry.get_flow("double_add_format")
        payload = flow_to_anthropic_tool(flow, linear_executor)
        assert set(payload) == {"name", "description", "input_schema"}


class TestToolToAnthropicTool:
    def test_emits_input_schema(self, double_tool: Tool) -> None:
        payload = tool_to_anthropic_tool(double_tool)
        assert payload["name"] == "double"
        assert payload["input_schema"]["properties"]["number"]["type"] == "integer"


# ---------------------------------------------------------------------------
# Callable export
# ---------------------------------------------------------------------------


class TestFlowToCallable:
    def test_executes_flow_end_to_end(self, linear_executor: FlowExecutor) -> None:
        flow = linear_executor._registry.get_flow("double_add_format")
        run = flow_to_callable(flow, linear_executor)
        out = run({"number": 5})
        # Double: 5 → 10. Add ten: 10 → 20. Format: "Final value: 20".
        assert out["result"] == "Final value: 20"

    def test_callable_has_flow_name(self, linear_executor: FlowExecutor) -> None:
        flow = linear_executor._registry.get_flow("double_add_format")
        run = flow_to_callable(flow, linear_executor)
        assert run.__name__ == "double_add_format"

    def test_callable_name_override(self, linear_executor: FlowExecutor) -> None:
        flow = linear_executor._registry.get_flow("double_add_format")
        run = flow_to_callable(flow, linear_executor, name="custom_runner")
        assert run.__name__ == "custom_runner"

    def test_validation_failure_raises(self, linear_executor: FlowExecutor) -> None:
        flow = linear_executor._registry.get_flow("double_add_format")
        run = flow_to_callable(flow, linear_executor)
        # ``number`` must be an int; passing a non-coercible value should
        # surface as a pydantic ValidationError.
        with pytest.raises(Exception) as exc_info:
            run({"number": "not_a_number"})
        assert "number" in str(exc_info.value)

    def test_flow_execution_failure_raises_flow_execution_error(
        self, linear_executor: FlowExecutor
    ) -> None:
        # Register and execute a flow whose tool raises at runtime.
        class _Inp(BaseModel):
            x: int

        class _Out(BaseModel):
            y: int

        def _boom(inp: _Inp) -> dict[str, Any]:
            raise RuntimeError("kaboom")

        boom_flow = Flow(
            name="boom",
            version="0.1.0",
            description="Always fails.",
            steps=[FlowStep(tool_name="boomer", input_mapping={"x": "x"})],
        )
        registry = linear_executor._registry
        registry.register_flow(boom_flow)
        linear_executor.register_tool(
            Tool(
                name="boomer",
                description="raises",
                input_schema=_Inp,
                output_schema=_Out,
                fn=_boom,
            )
        )
        run = flow_to_callable(boom_flow, linear_executor)
        with pytest.raises(FlowExecutionError):
            run({"x": 1})


class TestToolToCallable:
    def test_runs_with_validation(self, double_tool: Tool) -> None:
        run = tool_to_callable(double_tool)
        assert run({"number": 7}) == {"value": 14}

    def test_callable_has_tool_name(self, double_tool: Tool) -> None:
        run = tool_to_callable(double_tool)
        assert run.__name__ == "double"


# ---------------------------------------------------------------------------
# JSON Schema validity of emitted parameters (against Draft 2020-12 surface)
# ---------------------------------------------------------------------------


class TestEmittedSchemaShape:
    """Sanity checks that the emitted JSON Schema bodies look like real schemas."""

    def test_openai_parameters_is_object_schema(self, double_tool: Tool) -> None:
        payload = tool_to_openai_function(double_tool)
        params = payload["function"]["parameters"]
        assert params["type"] == "object"
        assert "properties" in params

    def test_anthropic_input_schema_is_object_schema(self, double_tool: Tool) -> None:
        payload = tool_to_anthropic_tool(double_tool)
        schema = payload["input_schema"]
        assert schema["type"] == "object"
        assert "properties" in schema

    def test_required_fields_propagate(self, double_tool: Tool) -> None:
        """NumberInput has no default — ``number`` should be required."""
        payload = tool_to_openai_function(double_tool)
        params = payload["function"]["parameters"]
        # Pydantic emits ``required`` for fields without defaults.
        assert "required" in params
        assert "number" in params["required"]
