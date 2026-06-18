"""Shared machinery for optional provider :data:`LLMFn` adapters (issue #368).

The ``chainweaver.integrations.llm_*`` adapters wrap a provider SDK behind the
:class:`~chainweaver.proposals.StructuredLLMFn` seam, adding retry/backoff,
timeouts, spend ceilings, and usage accounting — while the base package stays
free of any provider SDK.  This module holds the provider-agnostic parts so
each adapter is a thin, single-call-site shim:

* :class:`LLMUsage` — running call/token/cost tally exposed as ``adapter.usage``.
* :class:`LLMFnOptions` — retry/timeout/ceiling configuration.
* :class:`ProviderAdapter` — a callable base that orchestrates ceiling checks,
  retry with exponential backoff + jitter, and usage recording around a
  subclass-supplied ``_invoke``.

Build-time only — never imported by :mod:`chainweaver.executor`.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field
from tenacity import (
    RetryError,
    Retrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_random_exponential,
)

from chainweaver.cost import PriceSnap, lookup_price
from chainweaver.exceptions import (
    CostProfileError,
    LLMBudgetExceededError,
    LLMProviderError,
)


@dataclass
class LLMUsage:
    """Running usage tally for a provider adapter instance (issue #368).

    Token counts are populated only when the provider reports them.  ``est_cost_usd``
    is a best-effort estimate from the maintained price table (issue #156) and
    is ``None`` when no price is known for the model.
    """

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    est_cost_usd: float | None = None

    def __str__(self) -> str:
        cost = "unknown" if self.est_cost_usd is None else f"{self.est_cost_usd:.4f}"
        return (
            f"calls={self.calls} input_tokens={self.input_tokens} "
            f"output_tokens={self.output_tokens} est_cost_usd={cost}"
        )


class LLMFnOptions(BaseModel):
    """Retry, timeout, and spend-ceiling options for a provider adapter (issue #368)."""

    model_config = ConfigDict(frozen=True)

    timeout_s: float | None = Field(default=60.0, gt=0.0)
    max_retries: int = Field(default=2, ge=0)
    max_output_tokens: int = Field(default=4096, gt=0)
    temperature: float | None = Field(default=None, ge=0.0)
    max_calls: int | None = Field(default=None, gt=0)
    max_cost_usd: float | None = Field(default=None, gt=0.0)


#: One completion: ``(text, input_tokens, output_tokens)``.  Token counts are
#: ``0`` when the provider does not report them.
Completion = tuple[str, int, int]


def _sleep(seconds: float) -> None:
    """Backoff sleep used between retries (monkeypatched to a no-op in tests)."""
    time.sleep(seconds)


def augment_prompt_for_json(prompt: str, json_schema: dict[str, Any] | None) -> str:
    """Append a JSON-conformance instruction when *json_schema* is supplied (issue #363).

    A uniform way for adapters to honour the :class:`StructuredLLMFn` seam even
    when the provider has no native schema-constrained mode: the schema is
    inlined into the prompt so the model returns conforming JSON.
    """
    if json_schema is None:
        return prompt
    return (
        f"{prompt}\n\nReturn only a JSON object conforming to this JSON Schema "
        f"(no prose, no code fence):\n{json.dumps(json_schema)}"
    )


class ProviderAdapter:
    """Callable base for provider :data:`LLMFn` adapters (issue #368).

    Subclasses implement :meth:`_invoke` (one provider call) and
    :attr:`_transient` (the exception types worth retrying).  Instances satisfy
    both the plain :data:`~chainweaver._offline_llm.LLMFn` and the
    :class:`~chainweaver.proposals.StructuredLLMFn` seam (``__call__`` accepts an
    optional ``json_schema``), and expose a live :attr:`usage` tally.
    """

    provider: str = "unknown"

    def __init__(self, *, model: str, options: LLMFnOptions | None = None) -> None:
        self.model = model
        self.options = options or LLMFnOptions()
        self.usage = LLMUsage()
        self._price: PriceSnap | None
        try:
            self._price = lookup_price(self.provider, model)
        except CostProfileError:
            self._price = None  # cost estimation simply unavailable for this model

    # -- subclass contract --------------------------------------------------

    def _invoke(self, prompt: str, json_schema: dict[str, Any] | None) -> Completion:
        raise NotImplementedError  # pragma: no cover — abstract

    @property
    def _transient(self) -> tuple[type[BaseException], ...]:
        return ()

    # -- orchestration ------------------------------------------------------

    def __call__(self, prompt: str, *, json_schema: dict[str, Any] | None = None) -> str:
        self._check_ceilings()
        text, input_tokens, output_tokens = self._invoke_with_retry(prompt, json_schema)
        self._record(input_tokens, output_tokens)
        return text

    def _check_ceilings(self) -> None:
        opts = self.options
        if opts.max_calls is not None and self.usage.calls >= opts.max_calls:
            raise LLMBudgetExceededError(
                self.provider, f"max_calls={opts.max_calls} already reached"
            )
        if (
            opts.max_cost_usd is not None
            and self.usage.est_cost_usd is not None
            and self.usage.est_cost_usd >= opts.max_cost_usd
        ):
            raise LLMBudgetExceededError(
                self.provider,
                f"estimated spend ${self.usage.est_cost_usd:.4f} reached "
                f"max_cost_usd=${opts.max_cost_usd:.4f}",
            )

    def _invoke_with_retry(self, prompt: str, json_schema: dict[str, Any] | None) -> Completion:
        retryer = Retrying(
            stop=stop_after_attempt(self.options.max_retries + 1),
            wait=wait_random_exponential(multiplier=1, max=30),
            retry=retry_if_exception_type(self._transient),
            sleep=_sleep,
            reraise=False,
        )
        try:
            return retryer(self._invoke, prompt, json_schema)
        except RetryError as exc:
            last = exc.last_attempt.exception()
            raise LLMProviderError(self.provider, f"call failed after retries: {last}") from last
        except self._transient as exc:  # pragma: no cover — reraise=False path
            raise LLMProviderError(self.provider, f"transient failure: {exc}") from exc

    def _record(self, input_tokens: int, output_tokens: int) -> None:
        self.usage.calls += 1
        self.usage.input_tokens += input_tokens
        self.usage.output_tokens += output_tokens
        if self._price is not None:
            cost = (
                input_tokens * self._price.input_per_mtok
                + output_tokens * self._price.output_per_mtok
            ) / 1_000_000
            self.usage.est_cost_usd = (self.usage.est_cost_usd or 0.0) + cost
