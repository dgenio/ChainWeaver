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
├── compiler_llm.py    Offline build-time LLM flow compiler: LLMProposal (+ provenance) + llm_propose_flows() + write_proposals()/read_provenance() + flow_proposal_schema() (#28, #363, #364); banned from executor.py
├── optimizer.py       Offline build-time tool-description optimizer: OptimizationStrategy + ToolDescriptionProposal + optimize_tool_descriptions()/optimize_new_tool_description() + description_proposal_schema() + routing-accuracy annotation (#100, #374); banned from executor.py
├── _offline_llm.py    Private shared internals for the offline LLM proposers: LLMFn type + parse_llm_yaml()/parse_llm_payload() + render_tool_catalogue() with inline metadata sanitisation (#28, #100, #363, #366)
├── proposals.py       Shared proposer primitives: ModelInfo/ProposalProvenance (#364), StructuredLLMFn + run_with_repair() (#363), PromptBudget + apply_budget() (#367); banned from executor.py
├── routing.py         Routing-accuracy evaluation: RoutingCase + evaluate_routing() + mine_routing_cases() (#374); banned from executor.py
├── contracts.py       ToolSafetyContract + SideEffectLevel/StabilityLevel/DeterminismLevel enums + merge_safety() + side_effect_exceeds() (#356) + evaluate_predicate() — determinism + operational safety vocabulary (#19, #125, #293, #9, #8)
├── approvals.py       ApprovalCallback Protocol + ApprovalContext/ApprovalDecision/ApprovalRecord + coerce_approval_callback — execution-time ToolSafetyContract enforcement seam (#356); mirrors decisions.py
├── decorators.py      @tool decorator for zero-boilerplate tool definition
├── tools.py           Tool class: named callable with Pydantic I/O schemas + schema_hash + safety contract (#19) + metadata provenance (#358/#359/#371) + dry_run_fn/run_dry (#357); Tool.from_flow() wraps a Flow as a Tool (#24) with derived safety (#125); StreamingTool + ToolChunk for streamed output via run_streaming (#320)
├── flow/              Stable `chainweaver.flow` surface, split by model concern (#396)
│   ├── __init__.py    Re-exports the historical surface and preserves module-qualified references
│   ├── definitions.py Flow + FlowStatus + ConditionalEdge + ContextCollisionPolicy
│   ├── steps.py       FlowStep (+ output_mapping #386) + RetryPolicy
│   ├── dag.py         DAGFlowStep + DAGFlow (+ dynamic_params #316) + validate_dag_topology
│   ├── governance.py  FlowLifecycle + FlowGovernance
│   ├── drift.py       DriftInfo
│   └── refs.py        Schema/exception class-ref resolution + opt-in module allowlist policy (#345)
├── step_index.py      Named sentinels for flow input/output validation records (#339)
├── _pointer.py        Dependency-free RFC-6901 JSON pointer resolver shared by executor input_mapping (#387) and contrib json_pluck
├── registry.py        FlowRegistry: multi-version catalogue with status filtering (store-backed) + copy-on-write update_flow_state (#335) + directory hot-reload (load_from_directory/reload_from_directory/watch → ReloadReport/WatchHandle, flow-definitions only, #322)
├── storage.py         RegistryStore protocol + InMemoryStore + FileStore (#16)
├── analyzer.py        ChainAnalyzer: offline schema-compatibility analysis (#77)
├── attest.py          attest_flow() + AttestationReport: observed-determinism evidence (#154)
├── decisions.py       DecisionCallback Protocol + DecisionContext + coerce_decision_callback (#102)
├── executor.py        FlowExecutor: sequential/DAG runner + drift detection + stream_flow + opt-in async DAG-level concurrency (max_step_concurrency, #344) + opt-in execution-time safety enforcement (approval_callback/strict_safety/max_side_effect_level, #356) + dry-run mode (execute_flow(dry_run=...), #357) (main entry point)
├── _execution/        Internal, no-I/O execution collaborators shared by both lanes (#330, #331); banned from importing LLM/network/random — see invariants
│   ├── __init__.py    Re-exports merge_step_outputs + apply_output_mapping
│   └── context.py     merge_step_outputs + apply_output_mapping: single context-merge honouring on_context_collision (#337) and output_mapping (#386)
├── middleware.py      FlowExecutorMiddleware Protocol + lifecycle context models + BaseMiddleware (#131); optional on_step_chunk hook + StepChunkContext for streaming steps (#320)
├── events.py          FlowEvent streamable lifecycle payload yielded by FlowExecutor.stream_flow / stream_flow_async (#134, #389) — incl. kind="step_chunk" carrying a ToolChunk for streaming tools (#320)
├── cache.py           StepCache Protocol + InMemoryStepCache + FileStepCache + StepCacheKey (#127)
├── checkpoint.py      Checkpointer Protocol + ExecutionSnapshot + InMemoryCheckpointer + FileCheckpointer (#128)
├── integrations/      Optional third-party adapters (each guards its extra import)
│   ├── __init__.py    Package marker; documents available integrations
│   ├── opentelemetry.py  OTelTraceExporter middleware + export_result_to_otel (#126); requires chainweaver[otel]
│   ├── langchain.py   from_/to_langchain_tool + from_langchain_toolkit (#82); requires chainweaver[langchain]
│   ├── llamaindex.py  from_/to_llamaindex_tool (#82); requires chainweaver[llamaindex]
│   ├── weaver_spec.py    Re-exports weaver-contracts types + flow_to_selectable_item + routing resolvers; needs [weaver-stack] extra (#91, #107, #233)
│   ├── contextweaver.py  RoutingDecisionAdapter (DecisionCallback impl) + ContextweaverClient Protocol (#106)
│   ├── agent_kernel.py   KernelBackedExecutor + KernelProtocol + InMemoryKernel (#89)
│   ├── _llm_common.py    Provider-adapter base: ProviderAdapter + LLMFnOptions + LLMUsage — retry/timeout/spend-ceiling/usage around proposer LLM calls (#368)
│   ├── llm_anthropic.py  anthropic_llm_fn() → Anthropic-backed LLMFn/StructuredLLMFn (#368); requires chainweaver[llm-anthropic]
│   └── llm_openai.py     openai_llm_fn() → OpenAI / OpenAI-compatible LLMFn/StructuredLLMFn (#368); requires chainweaver[llm-openai]
├── mcp/               MCP integration (issues #70, #72, #150); requires chainweaver[mcp]
│   ├── __init__.py    Public surface: MCPToolAdapter, FlowServer, jsonschema_to_pydantic
│   ├── _schema.py     JSON Schema ↔ Pydantic bridge
│   ├── adapter.py     MCPToolAdapter: wrap MCP server tools as ChainWeaver Tools (#70, #150) + untrusted-metadata trust controls — annotation_trust→ToolSafetyContract (#371), MetadataPolicy name/description sanitisation (#359), schema-hash pinning + on_drift (#358), build_pin_file/load_pins
│   ├── server.py      FlowServer: safely expose governed flows as MCP tools via FastMCP (#72, #259, #294) + trust-boundary hooks: force_expose governance (#360), authenticator/rate_limiter (#362), authorizer callback (#443), error_detail redaction (#347), MCPServerProfile + readiness_report (#446)
│   └── security.py    FlowServer trust-boundary primitives: CallerIdentity/MCPRequestContext + Authenticator (#362), AuthorizationCallback/AuthorizationDecision/AuthorizationContext + coerce_authorizer (#443), RateLimiter + FixedWindowRateLimiter (#362), AuditEvent, render_error_detail (#347), MCPServerProfile/ReadinessFinding/evaluate_readiness (#446)
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
│   ├── replay.py      record_then_replay decorator + FixtureStaleError (#153); hooks at Tool._call_fn — never inside executor.py
│   └── protocol_suites.py  Reusable pytest conformance suites (#397): RegistryStoreConformance / StepCacheConformance / CheckpointerConformance base classes a third-party backend subclasses with a fixture; imports pytest, so it stays a submodule never imported by testing/__init__.py
├── plugins.py         discover_tools() + discover_flows() over importlib.metadata entry points (#130)
├── exceptions.py      Typed exception hierarchy (all inherit ChainWeaverError)
├── log_utils.py       Structured per-step logging utilities
├── cost.py            CostProfile + CostReport for cost-avoided estimation; PriceSnap + PROVIDER_PRICES maintained price table + lookup_price + CostProfile.from_provider (#156)
├── observation.py     TraceRecorder + ObservedTrace for ad-hoc capture
├── observer.py        ChainObserver: record runtime tool calls, mine repeated sequences, suggest FlowSuggestion proposals (#78); banned from executor.py
├── traces.py          Coding-agent trace pipeline: AgentTraceEvent + load_agent_trace (#254), CandidateScore + score_candidate (#256), DraftFlow + draft_flow_from_candidate (#257), render_candidate_report (#266), BacktestReport + backtest_flow (#267); offline, banned from executor.py
├── opencode.py        OpenCode adapter: normalize_opencode_event(s) plugin→AgentTraceEvent (#278/#276), safe_macro_tool_name + detect_tool_name_collisions (#280), build_flow_mcp_entry + add/remove_flow_server_from_config (#279), render_observe_plugin (#276), OpenCodeAdapterError (CW-E048); offline, banned from executor.py
├── lessons.py         trace_to_lesson_candidate() + LessonCandidate/LessonEvidenceStep/LessonReview: normalise an ExecutionResult into a reviewable, workflow-scoped lesson candidate for lessonweaver (#210); no hard dep on lessonweaver; banned from executor.py
├── service.py         ChainWeaverService: continuous analyze→observe→propose→govern loop tying analyzer + observer + a proposal gate (#101); banned from executor.py
├── viz.py             ASCII + Mermaid + DOT renderers for Flow/ExecutionResult
├── serialization.py   YAML + JSON encode/decode for Flow and DAGFlow
├── schemas.py         JSON Schema export for .flow.json / .flow.yaml files (#135, #139)
├── cli/               typer-based CLI command package (#333): inspect/viz (ascii/dot/mermaid + --result overlay, #392), explain (deterministic LLM-free review render, #420), init (project scaffolder, #441), validate/check/dump-schema, run/serve, profile, diff, attest, suggest, record, flows (promote/ignore/list), traces (mine/draft-flows/backtest), opencode group (`opencode capture` plugin event→trace JSONL #276; `opencode setup`/`revert` reversible observe-plugin + FlowServer exposure with dry-run/backups #277/#279/#280), doctor group (`doctor flow` --check-drift / --preflight / --profile first-run #442; `doctor vscode|claude|opencode` read-only coding-agent workspace inspectors #264/#270/#275), fuzz, service
│   ├── __init__.py    Wires the command submodules, defines the ``main`` entry point, re-exports the stable surface (``app``, ``set_default_registry`` …)
│   ├── _shared.py     Typer ``app`` / sub-apps, registry state, shared flow/result loading, error→exit-code handling, ``--format json`` envelope, and flow-resolution/discovery (#381, #440)
│   └── <command>.py   One module per command group; each registers on the shared ``app`` at import time
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
playground/                  Streamlit zero-install onboarding playground (#81); outside the package, not lint/type-gated
├── app.py                   Thin Streamlit UI shell
├── core.py                  Streamlit-free flow builders + headless runner + Mermaid + share codec (tests/test_playground.py)
└── requirements.txt         streamlit + streamlit-mermaid + chainweaver
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
scripts/                     Maintenance scripts run from CI, not shipped in the package — release.py prepares/verifies releases (#304–#309); refresh_prices.py keeps cost.py PROVIDER_PRICES fresh (#156)
benchmarks/                  Standalone benchmark scripts (not coverage-gated): bench_naive_vs_compiled.py (#29), bench_correctness.py (#103), report.py (#207); results/ holds generated latest.{json,md}
.github/workflows/           CI/docs/bench plus PR-first release, publish, post-publish distribution verification, and update-prices workflows
```

### Key entry points

- `FlowExecutor(..., decision_callback=...)` → wire a `DecisionCallback` for guided decision points (#102); steps with `decision_candidates` set call the callback to pick which tool to run.  Either a class with `decide(ctx)` or a bare callable is accepted (coerced via `coerce_decision_callback`).  Each resolution is recorded on `StepRecord.decision` (`DecisionRecord`, #369).  Pass `decision_policy=DecisionPolicy(timeout_s=..., max_decisions_per_flow=..., on_timeout=...)` to bound callback latency and per-flow decision count (#370).
- `KernelBackedExecutor(..., kernel=...)` from `chainweaver.integrations.agent_kernel` (#89) → optional `FlowExecutor` subclass that delegates `DAGFlowStep` instances with `step_type="capability"` through a `KernelProtocol`.  The base `FlowExecutor` rejects capability steps; only this subclass dispatches them.
- `flow_to_selectable_item(flow, *, capability_id=None, tags=())` from `chainweaver.integrations.weaver_spec` (#107) → project a `Flow` or `DAGFlow` to a weaver-spec `SelectableItem` for contextweaver catalog ingestion.
- `RoutingDecisionAdapter(client=...)` from `chainweaver.integrations.contextweaver` (#106) → `DecisionCallback` impl that asks a `ContextweaverClient` for a `RoutingDecision` and returns the selected capability id.
- `FlowExecutor.execute_flow(flow_name, initial_input, *, version=None, force=False, deadline=None, cancel_token=None)` → `ExecutionResult`. `version` (#201) targets an exact registered flow version (default: latest); the version that ran is recorded on `ExecutionResult.flow_version`. `deadline` (wall-clock `time.time()` seconds) and `cancel_token` (`CancellationToken`, #142) cooperatively cancel **between** steps / DAG levels — never inside a tool — raising `FlowCancelledError` with the partial result.
- `FlowExecutor.execute_flow_async(flow_name, initial_input, *, version=None, force=False, deadline=None, cancel_token=None)` → `Awaitable[ExecutionResult]` (#80); async-native counterpart of `execute_flow`. Dispatches each step through `Tool.run_async` so async-fn tools (e.g. those produced by `chainweaver.mcp.MCPToolAdapter`) execute on the calling loop and sync-fn tools are offloaded to `asyncio.to_thread`. Supports linear and DAG flows with retries, middleware, and on_error policies; honours `version` / `deadline` / `cancel_token`; executes composed `flow_name` sub-flow steps, consults the step cache, and writes checkpoints — resume via `resume_flow_async(trace_id)` (#388). Still rejects conditional branching (#9) and `decision_candidates` (#102).
- `FlowExecutor.stream_flow(flow_name, initial_input, *, force=False, deadline=None, cancel_token=None)` → `Iterator[FlowEvent]` (#134); yields `kind="flow_start"` → (`step_start` → `step_end`)* → `flow_end` events as the flow runs on a worker thread. A `deadline` / `cancel_token` is checked at step boundaries on the worker (#389); abandoning the iterator still lets the in-flight step run to completion.
- `FlowExecutor.stream_flow_async(flow_name, initial_input, *, force=False, deadline=None, cancel_token=None)` → `AsyncIterator[FlowEvent]` (#389); async-native counterpart driving `execute_flow_async` on the calling loop (no worker thread). Same event order; `cancel_token` / `deadline` end the stream promptly at the next step boundary by raising `FlowCancelledError` (partial on `.result`), and abandoning the iterator cancels the backing task. Async-lane feature support applies (#388).
- `FlowExecutor(..., step_cache=...)` → memoize step outputs across runs (#127); keyed by `(tool_name, schema_hash, input_value_hash)`. Cache hits skip `Tool.fn` entirely (including retries and timeout) and surface as `StepRecord.cached=True`. Tools mark themselves `cacheable=False` to always run (side-effects, external state). `replay_flow` always bypasses the cache.
- `FlowExecutor(..., checkpointer=..., delete_on_success=True)` → crash-resume (#128); writes an `ExecutionSnapshot` after every successful linear step or DAG level. `FlowExecutor.resume_flow(trace_id)` (or `resume_flow_async(trace_id)` for runs started on the async lane, #388) validates the snapshot's flow version and tool `schema_hash` values against the current registry — drift raises `CheckpointDriftError` — then continues execution with the original `trace_id`. Snapshots are deleted on terminal success when `delete_on_success=True` (the default); preserved on failure for operator-driven retry.
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

These invariants are mechanically enforced by
`tests/test_executor_import_contract.py` over `executor.py` and
`chainweaver/_execution/`, including direct imports, transitive in-repo reach,
and obvious literal dynamic imports; see
[invariants.md](docs/agent-context/invariants.md).

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
12. One primary issue per PR (bundle only genuinely coupled work, and say why); declare closing issues in the PR template; all tests must pass before merge. See [workflows.md § PR conventions](docs/agent-context/workflows.md#pr-conventions).

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
| `status` | `FlowStatus` | `ACTIVE` | Operational execution gate (`active` / `needs_review` / `disabled`). Non-`ACTIVE` flows are refused by `execute_flow` unless `force=True`. |
| `trigger_conditions` | `dict[str, Any] \| None` | `None` | Free-form metadata for higher-level orchestrators; ChainWeaver itself does not evaluate these. |
| `input_schema_ref` | `str \| None` | `None` | `"module:qualname"` ref to a Pydantic model validating `initial_input` before the first step runs. Resolved lazily by the `input_schema` property. |
| `output_schema_ref` | `str \| None` | `None` | `"module:qualname"` ref to a Pydantic model validating the final merged context. Resolved lazily by the `output_schema` property. |
| `context_schema_ref` | `str \| None` | `None` | `"module:qualname"` ref for the accumulated execution context (#152). Resolved lazily by the `context_schema` property; validated at flow end. |
| `tool_schema_hashes` | `dict[str, str] \| None` | `None` | Snapshot of per-tool schema fingerprints (#50). Drives drift detection and `doctor --check-drift`. |
| `capability_id` | `str \| None` | `None` | Optional Weaver Stack capability identifier (#90); when set, the flow is routable as a `SelectableItem` via `flow_to_selectable_item`. See [docs/agent-context/flow-as-capability.md](docs/agent-context/flow-as-capability.md). |
| `governance` | `FlowGovernance` | active defaults | Review lifecycle, owner, replacement-tool list, savings estimates, and review notes (#259, #268). Separate from `FlowStatus`. |
| `safety` | `ToolSafetyContract \| None` | `None` | Explicit flow-level side-effect, retry, dry-run, idempotency, and approval metadata (#293). `None` means unknown, not safe. |
| `on_context_collision` | `Literal["overwrite", "warn", "error"]` | `"warn"` | Policy when a step output overwrites an existing context key (#337). `"overwrite"` = silent last-write-wins; `"warn"` = log at WARNING then overwrite; `"error"` = abort with `ContextKeyCollisionError`. Applied by the single shared merge helper (`chainweaver._execution.merge_step_outputs`) on both linear and DAG, sync and async. DAG *sibling* collisions within one level remain an unconditional error regardless. |
| `dynamic_params` | `tuple[str, ...]` | `()` | Declarative names of params injected at execute-time via `execute_flow(..., dynamic_params={...})` rather than `initial_input` (#316). Merged into the running context *after* `input_schema` validation, so they reach every step's `input_mapping` and the final output yet stay out of the LLM-visible `input_schema` — for per-request secrets a model must never see. Metadata only; the executor accepts any `dynamic_params` keys whether or not they are declared here. |

### Context-collision semantics (#337)

The accumulated context is the data plane of every flow. A step output that
overwrites an existing key (including an `initial_input` key) is governed by
`Flow.on_context_collision` and enforced in exactly one place —
`chainweaver._execution.merge_step_outputs` — for both flow kinds and both
lanes. `compile_flow` additionally emits a `context_collision` warning for
statically detectable overwrites (suppressed under `"overwrite"`). See
[docs/data-integrity.md](docs/data-integrity.md#context-key-collisions-337).

### Concurrency contract (#336)

A single `FlowExecutor` instance supports **concurrent** `execute_flow` /
`execute_flow_async` / `stream_flow` calls: run-scoped state (the stream event
collector, `active_flow_version`, replay/resume markers, injected
`dynamic_params`) lives in a per-instance `contextvars.ContextVar` and each
entry point binds a fresh per-scope copy, so the isolation holds across both OS
threads **and** concurrent `execute_flow_async` tasks sharing one event-loop
thread (a `threading.local` would not isolate the latter). The bundled
`InMemoryStepCache` / `InMemoryCheckpointer` are internally locked. The one
rule: **mutating operations (`register_tool`, `add_middleware`,
`accept_drift`) must not run concurrently with executions** — do them at setup.

### Async lane support matrix (#332)

`execute_flow_async` raises `AsyncLaneUnsupportedError` (before any step runs)
for features it does not yet honour, rather than diverging silently:

| Feature | `execute_flow` (sync) | `execute_flow_async` |
|---------|:---------------------:|:--------------------:|
| Linear flows | ✅ | ✅ |
| DAG flows (no branching) | ✅ | ✅ |
| Opt-in DAG-level concurrency (#344) | sequential | ✅ (`max_step_concurrency`) |
| Conditional branches / `default_next` (#9) | ✅ | ❌ rejected |
| `decision_candidates` (#102) | ✅ | ❌ rejected |
| Composed sub-flow (`flow_name`, #75) | ✅ | ✅ (#388) |
| Step cache / checkpoint resume | ✅ | ✅ (#388; resume via `resume_flow_async`) |

### State transitions (#335)

`accept_drift` and `set_flow_status` never mutate a registry-held `Flow` in
place — they go through `FlowRegistry.update_flow_state`, which performs a
`model_copy(update=...)`, persists the new object, and returns it. Callers
needing the new state must re-fetch via `get_flow`.

**Read-only properties (not fields):** `input_schema`, `output_schema`, and
`context_schema` resolve their `*_schema_ref` counterparts to a
`type[BaseModel] | None`. `determinism_level` is a computed
`DeterminismLevel` (#8): linear `Flow` → `FULL` (or `NONE` if
`deterministic=False`); `DAGFlow` with any conditional `branches` → `PARTIAL`.
Any step (linear or DAG) with non-empty `decision_candidates` (#102) also
downgrades the flow to `PARTIAL` (#369), since a registered callback can pick
a different tool per run.

### `DAGFlowStep` conditional branching (#9)

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `branches` | `list[ConditionalEdge]` | `[]` | Outgoing guards.  After this step runs, the first `ConditionalEdge` whose `predicate` evaluates truthy against the merged context picks the active downstream path; non-selected immediate dependents are recorded as `StepRecord(skipped=True)`.  Empty list (default) → unconditional fan-out, every dependent runs. |
| `default_next` | `str \| None` | `None` | Fallback `target_step_id` when no `ConditionalEdge` matches.  Only meaningful alongside non-empty `branches`. |

Predicates are evaluated by `chainweaver.contracts.evaluate_predicate`, which parses the string with `ast` and walks the tree by hand — `eval()` is **never** called.  Predicate syntax errors and unsupported AST nodes raise `PredicateSyntaxError` and abort the flow with a synthetic failed `StepRecord`.

Branching is only supported on `step_type="tool"` steps.  Capability steps (`step_type="capability"`) are dispatched through `_execute_capability_step` before `_select_branch` runs, so `branches` / `default_next` are rejected on them at construction (a `DAGFlowStep` validator) rather than silently ignored.

### `FlowStep.tool_name` / `FlowStep.flow_name` (issue #75)

A step runs **either** a tool or a registered sub-flow — exactly one of
`tool_name` / `flow_name` must be set (a model validator enforces this; both
or neither raises `ValidationError`). When `flow_name` is set the executor
recursively runs that flow with the step's resolved inputs, merges its final
output into the parent context, and attaches the sub-flow's `ExecutionResult`
to `StepRecord.sub_result` (nested trace). The composition graph is validated
before execution — cycles, nesting beyond `FlowExecutor(max_composition_depth=...)`
(default 10), and references to unregistered flows raise `FlowCompositionError`.
Composition is sync-only; `execute_flow_async` rejects `flow_name` steps.
`FlowStep.display_name` returns `tool_name` or `flow_name` for logs/records.
The parent's `deadline` / `cancel_token` are forwarded into the recursive
sub-flow run, so cancellation and the wall-clock budget are honoured between a
sub-flow's own steps (not just at the parent boundary). `ExecutionResult.cost_report.steps_executed`
counts the tool invocations a composed step actually drove (recursively), so
`llm_calls_avoided` is not under-counted for composed flows.

### `FlowStep.input_mapping`

| Value type | Behavior |
|------------|----------|
| `str` (plain key) | Looked up as a top-level key in the accumulated execution context. |
| `str` starting with `/` | An RFC-6901 JSON pointer (#387) resolved against the nested context — e.g. `"/user/address/city"` or `"/items/0/id"`. A miss raises `InputMappingError` naming the pointer. A top-level key that literally starts with `/` is addressed with the `~1` escape (the key `"/raw"` is the pointer `"/~1raw"`). |
| Non-string (`int`, `float`, `bool`, …) | Used as a literal constant. |
| Empty `{}` (default) | The tool receives the full current context. |

Pointer resolution is shared with the contrib `json_pluck` tool via the
dependency-free `chainweaver._pointer` module, so core never imports the
optional `contrib` extra.

### `FlowStep.output_mapping` (issue #386)

Optional `dict[str, str] | None` (default `None`), shaped `{context_key:
output_key}`. Applied to a tool's *validated* outputs before they merge into
the context: only the listed output keys merge, each renamed to its context
key; unlisted keys are pruned. `None` merges every output key verbatim (the
historical behaviour). A mapped `output_key` the tool did not produce raises
`OutputMappingError` (`CW-E041`). The raw outputs are still recorded on
`StepRecord.outputs` — the mapping affects only the context merge. `compile_flow`
understands the remapped keys and statically flags an unknown `output_key`.

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
| `trace_schema_version` | `str` | Library-stamped version of the trace *shape* (#393), currently `"1.1"`. Lets long-lived trace consumers detect shape evolution; distinct from `flow_version`. See [docs/versioning-policy.md](docs/versioning-policy.md#artifact-schema-versions). |
| `flow_name` | `str` | Name of the executed flow. |
| `success` | `bool` | `True` when all steps completed without error. |
| `final_output` | `dict \| None` | Merged execution context, or `None` on failure. |
| `execution_log` | `list[StepRecord]` | Ordered per-step records. |
| `trace_id` | `str` | UUID4 hex string assigned at the start of execution; correlates with logs. |
| `started_at` | `datetime` | UTC timestamp when execution began. |
| `ended_at` | `datetime` | UTC timestamp when execution finished. |
| `total_duration_ms` | `float` | Wall-clock duration in ms (via `time.perf_counter`). |
| `dry_run` | `bool` | `True` when produced by `execute_flow(dry_run=True)` (#357); a rehearsal trace, never a real run. |

### `StepRecord` (Pydantic `BaseModel`)

| Field | Type | Meaning |
|-------|------|---------|
| `step_index` | `int` | Zero-based position (`FLOW_INPUT_STEP_INDEX` = flow-input validation, `flow_output_step_index(flow)` = flow-output/context validation). |
| `tool_name` | `str` | Configured primary tool for the step (or flow name for validation records). Remains the primary name when a fallback runs so step identity is stable across traces. |
| `inputs` | `dict` | Validated inputs passed to the tool. |
| `outputs` | `dict \| None` | Validated outputs, or `None` on failure. |
| `error_type` | `str \| None` | Exception class name (e.g. `"FlowExecutionError"`) when the step failed; `None` on success. |
| `error_code` | `str \| None` | Stable diagnostic code (#390, e.g. `"CW-E006"`) auto-derived from `error_type` for typed `ChainWeaverError`s; `None` on success or a foreign exception. |
| `error_message` | `str \| None` | Human-readable error text when the step failed; `None` on success. |
| `success` | `bool` | `True` when the step completed without error. |
| `started_at` | `datetime` | UTC timestamp when the step began. |
| `ended_at` | `datetime` | UTC timestamp when the step finished. |
| `duration_ms` | `float` | Wall-clock duration in ms (via `time.perf_counter`). |
| `fallback_used` | `bool` | `True` when `on_error="fallback:<tool_name>"` attempted recovery, including missing or failing fallbacks. |
| `fallback_tool_name` | `str \| None` | The configured fallback target when `fallback_used=True`; `None` otherwise. |
| `approval` | `ApprovalRecord \| None` | The decision for a step gated by an execution-time approval callback (#356); `None` when no approval was required. |

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
| Add a new Flow field | `flow/definitions.py` | Serialization tests if `model_dump()` changes |
| Add a new DAGFlow / DAGFlowStep field | `flow/dag.py` | Update `validate_dag_topology` if needed; update tests |
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

CI runs lint + format + mypy in a dedicated `lint` job on Python 3.10 /
`ubuntu-latest` (issue #458); that job also runs the banned-vocabulary check
(`scripts/check_vocabulary.py`, issue #466) and lints the workflows with
`actionlint`. Tests run across
`{ubuntu-latest, windows-latest, macos-latest} × {3.10, 3.11,
3.12, 3.13, 3.14}` (15 jobs in total). A `floor-deps` job additionally
installs the minimum declared dependency versions
(`uv pip install --resolution lowest-direct`) and runs the full suite on
Python 3.10, and a weekly scheduled `latest-deps` job runs the suite
against the newest (incl. pre-release) dependencies on Python 3.14
(issue #236). A separate `bench.yml` workflow runs the naive-vs-compiled
benchmark on `ubuntu-22.04`; executor-sensitive changes alert when a compiled
metric exceeds 200 % of the `gh-pages` baseline, while release/docs changes
cannot emit performance alerts (see [benchmarks/README.md](benchmarks/README.md)).

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
| [SPEC_COMPAT.md](docs/SPEC_COMPAT.md) | Declared `weaver-contracts>=0.6,<1.0` compatibility (#91, #233); conformance test + CI gates | Changing the supported contract range or weaver_spec adapters |
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
