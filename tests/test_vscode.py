"""Tests for the VS Code / Copilot integration library (issues #265, #269).

Covers MCP trace-event normalization (flat and OTel-attribute shapes,
redaction, missing fields, determinism), the Copilot OpenTelemetry settings
snippet, and the FlowServer ``servers`` exposure builders. The CLI surface is
tested in ``test_cli_vscode.py``.
"""

from __future__ import annotations

import json

import pytest

from chainweaver.log_utils import RedactionPolicy
from chainweaver.traces import TraceEventKind
from chainweaver.vscode import (
    VSCODE_TRACE_SINK,
    VSCodeAdapterError,
    add_flow_server_to_config,
    copilot_otel_settings_snippet,
    normalize_vscode_event,
    normalize_vscode_events,
    remove_flow_server_from_config,
)


class TestNormalizeEvent:
    def test_flat_tool_event_maps_all_fields(self) -> None:
        event = normalize_vscode_event(
            {
                "tool": "github_get_pr",
                "sessionId": "s1",
                "messageId": "m1",
                "args": {"repo": "x"},
                "result": {"title": "hi", "files": []},
                "time": {"start": 100, "end": 1600},
                "source": "mcp",
            }
        )
        assert event is not None
        assert event.event is TraceEventKind.TOOL_CALL
        assert event.tool == "github_get_pr"
        assert event.session_id == "s1"
        assert event.turn_id == "m1"
        assert event.result_status == "ok"
        assert event.output_keys == ("title", "files")
        assert event.latency_ms == 1500.0
        assert event.tool_source == "mcp"

    def test_otel_attributes_tool_name(self) -> None:
        # A Copilot OTel-style span carries the tool name in a nested attributes map.
        event = normalize_vscode_event(
            {"attributes": {"mcp.tool.name": "search_code"}, "traceId": "t1"}
        )
        assert event is not None
        assert event.tool == "search_code"
        assert event.session_id == "t1"

    def test_failed_event_marks_error_status(self) -> None:
        event = normalize_vscode_event({"tool": "deploy", "error": "boom"})
        assert event is not None
        assert event.result_status == "error"

    def test_redaction_on_by_default(self) -> None:
        event = normalize_vscode_event({"tool": "login", "args": {"token": "SECRET"}})
        assert event is not None
        assert event.args == {"token": "***REDACTED***"}

    def test_redaction_can_be_disabled(self) -> None:
        event = normalize_vscode_event(
            {"tool": "login", "args": {"token": "SECRET"}},
            redaction=RedactionPolicy(redact_keys=frozenset()),
        )
        assert event is not None
        assert event.args == {"token": "SECRET"}

    def test_alternate_key_spellings(self) -> None:
        event = normalize_vscode_event(
            {"tool_name": "x", "session_id": "s9", "params": {"a": 1}, "response": {"ok": True}}
        )
        assert event is not None
        assert event.tool == "x"
        assert event.session_id == "s9"
        assert event.args == {"a": 1}
        assert event.output_keys == ("ok",)

    def test_valid_iso_timestamp_preserved(self) -> None:
        event = normalize_vscode_event({"tool": "x", "timestamp": "2026-07-12T09:00:00+00:00"})
        assert event is not None
        assert event.timestamp is not None

    def test_non_iso_timestamp_dropped_not_raised(self) -> None:
        # A non-ISO timestamp string must not crash capture (tolerant of drift):
        # it is dropped to None rather than propagated into the datetime field.
        event = normalize_vscode_event({"tool": "x", "timestamp": "last tuesday"})
        assert event is not None
        assert event.timestamp is None

    def test_missing_optional_fields_do_not_fail(self) -> None:
        event = normalize_vscode_event({"tool": "read"})
        assert event is not None
        assert event.session_id == "__default__"
        assert event.turn_id is None
        assert event.latency_ms is None
        assert event.timestamp is None

    def test_non_tool_event_returns_none(self) -> None:
        assert normalize_vscode_event({"type": "model.call"}) is None
        assert normalize_vscode_event({"attributes": {"gen_ai.system": "copilot"}}) is None

    def test_unknown_fields_preserved_in_metadata(self) -> None:
        event = normalize_vscode_event({"tool": "x", "vendorField": "keep"})
        assert event is not None
        assert event.metadata == {"vendorField": "keep"}

    def test_non_dict_payload_raises(self) -> None:
        with pytest.raises(VSCodeAdapterError):
            normalize_vscode_event(["not", "a", "dict"])

    def test_normalize_events_filters_none_and_preserves_order(self) -> None:
        events = normalize_vscode_events([{"tool": "a"}, {"type": "model.call"}, {"tool": "b"}])
        assert [e.tool for e in events] == ["a", "b"]

    def test_deterministic_output(self) -> None:
        payload = {"tool": "x", "args": {"b": 2, "a": 1}, "sessionId": "s"}
        first = normalize_vscode_event(payload)
        second = normalize_vscode_event(payload)
        assert first is not None and second is not None
        assert first.model_dump(mode="json") == second.model_dump(mode="json")


class TestOtelSnippet:
    def test_snippet_contains_exporter_keys_and_sink(self) -> None:
        snippet = copilot_otel_settings_snippet(sink=".chainweaver/traces/vscode.jsonl")
        data = json.loads(snippet)
        assert data["github.copilot.chat.otel.exporterType"] == "file"
        assert data["github.copilot.chat.otel.outfile"] == ".chainweaver/traces/vscode.jsonl"

    def test_snippet_default_sink(self) -> None:
        data = json.loads(copilot_otel_settings_snippet())
        assert data["github.copilot.chat.otel.outfile"] == VSCODE_TRACE_SINK

    def test_snippet_normalizes_windows_backslash_sink(self) -> None:
        data = json.loads(copilot_otel_settings_snippet(sink=".chainweaver\\traces\\vscode.jsonl"))
        assert data["github.copilot.chat.otel.outfile"] == ".chainweaver/traces/vscode.jsonl"


class TestExposureConfig:
    def test_add_uses_servers_key_without_mutation(self) -> None:
        original = {"servers": {"other": {"command": "x"}}}
        merged = add_flow_server_to_config(original, {"command": "chainweaver"})
        assert merged["servers"]["other"] == {"command": "x"}
        assert merged["servers"]["chainweaver"] == {"command": "chainweaver"}
        assert "chainweaver" not in original["servers"]

    def test_add_to_empty_config(self) -> None:
        merged = add_flow_server_to_config(None, {"command": "chainweaver"})
        assert merged == {"servers": {"chainweaver": {"command": "chainweaver"}}}

    def test_remove_only_chainweaver_entry(self) -> None:
        config = {"servers": {"other": {"command": "x"}, "chainweaver": {"command": "y"}}}
        new_config, removed = remove_flow_server_from_config(config)
        assert removed is True
        assert new_config["servers"] == {"other": {"command": "x"}}

    def test_remove_drops_empty_map(self) -> None:
        new_config, removed = remove_flow_server_from_config({"servers": {"chainweaver": {}}})
        assert removed is True
        assert "servers" not in new_config

    def test_remove_reports_when_absent(self) -> None:
        _, removed = remove_flow_server_from_config({"servers": {"other": {}}})
        assert removed is False
