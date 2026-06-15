"""Tests for the ``chainweaver traces`` CLI group and ``doctor --preflight``.

Covers the coding-agent macro-flow surface (#254, #256, #257, #266, #267) and
the structural preflight checker (#314).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from chainweaver import cli
from chainweaver.flow import Flow, FlowStep
from chainweaver.serialization import flow_to_yaml


def _write_trace(path: Path, lines: list[dict[str, object]]) -> None:
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", encoding="utf-8")


def _repeated_agent_trace(sessions: int) -> list[dict[str, object]]:
    """``fs.search -> fs.read`` repeated across *sessions* sessions, with model calls."""
    lines: list[dict[str, object]] = []
    for index in range(sessions):
        sid = f"s{index}"
        lines.append(
            {"session_id": sid, "event": "model_call", "input_tokens": 1000, "output_tokens": 100}
        )
        lines.append(
            {
                "session_id": sid,
                "event": "tool_call",
                "tool": "fs.search",
                "args": {"q": "x"},
                "result_status": "ok",
                "output_keys": ["hits"],
            }
        )
        lines.append(
            {
                "session_id": sid,
                "event": "tool_call",
                "tool": "fs.read",
                "args": {"path": "p"},
                "result_status": "ok",
            }
        )
    return lines


class TestTracesMine:
    def test_table_report(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        path = tmp_path / "trace.jsonl"
        _write_trace(path, _repeated_agent_trace(4))
        exit_code = cli.main(["traces", "mine", str(path)])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "fs.search → fs.read" in captured.out
        assert "safe_to_draft" in captured.out

    def test_json_output(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        path = tmp_path / "trace.jsonl"
        _write_trace(path, _repeated_agent_trace(4))
        exit_code = cli.main(["traces", "mine", str(path), "--format", "json"])
        captured = capsys.readouterr()
        assert exit_code == 0
        payload = json.loads(captured.out)
        assert payload["candidate_count"] >= 1
        first = payload["candidates"][0]
        assert first["sequence"] == ["fs.search", "fs.read"]
        assert first["support"] == 4

    def test_limit(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        path = tmp_path / "trace.jsonl"
        _write_trace(path, _repeated_agent_trace(4))
        cli.main(["traces", "mine", str(path), "--limit", "1"])
        captured = capsys.readouterr()
        assert "Candidate 2" not in captured.out

    def test_missing_file_exit_2(self, tmp_path: Path) -> None:
        assert cli.main(["traces", "mine", str(tmp_path / "nope.jsonl")]) == 2

    def test_malformed_trace_exit_1(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        path = tmp_path / "bad.jsonl"
        path.write_text("{not json}\n", encoding="utf-8")
        assert cli.main(["traces", "mine", str(path)]) == 1


class TestTracesDraftFlows:
    def test_dry_run_reports(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        path = tmp_path / "trace.jsonl"
        _write_trace(path, _repeated_agent_trace(4))
        exit_code = cli.main(["traces", "draft-flows", str(path)])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "draft__fs_search__fs_read" in captured.out

    def test_writes_flow_and_sidecar(self, tmp_path: Path) -> None:
        path = tmp_path / "trace.jsonl"
        _write_trace(path, _repeated_agent_trace(4))
        out_dir = tmp_path / "drafts"
        exit_code = cli.main(["traces", "draft-flows", str(path), "--output-dir", str(out_dir)])
        assert exit_code == 0
        flow_file = out_dir / "draft__fs_search__fs_read.flow.yaml"
        sidecar = out_dir / "draft__fs_search__fs_read.json"
        assert flow_file.is_file()
        assert sidecar.is_file()
        meta = json.loads(sidecar.read_text(encoding="utf-8"))
        assert meta["sidecar"]["sequence"] == ["fs.search", "fs.read"]

    def test_json_output(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        path = tmp_path / "trace.jsonl"
        _write_trace(path, _repeated_agent_trace(4))
        cli.main(["traces", "draft-flows", str(path), "--format", "json"])
        captured = capsys.readouterr()
        payload = json.loads(captured.out)
        assert payload["draft_count"] >= 1

    def test_no_candidates(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        path = tmp_path / "trace.jsonl"
        _write_trace(path, [{"session_id": "s1", "tool": "lonely", "args": {}}])
        exit_code = cli.main(["traces", "draft-flows", str(path)])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "No draft flows" in captured.out


class TestTracesBacktest:
    def _write_flow(self, path: Path) -> None:
        flow = Flow(
            name="repo_context_pack",
            description="draft",
            steps=[
                FlowStep(tool_name="fs.search", input_mapping={"q": "q"}),
                FlowStep(tool_name="fs.read", input_mapping={"path": "path"}),
            ],
        )
        path.write_text(flow_to_yaml(flow), encoding="utf-8")

    def test_all_pass_exit_0(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        flow_file = tmp_path / "f.flow.yaml"
        trace = tmp_path / "trace.jsonl"
        self._write_flow(flow_file)
        _write_trace(trace, _repeated_agent_trace(2))
        exit_code = cli.main(["traces", "backtest", str(flow_file), "--trace", str(trace)])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "produced expected output: 2" in captured.out

    def test_mismatch_exit_1(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        flow_file = tmp_path / "f.flow.yaml"
        trace = tmp_path / "trace.jsonl"
        self._write_flow(flow_file)
        # 'fs.read' here is missing its 'path' input -> shape mismatch.
        _write_trace(
            trace,
            [
                {"session_id": "s1", "tool": "fs.search", "args": {"q": "x"}},
                {"session_id": "s1", "tool": "fs.read", "args": {}},
            ],
        )
        exit_code = cli.main(["traces", "backtest", str(flow_file), "--trace", str(trace)])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "missing input field" in captured.out

    def test_json(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        flow_file = tmp_path / "f.flow.yaml"
        trace = tmp_path / "trace.jsonl"
        self._write_flow(flow_file)
        _write_trace(trace, _repeated_agent_trace(2))
        cli.main(["traces", "backtest", str(flow_file), "--trace", str(trace), "--format", "json"])
        payload = json.loads(capsys.readouterr().out)
        assert payload["flow_name"] == "repo_context_pack"
        assert payload["examples_tested"] == 2


# ---------------------------------------------------------------------------
# doctor --preflight (#314)
# ---------------------------------------------------------------------------


_TOOLS_MODULE = """
from __future__ import annotations
from typing import Any
from pydantic import BaseModel
from chainweaver.tools import Tool


