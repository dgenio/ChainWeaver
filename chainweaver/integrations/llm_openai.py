"""Optional OpenAI / OpenAI-compatible :data:`LLMFn` adapter (issue #368).

Drives the offline proposers against the OpenAI Chat Completions API — and,
via ``base_url``, any OpenAI-compatible endpoint (most local runtimes), so this
single adapter also covers self-hosted models.  Adds retry/backoff, a timeout,
spend ceilings, and usage accounting; the base package never imports ``openai``.

Optional extra
--------------

::

    pip install 'chainweaver[llm-openai]'

Example
-------

.. code-block:: python

    from chainweaver import optimize_tool_descriptions
    from chainweaver.integrations.llm_openai import openai_llm_fn

    # A local OpenAI-compatible runtime:
    llm = openai_llm_fn(model="llama-3.3-70b", base_url="http://localhost:11434/v1")
    proposals = optimize_tool_descriptions(tools, llm_fn=llm)
"""

from __future__ import annotations

from typing import Any

from chainweaver.integrations._llm_common import (
    Completion,
    LLMFnOptions,
    ProviderAdapter,
    augment_prompt_for_json,
)

__all__ = ["OpenAILLM", "openai_llm_fn"]


def _import_openai() -> Any:
    try:
        import openai
    except ImportError as exc:  # pragma: no cover — depends on install layout
        raise ImportError(
            "chainweaver.integrations.llm_openai requires the 'openai' SDK. "
            "Install with: pip install 'chainweaver[llm-openai]'."
        ) from exc
    return openai


class OpenAILLM(ProviderAdapter):
    """A :class:`~chainweaver.proposals.StructuredLLMFn` backed by OpenAI Chat Completions."""

    provider = "openai"

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
        if json_schema is not None:
            # Native JSON mode where the endpoint supports it.
            kwargs["response_format"] = {"type": "json_object"}
        resp = self._client.chat.completions.create(**kwargs)
        text = resp.choices[0].message.content or ""
        usage = getattr(resp, "usage", None)
        input_tokens = int(getattr(usage, "prompt_tokens", 0) or 0)
        output_tokens = int(getattr(usage, "completion_tokens", 0) or 0)
        return text, input_tokens, output_tokens


def openai_llm_fn(
    model: str,
    *,
    client: Any | None = None,
    base_url: str | None = None,
    timeout_s: float | None = 60.0,
    max_retries: int = 2,
    max_output_tokens: int = 4096,
    temperature: float | None = None,
    max_calls: int | None = None,
    max_cost_usd: float | None = None,
) -> OpenAILLM:
    """Build an OpenAI (or OpenAI-compatible) adapter for the proposer seam (issue #368).

    Args:
        model: Model id understood by the target endpoint.
        client: An ``openai.OpenAI``-compatible client.  When ``None`` a default
            client is constructed (requires the ``openai`` SDK; ``base_url``
            points it at any compatible endpoint, including local runtimes).
        base_url: Optional base URL for an OpenAI-compatible endpoint.
        timeout_s: Per-call timeout passed to the SDK.
        max_retries: Retries (beyond the first attempt) on transient/rate-limit
            errors, with exponential backoff + jitter.
        max_output_tokens: ``max_tokens`` for each completion.
        temperature: Optional sampling temperature.
        max_calls: Hard ceiling on calls for this adapter instance.
        max_cost_usd: Estimated-spend ceiling (priced from the maintained table).

    Returns:
        An :class:`OpenAILLM` callable exposing a live ``.usage`` tally.
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
        openai = _import_openai()
        client = openai.OpenAI(base_url=base_url)
        transient = (
            openai.RateLimitError,
            openai.APITimeoutError,
            openai.APIConnectionError,
            openai.InternalServerError,
        )
    return OpenAILLM(model=model, client=client, transient=transient, options=options)
