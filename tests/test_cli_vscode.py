"""Tests for the ``chainweaver vscode`` CLI commands (issues #265, #269).

``capture`` normalizes MCP trace records from stdin or ``--from`` into a sink;
``setup --observe`` prints the Copilot OTel snippet (never writes it);
``setup --flows`` / ``revert`` manage the ``.vscode/mcp.json`` FlowServer entry
with dry-run and backups. Exit-code contract: ``0`` success, ``1`` logic error,
``2`` missing path.
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


class TestCapture:
    def test_writes_normalized_jsonl_from_stdin(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sink = tmp_path / "trace.jsonl"
        _feed_stdin(
            monkeypatch,
            json.dumps({"tool": "search_code", "sessionId": "s1", "args": {"q": "x"}}),
        )
        exit_code = cli.main(["vscode", "capture", "--sink", str(sink)])
        assert exit_code == 0
        line = json.loads(sink.read_text(encoding="utf-8").strip())
        assert line["tool"] == "search_code"
        assert line["session_id"] == "s1"

    def test_reads_from_file(self, tmp_path: Path) -> None:
        source = tmp_path / "otel.jsonl"
        source.write_text(
            json.dumps({"attributes": {"mcp.tool.name": "get_file"}}) + "\n", encoding="utf-8"
        )
        sink = tmp_path / "trace.jsonl"
        exit_code = cli.main(["vscode", "capture", "--from", str(source), "--sink", str(sink)])
        assert exit_code == 0
        assert json.loads(sink.read_text(encoding="utf-8").strip())["tool"] == "get_file"

    def test_missing_from_file_exits_two(self, tmp_path: Path) -> None:
        assert cli.main(["vscode", "capture", "--from", str(tmp_path / "nope.jsonl")]) == 2

    def test_redaction_on_by_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sink = tmp_path / "trace.jsonl"
        _feed_stdin(monkeypatch, json.dumps({"tool": "x", "args": {"token": "SECRET"}}))
        cli.main(["vscode", "capture", "--sink", str(sink)])
        assert "SECRET" not in sink.read_text(encoding="utf-8")

    def test_non_tool_event_writes_nothing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sink = tmp_path / "trace.jsonl"
        _feed_stdin(monkeypatch, json.dumps({"type": "model.call"}))
        assert cli.main(["vscode", "capture", "--sink", str(sink)]) == 0
        assert not sink.exists()

    def test_malformed_input_exits_one_without_corrupting_sink(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        sink = tmp_path / "trace.jsonl"
        sink.write_text('{"tool": "existing"}\n', encoding="utf-8")
        _feed_stdin(monkeypatch, "not json{")
        assert cli.main(["vscode", "capture", "--sink", str(sink)]) == 1
        assert "chainweaver:" in capsys.readouterr().err
        assert sink.read_text(encoding="utf-8") == '{"tool": "existing"}\n'


class TestSetupObserve:
    def test_prints_snippet_and_writes_no_file(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = cli.main(["vscode", "setup", "--observe", "--workspace", str(tmp_path)])
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "github.copilot.chat.otel.exporterType" in out
        # observe is guidance-only: no .vscode files are written even without --write
        assert not (tmp_path / ".vscode").exists()

    def test_observe_write_still_writes_no_settings(self, tmp_path: Path) -> None:
        cli.main(["vscode", "setup", "--observe", "--write", "--workspace", str(tmp_path)])
        assert not (tmp_path / ".vscode" / "settings.json").exists()


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
                "vscode",
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
        vscode_dir = tmp_path / ".vscode"
        vscode_dir.mkdir()
        config = vscode_dir / "mcp.json"
        config.write_text(json.dumps({"servers": {"other": {"command": "x"}}}), encoding="utf-8")
        flows = tmp_path / "flows"
        flows.mkdir()
        (flows / "a.flow.yaml").write_text(_flow_yaml("ship_it", "active"), encoding="utf-8")
        exit_code = cli.main(
            [
                "vscode",
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
        assert written["servers"]["other"] == {"command": "x"}
        assert written["servers"]["chainweaver"]["command"] == "chainweaver"
        assert config.with_suffix(".json.bak").is_file()

    def test_write_creates_vscode_dir_when_absent(self, tmp_path: Path) -> None:
        flows = tmp_path / "flows"
        flows.mkdir()
        (flows / "a.flow.yaml").write_text(_flow_yaml("ship_it", "active"), encoding="utf-8")
        exit_code = cli.main(
            [
                "vscode",
                "setup",
                "--flows",
                "--write",
                "--workspace",
                str(tmp_path),
                "--flows-dir",
                str(flows),
            ]
        )
        assert exit_code == 0
        assert (tmp_path / ".vscode" / "mcp.json").is_file()

    def test_collision_fails_unless_allowed(self, tmp_path: Path) -> None:
        flows = tmp_path / "flows"
        flows.mkdir()
        (flows / "r.flow.yaml").write_text(_flow_yaml("read", "active"), encoding="utf-8")
        base = [
            "vscode",
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

    def test_relative_flows_dir_resolved_against_workspace(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # A relative --flows-dir (here the default) must resolve against the
        # workspace, not the process CWD.
        flows = tmp_path / ".chainweaver" / "flows"
        flows.mkdir(parents=True)
        (flows / "a.flow.yaml").write_text(_flow_yaml("ship_it", "active"), encoding="utf-8")
        exit_code = cli.main(
            ["vscode", "setup", "--flows", "--workspace", str(tmp_path), "--json"]
        )
        assert exit_code == 0
        change = json.loads(capsys.readouterr().out)["changes"][0]
        assert "ship_it" in change["exposed_tools"]


class TestSetupArgsContract:
    def test_no_flag_exits_one(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        assert cli.main(["vscode", "setup", "--workspace", str(tmp_path)]) == 1
        assert "--observe" in capsys.readouterr().err

    def test_missing_workspace_exits_two(self, tmp_path: Path) -> None:
        assert cli.main(["vscode", "setup", "--flows", "--workspace", str(tmp_path / "nope")]) == 2


class TestRevert:
    def test_revert_flows_preserves_other_servers(self, tmp_path: Path) -> None:
        vscode_dir = tmp_path / ".vscode"
        vscode_dir.mkdir()
        config = vscode_dir / "mcp.json"
        config.write_text(
            json.dumps({"servers": {"other": {"command": "x"}, "chainweaver": {"command": "y"}}}),
            encoding="utf-8",
        )
        exit_code = cli.main(
            ["vscode", "revert", "--flows", "--write", "--workspace", str(tmp_path)]
        )
        assert exit_code == 0
        written = json.loads(config.read_text(encoding="utf-8"))
        assert written["servers"] == {"other": {"command": "x"}}

    def test_revert_observe_prints_manual_note(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = cli.main(["vscode", "revert", "--observe", "--workspace", str(tmp_path)])
        assert exit_code == 0
        assert "github.copilot.chat.otel" in capsys.readouterr().out
