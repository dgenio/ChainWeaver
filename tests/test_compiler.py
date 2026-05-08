"""Tests for compile-time schema chain validation."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from chainweaver.compiler import CompilationResult, compile_flow
from chainweaver.flow import Flow, FlowStep
from chainweaver.tools import Tool

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class NumberInput(BaseModel):
    number: int


class ValueOutput(BaseModel):
    value: int


class ValueInput(BaseModel):
    value: int


class FormattedOutput(BaseModel):
    result: str


class FloatInput(BaseModel):
    value: float


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------


def _double_fn(inp: NumberInput) -> dict[str, Any]:
    return {"value": inp.number * 2}


def _add_ten_fn(inp: ValueInput) -> dict[str, Any]:
    return {"value": inp.value + 10}


def _format_fn(inp: ValueInput) -> dict[str, Any]:
    return {"result": f"Final value: {inp.value}"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tools() -> dict[str, Tool]:
    return {
        "double": Tool(
            name="double",
            description="Doubles.",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=_double_fn,
        ),
        "add_ten": Tool(
            name="add_ten",
            description="Adds ten.",
            input_schema=ValueInput,
            output_schema=ValueOutput,
            fn=_add_ten_fn,
        ),
        "format_result": Tool(
            name="format_result",
            description="Formats.",
            input_schema=ValueInput,
            output_schema=FormattedOutput,
            fn=_format_fn,
        ),
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestValidFlow:
    def test_valid_flow_compiles_successfully(self) -> None:
        tools = _make_tools()
        flow = Flow(
            name="double_add_format",
            description="Doubles, adds ten, formats.",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "number"}),
                FlowStep(tool_name="add_ten", input_mapping={"value": "value"}),
                FlowStep(tool_name="format_result", input_mapping={"value": "value"}),
            ],
            input_schema=NumberInput,
            output_schema=FormattedOutput,
        )
        result = compile_flow(flow, tools)
        assert result.success is True
        assert result.errors == []

    def test_valid_flow_without_schemas(self) -> None:
        tools = _make_tools()
        flow = Flow(
            name="simple",
            description="Simple flow.",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "number"}),
            ],
            input_schema=NumberInput,
        )
        result = compile_flow(flow, tools)
        assert result.success is True


class TestMissingTool:
    def test_missing_tool_detected(self) -> None:
        flow = Flow(
            name="bad",
            description="Bad flow.",
            steps=[FlowStep(tool_name="nonexistent", input_mapping={"x": "x"})],
            input_schema=NumberInput,
        )
        result = compile_flow(flow, {})
        assert result.success is False
        assert len(result.errors) == 1
        assert result.errors[0].issue_type == "missing_tool"
        assert result.errors[0].tool_name == "nonexistent"


class TestMissingMappingKey:
    def test_missing_key_in_mapping(self) -> None:
        tools = _make_tools()
        flow = Flow(
            name="bad_mapping",
            description="Bad mapping.",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "missing_key"}),
            ],
            input_schema=NumberInput,
        )
        result = compile_flow(flow, tools)
        assert result.success is False
        assert any(e.issue_type == "missing_mapping_key" for e in result.errors)

    def test_mapping_to_upstream_output_succeeds(self) -> None:
        tools = _make_tools()
        flow = Flow(
            name="chained",
            description="Chained flow.",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "number"}),
                FlowStep(tool_name="add_ten", input_mapping={"value": "value"}),
            ],
            input_schema=NumberInput,
        )
        result = compile_flow(flow, tools)
        assert result.success is True


class TestTypeMismatch:
    def test_incompatible_types_detected(self) -> None:
        class StrInput(BaseModel):
            value: str

        class StrOutput(BaseModel):
            text: str

        def _str_fn(inp: StrInput) -> dict[str, Any]:
            return {"text": inp.value}

        str_tool = Tool(
            name="str_tool",
            description="Outputs a string.",
            input_schema=StrInput,
            output_schema=StrOutput,
            fn=_str_fn,
        )

        tools = {"str_tool": str_tool, **_make_tools()}
        flow = Flow(
            name="type_mismatch",
            description="Type mismatch flow.",
            steps=[
                FlowStep(tool_name="str_tool", input_mapping={"value": "number"}),
                # "text" (str) mapped to "value" (int) on add_ten
                FlowStep(tool_name="add_ten", input_mapping={"value": "text"}),
            ],
            input_schema=NumberInput,
        )
        result = compile_flow(flow, tools)
        assert result.success is False
        type_errors = [e for e in result.errors if e.issue_type == "type_mismatch"]
        assert len(type_errors) >= 1

    def test_numeric_widening_allowed(self) -> None:
        class IntOut(BaseModel):
            value: int

        class FloatIn(BaseModel):
            value: float

        class FloatOut(BaseModel):
            result: float

        def _int_fn(inp: NumberInput) -> dict[str, Any]:
            return {"value": inp.number}

        def _float_fn(inp: FloatIn) -> dict[str, Any]:
            return {"result": inp.value * 1.5}

        int_tool = Tool(
            name="int_tool",
            description="Produces int.",
            input_schema=NumberInput,
            output_schema=IntOut,
            fn=_int_fn,
        )
        float_tool = Tool(
            name="float_tool",
            description="Consumes float.",
            input_schema=FloatIn,
            output_schema=FloatOut,
            fn=_float_fn,
        )

        tools = {"int_tool": int_tool, "float_tool": float_tool}
        flow = Flow(
            name="widening",
            description="Int to float widening.",
            steps=[
                FlowStep(tool_name="int_tool", input_mapping={"number": "number"}),
                FlowStep(tool_name="float_tool", input_mapping={"value": "value"}),
            ],
            input_schema=NumberInput,
        )
        result = compile_flow(flow, tools)
        assert result.success is True


class TestOutputSchemaGap:
    def test_output_schema_gap_detected(self) -> None:
        class RequiredOutput(BaseModel):
            value: int
            missing_field: str

        tools = _make_tools()
        flow = Flow(
            name="gap",
            description="Missing output field.",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "number"}),
            ],
            input_schema=NumberInput,
            output_schema=RequiredOutput,
        )
        result = compile_flow(flow, tools)
        assert result.success is False
        gap_errors = [e for e in result.errors if e.issue_type == "output_schema_gap"]
        assert len(gap_errors) == 1
        assert gap_errors[0].field_name == "missing_field"


class TestCompilationResult:
    def test_result_dataclass_fields(self) -> None:
        result = CompilationResult(success=True, errors=[], warnings=[])
        assert result.success is True
        assert result.errors == []
        assert result.warnings == []
