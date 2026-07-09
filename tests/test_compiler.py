"""Tests for compile-time schema flow validation."""

from __future__ import annotations

from typing import Any, Union

from pydantic import BaseModel

from chainweaver.compiler import CompilationResult, compile_flow
from chainweaver.contracts import SideEffectLevel, ToolSafetyContract
from chainweaver.flow import DAGFlow, DAGFlowStep, Flow, FlowStep, RetryPolicy
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


class TestUnsafeRetryAdvisory:
    """``RetryPolicy`` against an unsafe-to-retry contract is a warning (#488)."""

    def test_safe_to_retry_false_warns(self) -> None:
        tools = _make_tools()
        tools["double"] = Tool(
            name="double",
            description="Doubles, but not safe to retry.",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=_double_fn,
            safety=ToolSafetyContract(side_effects=SideEffectLevel.EXTERNAL, safe_to_retry=False),
        )
        flow = Flow(
            name="unsafe_retry",
            description="Retries a tool that declares it unsafe to retry.",
            steps=[
                FlowStep(
                    tool_name="double",
                    input_mapping={"number": "number"},
                    retry=RetryPolicy(max_retries=2, backoff_seconds=0.0),
                )
            ],
            input_schema_ref=Flow.schema_ref_from(NumberInput),
        )
        result = compile_flow(flow, tools)
        assert result.success is True  # advisory only, not blocking
        warning = next(w for w in result.warnings if w.issue_type == "unsafe_retry")
        assert warning.tool_name == "double"
        assert warning.step_index == 0

    def test_non_idempotent_side_effecting_warns(self) -> None:
        tools = _make_tools()
        tools["double"] = Tool(
            name="double",
            description="Doubles, non-idempotent side effect.",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=_double_fn,
            safety=ToolSafetyContract(side_effects=SideEffectLevel.WRITE, idempotent=False),
        )
        flow = Flow(
            name="unsafe_retry_non_idempotent",
            description="Retries a non-idempotent, side-effecting tool.",
            steps=[
                FlowStep(
                    tool_name="double",
                    input_mapping={"number": "number"},
                    retry=RetryPolicy(max_retries=2, backoff_seconds=0.0),
                )
            ],
            input_schema_ref=Flow.schema_ref_from(NumberInput),
        )
        result = compile_flow(flow, tools)
        assert any(w.issue_type == "unsafe_retry" for w in result.warnings)

    def test_non_idempotent_read_only_does_not_warn(self) -> None:
        # Non-idempotent but read-only: nothing external to duplicate.
        tools = _make_tools()
        tools["double"] = Tool(
            name="double",
            description="Doubles, non-idempotent but read-only.",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=_double_fn,
            safety=ToolSafetyContract(side_effects=SideEffectLevel.READ, idempotent=False),
        )
        flow = Flow(
            name="safe_retry_read_only",
            description="Retries a non-idempotent read-only tool.",
            steps=[
                FlowStep(
                    tool_name="double",
                    input_mapping={"number": "number"},
                    retry=RetryPolicy(max_retries=2, backoff_seconds=0.0),
                )
            ],
            input_schema_ref=Flow.schema_ref_from(NumberInput),
        )
        result = compile_flow(flow, tools)
        assert not any(w.issue_type == "unsafe_retry" for w in result.warnings)

    def test_default_safety_contract_does_not_warn(self) -> None:
        # The default ToolSafetyContract is maximally permissive
        # (safe_to_retry=True, idempotent=True) — no advisory expected.
        tools = _make_tools()
        flow = Flow(
            name="default_safe_retry",
            description="Retries a tool with the default safety contract.",
            steps=[
                FlowStep(
                    tool_name="double",
                    input_mapping={"number": "number"},
                    retry=RetryPolicy(max_retries=2, backoff_seconds=0.0),
                )
            ],
            input_schema_ref=Flow.schema_ref_from(NumberInput),
        )
        result = compile_flow(flow, tools)
        assert not any(w.issue_type == "unsafe_retry" for w in result.warnings)

    def test_no_retry_policy_no_warning_even_if_unsafe(self) -> None:
        tools = _make_tools()
        tools["double"] = Tool(
            name="double",
            description="Unsafe to retry, but no RetryPolicy attached.",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=_double_fn,
            safety=ToolSafetyContract(side_effects=SideEffectLevel.EXTERNAL, safe_to_retry=False),
        )
        flow = Flow(
            name="unsafe_no_retry_policy",
            description="No retry attached at all.",
            steps=[FlowStep(tool_name="double", input_mapping={"number": "number"})],
            input_schema_ref=Flow.schema_ref_from(NumberInput),
        )
        result = compile_flow(flow, tools)
        assert not any(w.issue_type == "unsafe_retry" for w in result.warnings)


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


