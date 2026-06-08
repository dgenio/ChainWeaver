"""Tests for :class:`chainweaver.mcp.FlowServer` (issue #72)."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from pydantic import BaseModel

from chainweaver import (
    Flow,
    FlowExecutor,
    FlowGovernance,
    FlowLifecycle,
    FlowRegistry,
    FlowStatus,
    FlowStep,
    SideEffectLevel,
    Tool,
    ToolSafetyContract,
)
from chainweaver.mcp import FlowServer


class _NumIn(BaseModel):
    n: int


class _NumOut(BaseModel):
    value: int


def _double(inp: _NumIn) -> dict[str, Any]:
    return {"value": inp.n * 2}


def _add_one(inp: _NumOut) -> dict[str, Any]:
    return {"value": inp.value + 1}


def _run(coro: Any) -> Any:
    """Run *coro* on a fresh asyncio event loop."""
    return asyncio.run(coro)


@pytest.fixture()
def executor_with_flow() -> FlowExecutor:
    registry = FlowRegistry()
    flow = Flow(
        name="number_flow",
        version="1.0.0",
        description="Double then increment.",
        steps=[
            FlowStep(tool_name="double", input_mapping={"n": "n"}),
            FlowStep(tool_name="add_one", input_mapping={"value": "value"}),
        ],
        input_schema_ref=Flow.schema_ref_from(_NumIn),
        output_schema_ref=Flow.schema_ref_from(_NumOut),
        governance=FlowGovernance(
            owner="platform",
            replaces_tools=("double", "add_one"),
            estimated_model_calls_removed=2,
            estimated_token_savings=500,
        ),
        safety=ToolSafetyContract(
            side_effects=SideEffectLevel.NONE,
            supports_dry_run=True,
        ),
    )
    registry.register_flow(flow)
    executor = FlowExecutor(registry=registry)
    executor.register_tool(
        Tool(
            name="double",
            description="",
            input_schema=_NumIn,
            output_schema=_NumOut,
            fn=_double,
        )
    )
    executor.register_tool(
        Tool(
            name="add_one",
            description="",
            input_schema=_NumOut,
            output_schema=_NumOut,
            fn=_add_one,
        )
    )
    return executor


class TestFlowServerRegistration:
    def test_registers_one_tool_per_flow(self, executor_with_flow: FlowExecutor) -> None:
        server = FlowServer(executor_with_flow, name="cw-test")
        assert server.registered_tool_names == ["number_flow"]

    def test_explicit_flow_names_subset(self, executor_with_flow: FlowExecutor) -> None:
        server = FlowServer(executor_with_flow, name="cw-test", flow_names=["number_flow"])
        assert server.registered_tool_names == ["number_flow"]

    def test_server_prefix_applied(self, executor_with_flow: FlowExecutor) -> None:
        server = FlowServer(executor_with_flow, name="cw-test", server_prefix="cw")
        assert server.registered_tool_names == ["cw__number_flow"]

    def test_fastmcp_property_returns_underlying_instance(
        self, executor_with_flow: FlowExecutor
    ) -> None:
        server = FlowServer(executor_with_flow, name="cw-test")
        assert server.fastmcp.name == "cw-test"

    def test_backed_by_standalone_fastmcp(self, executor_with_flow: FlowExecutor) -> None:
        # Migration guard (issue #243): the server runs on the standalone
        # ``fastmcp`` package, not the SDK-bundled ``mcp.server.fastmcp``.
        from fastmcp import FastMCP

        server = FlowServer(executor_with_flow, name="cw-test")
        assert isinstance(server.fastmcp, FastMCP)

    def test_implicit_exposure_skips_missing_safety(self) -> None:
        registry = FlowRegistry()
        registry.register_flow(
            Flow(
                name="unknown",
                description="Unknown safety.",
                steps=[FlowStep(tool_name="double")],
            )
        )
        executor = FlowExecutor(registry=registry)
        executor.register_tool(
            Tool(
                name="double",
                description="",
                input_schema=_NumIn,
                output_schema=_NumOut,
                fn=_double,
            )
        )
        assert FlowServer(executor).registered_tool_names == []

    def test_missing_safety_emits_warning(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        registry = FlowRegistry()
        registry.register_flow(
            Flow(
                name="unknown",
                description="Unknown safety.",
                steps=[FlowStep(tool_name="double")],
            )
        )
        executor = FlowExecutor(registry=registry)
        with caplog.at_level("WARNING", logger="chainweaver.mcp.server"):
            FlowServer(executor)
        assert "safety metadata is missing" in caplog.text

    def test_implicit_exposure_skips_draft_and_writing_flows(self) -> None:
        registry = FlowRegistry()
        registry.register_flow(
            Flow(
                name="draft",
                description="Draft.",
                steps=[FlowStep(tool_name="double")],
                governance=FlowGovernance(lifecycle=FlowLifecycle.DRAFT),
                safety=ToolSafetyContract(),
            )
        )
        registry.register_flow(
            Flow(
                name="writer",
                description="Writes.",
                steps=[FlowStep(tool_name="double")],
                safety=ToolSafetyContract(side_effects=SideEffectLevel.WRITE),
            )
        )
        executor = FlowExecutor(registry=registry)
        assert FlowServer(executor).registered_tool_names == []

    def test_filters_by_lifecycle_owner_and_approval(self) -> None:
        registry = FlowRegistry()
        registry.register_flow(
            Flow(
                name="reviewed",
                description="Reviewed.",
                steps=[FlowStep(tool_name="double")],
                governance=FlowGovernance(
                    lifecycle=FlowLifecycle.REVIEWED,
                    owner="platform",
                ),
                safety=ToolSafetyContract(),
            )
        )
        registry.register_flow(
            Flow(
                name="approval",
                description="Approval.",
                steps=[FlowStep(tool_name="double")],
                governance=FlowGovernance(owner="platform"),
                safety=ToolSafetyContract(
                    requires_approval=True,
                    approval_reason="Writes billing state.",
                ),
            )
        )
        executor = FlowExecutor(registry=registry)
        server = FlowServer(
            executor,
            allowed_lifecycles={FlowLifecycle.ACTIVE, FlowLifecycle.REVIEWED},
            owners={"platform"},
        )
        assert server.registered_tool_names == ["reviewed"]

    def test_derives_safety_from_explicit_tool_contracts(self) -> None:
        registry = FlowRegistry()
        registry.register_flow(
            Flow(
                name="derived",
                description="Derived.",
                steps=[FlowStep(tool_name="double")],
            )
        )
        executor = FlowExecutor(registry=registry)
        executor.register_tool(
            Tool(
                name="double",
                description="",
                input_schema=_NumIn,
                output_schema=_NumOut,
                fn=_double,
                safety=ToolSafetyContract(side_effects=SideEffectLevel.READ),
            )
        )
        assert FlowServer(executor).registered_tool_names == ["derived"]

    def test_nested_flow_with_undeclared_safety_is_not_exposed(self) -> None:
        registry = FlowRegistry()
        inner = Flow(
            name="inner",
            description="Uses a tool without declared safety.",
            steps=[FlowStep(tool_name="double")],
        )
        outer = Flow(
            name="outer",
            description="Wraps the inner flow as a tool.",
            steps=[FlowStep(tool_name="inner")],
        )
        registry.register_flow(inner)
        registry.register_flow(outer)
        executor = FlowExecutor(registry=registry)
        executor.register_tool(
            Tool(
                name="double",
                description="",
                input_schema=_NumIn,
                output_schema=_NumOut,
                fn=_double,
            )
        )
        executor.register_tool(Tool.from_flow(inner, executor))

        assert FlowServer(executor).registered_tool_names == []

    def test_explicit_names_override_default_filters(self) -> None:
        registry = FlowRegistry()
        registry.register_flow(
            Flow(
                name="writer",
                description="Writes.",
                steps=[FlowStep(tool_name="double")],
                governance=FlowGovernance(lifecycle=FlowLifecycle.REVIEWED),
                safety=ToolSafetyContract(side_effects=SideEffectLevel.WRITE),
            )
        )
        executor = FlowExecutor(registry=registry)
        server = FlowServer(executor, flow_names=["writer"])
        assert server.registered_tool_names == ["writer"]

    def test_duplicate_explicit_names_raise(self, executor_with_flow: FlowExecutor) -> None:
        with pytest.raises(ValueError, match="collision"):
            FlowServer(
                executor_with_flow,
                flow_names=["number_flow", "number_flow"],
            )


class TestFlowServerOverMCP:
    def test_client_sees_advertised_flow(self, executor_with_flow: FlowExecutor) -> None:
        flow_server = FlowServer(executor_with_flow, name="cw-test")

        async def go() -> list[str]:
            async with create_connected_server_and_client_session(
                flow_server.fastmcp._mcp_server
            ) as client:
                listing = await client.list_tools()
                return [t.name for t in listing.tools]

        names = _run(go())
        assert "number_flow" in names

    def test_client_invokes_flow_via_call_tool(self, executor_with_flow: FlowExecutor) -> None:
        flow_server = FlowServer(executor_with_flow, name="cw-test")

        async def go() -> Any:
            async with create_connected_server_and_client_session(
                flow_server.fastmcp._mcp_server
            ) as client:
                return await client.call_tool("number_flow", {"n": 5})

        result = _run(go())
        assert not result.isError
        assert result.structuredContent is not None
        # (5 * 2) + 1 == 11
        assert result.structuredContent.get("value") == 11

    def test_implicit_exposure_uses_latest_active_version(
        self,
        executor_with_flow: FlowExecutor,
    ) -> None:
        executor_with_flow.registry.register_flow(
            Flow(
                name="number_flow",
                version="2.0.0",
                description="Disabled replacement.",
                steps=[FlowStep(tool_name="double", input_mapping={"n": "n"})],
                status=FlowStatus.DISABLED,
                input_schema_ref=Flow.schema_ref_from(_NumIn),
                output_schema_ref=Flow.schema_ref_from(_NumOut),
                safety=ToolSafetyContract(side_effects=SideEffectLevel.WRITE),
            )
        )
        flow_server = FlowServer(executor_with_flow, name="cw-test")

        async def go() -> tuple[Any, Any]:
            async with create_connected_server_and_client_session(
                flow_server.fastmcp._mcp_server
            ) as client:
                listing = await client.list_tools()
                advertised = next(t for t in listing.tools if t.name == "number_flow")
                result = await client.call_tool("number_flow", {"n": 5})
                return advertised, result

        advertised, result = _run(go())
        assert advertised.meta["chainweaver"]["flow_version"] == "1.0.0"
        assert result.isError is False
        assert result.structuredContent == {"value": 11}

    def test_flow_failure_surfaces_as_mcp_error(self) -> None:
        registry = FlowRegistry()
        flow = Flow(
            name="boom",
            version="1.0.0",
            description="",
            steps=[FlowStep(tool_name="boom", input_mapping={"n": "n"})],
            input_schema_ref=Flow.schema_ref_from(_NumIn),
            safety=ToolSafetyContract(),
        )
        registry.register_flow(flow)
        executor = FlowExecutor(registry=registry)

        def _boom(inp: _NumIn) -> dict[str, Any]:
            raise RuntimeError("boom")

        executor.register_tool(
            Tool(
                name="boom",
                description="",
                input_schema=_NumIn,
                output_schema=_NumOut,
                fn=_boom,
            )
        )
        flow_server = FlowServer(executor, name="cw-test")

        async def go() -> Any:
            async with create_connected_server_and_client_session(
                flow_server.fastmcp._mcp_server
            ) as client:
                return await client.call_tool("boom", {"n": 1})

        result = _run(go())
        # FastMCP wraps the raised FlowExecutionError as isError=True.
        assert result.isError is True

    def test_advertised_input_schema_matches_flow(self, executor_with_flow: FlowExecutor) -> None:
        flow_server = FlowServer(executor_with_flow, name="cw-test")

        async def go() -> Any:
            async with create_connected_server_and_client_session(
                flow_server.fastmcp._mcp_server
            ) as client:
                listing = await client.list_tools()
                return next(t for t in listing.tools if t.name == "number_flow")

        flow_tool = _run(go())
        props = flow_tool.inputSchema.get("properties", {})
        assert "n" in props

    def test_advertises_safety_and_savings_metadata(
        self,
        executor_with_flow: FlowExecutor,
    ) -> None:
        flow_server = FlowServer(executor_with_flow, name="cw-test")

        async def go() -> Any:
            async with create_connected_server_and_client_session(
                flow_server.fastmcp._mcp_server
            ) as client:
                listing = await client.list_tools()
                return next(t for t in listing.tools if t.name == "number_flow")

        flow_tool = _run(go())
        assert flow_tool.annotations is not None
        assert flow_tool.annotations.readOnlyHint is True
        assert flow_tool.annotations.destructiveHint is False
        assert flow_tool.annotations.idempotentHint is True
        assert flow_tool.meta is not None
        metadata = flow_tool.meta["chainweaver"]
        assert metadata["lifecycle"] == "active"
        assert metadata["replaces_tools"] == ["double", "add_one"]
        assert metadata["estimated_token_savings"] == 500
        assert "requires_approval=false" in flow_tool.description
