"""Tests for schema fingerprinting and compatibility utilities."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from chainweaver.compat import check_flow_compatibility, schema_fingerprint
from chainweaver.flow import Flow, FlowStep
from chainweaver.tools import Tool

# ---------------------------------------------------------------------------
# Schemas for testing
# ---------------------------------------------------------------------------


class SimpleInput(BaseModel):
    value: int


class SimpleOutput(BaseModel):
    result: int


class ExtendedInput(BaseModel):
    value: int
    extra: str


class RenamedInput(BaseModel):
    amount: int


# ---------------------------------------------------------------------------
# schema_fingerprint tests
# ---------------------------------------------------------------------------


class TestSchemaFingerprint:
    def test_same_model_same_hash(self) -> None:
        h1 = schema_fingerprint(SimpleInput)
        h2 = schema_fingerprint(SimpleInput)
        assert h1 == h2

    def test_hash_is_16_chars(self) -> None:
        h = schema_fingerprint(SimpleInput)
        assert len(h) == 16
        assert all(c in "0123456789abcdef" for c in h)

    def test_different_field_produces_different_hash(self) -> None:
        h1 = schema_fingerprint(SimpleInput)
        h2 = schema_fingerprint(ExtendedInput)
        assert h1 != h2

    def test_renamed_field_produces_different_hash(self) -> None:
        h1 = schema_fingerprint(SimpleInput)
        h2 = schema_fingerprint(RenamedInput)
        assert h1 != h2

    def test_different_type_same_name_produces_different_hash(self) -> None:
        class ValueStr(BaseModel):
            value: str

        h1 = schema_fingerprint(SimpleInput)
        h2 = schema_fingerprint(ValueStr)
        assert h1 != h2

    def test_identical_structure_different_name_produces_different_hash(self) -> None:
        """Different class names produce different JSON schema titles, hence different hashes."""

        class CopyOfSimpleInput(BaseModel):
            value: int

        h1 = schema_fingerprint(SimpleInput)
        h2 = schema_fingerprint(CopyOfSimpleInput)
        assert h1 != h2


# ---------------------------------------------------------------------------
# Tool.schema_hash tests
# ---------------------------------------------------------------------------


def _noop(inp: Any) -> dict[str, Any]:
    return {"result": 0}


class TestToolSchemaHash:
    def test_schema_hash_property_exists(self) -> None:
        tool = Tool(
            name="test",
            description="Test tool.",
            input_schema=SimpleInput,
            output_schema=SimpleOutput,
            fn=_noop,
        )
        assert isinstance(tool.schema_hash, str)
        assert len(tool.schema_hash) == 16

    def test_same_tool_same_hash(self) -> None:
        tool = Tool(
            name="test",
            description="Test tool.",
            input_schema=SimpleInput,
            output_schema=SimpleOutput,
            fn=_noop,
        )
        assert tool.schema_hash == tool.schema_hash

    def test_different_input_schema_different_hash(self) -> None:
        tool1 = Tool(
            name="t1",
            description="T1.",
            input_schema=SimpleInput,
            output_schema=SimpleOutput,
            fn=_noop,
        )
        tool2 = Tool(
            name="t2",
            description="T2.",
            input_schema=ExtendedInput,
            output_schema=SimpleOutput,
            fn=_noop,
        )
        assert tool1.schema_hash != tool2.schema_hash

    def test_input_and_output_hash_properties(self) -> None:
        tool = Tool(
            name="test",
            description="Test tool.",
            input_schema=SimpleInput,
            output_schema=SimpleOutput,
            fn=_noop,
        )
        assert tool.input_schema_hash == schema_fingerprint(SimpleInput)
        assert tool.output_schema_hash == schema_fingerprint(SimpleOutput)


# ---------------------------------------------------------------------------
# check_flow_compatibility tests
# ---------------------------------------------------------------------------


class TestCheckFlowCompatibility:
    def test_compatible_flow_returns_empty(self) -> None:
        tool = Tool(
            name="proc",
            description="Process.",
            input_schema=SimpleInput,
            output_schema=SimpleOutput,
            fn=_noop,
        )
        flow = Flow(
            name="f",
            description="Flow.",
            steps=[FlowStep(tool_name="proc")],
            tool_schema_hashes={"proc": tool.schema_hash},
        )
        issues = check_flow_compatibility(flow, {"proc": tool})
        assert issues == []

    def test_missing_tool_detected(self) -> None:
        flow = Flow(
            name="f",
            description="Flow.",
            steps=[FlowStep(tool_name="missing")],
        )
        issues = check_flow_compatibility(flow, {})
        assert len(issues) == 1
        assert issues[0].issue_type == "missing_tool"
        assert issues[0].tool_name == "missing"

    def test_schema_mismatch_detected(self) -> None:
        tool = Tool(
            name="proc",
            description="Process.",
            input_schema=SimpleInput,
            output_schema=SimpleOutput,
            fn=_noop,
        )
        flow = Flow(
            name="f",
            description="Flow.",
            steps=[FlowStep(tool_name="proc")],
            tool_schema_hashes={"proc": "0000000000000000"},
        )
        issues = check_flow_compatibility(flow, {"proc": tool})
        assert len(issues) == 1
        assert issues[0].issue_type == "schema_mismatch"

    def test_no_snapshot_skips_hash_check(self) -> None:
        tool = Tool(
            name="proc",
            description="Process.",
            input_schema=SimpleInput,
            output_schema=SimpleOutput,
            fn=_noop,
        )
        flow = Flow(
            name="f",
            description="Flow.",
            steps=[FlowStep(tool_name="proc")],
            tool_schema_hashes=None,
        )
        issues = check_flow_compatibility(flow, {"proc": tool})
        assert issues == []
