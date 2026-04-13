# ChainWeaver — Agent Instructions

> Single source of truth for all coding agents working on this repository.
> For tool-specific wrappers, see the documentation map at the end of this file.

---

## 1. Project identity

ChainWeaver is a deterministic orchestration layer for MCP-based agents.
It compiles multi-tool flows into executable sequences that run without any
LLM involvement between steps.

- Python 3.10+; `from __future__ import annotations` in every module.
- Single runtime dependency: `pydantic>=2.0`.
- Core philosophy: **compiled, not interpreted** — the executor is a graph
  runner, not a reasoning engine.

---

## 2. Domain vocabulary

Use these terms consistently in code, docs, comments, and PR descriptions.

| Canonical term | Never use | Meaning |
|----------------|-----------|---------|
| **flow** | chain, pipeline | A named, ordered sequence of tool invocations (`Flow`) |
| **tool** | function, action | A named callable with Pydantic input/output schemas (`Tool`) |

---

## 3. Repository map

```text
chainweaver/
├── __init__.py        Public API surface; all exports in __all__
├── builder.py         FlowBuilder: fluent API for constructing Flow objects
├── decorators.py      @tool decorator for zero-boilerplate tool definition
├── tools.py           Tool class: named callable with Pydantic I/O schemas
├── flow.py            FlowStep + Flow: ordered step definitions (Pydantic models)
├── registry.py        FlowRegistry: in-memory catalogue of named flows
├── executor.py        FlowExecutor: sequential, LLM-free runner (main entry point)
├── exceptions.py      Typed exception hierarchy (all inherit ChainWeaverError)
├── log_utils.py       Structured per-step logging utilities
└── py.typed           PEP 561 marker
tests/
├── conftest.py        Pytest fixtures (import schemas/functions from helpers.py)
├── helpers.py         Shared Pydantic schemas and tool functions
├── test_*.py          Test files
examples/
└── simple_linear_flow.py   Runnable standalone usage example
pyproject.toml             Ruff, mypy, pytest config (source of truth for tooling)
.github/workflows/         CI (ci.yml) and publish (publish.yml) pipelines
```

### Key entry points

- `FlowExecutor.execute_flow(flow_name, initial_input)` → `ExecutionResult`
- `FlowRegistry.register_flow(flow, *, overwrite=False)` → register a flow
- `FlowExecutor.register_tool(tool)` → register a tool for use in flows

---

## 4. Core invariants

Three hard executor invariants and nine package-wide invariants govern all
changes. The executor is deterministic by design.

**Executor — never add to `executor.py`:**
1. No LLM or AI client calls.
2. No network I/O.
3. No randomness.

**Package-wide:**
4. All exceptions inherit from `ChainWeaverError` with relevant context
   attributes (`tool_name`, `step_index`, `detail` where applicable).
5. All public symbols exported in `chainweaver/__init__.py` `__all__`.
6. Tool function signature: `fn(validated_input: BaseModel) -> dict[str, Any]`.
7. `from __future__ import annotations` at the top of every module.
8. Type annotations on all function signatures (package ships `py.typed`).
9. Pydantic `BaseModel` for all data schemas (`Flow`, `FlowStep`, I/O contracts).
10. No secrets, credentials, or PII in code, logs, or tests.
11. All new code must pass: `ruff check`, `ruff format --check`, `mypy`, `pytest`.
12. One logical change per PR; all tests must pass before merge.

For the full prohibited-actions list and anti-patterns, see
[invariants.md](docs/agent-context/invariants.md).

---

## 5. Executor and flow semantics

### `FlowStep.input_mapping`

| Value type | Behavior |
|------------|----------|
| `str` | Looked up as a key in the accumulated execution context. |
| Non-string (`int`, `float`, `bool`, …) | Used as a literal constant. |
| Empty `{}` (default) | The tool receives the full current context. |

### `ExecutionResult` (dataclass)

