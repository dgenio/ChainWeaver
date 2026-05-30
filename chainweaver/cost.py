"""Cost-avoided estimation for ChainWeaver flows.

ChainWeaver's value proposition is eliminating intermediate LLM calls — saving
cost and latency.  :class:`CostProfile` captures the user's assumptions about
typical LLM call cost and latency; :class:`CostReport` reports the resulting
estimate against an executed flow.

All values are clearly labelled as **estimates** in human-readable output:
they depend entirely on the configured profile.

A maintained, dated provider price table (:data:`PROVIDER_PRICES`, issue #156)
lets callers derive a :class:`CostProfile` from real per-model pricing via
:meth:`CostProfile.from_provider` so the "cost avoided" figure lands with
credible dollars instead of a hand-wired token rate.  The table ships in the
source tree — there is **no live HTTP lookup at runtime** — and every report
built from it surfaces the snapshot's ``as_of`` date so stale prices are
visible.  Refresh it via :mod:`scripts.refresh_prices` /
``.github/workflows/update-prices.yml`` (a maintainer-reviewed PR, never
auto-merged).
"""

from __future__ import annotations

from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from chainweaver.exceptions import CostProfileError


class PriceSnap(BaseModel):
    """A dated per-million-token price snapshot for one provider/model (issue #156).

    Prices are quoted per *million* tokens (the unit providers publish) and
    are split into input (prompt) and output (completion) rates because the two
    differ by 3-5x on most frontier models.  The ``as_of`` date records when
    the snapshot was taken so consumers can decide whether it is stale.

    Attributes:
        input_per_mtok: USD per 1,000,000 input (prompt) tokens.
        output_per_mtok: USD per 1,000,000 output (completion) tokens.
        as_of: ISO-8601 date (``YYYY-MM-DD``) the price was captured.
    """

    model_config = ConfigDict(frozen=True)

    input_per_mtok: float = Field(ge=0.0)
    output_per_mtok: float = Field(ge=0.0)
    as_of: str

    def blended_cost_per_token_usd(self, *, output_fraction: float = 0.5) -> float:
        """Collapse the input/output split into one blended per-token USD cost.

        Args:
            output_fraction: Fraction of tokens assumed to be output
                (completion) tokens; the remainder are input tokens.  Defaults
                to ``0.5`` (an even split) — callers with a better mix should
                override it.

        Returns:
            The blended USD cost of a single token.

        Raises:
            ValueError: When ``output_fraction`` is outside ``[0.0, 1.0]``;
                out-of-range values would yield a negative or inflated blended
                cost.
        """
        if not 0.0 <= output_fraction <= 1.0:
            raise ValueError(f"'output_fraction' must be in [0.0, 1.0], got {output_fraction}.")
        input_fraction = 1.0 - output_fraction
        per_mtok = self.input_per_mtok * input_fraction + self.output_per_mtok * output_fraction
        return per_mtok / 1_000_000.0


# Hand-curated, dated price snapshots for the major LLM providers (issue #156).
#
# These are maintained by hand and refreshed via a reviewed PR — never a live
# runtime lookup (that would break offline use and the executor's spirit).
# Keep the ``as_of`` dates current at release time; ``scripts/refresh_prices.py``
# and ``.github/workflows/update-prices.yml`` open a maintainer-reviewed PR.
#
# Sources: each provider's public pricing page as of the ``as_of`` date.
PROVIDER_PRICES: Mapping[tuple[str, str], PriceSnap] = MappingProxyType(
    {
        ("openai", "gpt-4o"): PriceSnap(
            input_per_mtok=2.50, output_per_mtok=10.00, as_of="2026-05-01"
        ),
        ("openai", "gpt-4o-mini"): PriceSnap(
            input_per_mtok=0.15, output_per_mtok=0.60, as_of="2026-05-01"
        ),
        ("anthropic", "claude-opus-4-7"): PriceSnap(
            input_per_mtok=15.00, output_per_mtok=75.00, as_of="2026-05-01"
        ),
        ("anthropic", "claude-sonnet-4-6"): PriceSnap(
            input_per_mtok=3.00, output_per_mtok=15.00, as_of="2026-05-01"
        ),
        ("anthropic", "claude-haiku-4-5"): PriceSnap(
            input_per_mtok=0.80, output_per_mtok=4.00, as_of="2026-05-01"
        ),
        ("google", "gemini-2.5-pro"): PriceSnap(
            input_per_mtok=1.25, output_per_mtok=10.00, as_of="2026-05-01"
        ),
        ("google", "gemini-2.5-flash"): PriceSnap(
            input_per_mtok=0.30, output_per_mtok=2.50, as_of="2026-05-01"
        ),
        ("aws-bedrock", "claude-opus-4-7"): PriceSnap(
            input_per_mtok=15.00, output_per_mtok=75.00, as_of="2026-05-01"
        ),
    }
)


def lookup_price(provider: str, model: str) -> PriceSnap:
    """Return the :class:`PriceSnap` for ``(provider, model)`` (issue #156).

    Args:
        provider: Provider key (e.g. ``"openai"``, ``"anthropic"``).
        model: Model key (e.g. ``"gpt-4o"``, ``"claude-opus-4-7"``).

    Returns:
        The maintained :class:`PriceSnap` for that pair.

    Raises:
        CostProfileError: When the pair is not present in
            :data:`PROVIDER_PRICES`.
    """
    snap = PROVIDER_PRICES.get((provider, model))
    if snap is None:
        known = ", ".join(sorted(f"{p}:{m}" for p, m in PROVIDER_PRICES))
        raise CostProfileError(provider, model, f"known pairs are [{known}]")
    return snap


