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
├── compat.py          schema_fingerprint() + check_flow_compatibility() + CompatibilityIssue
├── compiler.py        compile_flow(): static schema flow validation (CompilationResult)
├── decorators.py      @tool decorator for zero-boilerplate tool definition
├── tools.py           Tool class: named callable with Pydantic I/O schemas + schema_hash; Tool.from_flow() wraps a Flow as a Tool (#24)
├── flow.py            FlowStep + Flow + DAGFlow + FlowStatus enum + DriftInfo dataclass
├── registry.py        FlowRegistry: multi-version catalogue with status filtering (store-backed)
├── storage.py         RegistryStore protocol + InMemoryStore + FileStore (#16)
├── analyzer.py        ChainAnalyzer: offline schema-compatibility analysis (#77)
├── attest.py          attest_flow() + AttestationReport: observed-determinism evidence (#154)
├── executor.py        FlowExecutor: sequential/DAG runner + drift detection + stream_flow (main entry point)
├── middleware.py      FlowExecutorMiddleware Protocol + lifecycle context models + BaseMiddleware (#131)
├── events.py          FlowEvent streamable lifecycle payload yielded by FlowExecutor.stream_flow (#134)
├── cache.py           StepCache Protocol + InMemoryStepCache + FileStepCache + StepCacheKey (#127)
├── checkpoint.py      Checkpointer Protocol + ExecutionSnapshot + InMemoryCheckpointer + FileCheckpointer (#128)
├── integrations/      Optional third-party adapters (each guards its extra import)
│   ├── __init__.py    Package marker; documents available integrations
│   └── opentelemetry.py  OTelTraceExporter middleware + export_result_to_otel (#126); requires chainweaver[otel]
├── testing/           Public test harness for flows (#132, #153)
│   ├── __init__.py    Re-exports FlowTestRunner / fake_tool / capture_steps / assert_result_matches / record_then_replay / FixtureStaleError / RecordReplayMode / DEFAULT_IGNORE_FIELDS
│   ├── fakes.py       fake_tool: permissive-schema Tool factory for tests
│   ├── runner.py      FlowTestRunner facade + capture_steps context manager
│   ├── assertions.py  assert_result_matches with volatile-field normalisation
│   └── replay.py      record_then_replay decorator + FixtureStaleError (#153); hooks at Tool._call_fn — never inside executor.py
├── exceptions.py      Typed exception hierarchy (all inherit ChainWeaverError)
├── log_utils.py       Structured per-step logging utilities
├── cost.py            CostProfile + CostReport for cost-avoided estimation
├── observation.py     TraceRecorder + ObservedTrace for ad-hoc capture
├── viz.py             ASCII + Mermaid renderers for Flow/ExecutionResult
├── serialization.py   YAML + JSON encode/decode for Flow and DAGFlow
├── cli.py             typer-based CLI: inspect, validate, check, viz, run, profile
└── py.typed           PEP 561 marker
tests/
├── conftest.py        Pytest fixtures (import schemas/functions from helpers.py)
├── helpers.py         Shared Pydantic schemas and tool functions
├── test_*.py          Test files
examples/
└── simple_linear_flow.py   Runnable standalone usage example
pytest_chainweaver.py      Top-level pytest plugin module (#132); registered via [project.entry-points.pytest11]. Deliberately outside the chainweaver/ package so pytest's entry-point loader does not transitively import chainweaver before pytest-cov starts coverage measurement.
pyproject.toml             Ruff, mypy, pytest config (source of truth for tooling)
.github/workflows/         CI (ci.yml) and publish (publish.yml) pipelines
```

### Key entry points

- `FlowExecutor.execute_flow(flow_name, initial_input, *, force=False)` → `ExecutionResult`
- `FlowExecutor.stream_flow(flow_name, initial_input, *, force=False)` → `Iterator[FlowEvent]` (#134); yields `kind="flow_start"` → (`step_start` → `step_end`)* → `flow_end` events as the flow runs on a worker thread. Cancellation is not supported for the sync variant; the background thread runs to completion.
- `FlowExecutor(..., step_cache=...)` → memoize step outputs across runs (#127); keyed by `(tool_name, schema_hash, input_value_hash)`. Cache hits skip `Tool.fn` entirely (including retries and timeout) and surface as `StepRecord.cached=True`. Tools mark themselves `cacheable=False` to always run (side-effects, external state). `replay_flow` always bypasses the cache.
- `FlowExecutor(..., checkpointer=..., delete_on_success=True)` → crash-resume (#128); writes an `ExecutionSnapshot` after every successful linear step or DAG level. `FlowExecutor.resume_flow(trace_id)` validates the snapshot's flow version and tool `schema_hash` values against the current registry — drift raises `CheckpointDriftError` — then continues execution with the original `trace_id`. Snapshots are deleted on terminal success when `delete_on_success=True` (the default); preserved on failure for operator-driven retry.
- `OTelTraceExporter(tracer=...)` from `chainweaver.integrations.opentelemetry` (#126) → emits OpenTelemetry spans as a `FlowExecutorMiddleware`: one parent `chainweaver.flow.{name}` span + one child `chainweaver.tool.{name}` span per `StepRecord`. After-the-fact export of a completed `ExecutionResult` via `export_result_to_otel(result, tracer=...)`. Optional extra: `pip install 'chainweaver[otel]'`.
- `FlowExecutor(..., middleware=[...])` → register lifecycle hooks (#131); fire order is `on_flow_start` → (`on_step_start` → `on_step_end`)* → `on_flow_end`. Hook exceptions are caught and logged at `WARNING` (chainweaver.middleware) — observability bugs never abort a flow.
- `FlowExecutor.add_middleware(mw)` → append a middleware to the registration chain
- `FlowRegistry.register_flow(flow, *, overwrite=False)` → register a flow
- `FlowRegistry.get_flow(name, *, version=None)` → latest or specific version
- `FlowExecutor.register_tool(tool)` → register a tool; triggers drift detection on schema change
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

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `name` | `str` | — | Unique identifier for the flow. |
| `description` | `str` | — | Human-readable description of what the flow does. |
| `steps` | `list[FlowStep]` | — | Ordered list of tool invocations. |
| `deterministic` | `bool` | `True` | Metadata annotation for downstream orchestrators. `FlowExecutor` is unconditionally LLM-free and does not evaluate this flag. |
| `trigger_conditions` | `dict[str, Any] \| None` | `None` | Free-form metadata for higher-level orchestrators; ChainWeaver itself does not evaluate these. |
| `input_schema` | `type[BaseModel] \| None` | `None` | Optional Pydantic schema for validating `initial_input` before the first step runs. |
| `output_schema` | `type[BaseModel] \| None` | `None` | Optional Pydantic schema for validating the final merged context after the last step finishes. |

### `FlowStep.input_mapping`

| Value type | Behavior |
|------------|----------|
| `str` | Looked up as a key in the accumulated execution context. |
| Non-string (`int`, `float`, `bool`, …) | Used as a literal constant. |
| Empty `{}` (default) | The tool receives the full current context. |

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
3.12, 3.13}` (12 jobs in total).

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
