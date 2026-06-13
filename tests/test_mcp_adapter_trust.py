"""Tests for the MCP adapter trust-boundary hardening (issues #358, #359, #371).

Covers three adjacent concerns that all live on the MCP import boundary
(``chainweaver/mcp/adapter.py``):

* **#371** — mapping server-declared ``ToolAnnotations`` onto a conservative
  :class:`~chainweaver.contracts.ToolSafetyContract`.
* **#359** — the :class:`~chainweaver.mcp.MetadataPolicy` trust controls for
  server-provided tool names and descriptions.
* **#358** — raw-schema fingerprint pinning and drift detection.

The integration tests drive an in-memory FastMCP server using the same
``create_connected_server_and_client_session`` helper as ``test_mcp_adapter.py``.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import pytest
from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session
from mcp.types import ToolAnnotations

from chainweaver.contracts import DeterminismLevel, SideEffectLevel
from chainweaver.exceptions import MCPMetadataError, MCPSchemaDriftError
from chainweaver.mcp import MCPToolAdapter, MetadataPolicy, build_pin_file, load_pins
from chainweaver.mcp.adapter import _safety_from_annotations


def _run(coro: Any) -> Any:
    """Run *coro* on a fresh asyncio event loop and return its result."""
    return asyncio.run(coro)


def _build_demo_server() -> FastMCP:
    server = FastMCP(name="demo")

    @server.tool(name="echo", description="Echoes the supplied text.")
    def echo(text: str) -> dict:  # type: ignore[type-arg]
        return {"echoed": text}

    @server.tool(name="add", description="Adds two integers.")
    def add(a: int, b: int) -> int:
        return a + b

    return server


# ---------------------------------------------------------------------------
# #371 — ToolAnnotations → ToolSafetyContract mapping
# ---------------------------------------------------------------------------


class TestAdapterValidation:
    def test_invalid_annotation_trust_rejected(self) -> None:
        with pytest.raises(ValueError):
            MCPToolAdapter(None, annotation_trust="bogus")  # type: ignore[arg-type]

    def test_invalid_on_drift_rejected(self) -> None:
        # A typo must fail loudly, not silently fall through to "accept".
        with pytest.raises(ValueError):
            MCPToolAdapter(None, on_drift="erorr")  # type: ignore[arg-type]


class TestAnnotationMapping:
    def test_ignore_always_none(self) -> None:
        ann = ToolAnnotations(readOnlyHint=True)
        assert _safety_from_annotations(ann, "ignore") is None
        assert _safety_from_annotations(None, "ignore") is None

    def test_trust_unannotated_is_none(self) -> None:
        assert _safety_from_annotations(None, "trust") is None

    def test_cap_unannotated_is_external(self) -> None:
        contract = _safety_from_annotations(None, "cap")
        assert contract is not None
        assert contract.side_effects is SideEffectLevel.EXTERNAL
        assert contract.read_only is False
        assert contract.determinism_level is DeterminismLevel.NONE

    def test_read_only_maps_to_read_not_none(self) -> None:
        # A declared read-only remote tool still observed the world: READ, not NONE.
        for trust in ("trust", "cap"):
            contract = _safety_from_annotations(ToolAnnotations(readOnlyHint=True), trust)
            assert contract is not None
            assert contract.side_effects is SideEffectLevel.READ
            assert contract.read_only is True

    def test_destructive_maps_to_destructive(self) -> None:
        contract = _safety_from_annotations(ToolAnnotations(destructiveHint=True), "cap")
        assert contract is not None
        assert contract.side_effects is SideEffectLevel.DESTRUCTIVE
        assert contract.read_only is False

    def test_destructive_wins_over_read_only(self) -> None:
        contract = _safety_from_annotations(
            ToolAnnotations(readOnlyHint=True, destructiveHint=True), "cap"
        )
        assert contract is not None
        assert contract.side_effects is SideEffectLevel.DESTRUCTIVE

    def test_idempotent_hint_propagates(self) -> None:
        contract = _safety_from_annotations(
            ToolAnnotations(destructiveHint=True, idempotentHint=True), "cap"
        )
        assert contract is not None
        assert contract.idempotent is True
        # Destructive but idempotent → retry is at least not unsafe by idempotency.
        assert contract.safe_to_retry is True

    def test_remote_determinism_always_none(self) -> None:
        contract = _safety_from_annotations(ToolAnnotations(readOnlyHint=True), "cap")
        assert contract is not None
        assert contract.determinism_level is DeterminismLevel.NONE
        assert contract.cacheable is False

    def test_integration_unannotated_tool_capped_external(self) -> None:
        async def go() -> None:
            server = _build_demo_server()
            async with create_connected_server_and_client_session(server._mcp_server) as session:
                await session.initialize()
                adapter = MCPToolAdapter(session, annotation_trust="cap")
                tools = {t.name: t for t in await adapter.discover_tools()}
                # FastMCP does not emit annotations for these tools → capped EXTERNAL.
                assert tools["echo"].safety.side_effects is SideEffectLevel.EXTERNAL
                assert tools["echo"].metadata["mcp_annotation_source"] == "absent"

        _run(go())

    def test_integration_ignore_leaves_permissive_default(self) -> None:
        async def go() -> None:
            server = _build_demo_server()
            async with create_connected_server_and_client_session(server._mcp_server) as session:
                await session.initialize()
                adapter = MCPToolAdapter(session, annotation_trust="ignore")
                tools = {t.name: t for t in await adapter.discover_tools()}
                # safety=None → Tool falls back to its permissive default contract,
                # but remains uncached (the historical adapter behaviour).
                assert tools["echo"].cacheable is False
                assert tools["echo"].safety_declared is False

        _run(go())


# ---------------------------------------------------------------------------
# #359 — MetadataPolicy
# ---------------------------------------------------------------------------


class TestMetadataPolicy:
    def test_strips_control_chars(self) -> None:
        policy = MetadataPolicy()
        out = policy.apply_description("hi\x00\x07there", cw_name="t", server=None)
        assert out == "hithere"

    def test_normalizes_whitespace(self) -> None:
        policy = MetadataPolicy()
        out = policy.apply_description("a   b\n\nc", cw_name="t", server=None)
        assert out == "a b c"

    def test_truncates_to_cap(self) -> None:
        policy = MetadataPolicy(max_description_length=5, normalize_whitespace=False)
        out = policy.apply_description("abcdefghij", cw_name="t", server=None)
        assert out == "abcde…(truncated)"

    def test_placeholder_mode_ignores_remote_text(self) -> None:
        policy = MetadataPolicy(description_mode="placeholder")
        out = policy.apply_description("malicious instructions", cw_name="t", server="srv")
        assert "malicious" not in out
        assert "srv" in out

    def test_empty_after_sanitize_falls_back(self) -> None:
        policy = MetadataPolicy()
        out = policy.apply_description("\x00\x01\x02", cw_name="tool_x", server=None)
        assert out == "MCP tool 'tool_x'."

    def test_invalid_name_errors_by_default(self) -> None:
        policy = MetadataPolicy()
        with pytest.raises(MCPMetadataError):
            policy.apply_name("bad name!")

    def test_invalid_name_sanitized_when_configured(self) -> None:
        policy = MetadataPolicy(on_invalid_name="sanitize")
        assert policy.apply_name("bad name!") == "bad_name_"

    def test_valid_name_unchanged(self) -> None:
        assert MetadataPolicy().apply_name("search__query") == "search__query"

    def test_permissive_restores_verbatim(self) -> None:
        policy = MetadataPolicy.permissive()
        raw = "x" * 5000 + "\x07"
        out = policy.apply_description(raw, cw_name="t", server=None)
        assert out == raw  # no cap, no stripping
        assert policy.apply_name("weird name!!") == "weird name!!"

    def test_integration_raw_description_preserved(self) -> None:
        async def go() -> None:
            server = _build_demo_server()
            async with create_connected_server_and_client_session(server._mcp_server) as session:
                await session.initialize()
                adapter = MCPToolAdapter(
                    session, metadata_policy=MetadataPolicy(description_mode="placeholder")
                )
                tools = {t.name: t for t in await adapter.discover_tools()}
                # Description replaced, but the raw server text is retained for audit.
                assert "Echoes" not in tools["echo"].description
                assert tools["echo"].metadata["mcp_raw_description"] == "Echoes the supplied text."

        _run(go())


# ---------------------------------------------------------------------------
# #358 — schema-hash pinning + drift
# ---------------------------------------------------------------------------


class TestSchemaPinning:
    def test_metadata_carries_schema_hash(self) -> None:
        async def go() -> None:
            server = _build_demo_server()
            async with create_connected_server_and_client_session(server._mcp_server) as session:
                await session.initialize()
                adapter = MCPToolAdapter(session)
                tools = await adapter.discover_tools()
                for tool in tools:
                    assert isinstance(tool.metadata["mcp_schema_hash"], str)
                    assert len(tool.metadata["mcp_schema_hash"]) == 16

        _run(go())

    def test_drift_error_raises(self) -> None:
        async def go() -> None:
            server = _build_demo_server()
            async with create_connected_server_and_client_session(server._mcp_server) as session:
                await session.initialize()
                adapter = MCPToolAdapter(session, on_drift="error")
                with pytest.raises(MCPSchemaDriftError) as excinfo:
                    await adapter.discover_tools(pins={"echo": "0000000000000000"})
                assert excinfo.value.tool_name == "echo"

        _run(go())

    def test_drift_warn_continues(self, caplog: pytest.LogCaptureFixture) -> None:
        async def go() -> list[Any]:
            server = _build_demo_server()
            async with create_connected_server_and_client_session(server._mcp_server) as session:
                await session.initialize()
                adapter = MCPToolAdapter(session, on_drift="warn")
                with caplog.at_level(logging.WARNING, logger="chainweaver.mcp.adapter"):
                    return await adapter.discover_tools(pins={"echo": "0000000000000000"})

        tools = _run(go())
        assert {t.name for t in tools} == {"echo", "add"}
        assert any("drifted" in r.message for r in caplog.records)

    def test_matching_pin_no_drift(self) -> None:
        async def go() -> None:
            server = _build_demo_server()
            async with create_connected_server_and_client_session(server._mcp_server) as session:
                await session.initialize()
                adapter = MCPToolAdapter(session, on_drift="error")
                first = await adapter.discover_tools()
                pins = {
                    t.metadata["mcp_remote_name"]: t.metadata["mcp_schema_hash"] for t in first
                }
                # Re-discovering with the captured pins must not raise.
                again = await adapter.discover_tools(pins=pins)
                assert len(again) == len(first)

        _run(go())

    def test_pin_file_roundtrip(self, tmp_path: Any) -> None:
        async def go() -> None:
            server = _build_demo_server()
            async with create_connected_server_and_client_session(server._mcp_server) as session:
                await session.initialize()
                adapter = MCPToolAdapter(session, on_drift="error")
                tools = await adapter.discover_tools()
                pin_file = tmp_path / "mcp-pins.json"
                pin_file.write_text(json.dumps(build_pin_file(tools, server="demo")))

                loaded = load_pins(pin_file)
                assert loaded == {
                    t.metadata["mcp_remote_name"]: t.metadata["mcp_schema_hash"] for t in tools
                }
                # pins_path consumed end-to-end with no drift.
                again = await adapter.discover_tools(pins_path=pin_file)
                assert len(again) == len(tools)

        _run(go())
