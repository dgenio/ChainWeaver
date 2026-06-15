"""Tests for the ``chainweaver doctor {vscode,claude,opencode}`` inspectors.

These read-only commands (issues #264 / #270 / #275) inspect a workspace and
report what is configured for the observe → suggest → compile workflow:
the editor's MCP config, whether a ChainWeaver FlowServer is exposed, trace
capture, and discoverable macro-flows. They never modify files.

Exit-code contract: ``0`` when the workspace is inspectable (a missing config
is a *finding*, not a failure) and ``2`` when ``--workspace`` is missing or is
not a directory.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chainweaver import cli


@pytest.fixture(autouse=True)
def _reset_registry() -> None:
    cli.set_default_registry(None)


def _write(path: Path, payload: object) -> None:
    """Write *payload* as JSON to *path*, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _flowserver_spec() -> dict[str, object]:
    return {"command": "chainweaver", "args": ["serve", "flows/", "--tools", "my.tools"]}


# ---------------------------------------------------------------------------
# Shared workspace / exit-code contract
# ---------------------------------------------------------------------------


class TestWorkspaceContract:
    @pytest.mark.parametrize("editor", ["vscode", "claude", "opencode"])
    def test_missing_workspace_exits_two(
        self, editor: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = cli.main(["doctor", editor, "--workspace", str(tmp_path / "nope")])
        captured = capsys.readouterr()
        assert exit_code == 2
        assert "workspace not found" in captured.err

    @pytest.mark.parametrize("editor", ["vscode", "claude", "opencode"])
    def test_workspace_not_a_directory_exits_two(
        self, editor: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        file_path = tmp_path / "afile"
        file_path.write_text("x", encoding="utf-8")
        exit_code = cli.main(["doctor", editor, "--workspace", str(file_path)])
        captured = capsys.readouterr()
        assert exit_code == 2
        assert "not a directory" in captured.err

    @pytest.mark.parametrize("editor", ["vscode", "claude", "opencode"])
    def test_empty_workspace_is_inspectable_exit_zero(
        self, editor: str, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = cli.main(["doctor", editor, "--workspace", str(tmp_path), "--format", "json"])
        captured = capsys.readouterr()
        assert exit_code == 0
        report = json.loads(captured.out)
        assert report["editor"] == editor
        assert report["ok"] is True
        # An empty workspace surfaces a missing MCP config and at least one
        # recommendation, but is not itself a failure.
        assert any(c["status"] == "missing" for c in report["checks"])
        assert report["recommendations"]


# ---------------------------------------------------------------------------
# doctor vscode (#264)
# ---------------------------------------------------------------------------


class TestDoctorVSCode:
    def test_detects_flowserver_and_traces(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(
            tmp_path / ".vscode" / "mcp.json",
            {"servers": {"chainweaver": _flowserver_spec(), "other": {"command": "x"}}},
        )
        (tmp_path / ".chainweaver" / "traces").mkdir(parents=True)
        (tmp_path / ".chainweaver" / "traces" / "agent.jsonl").write_text("{}\n", encoding="utf-8")

        exit_code = cli.main(
            ["doctor", "vscode", "--workspace", str(tmp_path), "--format", "json"]
        )
        report = json.loads(capsys.readouterr().out)
        assert exit_code == 0
        by_name = {c["name"]: c for c in report["checks"]}
        assert "2 MCP server(s)" in by_name["VS Code MCP config"]["detail"]
        assert by_name["ChainWeaver FlowServer"]["status"] == "ok"
        assert by_name["trace capture"]["status"] == "ok"

    def test_missing_flowserver_recommended(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(tmp_path / ".vscode" / "mcp.json", {"servers": {"unrelated": {"command": "x"}}})
        exit_code = cli.main(
            ["doctor", "vscode", "--workspace", str(tmp_path), "--format", "json"]
        )
        report = json.loads(capsys.readouterr().out)
        assert exit_code == 0
        by_name = {c["name"]: c for c in report["checks"]}
        assert by_name["ChainWeaver FlowServer"]["status"] == "missing"
        assert any("FlowServer" in rec for rec in report["recommendations"])

    def test_invalid_json_reported_not_crashed(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        mcp_path = tmp_path / ".vscode" / "mcp.json"
        mcp_path.parent.mkdir(parents=True)
        mcp_path.write_text("{ not json", encoding="utf-8")
        exit_code = cli.main(
            ["doctor", "vscode", "--workspace", str(tmp_path), "--format", "json"]
        )
        report = json.loads(capsys.readouterr().out)
        assert exit_code == 0
        config_check = next(c for c in report["checks"] if c["name"] == "VS Code MCP config")
        assert config_check["status"] == "missing"
        assert "not valid JSON" in config_check["detail"]

    def test_fix_dry_run_emits_proposal_without_writing(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = cli.main(
            ["doctor", "vscode", "--workspace", str(tmp_path), "--fix-dry-run", "--format", "json"]
        )
        report = json.loads(capsys.readouterr().out)
        assert exit_code == 0
        assert report["proposed_changes"], "expected a proposed change under --fix-dry-run"
        # Dry run must not create the config file.
        assert not (tmp_path / ".vscode" / "mcp.json").exists()

    def test_table_output_renders(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = cli.main(["doctor", "vscode", "--workspace", str(tmp_path)])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "ChainWeaver doctor — vscode" in captured.out
        assert "Recommendations:" in captured.out


# ---------------------------------------------------------------------------
# doctor claude (#270)
# ---------------------------------------------------------------------------


class TestDoctorClaude:
    def test_detects_servers_scope_and_hooks(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(tmp_path / ".mcp.json", {"mcpServers": {"chainweaver-flows": _flowserver_spec()}})
        _write(
            tmp_path / ".claude" / "settings.json",
            {"hooks": {"PostToolUse": [{"matcher": "*", "hooks": []}]}},
        )
        exit_code = cli.main(
            ["doctor", "claude", "--workspace", str(tmp_path), "--format", "json"]
        )
        report = json.loads(capsys.readouterr().out)
        assert exit_code == 0
        by_name = {c["name"]: c for c in report["checks"]}
        assert by_name["ChainWeaver FlowServer"]["status"] == "ok"
        assert by_name["observe hooks"]["status"] == "ok"
        assert ".mcp.json" in by_name["config scope"]["detail"]

    def test_missing_hooks_recommended(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(tmp_path / ".mcp.json", {"mcpServers": {}})
        exit_code = cli.main(
            ["doctor", "claude", "--workspace", str(tmp_path), "--format", "json"]
        )
        report = json.loads(capsys.readouterr().out)
        assert exit_code == 0
        by_name = {c["name"]: c for c in report["checks"]}
        assert by_name["observe hooks"]["status"] == "missing"
        assert any("PostToolUse" in rec for rec in report["recommendations"])


# ---------------------------------------------------------------------------
# doctor opencode (#275)
# ---------------------------------------------------------------------------


class TestDoctorOpenCode:
    def test_detects_servers_plugin_and_collision_note(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(tmp_path / "opencode.json", {"mcp": {"chainweaver": _flowserver_spec()}})
        (tmp_path / ".opencode" / "plugin").mkdir(parents=True)
        (tmp_path / ".opencode" / "plugin" / "cw.js").write_text("// plugin\n", encoding="utf-8")
        # A discoverable flow triggers the tool-name-collision reminder.
        (tmp_path / "etl.flow.yaml").write_text(
            "type: Flow\nname: etl\nversion: '0.1.0'\ndescription: d\nsteps: []\n",
            encoding="utf-8",
        )
        exit_code = cli.main(
            ["doctor", "opencode", "--workspace", str(tmp_path), "--format", "json"]
        )
        report = json.loads(capsys.readouterr().out)
        assert exit_code == 0
        by_name = {c["name"]: c for c in report["checks"]}
        assert by_name["ChainWeaver FlowServer"]["status"] == "ok"
        assert by_name["OpenCode plugin"]["status"] == "ok"
        assert by_name["macro-flows"]["status"] == "ok"
        assert "tool-name collisions" in by_name

    def test_jsonc_config_with_comments_parses(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        (tmp_path / "opencode.jsonc").write_text(
            '{\n  // project MCP servers\n  "mcp": {"chainweaver": '
            '{"command": "chainweaver"}}\n}\n',
            encoding="utf-8",
        )
        exit_code = cli.main(
            ["doctor", "opencode", "--workspace", str(tmp_path), "--format", "json"]
        )
        report = json.loads(capsys.readouterr().out)
        assert exit_code == 0
        by_name = {c["name"]: c for c in report["checks"]}
        assert by_name["OpenCode MCP config"]["status"] == "ok"
        assert by_name["ChainWeaver FlowServer"]["status"] == "ok"

    def test_missing_plugin_recommended(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write(tmp_path / "opencode.json", {"mcp": {}})
        exit_code = cli.main(
            ["doctor", "opencode", "--workspace", str(tmp_path), "--format", "json"]
        )
        report = json.loads(capsys.readouterr().out)
        assert exit_code == 0
        by_name = {c["name"]: c for c in report["checks"]}
        assert by_name["OpenCode plugin"]["status"] == "missing"
        assert any("plugin" in rec for rec in report["recommendations"])
