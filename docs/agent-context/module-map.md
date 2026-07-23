# Module Map

> **Non-authoritative factual reference.** This file inventories what exists
> and where, so a task can find the right module without loading the whole
> package. It records facts (modules, exports, issue history), **not policy**:
> architectural rules live in [AGENTS.md](/AGENTS.md) (root contract),
> the path-scoped `AGENTS.md` files it indexes, and
> [architecture.md](architecture.md) (intent and boundaries). If this file
> disagrees with any of those, they win — fix the drift here.
>
> Freshness is mechanically checked: `tests/test_agent_instructions.py`
> asserts every top-level module/package in `chainweaver/` has a row here,
> every module named here exists on disk, and the "banned from executor.py"
> annotations match the enforced list in
> `tests/test_executor_import_contract.py`.

---

## Package inventory

```text
chainweaver/
├── __init__.py        Public API surface; all exports in __all__
├── builder.py         FlowBuilder: fluent API for constructing Flow objects
├── compat.py          schema_fingerprint() + check_flow_compatibility() + CompatibilityIssue
├── compiler.py        compile_flow(): static schema flow validation (CompilationResult)
├── compiler_llm.py    Offline build-time LLM flow compiler: LLMProposal (+ provenance) + llm_propose_flows() + write_proposals()/read_provenance() + flow_proposal_schema() (#28, #363, #364); banned from executor.py
├── optimizer.py       Offline build-time tool-description optimizer: OptimizationStrategy + ToolDescriptionProposal + optimize_tool_descriptions()/optimize_new_tool_description() + description_proposal_schema() + routing-accuracy annotation (#100, #374); banned from executor.py
├── _offline_llm.py    Private shared internals for the offline LLM proposers: LLMFn type + parse_llm_yaml()/parse_llm_payload() + render_tool_catalogue() with inline metadata sanitisation (#28, #100, #363, #366); banned from executor.py
├── proposals.py       Shared proposer primitives: ModelInfo/ProposalProvenance (#364), StructuredLLMFn + run_with_repair() (#363), PromptBudget + apply_budget() (#367); banned from executor.py
├── routing.py         Routing-accuracy evaluation: RoutingCase + evaluate_routing() + mine_routing_cases() (#374); banned from executor.py
├── contracts.py       ToolSafetyContract + SideEffectLevel/StabilityLevel/DeterminismLevel enums + merge_safety() + side_effect_exceeds() (#356) + evaluate_predicate() — determinism + operational safety vocabulary (#19, #125, #293, #9, #8)
├── approvals.py       ApprovalCallback Protocol + ApprovalContext/ApprovalDecision/ApprovalRecord + coerce_approval_callback — execution-time ToolSafetyContract enforcement seam (#356); mirrors decisions.py
├── decorators.py      @tool decorator for zero-boilerplate tool definition
├── tools.py           Tool class: named callable with Pydantic I/O schemas + schema_hash + safety contract (#19) + metadata provenance (#358/#359/#371) + dry_run_fn/run_dry (#357); Tool.from_flow() wraps a Flow as a Tool (#24) with derived safety (#125); StreamingTool + ToolChunk for streamed output via run_streaming (#320)
├── flow/              Stable `chainweaver.flow` surface, split by model concern (#396) — see chainweaver/flow/AGENTS.md
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
├── cancellation.py    CancellationToken: cooperative flow cancellation between steps / DAG levels, paired with wall-clock deadlines (#142)
├── decisions.py       DecisionCallback Protocol + DecisionContext + coerce_decision_callback (#102)
├── guardrails.py      GuardrailCallback Protocol + GuardrailContext (stage input/output) + coerce_guardrail_callback — input-stage content-safety seam wired in executor.py (#317); mirrors approvals.py
├── executor.py        FlowExecutor: sequential/DAG runner + drift detection + stream_flow + opt-in async DAG-level concurrency (max_step_concurrency, #344) + opt-in execution-time safety enforcement (approval_callback/strict_safety/max_side_effect_level, #356) + dry-run mode (execute_flow(dry_run=...), #357) + opt-in input-stage content-safety guardrails (guardrail_callback, #317) (main entry point)
├── _execution/        Internal, no-I/O execution collaborators shared by both lanes (#330, #331); same determinism invariants as executor.py, covered by the import contract — see chainweaver/_execution/AGENTS.md
│   ├── __init__.py    Re-exports merge_step_outputs + apply_output_mapping
│   └── context.py     merge_step_outputs + apply_output_mapping: single context-merge honouring on_context_collision (#337) and output_mapping (#386)
├── middleware.py      FlowExecutorMiddleware Protocol + lifecycle context models + BaseMiddleware (#131); optional on_step_chunk hook + StepChunkContext for streaming steps (#320)
├── events.py          FlowEvent streamable lifecycle payload yielded by FlowExecutor.stream_flow / stream_flow_async (#134, #389) — incl. kind="step_chunk" carrying a ToolChunk for streaming tools (#320)
├── cache.py           StepCache Protocol + InMemoryStepCache + FileStepCache + StepCacheKey (#127)
├── checkpoint.py      Checkpointer Protocol + ExecutionSnapshot + InMemoryCheckpointer + FileCheckpointer (#128)
├── integrations/      Optional third-party adapters (each guards its extra import) — see chainweaver/integrations/AGENTS.md
│   ├── __init__.py    Package marker; documents available integrations
│   ├── opentelemetry.py  OTelTraceExporter middleware + export_result_to_otel (#126); OTelMetricsMiddleware + export_result_to_otel_metrics — flow/step counters, duration histograms, cache-hit + retry counters (#435); requires chainweaver[otel]
│   ├── langchain.py   from_/to_langchain_tool + from_langchain_toolkit (#82); requires chainweaver[langchain]
│   ├── llamaindex.py  from_/to_llamaindex_tool (#82); requires chainweaver[llamaindex]
│   ├── weaver_spec.py    Re-exports weaver-contracts types + flow_to_selectable_item + routing resolvers; needs [weaver-stack] extra (#91, #107, #233)
│   ├── contextweaver.py  RoutingDecisionAdapter (DecisionCallback impl) + ContextweaverClient Protocol (#106)
│   ├── agent_kernel.py   KernelBackedExecutor + KernelProtocol + InMemoryKernel (#89)
│   ├── _llm_common.py    Provider-adapter base: ProviderAdapter + LLMFnOptions + LLMUsage — retry/timeout/spend-ceiling/usage around proposer LLM calls (#368)
│   ├── llm_anthropic.py  anthropic_llm_fn() → Anthropic-backed LLMFn/StructuredLLMFn (#368); requires chainweaver[llm-anthropic]
│   └── llm_openai.py     openai_llm_fn() → OpenAI / OpenAI-compatible LLMFn/StructuredLLMFn (#368); requires chainweaver[llm-openai]
├── mcp/               MCP integration (issues #70, #72, #150); requires chainweaver[mcp] — see chainweaver/mcp/AGENTS.md
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
├── testing/           Public test harness for flows (#132, #153) — see chainweaver/testing/AGENTS.md
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
├── fuzz.py            Property-based fuzzing harness for flows (#220, #221, #222): input-corpus generation, explicit property checks (e.g. gracefully_handles_input), replayable violation traces; drives the `chainweaver fuzz` CLI and fuzz.yml workflow (#340)
├── trace_store.py     TraceStore protocol + InMemoryTraceStore + FileTraceStore (JSONL) + redact_execution_result — redacted execution-trace persistence with retention (#292)
├── observation.py     TraceRecorder + ObservedTrace for ad-hoc capture
├── observer.py        ChainObserver: record runtime tool calls, mine repeated sequences, suggest FlowSuggestion proposals (#78); banned from executor.py
├── traces.py          Coding-agent trace pipeline: AgentTraceEvent + load_agent_trace (#254), CandidateScore + score_candidate (#256), DraftFlow + draft_flow_from_candidate (#257), render_candidate_report (#266), BacktestReport + backtest_flow (#267); offline, banned from executor.py
├── opencode.py        OpenCode adapter: normalize_opencode_event(s) plugin→AgentTraceEvent (#278/#276), safe_macro_tool_name + detect_tool_name_collisions (#280), build_flow_mcp_entry + add/remove_flow_server_from_config (#279), render_observe_plugin (#276), OpenCodeAdapterError (CW-E048); offline, banned from executor.py
├── lessons.py         trace_to_lesson_candidate() + LessonCandidate/LessonEvidenceStep/LessonReview: normalise an ExecutionResult into a reviewable, workflow-scoped lesson candidate for lessonweaver (#210); no hard dep on lessonweaver; banned from executor.py
├── service.py         ChainWeaverService: continuous analyze→observe→propose→govern loop tying analyzer + observer + a proposal gate (#101); banned from executor.py
├── viz.py             ASCII + Mermaid + DOT renderers for Flow/ExecutionResult
├── serialization.py   YAML + JSON encode/decode for Flow and DAGFlow
├── schemas.py         JSON Schema export for .flow.json / .flow.yaml files (#135, #139)
├── _versions.py       Shared version-stamping policy for serialized artifacts: format_version (#394), trace_schema_version (#393), snapshot_version (#395)
├── cli/               typer-based CLI command package (#333) — see chainweaver/cli/AGENTS.md: inspect/viz (ascii/dot/mermaid + --result overlay, #392), explain (deterministic LLM-free review render, #420), init (project scaffolder, #441), validate/check/dump-schema, run/serve, profile, diff, attest, suggest, record, flows (promote/ignore/list), traces (mine/draft-flows/backtest), opencode group (`opencode capture` plugin event→trace JSONL #276; `opencode setup`/`revert` reversible observe-plugin + FlowServer exposure with dry-run/backups #277/#279/#280), doctor group (`doctor flow` --check-drift / --preflight / --profile first-run #442; `doctor vscode|claude|opencode` read-only coding-agent workspace inspectors #264/#270/#275), fuzz, service
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
scripts/                     Maintenance scripts run from CI, not shipped in the package — release.py prepares/verifies releases (#304–#309); refresh_prices.py keeps cost.py PROVIDER_PRICES fresh (#156); check_vocabulary.py banned-vocabulary lint (#466)
benchmarks/                  Standalone benchmark scripts (not coverage-gated): bench_naive_vs_compiled.py (#29), bench_correctness.py (#103), report.py (#207); results/ holds generated latest.{json,md}
.github/workflows/           CI/docs/bench plus PR-first release, publish, post-publish distribution verification, and update-prices workflows
```

> The "banned from executor.py" annotations above are the enforced list:
> `compiler_llm`, `optimizer`, `observer`, `traces`, `lessons`, `service`,
> `_offline_llm`, `proposals`, `routing`, `opencode` — matched one-to-one
> against `BANNED_INREPO` in `tests/test_executor_import_contract.py` by
> `tests/test_agent_instructions.py`.

---

## Key entry points

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

## Update triggers

Update this file when a module or package is added, removed, renamed, or its
primary responsibility changes (same PR — see
[AGENTS.md § Update policy](/AGENTS.md#10-update-policy)). The coverage guard
in `tests/test_agent_instructions.py` fails when a top-level module is missing
from this inventory or a listed module no longer exists.
