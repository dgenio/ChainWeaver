---
applyTo: "chainweaver/**"
---
# ChainWeaver package — design traps

Do not "fix" these without a solution for the underlying constraint.
See [architecture.md § Design traps](/docs/agent-context/architecture.md#design-traps)
for full context.

- `StepRecord` and `ExecutionResult` are `dataclass`, not Pydantic. They carry
  `Exception` instances. Do not convert them.
- `log_utils.py` was renamed from `logging.py` to avoid stdlib shadowing. Do
  not rename it back.
- Weaver Stack: do not add agent-kernel or weaver-spec imports to `executor.py`.
  `KernelBackedExecutor` goes in a separate class.
