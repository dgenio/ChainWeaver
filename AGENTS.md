# ChainWeaver — Agent Instructions

> Recognized by GitHub Copilot (nearest-in-tree) and Claude Code as the
> authoritative project guidance file.

---

## 1. Project overview

ChainWeaver is a deterministic orchestration layer for MCP-based agents. It
compiles multi-tool chains into executable flows that run without any LLM
involvement between steps. Python 3.10+, single runtime dependency
(`pydantic>=2.0`).

---

## 2. Architecture map

```
chainweaver/
├── __init__.py       → Public API surface; all exports listed in __all__
├── tools.py          → Tool class: named callable with Pydantic input/output schemas
├── flow.py           → FlowStep + Flow: ordered step definitions (Pydantic models)
├── registry.py       → FlowRegistry: in-memory catalogue of named flows
├── executor.py       → FlowExecutor: sequential, LLM-free runner (main entry point)
├── exceptions.py     → Typed exception hierarchy (all inherit ChainWeaverError)
├── log_utils.py      → Structured per-step logging utilities
└── py.typed          → PEP 561 marker for typed package
```

---

## 3. Key entry points

- `FlowExecutor.execute_flow(flow_name, initial_input)` — main orchestration
  entry point; returns `ExecutionResult`
- `FlowRegistry.register_flow(flow)` — register a flow for execution
- `FlowExecutor.register_tool(tool)` — register a tool for use in flows

---

## 4. Decision context

| Decision | Rationale |
|---|---|
| **Sequential-only execution** | Phase 1 MVP. DAG execution is planned for v0.2 (see Roadmap in README). |
| **Pydantic for all schemas** | Schema validation ensures deterministic I/O contracts between steps. Every tool input/output is validated. |
| **No LLM calls in executor** | Core design principle — "compiled, not interpreted." The executor is a graph runner, not a reasoning engine. |
| **`from __future__ import annotations`** | Every module uses it for forward-reference support and cleaner type hints. |

---

## 5. Top invariants

1. **No LLM calls in `executor.py`** — the executor is deterministic by design.
2. All exceptions inherit from `ChainWeaverError` and include context (`tool_name`, `step_index`, `detail`).
3. All public API symbols must be exported in `chainweaver/__init__.py` `__all__`.
4. Every tool function signature: `fn(validated_input: BaseModel) -> dict[str, Any]`.
5. `from __future__ import annotations` at the top of every module.
6. Type annotations on all function signatures (the package ships `py.typed`).
7. Pydantic `BaseModel` for all data schemas (`Flow`, `FlowStep`, input/output contracts).
8. No secrets, credentials, or PII in code, logs, or tests.
9. All new code must pass: `pytest`, `ruff check`, `ruff format --check`.
10. One logical change per PR; all tests must pass before merge.

---

## 6. Development workflow

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Lint
ruff check chainweaver/ tests/ examples/

# Check formatting
ruff format --check chainweaver/ tests/ examples/

# Run the example
python examples/simple_linear_flow.py
```

See [README > Development](README.md#development) for extended context.

> **Note:** Once [#39](https://github.com/dgenio/ChainWeaver/issues/39) (mypy)
> lands, add `python -m mypy chainweaver/` to the validation sequence.

---

## 7. Common tasks

| Task | Where to look | What to update |
|---|---|---|
| Add a new Tool | `chainweaver/tools.py` | Integration tests in `tests/test_flow_execution.py` |
| Add a new exception | `chainweaver/exceptions.py` | Re-export in `chainweaver/__init__.py`, update `__all__` |
| Modify flow execution | `chainweaver/executor.py` | Ensure `StepRecord` and `ExecutionResult` stay consistent |
| Add a new Flow field | `chainweaver/flow.py` | Update serialization tests if `model_dump()` changes |
| Change logging format | `chainweaver/log_utils.py` | No re-export needed; update tests |

> **Ownership rule:** If you change the architecture, update this file in the
> same PR.

---

## 8. Testing conventions

- Test files: `tests/test_*.py`
- Test classes grouped by scenario (e.g., `TestSuccessfulExecution`, `TestMissingTool`)
- Use `@pytest.fixture()` for shared objects (tools, flows, executors)
- Shared fixtures and schemas live in `tests/conftest.py`
- Test both success and failure paths
- See [README > Development](README.md#development) for commands

---

## 9. CI pipeline

- `.github/workflows/ci.yml`: runs on push/PR to `main`
  - Ruff lint + format check (Python 3.10 only)
  - `pytest` across Python 3.10, 3.11, 3.12, 3.13
- `.github/workflows/publish.yml`: triggered by `v*` tags →
  test → build → PyPI publish → GitHub Release
