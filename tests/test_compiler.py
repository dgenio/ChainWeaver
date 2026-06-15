"""Tests for compile-time schema flow validation."""

from __future__ import annotations

from typing import Any, Union

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


class RequiredOutputWithMissingField(BaseModel):
    value: int
    missing_field: str


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
            version="0.1.0",
            description="Doubles, adds ten, formats.",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "number"}),
                FlowStep(tool_name="add_ten", input_mapping={"value": "value"}),
                FlowStep(tool_name="format_result", input_mapping={"value": "value"}),
            ],
            input_schema_ref=Flow.schema_ref_from(NumberInput),
            output_schema_ref=Flow.schema_ref_from(FormattedOutput),
        )
        result = compile_flow(flow, tools)
        assert result.success is True
        assert result.errors == []

    def test_valid_flow_without_schemas(self) -> None:
        tools = _make_tools()
        flow = Flow(
            name="simple",
            version="0.1.0",
            description="Simple flow.",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "number"}),
            ],
            input_schema_ref=Flow.schema_ref_from(NumberInput),
        )
        result = compile_flow(flow, tools)
        assert result.success is True


class TestMissingTool:
    def test_missing_tool_detected(self) -> None:
        flow = Flow(
            name="bad",
            version="0.1.0",
            description="Bad flow.",
            steps=[FlowStep(tool_name="nonexistent", input_mapping={"x": "x"})],
            input_schema_ref=Flow.schema_ref_from(NumberInput),
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
            version="0.1.0",
            description="Bad mapping.",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "missing_key"}),
            ],
            input_schema_ref=Flow.schema_ref_from(NumberInput),
        )
        result = compile_flow(flow, tools)
        assert result.success is False
        assert any(e.issue_type == "missing_mapping_key" for e in result.errors)

    def test_mapping_to_upstream_output_succeeds(self) -> None:
        tools = _make_tools()
        flow = Flow(
            name="multi_step",
            version="0.1.0",
            description="Multi-step flow.",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "number"}),
                FlowStep(tool_name="add_ten", input_mapping={"value": "value"}),
            ],
            input_schema_ref=Flow.schema_ref_from(NumberInput),
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
            version="0.1.0",
            description="Type mismatch flow.",
            steps=[
                FlowStep(tool_name="str_tool", input_mapping={"value": "number"}),
                # "text" (str) mapped to "value" (int) on add_ten
                FlowStep(tool_name="add_ten", input_mapping={"value": "text"}),
            ],
            input_schema_ref=Flow.schema_ref_from(NumberInput),
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
            version="0.1.0",
            description="Int to float widening.",
            steps=[
                FlowStep(tool_name="int_tool", input_mapping={"number": "number"}),
                FlowStep(tool_name="float_tool", input_mapping={"value": "value"}),
            ],
            input_schema_ref=Flow.schema_ref_from(NumberInput),
        )
        result = compile_flow(flow, tools)
        assert result.success is True


class TestOutputSchemaGap:
    def test_output_schema_gap_detected(self) -> None:
        tools = _make_tools()
        flow = Flow(
            name="gap",
            version="0.1.0",
            description="Missing output field.",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "number"}),
            ],
            input_schema_ref=Flow.schema_ref_from(NumberInput),
            output_schema_ref=Flow.schema_ref_from(RequiredOutputWithMissingField),
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


