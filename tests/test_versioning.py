"""Tests for flow and tool schema versioning."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from chainweaver.exceptions import (
    FlowNotFoundError,
    FlowStatusError,
    InvalidFlowVersionError,
)
from chainweaver.executor import FlowExecutor
from chainweaver.flow import Flow, FlowStatus, FlowStep
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class DummyInput(BaseModel):
    x: int


class DummyOutput(BaseModel):
    y: int


def _dummy_fn(inp: DummyInput) -> dict[str, Any]:
    return {"y": inp.x}


def _make_flow(name: str = "versioned", version: str = "0.0.0") -> Flow:
    return Flow(
        name=name,
        version=version,
        description=f"Flow {name} v{version}.",
        steps=[FlowStep(tool_name="dummy")],
    )


# ---------------------------------------------------------------------------
# Flow.version tests
# ---------------------------------------------------------------------------


class TestFlowVersion:
    def test_default_version(self) -> None:
        flow = Flow(name="f", description="D.", steps=[FlowStep(tool_name="x")])
        assert flow.version == "0.1.0"

    def test_custom_version(self) -> None:
        flow = _make_flow(version="1.2.3")
        assert flow.version == "1.2.3"


# ---------------------------------------------------------------------------
# Tool.schema_version tests
# ---------------------------------------------------------------------------


class TestToolSchemaVersion:
    def test_default_schema_version(self) -> None:
        tool = Tool(
            name="t",
            description="T.",
            input_schema=DummyInput,
            output_schema=DummyOutput,
            fn=_dummy_fn,
        )
        assert tool.schema_version == "0.0.0"

    def test_custom_schema_version(self) -> None:
        tool = Tool(
            name="t",
            description="T.",
            input_schema=DummyInput,
            output_schema=DummyOutput,
            fn=_dummy_fn,
            schema_version="2.0.0",
        )
        assert tool.schema_version == "2.0.0"

    def test_schema_version_participates_in_schema_hash(self) -> None:
        tool_v1 = Tool(
            name="t",
            description="T.",
            input_schema=DummyInput,
            output_schema=DummyOutput,
            fn=_dummy_fn,
            schema_version="1.0.0",
        )
        tool_v2 = Tool(
            name="t",
            description="T.",
            input_schema=DummyInput,
            output_schema=DummyOutput,
            fn=_dummy_fn,
            schema_version="2.0.0",
        )
        assert tool_v1.schema_hash != tool_v2.schema_hash


# ---------------------------------------------------------------------------
# Multi-version registry tests
# ---------------------------------------------------------------------------


class TestMultiVersionRegistry:
    def test_register_multiple_versions(self) -> None:
        registry = FlowRegistry()
        registry.register_flow(_make_flow("f", "1.0.0"))
        registry.register_flow(_make_flow("f", "2.0.0"))
        assert len(registry) == 2

    def test_get_flow_returns_latest(self) -> None:
        registry = FlowRegistry()
        registry.register_flow(_make_flow("f", "1.0.0"))
        registry.register_flow(_make_flow("f", "2.0.0"))
        flow = registry.get_flow("f")
        assert flow.version == "2.0.0"

    def test_get_flow_specific_version(self) -> None:
        registry = FlowRegistry()
        registry.register_flow(_make_flow("f", "1.0.0"))
        registry.register_flow(_make_flow("f", "2.0.0"))
        flow = registry.get_flow("f", version="1.0.0")
        assert flow.version == "1.0.0"

    def test_get_flow_missing_version_raises(self) -> None:
        registry = FlowRegistry()
        registry.register_flow(_make_flow("f", "1.0.0"))
        with pytest.raises(FlowNotFoundError):
            registry.get_flow("f", version="9.9.9")

    def test_list_flow_versions_sorted(self) -> None:
        registry = FlowRegistry()
        registry.register_flow(_make_flow("f", "2.0.0"))
        registry.register_flow(_make_flow("f", "1.0.0"))
        registry.register_flow(_make_flow("f", "1.5.0"))
        versions = registry.list_flow_versions("f")
        assert versions == ["1.0.0", "1.5.0", "2.0.0"]

    def test_list_flow_versions_missing_name_raises(self) -> None:
        registry = FlowRegistry()
        with pytest.raises(FlowNotFoundError):
            registry.list_flow_versions("nonexistent")

    def test_latest_pointer_updates_on_higher_version(self) -> None:
        registry = FlowRegistry()
        registry.register_flow(_make_flow("f", "1.0.0"))
        assert registry.get_flow("f").version == "1.0.0"
        registry.register_flow(_make_flow("f", "3.0.0"))
        assert registry.get_flow("f").version == "3.0.0"
        # Registering an older version does not change latest.
        registry.register_flow(_make_flow("f", "0.5.0"))
        assert registry.get_flow("f").version == "3.0.0"

    def test_register_with_explicit_version(self) -> None:
        registry = FlowRegistry()
        flow = Flow(name="f", version="0.1.0", description="D.", steps=[FlowStep(tool_name="x")])
        registry.register_flow(flow)
        assert registry.get_flow("f").version == "0.1.0"


class TestFlowNotFoundErrorIncludesVersion:
    def test_missing_unversioned_lookup_omits_version(self) -> None:
        registry = FlowRegistry()
        with pytest.raises(FlowNotFoundError) as exc_info:
            registry.get_flow("ghost")
        err = exc_info.value
        assert err.flow_name == "ghost"
        assert err.version is None
        assert "version" not in str(err)

    def test_missing_specific_version_surfaces_version(self) -> None:
        registry = FlowRegistry()
        registry.register_flow(_make_flow("f", "1.0.0"))
        with pytest.raises(FlowNotFoundError) as exc_info:
            registry.get_flow("f", version="9.9.9")
        err = exc_info.value
        assert err.flow_name == "f"
        assert err.version == "9.9.9"
        assert "9.9.9" in str(err)


class TestInvalidFlowVersion:
    def test_register_invalid_version_raises_chainweaver_error(self) -> None:
        bad = Flow(
            name="bad_ver",
            version="not-a-version",
            description="D.",
            steps=[FlowStep(tool_name="x")],
        )
        registry = FlowRegistry()
        with pytest.raises(InvalidFlowVersionError) as exc_info:
            registry.register_flow(bad)
        assert exc_info.value.flow_name == "bad_ver"
        assert exc_info.value.version == "not-a-version"

    def test_register_invalid_version_does_not_store_flow(self) -> None:
        bad = Flow(
            name="bad_ver",
            version="not-a-version",
            description="D.",
            steps=[FlowStep(tool_name="x")],
        )
        registry = FlowRegistry()
        with pytest.raises(InvalidFlowVersionError):
            registry.register_flow(bad)
        # Subsequent lookup should not find the flow.
        with pytest.raises(FlowNotFoundError):
            registry.get_flow("bad_ver")


# ---------------------------------------------------------------------------
# Version-targeted execution (issue #201)
# ---------------------------------------------------------------------------


def _tenx_fn(inp: DummyInput) -> dict[str, Any]:
    return {"y": inp.x * 10}


def _versioned_executor() -> FlowExecutor:
    """Registry with two versions of ``vflow`` that differ observably.

    ``1.0.0`` echoes ``x`` into ``y``; ``2.0.0`` multiplies it by ten.  The
    distinct outputs let a test prove *which* version actually executed,
    not merely that some version ran.
    """
    registry = FlowRegistry()
    registry.register_flow(
        Flow(
            name="vflow",
            version="1.0.0",
            description="Echo x into y.",
            steps=[FlowStep(tool_name="echo", input_mapping={"x": "x"})],
        )
    )
    registry.register_flow(
        Flow(
            name="vflow",
            version="2.0.0",
            description="Multiply x by ten into y.",
            steps=[FlowStep(tool_name="tenx", input_mapping={"x": "x"})],
        )
    )
    executor = FlowExecutor(registry=registry)
    executor.register_tool(
        Tool(
            name="echo",
            description="Echo x into y.",
            input_schema=DummyInput,
            output_schema=DummyOutput,
            fn=_dummy_fn,
        )
    )
    executor.register_tool(
        Tool(
            name="tenx",
            description="Multiply x by ten into y.",
            input_schema=DummyInput,
            output_schema=DummyOutput,
            fn=_tenx_fn,
        )
    )
    return executor


class TestVersionTargetedExecution:
    def test_default_executes_latest_version(self) -> None:
        executor = _versioned_executor()
        result = executor.execute_flow("vflow", {"x": 5})
        assert result.success is True
        assert result.flow_version == "2.0.0"
        assert result.final_output is not None
        assert result.final_output["y"] == 50

    def test_explicit_older_version_executes_that_version(self) -> None:
        executor = _versioned_executor()
        result = executor.execute_flow("vflow", {"x": 5}, version="1.0.0")
        assert result.success is True
        assert result.flow_version == "1.0.0"
        assert result.final_output is not None
        assert result.final_output["y"] == 5

    def test_explicit_latest_version_matches_default(self) -> None:
        executor = _versioned_executor()
        result = executor.execute_flow("vflow", {"x": 3}, version="2.0.0")
        assert result.flow_version == "2.0.0"
        assert result.final_output is not None
        assert result.final_output["y"] == 30

    def test_missing_version_raises_flow_not_found(self) -> None:
        executor = _versioned_executor()
        with pytest.raises(FlowNotFoundError) as exc_info:
            executor.execute_flow("vflow", {"x": 1}, version="9.9.9")
        assert exc_info.value.version == "9.9.9"

    def test_status_guard_applies_to_targeted_version(self) -> None:
        executor = _versioned_executor()
        executor._registry.set_flow_status("vflow", FlowStatus.NEEDS_REVIEW, version="1.0.0")
        # The targeted version's status is what gates execution.
        with pytest.raises(FlowStatusError):
            executor.execute_flow("vflow", {"x": 1}, version="1.0.0")
        # Latest (2.0.0) is still ACTIVE and unaffected.
        assert executor.execute_flow("vflow", {"x": 1}).success is True

    def test_force_bypasses_status_guard_for_targeted_version(self) -> None:
        executor = _versioned_executor()
        executor._registry.set_flow_status("vflow", FlowStatus.NEEDS_REVIEW, version="1.0.0")
        result = executor.execute_flow("vflow", {"x": 4}, version="1.0.0", force=True)
        assert result.success is True
        assert result.flow_version == "1.0.0"
        assert result.final_output is not None
        assert result.final_output["y"] == 4

    @pytest.mark.asyncio
    async def test_async_explicit_version(self) -> None:
        executor = _versioned_executor()
        result = await executor.execute_flow_async("vflow", {"x": 6}, version="1.0.0")
        assert result.flow_version == "1.0.0"
        assert result.final_output is not None
        assert result.final_output["y"] == 6
