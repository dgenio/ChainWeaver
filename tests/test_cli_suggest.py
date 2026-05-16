"""Tests for ``suggest_optimizations`` + the ``chainweaver suggest`` CLI (#155)."""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from chainweaver import (
    Flow,
    FlowStep,
    Suggestion,
    Tool,
    cli,
    suggest_optimizations,
)
from chainweaver.executor import ExecutionResult, StepRecord

# ---------------------------------------------------------------------------
# Shared schemas
# ---------------------------------------------------------------------------


class NumberIn(BaseModel):
    number: int


class ValueOut(BaseModel):
    value: int


class ValueIn(BaseModel):
    value: int


class FormattedOut(BaseModel):
    result: str


def _identity(inp: BaseModel) -> dict[str, Any]:
    return inp.model_dump()


def _double_tool() -> Tool:
    return Tool(
        name="double",
        description="Doubles.",
        input_schema=NumberIn,
        output_schema=ValueOut,
        fn=_identity,
    )


def _format_tool() -> Tool:
    return Tool(
        name="format_result",
        description="Formats.",
        input_schema=ValueIn,
        output_schema=FormattedOut,
        fn=_identity,
    )


# ---------------------------------------------------------------------------
# Programmatic suggest_optimizations()
# ---------------------------------------------------------------------------


class TestSuggestStatic:
    def test_clean_flow_has_no_suggestions(self) -> None:
        flow = Flow(
            name="clean",
            version="0.1.0",
            description="Clean.",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "number"}),
                FlowStep(tool_name="format_result", input_mapping={"value": "value"}),
            ],
        )
        assert suggest_optimizations(flow) == []

    def test_cw001_flagged_for_empty_mapping(self) -> None:
        flow = Flow(
            name="wasteful",
            version="0.1.0",
            description="Wasteful mapping.",
            steps=[
                FlowStep(tool_name="double"),
                FlowStep(tool_name="format_result", input_mapping={"value": "value"}),
            ],
        )
        suggestions = suggest_optimizations(flow)
        codes = [s.code for s in suggestions]
        assert "CW001" in codes
        cw001 = next(s for s in suggestions if s.code == "CW001")
        assert cw001.step_index == 0
        assert cw001.tool_name == "double"

    def test_cw002_flagged_for_disjoint_io(self) -> None:
        # double outputs {value}; double inputs {number}. Output ∩ Input = ∅
        # so an adjacent (double → double) pair is DAG-eligible. CW002 now
        # requires tools because the check needs schemas.
        flow = Flow(
            name="parallelizable",
            version="0.1.0",
            description="Two independent steps.",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "left"}),
                FlowStep(tool_name="double", input_mapping={"number": "right"}),
            ],
        )
        # Without tools: no CW002 (we can't tell).
        without_tools = suggest_optimizations(flow)
        assert all(s.code != "CW002" for s in without_tools)
        # With tools: CW002 fires.
        with_tools = suggest_optimizations(flow, tools=[_double_tool()])
        codes = [s.code for s in with_tools]
        assert "CW002" in codes
        cw002 = next(s for s in with_tools if s.code == "CW002")
        assert cw002.step_index == 0

    def test_cw003_requires_tools(self) -> None:
        # Without tools: no CW003.
        flow = Flow(
            name="dead",
            version="0.1.0",
            description="Step 0 output is unread.",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "number"}),
                FlowStep(tool_name="format_result", input_mapping={"value": "other"}),
            ],
        )
        no_tools = suggest_optimizations(flow)
        assert all(s.code != "CW003" for s in no_tools)

        # With tools: CW003 fires because 'double' outputs 'value' but the next
        # step reads 'other'.
        with_tools = suggest_optimizations(flow, tools=[_double_tool(), _format_tool()])
        codes = [s.code for s in with_tools]
        assert "CW003" in codes
        cw003 = next(s for s in with_tools if s.code == "CW003")
        assert cw003.step_index == 0

    def test_dagflow_returns_no_suggestions(self) -> None:
        from chainweaver.flow import DAGFlow, DAGFlowStep

        dag = DAGFlow(
            name="dag",
            version="0.1.0",
            description=".",
            steps=[
                DAGFlowStep(tool_name="double", step_id="A", depends_on=[]),
                DAGFlowStep(tool_name="format_result", step_id="B", depends_on=["A"]),
            ],
        )
        assert suggest_optimizations(dag) == []


# ---------------------------------------------------------------------------
# Cacheable-step (CW004) — requires traces
# ---------------------------------------------------------------------------