class TestOptionalTypeCompatibility:
    """Optional[T] / Union handling in `_get_field_type`."""

    def test_optional_int_accepts_int_source(self) -> None:
        # `Union[int, None]` is the canonical form of `Optional[int]`; both
        # surface as Union origins and exercise the same code path. Using the
        # Union spelling here avoids ruff UP045 on `Optional[...]`.
        class OptionalIntInput(BaseModel):
            value: Union[int, None] = None  # noqa: UP007 — explicit Union for the test

        class OutSchema(BaseModel):
            ok: bool

        def _fn(inp: OptionalIntInput) -> dict[str, Any]:
            return {"ok": True}

        opt_tool = Tool(
            name="opt",
            description="Accepts optional int.",
            input_schema=OptionalIntInput,
            output_schema=OutSchema,
            fn=_fn,
        )
        tools = {"opt": opt_tool, **_make_tools()}
        flow = Flow(
            name="opt_flow",
            version="0.1.0",
            description="Map int into Optional[int].",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "number"}),
                FlowStep(tool_name="opt", input_mapping={"value": "value"}),
            ],
            input_schema_ref=Flow.schema_ref_from(NumberInput),
        )
        result = compile_flow(flow, tools)
        assert result.success is True
        assert not any(e.issue_type == "type_mismatch" for e in result.errors)

    def test_pep604_union_int_or_none_accepts_int_source(self) -> None:
        class PEP604Input(BaseModel):
            value: int | None = None

        class OutSchema(BaseModel):
            ok: bool

        def _fn(inp: PEP604Input) -> dict[str, Any]:
            return {"ok": True}

        tool = Tool(
            name="pep604",
            description="Accepts int | None.",
            input_schema=PEP604Input,
            output_schema=OutSchema,
            fn=_fn,
        )
        tools = {"pep604": tool, **_make_tools()}
        flow = Flow(
            name="pep604_flow",
            version="0.1.0",
            description="Map int into int | None.",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "number"}),
                FlowStep(tool_name="pep604", input_mapping={"value": "value"}),
            ],
            input_schema_ref=Flow.schema_ref_from(NumberInput),
        )
        result = compile_flow(flow, tools)
        assert result.success is True

    def test_multi_arm_union_treated_as_unknown(self) -> None:
        class MultiArmInput(BaseModel):
            value: Union[int, str] = 0  # noqa: UP007 — multi-arm union by design

        class OutSchema(BaseModel):
            ok: bool

        def _fn(inp: MultiArmInput) -> dict[str, Any]:
            return {"ok": True}

        tool = Tool(
            name="multi",
            description="Accepts int | str.",
            input_schema=MultiArmInput,
            output_schema=OutSchema,
            fn=_fn,
        )
        tools = {"multi": tool, **_make_tools()}
        # Map an int source — should pass (unknown target treats as compatible).
        flow = Flow(
            name="multi_flow",
            version="0.1.0",
            description="Map int into Union[int, str].",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "number"}),
                FlowStep(tool_name="multi", input_mapping={"value": "value"}),
            ],
            input_schema_ref=Flow.schema_ref_from(NumberInput),
        )
        result = compile_flow(flow, tools)
        # Multi-arm Union[int, str] is unknown → no false-positive type_mismatch.
        assert not any(e.issue_type == "type_mismatch" for e in result.errors)


class TestUnknownTargetKey:
    def test_unknown_target_key_is_error(self) -> None:
        tools = _make_tools()
        flow = Flow(
            name="bad_target",
            version="0.1.0",
            description="Maps to a field the tool does not declare.",
            steps=[
                FlowStep(
                    tool_name="double",
                    input_mapping={"number": "number", "ghost": "number"},
                ),
            ],
            input_schema_ref=Flow.schema_ref_from(NumberInput),
        )
        result = compile_flow(flow, tools)
        assert result.success is False
        unknown_errors = [e for e in result.errors if e.issue_type == "unknown_target_key"]
        assert len(unknown_errors) == 1
        assert unknown_errors[0].field_name == "ghost"


class TestMissingRequiredInput:
    def test_missing_required_input_detected(self) -> None:
        class TwoFieldInput(BaseModel):
            a: int
            b: int

        class OutSchema(BaseModel):
            sum: int

        def _fn(inp: TwoFieldInput) -> dict[str, Any]:
            return {"sum": inp.a + inp.b}

        tools = {
            "two": Tool(
                name="two",
                description="Needs both a and b.",
                input_schema=TwoFieldInput,
                output_schema=OutSchema,
                fn=_fn,
            )
        }
        # Provide only `a` via mapping — `b` is required but missing.
        flow = Flow(
            name="missing_required",
            version="0.1.0",
            description="Only `a` is mapped.",
            steps=[FlowStep(tool_name="two", input_mapping={"a": "number"})],
            input_schema_ref=Flow.schema_ref_from(NumberInput),
        )
        result = compile_flow(flow, tools)
        assert result.success is False
        missing = [e for e in result.errors if e.issue_type == "missing_required_input"]
        assert len(missing) == 1
        assert missing[0].field_name == "b"

    def test_empty_mapping_satisfied_by_context(self) -> None:
        class SingleFieldInput(BaseModel):
            number: int

        class OutSchema(BaseModel):
            ok: bool

        def _fn(inp: SingleFieldInput) -> dict[str, Any]:
            return {"ok": True}

        tools = {
            "one": Tool(
                name="one",
                description="Needs `number`.",
                input_schema=SingleFieldInput,
                output_schema=OutSchema,
                fn=_fn,
            )
        }
        # Empty mapping — `number` is in the input_schema context, so it is satisfied.
        flow = Flow(
            name="empty_map",
            version="0.1.0",
            description="Empty mapping satisfied by context.",
            steps=[FlowStep(tool_name="one")],
            input_schema_ref=Flow.schema_ref_from(NumberInput),
        )
        result = compile_flow(flow, tools)
        assert result.success is True

    def test_optional_input_not_flagged_as_missing(self) -> None:
        class OptionalFieldInput(BaseModel):
            value: int | None = None

        class OutSchema(BaseModel):
            ok: bool

        def _fn(inp: OptionalFieldInput) -> dict[str, Any]:
            return {"ok": True}

        tools = {
            "opt": Tool(
                name="opt",
                description="Optional input.",
                input_schema=OptionalFieldInput,
                output_schema=OutSchema,
                fn=_fn,
            )
        }
        # No mapping for "value", and "value" not in context — but it's optional.
        flow = Flow(
            name="optional_unmapped",
            version="0.1.0",
            description="Optional input deliberately unmapped.",
            steps=[FlowStep(tool_name="opt", input_mapping={"_dummy": "number"})],
            input_schema_ref=Flow.schema_ref_from(NumberInput),
        )
        result = compile_flow(flow, tools)
        # Optional input field `value` should not produce a missing_required_input
        # error — but the `_dummy` mapping target is unknown.
        assert not any(e.issue_type == "missing_required_input" for e in result.errors)


