"""Tests for the @tool decorator."""

from __future__ import annotations

from typing import Annotated

import pytest
from pydantic import BaseModel, Field

from chainweaver import tool
from chainweaver.exceptions import ToolDefinitionError
from chainweaver.executor import FlowExecutor
from chainweaver.flow import Flow, FlowStep
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool

# ---------------------------------------------------------------------------
# Shared output schemas for decorator tests
# ---------------------------------------------------------------------------


class ValueOutput(BaseModel):
    value: int


class GreetOutput(BaseModel):
    message: str


# ---------------------------------------------------------------------------
# Basic usage
# ---------------------------------------------------------------------------


class TestBasicUsage:
    def test_creates_valid_tool(self) -> None:
        @tool(description="Doubles a number.")
        def double(number: int) -> ValueOutput:
            return {"value": number * 2}

        assert isinstance(double, Tool)
        assert double.name == "double"
        assert double.description == "Doubles a number."

    def test_tool_run_validates_and_returns(self) -> None:
        @tool(description="Doubles a number.")
        def double(number: int) -> ValueOutput:
            return {"value": number * 2}

        result = double.run({"number": 5})
        assert result == {"value": 10}

    def test_repr(self) -> None:
        @tool(description="Doubles a number.")
        def double(number: int) -> ValueOutput:
            return {"value": number * 2}

        assert repr(double) == "Tool(name='double')"


# ---------------------------------------------------------------------------
# Custom name
# ---------------------------------------------------------------------------


class TestCustomName:
    def test_overrides_function_name(self) -> None:
        @tool(name="my_double", description="Doubles.")
        def double(number: int) -> ValueOutput:
            return {"value": number * 2}

        assert double.name == "my_double"


# ---------------------------------------------------------------------------
# Description fallback
# ---------------------------------------------------------------------------


class TestDescriptionFallback:
    def test_uses_docstring_when_no_description(self) -> None:
        @tool()
        def double(number: int) -> ValueOutput:
            """Doubles a number."""
            return {"value": number * 2}

        assert double.description == "Doubles a number."

    def test_bare_decorator_uses_docstring(self) -> None:
        @tool
        def double(number: int) -> ValueOutput:
            """Doubles a number."""
            return {"value": number * 2}

        assert double.description == "Doubles a number."

    def test_empty_description_when_nothing_provided(self) -> None:
        @tool()
        def double(number: int) -> ValueOutput:
            return {"value": number * 2}

        assert double.description == ""

    def test_explicit_description_overrides_docstring(self) -> None:
        @tool(description="Custom desc.")
        def double(number: int) -> ValueOutput:
            """This docstring is ignored."""
            return {"value": number * 2}

        assert double.description == "Custom desc."


# ---------------------------------------------------------------------------
# Direct callable
# ---------------------------------------------------------------------------


class TestDirectCallable:
    def test_callable_with_kwargs(self) -> None:
        @tool(description="Doubles a number.")
        def double(number: int) -> ValueOutput:
            return {"value": number * 2}

        assert double(number=5) == {"value": 10}

    def test_callable_with_positional_args(self) -> None:
        @tool(description="Doubles a number.")
        def double(number: int) -> ValueOutput:
            return {"value": number * 2}

        assert double(5) == {"value": 10}


# ---------------------------------------------------------------------------
# Missing / insufficient type hints
# ---------------------------------------------------------------------------


