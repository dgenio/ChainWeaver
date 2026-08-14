"""CLI coverage for imported trace redaction (#376)."""

from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from chainweaver import cli

_RUNNER = CliRunner()
_CANARY = "sk-ABCDEFGHIJKLMNOPQRSTUVWX"


def _write_trace(path: Path) -> None:
    records: list[dict] = []
    for index in range(3):
        records.extend(
            [
                {
                    "session_id": f"session-{index}",
                    "tool": "read_file",
                    "args": {"path": f"/private/{index}", "token": _CANARY},
                    "outputs": {"content": "x"},
                    "result_status": "ok",
                },
                {
                    "session_id": f"session-{index}",
                    "tool": "summarize",
                    "args": {"content": "x", "authorization": _CANARY},
                    "outputs": {"summary": "y"},
                    "result_status": "ok",
                },
            ]
        )
    path.write_text(
        "\n".join(json.dumps(record) for record in records),
        encoding="utf-8",
    )


def test_mine_accepts_recommended_redaction(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    _write_trace(trace)

    result = _RUNNER.invoke(
        cli.app,
        ["traces", "mine", str(trace), "--redact", "recommended", "--format", "json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["redaction"] == "recommended"
    assert payload["candidate_count"] >= 1
    assert _CANARY not in result.stdout


def test_draft_flow_artifacts_do_not_contain_canary(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    output = tmp_path / "drafts"
    _write_trace(trace)

    result = _RUNNER.invoke(
        cli.app,
        [
            "traces",
            "draft-flows",
            str(trace),
            "--redact",
            "recommended",
            "--output-dir",
            str(output),
        ],
    )

    assert result.exit_code == 0, result.output
    files = list(output.iterdir())
    assert files
    assert all(_CANARY not in path.read_text(encoding="utf-8") for path in files)


def test_invalid_redaction_preset_is_rejected(tmp_path: Path) -> None:
    trace = tmp_path / "trace.jsonl"
    _write_trace(trace)

    result = _RUNNER.invoke(
        cli.app,
        ["traces", "mine", str(trace), "--redact", "unknown"],
    )

    assert result.exit_code == 1
    assert "--redact must be one of" in result.output