| Field | Type | Meaning |
|-------|------|---------|
| `flow_name` | `str` | Name of the executed flow. |
| `success` | `bool` | `True` when all steps completed without error. |
| `final_output` | `dict \| None` | Merged execution context, or `None` on failure. |
| `execution_log` | `list[StepRecord]` | Ordered per-step records. |

### `StepRecord` (dataclass)

| Field | Type | Meaning |
|-------|------|---------|
| `step_index` | `int` | Zero-based position (`-1` = flow-input validation, `len(steps)` = flow-output validation). |
| `tool_name` | `str` | Tool invoked (or flow name for validation records). |
| `inputs` | `dict` | Validated inputs passed to the tool. |
| `outputs` | `dict \| None` | Validated outputs, or `None` on failure. |
| `error` | `Exception \| None` | Exception raised, or `None` on success. |
| `success` | `bool` | `True` when the step completed without error. |

> **Design note:** `StepRecord` and `ExecutionResult` are intentionally
> `dataclass`, not `BaseModel`. They carry `Exception` instances that Pydantic
> cannot serialize. See [architecture.md § Design traps](docs/agent-context/architecture.md#design-traps).

---

## 6. Common tasks

| Task | Where to look | What to update |
|------|---------------|----------------|
| Add a new tool | `tools.py` | Integration tests in `test_flow_execution.py` |
| Add a new exception | `exceptions.py` | `__init__.py` + `__all__` + README error table — **same PR** |
| Modify flow execution | `executor.py` | Keep `StepRecord` + `ExecutionResult` consistent |
| Add a new Flow field | `flow.py` | Serialization tests if `model_dump()` changes |
| Change logging format | `log_utils.py` | Update tests (no re-export needed) |
| Add a new module | See [new-module checklist](docs/agent-context/workflows.md#new-module-checklist) |

### Exception message style

Use f-string sentences with single-quoted identifiers, ending with a period:

```python
f"Tool '{tool_name}' is not registered."
```

---

## 7. Validation commands

Run all four before every commit and PR:

```bash
ruff check chainweaver/ tests/ examples/
ruff format --check chainweaver/ tests/ examples/
python -m mypy chainweaver/
python -m pytest tests/ -v
```

CI runs lint + format + mypy on Python 3.10 only; tests run across 3.10–3.13.

For full CI, PR, branch, and commit conventions, see
[workflows.md](docs/agent-context/workflows.md).

---

## 8. Definition of done

Before marking a PR ready for review:

- [ ] All four validation commands pass locally.
- [ ] Both success and error paths are tested.
- [ ] `__init__.py` `__all__` is updated if public symbols were added.
- [ ] No new contradictions introduced between docs.
- [ ] AGENTS.md updated if architecture changed.

Full checklist: [review-checklist.md](docs/agent-context/review-checklist.md).

---

## 9. Documentation map

| File | Purpose | Consult when… |
|------|---------|---------------|
| [architecture.md](docs/agent-context/architecture.md) | Boundaries, decisions, design traps, planned modules | Scoping changes, understanding why something is built a certain way, choosing file placement |
| [workflows.md](docs/agent-context/workflows.md) | Commands, CI, code style, testing, PR/git conventions | Writing code, creating branches/PRs, adding modules, running CI |
| [invariants.md](docs/agent-context/invariants.md) | Hard rules, forbidden patterns | Modifying core modules, adding deps, touching executor |
| [lessons-learned.md](docs/agent-context/lessons-learned.md) | Recurring mistake patterns | Before proposing changes to avoid known pitfalls |
| [review-checklist.md](docs/agent-context/review-checklist.md) | Definition-of-done, review gates | Before submitting a PR, during code review |

---

## 10. Update policy

- **Every PR:** check whether AGENTS.md or any `docs/agent-context/` file is
  stale with respect to the change. Update in the same PR if so.
- **Architecture changes** (add/remove/rename modules): update AGENTS.md repo
  map and architecture.md in the same PR.
- **Ownership rule:** if you change the architecture, you own the doc update.
- **Contradictions:** if you find a contradiction between docs, fix it in the
  same PR if small, or open an issue if large.
