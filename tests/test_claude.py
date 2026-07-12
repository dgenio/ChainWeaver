"""Tests for the Claude Code integration library (issues #271, #272, #273).

Covers ``PostToolUse`` hook-event normalization (tool sources, redaction,
missing fields, determinism), observe-hook rendering and settings merge, and
the FlowServer ``mcpServers`` exposure builders. The CLI surface is tested in
``test_cli_claude.py``.
"""

from __future__ import annotations

import pytest

from chainweaver.claude import (
    ClaudeCodeAdapterError,
    add_flow_server_to_config,
    add_observe_hook_to_settings,
    normalize_claude_hook_event,
    normalize_claude_hook_events,
    remove_flow_server_from_config,
    remove_observe_hook_from_settings,
    render_posttooluse_hook,
)
from chainweaver.log_utils import RedactionPolicy
from chainweaver.traces import TraceEventKind


class TestNormalizeEvent:
    def test_mcp_tool_event_maps_all_fields(self) -> None:
        event = normalize_claude_hook_event(
            {
                "hook_event_name": "PostToolUse",
                "session_id": "s1",
                "prompt_id": "p1",
                "tool_name": "mcp__github__get_pr",
                "tool_input": {"repo": "x"},
                "tool_output": {"title": "hi", "files": []},
            }
        )
        assert event is not None
        assert event.event is TraceEventKind.TOOL_CALL
        assert event.tool == "mcp__github__get_pr"
        assert event.session_id == "s1"
        assert event.turn_id == "p1"
        assert event.result_status == "ok"
        assert event.output_keys == ("title", "files")
        assert event.tool_source == "mcp"
        # MCP server / leaf provenance is recorded in metadata.
        assert event.metadata["mcp_server"] == "github"
        assert event.metadata["mcp_tool"] == "get_pr"

    def test_builtin_tool_source(self) -> None:
        event = normalize_claude_hook_event({"tool_name": "Bash", "tool_input": {"command": "ls"}})
        assert event is not None
        assert event.tool_source == "builtin"

    def test_explicit_source_wins(self) -> None:
        event = normalize_claude_hook_event({"tool_name": "x", "tool_source": "custom"})
        assert event is not None
        assert event.tool_source == "custom"

    def test_failed_event_marks_error_status(self) -> None:
        via_top = normalize_claude_hook_event({"tool_name": "Edit", "error": "boom"})
        via_output = normalize_claude_hook_event(
            {"tool_name": "Edit", "tool_output": {"is_error": True}}
        )
        assert via_top is not None and via_top.result_status == "error"
        assert via_output is not None and via_output.result_status == "error"

    def test_redaction_on_by_default(self) -> None:
        event = normalize_claude_hook_event(
            {"tool_name": "login", "tool_input": {"user": "ann", "token": "SECRET"}}
        )
        assert event is not None
        assert event.args == {"user": "ann", "token": "***REDACTED***"}

    def test_redaction_can_be_disabled(self) -> None:
        event = normalize_claude_hook_event(
            {"tool_name": "login", "tool_input": {"token": "SECRET"}},
            redaction=RedactionPolicy(redact_keys=frozenset()),
        )
        assert event is not None
        assert event.args == {"token": "SECRET"}

    def test_tool_response_and_result_spellings(self) -> None:
        via_response = normalize_claude_hook_event({"tool_name": "x", "tool_response": {"a": 1}})
        via_result = normalize_claude_hook_event({"tool_name": "x", "result": {"b": 2}})
        assert via_response is not None and via_response.output_keys == ("a",)
        assert via_result is not None and via_result.output_keys == ("b",)

    def test_missing_optional_fields_do_not_fail(self) -> None:
        event = normalize_claude_hook_event({"tool_name": "Read"})
        assert event is not None
        assert event.session_id == "__default__"
        assert event.turn_id is None
        assert event.latency_ms is None
        assert event.timestamp is None  # no wall-clock in the payload (determinism)

    def test_non_tool_event_returns_none(self) -> None:
        assert normalize_claude_hook_event({"hook_event_name": "SessionStart"}) is None
        assert normalize_claude_hook_event({"tool_input": {"a": 1}}) is None

    def test_unknown_fields_preserved_in_metadata(self) -> None:
        event = normalize_claude_hook_event(
            {"tool_name": "Read", "transcript_path": "/t.jsonl", "cwd": "/proj"}
        )
        assert event is not None
        assert event.metadata["transcript_path"] == "/t.jsonl"
        assert event.metadata["cwd"] == "/proj"

    def test_non_dict_payload_raises(self) -> None:
        with pytest.raises(ClaudeCodeAdapterError):
            normalize_claude_hook_event(["not", "a", "dict"])

    def test_normalize_events_filters_none_and_preserves_order(self) -> None:
        events = normalize_claude_hook_events(
            [
                {"tool_name": "a"},
                {"hook_event_name": "Stop"},
                {"tool_name": "b"},
            ]
        )
        assert [e.tool for e in events] == ["a", "b"]

    def test_deterministic_output(self) -> None:
        payload = {"tool_name": "x", "tool_input": {"b": 2, "a": 1}, "session_id": "s"}
        first = normalize_claude_hook_event(payload)
        second = normalize_claude_hook_event(payload)
        assert first is not None and second is not None
        assert first.model_dump(mode="json") == second.model_dump(mode="json")


