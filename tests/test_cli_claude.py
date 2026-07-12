"""Tests for the ``chainweaver claude`` CLI commands (issues #271, #272, #273).

``capture`` normalizes PostToolUse hook events from stdin into a trace sink;
``setup`` / ``revert`` wire up the observe hook and FlowServer exposure with
dry-run, backups, scope selection, and ChainWeaver-only edits. Exit-code
contract: ``0`` success, ``1`` logic error, ``2`` missing workspace.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from chainweaver import cli


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


def _hook_payload(**overrides: object) -> str:
    payload: dict[str, object] = {
        "hook_event_name": "PostToolUse",
        "session_id": "s1",
        "tool_name": "Read",
        "tool_input": {"file_path": "a.py"},
        "tool_output": {"text": "ok"},
    }
    payload.update(overrides)
    return json.dumps(payload)


class TestCapture:
    def test_writes_normalized_jsonl(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sink = tmp_path / "trace.jsonl"
        _feed_stdin(monkeypatch, _hook_payload())
        exit_code = cli.main(["claude", "capture", "--sink", str(sink)])
        assert exit_code == 0
        line = json.loads(sink.read_text(encoding="utf-8").strip())
        assert line["tool"] == "Read"
        assert line["session_id"] == "s1"

    def test_redaction_on_by_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sink = tmp_path / "trace.jsonl"
        _feed_stdin(monkeypatch, _hook_payload(tool_input={"token": "SECRET"}))
        cli.main(["claude", "capture", "--sink", str(sink)])
        assert "SECRET" not in sink.read_text(encoding="utf-8")

    def test_no_redact_keeps_raw(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        sink = tmp_path / "trace.jsonl"
        _feed_stdin(monkeypatch, _hook_payload(tool_input={"token": "SECRET"}))
        cli.main(["claude", "capture", "--sink", str(sink), "--no-redact"])
        assert "SECRET" in sink.read_text(encoding="utf-8")

    def test_jsonl_multiple_events(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        sink = tmp_path / "trace.jsonl"
        _feed_stdin(
            monkeypatch,
            json.dumps(
                [
                    {"tool_name": "a"},
                    {"hook_event_name": "Stop"},
                    {"tool_name": "b"},
                ]
            ),
        )
        cli.main(["claude", "capture", "--sink", str(sink)])
        lines = sink.read_text(encoding="utf-8").splitlines()
        assert [json.loads(line)["tool"] for line in lines] == ["a", "b"]

    def test_non_tool_event_writes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sink = tmp_path / "trace.jsonl"
        _feed_stdin(monkeypatch, json.dumps({"hook_event_name": "SessionStart"}))
        exit_code = cli.main(["claude", "capture", "--sink", str(sink)])
        assert exit_code == 0
        assert not sink.exists()

    def test_malformed_input_exits_one_without_corrupting_sink(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        sink = tmp_path / "trace.jsonl"
        sink.write_text('{"tool": "existing"}\n', encoding="utf-8")
        _feed_stdin(monkeypatch, "not json{")
        exit_code = cli.main(["claude", "capture", "--sink", str(sink)])
        assert exit_code == 1
        assert "chainweaver:" in capsys.readouterr().err
        assert sink.read_text(encoding="utf-8") == '{"tool": "existing"}\n'


class TestSetupObserve:
    def test_dry_run_writes_nothing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = cli.main(["claude", "setup", "--observe", "--workspace", str(tmp_path)])
        assert exit_code == 0
        assert "dry run" in capsys.readouterr().out
        assert not (tmp_path / ".claude").exists()

    def test_write_creates_local_settings_hook(self, tmp_path: Path) -> None:
        exit_code = cli.main(
            ["claude", "setup", "--observe", "--write", "--workspace", str(tmp_path)]
        )
        assert exit_code == 0
        settings = tmp_path / ".claude" / "settings.local.json"
        assert settings.is_file()
        data = json.loads(settings.read_text(encoding="utf-8"))
        command = data["hooks"]["PostToolUse"][0]["hooks"][0]["command"]
        assert "chainweaver claude capture" in command

    def test_scope_project_writes_shared_settings(self, tmp_path: Path) -> None:
        cli.main(
            [
                "claude",
                "setup",
                "--observe",
                "--write",
                "--scope",
                "project",
                "--workspace",
                str(tmp_path),
            ]
        )
        assert (tmp_path / ".claude" / "settings.json").is_file()
        assert not (tmp_path / ".claude" / "settings.local.json").exists()

    def test_repeated_write_creates_backup(self, tmp_path: Path) -> None:
        args = ["claude", "setup", "--observe", "--write", "--workspace", str(tmp_path)]
        cli.main(args)
        cli.main(args)
        settings = tmp_path / ".claude" / "settings.local.json"
        assert settings.with_suffix(settings.suffix + ".bak").is_file()

    def test_bad_scope_exits_one(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        exit_code = cli.main(
            ["claude", "setup", "--observe", "--scope", "user", "--workspace", str(tmp_path)]
        )
        assert exit_code == 1
        assert "--scope" in capsys.readouterr().err


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
                "claude",
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
        assert change["exposed_tools"]["ship_it"] == "cw__ship_it"
        assert "wip" in change["withheld_flows"]

    def test_write_creates_mcp_json_preserving_other_servers(self, tmp_path: Path) -> None:
        config = tmp_path / ".mcp.json"
        config.write_text(
            json.dumps({"mcpServers": {"other": {"command": "x"}}}), encoding="utf-8"
        )
        flows = tmp_path / "flows"
        flows.mkdir()
        (flows / "a.flow.yaml").write_text(_flow_yaml("ship_it", "active"), encoding="utf-8")
        exit_code = cli.main(
            [
                "claude",
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
        assert written["mcpServers"]["other"] == {"command": "x"}
        assert written["mcpServers"]["chainweaver"]["command"] == "chainweaver"
        assert config.with_suffix(".json.bak").is_file()

    def test_collision_fails_unless_allowed(self, tmp_path: Path) -> None:
        flows = tmp_path / "flows"
        flows.mkdir()
        (flows / "r.flow.yaml").write_text(_flow_yaml("read", "active"), encoding="utf-8")
        base = [
            "claude",
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
        assert cli.main(["claude", "setup", "--workspace", str(tmp_path)]) == 1
        assert "--observe" in capsys.readouterr().err

    def test_missing_workspace_exits_two(self, tmp_path: Path) -> None:
        assert (
            cli.main(["claude", "setup", "--observe", "--workspace", str(tmp_path / "nope")]) == 2
        )


class TestRevert:
    def test_revert_observe_removes_only_chainweaver_hook(self, tmp_path: Path) -> None:
        settings = tmp_path / ".claude" / "settings.local.json"
        settings.parent.mkdir(parents=True, exist_ok=True)
        settings.write_text(
            json.dumps(
                {"hooks": {"PostToolUse": [{"hooks": [{"type": "command", "command": "keep"}]}]}}
            ),
            encoding="utf-8",
        )
        cli.main(["claude", "setup", "--observe", "--write", "--workspace", str(tmp_path)])
        exit_code = cli.main(
            ["claude", "revert", "--observe", "--write", "--workspace", str(tmp_path)]
        )
        assert exit_code == 0
        data = json.loads(settings.read_text(encoding="utf-8"))
        commands = [h["command"] for e in data["hooks"]["PostToolUse"] for h in e["hooks"]]
        assert commands == ["keep"]

    def test_revert_flows_preserves_other_servers(self, tmp_path: Path) -> None:
        config = tmp_path / ".mcp.json"
        config.write_text(
            json.dumps(
                {"mcpServers": {"other": {"command": "x"}, "chainweaver": {"command": "y"}}}
            ),
            encoding="utf-8",
        )
        exit_code = cli.main(
            ["claude", "revert", "--flows", "--write", "--workspace", str(tmp_path)]
        )
        assert exit_code == 0
        written = json.loads(config.read_text(encoding="utf-8"))
        assert written["mcpServers"] == {"other": {"command": "x"}}

    def test_dry_run_makes_no_change(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        config = tmp_path / ".mcp.json"
        config.write_text(
            json.dumps({"mcpServers": {"chainweaver": {"command": "y"}}}), encoding="utf-8"
        )
        cli.main(["claude", "revert", "--flows", "--workspace", str(tmp_path)])
        assert "dry run" in capsys.readouterr().out
        assert "chainweaver" in config.read_text(encoding="utf-8")
