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

> **Jitter carve-out (since #76):** :class:`RetryPolicy` accepts an opt-in
> ``jitter=True`` that multiplies its computed backoff by a uniform sample.
> The :mod:`random` import lives in ``flow.py`` (inside
> ``RetryPolicy.compute_delay``); ``executor.py`` itself never imports
> :mod:`random`. The default ``jitter=False`` preserves full determinism;
> users opt in per-step.

> **Trace-id carve-out (since #20):** :class:`FlowExecutor` calls
> ``uuid.uuid4().hex`` (via the private ``_new_trace_id`` helper) to mint
> an opaque correlation identifier on every ``execute_flow`` call. The
> ``uuid`` module uses OS entropy, but the trace id is recorded as
> metadata only — it does not influence which tools run, the order they
> run in, or any value passed between them. ``ExecutionResult.trace_id``
> changes between runs by design (so logs can be correlated across
> systems); every other field is fully deterministic given the same
> input and tools.

> **Predicate carve-out (since #9):** ``DAGFlowStep.branches`` introduce
> conditional routing.  :func:`chainweaver.contracts.evaluate_predicate`
> evaluates predicate strings by parsing them with :mod:`ast` and walking
> the resulting tree against an explicit node allow-list — **no**
> :func:`eval` / :func:`exec` is ever called.  The grammar is limited to
> variable lookups, subscript, the six comparison operators, ``in`` /
> ``not in``, ``and`` / ``or`` / ``not``, unary ``+`` / ``-`` (for signed
> literals such as ``n == -1``), and literal constants — no attribute
> access, no function calls, no *binary* arithmetic.  Any rejected node
> raises :class:`~chainweaver.exceptions.PredicateSyntaxError`.  The
> evaluator is pure-Python and deterministic: same predicate + same
> context always yields the same boolean.  Branching makes the
> *executed path* data-dependent, which is why
> :attr:`DAGFlow.determinism_level` downgrades to ``PARTIAL`` when any
> step carries non-empty ``branches``.

Network I/O and randomness are allowed in **tool functions** — the executor
only manages the data flow between tools.

### Automated enforcement (since #354; dynamic-import hardening #430)

The three hard invariants are mechanically enforced by
`tests/test_executor_import_contract.py`, which runs as part of the normal
`pytest` suite (no separate CI job). It performs a static, AST-based check:

- **Direct imports** — `executor.py` and every module under
  `chainweaver/_execution/` must not import any banned module. The banned set
  is the network/LLM/randomness sources (`random`, `secrets`, `socket`,
  `http`, `urllib`, `requests`, `httpx`, `aiohttp`, `openai`, `anthropic`) plus
  the in-repo modules marked "banned from executor.py" in the
  [module map](module-map.md) (`compiler_llm`, `optimizer`, `observer`,
  `traces`, `lessons`, `service`, `_offline_llm`, `proposals`, `routing`,
  `opencode`). The map annotations and the enforced list are kept identical
  by `tests/test_agent_instructions.py`.
- **Literal dynamic import patterns** — the same execution modules reject
  reviewable bypasses such as `__import__("random")`,
  `importlib.import_module("openai")`, and simple aliases when the target is
  a string literal. Relative `importlib.import_module(".optimizer",
  package="chainweaver")` literals are resolved against their literal
  `package` argument before classification, so a leading dot cannot hide a
  banned in-repo module. The check intentionally does not evaluate
  runtime-built strings; those should not appear in executor code.
- **Transitive in-repo reach** — following `chainweaver.*` imports out of the
  execution modules, none of the deterministic-execution closure may reach a
  banned in-repo module, so a helper cannot smuggle an LLM proposer onto the
  execution path indirectly.

A PR that adds `import random`, `__import__("random")`, or any banned import
to the execution modules fails this test with a message pointing back at this
document.

**Carve-outs:** `uuid` is the single reviewed exception, for the trace-id
carve-out above. It is kept deliberately *off* the banned list (rather than
banned-then-re-permitted); the contract test asserts reviewed carve-outs stay
unbanned, so banning one later trips the test and forces a conscious review. A
blanket "`random` absent from `sys.modules`" check is deliberately not used
because `flow.py` legitimately imports `random` for the opt-in jitter carve-out;
the contract is therefore scoped to the *execution-module boundary*
(`executor.py` + `_execution/`), which is exactly where the invariants apply.
Expanding the banned list is cheap; keep carve-outs conservative and document
every addition here.

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
| Re-introducing a live `Exception` field on `StepRecord`/`ExecutionResult` | Both are Pydantic models since #20; errors are stored as `error_type` / `error_message` strings so the trace is JSON-serializable. See [architecture.md § Design traps](architecture.md#design-traps) |
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
| Convert `StepRecord`/`ExecutionResult` to Pydantic | ✅ Done in #20 | Errors are now `error_type` / `error_message` strings |
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
