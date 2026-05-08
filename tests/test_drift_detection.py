"""Tests for schema drift detection on tool re-registration."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from chainweaver.executor import FlowExecutor
from chainweaver.flow import DriftInfo, Flow, FlowStatus, FlowStep
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool

# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class InputA(BaseModel):
    value: int


class OutputA(BaseModel):
    result: int


class InputB(BaseModel):
    value: int
    extra: str


class OutputB(BaseModel):
    result: int
    detail: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fn_a(inp: InputA) -> dict[str, Any]:
    return {"result": inp.value}


def _fn_b(inp: InputB) -> dict[str, Any]:
    return {"result": inp.value, "detail": inp.extra}


def _make_tool_v1() -> Tool:
    return Tool(
        name="proc",
        description="Processor v1.",
        input_schema=InputA,
        output_schema=OutputA,
        fn=_fn_a,
    )


def _make_tool_v2() -> Tool:
    return Tool(
        name="proc",
        description="Processor v2.",
        input_schema=InputB,
        output_schema=OutputB,
        fn=_fn_b,
    )


def _make_flow_with_hashes(tool: Tool) -> Flow:
    return Flow(
        name="my_flow",
        description="A flow using proc.",
        steps=[FlowStep(tool_name="proc", input_mapping={"value": "value"})],
        tool_schema_hashes={"proc": tool.schema_hash},
    )


# ---------------------------------------------------------------------------
# Drift detection tests
# ---------------------------------------------------------------------------


class TestNoDrift:
    def test_same_schema_no_status_change(self) -> None:
        tool = _make_tool_v1()
        registry = FlowRegistry()
        registry.register_flow(_make_flow_with_hashes(tool))
        ex = FlowExecutor(registry=registry)
        ex.register_tool(tool)
        # Re-register same tool — no drift.
        ex.register_tool(tool)
        flow = registry.get_flow("my_flow")
        assert flow.status == FlowStatus.ACTIVE

    def test_no_snapshot_no_false_positive(self) -> None:
        registry = FlowRegistry()
        flow = Flow(
            name="no_hashes",
            description="No hashes stored.",
            steps=[FlowStep(tool_name="proc")],
            tool_schema_hashes=None,
        )
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(_make_tool_v1())
        ex.register_tool(_make_tool_v2())
        assert registry.get_flow("no_hashes").status == FlowStatus.ACTIVE


class TestDriftDetected:
    def test_changed_schema_marks_flow_needs_review(self) -> None:
        tool_v1 = _make_tool_v1()
        registry = FlowRegistry()
        registry.register_flow(_make_flow_with_hashes(tool_v1))
        ex = FlowExecutor(registry=registry)
        ex.register_tool(tool_v1)
        # Re-register with changed schema.
        tool_v2 = _make_tool_v2()
        ex.register_tool(tool_v2)
        flow = registry.get_flow("my_flow")
        assert flow.status == FlowStatus.NEEDS_REVIEW

    def test_unaffected_flow_remains_active(self) -> None:
        tool_v1 = _make_tool_v1()
        other_tool = Tool(
            name="other",
            description="Other tool.",
            input_schema=InputA,
            output_schema=OutputA,
            fn=_fn_a,
        )
        registry = FlowRegistry()
        # Flow using "other" tool, not "proc".
        flow = Flow(
            name="other_flow",
            description="Uses other.",
            steps=[FlowStep(tool_name="other")],
            tool_schema_hashes={"other": other_tool.schema_hash},
        )
        registry.register_flow(flow)
        registry.register_flow(_make_flow_with_hashes(tool_v1))
        ex = FlowExecutor(registry=registry)
        ex.register_tool(tool_v1)
        ex.register_tool(other_tool)
        # Drift proc — only my_flow should be affected.
        ex.register_tool(_make_tool_v2())
        assert registry.get_flow("other_flow").status == FlowStatus.ACTIVE
        assert registry.get_flow("my_flow").status == FlowStatus.NEEDS_REVIEW


class TestDriftReport:
    def test_drift_report_empty_when_no_drift(self) -> None:
        tool = _make_tool_v1()
        registry = FlowRegistry()
        registry.register_flow(_make_flow_with_hashes(tool))
        ex = FlowExecutor(registry=registry)
        ex.register_tool(tool)
        assert ex.get_drift_report() == []

    def test_drift_report_contains_mismatch(self) -> None:
        tool_v1 = _make_tool_v1()
        registry = FlowRegistry()
        registry.register_flow(_make_flow_with_hashes(tool_v1))
        ex = FlowExecutor(registry=registry)
        ex.register_tool(_make_tool_v2())
        report = ex.get_drift_report()
        assert len(report) == 1
        assert isinstance(report[0], DriftInfo)
        assert report[0].flow_name == "my_flow"
        assert report[0].tool_name == "proc"
        assert report[0].expected_hash == tool_v1.schema_hash
        assert report[0].actual_hash == _make_tool_v2().schema_hash


class TestAcceptDrift:
    def test_accept_drift_updates_hashes_and_status(self) -> None:
        tool_v1 = _make_tool_v1()
        registry = FlowRegistry()
        registry.register_flow(_make_flow_with_hashes(tool_v1))
        ex = FlowExecutor(registry=registry)
        ex.register_tool(tool_v1)
        # Trigger drift.
        tool_v2 = _make_tool_v2()
        ex.register_tool(tool_v2)
        assert registry.get_flow("my_flow").status == FlowStatus.NEEDS_REVIEW
        # Accept drift.
        ex.accept_drift("my_flow")
        flow = registry.get_flow("my_flow")
        assert flow.status == FlowStatus.ACTIVE
        assert flow.tool_schema_hashes == {"proc": tool_v2.schema_hash}

    def test_accept_drift_clears_drift_report(self) -> None:
        tool_v1 = _make_tool_v1()
        registry = FlowRegistry()
        registry.register_flow(_make_flow_with_hashes(tool_v1))
        ex = FlowExecutor(registry=registry)
        ex.register_tool(tool_v1)
        ex.register_tool(_make_tool_v2())
        assert len(ex.get_drift_report()) == 1
        ex.accept_drift("my_flow")
        assert ex.get_drift_report() == []
