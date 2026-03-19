"""Tests for the @tool decorator."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

import chainweaver
from chainweaver.exceptions import ToolDecoratorError
from chainweaver.executor import FlowExecutor
from chainweaver.flow import Flow, FlowStep
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool

# ---------------------------------------------------------------------------
# Shared output schemas used across tests
# ---------------------------------------------------------------------------


class DoubledOutput(BaseModel):
    value: int


class SumOutput(BaseModel):
    total: int


class GreetOutput(BaseModel):
    message: str


# ---------------------------------------------------------------------------
# Basic decorator behaviour
# ---------------------------------------------------------------------------


class TestBasicDecorator:
    def test_returns_tool_instance(self) -> None:
        @chainweaver.tool(description="Doubles a number.")
        def double(number: int) -> DoubledOutput:
            return {"value": number * 2}  # type: ignore[return-value]

        assert isinstance(double, Tool)

    def test_tool_name_defaults_to_function_name(self) -> None:
        @chainweaver.tool(description="Doubles a number.")
        def double(number: int) -> DoubledOutput:
            return {"value": number * 2}  # type: ignore[return-value]

        assert double.name == "double"

    def test_tool_description_set_explicitly(self) -> None:
        @chainweaver.tool(description="Explicit description.")
        def my_fn(x: int) -> DoubledOutput:
            return {"value": x}  # type: ignore[return-value]

        assert my_fn.description == "Explicit description."

    def test_tool_description_falls_back_to_docstring(self) -> None:
        @chainweaver.tool
        def my_fn(x: int) -> DoubledOutput:
            """Docstring description."""
            return {"value": x}  # type: ignore[return-value]

        assert my_fn.description == "Docstring description."

    def test_tool_description_empty_when_no_docstring(self) -> None:
        @chainweaver.tool
        def my_fn(x: int) -> DoubledOutput:
            return {"value": x}  # type: ignore[return-value]

        assert my_fn.description == ""

    def test_input_schema_has_correct_fields(self) -> None:
        @chainweaver.tool
        def add(a: int, b: int) -> SumOutput:
            return {"total": a + b}  # type: ignore[return-value]

        model_fields = add.input_schema.model_fields
        assert "a" in model_fields
        assert "b" in model_fields

    def test_output_schema_is_return_type(self) -> None:
        @chainweaver.tool
        def double(number: int) -> DoubledOutput:
            return {"value": number * 2}  # type: ignore[return-value]

        assert double.output_schema is DoubledOutput


# ---------------------------------------------------------------------------
# Custom name
# ---------------------------------------------------------------------------


class TestCustomName:
    def test_custom_name_override(self) -> None:
        @chainweaver.tool(name="my_custom_tool", description="Custom.")
        def double(number: int) -> DoubledOutput:
            return {"value": number * 2}  # type: ignore[return-value]

        assert double.name == "my_custom_tool"

    def test_custom_name_reflected_in_repr(self) -> None:
        @chainweaver.tool(name="renamed")
        def fn(x: int) -> DoubledOutput:
            return {"value": x}  # type: ignore[return-value]

        assert "renamed" in repr(fn)


# ---------------------------------------------------------------------------
# Direct callability (Tool.__call__)
# ---------------------------------------------------------------------------


class TestDirectCallability:
    def test_decorated_tool_callable_with_kwargs(self) -> None:
        @chainweaver.tool
        def double(number: int) -> DoubledOutput:
            return {"value": number * 2}  # type: ignore[return-value]

        result = double(number=5)
        assert result == {"value": 10}

    def test_decorated_tool_callable_with_default_param(self) -> None:
        @chainweaver.tool
        def add(a: int, b: int = 3) -> SumOutput:
            return {"total": a + b}  # type: ignore[return-value]

        assert add(a=7) == {"total": 10}
        assert add(a=7, b=10) == {"total": 17}

    def test_plain_tool_also_callable(self) -> None:
        """Tool.__call__ also works on Tools created via the explicit constructor."""

        class NumIn(BaseModel):
            n: int

        class NumOut(BaseModel):
            result: int

        t = Tool(
            name="triple",
            description="Triples.",
            input_schema=NumIn,
            output_schema=NumOut,
            fn=lambda inp: {"result": inp.n * 3},
        )
        assert t(n=4) == {"result": 12}


# ---------------------------------------------------------------------------
# Decorator used without parentheses
# ---------------------------------------------------------------------------


class TestDecoratorWithoutParentheses:
    def test_bare_decorator_returns_tool(self) -> None:
        @chainweaver.tool
        def greet(name: str) -> GreetOutput:
            return {"message": f"Hello, {name}!"}  # type: ignore[return-value]

        assert isinstance(greet, Tool)
        assert greet.name == "greet"
        assert greet(name="Alice") == {"message": "Hello, Alice!"}


# ---------------------------------------------------------------------------
# Default parameter values are preserved in input schema
# ---------------------------------------------------------------------------


class TestDefaultParameters:
    def test_default_value_makes_field_optional(self) -> None:
        @chainweaver.tool
        def add(a: int, b: int = 10) -> SumOutput:
            return {"total": a + b}  # type: ignore[return-value]

        fields = add.input_schema.model_fields
        assert fields["b"].default == 10
        assert fields["a"].is_required()


# ---------------------------------------------------------------------------
# Error cases
# ---------------------------------------------------------------------------


class TestDecoratorErrors:
    def test_missing_return_type_raises(self) -> None:
        with pytest.raises(ToolDecoratorError, match="Missing return type annotation"):

            @chainweaver.tool
            def no_return(x: int):  # type: ignore[return]
                return {"value": x}

    def test_non_basemodel_return_type_raises(self) -> None:
        with pytest.raises(ToolDecoratorError, match="Return type must be a BaseModel subclass"):

            @chainweaver.tool
            def bad_return(x: int) -> dict:  # type: ignore[return-value]
                return {"value": x}

    def test_missing_parameter_annotation_raises(self) -> None:
        with pytest.raises(ToolDecoratorError, match="has no type annotation"):

            @chainweaver.tool
            def missing_hint(x) -> DoubledOutput:  # type: ignore[no-untyped-def]
                return {"value": x}  # type: ignore[return-value]

    def test_error_inherits_from_chainweaver_error(self) -> None:
        with pytest.raises(chainweaver.ChainWeaverError):

            @chainweaver.tool
            def no_return(x: int):  # type: ignore[return]
                return {"value": x}

    def test_error_exposes_fn_name(self) -> None:
        with pytest.raises(ToolDecoratorError) as exc_info:

            @chainweaver.tool
            def my_broken_fn(x: int):  # type: ignore[return]
                return {"value": x}

        assert exc_info.value.fn_name == "my_broken_fn"


# ---------------------------------------------------------------------------
# Round-trip with FlowExecutor
# ---------------------------------------------------------------------------


class TestRoundTripWithExecutor:
    def test_decorator_tool_runs_in_flow(self) -> None:
        @chainweaver.tool(description="Doubles a number.")
        def double(number: int) -> DoubledOutput:
            return {"value": number * 2}  # type: ignore[return-value]

        flow = Flow(
            name="just_double",
            description="Single-step double flow.",
            steps=[FlowStep(tool_name="double", input_mapping={"number": "number"})],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        executor = FlowExecutor(registry=registry)
        executor.register_tool(double)

        result = executor.execute_flow("just_double", {"number": 7})
        assert result.success is True
        assert result.final_output is not None
        assert result.final_output["value"] == 14

    def test_decorator_tool_works_alongside_explicit_tool(self) -> None:
        """Mixing @tool decorator and explicit Tool() in the same flow."""

        class ValueIn(BaseModel):
            value: int

        class FormattedOut(BaseModel):
            result: str

        @chainweaver.tool(description="Doubles a number.")
        def double(number: int) -> DoubledOutput:
            return {"value": number * 2}  # type: ignore[return-value]

        format_tool = Tool(
            name="format_result",
            description="Formats a value.",
            input_schema=ValueIn,
            output_schema=FormattedOut,
            fn=lambda inp: {"result": f"value={inp.value}"},
        )

        flow = Flow(
            name="double_then_format",
            description="Doubles then formats.",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "number"}),
                FlowStep(tool_name="format_result", input_mapping={"value": "value"}),
            ],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        executor = FlowExecutor(registry=registry)
        executor.register_tool(double)
        executor.register_tool(format_tool)

        result = executor.execute_flow("double_then_format", {"number": 4})
        assert result.success is True
        assert result.final_output is not None
        assert result.final_output["result"] == "value=8"
