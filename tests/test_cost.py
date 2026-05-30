"""Tests for the Cost Avoided calculator (issue #74)."""

from __future__ import annotations

from typing import Any

import pytest
from helpers import (
    NumberInput,
    ValueInput,
    ValueOutput,
    _add_ten_fn,
    _double_fn,
)
from pydantic import BaseModel

from chainweaver.cost import (
    PROVIDER_PRICES,
    CostProfile,
    CostReport,
    PriceSnap,
    compute_cost_report,
    lookup_price,
)
from chainweaver.exceptions import CostProfileError
from chainweaver.executor import FlowExecutor
from chainweaver.flow import Flow, FlowStep
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool


def _build_two_step_executor(*, cost_profile: CostProfile | None = None) -> FlowExecutor:
    flow = Flow(
        name="cost_two_step",
        version="0.1.0",
        description="Two-step flow.",
        steps=[
            FlowStep(tool_name="double", input_mapping={"number": "number"}),
            FlowStep(tool_name="add_ten", input_mapping={"value": "value"}),
        ],
    )
    registry = FlowRegistry()
    registry.register_flow(flow)
    ex = FlowExecutor(registry=registry, cost_profile=cost_profile)
    ex.register_tool(
        Tool(
            name="double",
            description="Doubles a number.",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=_double_fn,
        )
    )
    ex.register_tool(
        Tool(
            name="add_ten",
            description="Adds 10.",
            input_schema=ValueInput,
            output_schema=ValueOutput,
            fn=_add_ten_fn,
        )
    )
    return ex


# ---------------------------------------------------------------------------
# Pure compute_cost_report
# ---------------------------------------------------------------------------


class TestComputeCostReport:
    def test_two_steps_one_call_avoided(self) -> None:
        report = compute_cost_report(
            steps_executed=2,
            actual_execution_ms=10.0,
            profile=CostProfile(),
        )
        assert report.steps_executed == 2
        assert report.llm_calls_avoided == 1

    def test_zero_steps_zero_calls_avoided(self) -> None:
        report = compute_cost_report(
            steps_executed=0,
            actual_execution_ms=0.0,
            profile=CostProfile(),
        )
        assert report.llm_calls_avoided == 0
        assert report.latency_saved_ms == 0.0
        assert report.cost_saved_usd == 0.0

    def test_single_step_zero_calls_avoided(self) -> None:
        report = compute_cost_report(
            steps_executed=1,
            actual_execution_ms=5.0,
            profile=CostProfile(),
        )
        assert report.llm_calls_avoided == 0

    def test_custom_profile_drives_savings(self) -> None:
        profile = CostProfile(
            avg_llm_latency_ms=400.0,
            avg_tokens_per_call=1000.0,
            cost_per_token_usd=0.0001,
        )
        report = compute_cost_report(
            steps_executed=5,
            actual_execution_ms=15.0,
            profile=profile,
        )
        assert report.llm_calls_avoided == 4
        assert report.latency_saved_ms == 4 * 400.0
        # 4 calls * 1000 tokens * $0.0001/token = $0.40
        assert report.cost_saved_usd == 0.4

    def test_str_contains_estimate_label(self) -> None:
        report = compute_cost_report(
            steps_executed=3,
            actual_execution_ms=12.0,
            profile=CostProfile(),
        )
        assert "estimate" in str(report)

    def test_to_dict_round_trip(self) -> None:
        report = compute_cost_report(
            steps_executed=4,
            actual_execution_ms=8.0,
            profile=CostProfile(avg_llm_latency_ms=200.0),
        )
        as_dict = report.to_dict()
        assert as_dict["steps_executed"] == 4
        assert as_dict["llm_calls_avoided"] == 3
        rebuilt = CostReport.model_validate(as_dict)
        assert rebuilt == report


# ---------------------------------------------------------------------------
# Executor integration
# ---------------------------------------------------------------------------


class TestExecutorIntegration:
    def test_no_profile_no_report(self) -> None:
        ex = _build_two_step_executor()
        result = ex.execute_flow("cost_two_step", {"number": 1})
        assert result.cost_report is None

    def test_profile_set_attaches_report(self) -> None:
        ex = _build_two_step_executor(cost_profile=CostProfile())
        result = ex.execute_flow("cost_two_step", {"number": 1})
        assert result.cost_report is not None
        assert result.cost_report.steps_executed == 2
        assert result.cost_report.llm_calls_avoided == 1

    def test_actual_execution_ms_matches_total(self) -> None:
        ex = _build_two_step_executor(cost_profile=CostProfile())
        result = ex.execute_flow("cost_two_step", {"number": 1})
        assert result.cost_report is not None
        assert result.cost_report.actual_execution_ms == result.total_duration_ms

    def test_failed_flow_still_has_report(self) -> None:
        class Inp(BaseModel):
            x: int

        class Out(BaseModel):
            x: int

        def boom(_: Inp) -> dict[str, Any]:
            raise RuntimeError("boom")

        flow = Flow(
            name="cost_boom",
            version="0.1.0",
            description="Always-failing flow.",
            steps=[FlowStep(tool_name="boom", input_mapping={"x": "x"})],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry, cost_profile=CostProfile())
        ex.register_tool(
            Tool(
                name="boom",
                description="Raises.",
                input_schema=Inp,
                output_schema=Out,
                fn=boom,
            )
        )

        result = ex.execute_flow("cost_boom", {"x": 1})
        assert result.success is False
        assert result.cost_report is not None
        # One step executed before failure; zero calls avoided.
        assert result.cost_report.steps_executed == 1
        assert result.cost_report.llm_calls_avoided == 0

    def test_report_serializes_with_result(self) -> None:
        ex = _build_two_step_executor(cost_profile=CostProfile())
        result = ex.execute_flow("cost_two_step", {"number": 1})
        payload = result.model_dump_json()
        assert "cost_report" in payload
        assert "llm_calls_avoided" in payload