class TestFallbackOutputCompatibility:
    """Fallback output-schema compatibility checks (issue #457)."""

    def test_compatible_fallback_output_compiles(self) -> None:
        # double and add_ten both declare ValueOutput(value: int); reusing
        # double as its own fallback keeps the output shape identical.
        tools = _make_tools()
        flow = Flow(
            name="fb_out_ok",
            description="Fallback with an identical output shape.",
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
        assert not any(w.issue_type.startswith("fallback_output_") for w in result.warnings)

    def test_fallback_output_shape_divergence_warns(self) -> None:
        tools = _make_tools()
        tools["double_alt"] = Tool(
            name="double_alt",
            description="Same input, different output key.",
            input_schema=NumberInput,
            output_schema=FormattedOutput,  # produces 'result', not 'value'
            fn=lambda inp: {"result": str(inp.number)},
        )
        flow = Flow(
            name="fb_out_diverge",
            description="Fallback output shape diverges from the primary.",
            steps=[
                FlowStep(
                    tool_name="double",
                    input_mapping={"number": "number"},
                    on_error="fallback:double_alt",
                )
            ],
            input_schema_ref=Flow.schema_ref_from(NumberInput),
        )

        result = compile_flow(flow, tools)

        # No output_mapping -> divergence is advisory, not blocking.
        assert result.success is True
        warning = next(
            w for w in result.warnings if w.issue_type == "fallback_output_shape_divergence"
        )
        assert warning.tool_name == "double_alt"
        assert warning.field_name == "value"

    def test_fallback_output_missing_mapped_key_is_error(self) -> None:
        tools = _make_tools()
        tools["double_alt"] = Tool(
            name="double_alt",
            description="Same input, but lacks the mapped output key.",
            input_schema=NumberInput,
            output_schema=FormattedOutput,  # lacks 'value'
            fn=lambda inp: {"result": str(inp.number)},
        )
        flow = Flow(
            name="fb_out_missing_mapped",
            description="Fallback misses a mapped output key.",
            steps=[
                FlowStep(
                    tool_name="double",
                    input_mapping={"number": "number"},
                    output_mapping={"doubled": "value"},  # needs output key 'value'
                    on_error="fallback:double_alt",
                )
            ],
            input_schema_ref=Flow.schema_ref_from(NumberInput),
        )

        result = compile_flow(flow, tools)

        # A mapped output key the fallback cannot produce is a deterministic
        # runtime OutputMappingError -> blocking error.
        error = next(
            e for e in result.errors if e.issue_type == "fallback_output_missing_mapped_key"
        )
        assert result.success is False
        assert error.tool_name == "double_alt"
        assert error.field_name == "value"

    def test_fallback_output_type_mismatch_warns(self) -> None:
        class StrValueOutput(BaseModel):
            value: str

        tools = _make_tools()
        tools["double_str"] = Tool(
            name="double_str",
            description="Same output key, different type.",
            input_schema=NumberInput,
            output_schema=StrValueOutput,  # value: str vs primary value: int
            fn=lambda inp: {"value": str(inp.number)},
        )
        flow = Flow(
            name="fb_out_type",
            description="Fallback output type diverges from the primary.",
            steps=[
                FlowStep(
                    tool_name="double",
                    input_mapping={"number": "number"},
                    on_error="fallback:double_str",
                )
            ],
            input_schema_ref=Flow.schema_ref_from(NumberInput),
        )

        result = compile_flow(flow, tools)

        assert result.success is True
        warning = next(
            w for w in result.warnings if w.issue_type == "fallback_output_type_mismatch"
        )
        assert warning.tool_name == "double_str"
        assert warning.field_name == "value"

    def test_mapped_fallback_output_type_mismatch_warns(self) -> None:
        # With an output_mapping, a fallback that *does* produce the mapped key
        # but types it differently is still only advisory (the mapping renames;
        # it does not coerce), so a warning — not an error — is expected.
        class StrValueOutput(BaseModel):
            value: str

        tools = _make_tools()
        tools["double_str"] = Tool(
            name="double_str",
            description="Mapped key present, different type.",
            input_schema=NumberInput,
            output_schema=StrValueOutput,  # value: str vs primary value: int
            fn=lambda inp: {"value": str(inp.number)},
        )
        flow = Flow(
            name="fb_out_mapped_type",
            description="Mapped fallback output type diverges.",
            steps=[
                FlowStep(
                    tool_name="double",
                    input_mapping={"number": "number"},
                    output_mapping={"doubled": "value"},
                    on_error="fallback:double_str",
                )
            ],
            input_schema_ref=Flow.schema_ref_from(NumberInput),
        )

        result = compile_flow(flow, tools)

        assert result.success is True
        assert not any(e.issue_type == "fallback_output_missing_mapped_key" for e in result.errors)
        warning = next(
            w for w in result.warnings if w.issue_type == "fallback_output_type_mismatch"
        )
        assert warning.field_name == "value"


class TestDAGFallbackCompatibility:
    """Fallback compile-time checks extended to the DAG path (issue #456)."""

    def test_compatible_dag_fallback_compiles(self) -> None:
        tools = _make_tools()
        dag = DAGFlow(
            name="dag_fb_ok",
            version="1.0.0",
            description="Compatible DAG fallback.",
            steps=[
                DAGFlowStep(
                    tool_name="double",
                    step_id="A",
                    depends_on=[],
                    input_mapping={"number": "number"},
                ),
                DAGFlowStep(
                    tool_name="add_ten",
                    step_id="B",
                    depends_on=["A"],
                    input_mapping={"value": "value"},
                    on_error="fallback:add_ten",
                ),
            ],
            input_schema_ref=DAGFlow.schema_ref_from(NumberInput),
        )

        result = compile_flow(dag, tools)

        assert result.success is True
        assert not any(e.issue_type.startswith("fallback_") for e in result.errors)

    def test_dag_missing_fallback_tool_is_error(self) -> None:
        dag = DAGFlow(
            name="dag_fb_missing",
            version="1.0.0",
            description="Missing DAG fallback tool.",
            steps=[
                DAGFlowStep(
                    tool_name="double",
                    step_id="A",
                    depends_on=[],
                    input_mapping={"number": "number"},
                    on_error="fallback:missing",
                ),
            ],
            input_schema_ref=DAGFlow.schema_ref_from(NumberInput),
        )

        result = compile_flow(dag, _make_tools())

        assert result.success is False
        assert any(
            e.issue_type == "missing_fallback_tool" and e.tool_name == "missing"
            for e in result.errors
        )

    def test_dag_fallback_type_mismatch_is_error(self) -> None:
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
        dag = DAGFlow(
            name="dag_fb_type",
            version="1.0.0",
            description="DAG fallback type mismatch.",
            steps=[
                DAGFlowStep(
                    tool_name="double",
                    step_id="A",
                    depends_on=[],
                    input_mapping={"number": "number"},
                    on_error="fallback:backup",
                ),
            ],
            input_schema_ref=DAGFlow.schema_ref_from(NumberInput),
        )

        result = compile_flow(dag, tools)

        error = next(e for e in result.errors if e.issue_type == "fallback_type_mismatch")
        assert result.success is False
        assert error.tool_name == "backup"
        assert error.field_name == "number"

    def test_dag_fallback_sees_ancestor_not_sibling_context(self) -> None:
        # Diamond A -> B, A -> C. C's fallback requires a key produced only by
        # its *sibling* B, which is not an ancestor of C, so the DAG-aware
        # context must report it missing (a linear list-order model would not).
        class AOut(BaseModel):
            a_val: int

        class BOut(BaseModel):
            b_val: int

        class AValInput(BaseModel):
            a_val: int

        class BValInput(BaseModel):
            b_val: int

        tools = {
            "produce_a": Tool(
                name="produce_a",
                description="Produces a_val.",
                input_schema=NumberInput,
                output_schema=AOut,
                fn=lambda inp: {"a_val": inp.number},
            ),
            "produce_b": Tool(
                name="produce_b",
                description="Produces b_val.",
                input_schema=AValInput,
                output_schema=BOut,
                fn=lambda inp: {"b_val": inp.a_val},
            ),
            "consume_a": Tool(
                name="consume_a",
                description="Consumes a_val.",
                input_schema=AValInput,
                output_schema=ValueOutput,
                fn=lambda inp: {"value": inp.a_val},
            ),
            "needs_b": Tool(
                name="needs_b",
                description="Fallback requiring b_val.",
                input_schema=BValInput,
                output_schema=ValueOutput,
                fn=lambda inp: {"value": inp.b_val},
            ),
        }
        dag = DAGFlow(
            name="dag_fb_ancestor",
            version="1.0.0",
            description="Fallback sees ancestor, not sibling, context.",
            steps=[
                DAGFlowStep(tool_name="produce_a", step_id="A", depends_on=[]),
                DAGFlowStep(tool_name="produce_b", step_id="B", depends_on=["A"]),
                DAGFlowStep(
                    tool_name="consume_a",
                    step_id="C",
                    depends_on=["A"],
                    on_error="fallback:needs_b",
                ),
            ],
            input_schema_ref=DAGFlow.schema_ref_from(NumberInput),
        )

        result = compile_flow(dag, tools)

        assert result.success is False
        assert any(
            e.issue_type == "fallback_missing_required_input" and e.field_name == "b_val"
            for e in result.errors
        )

    def test_dag_fallback_satisfied_by_ancestor_context(self) -> None:
        # Same diamond, but C's fallback requires a_val — produced by ancestor
        # A — so the DAG-aware context satisfies it and compilation is clean.
        class AOut(BaseModel):
            a_val: int

        class BOut(BaseModel):
            b_val: int

        class AValInput(BaseModel):
            a_val: int

        tools = {
            "produce_a": Tool(
                name="produce_a",
                description="Produces a_val.",
                input_schema=NumberInput,
                output_schema=AOut,
                fn=lambda inp: {"a_val": inp.number},
            ),
            "produce_b": Tool(
                name="produce_b",
                description="Produces b_val.",
                input_schema=AValInput,
                output_schema=BOut,
                fn=lambda inp: {"b_val": inp.a_val},
            ),
            "consume_a": Tool(
                name="consume_a",
                description="Consumes a_val.",
                input_schema=AValInput,
                output_schema=ValueOutput,
                fn=lambda inp: {"value": inp.a_val},
            ),
            "needs_a": Tool(
                name="needs_a",
                description="Fallback requiring a_val.",
                input_schema=AValInput,
                output_schema=ValueOutput,
                fn=lambda inp: {"value": inp.a_val},
            ),
        }
        dag = DAGFlow(
            name="dag_fb_ancestor_ok",
            version="1.0.0",
            description="Fallback satisfied by ancestor context.",
            steps=[
                DAGFlowStep(tool_name="produce_a", step_id="A", depends_on=[]),
                DAGFlowStep(tool_name="produce_b", step_id="B", depends_on=["A"]),
                DAGFlowStep(
                    tool_name="consume_a",
                    step_id="C",
                    depends_on=["A"],
                    on_error="fallback:needs_a",
                ),
            ],
            input_schema_ref=DAGFlow.schema_ref_from(NumberInput),
        )

        result = compile_flow(dag, tools)

        assert result.success is True
        assert not any(e.issue_type.startswith("fallback_") for e in result.errors)

    def test_dag_with_cycle_degrades_without_raising(self) -> None:
        # Topology errors (cycles) are reported by validate_dag_topology, not
        # the compiler; compile_flow must degrade to list order rather than
        # raise, so per-step wiring results are still returned.
        tools = _make_tools()
        dag = DAGFlow(
            name="dag_cycle",
            version="1.0.0",
            description="Cyclic DAG (A <-> B).",
            steps=[
                DAGFlowStep(
                    tool_name="double",
                    step_id="A",
                    depends_on=["B"],
                    input_mapping={"number": "number"},
                ),
                DAGFlowStep(
                    tool_name="add_ten",
                    step_id="B",
                    depends_on=["A"],
                    input_mapping={"value": "value"},
                ),
            ],
            input_schema_ref=DAGFlow.schema_ref_from(NumberInput),
        )

        result = compile_flow(dag, tools)

        assert isinstance(result, CompilationResult)

    def test_dag_unknown_dependency_is_skipped_gracefully(self) -> None:
        # A depends_on referencing a non-existent step id is a topology error
        # owned by validate_dag_topology; the compiler must not raise on it.
        tools = _make_tools()
        dag = DAGFlow(
            name="dag_unknown_dep",
            version="1.0.0",
            description="Step depends on an unknown id.",
            steps=[
                DAGFlowStep(
                    tool_name="double",
                    step_id="A",
                    depends_on=["ghost"],
                    input_mapping={"number": "number"},
                ),
            ],
            input_schema_ref=DAGFlow.schema_ref_from(NumberInput),
        )

        result = compile_flow(dag, tools)

        assert isinstance(result, CompilationResult)
