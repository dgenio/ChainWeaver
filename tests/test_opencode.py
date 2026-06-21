"""Tests for the OpenCode integration library (issues #276, #278, #279, #280).

Covers event normalization (tool sources, redaction, missing fields, determinism),
macro-tool naming and collision detection, and the FlowServer exposure config
builders/merge helpers. The CLI surface is tested in ``test_cli_opencode.py``.
"""

from __future__ import annotations

import pytest

from chainweaver.log_utils import RedactionPolicy
from chainweaver.opencode import (
    OPENCODE_TOOL_PREFIX,
    OpenCodeAdapterError,
    add_flow_server_to_config,
    build_flow_mcp_entry,
    detect_tool_name_collisions,
    normalize_opencode_event,
    normalize_opencode_events,
    remove_flow_server_from_config,
    render_observe_plugin,
    safe_macro_tool_name,
)
from chainweaver.traces import TraceEventKind


class TestNormalizeEvent:
    def test_mcp_tool_event_maps_all_fields(self) -> None:
        event = normalize_opencode_event(
            {
                "type": "tool.execute.after",
                "tool": "github_get_pr",
                "sessionID": "s1",
                "callID": "c1",
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
        assert event.turn_id == "c1"
        assert event.result_status == "ok"
        assert event.output_keys == ("title", "files")
        assert event.latency_ms == 1500.0
        assert event.tool_source == "mcp"

    def test_builtin_and_custom_sources_preserved(self) -> None:
        builtin = normalize_opencode_event({"tool": "read", "source": "builtin"})
        custom = normalize_opencode_event({"tool": "my_tool", "tool_source": "custom"})
        assert builtin is not None and builtin.tool_source == "builtin"
        assert custom is not None and custom.tool_source == "custom"

    def test_failed_event_marks_error_status(self) -> None:
        event = normalize_opencode_event({"tool": "deploy", "sessionID": "s1", "error": "boom"})
        assert event is not None
        assert event.result_status == "error"

    def test_redaction_on_by_default(self) -> None:
        event = normalize_opencode_event(
            {"tool": "login", "args": {"user": "ann", "token": "SECRET"}}
        )
        assert event is not None
        assert event.args == {"user": "ann", "token": "***REDACTED***"}

    def test_redaction_can_be_disabled(self) -> None:
        event = normalize_opencode_event(
            {"tool": "login", "args": {"token": "SECRET"}},
            redaction=RedactionPolicy(redact_keys=frozenset()),
        )
        assert event is not None
        assert event.args == {"token": "SECRET"}

    def test_missing_optional_fields_do_not_fail(self) -> None:
        event = normalize_opencode_event({"tool": "read"})
        assert event is not None
        assert event.session_id == "__default__"
        assert event.turn_id is None
        assert event.latency_ms is None
        assert event.timestamp is None  # absent clock is left None (determinism)

    def test_alternate_key_spellings(self) -> None:
        event = normalize_opencode_event(
            {"event": "tool.execute", "tool_name": "x", "session_id": "s9", "input": {"a": 1}}
        )
        assert event is not None
        assert event.tool == "x"
        assert event.session_id == "s9"
        assert event.args == {"a": 1}

    def test_non_tool_event_returns_none(self) -> None:
        assert normalize_opencode_event({"type": "session.idle"}) is None
        assert normalize_opencode_event({"event": "storage.write"}) is None

    def test_unknown_fields_preserved_in_metadata(self) -> None:
        event = normalize_opencode_event({"tool": "x", "vendorField": "keep", "nested": {"k": 1}})
        assert event is not None
        assert event.metadata == {"vendorField": "keep", "nested": {"k": 1}}

    def test_non_dict_payload_raises(self) -> None:
        with pytest.raises(OpenCodeAdapterError):
            normalize_opencode_event(["not", "a", "dict"])

    def test_normalize_events_filters_none_and_preserves_order(self) -> None:
        events = normalize_opencode_events(
            [
                {"tool": "a"},
                {"type": "session.idle"},
                {"tool": "b"},
            ]
        )
        assert [e.tool for e in events] == ["a", "b"]

    def test_deterministic_output(self) -> None:
        payload = {"tool": "x", "args": {"b": 2, "a": 1}, "sessionID": "s"}
        first = normalize_opencode_event(payload)
        second = normalize_opencode_event(payload)
        assert first is not None and second is not None
        assert first.model_dump(mode="json") == second.model_dump(mode="json")


class TestNaming:
    def test_prefix_and_slugify(self) -> None:
        assert safe_macro_tool_name("PR Review Flow") == "cw_pr_review_flow"
        assert safe_macro_tool_name("github.get-pr") == "cw_github_get_pr"

    def test_already_prefixed_not_doubled(self) -> None:
        assert safe_macro_tool_name("cw_existing") == "cw_existing"

    def test_stable_across_calls(self) -> None:
        assert safe_macro_tool_name("My Flow") == safe_macro_tool_name("My Flow")

    def test_custom_prefix(self) -> None:
        assert safe_macro_tool_name("deploy", prefix="chainweaver") == "chainweaver_deploy"

    def test_empty_prefix_allowed(self) -> None:
        assert safe_macro_tool_name("deploy", prefix="") == "deploy"

    def test_no_safe_characters_raises(self) -> None:
        with pytest.raises(OpenCodeAdapterError):
            safe_macro_tool_name("!!!")

    def test_reserved_collision_detected(self) -> None:
        collisions = detect_tool_name_collisions(["read"], prefix="")
        assert "read" in collisions
        assert "reserved" in collisions["read"]

    def test_prefix_avoids_reserved_collision(self) -> None:
        assert detect_tool_name_collisions(["read", "bash"]) == {}

    def test_known_name_collision_detected(self) -> None:
        collisions = detect_tool_name_collisions(
            ["deploy"], known_tool_names=["cw_deploy"], prefix=OPENCODE_TOOL_PREFIX
        )
        assert "deploy" in collisions

    def test_interflow_collision_detected(self) -> None:
        collisions = detect_tool_name_collisions(["PR Review", "pr-review"], prefix="")
        # Both slugify to the same name; the second is flagged.
        assert len(collisions) == 1


class TestExposureConfig:
    def test_build_entry_with_tools(self) -> None:
        entry = build_flow_mcp_entry(flows_dir="flows", tools_module="my.tools")
        assert entry == {
            "command": "chainweaver",
            "args": ["serve", "flows", "--tools", "my.tools", "--prefix", "cw"],
        }

    def test_build_entry_without_tools(self) -> None:
        entry = build_flow_mcp_entry(flows_dir="flows")
        assert "--tools" not in entry["args"]

    def test_add_preserves_other_servers_without_mutation(self) -> None:
        original = {"mcp": {"other": {"command": "x"}}}
        merged = add_flow_server_to_config(original, {"command": "chainweaver"})
        assert merged["mcp"]["other"] == {"command": "x"}
        assert merged["mcp"]["chainweaver"] == {"command": "chainweaver"}
        # input not mutated
        assert "chainweaver" not in original["mcp"]

    def test_add_to_empty_config(self) -> None:
        merged = add_flow_server_to_config(None, {"command": "chainweaver"})
        assert merged == {"mcp": {"chainweaver": {"command": "chainweaver"}}}

    def test_remove_only_chainweaver_entry(self) -> None:
        config = {"mcp": {"other": {"command": "x"}, "chainweaver": {"command": "y"}}}
        new_config, removed = remove_flow_server_from_config(config)
        assert removed is True
        assert new_config["mcp"] == {"other": {"command": "x"}}

    def test_remove_drops_empty_mcp_map(self) -> None:
        new_config, removed = remove_flow_server_from_config({"mcp": {"chainweaver": {}}})
        assert removed is True
        assert "mcp" not in new_config

    def test_remove_reports_when_absent(self) -> None:
        _, removed = remove_flow_server_from_config({"mcp": {"other": {}}})
        assert removed is False


class TestObservePlugin:
    def test_plugin_contains_sink_and_redaction(self) -> None:
        source = render_observe_plugin(sink=".chainweaver/traces/oc.jsonl")
        assert ".chainweaver/traces/oc.jsonl" in source
        assert "--no-redact" not in source  # redaction on by default
        assert "opencode" in source and "capture" in source

    def test_plugin_disables_redaction_when_requested(self) -> None:
        source = render_observe_plugin(redact=False)
        assert "--no-redact" in source

    def test_plugin_normalizes_windows_backslash_sink(self) -> None:
        # A Windows ``str(Path(...))`` sink uses backslashes; the baked plugin
        # must always use forward slashes so the generated JS is portable.
        source = render_observe_plugin(sink=".chainweaver\\traces\\opencode.jsonl")
        assert ".chainweaver/traces/opencode.jsonl" in source
        assert "\\" not in source
