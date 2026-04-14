# Architecture

> Canonical reference for ChainWeaver's architectural intent, major boundaries,
> and design decisions. Consult this before scoping changes or choosing where
> new code belongs.

---

## Architectural intent

ChainWeaver is a **deterministic graph runner**. It compiles ordered sequences
of tool invocations into flows and executes them with strict schema validation
at every boundary. No LLM, no network I/O, no randomness enters the executor.

The entire value proposition rests on this determinism: given the same input
and tools, the same flow produces the same output every time.

---

## Module boundaries

| Module | Responsibility | Key constraint |
|--------|---------------|----------------|
| `builder.py` | `FlowBuilder`: chainable API that produces validated `Flow` objects | Pure construction sugar — no execution logic; delegates to `Flow`/`FlowStep` |
| `decorators.py` | `@tool` decorator for zero-boilerplate tool definition | Returns a `Tool` subclass; introspects type hints |
| `tools.py` | Define `Tool`: name + callable + Pydantic I/O schemas | Tool functions must be `fn(BaseModel) -> dict[str, Any]` |
| `flow.py` | Define `FlowStep`, `Flow` (linear), `DAGFlowStep`, `DAGFlow`, `validate_dag_topology` | Pure data definitions + topology validation; no execution logic |
| `registry.py` | Store and retrieve `Flow` and `DAGFlow` by name; validates DAG topology at registration | In-memory; intentionally simple for later wrapping |
| `executor.py` | Run flows step-by-step (linear) or level-by-level (DAG), validate I/O, merge context | **No LLM, no network I/O, no randomness** |
| `exceptions.py` | Typed exception hierarchy | All inherit `ChainWeaverError`; carry context attrs |
| `log_utils.py` | Per-step structured logging | Library-safe (NullHandler only); no handler config |
| `__init__.py` | Public API surface | Every public symbol must be in `__all__` |

---

## Decision context

| Decision | Rationale |
|----------|-----------|
| Sequential-only execution for linear `Flow` | Phase 1 MVP. Unchanged. |
| DAG execution for `DAGFlow` | Phase 2: topological level grouping. Parallel/async execution for independent levels is planned for v0.2. |
| Pydantic for all schemas | Deterministic I/O contracts between steps. |
| No LLM calls in executor | "Compiled, not interpreted." |
| `from __future__ import annotations` | Forward-reference support; cleaner type hints. |
| `dataclass` for `StepRecord`/`ExecutionResult` | They carry `Exception` instances; Pydantic cannot serialize these. |
| `step_type` + `capability_id` on `DAGFlowStep` | Forward-compat slots for Weaver Stack kernel integration (weaver-spec I-07). Only `"tool"` is executed today; `"capability"` is reserved for `KernelBackedExecutor`. |
| Cycle detection at registration time | Fail fast — no silent deferral to execution. Belt-and-suspenders check also runs in the executor for flows created without registry. |

---

## Design traps

Things that look wrong but are intentional. Do not "fix" these without a
solution for the underlying constraint.

### `StepRecord` and `ExecutionResult` are dataclasses, not Pydantic

The `error` field holds an `Exception` instance. Pydantic's serialization
cannot handle arbitrary exception objects. These may migrate to Pydantic if a
serialization solution is found, but until then agents must not convert them.

### `log_utils.py`, not `logging.py`

Renamed from `logging.py` (commit ccfe7f8) to avoid shadowing Python's `logging`
stdlib module. Do not rename it back.

### `tests/helpers.py` is separate from `tests/conftest.py`

Extracted intentionally (commit 7ef3245). Boundary:
- `helpers.py` → shared Pydantic schemas and tool functions (importable by any test)
- `conftest.py` → pytest fixtures that compose objects from `helpers.py`

Do not merge them back together.

---

## Planned modules

The following module names are reserved for planned features. Do not create
files that conflict with these names:

| Reserved name | Issue | Purpose |
|---------------|-------|---------|
| `compiler.py` | #71 | Compile-time schema flow validation |
| `analyzer.py` | #77 | Offline flow analyzer |
| `observer.py` | #78 | Runtime flow observer |
| `compat.py` | #48 | Schema fingerprinting |
| `viz.py` | #79 | Flow visualization |
| `cli.py` | #44 | CLI interface |
| `mcp/` | #70, #72 | MCP adapter + flow server |
| `integrations/` | #82 | LangChain/LlamaIndex bridge adapters |
| `export/` | #25 | Flow export formats |
| `governance.py` | #13 | Governance policies |

### Weaver Stack guardrail

Issues #89–#91 introduce a kernel-backed executor (`KernelBackedExecutor`) that
delegates step execution to an agent-kernel. This is a **separate class** —
do not add agent-kernel or weaver-spec imports to `executor.py`. The core
`FlowExecutor` stays deterministic and standalone.
