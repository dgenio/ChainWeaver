"""Optional Anthropic :data:`LLMFn` adapter for the offline proposers (issue #368).

Produces a callable that drives :func:`~chainweaver.llm_propose_flows` and
:func:`~chainweaver.optimize_tool_descriptions` against the Anthropic Messages
API, with retry/backoff, a timeout, spend ceilings, and usage accounting.  The
base package never imports ``anthropic``; this module does so lazily.

Optional extra
--------------

::

    pip install 'chainweaver[llm-anthropic]'

Example
-------

.. code-block:: python

    from chainweaver import llm_propose_flows
    from chainweaver.integrations.llm_anthropic import anthropic_llm_fn

    llm = anthropic_llm_fn(model="claude-sonnet-4-6", max_calls=10, max_cost_usd=1.00)
    proposals = llm_propose_flows(tools, llm_fn=llm)
    print(llm.usage)  # calls=2 input_tokens=8431 output_tokens=912 est_cost_usd=0.0412
"""

from __future__ import annotations

from typing import Any

from chainweaver.integrations._llm_common import (
    Completion,
    LLMFnOptions,
    ProviderAdapter,
    augment_prompt_for_json,
)

__all__ = ["AnthropicLLM", "anthropic_llm_fn"]


def _import_anthropic() -> Any:
    try:
        import anthropic
    except ImportError as exc:  # pragma: no cover — depends on install layout
        raise ImportError(
            "chainweaver.integrations.llm_anthropic requires the 'anthropic' SDK. "
            "Install with: pip install 'chainweaver[llm-anthropic]'."
        ) from exc
    return anthropic


class AnthropicLLM(ProviderAdapter):
    """A :class:`~chainweaver.proposals.StructuredLLMFn` backed by Anthropic Messages."""

    provider = "anthropic"

    def __init__(
        self,
        *,
        model: str,
        client: Any,
        transient: tuple[type[BaseException], ...] = (),
        options: LLMFnOptions | None = None,
    ) -> None:
        super().__init__(model=model, options=options)
        self._client = client
        self._transient_types = transient

    @property
    def _transient(self) -> tuple[type[BaseException], ...]:
        return self._transient_types

    def _invoke(self, prompt: str, json_schema: dict[str, Any] | None) -> Completion:
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": self.options.max_output_tokens,
            "messages": [
                {"role": "user", "content": augment_prompt_for_json(prompt, json_schema)}
            ],
        }
        if self.options.temperature is not None:
            kwargs["temperature"] = self.options.temperature
        if self.options.timeout_s is not None:
            kwargs["timeout"] = self.options.timeout_s
        resp = self._client.messages.create(**kwargs)
        text = resp.content[0].text
        usage = getattr(resp, "usage", None)
        input_tokens = int(getattr(usage, "input_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "output_tokens", 0) or 0)
        return text, input_tokens, output_tokens


def anthropic_llm_fn(
    model: str,
    *,
    client: Any | None = None,
    timeout_s: float | None = 60.0,
    max_retries: int = 2,
    max_output_tokens: int = 4096,
    temperature: float | None = None,
    max_calls: int | None = None,
    max_cost_usd: float | None = None,
) -> AnthropicLLM:
    """Build an Anthropic-backed adapter satisfying the proposer LLM seam (issue #368).

    Args:
        model: Anthropic model id (e.g. ``"claude-sonnet-4-6"``).
        client: An ``anthropic.Anthropic``-compatible client.  When ``None`` a
            default client is constructed (requires the ``anthropic`` SDK and
            credentials in the environment).
        timeout_s: Per-call timeout passed to the SDK.
        max_retries: Retries (beyond the first attempt) on transient/rate-limit
            errors, with exponential backoff + jitter.
        max_output_tokens: ``max_tokens`` for each completion.
        temperature: Optional sampling temperature.
        max_calls: Hard ceiling on calls for this adapter instance.
        max_cost_usd: Estimated-spend ceiling (priced from the maintained table).

    Returns:
        An :class:`AnthropicLLM` callable exposing a live ``.usage`` tally.
    """
    options = LLMFnOptions(
        timeout_s=timeout_s,
        max_retries=max_retries,
        max_output_tokens=max_output_tokens,
        temperature=temperature,
        max_calls=max_calls,
        max_cost_usd=max_cost_usd,
    )
    transient: tuple[type[BaseException], ...] = ()
    if client is None:
        anthropic = _import_anthropic()
        client = anthropic.Anthropic()
        transient = (
            anthropic.RateLimitError,
            anthropic.APITimeoutError,
            anthropic.APIConnectionError,
            anthropic.InternalServerError,
        )
    return AnthropicLLM(model=model, client=client, transient=transient, options=options)
