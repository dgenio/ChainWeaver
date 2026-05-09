"""Cost-avoided estimation for ChainWeaver flows.

ChainWeaver's value proposition is eliminating intermediate LLM calls — saving
cost and latency.  :class:`CostProfile` captures the user's assumptions about
typical LLM call cost and latency; :class:`CostReport` reports the resulting
estimate against an executed flow.

All values are clearly labelled as **estimates** in human-readable output:
they depend entirely on the configured profile.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CostProfile(BaseModel):
    """LLM cost / latency assumptions used to estimate avoided cost.

    Defaults are loosely modelled on a small frontier model (e.g. GPT-4o-mini
    pricing as of late 2024) and are intended as a reasonable starting point;
    callers are expected to override them when they have better data.

    Attributes:
        avg_llm_latency_ms: Average wall-clock round-trip time of one LLM
            call, in milliseconds.
        avg_tokens_per_call: Average tokens consumed per inter-step routing
            call.
        cost_per_token_usd: USD cost per token (input + output combined).
    """

    model_config = ConfigDict(frozen=True)

    avg_llm_latency_ms: float = Field(default=300.0, ge=0.0)
    avg_tokens_per_call: float = Field(default=750.0, ge=0.0)
    cost_per_token_usd: float = Field(default=0.00004, ge=0.0)


class CostReport(BaseModel):
    """Estimated savings from compiled flow execution.

    The numbers are estimates derived from a :class:`CostProfile`; they
    reflect what a naive agent that calls an LLM between every tool step
    would *additionally* spend.  ChainWeaver itself never calls an LLM.

    Attributes:
        steps_executed: Total number of steps recorded in the execution log.
        llm_calls_avoided: ``max(0, steps_executed - 1)`` — one LLM call is
            assumed avoided per inter-step transition.
        latency_saved_ms: ``llm_calls_avoided *profile.avg_llm_latency_ms``.
        cost_saved_usd: ``llm_calls_avoided * profile.avg_tokens_per_call *
            profile.cost_per_token_usd``.
        actual_execution_ms: Wall-clock time spent inside ``execute_flow``,
            taken from ``ExecutionResult.total_duration_ms``.
        profile: The :class:`CostProfile` that produced this report.
    """

    model_config = ConfigDict(frozen=True)

    steps_executed: int
    llm_calls_avoided: int
    latency_saved_ms: float
    cost_saved_usd: float
    actual_execution_ms: float
    profile: CostProfile

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable dictionary representation."""
        return self.model_dump()

    def __str__(self) -> str:
        return (
            "Cost Avoided Report (estimate)\n"
            "──────────────────────────────\n"
            f"Steps executed:          {self.steps_executed}\n"
            f"LLM calls avoided:       {self.llm_calls_avoided}\n"
            f"Est. latency saved:      {self.latency_saved_ms:.1f}ms\n"
            f"Est. cost saved:         ${self.cost_saved_usd:.4f}\n"
            f"Actual execution time:   {self.actual_execution_ms:.1f}ms"
        )


def compute_cost_report(
    *,
    steps_executed: int,
    actual_execution_ms: float,
    profile: CostProfile,
) -> CostReport:
    """Compute a :class:`CostReport` from execution metadata and a profile.

    Args:
        steps_executed: Number of steps recorded in the execution log.
        actual_execution_ms: Wall-clock duration of the execution.
        profile: The :class:`CostProfile` providing per-call assumptions.

    Returns:
        A populated :class:`CostReport`.
    """
    llm_calls_avoided = max(0, steps_executed - 1)
    latency_saved_ms = llm_calls_avoided * profile.avg_llm_latency_ms
    cost_saved_usd = llm_calls_avoided * profile.avg_tokens_per_call * profile.cost_per_token_usd
    return CostReport(
        steps_executed=steps_executed,
        llm_calls_avoided=llm_calls_avoided,
        latency_saved_ms=latency_saved_ms,
        cost_saved_usd=cost_saved_usd,
        actual_execution_ms=actual_execution_ms,
        profile=profile,
    )