class TestMissingHints:
    def test_missing_return_type(self) -> None:
        with pytest.raises(ToolDefinitionError, match="Missing a return type") as exc_info:

            @tool(description="Bad.")
            def bad(x: int):  # type: ignore[no-untyped-def]
                return {"value": x}

        assert exc_info.value.function_name == "bad"

    def test_non_basemodel_return_type(self) -> None:
        with pytest.raises(ToolDefinitionError, match="must be a BaseModel subclass"):

            @tool(description="Bad.")
            def bad(x: int) -> dict:  # type: ignore[type-arg]
                return {"value": x}

    def test_missing_param_annotation(self) -> None:
        with pytest.raises(ToolDefinitionError, match="missing a type annotation"):

            @tool(description="Bad.")
            def bad(x) -> ValueOutput:  # type: ignore[no-untyped-def]
                return {"value": x}

    def test_var_positional_rejected(self) -> None:
        with pytest.raises(ToolDefinitionError, match="\\*args or \\*\\*kwargs"):

            @tool(description="Bad.")
            def bad(*args: int) -> ValueOutput:
                return {"value": 0}

    def test_var_keyword_rejected(self) -> None:
        with pytest.raises(ToolDefinitionError, match="\\*args or \\*\\*kwargs"):

            @tool(description="Bad.")
            def bad(**kwargs: int) -> ValueOutput:
                return {"value": 0}

    def test_positional_only_rejected(self) -> None:
        with pytest.raises(ToolDefinitionError, match="positional-only parameters"):

            @tool(description="Bad.")
            def bad(x: int, /) -> ValueOutput:
                return {"value": x}

    def test_unresolvable_forward_ref(self) -> None:
        with pytest.raises(ToolDefinitionError, match="Failed to resolve type hints"):

            @tool(description="Bad.")
            def bad(x: NoSuchType) -> ValueOutput:  # type: ignore[name-defined]  # noqa: F821
                return {"value": 0}


# ---------------------------------------------------------------------------
# Default parameter values
# ---------------------------------------------------------------------------


class TestDefaultValues:
    def test_required_param_only(self) -> None:
        @tool(description="Adds.")
        def add(a: int, b: int = 10) -> ValueOutput:
            return {"value": a + b}

        result = add.run({"a": 5})
        assert result == {"value": 15}

    def test_both_params_provided(self) -> None:
        @tool(description="Adds.")
        def add(a: int, b: int = 10) -> ValueOutput:
            return {"value": a + b}

        result = add.run({"a": 5, "b": 20})
        assert result == {"value": 25}


# ---------------------------------------------------------------------------
# No-parameter tools
# ---------------------------------------------------------------------------


class TestNoParameters:
    def test_no_params_creates_empty_schema(self) -> None:
        @tool(description="Returns fixed value.")
        def fixed() -> ValueOutput:
            return {"value": 42}

        result = fixed.run({})
        assert result == {"value": 42}


# ---------------------------------------------------------------------------
# Annotated type support
# ---------------------------------------------------------------------------


class TestAnnotatedSupport:
    def test_annotated_field_metadata(self) -> None:
        @tool(description="Greets.")
        def greet(
            name: Annotated[str, Field(description="The name to greet")],
        ) -> GreetOutput:
            return {"message": f"Hello, {name}!"}

        result = greet.run({"name": "World"})
        assert result == {"message": "Hello, World!"}

        # Verify the field description was preserved in the schema.
        name_field = greet.input_schema.model_fields["name"]
        assert name_field.description == "The name to greet"


# ---------------------------------------------------------------------------
# Round-trip with FlowExecutor
# ---------------------------------------------------------------------------


class TestRoundTripWithExecutor:
    def test_decorator_tool_in_flow(self) -> None:
        @tool(description="Doubles a number.")
        def double(number: int) -> ValueOutput:
            return {"value": number * 2}

        flow = Flow(
            name="decorator_flow",
            description="Test flow with decorated tool.",
            steps=[FlowStep(tool_name="double", input_mapping={"number": "number"})],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(double)

        result = ex.execute_flow("decorator_flow", {"number": 5})
        assert result.success is True
        assert result.final_output is not None
        assert result.final_output["value"] == 10

    def test_multi_step_flow_with_decorated_tools(self) -> None:
        @tool(description="Doubles a number.")
        def double(number: int) -> ValueOutput:
            return {"value": number * 2}

        @tool(description="Adds ten.")
        def add_ten(value: int) -> ValueOutput:
            return {"value": value + 10}

        flow = Flow(
            name="double_then_add",
            description="Doubles then adds ten.",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "number"}),
                FlowStep(tool_name="add_ten", input_mapping={"value": "value"}),
            ],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(double)
        ex.register_tool(add_ten)

        result = ex.execute_flow("double_then_add", {"number": 5})
        assert result.success is True
        assert result.final_output is not None
        assert result.final_output["value"] == 20
