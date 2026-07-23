# Scoped guidance — `chainweaver/testing/`

> Root `AGENTS.md` is authoritative and cannot be weakened here; on conflict,
> the root wins — flag and fix the conflict in the same PR. This file adds
> durable local rules only.

## Public harness contract

- This package is the **public** test harness for flows: users import from
  `chainweaver.testing` directly. Its symbols are deliberately **not** in
  the top-level `chainweaver/__init__.py` `__all__` (the one exception is
  `FixtureStaleError`, which follows the error-catalog convention) — keep it
  that way so the public-API snapshot stays runtime-focused.
- The harness hooks at the `Tool._call_fn` / `_call_fn_async` boundary —
  **never** inside `executor.py` — so schema validation still runs during
  replay and the executor's invariants stay untouched. See
  [architecture.md § Design traps](/docs/agent-context/architecture.md#design-traps)
  before changing the record/replay patching.
- `protocol_suites.py` imports `pytest`, so it must remain a submodule that
  `testing/__init__.py` never imports — the harness itself stays
  pytest-free.
- The pytest plugin lives at the repo root (`pytest_chainweaver.py`), not in
  this package — that placement is deliberate (coverage measurement); do not
  move it here.
