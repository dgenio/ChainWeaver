# Scoped guidance — `chainweaver/integrations/`

> Root `AGENTS.md` is authoritative and cannot be weakened here; on conflict,
> the root wins — flag and fix the conflict in the same PR. This file adds
> durable local rules only.

## Optional-dependency conventions

- Every adapter guards its third-party import and raises a clear
  `ImportError` naming the extra to install (e.g.
  `pip install 'chainweaver[otel]'`). The base install must import
  `chainweaver` successfully with **no** optional extra present.
- No optional dependency may leak into core modules: core reaches
  integrations only through dependency-free seams (the `DecisionCallback`
  protocol, the `_execute_capability_step` hook, middleware). Never add an
  integration import to `executor.py` — see the Weaver Stack guardrail in
  [architecture.md](/docs/agent-context/architecture.md#weaver-stack-guardrail).
- `KernelBackedExecutor` is the *only* place capability steps are
  dispatched; it overrides `_execute_capability_step` and nothing else.
- New adapters: one module per third-party system, `[extra]` declared in
  `pyproject.toml`, guarded import tested both with and without the extra
  installed.
