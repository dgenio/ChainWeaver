# Scoped guidance — `chainweaver/_execution/`

> Root `AGENTS.md` is authoritative and cannot be weakened here; on conflict,
> the root wins — flag and fix the conflict in the same PR. This file adds
> durable local rules only.

## Determinism boundary

- Every module in this package is part of the deterministic execution path.
  The three executor invariants — **no LLM or AI client calls, no network
  I/O, no randomness** — apply to every file here exactly as they apply to
  `executor.py` (root `AGENTS.md` §4).
- Enforcement is mechanical: `tests/test_executor_import_contract.py` checks
  direct imports, literal dynamic imports, and the transitive in-repo import
  closure of this package. A new module here is covered automatically.
- Carve-outs (e.g. `uuid` for trace ids) are reviewed exceptions documented
  in [invariants.md](/docs/agent-context/invariants.md). Do not add one
  without updating that document and its rationale.

## Package rules

- This package is **private**: nothing here goes in the top-level
  `chainweaver/__init__.py` `__all__`. Consumers are `executor.py` and the
  package itself.
- Helpers here must be lane-neutral: usable identically by the sync and
  async lanes. Context merging goes through `merge_step_outputs` — the
  single merge point — never a second implementation.
- Executor decomposition work has its own tracked design; do not grow this
  package speculatively beyond what both lanes consume today.