class SearchIn(BaseModel):
    q: str


class SearchOut(BaseModel):
    hits: str


class ReadIn(BaseModel):
    hits: str
    path: str


class ReadOut(BaseModel):
    content: str


def _search_fn(inp: SearchIn) -> dict[str, Any]:
    return {"hits": "h"}


def _read_fn(inp: ReadIn) -> dict[str, Any]:
    return {"content": "c"}


search = Tool(name="fs.search", description="s", input_schema=SearchIn,
              output_schema=SearchOut, fn=_search_fn)
read_file = Tool(name="fs.read", description="r", input_schema=ReadIn,
                 output_schema=ReadOut, fn=_read_fn)
"""


@pytest.fixture
def _tools_module(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    name = "preflight_toolmod"
    (tmp_path / f"{name}.py").write_text(_TOOLS_MODULE, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop(name, None)
    return name


def _write_flow(path: Path, flow: Flow) -> None:
    path.write_text(flow_to_yaml(flow), encoding="utf-8")


class TestDoctorPreflight:
    def test_requires_a_mode(self, tmp_path: Path) -> None:
        flow_file = tmp_path / "f.flow.yaml"
        _write_flow(flow_file, Flow(name="f", description="d", steps=[FlowStep(tool_name="a")]))
        assert cli.main(["doctor", "flow", str(flow_file)]) == 1

    def test_both_modes_exit_2(self, tmp_path: Path) -> None:
        flow_file = tmp_path / "f.flow.yaml"
        _write_flow(flow_file, Flow(name="f", description="d", steps=[FlowStep(tool_name="a")]))
        assert cli.main(["doctor", "flow", str(flow_file), "--check-drift", "--preflight"]) == 2

    def test_valid_flow_is_ok(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], _tools_module: str
    ) -> None:
        flow_file = tmp_path / "ok.flow.yaml"
        _write_flow(
            flow_file,
            Flow(
                name="ok",
                description="d",
                steps=[
                    FlowStep(tool_name="fs.search", input_mapping={"q": "q"}),
                    FlowStep(tool_name="fs.read", input_mapping={"hits": "hits"}),
                ],
            ),
        )
        exit_code = cli.main(
            ["doctor", "flow", str(flow_file), "--preflight", "--tools", _tools_module]
        )
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "all 1 flow(s) ok" in captured.out

    def test_missing_tool_flagged(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], _tools_module: str
    ) -> None:
        flow_file = tmp_path / "bad.flow.yaml"
        _write_flow(
            flow_file,
            Flow(name="bad", description="d", steps=[FlowStep(tool_name="ghost")]),
        )
        exit_code = cli.main(
            ["doctor", "flow", str(flow_file), "--preflight", "--tools", _tools_module]
        )
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "missing_tool" in captured.out

    def test_unresolved_mapping_flagged(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], _tools_module: str
    ) -> None:
        flow_file = tmp_path / "unresolved.flow.yaml"
        _write_flow(
            flow_file,
            Flow(
                name="unresolved",
                description="d",
                steps=[
                    FlowStep(tool_name="fs.search", input_mapping={"q": "q"}),
                    FlowStep(tool_name="fs.read", input_mapping={"hits": "nonexistent"}),
                ],
            ),
        )
        exit_code = cli.main(
            ["doctor", "flow", str(flow_file), "--preflight", "--tools", _tools_module]
        )
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "unresolved_mapping" in captured.out

    def test_json_output(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], _tools_module: str
    ) -> None:
        flow_file = tmp_path / "ok.flow.yaml"
        _write_flow(
            flow_file,
            Flow(name="ok", description="d", steps=[FlowStep(tool_name="fs.search")]),
        )
        cli.main(
            [
                "doctor",
                "flow",
                str(flow_file),
                "--preflight",
                "--tools",
                _tools_module,
                "--format",
                "json",
            ]
        )
        payload = json.loads(capsys.readouterr().out)
        assert payload["flow_count"] == 1
        assert payload["issue_count"] == 0

    def test_first_step_validated_against_input_schema(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], _tools_module: str
    ) -> None:
        # SearchIn declares field 'q'; mapping the first step's source from a
        # field the input schema does not declare must be flagged.
        flow_file = tmp_path / "schema.flow.yaml"
        _write_flow(
            flow_file,
            Flow(
                name="schema",
                description="d",
                input_schema_ref=f"{_tools_module}:SearchIn",
                steps=[FlowStep(tool_name="fs.search", input_mapping={"q": "bogus"})],
            ),
        )
        exit_code = cli.main(
            ["doctor", "flow", str(flow_file), "--preflight", "--tools", _tools_module]
        )
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "unresolved_mapping" in captured.out

    def test_first_step_ok_when_source_in_input_schema(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str], _tools_module: str
    ) -> None:
        flow_file = tmp_path / "schema_ok.flow.yaml"
        _write_flow(
            flow_file,
            Flow(
                name="schema_ok",
                description="d",
                input_schema_ref=f"{_tools_module}:SearchIn",
                steps=[FlowStep(tool_name="fs.search", input_mapping={"q": "q"})],
            ),
        )
        exit_code = cli.main(
            ["doctor", "flow", str(flow_file), "--preflight", "--tools", _tools_module]
        )
        assert exit_code == 0
