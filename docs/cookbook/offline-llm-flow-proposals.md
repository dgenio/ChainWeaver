# Recipe — Offline LLM-assisted flow proposals

**You have:** a set of tools whose useful chains aren't obvious from their
schemas alone — a `summarize` output that should feed `translate`, say, even
though the field names differ.
**You want:** an LLM to *propose* deterministic flows for you to review —
**offline, at build time**, never in the executor loop.

Paired script: `examples/llm_flow_proposals.py`. It runs fully offline with a
canned `llm_fn`, so there's no network and no API key.

## The seam: `llm_fn`, not an SDK

ChainWeaver never imports an LLM provider. `llm_propose_flows` reaches a model
only through a callable you supply:

```python
LLMFn = Callable[[str], str]  # prompt in, completion out
```

Adapt any model — a local Llama, GPT, Claude, or an offline stub — to that
signature. This keeps the dependency surface at zero and keeps the LLM
strictly at build time.

## Propose flows

```python
from chainweaver import Tool, llm_propose_flows, write_proposals

proposals = llm_propose_flows([search, summarize], llm_fn=my_llm)

for p in proposals:
    print(p.proposed_flow.name, p.confidence, p.rationale)

# Optionally write PR-ready artifacts: one <name>.flow.yaml per proposal
# plus a PROPOSALS.md summary (needs the chainweaver[yaml] extra).
write_proposals(proposals, "proposed_flows/")
```

Each `LLMProposal` carries the parsed `proposed_flow`, the LLM's `rationale`,
its self-reported `confidence` (clamped to `[0, 1]`), and a `source` tag of
`"llm-compiler"`.

## Guarantees

- **Never auto-registered.** Proposals are plain data for a human, governance,
  or a PR — `write_proposals` exists precisely so the output is reviewable.
- **Banned from the executor.** `chainweaver/executor.py` must not import this
  module; a guard test (`tests/test_offline_llm_guardrail.py`) enforces it.
- **Validated.** Unknown tool references, malformed flows, and non-YAML
  completions raise a typed `OfflineLLMError` rather than leaking a raw parser
  error.

You can hand `llm_propose_flows` the output of
`ChainAnalyzer.suggest_flows()` via `static_candidates=` to seed the prompt
with schema-valid chains the LLM can refine or extend.

## What next

Pair this with the [tool-description optimizer](offline-description-optimizer.md),
which rewrites tool descriptions so an agent picks the right tool in the first
place.
