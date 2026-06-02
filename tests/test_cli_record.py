"""Tests for the ``chainweaver record`` CLI command (issue #226)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from chainweaver import cli
from chainweaver.serialization import flow_from_yaml


def _write_trace(path: Path, lines: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")


def _repeated_trace(times: int) -> list[dict[str, object]]:
    """A ``fetch -> validate -> transform`` sequence repeated *times* times."""
    lines: list[dict[str, object]] = []
    for i in range(times):
        tid = f"req-{i}"
        lines.append(
            {"trace_id": tid, "tool": "fetch", "inputs": {"url": "u"}, "outputs": {"body": "b"}}
        )
        lines.append(
            {"trace_id": tid, "tool": "validate", "inputs": {"body": "b"}, "outputs": {"ok": True}}
        )
        lines.append(
            {"trace_id": tid, "tool": "transform", "inputs": {"body": "b"}, "outputs": {"out": 1}}
        )
    return lines


class TestRecordHappyPath:
    def test_table_dry_run_lists_candidate(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = tmp_path / "trace.jsonl"
        _write_trace(path, _repeated_trace(3))
        exit_code = cli.main(["record", str(path)])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "suggested__fetch__validate__transform" in captured.out
        assert "dry run" in captured.out

    def test_json_output_shape(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        path = tmp_path / "trace.jsonl"
        _write_trace(path, _repeated_trace(4))
        exit_code = cli.main(["record", str(path), "--format", "json"])
        captured = capsys.readouterr()
        assert exit_code == 0
        payload = json.loads(captured.out)
        assert payload["traces_analyzed"] == 4
        assert payload["candidate_count"] == 1
        top = payload["candidates"][0]
        assert top["flow_name"] == "suggested__fetch__validate__transform"
        assert top["tools"] == ["fetch", "validate", "transform"]
        assert top["occurrences"] == 4
        assert top["estimated_llm_calls_avoided"] == 12
        assert top["output_path"] is None

    def test_writes_valid_flow_files(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = tmp_path / "trace.jsonl"
        _write_trace(path, _repeated_trace(3))
        out_dir = tmp_path / "out"
        exit_code = cli.main(["record", str(path), "--output-dir", str(out_dir)])
        capsys.readouterr()
        assert exit_code == 0
        written = list(out_dir.glob("*.flow.yaml"))
        assert len(written) == 1
        # The emitted file round-trips back into a Flow.
        flow = flow_from_yaml(written[0].read_text(encoding="utf-8"))
        assert flow.name == "suggested__fetch__validate__transform"
        assert [s.tool_name for s in flow.steps] == ["fetch", "validate", "transform"]

    def test_ranking_prefers_higher_savings(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # A short 2-tool pattern seen 5x (savings 10) vs a 3-tool pattern seen
        # 4x (savings 12): the longer, higher-savings flow ranks first.
        lines: list[dict[str, object]] = []
        for i in range(5):
            lines.append(
                {"trace_id": f"s{i}", "tool": "a", "inputs": {"x": 1}, "outputs": {"y": 1}}
            )
            lines.append(
                {"trace_id": f"s{i}", "tool": "b", "inputs": {"y": 1}, "outputs": {"z": 1}}
            )
        for i in range(4):
            lines.append(
                {"trace_id": f"l{i}", "tool": "p", "inputs": {"x": 1}, "outputs": {"q": 1}}
            )
            lines.append(
                {"trace_id": f"l{i}", "tool": "q", "inputs": {"q": 1}, "outputs": {"r": 1}}
            )
            lines.append(
                {"trace_id": f"l{i}", "tool": "r", "inputs": {"r": 1}, "outputs": {"s": 1}}
            )
        path = tmp_path / "trace.jsonl"
        _write_trace(path, lines)
        cli.main(["record", str(path), "--format", "json"])
        payload = json.loads(capsys.readouterr().out)
        names = [c["flow_name"] for c in payload["candidates"]]
        assert names[0] == "suggested__p__q__r"  # savings 12 > 10

    def test_no_candidates_message(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = tmp_path / "trace.jsonl"
        _write_trace(path, _repeated_trace(1))
        exit_code = cli.main(["record", str(path)])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "No candidate flows" in captured.out


class TestRecordTraceFormat:
    def test_lines_without_trace_id_join_default_trace(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        # No trace_id anywhere -> one big default trace; a 2-gram appears
        # repeatedly within it.
        lines: list[dict[str, object]] = []
        for _ in range(3):
            lines.append({"tool": "a", "inputs": {}, "outputs": {}})
            lines.append({"tool": "b", "inputs": {}, "outputs": {}})
        path = tmp_path / "trace.jsonl"
        _write_trace(path, lines)
        cli.main(["record", str(path), "--format", "json"])
        payload = json.loads(capsys.readouterr().out)
        assert payload["traces_analyzed"] == 1
        assert any(c["tools"] == ["a", "b"] for c in payload["candidates"])

    def test_tool_name_alias_accepted(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        lines: list[dict[str, object]] = [
            {"trace_id": f"t{i}", "tool_name": tool, "inputs": {}, "outputs": {}}
            for i in range(3)
            for tool in ("a", "b")
        ]
        path = tmp_path / "trace.jsonl"
        _write_trace(path, lines)
        exit_code = cli.main(["record", str(path), "--format", "json"])
        payload = json.loads(capsys.readouterr().out)
        assert exit_code == 0
        assert any(c["tools"] == ["a", "b"] for c in payload["candidates"])


class TestRecordErrors:
    def test_malformed_json_line_exits_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = tmp_path / "trace.jsonl"
        path.write_text('{"tool": "a"}\nnot json\n', encoding="utf-8")
        exit_code = cli.main(["record", str(path)])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "line 2" in captured.err

    def test_missing_tool_field_exits_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = tmp_path / "trace.jsonl"
        path.write_text('{"inputs": {}}\n', encoding="utf-8")
        exit_code = cli.main(["record", str(path)])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "missing or empty 'tool'" in captured.err

    def test_missing_file_exits_2(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exit_code = cli.main(["record", str(tmp_path / "nope.jsonl")])
        captured = capsys.readouterr()
        assert exit_code == 2
        assert "file not found" in captured.err

    def test_invalid_threshold_exits_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = tmp_path / "trace.jsonl"
        _write_trace(path, _repeated_trace(3))
        exit_code = cli.main(["record", str(path), "--min-occurrences", "0"])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "min_occurrences must be >= 1" in captured.err