# ---------------------------------------------------------------------------
# Provider price table (issue #156)
# ---------------------------------------------------------------------------


class TestProviderPriceTable:
    def test_table_is_non_empty_and_well_shaped(self) -> None:
        # Snapshot/structure test: every entry is a (provider, model) -> PriceSnap
        # with non-negative dated prices.
        assert PROVIDER_PRICES, "the provider price table must not be empty"
        for key, snap in PROVIDER_PRICES.items():
            assert isinstance(key, tuple) and len(key) == 2
            provider, model = key
            assert isinstance(provider, str) and provider
            assert isinstance(model, str) and model
            assert isinstance(snap, PriceSnap)
            assert snap.input_per_mtok >= 0.0
            assert snap.output_per_mtok >= 0.0
            # ISO-8601 YYYY-MM-DD shape (cheap structural check, not a parse).
            assert len(snap.as_of) == 10 and snap.as_of[4] == "-" and snap.as_of[7] == "-"

    def test_known_providers_present(self) -> None:
        # The cost-avoided pitch needs the major providers out of the box.
        assert ("openai", "gpt-4o") in PROVIDER_PRICES
        assert ("anthropic", "claude-opus-4-7") in PROVIDER_PRICES
        assert ("google", "gemini-2.5-pro") in PROVIDER_PRICES

    def test_lookup_price_returns_snapshot(self) -> None:
        snap = lookup_price("openai", "gpt-4o")
        assert snap.input_per_mtok == 2.50
        assert snap.output_per_mtok == 10.00
        assert snap.as_of == "2026-05-01"

    def test_lookup_price_unknown_pair_raises(self) -> None:
        with pytest.raises(CostProfileError) as exc_info:
            lookup_price("openai", "gpt-does-not-exist")
        err = exc_info.value
        assert err.provider == "openai"
        assert err.model == "gpt-does-not-exist"
        # Error lists the known pairs to help the caller recover.
        assert "openai:gpt-4o" in str(err)

    def test_blended_cost_even_split(self) -> None:
        snap = PriceSnap(input_per_mtok=2.0, output_per_mtok=10.0, as_of="2026-05-01")
        # Even split: (2 * 0.5 + 10 * 0.5) / 1e6 = 6 / 1e6.
        assert snap.blended_cost_per_token_usd(output_fraction=0.5) == 6.0 / 1_000_000.0
        # All-input: 2 / 1e6.
        assert snap.blended_cost_per_token_usd(output_fraction=0.0) == 2.0 / 1_000_000.0


class TestCostProfileFromProvider:
    def test_from_provider_records_source_and_as_of(self) -> None:
        profile = CostProfile.from_provider("anthropic", "claude-sonnet-4-6")
        assert profile.provider == "anthropic"
        assert profile.model == "claude-sonnet-4-6"
        assert profile.price_as_of == "2026-05-01"
        # Blended of (3, 15) at 50/50 = 9 / 1e6.
        assert profile.cost_per_token_usd == 9.0 / 1_000_000.0

    def test_from_provider_unknown_raises(self) -> None:
        with pytest.raises(CostProfileError):
            CostProfile.from_provider("nope", "nope")

    def test_default_profile_has_no_provider_metadata(self) -> None:
        profile = CostProfile()
        assert profile.provider is None
        assert profile.model is None
        assert profile.price_as_of is None


class TestComputeCostReportWithProvider:
    def test_provider_model_builds_priced_report(self) -> None:
        report = compute_cost_report(
            steps_executed=5,
            actual_execution_ms=12.0,
            provider="anthropic",
            model="claude-opus-4-7",
        )
        # 4 calls avoided * 750 tokens * (15*.5 + 75*.5)/1e6 = 4 * 750 * 45e-6 = 0.135
        assert report.llm_calls_avoided == 4
        assert report.cost_saved_usd == pytest.approx(0.135)
        # Non-zero dollars — the whole point of the maintained table.
        assert report.cost_saved_usd > 0.0
        assert report.profile.price_as_of == "2026-05-01"

    def test_report_str_surfaces_priced_against_line(self) -> None:
        report = compute_cost_report(
            steps_executed=3,
            actual_execution_ms=5.0,
            provider="openai",
            model="gpt-4o",
        )
        rendered = str(report)
        assert "Priced against:" in rendered
        assert "openai/gpt-4o" in rendered
        assert "2026-05-01" in rendered

    def test_no_profile_no_provider_falls_back_to_defaults(self) -> None:
        report = compute_cost_report(steps_executed=2, actual_execution_ms=1.0)
        assert report.profile.provider is None
        assert report.llm_calls_avoided == 1

    def test_unknown_provider_model_raises(self) -> None:
        with pytest.raises(CostProfileError):
            compute_cost_report(
                steps_executed=2,
                actual_execution_ms=1.0,
                provider="openai",
                model="ghost-model",
            )
