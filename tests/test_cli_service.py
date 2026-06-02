"""Tests for the ``chainweaver service`` CLI command (issue #101)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chainweaver import cli


def _write_trace(path: Path, times: int, *tools: str) -> None:
    lines: list[str] = []
    for i in range(times):
        for tool in tools:
            lines.append(
                json.dumps(
                    {"trace_id": f"t{i}", "tool": tool, "inputs": {"x": 1}, "outputs": {"y": 1}}
                )
            )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class TestServiceCommand:
    def test_trace_pass_reports_proposal(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = tmp_path / "trace.jsonl"
        _write_trace(path, 3, "fetch", "validate")
        exit_code = cli.main(["service", "--trace", str(path), "--min-occurrences", "2"])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "suggested__fetch__validate" in captured.out
        assert "traces analyzed:   3" in captured.out

    def test_json_output_shape(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        path = tmp_path / "trace.jsonl"
        _write_trace(path, 3, "fetch", "validate")
        exit_code = cli.main(["service", "--trace", str(path), "--format", "json"])
        captured = capsys.readouterr()
        assert exit_code == 0
        payload = json.loads(captured.out)
        assert payload["traces_analyzed"] == 3
        assert payload["proposal_count"] == 1
        assert payload["proposals"][0]["flow_name"] == "suggested__fetch__validate"
        assert payload["proposals"][0]["source"] == "observer"
        assert payload["metrics"]["patterns_detected"] >= 1

    def test_tools_pass_uses_static_analyzer(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        repo_root = Path(__file__).resolve().parent.parent
        monkeypatch.syspath_prepend(str(repo_root))
        exit_code = cli.main(
            ["service", "--tools", "examples.simple_linear_flow", "--format", "json"]
        )
        captured = capsys.readouterr()
        assert exit_code == 0
        payload = json.loads(captured.out)
        assert payload["metrics"]["tools_monitored"] >= 2
        assert any(p["source"] == "analyzer" for p in payload["proposals"])

    def test_no_proposals_message(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = tmp_path / "trace.jsonl"
        _write_trace(path, 1, "fetch", "validate")
        exit_code = cli.main(["service", "--trace", str(path)])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "No new proposals." in captured.out

    def test_missing_trace_file_exits_2(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = cli.main(["service", "--trace", str(tmp_path / "nope.jsonl")])
        captured = capsys.readouterr()
        assert exit_code == 2
        assert "file not found" in captured.err

    def test_malformed_trace_exits_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = tmp_path / "trace.jsonl"
        path.write_text("not json\n", encoding="utf-8")
        exit_code = cli.main(["service", "--trace", str(path)])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "line 1" in captured.err
