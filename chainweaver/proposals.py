"""Shared structured-output, provenance, and prompt-budget primitives for the
offline LLM proposers (issues #363, #364, #367).

:mod:`chainweaver.compiler_llm` (proposes *flows*, issue #28) and
:mod:`chainweaver.optimizer` (proposes *description rewrites*, issue #100) share
the same provider seam and the same hardening needs.  This module hosts the
machinery they have in common so neither reimplements it:

* **Provenance (#364)** — :class:`ModelInfo` and :class:`ProposalProvenance`
  record *which prompt* (name, version, content hash) and *which model* (caller
  asserted) produced a proposal, plus repair usage and catalogue stats, so a
  promoted flow's origin is auditable and prompt revisions are comparable.
* **Structured output + repair (#363)** — :class:`StructuredLLMFn` lets a
  provider receive a JSON Schema; :func:`run_with_repair` issues one bounded
  follow-up call carrying the validation error when a completion is malformed.
  A plain :data:`~chainweaver._offline_llm.LLMFn` keeps working unchanged.
* **Prompt budget (#367)** — :class:`PromptBudget` and :func:`apply_budget`
  estimate the assembled prompt size and apply an overflow strategy
  (``error`` / ``truncate`` / ``batch`` / ``select``) before any LLM call.

Like the modules that import it, this is **build-time only** — never imported by
:mod:`chainweaver.executor`.
"""

from __future__ import annotations

import hashlib
import inspect
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from typing import Any, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from chainweaver._offline_llm import LLMFn
from chainweaver.exceptions import OfflineLLMError, PromptBudgetExceededError
from chainweaver.tools import Tool

__all__ = [
    "ModelInfo",
    "PromptBudget",
    "ProposalProvenance",
    "StructuredLLMFn",
    "estimate_tokens",
    "template_sha256",
]


@runtime_checkable
class StructuredLLMFn(Protocol):
    """A provider-agnostic LLM call that accepts a JSON Schema (issue #363).

    The richer counterpart to :data:`~chainweaver._offline_llm.LLMFn`: callers
    whose provider supports schema-constrained generation implement this so the
    proposers can request JSON that conforms to a published envelope schema.
    The proposers detect which seam they were given (by signature) and fall
    back to the plain :data:`LLMFn` contract otherwise.
    """

    def __call__(self, prompt: str, *, json_schema: dict[str, Any]) -> str: ...


class ModelInfo(BaseModel):
    """Caller-asserted identity of the model behind an :data:`LLMFn` (issue #364).

    The :data:`LLMFn` seam hides the provider by design, so model identity is
    *asserted by the caller*, not verified.  Treat it as provenance metadata,
    not ground truth.
    """

    model_config = ConfigDict(frozen=True)

    provider: str | None = None
    model: str | None = None


class ProposalProvenance(BaseModel):
    """Generation metadata attached to every offline proposal (issue #364).

    Records the prompt template (name, version, content hash), the
    caller-asserted model, generation parameters, repair usage, the ChainWeaver
    version, and prompt-budget catalogue stats.  Persisted alongside proposals
    so a promoted flow's origin is auditable and prompt revisions are
    attributable.
    """

    model_config = ConfigDict(frozen=True)

    prompt_name: str
    prompt_version: str
    prompt_sha256: str
    model: ModelInfo | None = None
    parameters: dict[str, Any] | None = None
    generated_at: str
    repair_attempts_used: int = Field(default=0, ge=0)
    chainweaver_version: str
    catalogue_tools_total: int | None = None
    catalogue_tools_rendered: int | None = None
    estimated_prompt_tokens: int | None = None


