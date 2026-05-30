# ChainWeaver — Agent Instructions

> Single source of truth for all coding agents working on this repository.
> For tool-specific wrappers, see the documentation map at the end of this file.

---

## 1. Project identity

ChainWeaver is a deterministic orchestration layer for MCP-based agents.
It compiles multi-tool flows into executable sequences that run without any
LLM involvement between steps.

- Python 3.10+; `from __future__ import annotations` in every module.
- Small runtime dependency set: `pydantic`, `typer`, `tenacity`, `packaging`, and `deepdiff`.
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
├── compat.py          schema_fingerprint() + check_flow_compatibility() + CompatibilityIssue
├── compiler.py        compile_flow(): static schema flow validation (CompilationResult)
├── contracts.py       ToolSafetyContract + SideEffectLevel/StabilityLevel/DeterminismLevel enums + merge_safety() + evaluate_predicate() — determinism + safety vocabulary (#19, #125, #9, #8)
├── decorators.py      @tool decorator for zero-boilerplate tool definition
├── tools.py           Tool class: named callable with Pydantic I/O schemas + schema_hash + safety contract (#19); Tool.from_flow() wraps a Flow as a Tool (#24) with derived safety (#125)
├── flow.py            FlowStep + Flow + DAGFlow + FlowStatus enum + DriftInfo dataclass + ConditionalEdge (#9) + determinism_level property (#8)
├── registry.py        FlowRegistry: multi-version catalogue with status filtering (store-backed)
├── storage.py         RegistryStore protocol + InMemoryStore + FileStore (#16)
├── analyzer.py        ChainAnalyzer: offline schema-compatibility analysis (#77)
├── attest.py          attest_flow() + AttestationReport: observed-determinism evidence (#154)
├── decisions.py       DecisionCallback Protocol + DecisionContext + coerce_decision_callback (#102)
├── executor.py        FlowExecutor: sequential/DAG runner + drift detection + stream_flow (main entry point)
├── middleware.py      FlowExecutorMiddleware Protocol + lifecycle context models + BaseMiddleware (#131)
├── events.py          FlowEvent streamable lifecycle payload yielded by FlowExecutor.stream_flow (#134)
├── cache.py           StepCache Protocol + InMemoryStepCache + FileStepCache + StepCacheKey (#127)
├── checkpoint.py      Checkpointer Protocol + ExecutionSnapshot + InMemoryCheckpointer + FileCheckpointer (#128)
├── integrations/      Optional third-party adapters (each guards its extra import)
│   ├── __init__.py    Package marker; documents available integrations
│   ├── opentelemetry.py  OTelTraceExporter middleware + export_result_to_otel (#126); requires chainweaver[otel]
│   ├── langchain.py   from_/to_langchain_tool + from_langchain_toolkit (#82); requires chainweaver[langchain]
│   ├── llamaindex.py  from_/to_llamaindex_tool (#82); requires chainweaver[llamaindex]
│   ├── weaver_spec.py    SelectableItem/RoutingDecision/CapabilityToken mirror types + flow_to_selectable_item (#91, #107)
│   ├── contextweaver.py  RoutingDecisionAdapter (DecisionCallback impl) + ContextweaverClient Protocol (#106)
│   └── agent_kernel.py   KernelBackedExecutor + KernelProtocol + InMemoryKernel (#89)
├── mcp/               MCP integration (issues #70, #72, #150); requires chainweaver[mcp]
│   ├── __init__.py    Public surface: MCPToolAdapter, FlowServer, jsonschema_to_pydantic
│   ├── _schema.py     JSON Schema ↔ Pydantic bridge
│   ├── adapter.py     MCPToolAdapter: wrap MCP server tools as ChainWeaver Tools (#70, #150)
│   └── server.py      FlowServer: expose flows as MCP tools via FastMCP (#72)
├── contrib/           Curated deterministic stdlib tools (#145); pip install 'chainweaver[contrib]'
│   ├── __init__.py    Re-exports the public tool set
│   └── tools.py       passthrough, json_pluck, json_set, assert_equal, map_list, filter_list
├── export/            Schema export adapters (#25) — no external dep imports
│   ├── __init__.py    Re-exports flow_to_*, tool_to_*
│   ├── _schema.py     Shared input/output schema derivation
│   ├── openai.py      flow_to_openai_function + tool_to_openai_function
│   ├── anthropic.py   flow_to_anthropic_tool + tool_to_anthropic_tool
│   └── callable.py    flow_to_callable + tool_to_callable (plain dict → dict)
├── testing/           Public test harness for flows (#132, #153)
│   ├── __init__.py    Re-exports FlowTestRunner / fake_tool / capture_steps / assert_result_matches / record_then_replay / FixtureStaleError / RecordReplayMode / DEFAULT_IGNORE_FIELDS
│   ├── fakes.py       fake_tool: permissive-schema Tool factory for tests
│   ├── runner.py      FlowTestRunner facade + capture_steps context manager
│   ├── assertions.py  assert_result_matches with volatile-field normalisation
│   └── replay.py      record_then_replay decorator + FixtureStaleError (#153); hooks at Tool._call_fn — never inside executor.py
├── plugins.py         discover_tools() + discover_flows() over importlib.metadata entry points (#130)
├── exceptions.py      Typed exception hierarchy (all inherit ChainWeaverError)
├── log_utils.py       Structured per-step logging utilities
├── cost.py            CostProfile + CostReport for cost-avoided estimation; PriceSnap + PROVIDER_PRICES maintained price table + lookup_price + CostProfile.from_provider (#156)
├── observation.py     TraceRecorder + ObservedTrace for ad-hoc capture
├── viz.py             ASCII + Mermaid renderers for Flow/ExecutionResult
├── serialization.py   YAML + JSON encode/decode for Flow and DAGFlow
├── schemas.py         JSON Schema export for .flow.json / .flow.yaml files (#135, #139)
├── cli.py             typer-based CLI: inspect, validate, check, viz, run, profile, diff, attest, suggest, doctor, dump-schema
└── py.typed           PEP 561 marker
tests/
├── conftest.py        Pytest fixtures (import schemas/functions from helpers.py)
├── helpers.py         Shared Pydantic schemas and tool functions
├── test_*.py          Test files
examples/
├── simple_linear_flow.py    Runnable standalone usage example
├── coding_agent_*.py        Coding-agent workflow templates (#173): PR review, changelog, debug-log triage
├── cookbook/                Paired scripts for docs/cookbook/ recipes (#146)
└── (other domain-specific demos)
docs/
├── index.md                 Hosted-site landing page
├── boundaries.md            Fit / non-fit guidance (#169)
├── comparisons.md           vs LangChain / Prefect / Dagster / Temporal / LangGraph (#141)
├── data-integrity.md        Five formal guarantees for compiled flow execution (#104)
├── cookbook/                Six runnable recipes for the hosted docs site (#146)
├── getting-started/, concepts/, reference/   Hosted-site nav sections (#133)
├── cli.md, security.md, versioning-policy.md, v1-release-criteria.md
└── agent-context/           Agent-specific deep-dive docs
mkdocs.yml                   MkDocs Material site config (#133)
.readthedocs.yaml            Read the Docs build config (#133)
pytest_chainweaver.py        Top-level pytest plugin module (#132); registered via [project.entry-points.pytest11]. Deliberately outside the chainweaver/ package so pytest's entry-point loader does not transitively import chainweaver before pytest-cov starts coverage measurement.
pyproject.toml               Ruff, mypy, pytest config (source of truth for tooling)
scripts/                     Maintenance scripts run from CI, not shipped in the package — refresh_prices.py keeps cost.py PROVIDER_PRICES fresh (#156)
benchmarks/                  Standalone benchmark scripts (not coverage-gated): bench_naive_vs_compiled.py (#29), bench_correctness.py (#103), report.py (#207); results/ holds generated latest.{json,md}
.github/workflows/           CI (ci.yml), docs (docs.yml), bench (bench.yml), publish (publish.yml), and update-prices.yml (#156) workflows
```

### Key entry points

- `FlowExecutor(..., decision_callback=...)` → wire a `DecisionCallback` for guided decision points (#102); steps with `decision_candidates` set call the callback to pick which tool to run.  Either a class with `decide(ctx)` or a bare callable is accepted (coerced via `coerce_decision_callback`).
- `KernelBackedExecutor(..., kernel=...)` from `chainweaver.integrations.agent_kernel` (#89) → optional `FlowExecutor` subclass that delegates `DAGFlowStep` instances with `step_type="capability"` through a `KernelProtocol`.  The base `FlowExecutor` rejects capability steps; only this subclass dispatches them.
- `flow_to_selectable_item(flow, *, capability_id=None, tags=())` from `chainweaver.integrations.weaver_spec` (#107) → project a `Flow` or `DAGFlow` to a weaver-spec `SelectableItem` for contextweaver catalog ingestion.
- `RoutingDecisionAdapter(client=...)` from `chainweaver.integrations.contextweaver` (#106) → `DecisionCallback` impl that asks a `ContextweaverClient` for a `RoutingDecision` and returns the selected capability id.
- `FlowExecutor.execute_flow(flow_name, initial_input, *, force=False)` → `ExecutionResult`
- `FlowExecutor.execute_flow_async(flow_name, initial_input, *, force=False)` → `Awaitable[ExecutionResult]` (#80); async-native counterpart of `execute_flow`. Dispatches each step through `Tool.run_async` so async-fn tools (e.g. those produced by `chainweaver.mcp.MCPToolAdapter`) execute on the calling loop and sync-fn tools are offloaded to `asyncio.to_thread`. Supports linear and DAG flows with retries, middleware, and on_error policies; defers step cache + checkpoint resume to a follow-up.
- `FlowExecutor.stream_flow(flow_name, initial_input, *, force=False)` → `Iterator[FlowEvent]` (#134); yields `kind="flow_start"` → (`step_start` → `step_end`)* → `flow_end` events as the flow runs on a worker thread. Cancellation is not supported for the sync variant; the background thread runs to completion.
- `FlowExecutor(..., step_cache=...)` → memoize step outputs across runs (#127); keyed by `(tool_name, schema_hash, input_value_hash)`. Cache hits skip `Tool.fn` entirely (including retries and timeout) and surface as `StepRecord.cached=True`. Tools mark themselves `cacheable=False` to always run (side-effects, external state). `replay_flow` always bypasses the cache.
- `FlowExecutor(..., checkpointer=..., delete_on_success=True)` → crash-resume (#128); writes an `ExecutionSnapshot` after every successful linear step or DAG level. `FlowExecutor.resume_flow(trace_id)` validates the snapshot's flow version and tool `schema_hash` values against the current registry — drift raises `CheckpointDriftError` — then continues execution with the original `trace_id`. Snapshots are deleted on terminal success when `delete_on_success=True` (the default); preserved on failure for operator-driven retry.
- `OTelTraceExporter(tracer=...)` from `chainweaver.integrations.opentelemetry` (#126) → emits OpenTelemetry spans as a `FlowExecutorMiddleware`: one parent `chainweaver.flow.{name}` span + one child `chainweaver.tool.{name}` span per `StepRecord`. After-the-fact export of a completed `ExecutionResult` via `export_result_to_otel(result, tracer=...)`. Optional extra: `pip install 'chainweaver[otel]'`.
- `MCPToolAdapter(session)` from `chainweaver.mcp` (#70, #150) → wraps each MCP tool advertised by an open `mcp.ClientSession` as a ChainWeaver `Tool`. `await adapter.discover_tools(server_prefix="…")` returns the wrapped tools; pass `include=[…]` to filter. The resulting tools are async-fn and must be run through `execute_flow_async`. Optional extra: `pip install 'chainweaver[mcp]'`.
- `FlowServer(executor, *, name="chainweaver", flow_names=None, server_prefix="")` from `chainweaver.mcp` (#72) → mounts registered flows as MCP tools on a FastMCP server. `server.serve(transport="stdio")` blocks; `await server.serve_async(transport=...)` returns to the loop. Synthesises the dispatcher signature from the flow's input schema so MCP clients call `tool(n=5)` directly. Optional extra: `pip install 'chainweaver[mcp]'`.
- `FlowExecutor(..., middleware=[...])` → register lifecycle hooks (#131); fire order is `on_flow_start` → (`on_step_start` → `on_step_end`)* → `on_flow_end`. Hook exceptions are caught and logged at `WARNING` (chainweaver.middleware) — observability bugs never abort a flow.
- `FlowExecutor.add_middleware(mw)` → append a middleware to the registration sequence
- `FlowRegistry.register_flow(flow, *, overwrite=False)` → register a flow
- `FlowRegistry.get_flow(name, *, version=None)` → latest or specific version
- `FlowExecutor.register_tool(tool)` → register a tool; triggers drift detection on schema change
- `FlowExecutor.registry` → read-only accessor for the backing `FlowRegistry` (used by `chainweaver.mcp.FlowServer` to enumerate exposable flows without touching executor internals)
- `FlowExecutor.get_drift_report()` → `list[DriftInfo]`
- `FlowExecutor.accept_drift(flow_name)` → re-snapshot hashes, restore ACTIVE status
- `compile_flow(flow, tools)` → `CompilationResult`
- `attest_flow(flow, executor, n, repeats, seed, seed_inputs=None)` → `AttestationReport` (#154); observed-determinism evidence via N×M execution loop with seeded input generation. Emits a reproducible `aggregate_fingerprint` when all repeats agree.

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

### `Flow` (Pydantic model)

The rows below are the actual Pydantic fields (`Flow.model_fields`), in
declaration order. `DAGFlow` carries the same field **names**, with two
differences: `version` is **required** (no default), and `steps` is typed
`list[DAGFlowStep]` (which extends `FlowStep` with conditional `branches` —
see the `DAGFlowStep` subsection below).

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `name` | `str` | — (required) | Unique identifier for the flow. |
| `version` | `str` | `"0.1.0"` | SemVer string. Required on `DAGFlow` (no default). Surfaced on every `ExecutionResult` as `flow_version`. |
| `description` | `str` | — (required) | Human-readable description of what the flow does. |
| `steps` | `list[FlowStep]` | — (required) | Ordered list of tool invocations. |
| `deterministic` | `bool` | `True` | Metadata annotation for downstream orchestrators. `FlowExecutor` is unconditionally LLM-free and does not evaluate this flag. |
| `status` | `FlowStatus` | `ACTIVE` | Lifecycle gate (`active` / `needs_review` / `disabled`). Non-`ACTIVE` flows are refused by `execute_flow` unless `force=True`. |
| `trigger_conditions` | `dict[str, Any] \| None` | `None` | Free-form metadata for higher-level orchestrators; ChainWeaver itself does not evaluate these. |
| `input_schema_ref` | `str \| None` | `None` | `"module:qualname"` ref to a Pydantic model validating `initial_input` before the first step runs. Resolved lazily by the `input_schema` property. |
| `output_schema_ref` | `str \| None` | `None` | `"module:qualname"` ref to a Pydantic model validating the final merged context. Resolved lazily by the `output_schema` property. |
| `context_schema_ref` | `str \| None` | `None` | `"module:qualname"` ref for the accumulated execution context (#152). Resolved lazily by the `context_schema` property; validated at flow end. |
| `tool_schema_hashes` | `dict[str, str] \| None` | `None` | Snapshot of per-tool schema fingerprints (#50). Drives drift detection and `doctor --check-drift`. |
| `capability_id` | `str \| None` | `None` | Optional Weaver Stack capability identifier (#90); when set, the flow is routable as a `SelectableItem` via `flow_to_selectable_item`. See [docs/agent-context/flow-as-capability.md](docs/agent-context/flow-as-capability.md). |

**Read-only properties (not fields):** `input_schema`, `output_schema`, and
`context_schema` resolve their `*_schema_ref` counterparts to a
`type[BaseModel] | None`. `determinism_level` is a computed
`DeterminismLevel` (#8): linear `Flow` → `FULL` (or `NONE` if
`deterministic=False`); `DAGFlow` with any conditional `branches` → `PARTIAL`.

### `DAGFlowStep` conditional branching (#9)

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `branches` | `list[ConditionalEdge]` | `[]` | Outgoing guards.  After this step runs, the first `ConditionalEdge` whose `predicate` evaluates truthy against the merged context picks the active downstream path; non-selected immediate dependents are recorded as `StepRecord(skipped=True)`.  Empty list (default) → unconditional fan-out, every dependent runs. |
| `default_next` | `str \| None` | `None` | Fallback `target_step_id` when no `ConditionalEdge` matches.  Only meaningful alongside non-empty `branches`. |

Predicates are evaluated by `chainweaver.contracts.evaluate_predicate`, which parses the string with `ast` and walks the tree by hand — `eval()` is **never** called.  Predicate syntax errors and unsupported AST nodes raise `PredicateSyntaxError` and abort the flow with a synthetic failed `StepRecord`.

Branching is only supported on `step_type="tool"` steps.  Capability steps (`step_type="capability"`) are dispatched through `_execute_capability_step` before `_select_branch` runs, so `branches` / `default_next` are rejected on them at construction (a `DAGFlowStep` validator) rather than silently ignored.

### `FlowStep.input_mapping`

| Value type | Behavior |
|------------|----------|
| `str` | Looked up as a key in the accumulated execution context. |
| Non-string (`int`, `float`, `bool`, …) | Used as a literal constant. |
| Empty `{}` (default) | The tool receives the full current context. |

### `FlowStep.decision_candidates` (issue #102)

Optional `list[str] | None` (default `None`).  When set together with an
executor-level `decision_callback`, the executor asks the callback to
choose which candidate tool to invoke for this step.  The callback
receives a `DecisionContext` and must return a member of
`decision_candidates`.  Callback failures (raise, or return outside the
list) abort the step with `DecisionCallbackError`.  When
`decision_candidates` is `None` *or* no callback is registered, the
step's static `tool_name` is used — flows stay runnable without the
integration.

### `ExecutionResult` (Pydantic `BaseModel`)

| Field | Type | Meaning |
|-------|------|---------|
| `flow_name` | `str` | Name of the executed flow. |
| `success` | `bool` | `True` when all steps completed without error. |
| `final_output` | `dict \| None` | Merged execution context, or `None` on failure. |
| `execution_log` | `list[StepRecord]` | Ordered per-step records. |
| `trace_id` | `str` | UUID4 hex string assigned at the start of execution; correlates with logs. |
| `started_at` | `datetime` | UTC timestamp when execution began. |
| `ended_at` | `datetime` | UTC timestamp when execution finished. |
| `total_duration_ms` | `float` | Wall-clock duration in ms (via `time.perf_counter`). |

### `StepRecord` (Pydantic `BaseModel`)

| Field | Type | Meaning |
|-------|------|---------|
| `step_index` | `int` | Zero-based position (`-1` = flow-input validation, `len(steps)` = flow-output validation). |
| `tool_name` | `str` | Tool invoked (or flow name for validation records). |
| `inputs` | `dict` | Validated inputs passed to the tool. |
| `outputs` | `dict \| None` | Validated outputs, or `None` on failure. |
| `error_type` | `str \| None` | Exception class name (e.g. `"FlowExecutionError"`) when the step failed; `None` on success. |
| `error_message` | `str \| None` | Human-readable error text when the step failed; `None` on success. |
| `success` | `bool` | `True` when the step completed without error. |
| `started_at` | `datetime` | UTC timestamp when the step began. |
| `ended_at` | `datetime` | UTC timestamp when the step finished. |
| `duration_ms` | `float` | Wall-clock duration in ms (via `time.perf_counter`). |

> **Serialization:** `ExecutionResult` and `StepRecord` are Pydantic models;
> `result.model_dump_json()` and `ExecutionResult.model_validate_json(...)`
> round-trip cleanly. Errors are stored as `error_type` / `error_message`
> strings rather than live `Exception` instances so the trace is fully
> JSON-serializable.

---

## 6. Common tasks

| Task | Where to look | What to update |
|------|---------------|----------------|
| Add a new tool | `tools.py` | Integration tests in `test_flow_execution.py` |
| Add a new exception | `exceptions.py` | `__init__.py` + `__all__` + README error table — **same PR** |
| Modify flow execution | `executor.py` | Keep `StepRecord` + `ExecutionResult` consistent |
| Add a new Flow field | `flow.py` | Serialization tests if `model_dump()` changes |
| Add a new DAGFlow / DAGFlowStep field | `flow.py` | Update `validate_dag_topology` if needed; update tests |
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
python -m mypy chainweaver/ tests/
python -m pytest tests/ -v
```

CI runs lint + format + mypy on Python 3.10 / `ubuntu-latest` only; tests
run across `{ubuntu-latest, windows-latest, macos-latest} × {3.10, 3.11,
3.12, 3.13}` (12 jobs in total). A separate `bench.yml` workflow runs
the naive-vs-compiled benchmark on `ubuntu-22.04` and fails PRs whose
median `total_duration_ms` regresses beyond 125 % of the `gh-pages`
baseline (see [benchmarks/README.md](benchmarks/README.md)).

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
| [versioning-policy.md](docs/versioning-policy.md) | SemVer policy, public-API scope, deprecation process | Adding / removing / renaming public symbols, planning a release |
| [flow-as-capability.md](docs/agent-context/flow-as-capability.md) | Treating a flow as a Weaver Stack capability (#90); `Flow.capability_id`; `flow_to_selectable_item` exporter | Setting capability identity on a flow, exporting to contextweaver |
| [SPEC_COMPAT.md](docs/SPEC_COMPAT.md) | Declared `weaver-spec` v0.1.0 compatibility (#91); conformance test + CI gate | Bumping the declared spec version, changing the weaver_spec mirror types |
| [v1-release-criteria.md](docs/v1-release-criteria.md) | Measurable v1.0.0 release bar | Before tagging a release, when scoping issues against the v1.0 milestone |

---

## 10. Update policy

- **Every PR:** check whether AGENTS.md or any `docs/agent-context/` file is
  stale with respect to the change. Update in the same PR if so.
- **Architecture changes** (add/remove/rename modules): update AGENTS.md repo
  map and architecture.md in the same PR.
- **Ownership rule:** if you change the architecture, you own the doc update.
- **Contradictions:** if you find a contradiction between docs, fix it in the
  same PR if small, or open an issue if large.
