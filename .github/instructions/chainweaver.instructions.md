---
applyTo: "chainweaver/**"
---
# ChainWeaver package — design traps

Also read the nearest path-scoped `AGENTS.md` for the subtree you are
changing — the index is in
[AGENTS.md § 11](/AGENTS.md#11-instruction-precedence-and-discovery).

Do not "fix" these without a solution for the underlying constraint.
See [architecture.md § Design traps](/docs/agent-context/architecture.md#design-traps)
for full context.

- `StepRecord` and `ExecutionResult` are Pydantic models. They carry
  serializable `error_type` / `error_message` fields, not live `Exception`
  instances. Do not add a live exception field back.
- `log_utils.py` was renamed from `logging.py` to avoid stdlib shadowing. Do
  not rename it back.
- Weaver Stack: do not add agent-kernel or weaver-spec imports to `executor.py`.
  `KernelBackedExecutor` goes in a separate class.
