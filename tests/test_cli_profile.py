"""Tests for the ``chainweaver profile`` CLI subcommand (issue #147)."""

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


def _make_step_record(
    *,
    step_index: int,
    tool_name: str,
    duration_ms: float,
    success: bool = True,
    retry_count: int = 0,
    skipped: bool = False,
    fallback_used: bool = False,
    cached: bool = False,
) -> StepRecord:
    """Minimal :class:`StepRecord` with the fields ``profile`` cares about."""
    now = datetime(2026, 5, 16, tzinfo=timezone.utc)
    return StepRecord(
        step_index=step_index,
        tool_name=tool_name,
        inputs={},
        outputs={} if success else None,
        success=success,
        error_type=None if success else "FlowExecutionError",
        error_message=None if success else "boom",
        started_at=now,
        ended_at=now,
        duration_ms=duration_ms,
        retry_count=retry_count,
        skipped=skipped,
        fallback_used=fallback_used,
        cached=cached,
    )


def _make_result(
    *,
    flow_name: str = "etl",
    trace_id: str = "abc123",
    success: bool = True,
    durations: list[tuple[str, float]] | None = None,
    total_duration_ms: float | None = None,
) -> ExecutionResult:
    """Build an :class:`ExecutionResult` with deterministic timestamps."""
    if durations is None:
        durations = [("fetch", 40.0), ("transform", 10.0), ("store", 20.0)]
    now = datetime(2026, 5, 16, tzinfo=timezone.utc)
    log = [
        _make_step_record(step_index=i, tool_name=name, duration_ms=ms, success=success)
        for i, (name, ms) in enumerate(durations)
    ]
    if total_duration_ms is not None:
        total = total_duration_ms
    else:
        total = sum(d for _, d in durations) + 1.0
    return ExecutionResult(
        flow_name=flow_name,
        flow_version="0.1.0",
        success=success,
        final_output={"ok": True} if success else None,
        execution_log=log,
        trace_id=trace_id,
        started_at=now,
        ended_at=now,
        total_duration_ms=total,
        initial_input={},
    )


def _write_trace(path: Path, result: ExecutionResult) -> None:
    path.write_text(result.model_dump_json(), encoding="utf-8")


# ---------------------------------------------------------------------------
# Single-trace mode
# ---------------------------------------------------------------------------