def _make_trace(
    *,
    flow_name: str,
    outputs_per_step: list[dict[str, Any]],
    trace_id: str,
) -> ExecutionResult:
    now = datetime(2026, 5, 16, tzinfo=timezone.utc)
    log = [
        StepRecord(
            step_index=i,
            tool_name=f"tool_{i}",
            inputs={},
            outputs=out,
            success=True,
            started_at=now,
            ended_at=now,
            duration_ms=1.0,
        )
        for i, out in enumerate(outputs_per_step)
    ]
    return ExecutionResult(
        flow_name=flow_name,
        success=True,
        final_output=outputs_per_step[-1] if outputs_per_step else None,
        execution_log=log,
        trace_id=trace_id,
        started_at=now,
        ended_at=now,
        total_duration_ms=10.0,
        initial_input={},
    )


class TestSuggestCacheable:
    def test_cw004_fires_on_identical_outputs(self) -> None:
        flow = Flow(
            name="cachey",
            version="0.1.0",
            description=".",
            steps=[
                FlowStep(tool_name="tool_0", input_mapping={"x": "x"}),
                FlowStep(tool_name="tool_1", input_mapping={"y": "y"}),
            ],
        )
        # Three traces; step 0 output identical, step 1 differs.
        traces = [
            _make_trace(
                flow_name="cachey",
                outputs_per_step=[{"value": 1}, {"other": 10}],
                trace_id=f"t{i}",
            )
            for i in range(3)
        ]
        # Mutate step 1 outputs so they differ across traces.
        traces[1].execution_log[1].outputs = {"other": 11}
        traces[2].execution_log[1].outputs = {"other": 12}
        suggestions = suggest_optimizations(flow, traces=traces)
        cw004 = [s for s in suggestions if s.code == "CW004"]
        assert len(cw004) == 1
        assert cw004[0].step_index == 0
        assert cw004[0].tool_name == "tool_0"

    def test_cw004_needs_two_or_more_traces(self) -> None:
        flow = Flow(
            name="one_trace",
            version="0.1.0",
            description=".",
            steps=[FlowStep(tool_name="tool_0", input_mapping={"x": "x"})],
        )
        one_trace = [
            _make_trace(
                flow_name="one_trace",
                outputs_per_step=[{"value": 1}],
                trace_id="t0",
            )
        ]
        assert all(s.code != "CW004" for s in suggest_optimizations(flow, traces=one_trace))


# ---------------------------------------------------------------------------
# CLI surface
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_registry() -> None:
    cli.set_default_registry(None)


def _write_flow(path: Path, flow: Flow) -> None:
    path.write_text(flow.to_yaml(), encoding="utf-8")


def _write_trace(path: Path, result: ExecutionResult) -> None:
    path.write_text(result.model_dump_json(), encoding="utf-8")


def _write_tools_module(dir_path: Path, name: str) -> str:
    module_name = f"suggestmod_{name}_{dir_path.stem.replace('.', '_')}"
    module_path = dir_path / f"{module_name}.py"
    module_path.write_text(
        "from __future__ import annotations\n"
        "from typing import Any\n"
        "from pydantic import BaseModel\n"
        "from chainweaver import Tool\n"
        "\n"
        "class _NumberInput(BaseModel):\n"
        "    number: int\n"
        "\n"
        "class _ValueOutput(BaseModel):\n"
        "    value: int\n"
        "\n"
        "class _ValueInput(BaseModel):\n"
        "    value: int\n"
        "\n"
        "class _FormattedOutput(BaseModel):\n"
        "    result: str\n"
        "\n"
        "def _double_fn(inp: _NumberInput) -> dict[str, Any]:\n"
        "    return {'value': inp.number * 2}\n"
        "\n"
        "def _format_fn(inp: _ValueInput) -> dict[str, Any]:\n"
        "    return {'result': str(inp.value)}\n"
        "\n"
        "double = Tool(name='double', description='.', "
        "input_schema=_NumberInput, output_schema=_ValueOutput, fn=_double_fn)\n"
        "format_result = Tool(name='format_result', description='.', "
        "input_schema=_ValueInput, output_schema=_FormattedOutput, fn=_format_fn)\n",
        encoding="utf-8",
    )
    return module_name


@pytest.fixture()
def _module_sys_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.syspath_prepend(str(tmp_path))
    for key in list(sys.modules):
        if key.startswith("suggestmod_"):
            sys.modules.pop(key, None)
    return tmp_path