class PromptBudget(BaseModel):
    """A token budget and overflow strategy for proposer prompt assembly (issue #367).

    Attributes:
        max_tokens: Estimated-token ceiling for the assembled prompt.
        overflow: What to do when the catalogue overflows the budget:

            * ``"error"`` (default) — raise :class:`PromptBudgetExceededError`
              before any LLM call.
            * ``"truncate"`` — cap per-tool descriptions, then drop trailing
              tools deterministically until the prompt fits.
            * ``"batch"`` — split the catalogue into budget-sized batches, run
              the proposer per batch, and merge the results.
            * ``"select"`` — apply :attr:`selector` to pick a relevant subset
              first (a seam for embedding-based selection), then behave like
              ``"error"`` on the reduced set.
        max_description_chars: Description cap used by the ``truncate`` strategy.
            ``None`` falls back to :data:`_TRUNCATE_DESCRIPTION_CHARS`.
        selector: Required for ``overflow="select"`` — maps the full tool list
            to a relevant subset.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    max_tokens: int = Field(gt=0)
    overflow: str = "error"
    max_description_chars: int | None = Field(default=None, gt=0)
    selector: Callable[[list[Tool]], list[Tool]] | None = None


_VALID_OVERFLOW = frozenset({"error", "truncate", "batch", "select"})
#: Description cap applied by the ``truncate`` overflow strategy (issue #367).
_TRUNCATE_DESCRIPTION_CHARS = 160


def estimate_tokens(text: str, token_counter: Callable[[str], int] | None = None) -> int:
    """Estimate the token count of *text* (issue #367).

    Uses a provider-agnostic chars/4 heuristic by default — no new
    dependencies.  Callers wanting provider-accurate counts pass a
    *token_counter*; the seam keeps the budget honest without coupling the base
    package to any tokenizer.
    """
    if token_counter is not None:
        return token_counter(text)
    return (len(text) + 3) // 4


def template_sha256(template: str) -> str:
    """Return the SHA-256 hex digest of a prompt *template* (issue #364)."""
    return hashlib.sha256(template.encode("utf-8")).hexdigest()


def _chainweaver_version() -> str:
    """Return the installed ChainWeaver version, or ``"0.0.0"`` if unknown."""
    try:
        return version("chainweaver")
    except PackageNotFoundError:  # pragma: no cover — only when run from a non-install
        return "0.0.0"


@dataclass(frozen=True)
class CatalogueStats:
    """How many catalogue tools were rendered and the resulting prompt estimate."""

    tools_total: int
    tools_rendered: int
    estimated_prompt_tokens: int


def build_provenance(
    *,
    prompt_name: str,
    prompt_version: str,
    template: str,
    model_info: ModelInfo | None,
    parameters: dict[str, Any] | None,
    repair_attempts_used: int,
    catalogue_stats: CatalogueStats | None = None,
) -> ProposalProvenance:
    """Assemble a :class:`ProposalProvenance` record for a proposer run (issue #364)."""
    return ProposalProvenance(
        prompt_name=prompt_name,
        prompt_version=prompt_version,
        prompt_sha256=template_sha256(template),
        model=model_info,
        parameters=parameters,
        generated_at=datetime.now(timezone.utc).isoformat(),
        repair_attempts_used=repair_attempts_used,
        chainweaver_version=_chainweaver_version(),
        catalogue_tools_total=None if catalogue_stats is None else catalogue_stats.tools_total,
        catalogue_tools_rendered=(
            None if catalogue_stats is None else catalogue_stats.tools_rendered
        ),
        estimated_prompt_tokens=(
            None if catalogue_stats is None else catalogue_stats.estimated_prompt_tokens
        ),
    )


def _accepts_json_schema(fn: Callable[..., Any]) -> bool:
    """Return ``True`` when *fn* accepts a ``json_schema`` keyword (issue #363)."""
    try:
        params = inspect.signature(fn).parameters
    except (TypeError, ValueError):  # pragma: no cover — builtins without signatures
        return False
    if "json_schema" in params:
        return True
    return any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values())


def invoke_llm(
    llm_fn: LLMFn | StructuredLLMFn,
    prompt: str,
    *,
    json_schema: dict[str, Any] | None,
) -> str:
    """Call *llm_fn*, passing *json_schema* when the seam accepts it (issue #363)."""
    if json_schema is not None and _accepts_json_schema(llm_fn):
        structured: StructuredLLMFn = llm_fn  # type: ignore[assignment]
        return structured(prompt, json_schema=json_schema)
    plain: LLMFn = llm_fn  # type: ignore[assignment]
    return plain(prompt)


def _repair_prompt(
    base_prompt: str,
    json_schema: dict[str, Any] | None,
    error: OfflineLLMError,
    previous: str,
) -> str:
    """Build a one-shot repair prompt carrying the validation *error* (issue #363)."""
    schema_note = " that conforms to the JSON Schema provided" if json_schema is not None else ""
    return (
        f"{base_prompt}\n\n"
        "The previous response failed validation:\n"
        f"  {error.detail}\n\n"
        "Previous response:\n"
        f"{previous}\n\n"
        f"Return a corrected response{schema_note}. Output only the structured "
        "result, no commentary."
    )


_T = TypeVar("_T")


def run_with_repair(
    llm_fn: LLMFn | StructuredLLMFn,
    prompt: str,
    *,
    json_schema: dict[str, Any] | None,
    parse: Callable[[str], _T],
    max_repair_attempts: int,
) -> tuple[_T, int]:
    """Invoke *llm_fn* and parse the result, repairing once on failure (issue #363).

    Returns ``(parsed, repair_attempts_used)``.  On the first parse/validation
    failure a follow-up call is issued carrying the validation error and the
    schema; up to *max_repair_attempts* such calls are made before the final
    :class:`OfflineLLMError` is re-raised.

    Raises:
        ValueError: When *max_repair_attempts* is negative.
        OfflineLLMError: When the completion is still invalid after the
            configured number of repair attempts.
    """
    if max_repair_attempts < 0:
        raise ValueError(f"max_repair_attempts must be >= 0, got {max_repair_attempts}.")

    raw = invoke_llm(llm_fn, prompt, json_schema=json_schema)
    repairs = 0
    while True:
        try:
            return parse(raw), repairs
        except OfflineLLMError as exc:
            if repairs >= max_repair_attempts:
                raise
            repairs += 1
            raw = invoke_llm(
                llm_fn,
                _repair_prompt(prompt, json_schema, exc, raw),
                json_schema=json_schema,
            )


@dataclass(frozen=True)
class BudgetPlan:
    """The catalogue batches and stats produced by :func:`apply_budget` (issue #367)."""

    batches: list[list[Tool]]
    description_chars: int | None
    stats: CatalogueStats


def apply_budget(
    tools: Sequence[Tool],
    *,
    budget: PromptBudget | None,
    token_counter: Callable[[str], int] | None,
    build_prompt: Callable[[list[Tool], int | None], str],
) -> BudgetPlan:
    """Plan prompt assembly under *budget* (issue #367).

    *build_prompt* renders the full proposer prompt for a list of tools and an
    optional per-description character cap, so this function can estimate sizes
    without knowing each proposer's template.

    Returns a :class:`BudgetPlan` with one or more tool batches to run, the
    description cap to render with, and catalogue stats for provenance.

    Raises:
        ValueError: For an unknown ``overflow`` mode, or ``overflow="select"``
            without a :attr:`PromptBudget.selector`.
        PromptBudgetExceededError: Under ``overflow="error"`` (or ``"select"``
            after selection) when the estimate exceeds ``max_tokens``.
    """
    all_tools = list(tools)
    total = len(all_tools)

    if budget is None:
        prompt = build_prompt(all_tools, None)
        est = estimate_tokens(prompt, token_counter)
        return BudgetPlan(
            batches=[all_tools] if all_tools else [],
            description_chars=None,
            stats=CatalogueStats(total, total, est),
        )

    if budget.overflow not in _VALID_OVERFLOW:
        raise ValueError(
            f"PromptBudget.overflow must be one of {sorted(_VALID_OVERFLOW)}; "
            f"got {budget.overflow!r}."
        )

    selected = all_tools
    if budget.overflow == "select":
        if budget.selector is None:
            raise ValueError("PromptBudget.overflow='select' requires a selector.")
        selected = list(budget.selector(all_tools))

    def _est(subset: list[Tool], cap: int | None) -> int:
        return estimate_tokens(build_prompt(subset, cap), token_counter)

    if budget.overflow in {"error", "select"}:
        est = _est(selected, None)
        if est > budget.max_tokens:
            raise PromptBudgetExceededError(est, budget.max_tokens)
        return BudgetPlan(
            batches=[selected] if selected else [],
            description_chars=None,
            stats=CatalogueStats(total, len(selected), est),
        )

    if budget.overflow == "truncate":
        cap = budget.max_description_chars or _TRUNCATE_DESCRIPTION_CHARS
        kept = list(selected)
        while kept and _est(kept, cap) > budget.max_tokens and len(kept) > 1:
            kept.pop()
        est = _est(kept, cap) if kept else 0
        # Even the smallest possible prompt (a single capped tool) can exceed the
        # budget; fail before any LLM call rather than silently making an
        # oversized one, so the budget contract holds for every batch.
        if est > budget.max_tokens:
            raise PromptBudgetExceededError(est, budget.max_tokens)
        return BudgetPlan(
            batches=[kept] if kept else [],
            description_chars=cap,
            stats=CatalogueStats(total, len(kept), est),
        )

    # overflow == "batch": greedily pack tools into budget-sized batches.
    batches: list[list[Tool]] = []
    current: list[Tool] = []
    for tool in selected:
        trial = [*current, tool]
        if current and _est(trial, None) > budget.max_tokens:
            batches.append(current)
            current = [tool]
        else:
            current = trial
    if current:
        batches.append(current)
    rendered = sum(len(b) for b in batches)
    est = max((_est(b, None) for b in batches), default=0)
    # A single tool whose rendered prompt already exceeds the budget cannot be
    # batched down any further; fail before any LLM call rather than issuing an
    # oversized one.
    if est > budget.max_tokens:
        raise PromptBudgetExceededError(est, budget.max_tokens)
    return BudgetPlan(
        batches=batches,
        description_chars=None,
        stats=CatalogueStats(total, rendered, est),
    )
