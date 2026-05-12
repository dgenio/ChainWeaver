"""Tests for FlowStatus enum, status filtering, and executor status guard."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from chainweaver.exceptions import FlowStatusError
from chainweaver.executor import FlowExecutor
from chainweaver.flow import Flow, FlowStatus, FlowStep
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class NumIn(BaseModel):
    number: int


class NumOut(BaseModel):
    value: int


def _double_fn(inp: NumIn) -> dict[str, Any]:
    return {"value": inp.number * 2}


def _make_tool() -> Tool:
    return Tool(
        name="double",
        description="Doubles a number.",
        input_schema=NumIn,
        output_schema=NumOut,
        fn=_double_fn,
    )


def _make_flow(name: str = "test_flow", status: FlowStatus = FlowStatus.ACTIVE) -> Flow:
    return Flow(
        name=name,
        version="0.1.0",
        description="A test flow.",
        steps=[FlowStep(tool_name="double", input_mapping={"number": "number"})],
        status=status,
    )


# ---------------------------------------------------------------------------
# FlowStatus enum tests
# ---------------------------------------------------------------------------


class TestFlowStatusEnum:
    def test_active_value(self) -> None:
        assert FlowStatus.ACTIVE.value == "active"

    def test_needs_review_value(self) -> None:
        assert FlowStatus.NEEDS_REVIEW.value == "needs_review"

    def test_disabled_value(self) -> None:
        assert FlowStatus.DISABLED.value == "disabled"

    def test_default_status_is_active(self) -> None:
        flow = Flow(
            name="test", version="0.1.0", description="Test.", steps=[FlowStep(tool_name="x")]
        )
        assert flow.status == FlowStatus.ACTIVE


# ---------------------------------------------------------------------------
# Registry status filtering tests
# ---------------------------------------------------------------------------


class TestRegistryStatusFiltering:
    def test_list_flows_returns_all_by_default(self) -> None:
        registry = FlowRegistry()
        registry.register_flow(_make_flow("a", FlowStatus.ACTIVE))
        registry.register_flow(_make_flow("b", FlowStatus.NEEDS_REVIEW))
        registry.register_flow(_make_flow("c", FlowStatus.DISABLED))
        assert len(registry.list_flows()) == 3

    def test_list_flows_filter_by_status(self) -> None:
        registry = FlowRegistry()
        registry.register_flow(_make_flow("a", FlowStatus.ACTIVE))
        registry.register_flow(_make_flow("b", FlowStatus.NEEDS_REVIEW))
        registry.register_flow(_make_flow("c", FlowStatus.DISABLED))
        active = registry.list_flows(status=FlowStatus.ACTIVE)
        assert len(active) == 1
        assert active[0].name == "a"

    def test_list_flows_exclude_status(self) -> None:
        registry = FlowRegistry()
        registry.register_flow(_make_flow("a", FlowStatus.ACTIVE))
        registry.register_flow(_make_flow("b", FlowStatus.DISABLED))
        result = registry.list_flows(exclude_status={FlowStatus.DISABLED})
        assert len(result) == 1
        assert result[0].name == "a"

    def test_get_active_flows(self) -> None:
        registry = FlowRegistry()
        registry.register_flow(_make_flow("a", FlowStatus.ACTIVE))
        registry.register_flow(_make_flow("b", FlowStatus.DISABLED))
        active = registry.get_active_flows()
        assert len(active) == 1
        assert active[0].name == "a"

    def test_set_flow_status(self) -> None:
        registry = FlowRegistry()
        registry.register_flow(_make_flow("a", FlowStatus.ACTIVE))
        registry.set_flow_status("a", FlowStatus.DISABLED)
        flow = registry.get_flow("a")
        assert flow.status == FlowStatus.DISABLED


# ---------------------------------------------------------------------------
# Executor status guard tests
# ---------------------------------------------------------------------------


class TestExecutorStatusGuard:
    def test_active_flow_executes(self) -> None:
        registry = FlowRegistry()
        registry.register_flow(_make_flow("f", FlowStatus.ACTIVE))
        ex = FlowExecutor(registry=registry)
        ex.register_tool(_make_tool())
        result = ex.execute_flow("f", {"number": 5})
        assert result.success is True

    def test_disabled_flow_raises(self) -> None:
        registry = FlowRegistry()
        registry.register_flow(_make_flow("f", FlowStatus.DISABLED))
        ex = FlowExecutor(registry=registry)
        ex.register_tool(_make_tool())
        with pytest.raises(FlowStatusError) as exc_info:
            ex.execute_flow("f", {"number": 5})
        assert exc_info.value.flow_name == "f"
        assert exc_info.value.status == "disabled"

    def test_needs_review_flow_raises(self) -> None:
        registry = FlowRegistry()
        registry.register_flow(_make_flow("f", FlowStatus.NEEDS_REVIEW))
        ex = FlowExecutor(registry=registry)
        ex.register_tool(_make_tool())
        with pytest.raises(FlowStatusError):
            ex.execute_flow("f", {"number": 5})

    def test_force_bypasses_status_check(self) -> None:
        registry = FlowRegistry()
        registry.register_flow(_make_flow("f", FlowStatus.DISABLED))
        ex = FlowExecutor(registry=registry)
        ex.register_tool(_make_tool())
        result = ex.execute_flow("f", {"number": 5}, force=True)
        assert result.success is True

    def test_serialization_roundtrip_preserves_status(self) -> None:
        flow = _make_flow("f", FlowStatus.NEEDS_REVIEW)
        data = flow.model_dump()
        restored = Flow.model_validate(data)
        assert restored.status == FlowStatus.NEEDS_REVIEW
