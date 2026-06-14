"""Tests for the ``chainweaver diff`` CLI subcommand (issue #148)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from chainweaver import cli
from chainweaver.executor import ExecutionResult, StepRecord


@pytest.fixture(autouse=True)
def _reset_registry() -> None:
    cli.set_default_registry(None)


def _record(
    *,
    step_index: int,
    tool_name: str,
    outputs: dict[str, object] | None,
    duration_ms: float = 10.0,
    success: bool = True,
    error_type: str | None = None,
    error_message: str | None = None,
) -> StepRecord:
    now = datetime(2026, 5, 16, tzinfo=timezone.utc)
    return StepRecord(
        step_index=step_index,
        tool_name=tool_name,
        inputs={},
        outputs=outputs,
        success=success,
        error_type=error_type,
        error_message=error_message,
        started_at=now,
        ended_at=now,
        duration_ms=duration_ms,
    )


def _result(
    *,
    flow_name: str = "etl",
    success: bool = True,
    log: list[StepRecord] | None = None,
    final_output: dict[str, object] | None = None,
    total_duration_ms: float = 30.0,
    trace_id: str = "trace_a",
) -> ExecutionResult:
    now = datetime(2026, 5, 16, tzinfo=timezone.utc)
    if log is None:
        log = [
            _record(step_index=0, tool_name="fetch", outputs={"data": "ok"}),
            _record(step_index=1, tool_name="store", outputs={"rows": 42}),
        ]
    return ExecutionResult(
        flow_name=flow_name,
        flow_version="0.1.0",
        success=success,
        final_output=final_output if final_output is not None else {"rows": 42},
        execution_log=log,
        trace_id=trace_id,
        started_at=now,
        ended_at=now,
        total_duration_ms=total_duration_ms,
        initial_input={},
    )


def _write(path: Path, result: ExecutionResult) -> None:
    path.write_text(result.model_dump_json(), encoding="utf-8")


# ---------------------------------------------------------------------------
# Identity / structural diffs
# ---------------------------------------------------------------------------


class TestDiffIdentical:
    def test_identical_traces_exit_zero(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Differ only in non-deterministic fields (trace_id, timestamps).
        a = tmp_path / "a.json"
        b = tmp_path / "b.json"
        _write(a, _result(trace_id="trace_a"))
        _write(b, _result(trace_id="trace_b"))
        exit_code = cli.main(["diff", str(a), str(b)])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "identical" in captured.out.lower()

    def test_identical_json_output(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        a = tmp_path / "a.json"
        b = tmp_path / "b.json"
        _write(a, _result(trace_id="trace_a"))
        _write(b, _result(trace_id="trace_b"))
        exit_code = cli.main(["diff", str(a), str(b), "--format", "json"])
        captured = capsys.readouterr()
        assert exit_code == 0
        payload = json.loads(captured.out)["data"]
        assert payload["identical"] is True
        assert payload["flow_name"] is None
        assert payload["step_count"] is None
        assert payload["steps"] == []


class TestDiffDivergent:
    def test_different_flow_names(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        a = tmp_path / "a.json"
        b = tmp_path / "b.json"
        _write(a, _result(flow_name="etl"))
        _write(b, _result(flow_name="renamed"))
        exit_code = cli.main(["diff", str(a), str(b)])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "etl" in captured.out and "renamed" in captured.out

    def test_diverging_step_output(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        a = tmp_path / "a.json"
        b = tmp_path / "b.json"
        _write(a, _result())
        _write(
            b,
            _result(
                log=[
                    _record(step_index=0, tool_name="fetch", outputs={"data": "ok"}),
                    _record(step_index=1, tool_name="store", outputs={"rows": 99}),
                ],
                final_output={"rows": 99},
            ),
        )
        exit_code = cli.main(["diff", str(a), str(b)])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "step 1" in captured.out
        assert "store" in captured.out

    def test_diverging_step_output_json_shape(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        a = tmp_path / "a.json"
        b = tmp_path / "b.json"
        _write(a, _result())
        _write(
            b,
            _result(
                log=[
                    _record(step_index=0, tool_name="fetch", outputs={"data": "ok"}),
                    _record(step_index=1, tool_name="store", outputs={"rows": 99}),
                ],
                final_output={"rows": 99},
            ),
        )
        exit_code = cli.main(["diff", str(a), str(b), "--format", "json"])
        captured = capsys.readouterr()
        assert exit_code == 1
        payload = json.loads(captured.out)["data"]
        assert payload["identical"] is False
        # Snapshot: exact DeepDiff serialization contract for a scalar change.
        # DeepDiff names paths as "root['key']" in tree-view mode.
        assert "values_changed" in payload["final_output"]
        row_diff = payload["final_output"]["values_changed"]["root['rows']"]
        assert row_diff["new_value"] == 99
        assert row_diff["old_value"] == 42
        # The single step diff names the diverging step with the same shape.
        assert len(payload["steps"]) == 1
        assert payload["steps"][0]["step_index"] == 1
        assert payload["steps"][0]["tool_name"] == "store"
        assert "values_changed" in payload["steps"][0]["outputs"]
        step_row_diff = payload["steps"][0]["outputs"]["values_changed"]["root['rows']"]
        assert step_row_diff["new_value"] == 99
        assert step_row_diff["old_value"] == 42

    def test_error_vs_success_divergence(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        a = tmp_path / "a.json"
        b = tmp_path / "b.json"
        _write(a, _result())
        _write(
            b,
            _result(
                success=False,
                log=[
                    _record(step_index=0, tool_name="fetch", outputs={"data": "ok"}),
                    _record(
                        step_index=1,
                        tool_name="store",
                        outputs=None,
                        success=False,
                        error_type="FlowExecutionError",
                        error_message="boom",
                    ),
                ],
                final_output=None,
            ),
        )
        exit_code = cli.main(["diff", str(a), str(b)])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "success" in captured.out
        assert "error_type" in captured.out
        assert "FlowExecutionError" in captured.out

    def test_mismatched_step_counts(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        a = tmp_path / "a.json"
        b = tmp_path / "b.json"
        _write(a, _result())
        _write(
            b,
            _result(log=[_record(step_index=0, tool_name="fetch", outputs={"data": "ok"})]),
        )
        exit_code = cli.main(["diff", str(a), str(b)])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "step_count" in captured.out
        assert "2" in captured.out and "1" in captured.out


# ---------------------------------------------------------------------------
# Performance tolerance
# ---------------------------------------------------------------------------


class TestDiffPerfTolerance:
    def test_within_tolerance_passes(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # 10ms vs 11ms = 10% delta. With --perf-tolerance 25 it should still
        # be considered identical.
        a = tmp_path / "a.json"
        b = tmp_path / "b.json"
        _write(
            a,
            _result(log=[_record(step_index=0, tool_name="t", outputs={}, duration_ms=10.0)]),
        )
        _write(
            b,
            _result(
                log=[_record(step_index=0, tool_name="t", outputs={}, duration_ms=11.0)],
                trace_id="trace_b",
            ),
        )
        exit_code = cli.main(["diff", str(a), str(b), "--perf-tolerance", "25"])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "identical" in captured.out.lower()

    def test_exceeds_tolerance_flags_regression(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # 10ms → 20ms = 100% delta. Tolerance 25 should flag it.
        a = tmp_path / "a.json"
        b = tmp_path / "b.json"
        _write(
            a,
            _result(log=[_record(step_index=0, tool_name="t", outputs={}, duration_ms=10.0)]),
        )
        _write(
            b,
            _result(
                log=[_record(step_index=0, tool_name="t", outputs={}, duration_ms=20.0)],
                trace_id="trace_b",
            ),
        )
        exit_code = cli.main(["diff", str(a), str(b), "--perf-tolerance", "25"])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "duration:" in captured.out
        assert "+10.0" in captured.out
        assert "100" in captured.out

    def test_perf_tolerance_off_ignores_duration(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Wide duration delta with no --perf-tolerance should still be
        # considered identical.
        a = tmp_path / "a.json"
        b = tmp_path / "b.json"
        _write(
            a,
            _result(log=[_record(step_index=0, tool_name="t", outputs={}, duration_ms=10.0)]),
        )
        _write(
            b,
            _result(
                log=[_record(step_index=0, tool_name="t", outputs={}, duration_ms=999.0)],
                trace_id="trace_b",
            ),
        )
        exit_code = cli.main(["diff", str(a), str(b)])
        assert exit_code == 0


# ---------------------------------------------------------------------------
# File errors
# ---------------------------------------------------------------------------


class TestDiffFileErrors:
    def test_missing_first_file_returns_two(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        b = tmp_path / "b.json"
        _write(b, _result())
        exit_code = cli.main(["diff", str(tmp_path / "nope.json"), str(b)])
        captured = capsys.readouterr()
        assert exit_code == 2
        assert "file not found" in captured.err

    def test_missing_second_file_returns_two(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        a = tmp_path / "a.json"
        _write(a, _result())
        exit_code = cli.main(["diff", str(a), str(tmp_path / "nope.json")])
        captured = capsys.readouterr()
        assert exit_code == 2
        assert "file not found" in captured.err

    def test_malformed_trace_returns_one(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        a = tmp_path / "a.json"
        b = tmp_path / "b.json"
        a.write_text("{not valid", encoding="utf-8")
        _write(b, _result())
        exit_code = cli.main(["diff", str(a), str(b)])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "malformed trace file" in captured.err
