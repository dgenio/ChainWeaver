# ChainWeaver + contextweaver: coding-agent token reduction

ChainWeaver and [contextweaver](https://github.com/dgenio) solve different
parts of the same coding-agent cost problem and compose cleanly:

- **contextweaver** reduces the *visible* tool-schema and result context an
  agent's model sees on each turn (a gateway concern).
- **ChainWeaver** reduces the number of *model-mediated tool steps* by
  compiling deterministic paths into macro-tools (a compilation concern).

Treating them as competing tools is a mistake. Deployed together they attack
both axes of token cost: context width *and* round-trip count.

## Architecture

```text
VS Code Copilot / Claude / Cursor / custom coding agent
        ↓
contextweaver gateway          (trims visible schema + results)
        ↓
ChainWeaver FlowServer         (exposes reviewed macro-flows as MCP tools)
        ↓
raw MCP tools / local tools    (kept available as fallback)
```

### Recommended behavior

- Expose **reviewed, active** ChainWeaver macro-flows as first-class MCP tools.
- Keep low-level raw MCP tools available as a fallback for paths that are not
  worth compiling (open-ended reasoning, unstable contracts).
- Route both through the contextweaver gateway so schema/result context stays
  trimmed regardless of which tool the agent picks.

## Why this reduces tokens

A raw agent loop pays, per primitive step, for:

1. a model-mediated decision (prompt + completion tokens), and
2. the tool's schema and result occupying the context window.

A compiled macro-flow removes (1) for every internal step — the executor walks
the path deterministically with **no LLM between steps** — and collapses N
tool schemas into **one** macro-tool schema, shrinking (2) as well. The
`benchmarks/bench_coding_agent_macroflow.py` script quantifies both effects
for a configurable path length; see [CLAIMS.md](https://github.com/dgenio/ChainWeaver/blob/main/CLAIMS.md)
for the receipts and the explicit non-claims.

## The compilation workflow

The [Daily Driver guide](daily-driver.md) covers the operator loop end to end:

```text
observe traces → chainweaver traces mine → score → draft-flows → backtest → review → flows promote
```

Only `active`, read-only, approval-free flows are exposed by `FlowServer` by
default — see [macro-flow safety](macro-flow-safety.md) for the boundary on
what is safe to compile.

## Boundaries

- ChainWeaver does not reason between steps; it is a deterministic graph
  runner, not an agent framework.
- contextweaver does not compile paths; it routes and trims context.
- The two share a vendor-neutral trace/telemetry format so a path observed at
  the gateway can be mined into a ChainWeaver flow.
