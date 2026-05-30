"""Format-validation tests for the benchmark artifacts (issues #103, #207).

The benchmark scripts live under ``benchmarks/`` (outside the importable
``chainweaver`` package and off the pytest ``pythonpath``), so they are loaded
here by file path via :mod:`importlib`. The goal is the contract issue #207
asks CI to guard — "generated report format remains valid" — plus the issue
#103 invariant that compiled execution shows zero data corruption.

Everything runs in a fast smoke configuration (no sleeps, few runs) so the
suite stays quick across the CI matrix.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

_BENCH_DIR = Path(__file__).resolve().parents[1] / "benchmarks"


def _load(module_name: str) -> ModuleType:
    """Load a ``benchmarks/<module_name>.py`` module by path.

    The module is registered in ``sys.modules`` before execution so that
    ``@dataclass`` annotation resolution (under ``from __future__ import
    annotations``) can find the module's namespace.
    """
    path = _BENCH_DIR / f"{module_name}.py"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def correctness() -> ModuleType:
    return _load("bench_correctness")


@pytest.fixture(scope="module")
def report_mod() -> ModuleType:
    return _load("report")


# ---------------------------------------------------------------------------
# Correctness benchmark (issue #103)
# ---------------------------------------------------------------------------


class TestCorrectnessBenchmark:
    def test_compiled_has_zero_corruption(self, correctness: Any) -> None:
        scenario = correctness.SCENARIOS[0]
        rpt = correctness.benchmark_compiled_correctness(scenario, runs=25)
        assert rpt.approach == "compiled"
        assert rpt.successful_runs == 25
        assert rpt.field_hallucinations == 0
        assert rpt.data_loss_events == 0
        assert rpt.type_corruptions == 0
        assert rpt.schema_drift_events == 0
        assert rpt.routing_inconsistencies == 0
        assert rpt.corruption_rate == 0.0
        assert rpt.data_integrity_score == 1.0
        # Compiled execution is deterministic by construction: one identical
        # outcome on every run.
        assert rpt.determinism_rate == 1.0

    def test_determinism_rate_measures_consistency_not_correctness(self, correctness: Any) -> None:
        # determinism_rate is the most-common-outcome frequency / runs, so a
        # corrupting naive chain (varied outcomes) must score below 1.0 and
        # need not equal the success rate.
        scenario = correctness.SCENARIOS[2]  # long_chain, 10 steps
        profile = correctness.LLMCorruptionProfile(seed=7)
        rpt = correctness.benchmark_naive_correctness(scenario, runs=100, profile=profile)
        assert 0.0 <= rpt.determinism_rate <= 1.0
        assert rpt.determinism_rate < 1.0

    def test_naive_introduces_corruption(self, correctness: Any) -> None:
        scenario = correctness.SCENARIOS[2]  # long_chain, 10 steps
        profile = correctness.LLMCorruptionProfile(seed=7)
        rpt = correctness.benchmark_naive_correctness(scenario, runs=100, profile=profile)
        assert rpt.approach == "naive"
        # A 10-step chain at default rates must show real corruption.
        assert rpt.corruption_rate > 0.0
        total_events = (
            rpt.field_hallucinations
            + rpt.data_loss_events
            + rpt.type_corruptions
            + rpt.schema_drift_events
            + rpt.routing_inconsistencies
        )
        assert total_events > 0

    def test_seed_is_reproducible(self, correctness: Any) -> None:
        scenario = correctness.SCENARIOS[0]
        p1 = correctness.LLMCorruptionProfile(seed=42)
        p2 = correctness.LLMCorruptionProfile(seed=42)
        r1 = correctness.benchmark_naive_correctness(scenario, runs=50, profile=p1)
        r2 = correctness.benchmark_naive_correctness(scenario, runs=50, profile=p2)
        assert r1.to_dict() == r2.to_dict()

    def test_corruption_compounds_with_length(self, correctness: Any) -> None:
        profile = correctness.LLMCorruptionProfile(seed=7)
        rows = correctness._compounding_analysis(runs=200, profile=profile)
        rates = [row["naive_corruption_rate"] for row in rows]
        # Monotonic non-decreasing: longer chains never corrupt less.
        assert rates == sorted(rates)
        assert rates[-1] > rates[0]

    def test_run_scenarios_shape(self, correctness: Any) -> None:
        report = correctness.run_scenarios(runs=20)
        assert report["runs"] == 20
        assert len(report["cases"]) == len(correctness.SCENARIOS)
        for case in report["cases"]:
            assert case["compiled"]["corruption_rate"] == 0.0
            assert {"scenario", "n_steps", "naive", "compiled"} <= case.keys()


# ---------------------------------------------------------------------------
# Aggregate report (issue #207)
# ---------------------------------------------------------------------------


def _smoke_report(report_mod: Any) -> Any:
    return report_mod.build_report(
        latency_cases=[(2, 0.0, 0.0), (4, 0.0, 0.0)],
        latency_repeats=1,
        correctness_runs=20,
    )


class TestBenchmarkReport:
    def test_report_has_required_sections(self, report_mod: Any) -> None:
        report = _smoke_report(report_mod)
        for key in ("environment", "parameters", "latency", "cost", "correctness", "caveats"):
            assert key in report

    def test_environment_metadata_present(self, report_mod: Any) -> None:
        env = _smoke_report(report_mod)["environment"]
        for key in ("python_version", "chainweaver_version", "os", "commit_sha"):
            assert env[key]

    def test_cost_section_is_priced_and_dated(self, report_mod: Any) -> None:
        cost = _smoke_report(report_mod)["cost"]
        assert cost["cost_saved_usd"] > 0.0
        assert cost["price_as_of"]  # snapshot date surfaced

    def test_decisions_avoided_is_positive(self, report_mod: Any) -> None:
        report = _smoke_report(report_mod)
        # Two cases (2 and 4 steps) -> (2-1)+(4-1) = 4 decisions avoided.
        assert report["decisions_avoided"] == 4

    def test_caveats_are_non_empty(self, report_mod: Any) -> None:
        assert len(_smoke_report(report_mod)["caveats"]) >= 1

    def test_markdown_renders_headers(self, report_mod: Any) -> None:
        md = report_mod.render_markdown(_smoke_report(report_mod))
        assert "# ChainWeaver Benchmark Report" in md
        assert "## Environment" in md
        assert "## Caveats" in md

    def test_write_artifacts_round_trip(self, report_mod: Any, tmp_path: Path) -> None:
        import json

        report = _smoke_report(report_mod)
        json_path, md_path = report_mod.write_artifacts(report, tmp_path)
        assert json_path.exists() and md_path.exists()
        # latest.json must be valid JSON that round-trips the sections.
        reloaded = json.loads(json_path.read_text(encoding="utf-8"))
        assert reloaded["cost"]["cost_saved_usd"] == report["cost"]["cost_saved_usd"]
