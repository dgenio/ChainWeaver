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
| `compat.py` | `schema_fingerprint()`, `CompatibilityIssue`, `check_flow_compatibility()` | Pure utility; no execution or I/O |
| `compiler.py` | `compile_flow()`: static schema flow validation pre-execution | Returns `CompilationResult`; no execution logic |
| `contracts.py` | `ToolSafetyContract`, `SideEffectLevel`, `StabilityLevel`, `DeterminismLevel`, `merge_safety()`, `evaluate_predicate()` — the determinism + safety vocabulary (#19, #125, #9, #8) | Pure module: enums + frozen Pydantic model + AST-based predicate evaluator.  `evaluate_predicate` never calls `eval`/`exec`; nodes are matched against an explicit allow-list |
| `decorators.py` | `@tool` decorator for zero-boilerplate tool definition | Returns a `Tool` subclass; introspects type hints |
| `tools.py` | Define `Tool`: name + callable + Pydantic I/O schemas + `schema_hash` + `safety` contract (#19); `Tool.from_flow()` adapter (#24) with `merge_safety` derivation (#125) | Tool functions must be `fn(BaseModel) -> dict[str, Any]`; `from_flow` reuses the same contract — its closure dispatches `FlowExecutor.execute_flow` and surfaces inner failures as `FlowExecutionError` |
| `flow.py` | Define `FlowStep`, `Flow`, `DAGFlowStep`, `DAGFlow`, `FlowStatus`, `DriftInfo`, `ConditionalEdge` (#9), `validate_dag_topology` | Pure data definitions + topology validation + structural `determinism_level` inference (#8); no execution logic |
| `registry.py` | Store and retrieve `Flow`/`DAGFlow` by `(name, version)`; status filtering; multi-version support | Delegates persistence to a `RegistryStore`; defaults to `InMemoryStore` |
| `storage.py` | `RegistryStore` Protocol + `InMemoryStore` (default) + `FileStore` (one JSON file per flow) | Filenames are `{name}@{version}.flow.json`; concurrent multi-process access not coordinated |
| `analyzer.py` | `ChainAnalyzer`: offline schema-compatibility analysis — compatibility matrix, chain enumeration, suggested flows (#77) | Pure static pass: no LLM, no network, no randomness; cycle-free DFS bounded by `max_depth` |
| `executor.py` | Run flows step-by-step (linear) or level-by-level (DAG), validate I/O, merge context, drift detection | **No LLM, no network I/O, no randomness** |
| `exceptions.py` | Typed exception hierarchy | All inherit `ChainWeaverError`; carry context attrs |
| `log_utils.py` | Per-step structured logging | Library-safe (NullHandler only); no handler config |
| `cost.py` | `CostProfile` + `CostReport` for cost-avoided estimation | Pure data + a single ``compute_cost_report`` helper; no execution logic |
| `observation.py` | `TraceRecorder` + `ObservedTrace` for ad-hoc tool sequence capture | In-memory storage only; persistence deferred |
| `viz.py` | `flow_to_ascii`, `flow_to_mermaid`, `result_to_mermaid` pure renderers | No external dependencies — string generation only |
| `serialization.py` | YAML + JSON encode/decode for `Flow` and `DAGFlow` (`flow_to_json`, `flow_from_yaml`, etc.) | JSON path is dep-free; YAML requires `pyyaml` (optional extra `chainweaver[yaml]`); schema/exception refs round-trip as `"module:qualname"` strings |
| `cli.py` | typer-based `chainweaver inspect` entry point | Reads from a process-scoped default registry installed via `cli.set_default_registry` |
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
| Pydantic `BaseModel` for `StepRecord`/`ExecutionResult` (since #20) | Errors are stored as `error_type` / `error_message` strings instead of live `Exception` instances, so the trace round-trips through JSON. |
| `step_type` + `capability_id` on `DAGFlowStep` | Forward-compat slots for Weaver Stack kernel integration (weaver-spec I-07). Only `"tool"` is executed today; `"capability"` is reserved for `KernelBackedExecutor`. |
| Cycle detection at registration time | Fail fast — no silent deferral to execution. Belt-and-suspenders check also runs in the executor for flows created without registry. |
| Branch targets must be direct dependents (#9) | Keeps conditional routing local — a `ConditionalEdge.target_step_id` (or `default_next`) must reference a step that already lists the branching step in its `depends_on`.  This makes "skipped" propagation a one-hop computation in the executor and prevents branches from jumping across unrelated subgraphs.  Enforced at registration time by `validate_dag_topology`. |
| AST-based predicate evaluator (#9) | Predicate strings are parsed with `ast.parse(mode="eval")` and walked against an explicit node allow-list — `eval`/`exec` are **never** called.  The grammar deliberately excludes attribute access, function calls, and arithmetic so predicates stay routing decisions, not computations. |

---

## Design traps

Things that look wrong but are intentional. Do not "fix" these without a
solution for the underlying constraint.

### `StepRecord` and `ExecutionResult` errors are stored as strings

These types are Pydantic models (since #20). The previous design trap — using
`dataclass` because Pydantic could not serialize an `Exception` — was resolved
by replacing the live `error: Exception | None` field with two string fields:
`error_type: str | None` (the exception class name) and
`error_message: str | None` (the formatted message). This keeps the entire
execution trace JSON-serializable end-to-end.

Do **not** add a live `Exception` field back to either model; the
`error_type` / `error_message` pair is the contract.

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
| ~~`analyzer.py`~~ | #77 ✅ | Offline schema-compatibility analyzer (delivered) |
| `observer.py` | #78 | Runtime flow observer |
| ~~`viz.py`~~ | #79 ✅ | Flow visualization (delivered) |
| ~~`cli.py`~~ | #44 ✅ | CLI interface (delivered) |
| `mcp/` | #70, #72 | MCP adapter + flow server |
| `integrations/` | #82 | LangChain/LlamaIndex bridge adapters |
| `export/` | #25 | Flow export formats |
| `governance.py` | #13 | Governance policies |

### Weaver Stack guardrail

Issues #89–#91 introduce a kernel-backed executor (`KernelBackedExecutor`) that
delegates step execution to an agent-kernel. This is a **separate class** —
do not add agent-kernel or weaver-spec imports to `executor.py`. The core
`FlowExecutor` stays deterministic and standalone.