class TestObserveHook:
    def test_render_contains_capture_command_and_sink(self) -> None:
        entry = render_posttooluse_hook(sink=".chainweaver/traces/cc.jsonl")
        command = entry["hooks"][0]["command"]
        assert "chainweaver claude capture" in command
        assert ".chainweaver/traces/cc.jsonl" in command
        assert "--no-redact" not in command  # redaction on by default
        assert "matcher" not in entry  # empty matcher → omitted (all tools)

    def test_render_disables_redaction_and_sets_matcher(self) -> None:
        entry = render_posttooluse_hook(redact=False, matcher="mcp__.*")
        assert "--no-redact" in entry["hooks"][0]["command"]
        assert entry["matcher"] == "mcp__.*"

    def test_render_normalizes_windows_backslash_sink(self) -> None:
        entry = render_posttooluse_hook(sink=".chainweaver\\traces\\claude-code.jsonl")
        command = entry["hooks"][0]["command"]
        assert ".chainweaver/traces/claude-code.jsonl" in command
        assert "\\" not in command

    def test_add_preserves_other_hooks_without_mutation(self) -> None:
        original = {
            "hooks": {"PreToolUse": [{"hooks": [{"type": "command", "command": "other"}]}]}
        }
        merged = add_observe_hook_to_settings(original, render_posttooluse_hook())
        assert "PreToolUse" in merged["hooks"]
        assert len(merged["hooks"]["PostToolUse"]) == 1
        # input untouched
        assert "PostToolUse" not in original["hooks"]

    def test_repeated_add_is_idempotent(self) -> None:
        s1 = add_observe_hook_to_settings(None, render_posttooluse_hook())
        s2 = add_observe_hook_to_settings(s1, render_posttooluse_hook())
        assert len(s2["hooks"]["PostToolUse"]) == 1

    def test_add_keeps_unrelated_posttooluse_hooks(self) -> None:
        original = {
            "hooks": {"PostToolUse": [{"hooks": [{"type": "command", "command": "user-linter"}]}]}
        }
        merged = add_observe_hook_to_settings(original, render_posttooluse_hook())
        commands = [
            h["command"] for entry in merged["hooks"]["PostToolUse"] for h in entry["hooks"]
        ]
        assert "user-linter" in commands
        assert any("chainweaver claude capture" in c for c in commands)

    def test_remove_only_chainweaver_hook(self) -> None:
        settings = add_observe_hook_to_settings(
            {"hooks": {"PostToolUse": [{"hooks": [{"type": "command", "command": "keep-me"}]}]}},
            render_posttooluse_hook(),
        )
        new_settings, removed = remove_observe_hook_from_settings(settings)
        assert removed is True
        commands = [
            h["command"] for entry in new_settings["hooks"]["PostToolUse"] for h in entry["hooks"]
        ]
        assert commands == ["keep-me"]

    def test_remove_prunes_empty_structures(self) -> None:
        settings = add_observe_hook_to_settings(None, render_posttooluse_hook())
        new_settings, removed = remove_observe_hook_from_settings(settings)
        assert removed is True
        assert "hooks" not in new_settings

    def test_remove_reports_when_absent(self) -> None:
        _, removed = remove_observe_hook_from_settings({"hooks": {"PreToolUse": []}})
        assert removed is False


class TestExposureConfig:
    def test_add_uses_mcpservers_key_without_mutation(self) -> None:
        original = {"mcpServers": {"other": {"command": "x"}}}
        merged = add_flow_server_to_config(original, {"command": "chainweaver"})
        assert merged["mcpServers"]["other"] == {"command": "x"}
        assert merged["mcpServers"]["chainweaver"] == {"command": "chainweaver"}
        assert "chainweaver" not in original["mcpServers"]

    def test_add_to_empty_config(self) -> None:
        merged = add_flow_server_to_config(None, {"command": "chainweaver"})
        assert merged == {"mcpServers": {"chainweaver": {"command": "chainweaver"}}}

    def test_remove_only_chainweaver_entry(self) -> None:
        config = {"mcpServers": {"other": {"command": "x"}, "chainweaver": {"command": "y"}}}
        new_config, removed = remove_flow_server_from_config(config)
        assert removed is True
        assert new_config["mcpServers"] == {"other": {"command": "x"}}

    def test_remove_drops_empty_map(self) -> None:
        new_config, removed = remove_flow_server_from_config({"mcpServers": {"chainweaver": {}}})
        assert removed is True
        assert "mcpServers" not in new_config

    def test_remove_reports_when_absent(self) -> None:
        _, removed = remove_flow_server_from_config({"mcpServers": {"other": {}}})
        assert removed is False
