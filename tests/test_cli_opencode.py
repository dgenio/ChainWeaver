"""Tests for the ``chainweaver opencode`` CLI commands (issues #276, #277, #279, #280).

``capture`` normalizes plugin events from stdin into a trace sink; ``setup`` /
``revert`` wire up observe mode and FlowServer exposure with dry-run, backups,
and ChainWeaver-only edits. Exit-code contract: ``0`` success, ``1`` logic
error (malformed input, name collisions, no flags), ``2`` missing workspace.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from chainweaver import cli
from chainweaver.opencode import OPENCODE_OBSERVE_PLUGIN_FILENAME


@pytest.fixture(autouse=True)
def _reset_registry() -> None:
    cli.set_default_registry(None)


def _flow_yaml(name: str, lifecycle: str) -> str:
    return (
        f"type: Flow\nname: {name}\nversion: '0.1.0'\ndescription: d\n"
        f"governance:\n  lifecycle: {lifecycle}\n"
        "steps:\n  - tool_name: double\n    input_mapping: {number: number}\n"
    )


def _feed_stdin(monkeypatch: pytest.MonkeyPatch, text: str) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(text))


class TestCapture:
    def test_writes_normalized_jsonl(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sink = tmp_path / "trace.jsonl"
        _feed_stdin(
            monkeypatch,
            json.dumps({"tool": "read", "sessionID": "s1", "args": {"path": "a"}}),
        )
        exit_code = cli.main(["opencode", "capture", "--sink", str(sink)])
        assert exit_code == 0
        line = json.loads(sink.read_text(encoding="utf-8").strip())
        assert line["tool"] == "read"
        assert line["session_id"] == "s1"

    def test_redaction_on_by_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sink = tmp_path / "trace.jsonl"
        _feed_stdin(monkeypatch, json.dumps({"tool": "x", "args": {"token": "SECRET"}}))
        cli.main(["opencode", "capture", "--sink", str(sink)])
        assert "SECRET" not in sink.read_text(encoding="utf-8")

    def test_no_redact_keeps_raw(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        sink = tmp_path / "trace.jsonl"
        _feed_stdin(monkeypatch, json.dumps({"tool": "x", "args": {"token": "SECRET"}}))
        cli.main(["opencode", "capture", "--sink", str(sink), "--no-redact"])
        assert "SECRET" in sink.read_text(encoding="utf-8")

    def test_jsonl_and_array_multiple_events(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sink = tmp_path / "trace.jsonl"
        _feed_stdin(
            monkeypatch,
            json.dumps([{"tool": "a"}, {"type": "session.idle"}, {"tool": "b"}]),
        )
        cli.main(["opencode", "capture", "--sink", str(sink)])
        lines = sink.read_text(encoding="utf-8").splitlines()
        assert [json.loads(line)["tool"] for line in lines] == ["a", "b"]

    def test_non_tool_event_writes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sink = tmp_path / "trace.jsonl"
        _feed_stdin(monkeypatch, json.dumps({"type": "session.idle"}))
        exit_code = cli.main(["opencode", "capture", "--sink", str(sink)])
        assert exit_code == 0
        assert not sink.exists()

    def test_malformed_input_exits_one_without_corrupting_sink(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        sink = tmp_path / "trace.jsonl"
        sink.write_text('{"tool": "existing"}\n', encoding="utf-8")
        _feed_stdin(monkeypatch, "not json{")
        exit_code = cli.main(["opencode", "capture", "--sink", str(sink)])
        assert exit_code == 1
        assert "chainweaver:" in capsys.readouterr().err
        # The pre-existing sink content is untouched.
        assert sink.read_text(encoding="utf-8") == '{"tool": "existing"}\n'


class TestSetupObserve:
    def test_dry_run_writes_nothing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = cli.main(["opencode", "setup", "--observe", "--workspace", str(tmp_path)])
        assert exit_code == 0
        assert "dry run" in capsys.readouterr().out
        assert not (tmp_path / ".opencode").exists()

    def test_write_creates_plugin(self, tmp_path: Path) -> None:
        exit_code = cli.main(
            ["opencode", "setup", "--observe", "--write", "--workspace", str(tmp_path)]
        )
        assert exit_code == 0
        plugin = tmp_path / ".opencode" / "plugin" / OPENCODE_OBSERVE_PLUGIN_FILENAME
        assert plugin.is_file()
        assert ".chainweaver/traces/opencode.jsonl" in plugin.read_text(encoding="utf-8")

    def test_repeated_write_creates_backup(self, tmp_path: Path) -> None:
        args = ["opencode", "setup", "--observe", "--write", "--workspace", str(tmp_path)]
        cli.main(args)
        cli.main(args)
        plugin = tmp_path / ".opencode" / "plugin" / OPENCODE_OBSERVE_PLUGIN_FILENAME
        assert plugin.with_suffix(plugin.suffix + ".bak").is_file()


class TestSetupFlows:
    def test_exposes_active_withholds_draft(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        flows = tmp_path / "flows"
        flows.mkdir()
        (flows / "active.flow.yaml").write_text(_flow_yaml("ship_it", "active"), encoding="utf-8")
        (flows / "draft.flow.yaml").write_text(_flow_yaml("wip", "draft"), encoding="utf-8")
        exit_code = cli.main(
            [
                "opencode",
                "setup",
                "--flows",
                "--workspace",
                str(tmp_path),
                "--flows-dir",
                str(flows),
                "--json",
            ]
        )
        assert exit_code == 0
        change = json.loads(capsys.readouterr().out)["changes"][0]
        assert "ship_it" in change["exposed_tools"]
        assert change["exposed_tools"]["ship_it"] == "cw_ship_it"
        assert "wip" in change["withheld_flows"]

    def test_write_creates_config_preserving_other_servers(self, tmp_path: Path) -> None:
        config = tmp_path / "opencode.json"
        config.write_text(json.dumps({"mcp": {"other": {"command": "x"}}}), encoding="utf-8")
        flows = tmp_path / "flows"
        flows.mkdir()
        (flows / "a.flow.yaml").write_text(_flow_yaml("ship_it", "active"), encoding="utf-8")
        exit_code = cli.main(
            [
                "opencode",
                "setup",
                "--flows",
                "--write",
                "--workspace",
                str(tmp_path),
                "--flows-dir",
                str(flows),
                "--tools",
                "my.tools",
            ]
        )
        assert exit_code == 0
        written = json.loads(config.read_text(encoding="utf-8"))
        assert written["mcp"]["other"] == {"command": "x"}
        assert written["mcp"]["chainweaver"]["command"] == "chainweaver"
        assert config.with_suffix(".json.bak").is_file()

    def test_collision_fails_unless_allowed(self, tmp_path: Path) -> None:
        flows = tmp_path / "flows"
        flows.mkdir()
        # An empty prefix makes "read" collide with the reserved built-in.
        (flows / "r.flow.yaml").write_text(_flow_yaml("read", "active"), encoding="utf-8")
        base = [
            "opencode",
            "setup",
            "--flows",
            "--write",
            "--workspace",
            str(tmp_path),
            "--flows-dir",
            str(flows),
            "--prefix",
            "",
        ]
        assert cli.main(base) == 1
        assert cli.main([*base, "--allow-collisions"]) == 0


class TestSetupArgsContract:
    def test_no_flag_exits_one(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert cli.main(["opencode", "setup", "--workspace", str(tmp_path)]) == 1
        assert "--observe" in capsys.readouterr().err

    def test_missing_workspace_exits_two(self, tmp_path: Path) -> None:
        assert (
            cli.main(["opencode", "setup", "--observe", "--workspace", str(tmp_path / "nope")])
            == 2
        )


class TestRevert:
    def test_revert_observe_removes_plugin_only(self, tmp_path: Path) -> None:
        cli.main(["opencode", "setup", "--observe", "--write", "--workspace", str(tmp_path)])
        traces = tmp_path / ".chainweaver" / "traces" / "opencode.jsonl"
        traces.parent.mkdir(parents=True, exist_ok=True)
        traces.write_text("keep\n", encoding="utf-8")
        exit_code = cli.main(
            ["opencode", "revert", "--observe", "--write", "--workspace", str(tmp_path)]
        )
        assert exit_code == 0
        plugin = tmp_path / ".opencode" / "plugin" / OPENCODE_OBSERVE_PLUGIN_FILENAME
        assert not plugin.exists()
        assert traces.read_text(encoding="utf-8") == "keep\n"  # traces left intact

    def test_revert_flows_preserves_other_servers(self, tmp_path: Path) -> None:
        config = tmp_path / "opencode.json"
        config.write_text(
            json.dumps({"mcp": {"other": {"command": "x"}, "chainweaver": {"command": "y"}}}),
            encoding="utf-8",
        )
        exit_code = cli.main(
            ["opencode", "revert", "--flows", "--write", "--workspace", str(tmp_path)]
        )
        assert exit_code == 0
        written = json.loads(config.read_text(encoding="utf-8"))
        assert written["mcp"] == {"other": {"command": "x"}}

    def test_dry_run_makes_no_change(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        config = tmp_path / "opencode.json"
        config.write_text(json.dumps({"mcp": {"chainweaver": {"command": "y"}}}), encoding="utf-8")
        cli.main(["opencode", "revert", "--flows", "--workspace", str(tmp_path)])
        assert "dry run" in capsys.readouterr().out
        assert "chainweaver" in config.read_text(encoding="utf-8")
