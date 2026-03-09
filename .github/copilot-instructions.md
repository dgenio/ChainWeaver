# Copilot Instructions — ChainWeaver

> Thin review-oriented layer. Canonical source of truth: [AGENTS.md](/AGENTS.md)
> and [docs/agent-context/](/docs/agent-context/).

---

## Review-critical rules

- Review code and agent-facing docs together. If a PR changes behavior,
  invariants, architecture, or workflows, the corresponding docs must be
  updated in the same PR.
- Invariants take priority over cleanup, simplification, or local refactors.
  See [AGENTS.md § Core invariants](/AGENTS.md#4-core-invariants).
- Do not invent conventions. All coding style, naming, workflow, and testing
  rules are grounded in [AGENTS.md](/AGENTS.md) and
  [docs/agent-context/](/docs/agent-context/). If guidance is missing, surface
  the gap — do not guess.
- Use authoritative commands exactly as written in
  [AGENTS.md § Validation commands](/AGENTS.md#7-validation-commands). Do not
  substitute alternative flags, paths, or invocations.
- If you find a contradiction or stale content in any doc, flag it explicitly.
  Do not silently work around it.

## Executor guardrails

`executor.py` has three hard invariants — no LLM calls, no network I/O, no
randomness. These are non-negotiable. See
[invariants.md](/docs/agent-context/invariants.md#hard-executor-invariants).

## Vocabulary

| Use | Never use |
|-----|-----------|
| **flow** | chain, pipeline |
| **tool** | function, action (when referring to a `Tool` instance) |

## Where to find guidance

| Topic | Canonical file |
|-------|----------------|
| Architecture, boundaries, design traps | [architecture.md](/docs/agent-context/architecture.md) |
| Commands, CI, code style, testing, PR rules | [workflows.md](/docs/agent-context/workflows.md) |
| Hard rules, forbidden patterns | [invariants.md](/docs/agent-context/invariants.md) |
| Recurring mistake patterns | [lessons-learned.md](/docs/agent-context/lessons-learned.md) |
| Definition-of-done, review gates | [review-checklist.md](/docs/agent-context/review-checklist.md) |
