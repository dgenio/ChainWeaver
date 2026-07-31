# Scoped guidance — `chainweaver/flow/`

> Root `AGENTS.md` is authoritative and cannot be weakened here; on conflict,
> the root wins — flag and fix the conflict in the same PR. This file adds
> durable local rules only.

## Facade stability

- `flow/__init__.py` is a **stable facade**: it re-exports the historical
  `chainweaver.flow` surface and preserves module-qualified and pickle
  references. Moving a symbol between submodules requires keeping the
  facade re-export (and pickle compatibility) intact.
- The package is split by model concern (`definitions` / `steps` / `dag` /
  `governance` / `drift` / `refs`). Keep new code in the submodule matching
  its concern; do not re-merge submodules or add topology logic to
  `steps.py`.

## Local invariants

- `FlowStatus` (operational gate) and `FlowLifecycle` (review lifecycle) are
  distinct — never overload one for the other.
- `refs.py` resolves `"module:qualname"` schema/exception refs **only**
  through the opt-in module allowlist policy. Never bypass the policy or
  import a referenced module before the active policy permits it.
- The `random` import for opt-in `RetryPolicy` jitter lives here (inside
  `RetryPolicy.compute_delay`) by design — it is the documented jitter
  carve-out and must not migrate into `executor.py` or `_execution/`. See
  [invariants.md](/docs/agent-context/invariants.md).
- Field changes to `Flow`/`FlowStep`/`DAGFlowStep` update
  [execution-semantics.md](/docs/agent-context/execution-semantics.md)
  (exhaustive tables) and serialization tests in the same PR.
