# ChainWeaver — Claude Instructions

Canonical source of truth: [AGENTS.md](/AGENTS.md) and
[docs/agent-context/](/docs/agent-context/).

Read AGENTS.md before starting any task. It contains the repo map,
invariants, entry points, common tasks, validation commands, and
documentation map that routes to deeper guidance.

---

## Explore before acting

- Read the canonical docs for the topic area before writing code.
- Inspect the files you plan to change. Do not assume structure from memory.
- Check [architecture.md](/docs/agent-context/architecture.md) for design
  traps and reserved module names before creating or renaming files.
- Do not infer repo-wide rules from a single local example.

## Implement safely

- Preserve invariants. The three executor rules (no LLM, no network I/O,
  no randomness in `executor.py`) are non-negotiable. See
  [invariants.md](/docs/agent-context/invariants.md).
- Use authoritative commands exactly as listed in
  [AGENTS.md § Validation commands](/AGENTS.md#7-validation-commands).
  Do not substitute alternative flags, paths, or invocations.
- Follow the conventions in canonical docs. Do not invent new patterns.
- Do not "clean up" or "simplify" code that looks unusual without first
  checking [architecture.md § Design traps](/docs/agent-context/architecture.md#design-traps).

## Validate before completing

- Run all four validation commands and confirm they pass.
- Check whether your change triggers a doc update. Consult the governance
  triggers in [workflows.md](/docs/agent-context/workflows.md#documentation-governance-triggers).
- Walk [review-checklist.md](/docs/agent-context/review-checklist.md) before
  marking work done.
- Verify that docstrings match actual behavior, not intended behavior.

## Handle contradictions

- If canonical docs contradict each other, flag the conflict explicitly.
  Do not silently pick one side.
- If code contradicts canonical docs, trust the docs for conventions and
  the code for runtime behavior. Flag the gap.
- If an older or duplicate document disagrees with AGENTS.md or
  `docs/agent-context/`, prefer AGENTS.md.
- Fix small contradictions in the same PR. Open an issue for large ones.

## Capture lessons

- If you discover a recurring failure pattern during work, note it as a
  candidate lesson.
- A candidate lesson is provisional. Do not promote it into durable docs
  based on a single observation.
- A lesson is promotable when it is reusable, decision-shaping, and durable
  — not just a one-off incident.
- Promotion order: canonical docs first (`lessons-learned.md`), then
  projections. See the criteria in
  [lessons-learned.md](/docs/agent-context/lessons-learned.md#promotion-criteria).

## Update order

1. Update canonical shared docs (`AGENTS.md`, `docs/agent-context/`) first.
2. Update tool-specific projections (this file, `.github/copilot-instructions.md`) second.
3. If a Claude-specific rule starts to look shared and durable, promote it
   into canonical docs and simplify it here.
