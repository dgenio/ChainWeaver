# Recipe — Offline tool-description optimizer

**You have:** several tools with overlapping, isolated descriptions —
`search`, `query`, `lookup` — that an agent's LLM can't reliably tell apart.
**You want:** descriptions rewritten to be maximally *discriminative* across
the whole tool set, **offline, at build time**.

Paired script: `examples/description_optimizer.py`. It runs fully offline with
a canned `llm_fn`.

## Why a set-level rewrite

Discrimination is a property of the *set*, not the individual tool: you can't
write a good `search` description without knowing about the other `query` and
`lookup` tools it will be confused with. `optimize_tool_descriptions` gives the
LLM visibility across every tool at once.

```python
from chainweaver import OptimizationStrategy, optimize_tool_descriptions

proposals = optimize_tool_descriptions(
    [search, query, lookup],
    llm_fn=my_llm,
    strategy=OptimizationStrategy.DISCRIMINATIVE,  # or CONCISE / STRUCTURED
)

for p in proposals:
    print(p.tool_name, p.token_delta)   # negative delta = shorter rewrite
    print("  before:", p.original_description)
    print("  after: ", p.proposed_description)
    print("  vs:    ", p.similarity_group)
```

Each `ToolDescriptionProposal` keeps the `original_description` for
side-by-side review, the `proposed_description`, a `rationale`, the
`similarity_group` it was disambiguated against, and an approximate
`token_delta` (`word_count * 1.3`).

## Strategies

| Strategy | Goal |
|---|---|
| `DISCRIMINATIVE` (default) | Maximise the distinction between similar tools. |
| `CONCISE` | Minimise tokens while preserving semantics. |
| `STRUCTURED` | Enforce one consistent format across all descriptions. |

## Incremental mode

When a single tool is added, optimize just it against the existing ecosystem —
and let the LLM flag existing tools whose descriptions should change now that
the newcomer exists:

```python
from chainweaver import optimize_new_tool_description

proposals = optimize_new_tool_description(new_tool, existing_tools, llm_fn=my_llm)
```

## Guarantees

Same as the [flow compiler](offline-llm-flow-proposals.md): the LLM is reached
only through `llm_fn`, the module is banned from the executor, proposals are
**never applied automatically**, and malformed completions raise a typed
`OfflineLLMError`.