class TestFallbackInputCompatibility:
    def test_compatible_fallback_compiles(self) -> None:
        tools = _make_tools()
        flow = Flow(
            name="fallback_ok",
            description="Compatible fallback.",
            steps=[
                FlowStep(
                    tool_name="double",
                    input_mapping={"number": "number"},
                    on_error="fallback:double",
                )
            ],
            input_schema_ref=Flow.schema_ref_from(NumberInput),
        )

        result = compile_flow(flow, tools)

        assert result.success is True
        assert not any(error.issue_type.startswith("fallback_") for error in result.errors)

    def test_missing_fallback_tool_is_error(self) -> None:
        flow = Flow(
            name="fallback_missing",
            description="Missing fallback.",
            steps=[
                FlowStep(
                    tool_name="double",
                    input_mapping={"number": "number"},
                    on_error="fallback:missing",
                )
            ],
            input_schema_ref=Flow.schema_ref_from(NumberInput),
        )

        result = compile_flow(flow, _make_tools())

        error = next(
            error for error in result.errors if error.issue_type == "missing_fallback_tool"
        )
        assert result.success is False
        assert error.tool_name == "missing"

    def test_fallback_type_mismatch_is_error(self) -> None:
        class TextNumberInput(BaseModel):
            number: str

        tools = _make_tools()
        tools["backup"] = Tool(
            name="backup",
            description="Requires text.",
            input_schema=TextNumberInput,
            output_schema=ValueOutput,
            fn=lambda inp: {"value": len(inp.number)},
        )
        flow = Flow(
            name="fallback_type",
            description="Fallback type mismatch.",
            steps=[
                FlowStep(
                    tool_name="double",
                    input_mapping={"number": "number"},
                    on_error="fallback:backup",
                )
            ],
            input_schema_ref=Flow.schema_ref_from(NumberInput),
        )

        result = compile_flow(flow, tools)

        error = next(
            error for error in result.errors if error.issue_type == "fallback_type_mismatch"
        )
        assert result.success is False
        assert error.tool_name == "backup"
        assert error.field_name == "number"

    def test_fallback_mapping_shape_is_checked(self) -> None:
        class TextInput(BaseModel):
            text: str

        tools = _make_tools()
        tools["backup"] = Tool(
            name="backup",
            description="Requires text.",
            input_schema=TextInput,
            output_schema=ValueOutput,
            fn=lambda inp: {"value": len(inp.text)},
        )
        flow = Flow(
            name="fallback_shape",
            description="Fallback mapping mismatch.",
            steps=[
                FlowStep(
                    tool_name="double",
                    input_mapping={"number": "number"},
                    on_error="fallback:backup",
                )
            ],
            input_schema_ref=Flow.schema_ref_from(NumberInput),
        )

        result = compile_flow(flow, tools)

        issue_types = {error.issue_type for error in result.errors}
        assert result.success is False
        assert issue_types >= {
            "fallback_unknown_target_key",
            "fallback_missing_required_input",
        }
