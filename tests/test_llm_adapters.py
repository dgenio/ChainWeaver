"""Tests for the optional provider LLM adapters (issue #368).

All tests use fake clients — no provider SDK is imported and no network call is
made.  Backoff sleeping is patched to a no-op so retry paths run instantly.
"""

from __future__ import annotations

import sys
from typing import Any

import pytest
from pydantic import BaseModel

from chainweaver.compiler_llm import llm_propose_flows
from chainweaver.exceptions import LLMBudgetExceededError, LLMProviderError
from chainweaver.integrations import _llm_common
from chainweaver.integrations.llm_anthropic import AnthropicLLM, anthropic_llm_fn
from chainweaver.integrations.llm_openai import OpenAILLM, openai_llm_fn
from chainweaver.proposals import StructuredLLMFn
from chainweaver.tools import Tool


@pytest.fixture(autouse=True)
def _no_backoff_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_llm_common, "_sleep", lambda _seconds: None)


class Transient(Exception):
    """Stand-in transient error for retry classification tests."""


# ---------------------------------------------------------------------------
# Fake provider clients
# ---------------------------------------------------------------------------


class _Usage:
    def __init__(self, *, anthropic: bool, in_tok: int, out_tok: int) -> None:
        if anthropic:
            self.input_tokens = in_tok
            self.output_tokens = out_tok
        else:
            self.prompt_tokens = in_tok
            self.completion_tokens = out_tok


class _AnthropicResp:
    def __init__(self, text: str, in_tok: int, out_tok: int) -> None:
        self.content = [type("Block", (), {"text": text})()]
        self.usage = _Usage(anthropic=True, in_tok=in_tok, out_tok=out_tok)


class FakeAnthropicClient:
    """Minimal anthropic.Anthropic stand-in. Each script item is a resp or an exception."""

    def __init__(self, *script: Any) -> None:
        self._script = list(script)
        self.calls: list[dict[str, Any]] = []

    @property
    def messages(self) -> FakeAnthropicClient:
        return self

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


class _OpenAIResp:
    def __init__(self, text: str, in_tok: int, out_tok: int) -> None:
        msg = type("Msg", (), {"content": text})()
        self.choices = [type("Choice", (), {"message": msg})()]
        self.usage = _Usage(anthropic=False, in_tok=in_tok, out_tok=out_tok)


class FakeOpenAIClient:
    def __init__(self, *script: Any) -> None:
        self._script = list(script)
        self.calls: list[dict[str, Any]] = []

    @property
    def chat(self) -> FakeOpenAIClient:
        return self

    @property
    def completions(self) -> FakeOpenAIClient:
        return self

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        item = self._script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


# ---------------------------------------------------------------------------
# Basic call + usage accounting
# ---------------------------------------------------------------------------


def test_anthropic_basic_call_and_usage() -> None:
    client = FakeAnthropicClient(_AnthropicResp("hello", 100, 20))
    # claude-sonnet-4-6 is not necessarily in the price table; use a priced model.
    llm = anthropic_llm_fn("claude-opus-4-7", client=client)
    assert isinstance(llm, AnthropicLLM)
    assert llm("a prompt") == "hello"
    assert llm.usage.calls == 1
    assert llm.usage.input_tokens == 100
    assert llm.usage.output_tokens == 20


def test_openai_basic_call_and_usage() -> None:
    client = FakeOpenAIClient(_OpenAIResp("world", 50, 10))
    llm = openai_llm_fn("gpt-4o", client=client)
    assert isinstance(llm, OpenAILLM)
    assert llm("p") == "world"
    assert llm.usage.input_tokens == 50
    assert llm.usage.output_tokens == 10


def test_usage_accumulates_and_estimates_cost() -> None:
    client = FakeAnthropicClient(
        _AnthropicResp("one", 1_000_000, 0),
        _AnthropicResp("two", 0, 1_000_000),
    )
    llm = anthropic_llm_fn("claude-opus-4-7", client=client)
    llm("a")
    llm("b")
    assert llm.usage.calls == 2
    assert llm.usage.input_tokens == 1_000_000
    assert llm.usage.output_tokens == 1_000_000
    # claude-opus-4-7 priced at input 15.00 / output 75.00 per Mtok → 90.00 total.
    assert llm.usage.est_cost_usd == pytest.approx(90.0)


def test_unknown_model_leaves_cost_none() -> None:
    client = FakeAnthropicClient(_AnthropicResp("x", 10, 10))
    llm = anthropic_llm_fn("totally-unknown-model", client=client)
    llm("p")
    assert llm.usage.est_cost_usd is None


def test_usage_str_format() -> None:
    usage = _llm_common.LLMUsage(calls=2, input_tokens=8431, output_tokens=912, est_cost_usd=0.04)
    assert str(usage) == "calls=2 input_tokens=8431 output_tokens=912 est_cost_usd=0.0400"


# ---------------------------------------------------------------------------
# Structured-output seam (#363 / #368)
# ---------------------------------------------------------------------------


def test_adapter_satisfies_structured_seam_and_augments_prompt() -> None:
    client = FakeAnthropicClient(_AnthropicResp("{}", 1, 1))
    llm = anthropic_llm_fn("claude-opus-4-7", client=client)
    assert isinstance(llm, StructuredLLMFn)
    llm("base prompt", json_schema={"type": "object"})
    sent = client.calls[0]["messages"][0]["content"]
    assert "base prompt" in sent
    assert "JSON Schema" in sent


