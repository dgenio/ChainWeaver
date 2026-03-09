# Invariants

> The strongest "do not break these assumptions" reference. Consult this when
> modifying core modules, adding dependencies, or touching the executor.

---

## Hard executor invariants

These three rules are foundational to ChainWeaver's value proposition.
They are non-negotiable.

| # | Rule | Why |
|---|------|-----|
| 1 | **No LLM or AI client calls** in `executor.py` | The executor is deterministic. Same input + same tools = same output. |
| 2 | **No network I/O** in `executor.py` | Network I/O belongs in tool functions, not the orchestrator. |
| 3 | **No randomness** in `executor.py` | Random routing or jitter would break the "compiled, not interpreted" guarantee. |

Network I/O and randomness are allowed in **tool functions** — the executor
only manages the data flow between tools.

---

## Package-wide invariants

| # | Rule |
|---|------|
| 4 | All exceptions inherit from `ChainWeaverError` with context attrs. |
| 5 | All public symbols in `__init__.py` `__all__`. |
| 6 | Tool signature: `fn(validated_input: BaseModel) -> dict[str, Any]`. |
| 7 | `from __future__ import annotations` in every module. |
| 8 | Type annotations on all function signatures (`py.typed` package). |
| 9 | Pydantic `BaseModel` for all data schemas. |
| 10 | No secrets, credentials, or PII in code, logs, or tests. |
| 11 | All new code must pass: `ruff check`, `ruff format --check`, `mypy`, `pytest`. |
| 12 | One logical change per PR; all tests must pass before merge. |

---

## Forbidden patterns

Never generate these in ChainWeaver code:

| Pattern | Why |
|---------|-----|
| LLM/AI client calls in `executor.py` | Violates invariant 1 |
| `unittest.TestCase` | Use plain pytest functions/classes |
| Relative imports from `chainweaver` internals outside the package | Breaks package boundaries |
| Adding deps without updating `pyproject.toml` `[project.dependencies]` | Invisible dependency |
| Secrets, API keys, or credentials in code | Security invariant |
| Converting `StepRecord`/`ExecutionResult` to Pydantic `BaseModel` | They carry `Exception`; see [architecture.md § Design traps](architecture.md#design-traps) |
| Renaming `log_utils.py` back to `logging.py` | Stdlib shadowing; see [architecture.md § Design traps](architecture.md#design-traps) |
| Merging `tests/helpers.py` into `conftest.py` | Intentional split; see [architecture.md § Design traps](architecture.md#design-traps) |
| Adding agent-kernel or weaver-spec imports to `executor.py` | Weaver Stack goes in `KernelBackedExecutor`; see [architecture.md § Weaver Stack](architecture.md#weaver-stack-guardrail) |
| Adding deps to `executor.py` that conflict with kernel delegation | Future `KernelBackedExecutor` requires a clean executor |

---

## Safe vs. unsafe simplifications

| Change | Safe? | Notes |
|--------|-------|-------|
| Extract a helper function within a module | ✅ Yes | Keep it private (`_name`) unless it's a public API |
| Refactor tests to use shared fixtures | ✅ Yes | Put new schemas in `helpers.py`, fixtures in `conftest.py` |
| Remove an unused import | ✅ Yes | Ruff already flags these |
| Inline a private helper | ✅ Yes | If it reduces complexity |
| Convert `StepRecord`/`ExecutionResult` to Pydantic | ❌ No | See forbidden patterns |
| Add a new field to `Flow` or `FlowStep` | ⚠️ Careful | Check `model_dump()` serialization; update tests |
| Change exception hierarchy | ⚠️ Careful | May break downstream `except` clauses |
| Add network I/O to executor.py | ❌ No | Hard invariant |

---

## Update triggers

Update this file when:
- A new hard invariant is established.
- A new forbidden pattern is discovered.
- An invariant is relaxed or removed (document why).
- A new "safe vs. unsafe" category is identified.