class TestProfileSingle:
    def test_table_output_shows_flow_and_durations(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        trace = tmp_path / "t.trace.json"
        _write_trace(trace, _make_result())
        exit_code = cli.main(["profile", str(trace)])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "etl" in captured.out
        assert "abc123" in captured.out
        # Per-step rows present:
        assert "fetch" in captured.out
        assert "transform" in captured.out
        assert "store" in captured.out
        # Total / overhead summary line:
        assert "Total:" in captured.out
        assert "overhead:" in captured.out

    def test_json_output_shape(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        trace = tmp_path / "t.trace.json"
        _write_trace(trace, _make_result(total_duration_ms=71.5))
        exit_code = cli.main(["profile", str(trace), "--format", "json"])
        captured = capsys.readouterr()
        assert exit_code == 0
        payload = json.loads(captured.out)["data"]
        assert payload["trace_count"] == 1
        assert payload["flow_name"] == "etl"
        assert payload["trace_id"] == "abc123"
        assert payload["step_count"] == 3
        assert payload["total_duration_ms"] == 71.5
        assert payload["sum_step_ms"] == 70.0
        assert payload["overhead_ms"] == pytest.approx(1.5, abs=1e-9)
        assert [s["tool_name"] for s in payload["steps"]] == ["fetch", "transform", "store"]
        assert payload["steps"][0]["duration_ms"] == 40.0

    def test_top_truncation_surfaces_hidden_count(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        trace = tmp_path / "t.trace.json"
        durations = [(f"step_{i}", float(i + 1)) for i in range(5)]
        _write_trace(trace, _make_result(durations=durations, total_duration_ms=20.0))
        exit_code = cli.main(["profile", str(trace), "--top", "2"])
        captured = capsys.readouterr()
        assert exit_code == 0
        # Slowest two are step_4 (5ms) and step_3 (4ms); rest hidden.
        assert "step_4" in captured.out
        assert "step_3" in captured.out
        assert "3 more step" in captured.out

    def test_top_must_be_positive(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        trace = tmp_path / "t.trace.json"
        _write_trace(trace, _make_result())
        exit_code = cli.main(["profile", str(trace), "--top", "0"])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "--top must be >= 1" in captured.err

    def test_failed_step_marked_in_table(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        trace = tmp_path / "t.trace.json"
        _write_trace(trace, _make_result(success=False))
        exit_code = cli.main(["profile", str(trace)])
        captured = capsys.readouterr()
        # Profile is read-only; even for failed flows it exits 0 because the
        # analysis itself succeeded. Failure is signalled in the rows.
        assert exit_code == 0
        assert "ERR" in captured.out

    def test_missing_file_returns_two(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        exit_code = cli.main(["profile", str(tmp_path / "nope.json")])
        captured = capsys.readouterr()
        assert exit_code == 2
        assert "file not found" in captured.err

    def test_malformed_trace_returns_one(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        bad = tmp_path / "bad.trace.json"
        bad.write_text("{not valid json", encoding="utf-8")
        exit_code = cli.main(["profile", str(bad)])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "malformed trace file" in captured.err


# ---------------------------------------------------------------------------
# Multi-trace aggregation
# ---------------------------------------------------------------------------


class TestProfileMulti:
    def _write_three_traces(self, tmp_path: Path) -> list[Path]:
        paths: list[Path] = []
        for i, factor in enumerate([1.0, 1.1, 0.9]):
            path = tmp_path / f"trace_{i}.json"
            _write_trace(
                path,
                _make_result(
                    trace_id=f"trace{i}",
                    durations=[("fetch", 40.0 * factor), ("store", 20.0 * factor)],
                    total_duration_ms=60.0 * factor + 1.0,
                ),
            )
            paths.append(path)
        return paths

    def test_json_output_includes_percentiles(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        paths = self._write_three_traces(tmp_path)
        exit_code = cli.main(["profile", *[str(p) for p in paths], "--format", "json"])
        captured = capsys.readouterr()
        assert exit_code == 0
        payload = json.loads(captured.out)["data"]
        assert payload["trace_count"] == 3
        assert payload["flow_name"] == "etl"
        assert payload["step_count"] == 2
        # Percentiles must be present and ordered consistently.
        total_stats = payload["total_duration_ms"]
        assert {"p50", "p95", "p99", "mean", "stdev"} == set(total_stats.keys())
        assert total_stats["p50"] <= total_stats["p95"] <= total_stats["p99"]
        # Per-step percentiles.
        first_step = payload["steps"][0]
        assert first_step["tool_name"] == "fetch"
        fetch_p50 = first_step["duration_ms"]["p50"]
        assert fetch_p50 == pytest.approx(40.0, abs=0.5)

    def test_table_output_aggregated(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        paths = self._write_three_traces(tmp_path)
        exit_code = cli.main(["profile", *[str(p) for p in paths]])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "aggregated over 3 traces" in captured.out
        assert "p95" in captured.out
        assert "fetch" in captured.out

    def test_mixed_flow_names_returns_one(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        path_a = tmp_path / "a.json"
        path_b = tmp_path / "b.json"
        _write_trace(path_a, _make_result(flow_name="etl"))
        _write_trace(path_b, _make_result(flow_name="other"))
        exit_code = cli.main(["profile", str(path_a), str(path_b)])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "mixed flow names" in captured.err

    def test_mismatched_step_counts_returns_one(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        path_a = tmp_path / "a.json"
        path_b = tmp_path / "b.json"
        _write_trace(path_a, _make_result(durations=[("fetch", 40.0)]))
        _write_trace(
            path_b,
            _make_result(durations=[("fetch", 40.0), ("store", 20.0)]),
        )
        exit_code = cli.main(["profile", str(path_a), str(path_b)])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "different step counts" in captured.err

    def test_mismatched_tool_at_step_returns_one(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Same step count, but trace B uses a different tool at index 1.
        # Without the guard, aggregates would be silently mislabelled
        # under whichever name the first trace happened to record.
        path_a = tmp_path / "a.json"
        path_b = tmp_path / "b.json"
        _write_trace(
            path_a,
            _make_result(durations=[("fetch", 40.0), ("store", 20.0)]),
        )
        _write_trace(
            path_b,
            _make_result(durations=[("fetch", 40.0), ("archive", 20.0)]),
        )
        exit_code = cli.main(["profile", str(path_a), str(path_b)])
        captured = capsys.readouterr()
        assert exit_code == 1
        assert "disagree on tool at step 1" in captured.err
        assert "archive" in captured.err
        assert "store" in captured.err

    def test_consistency_warning_surfaces(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Step "wobble" has very high stdev: 1ms, 100ms, 200ms → stdev >> 50% of mean.
        paths: list[Path] = []
        for i, ms in enumerate([1.0, 100.0, 200.0]):
            path = tmp_path / f"trace_{i}.json"
            _write_trace(
                path,
                _make_result(
                    trace_id=f"trace{i}",
                    durations=[("wobble", ms)],
                    total_duration_ms=ms + 1.0,
                ),
            )
            paths.append(path)
        exit_code = cli.main(["profile", *[str(p) for p in paths]])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "inconsistent" in captured.out
        assert "wobble" in captured.out


# ---------------------------------------------------------------------------
# Reliability aggregates (issue #176)
# ---------------------------------------------------------------------------


class TestProfileReliabilitySingle:
    """Per-step + per-tool aggregates surfaced in single-trace mode."""

    def test_per_step_reliability_fields_in_json(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        log = [
            _make_step_record(step_index=0, tool_name="fetch", duration_ms=10.0, retry_count=2),
            _make_step_record(step_index=1, tool_name="transform", duration_ms=20.0, skipped=True),
            _make_step_record(
                step_index=2,
                tool_name="store",
                duration_ms=30.0,
                fallback_used=True,
                cached=False,
            ),
        ]
        now = datetime(2026, 5, 16, tzinfo=timezone.utc)
        result = ExecutionResult(
            flow_name="etl",
            flow_version="0.1.0",
            success=True,
            final_output={"ok": True},
            execution_log=log,
            trace_id="abc123",
            started_at=now,
            ended_at=now,
            total_duration_ms=70.0,
            initial_input={},
        )
        trace = tmp_path / "t.trace.json"
        _write_trace(trace, result)
        exit_code = cli.main(["profile", str(trace), "--format", "json"])
        captured = capsys.readouterr()
        assert exit_code == 0
        payload = json.loads(captured.out)["data"]
        # Every step row now carries the reliability projection.
        by_tool = {s["tool_name"]: s for s in payload["steps"]}
        assert by_tool["fetch"]["retry_count"] == 2
        assert by_tool["fetch"]["skipped"] is False
        assert by_tool["fetch"]["fallback_used"] is False
        assert by_tool["transform"]["skipped"] is True
        assert by_tool["store"]["fallback_used"] is True
        # Aggregates: totals + per-tool buckets.
        agg = payload["aggregates"]
        assert agg["retry_count"] == 2
        assert agg["skip_count"] == 1
        assert agg["fallback_count"] == 1
        assert agg["failure_count"] == 0
        assert agg["cached_count"] == 0
        assert agg["by_tool"]["fetch"]["retry_count"] == 2
        assert agg["by_tool"]["fetch"]["invocation_count"] == 1
        assert agg["by_tool"]["transform"]["skip_count"] == 1
        assert agg["by_tool"]["store"]["fallback_count"] == 1

    def test_clean_run_has_zero_aggregates_and_no_reliability_footer(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        trace = tmp_path / "t.trace.json"
        _write_trace(trace, _make_result())
        exit_code = cli.main(["profile", str(trace), "--format", "json"])
        captured = capsys.readouterr()
        assert exit_code == 0
        payload = json.loads(captured.out)["data"]
        agg = payload["aggregates"]
        assert agg["retry_count"] == 0
        assert agg["skip_count"] == 0
        assert agg["fallback_count"] == 0
        assert agg["failure_count"] == 0
        # When nothing notable happened, the table view stays compact.
        exit_code = cli.main(["profile", str(trace)])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "Reliability:" not in captured.out

    def test_reliability_footer_surfaces_problem_tools(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        log = [
            _make_step_record(
                step_index=0,
                tool_name="upload",
                duration_ms=15.0,
                success=False,
            ),
            _make_step_record(
                step_index=1,
                tool_name="enrich",
                duration_ms=25.0,
                retry_count=3,
            ),
        ]
        now = datetime(2026, 5, 16, tzinfo=timezone.utc)
        result = ExecutionResult(
            flow_name="etl",
            flow_version="0.1.0",
            success=False,
            final_output=None,
            execution_log=log,
            trace_id="abc123",
            started_at=now,
            ended_at=now,
            total_duration_ms=50.0,
            initial_input={},
        )
        trace = tmp_path / "t.trace.json"
        _write_trace(trace, result)
        exit_code = cli.main(["profile", str(trace)])
        captured = capsys.readouterr()
        assert exit_code == 0
        assert "Reliability:" in captured.out
        assert "retries=3" in captured.out
        assert "failures=1" in captured.out
        # Per-tool table shows the offender first (failures sort to top).
        assert "upload" in captured.out
        assert "enrich" in captured.out


class TestProfileReliabilityMulti:
    """Cross-trace reliability aggregates in multi-trace mode."""

    def test_aggregates_summed_across_traces(
        self,
        tmp_path: Path,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        # Two traces of the same flow.  Trace A: fetch retries twice.
        # Trace B: fetch retries once and store falls back.
        now = datetime(2026, 5, 16, tzinfo=timezone.utc)

        def _result(
            *,
            trace_id: str,
            fetch_retries: int,
            store_fallback: bool,
        ) -> ExecutionResult:
            log = [
                _make_step_record(
                    step_index=0,
                    tool_name="fetch",
                    duration_ms=10.0,
                    retry_count=fetch_retries,
                ),
                _make_step_record(
                    step_index=1,
                    tool_name="store",
                    duration_ms=20.0,
                    fallback_used=store_fallback,
                ),
            ]
            return ExecutionResult(
                flow_name="etl",
                flow_version="0.1.0",
                success=True,
                final_output={"ok": True},
                execution_log=log,
                trace_id=trace_id,
                started_at=now,
                ended_at=now,
                total_duration_ms=40.0,
                initial_input={},
            )

        path_a = tmp_path / "a.json"
        path_b = tmp_path / "b.json"
        _write_trace(path_a, _result(trace_id="a", fetch_retries=2, store_fallback=False))
        _write_trace(path_b, _result(trace_id="b", fetch_retries=1, store_fallback=True))
        exit_code = cli.main(["profile", str(path_a), str(path_b), "--format", "json"])
        captured = capsys.readouterr()
        assert exit_code == 0
        payload = json.loads(captured.out)["data"]
        # Per-step entries carry counts summed across traces at that index.
        by_step = {s["tool_name"]: s for s in payload["steps"]}
        assert by_step["fetch"]["retry_count"] == 3
        assert by_step["store"]["fallback_count"] == 1
        # Run-wide aggregates and by_tool entries roll up the same data.
        agg = payload["aggregates"]
        assert agg["retry_count"] == 3
        assert agg["fallback_count"] == 1
        assert agg["by_tool"]["fetch"]["retry_count"] == 3
        assert agg["by_tool"]["fetch"]["invocation_count"] == 2
        assert agg["by_tool"]["store"]["fallback_count"] == 1
        assert agg["by_tool"]["store"]["invocation_count"] == 2