def test_openai_sets_json_response_format() -> None:
    client = FakeOpenAIClient(_OpenAIResp("{}", 1, 1))
    llm = openai_llm_fn("gpt-4o", client=client)
    llm("p", json_schema={"type": "object"})
    assert client.calls[0]["response_format"] == {"type": "json_object"}


# ---------------------------------------------------------------------------
# Retry / backoff
# ---------------------------------------------------------------------------


def test_retries_transient_then_succeeds() -> None:
    client = FakeAnthropicClient(Transient("rate limited"), _AnthropicResp("ok", 1, 1))
    llm = AnthropicLLM(
        model="claude-opus-4-7",
        client=client,
        transient=(Transient,),
        options=_llm_common.LLMFnOptions(max_retries=2),
    )
    assert llm("p") == "ok"
    assert len(client.calls) == 2  # one failure + one success


def test_retries_exhausted_raises_provider_error() -> None:
    client = FakeAnthropicClient(Transient("a"), Transient("b"), Transient("c"))
    llm = AnthropicLLM(
        model="claude-opus-4-7",
        client=client,
        transient=(Transient,),
        options=_llm_common.LLMFnOptions(max_retries=2),
    )
    with pytest.raises(LLMProviderError) as exc:
        llm("p")
    assert exc.value.provider == "anthropic"
    assert len(client.calls) == 3  # max_retries=2 → 3 attempts total


def test_non_transient_error_is_not_retried() -> None:
    client = FakeAnthropicClient(ValueError("hard failure"))
    llm = AnthropicLLM(
        model="claude-opus-4-7",
        client=client,
        transient=(Transient,),
        options=_llm_common.LLMFnOptions(max_retries=3),
    )
    with pytest.raises(ValueError, match="hard failure"):
        llm("p")
    assert len(client.calls) == 1  # not retried


# ---------------------------------------------------------------------------
# Spend ceilings (#368)
# ---------------------------------------------------------------------------


def test_max_calls_ceiling_aborts_before_call() -> None:
    client = FakeAnthropicClient(_AnthropicResp("one", 1, 1))  # only one response scripted
    llm = anthropic_llm_fn("claude-opus-4-7", client=client, max_calls=1)
    llm("first")  # consumes the single allowance
    with pytest.raises(LLMBudgetExceededError) as exc:
        llm("second")  # would exceed max_calls
    assert exc.value.provider == "anthropic"
    assert len(client.calls) == 1  # the second call never reached the client


def test_max_cost_ceiling_aborts_before_next_call() -> None:
    client = FakeAnthropicClient(
        _AnthropicResp("one", 1_000_000, 0),  # ~ $15 (input 15/Mtok)
        _AnthropicResp("two", 1, 1),
    )
    llm = anthropic_llm_fn("claude-opus-4-7", client=client, max_cost_usd=1.00)
    llm("first")  # pushes est_cost_usd well over the ceiling
    with pytest.raises(LLMBudgetExceededError):
        llm("second")
    assert len(client.calls) == 1


# ---------------------------------------------------------------------------
# Missing-extra import error pattern (#368)
# ---------------------------------------------------------------------------


def test_anthropic_without_sdk_raises_install_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    # Force ``import anthropic`` to fail regardless of the environment's install
    # state, then assert the documented install-the-extra error is raised.
    monkeypatch.setitem(sys.modules, "anthropic", None)
    with pytest.raises(ImportError, match=r"chainweaver\[llm-anthropic\]"):
        anthropic_llm_fn("claude-opus-4-7")


def test_openai_without_sdk_raises_install_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "openai", None)
    with pytest.raises(ImportError, match=r"chainweaver\[llm-openai\]"):
        openai_llm_fn("gpt-4o")


# ---------------------------------------------------------------------------
# End-to-end with the proposers (#368)
# ---------------------------------------------------------------------------


class _QueryIn(BaseModel):
    query: str


class _ResultsOut(BaseModel):
    results: str


def _noop(inp: Any) -> dict[str, Any]:
    return {}


_FLOW_JSON = """
{"proposals": [{"flow": {"type": "Flow", "name": "just_search", "version": "0.0.0",
"description": "Search.", "steps": [{"tool_name": "search", "input_mapping": {"query": "query"}}]},
"rationale": "trivial", "confidence": 0.8}]}
"""


def test_adapter_drives_llm_propose_flows_end_to_end() -> None:
    search = Tool(
        name="search",
        description="Search.",
        input_schema=_QueryIn,
        output_schema=_ResultsOut,
        fn=_noop,
    )
    client = FakeAnthropicClient(_AnthropicResp(_FLOW_JSON, 200, 30))
    llm = anthropic_llm_fn("claude-opus-4-7", client=client)
    proposals = llm_propose_flows([search], llm_fn=llm)
    assert len(proposals) == 1
    assert proposals[0].proposed_flow.name == "just_search"
    # The adapter received the published schema (StructuredLLMFn path) and tallied usage.
    assert "JSON Schema" in client.calls[0]["messages"][0]["content"]
    assert llm.usage.calls == 1
