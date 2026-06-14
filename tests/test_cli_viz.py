"""Tests for ``chainweaver viz`` Mermaid output and ``--result`` overlay (issue #392)."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from typer.testing import CliRunner

from chainweaver import cli
from chainweaver.executor import ExecutionResult, StepRecord
from chainweaver.flow import Flow, FlowStep
from chainweaver.registry import FlowRegistry

_RUNNER = CliRunner()

_DEMO_FLOW = """type: Flow
name: demo_flow
version: 0.1.0
description: Demo flow for viz tests.
steps:
  - tool_name: double
    input_mapping: {number: number}
  - tool_name: add_ten
    input_mapping: {value: value}
"""


@pytest.fixture(autouse=True)
def _reset_registry() -> None:
    cli.set_default_registry(None)


@pytest.fixture
def flow_file(tmp_path: Path) -> Path:
    path = tmp_path / "demo.flow.yaml"
    path.write_text(_DEMO_FLOW, encoding="utf-8")
    return path


def _write_trace(path: Path) -> Path:
    now = datetime(2026, 5, 16, tzinfo=timezone.utc)
    result = ExecutionResult(
        flow_name="demo_flow",
        flow_version="0.1.0",
        success=False,
        final_output=None,
        execution_log=[
            StepRecord(
                step_index=0,
                tool_name="double",
                inputs={},
                outputs={"value": 10},
                success=True,
                started_at=now,
                ended_at=now,
                duration_ms=12.5,
            ),
            StepRecord(
                step_index=1,
                tool_name="add_ten",
                inputs={},
                outputs=None,
                success=False,
                error_type="FlowExecutionError",
                error_message="boom",
                started_at=now,
                ended_at=now,
                duration_ms=3.0,
            ),
        ],
        trace_id="t1",
        started_at=now,
        ended_at=now,
        total_duration_ms=15.5,
        initial_input={},
    )
    path.write_text(result.model_dump_json(), encoding="utf-8")
    return path


class TestVizMermaid:
    def test_mermaid_format(self, flow_file: Path) -> None:
        result = _RUNNER.invoke(
            cli.app, ["viz", "demo_flow", "--file", str(flow_file), "--format", "mermaid"]
        )
        assert result.exit_code == 0
        assert result.stdout.startswith("graph LR")
        assert "double" in result.stdout
        assert "-->" in result.stdout

    def test_ascii_still_default(self, flow_file: Path) -> None:
        result = _RUNNER.invoke(cli.app, ["viz", "demo_flow", "--file", str(flow_file)])
        assert result.exit_code == 0
        assert "→" in result.stdout


class TestVizResultOverlay:
    def test_result_overlay_mermaid_no_registry(self, tmp_path: Path) -> None:
        trace = _write_trace(tmp_path / "t.json")
        result = _RUNNER.invoke(cli.app, ["viz", "--result", str(trace), "--format", "mermaid"])
        assert result.exit_code == 0
        assert result.stdout.startswith("graph LR")
        # Failure marker + red style on the failed step.
        assert "✗" in result.stdout
        assert "fill:#f66" in result.stdout

    def test_result_requires_mermaid_format(self, tmp_path: Path) -> None:
        trace = _write_trace(tmp_path / "t.json")
        result = _RUNNER.invoke(cli.app, ["viz", "--result", str(trace), "--format", "dot"])
        assert result.exit_code == 2
        assert "only available with --format mermaid" in result.output

    def test_missing_trace_file_exits_two(self, tmp_path: Path) -> None:
        result = _RUNNER.invoke(
            cli.app, ["viz", "--result", str(tmp_path / "nope.json"), "--format", "mermaid"]
        )
        assert result.exit_code == 2


class TestVizUsage:
    def test_no_flow_and_no_result_exits_two(self) -> None:
        result = _RUNNER.invoke(cli.app, ["viz", "--format", "mermaid"])
        assert result.exit_code == 2
        assert "provide a FLOW_NAME" in result.output

    def test_mermaid_renders_registered_flow(self) -> None:
        flow = Flow(
            name="reg_flow",
            version="0.1.0",
            description="From the registry.",
            steps=[FlowStep(tool_name="double", input_mapping={"number": "number"})],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        cli.set_default_registry(registry)
        result = _RUNNER.invoke(cli.app, ["viz", "reg_flow", "--format", "mermaid"])
        assert result.exit_code == 0
        assert result.stdout.startswith("graph LR")