class TestSuggestCLI:
    def test_clean_flow_table_says_no_suggestions(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        flow = Flow(
            name="clean",
            version="0.1.0",
            description=".",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "number"}),
                FlowStep(tool_name="format_result", input_mapping={"value": "value"}),
            ],
        )
        path = tmp_path / "clean.flow.yaml"
        _write_flow(path, flow)
        exit_code = cli.main(["suggest", str(path)])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "No suggestions" in captured.out

    def test_cw001_table_output(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        flow = Flow(
            name="wasteful",
            version="0.1.0",
            description=".",
            steps=[FlowStep(tool_name="double")],
        )
        path = tmp_path / "w.flow.yaml"
        _write_flow(path, flow)
        exit_code = cli.main(["suggest", str(path)])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "CW001" in captured.out
        assert "wasteful-passthrough" in captured.out
        assert "double" in captured.out

    def test_json_output_shape(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        flow = Flow(
            name="wasteful",
            version="0.1.0",
            description=".",
            steps=[FlowStep(tool_name="double")],
        )
        path = tmp_path / "w.flow.yaml"
        _write_flow(path, flow)
        exit_code = cli.main(["suggest", str(path), "--format", "json"])
        captured = capsys.readouterr()
        assert exit_code == 0
        payload = json.loads(captured.out)
        assert payload["flow_name"] == "wasteful"
        assert payload["suggestion_count"] == 1
        assert payload["suggestions"][0]["code"] == "CW001"
        assert payload["suggestions"][0]["title"] == "wasteful-passthrough"

    def test_with_tools_enables_cw003(
        self,
        _module_sys_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Dead-step flow: step 0 outputs 'value', step 1 reads 'other' (so nothing
        # reads step 0's output).
        flow = Flow(
            name="dead",
            version="0.1.0",
            description=".",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "number"}),
                FlowStep(tool_name="format_result", input_mapping={"value": "other"}),
            ],
        )
        path = _module_sys_path / "dead.flow.yaml"
        _write_flow(path, flow)
        module = _write_tools_module(_module_sys_path, "two")
        exit_code = cli.main(["suggest", str(path), "--tools", module, "--format", "json"])
        captured = capsys.readouterr()
        assert exit_code == 0
        payload = json.loads(captured.out)
        codes = [s["code"] for s in payload["suggestions"]]
        assert "CW003" in codes

    def test_with_traces_enables_cw004(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        flow = Flow(
            name="cachey",
            version="0.1.0",
            description=".",
            steps=[
                FlowStep(tool_name="tool_0", input_mapping={"x": "x"}),
                FlowStep(tool_name="tool_1", input_mapping={"y": "y"}),
            ],
        )
        flow_path = tmp_path / "c.flow.yaml"
        _write_flow(flow_path, flow)
        # Three traces with identical step 0 outputs.
        trace_paths: list[str] = []
        for i in range(3):
            tp = tmp_path / f"t{i}.json"
            outputs = [{"value": 1}, {"other": i}]
            _write_trace(
                tp, _make_trace(flow_name="cachey", outputs_per_step=outputs, trace_id=f"t{i}")
            )
            trace_paths.append(str(tp))
        exit_code = cli.main(
            [
                "suggest",
                str(flow_path),
                "--trace",
                trace_paths[0],
                "--trace",
                trace_paths[1],
                "--trace",
                trace_paths[2],
                "--format",
                "json",
            ]
        )
        captured = capsys.readouterr()
        assert exit_code == 0
        payload = json.loads(captured.out)
        codes = [s["code"] for s in payload["suggestions"]]
        assert "CW004" in codes

    def test_missing_flow_file_returns_two(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        exit_code = cli.main(["suggest", str(tmp_path / "nope.flow.yaml")])
        captured = capsys.readouterr()
        assert exit_code == 2
        assert "file not found" in captured.err

    def test_malformed_flow_returns_one(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        bad = tmp_path / "bad.flow.json"
        bad.write_text("{not valid", encoding="utf-8")
        exit_code = cli.main(["suggest", str(bad)])
        capsys.readouterr()
        assert exit_code == 1


# ---------------------------------------------------------------------------
# Suggestion data class
# ---------------------------------------------------------------------------


class TestSuggestion:
    def test_round_trips_via_pydantic(self) -> None:
        s = Suggestion(
            code="CW001",
            title="wasteful-passthrough",
            step_index=2,
            tool_name="double",
            message="hello",
        )
        round_tripped = Suggestion.model_validate_json(s.model_dump_json())
        assert round_tripped == s