class CostProfile(BaseModel):
    """LLM cost / latency assumptions used to estimate avoided cost.

    Defaults are loosely modelled on a small frontier model (e.g. GPT-4o-mini
    pricing as of late 2024) and are intended as a reasonable starting point;
    callers are expected to override them when they have better data, or build
    a profile from the maintained price table via :meth:`from_provider`.

    Attributes:
        avg_llm_latency_ms: Average wall-clock round-trip time of one LLM
            call, in milliseconds.
        avg_tokens_per_call: Average tokens consumed per inter-step routing
            call.
        cost_per_token_usd: USD cost per token (input + output combined).
        provider: Provider key the profile was derived from, or ``None`` for a
            hand-configured profile (issue #156).
        model: Model key the profile was derived from, or ``None`` (issue #156).
        price_as_of: ``as_of`` date of the :class:`PriceSnap` the profile was
            built from, or ``None`` when no maintained price was used. Surfaced
            on every :class:`CostReport` so stale prices are visible (issue #156).
    """

    model_config = ConfigDict(frozen=True)

    avg_llm_latency_ms: float = Field(default=300.0, ge=0.0)
    avg_tokens_per_call: float = Field(default=750.0, ge=0.0)
    cost_per_token_usd: float = Field(default=0.00004, ge=0.0)
    provider: str | None = None
    model: str | None = None
    price_as_of: str | None = None

    @classmethod
    def from_provider(
        cls,
        provider: str,
        model: str,
        *,
        avg_tokens_per_call: float = 750.0,
        output_fraction: float = 0.5,
        avg_llm_latency_ms: float = 300.0,
    ) -> CostProfile:
        """Build a :class:`CostProfile` from the maintained price table (issue #156).

        Args:
            provider: Provider key (e.g. ``"anthropic"``).
            model: Model key (e.g. ``"claude-opus-4-7"``).
            avg_tokens_per_call: Average tokens per inter-step routing call.
            output_fraction: Fraction of those tokens assumed to be output
                (completion) tokens; drives the blended per-token cost.
            avg_llm_latency_ms: Average round-trip latency assumption.

        Returns:
            A frozen :class:`CostProfile` whose ``cost_per_token_usd`` is the
            blended rate from the snapshot and whose ``provider`` / ``model`` /
            ``price_as_of`` record the source.

        Raises:
            CostProfileError: When ``(provider, model)`` is unknown.
        """
        snap = lookup_price(provider, model)
        return cls(
            avg_llm_latency_ms=avg_llm_latency_ms,
            avg_tokens_per_call=avg_tokens_per_call,
            cost_per_token_usd=snap.blended_cost_per_token_usd(output_fraction=output_fraction),
            provider=provider,
            model=model,
            price_as_of=snap.as_of,
        )


class CostReport(BaseModel):
    """Estimated savings from compiled flow execution.

    The numbers are estimates derived from a :class:`CostProfile`; they
    reflect what a naive agent that calls an LLM between every tool step
    would *additionally* spend.  ChainWeaver itself never calls an LLM.

    Attributes:
        steps_executed: Number of *tool* steps that ran during the
            execution (excludes the synthetic flow-level
            schema-validation records that may be appended on input or
            output validation failure).  Threaded through from
            ``FlowExecutor._make_result``; falls back to
            ``len(execution_log)`` only when the caller didn't supply a
            tool-step count.
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
        lines = [
            "Cost Avoided Report (estimate)",
            "──────────────────────────────",
            f"Steps executed:          {self.steps_executed}",
            f"LLM calls avoided:       {self.llm_calls_avoided}",
            f"Est. latency saved:      {self.latency_saved_ms:.1f}ms",
            f"Est. cost saved:         ${self.cost_saved_usd:.4f}",
            f"Actual execution time:   {self.actual_execution_ms:.1f}ms",
        ]
        if (
            self.profile.provider is not None
            and self.profile.model is not None
            and self.profile.price_as_of is not None
        ):
            lines.append(
                f"Priced against:          {self.profile.provider}/{self.profile.model} "
                f"(as of {self.profile.price_as_of})"
            )
        return "\n".join(lines)


def compute_cost_report(
    *,
    steps_executed: int,
    actual_execution_ms: float,
    profile: CostProfile | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> CostReport:
    """Compute a :class:`CostReport` from execution metadata and a profile.

    Args:
        steps_executed: Number of *tool* steps executed (excluding any
            flow-level schema-validation records).  This matches the
            ``tool_step_count`` threaded by
            ``FlowExecutor._make_result``.
        actual_execution_ms: Wall-clock duration of the execution.
        profile: The :class:`CostProfile` providing per-call assumptions.  When
            omitted, a profile is built from ``provider`` / ``model`` (if both
            are given, via :meth:`CostProfile.from_provider`, issue #156) or
            the :class:`CostProfile` defaults otherwise.
        provider: Optional provider key for the maintained price table; used
            only when ``profile`` is ``None``.
        model: Optional model key for the maintained price table; used only
            when ``profile`` is ``None``.

    Returns:
        A populated :class:`CostReport`.

    Raises:
        ValueError: When exactly one of ``provider`` / ``model`` is supplied
            (without an explicit ``profile``); the two must be given together
            or not at all.
        CostProfileError: When ``provider`` / ``model`` are supplied (without an
            explicit ``profile``) but the pair is unknown.
    """
    if profile is None:
        if (provider is None) != (model is None):
            raise ValueError("'provider' and 'model' must be supplied together or not at all.")
        if provider is not None and model is not None:
            profile = CostProfile.from_provider(provider, model)
        else:
            profile = CostProfile()
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
