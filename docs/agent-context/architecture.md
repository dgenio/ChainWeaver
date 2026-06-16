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
| `contracts.py` | `ToolSafetyContract`, `SideEffectLevel`, `StabilityLevel`, `DeterminismLevel`, `merge_safety()`, `evaluate_predicate()` — determinism + operational safety vocabulary (#19, #125, #293, #9, #8) | Pure module: enums + frozen Pydantic model + AST-based predicate evaluator. Safety metadata is descriptive; enforcement belongs to a host/policy surface such as `FlowServer`. |
| `decorators.py` | `@tool` decorator for zero-boilerplate tool definition | Returns a `Tool` subclass; introspects type hints |
| `tools.py` | Define `Tool`: name + callable + Pydantic I/O schemas + `schema_hash` + `safety` contract (#19); `Tool.from_flow()` adapter (#24) with `merge_safety` derivation (#125) | Tool functions must be `fn(BaseModel) -> dict[str, Any]`; `from_flow` reuses the same contract — its closure dispatches `FlowExecutor.execute_flow` and surfaces inner failures as `FlowExecutionError` |
| `flow.py` | Define `FlowStep`, `Flow`, `DAGFlowStep`, `DAGFlow`, `FlowStatus`, `FlowLifecycle`, `FlowGovernance`, `DriftInfo`, `ConditionalEdge` (#9), `validate_dag_topology` | Pure data definitions + topology/lifecycle-transition validation + structural `determinism_level` inference; governance lifecycle stays separate from the executor's operational `FlowStatus`. |
| `step_index.py` | Named sentinels for synthetic flow input/output validation records (#339) | Pure helper module; keeps validation-record sentinel values out of executor call sites. |
| `registry.py` | Store and retrieve `Flow`/`DAGFlow` by `(name, version)`; status filtering; multi-version support | Delegates persistence to a `RegistryStore`; defaults to `InMemoryStore` |
| `storage.py` | `RegistryStore` Protocol + `InMemoryStore` (default) + `FileStore` (one JSON file per flow) | Filenames are `{name}@{version}.flow.json`; concurrent multi-process access not coordinated |
| `analyzer.py` | `ChainAnalyzer`: offline schema-compatibility analysis — compatibility matrix, chain enumeration, suggested flows (#77) | Pure static pass: no LLM, no network, no randomness; cycle-free DFS bounded by `max_depth` |
| `decisions.py` | `DecisionCallback` Protocol + `DecisionContext` + `coerce_decision_callback` (#102) | Pure protocol module — no executor logic, no network, no randomness; the executor depends on it but it does not depend on the executor |
| `executor.py` | Run flows step-by-step (linear) or level-by-level (DAG), validate I/O, merge context, drift detection, invoke `DecisionCallback` at decision points, dispatch capability steps via the `_execute_capability_step` hook. `execute_flow_async` provides the async lane (#80). | **No LLM, no network I/O, no randomness.** No `agent-kernel` / `weaver-spec` / `contextweaver` imports — those live in `integrations/` and reach the executor only via the `DecisionCallback` seam and `KernelBackedExecutor` subclass hook |
| `integrations/weaver_spec.py` | Re-exports the `weaver-contracts` types (`SelectableItem`, `RoutingDecision`, `CapabilityToken`, …); `flow_to_selectable_item()` exporter; routing resolvers (`make_routing_decision`, `selected_capability_id`, `resolve_flow_from_routing_decision`); `WEAVER_SPEC_VERSION` (#91, #107, #233) | Consumes the published `weaver-contracts` package behind the `[weaver-stack]` extra — guarded import raises a clear `ImportError` without it |
| `integrations/contextweaver.py` | `RoutingDecisionAdapter` (`DecisionCallback` impl) + `ContextweaverClient` Protocol + `StaticRoutingClient` (#106) | Translates `RoutingDecision` → tool name; no hard dep on a `contextweaver` SDK |
| `integrations/agent_kernel.py` | `KernelBackedExecutor` (FlowExecutor subclass) + `KernelProtocol` + `InMemoryKernel` (#89) | Overrides only `_execute_capability_step`; no LLM, no randomness; kernel side-effects are the kernel's responsibility |
| `mcp/` | MCP integration package (#70, #72, #150, #259, #294): `MCPToolAdapter` (inbound), metadata-aware `FlowServer` (outbound), JSON Schema ↔ Pydantic bridge. | Default outbound exposure requires active lifecycle plus known read-only, approval-free safety. Explicit `flow_names` is the operator override. |
| `exceptions.py` | Typed exception hierarchy | All inherit `ChainWeaverError`; carry context attrs |
| `log_utils.py` | Per-step structured logging | Library-safe (NullHandler only); no handler config |
| `cost.py` | `CostProfile` + `CostReport` for cost-avoided estimation | Pure data + a single ``compute_cost_report`` helper; no execution logic |
| `observation.py` | `TraceRecorder` + `ObservedTrace` for ad-hoc tool sequence capture | In-memory storage only; persistence deferred |
| `observer.py` | `ChainObserver` + `FlowSuggestion`: record runtime tool calls, mine repeated contiguous sub-sequences, propose flows (#78) | Pure n-gram counting: no LLM, no network, no randomness; suggestions are proposals, never auto-registered |
| `lessons.py` | `trace_to_lesson_candidate()` + `LessonCandidate` / `LessonEvidenceStep` / `LessonReview`: normalise an `ExecutionResult` into a reviewable, workflow-scoped lesson candidate for the Weaver Stack's `lessonweaver` (#210) | Pure projection: no LLM, no network, no randomness; **no hard dependency on `lessonweaver`** (emits neutral Pydantic data); identifies the failure point but never asserts the lesson outcome; banned from `executor.py` |
| `service.py` | `ChainWeaverService` + `ServiceConfig` + `ServiceMetrics` + `ServiceEvent`: continuous analyze→observe→propose→govern loop (#101) | Ties analyzer + observer + an in-service proposal gate; LLM hooks opt-in; full `GovernanceManager` (#13) integration deferred |
| `viz.py` | `flow_to_ascii`, `flow_to_mermaid`, `result_to_mermaid` pure renderers | No external dependencies — string generation only |
| `serialization.py` | YAML + JSON encode/decode for `Flow` and `DAGFlow` (`flow_to_json`, `flow_from_yaml`, etc.) | JSON path is dep-free; YAML requires `pyyaml` (optional extra `chainweaver[yaml]`); schema/exception refs round-trip as `"module:qualname"` strings |
| `cli.py` | typer-based CLI hosting the full command surface: `inspect`, `viz`, `validate`, `check`, `run`, `profile`, `diff`, `attest`, `suggest`, `dump-schema`, `doctor` | `inspect` / `viz` read from a process-scoped default registry installed via `cli.set_default_registry`; the file-oriented commands (`validate`, `check`, `run`, `profile`, `diff`, `attest`, `suggest`, `doctor`) read directly from disk |
| `testing/` | Public test harness for flows (`FlowTestRunner`, `fake_tool`, `capture_steps`, `assert_result_matches`, `record_then_replay`) (#132, #153) | Hooks at the `Tool.fn` boundary — never edits `executor.py`. Helpers are imported as `from chainweaver.testing import ...`, mirroring the `integrations.opentelemetry` pattern; not re-exported from top-level `__all__` (except `FixtureStaleError`, which follows the error-catalog convention) |
| `pytest_chainweaver` (top-level) | Pytest plugin registered via `pytest11`: `flow_runner` / `flow_runner_session` fixtures + `@pytest.mark.flow(...)` marker | Lives outside the `chainweaver/` package so `pytest-cov` starts coverage **before** the library is imported (see Design traps below) |
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
| `step_type` + `capability_id` on `DAGFlowStep` | Per-step capability slot for Weaver Stack kernel integration (weaver-spec I-07).  `"capability"`-typed steps are dispatched by `KernelBackedExecutor._execute_capability_step` (#89); the base `FlowExecutor` rejects them. |
| `Flow.capability_id` and `DAGFlow.capability_id` (#90) | Flow-level capability identifier — distinct from `DAGFlowStep.capability_id`.  Names *the flow itself* as a routable capability; resolved by `flow_to_selectable_item()` for contextweaver catalog ingestion. |
| `FlowStatus` vs `FlowLifecycle` (#268) | `FlowStatus` is the executor's operational gate (active / needs-review / disabled). `FlowLifecycle` is the macro-flow review path (observed / suggested / draft / reviewed / active / ignored / archived). Never overload one for the other. |
| `DecisionCallback` Protocol in `chainweaver/decisions.py` (#102) | Single LLM-router / contextual-narrowing extension point.  Executor invokes it for steps with `decision_candidates` set; failures wrap as `DecisionCallbackError` and abort the step (no silent fall-through to `tool_name`). |
| Consume `weaver-contracts` behind an optional extra (#91, #107, #233) | The weaver-spec contract ships on PyPI as `weaver-contracts`.  ChainWeaver consumes its I-03 / I-04 / I-07 dataclasses directly via the optional `[weaver-stack]` extra rather than carrying mirror types — `chainweaver.integrations.weaver_spec` (and the `contextweaver` / `agent_kernel` adapters that import it) guard the import and raise a clear `ImportError` when the extra is absent, so the base install stays dependency-light. |
| `KernelBackedExecutor` as a subclass, not a flag (#89) | Subclass overrides only the `_execute_capability_step` hook.  Keeps the executor's three invariants (no LLM, no network I/O, no randomness in `executor.py`) intact — kernel side-effects live in `integrations/agent_kernel.py`. |
| Cycle detection at registration time | Fail fast — no silent deferral to execution. Belt-and-suspenders check also runs in the executor for flows created without registry. |
| Branch targets must be direct dependents (#9) | Keeps conditional routing local — a `ConditionalEdge.target_step_id` (or `default_next`) must reference a step that already lists the branching step in its `depends_on`.  This makes "skipped" propagation a one-hop computation in the executor and prevents branches from jumping across unrelated subgraphs.  Enforced at registration time by `validate_dag_topology`. |
| AST-based predicate evaluator (#9) | Predicate strings are parsed with `ast.parse(mode="eval")` and walked against an explicit node allow-list — `eval`/`exec` are **never** called.  The grammar deliberately excludes attribute access, function calls, and binary arithmetic so predicates stay routing decisions, not computations (unary `+`/`-` is permitted so signed literals like `n == -1` parse). |

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

### `pytest_chainweaver.py` lives at the repo root, not under `chainweaver/`

The `pytest11` entry-point registered in `pyproject.toml` points at the
top-level `pytest_chainweaver` module rather than at
`chainweaver.testing.plugin` (#132). This is **deliberate**: pytest
loads `pytest11` plugins by importing the entry-point module, and any
module under `chainweaver.*` transitively triggers
`chainweaver/__init__.py`, which eagerly imports the entire library.
If that import cascade happens before `pytest_cov.plugin` can start
coverage tracking, every import-time statement in the package is
counted as "missed" — coverage collapses from ~94 % to ~64 %.

Keeping the plugin out of the `chainweaver` namespace breaks that
chain: pytest's entry-point loader touches only `pytest_chainweaver`
plus `pytest` itself, and the heavy `chainweaver` imports happen
lazily inside the fixture bodies. The module is included in the wheel
via `[tool.setuptools] py-modules = ["pytest_chainweaver"]`.

Do not move the plugin under `chainweaver/testing/` to "tidy up" the
layout.

### `chainweaver.testing` helpers are NOT in top-level `__all__`

Like `chainweaver.integrations.opentelemetry`, the test-harness symbols
(`FlowTestRunner`, `fake_tool`, etc.) are exported from the subpackage
`chainweaver.testing` and intentionally absent from
`chainweaver/__init__.py` `__all__`. This keeps the public-API
snapshot focused on runtime symbols and lets test helpers evolve
without churning the snapshot fixture.

### `record_then_replay` monkey-patches `Tool._call_fn` / `_call_fn_async`, not `Tool.run`

The decorator swaps `Tool._call_fn` (the boundary between Pydantic
validation and the user-supplied callable) — not `Tool.run` — so
input and output schema validation still execute during replay. A
stale fixture with a now-invalid output payload therefore fails the
output validator loudly, the same way a real `Tool.fn` returning bad
data would.

Both `Tool._call_fn` and `Tool._call_fn_async` are patched so the
synchronous lane (`FlowExecutor.execute_flow`) and the async lane
(`FlowExecutor.execute_flow_async`) are covered. The two must record
each logical call **exactly once**, but an async tool reached through
the sync lane enters `_call_fn`, which bridges to `_call_fn_async` via
`asyncio.run` — so both patched methods sit in the call stack for that
one call. The sync patch therefore records/replays only *sync* tools
and passes *async* tools straight through to the async patch, which is
the single record/replay point for them. (Sync tools never reach
`_call_fn_async`; async-lane calls never reach `_call_fn`.)

Both methods are class-level monkey-patched and restored in a `finally`
block. This is intentional: a context-local variable would require
threading a session handle through every `Tool` invocation, which
defeats the decorator's drop-in shape. The trade-off: concurrent
record/replay sessions (e.g. under `pytest-xdist`) are not supported.

---

## Planned modules

The following module names are reserved for planned features. Do not create
files that conflict with these names:

| Reserved name | Issue | Purpose |
|---------------|-------|---------|
| ~~`analyzer.py`~~ | #77 ✅ | Offline schema-compatibility analyzer (delivered) |
| ~~`decisions.py`~~ | #102 ✅ | `DecisionCallback` Protocol (delivered) |
| ~~`observer.py`~~ | #78 ✅ | Runtime flow observer + flow suggestion (delivered) |
| ~~`viz.py`~~ | #79 ✅ | Flow visualization (delivered) |
| ~~`cli.py`~~ | #44 ✅ | CLI interface (delivered) |
| ~~`schemas.py`~~ | #135 ✅ | JSON Schema export for flow files (delivered) |
| ~~`mcp/`~~ | #70, #72, #150 ✅ | MCP adapter + flow server (delivered; requires `chainweaver[mcp]`) |
| ~~`integrations/weaver_spec.py`~~ | #91, #107, #233 ✅ | Consumes `weaver-contracts`; `SelectableItem` exporter + routing resolvers (delivered) |
| ~~`integrations/contextweaver.py`~~ | #106 ✅ | `RoutingDecisionAdapter` (delivered) |
| ~~`integrations/agent_kernel.py`~~ | #89 ✅ | `KernelBackedExecutor` (delivered) |
| `integrations/langchain.py` / `integrations/llama_index.py` | #82 | LangChain / LlamaIndex bridge adapters |
| `export/` | #25 | Flow export formats |
| `governance.py` | #13 | Governance policies |

### Weaver Stack guardrail (still in force after #89/#90/#91/#102/#106/#107)

`KernelBackedExecutor` (#89) is a **separate subclass** of `FlowExecutor` —
do not add `agent-kernel`, `weaver-spec`, or `contextweaver` imports to
`executor.py` itself. The core `FlowExecutor` stays deterministic and
standalone; the only seams that reach into integrations are:

- The `DecisionCallback` Protocol from `chainweaver.decisions` (a
  protocol — no third-party imports leak through it).
- The `_execute_capability_step` hook — overridden by
  `KernelBackedExecutor`, not by the base class.

`docs/SPEC_COMPAT.md` declares the supported weaver-spec range; changing it
follows the procedure documented there.
