"""Tests for the deterministic ``chainweaver explain`` command (issue #420)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from chainweaver import cli
from chainweaver.executor import ExecutionResult, StepRecord

_RUNNER = CliRunner()

_LINEAR_FLOW = """type: Flow
name: demo_flow
version: 0.2.0
description: Demo flow for explain tests.
steps:
  - tool_name: double
    input_mapping: {number: number}
  - tool_name: add_ten
    input_mapping: {value: value}
"""

_DAG_FLOW = """type: DAGFlow
name: dag_flow
version: 0.1.0
description: Branching DAG for explain tests.
steps:
  - step_id: probe
    tool_name: probe
    input_mapping: {x: x}
    depends_on: []
    branches:
      - {target_step_id: fast, predicate: "cache_hit == True"}
      - {target_step_id: slow, predicate: "cache_hit == False"}
  - step_id: fast
    tool_name: fast
    input_mapping: {x: x}
    depends_on: [probe]
  - step_id: slow
    tool_name: slow
    input_mapping: {x: x}
    depends_on: [probe]
"""


@pytest.fixture(autouse=True)
def _reset_registry() -> None:
    cli.set_default_registry(None)


@pytest.fixture
def linear_file(tmp_path: Path) -> Path:
    path = tmp_path / "demo.flow.yaml"
    path.write_text(_LINEAR_FLOW, encoding="utf-8")
    return path


@pytest.fixture
def dag_file(tmp_path: Path) -> Path:
    path = tmp_path / "dag.flow.yaml"
    path.write_text(_DAG_FLOW, encoding="utf-8")
    return path


class TestExplainMarkdown:
    def test_md_covers_required_sections(self, linear_file: Path) -> None:
        result = _RUNNER.invoke(cli.app, ["explain", "demo_flow", "--file", str(linear_file)])
        assert result.exit_code == 0
        out = result.stdout
        assert "# Flow: demo_flow" in out
        assert "## Governance" in out
        assert "## Safety" in out
        assert "## Steps" in out
        assert "## Diagram" in out
        assert "```mermaid" in out
        assert "graph LR" in out
        # Mappings rendered for steps.
        assert "number ← number" in out

    def test_deterministic_across_runs(self, linear_file: Path) -> None:
        first = _RUNNER.invoke(cli.app, ["explain", "demo_flow", "--file", str(linear_file)])
        second = _RUNNER.invoke(cli.app, ["explain", "demo_flow", "--file", str(linear_file)])
        assert first.stdout == second.stdout

    def test_dag_branches_rendered(self, dag_file: Path) -> None:
        result = _RUNNER.invoke(cli.app, ["explain", "dag_flow", "--file", str(dag_file)])
        assert result.exit_code == 0
        out = result.stdout
        assert "Depends on: probe" in out
        assert "cache_hit == True" in out
        assert "fast" in out


class TestExplainText:
    def test_text_format_drops_fences(self, linear_file: Path) -> None:
        result = _RUNNER.invoke(
            cli.app, ["explain", "demo_flow", "--file", str(linear_file), "--format", "text"]
        )
        assert result.exit_code == 0
        assert "```" not in result.stdout
        # Table framing pipes are flattened away in text mode.
        assert "|" not in result.stdout
        assert "Flow: demo_flow" in result.stdout


class TestExplainResultOverlay:
    def test_result_overlay(self, linear_file: Path, tmp_path: Path) -> None:
        now = datetime(2026, 5, 16, tzinfo=timezone.utc)
        result_obj = ExecutionResult(
            flow_name="demo_flow",
            flow_version="0.2.0",
            success=True,
            final_output={"value": 20},
            execution_log=[
                StepRecord(
                    step_index=0,
                    tool_name="double",
                    inputs={},
                    outputs={"value": 10},
                    success=True,
                    started_at=now,
                    ended_at=now,
                    duration_ms=5.0,
                ),
            ],
            trace_id="t1",
            started_at=now,
            ended_at=now,
            total_duration_ms=6.0,
            initial_input={},
        )
        trace = tmp_path / "t.json"
        trace.write_text(result_obj.model_dump_json(), encoding="utf-8")
        result = _RUNNER.invoke(
            cli.app,
            ["explain", "demo_flow", "--file", str(linear_file), "--result", str(trace)],
        )
        assert result.exit_code == 0
        assert "## Execution outcome" in result.stdout
        assert "| 0 | double | ok |" in result.stdout


class TestExplainErrors:
    def test_flow_not_found_exits_one(self, linear_file: Path) -> None:
        result = _RUNNER.invoke(cli.app, ["explain", "missing", "--file", str(linear_file)])
        assert result.exit_code == 1

    def test_missing_file_exits_two(self, tmp_path: Path) -> None:
        result = _RUNNER.invoke(
            cli.app, ["explain", "demo_flow", "--file", str(tmp_path / "nope.flow.yaml")]
        )
        assert result.exit_code == 2
