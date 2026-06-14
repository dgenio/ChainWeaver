# Changelog

All notable changes to ChainWeaver will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
(see [docs/versioning-policy.md](docs/versioning-policy.md)).

## [Unreleased]

### Added

- **Explicit schema versions for serialized artifacts** (#393, #394, #395): the
  three durable artifacts now carry a library-stamped version so consumers can
  detect shape evolution instead of sniffing fields. A shared
  `chainweaver._versions` module centralises the "accept same MAJOR, reject
  incompatible MAJOR, tolerate absent (legacy)" policy.
  - Serialized flow files (`.flow.yaml` / `.flow.json`) gain a `format_version`
    key; `flow_from_dict` rejects an incompatible MAJOR with
    `FlowSerializationError` and tolerates legacy files with no key (#394). The
    emitted `schemas/flow.schema.json` documents the key.
  - `ExecutionResult` gains `trace_schema_version`; legacy traces without it
    load unchanged (#393).
  - `ExecutionSnapshot` gains `snapshot_version`; `FlowExecutor.resume_flow`
    refuses an incompatible MAJOR with the new `CheckpointVersionError` rather
    than failing opaquely mid-recovery (#395).
- **Stable diagnostic codes on the exception hierarchy** (#390): every
  `ChainWeaverError` subclass carries an append-only `code` class attribute
  (e.g. `CW-E006`). The CLI prefixes it on error output
  (`chainweaver: [CW-E006] …`), failing `StepRecord`s expose it as the new
  `error_code` field (auto-derived from `error_type`), and every code is
  documented in `docs/reference/error-table.md`. A consistency test enforces
  uniqueness, completeness, and documentation. The code is intentionally not
  injected into `str(exc)`, preserving existing message contracts.

- **FlowExecutor execution-core hardening** (#330, #331, #332, #335, #336,
  #337, #344): a cluster of architecture/reliability improvements to the
  executor core.
  - A new internal `chainweaver._execution` package holds the transport-agnostic,
    no-I/O building blocks shared by both lanes (#330, #331), starting with
    `merge_step_outputs` — a single context-merge implementation used by linear
    and DAG, sync and async.
  - `Flow` / `DAGFlow` gain `on_context_collision` (`"overwrite"` / `"warn"`
    (default) / `"error"`) governing what happens when a step output overwrites
    an existing context key; `compile_flow` emits a `context_collision` warning
    for statically detectable overwrites; new `ContextKeyCollisionError` (#337).
  - Opt-in concurrent execution of independent DAG-level steps in the async lane
    via `FlowExecutor(max_step_concurrency=N)` (default `1` = sequential,
    bit-identical); results stay deterministic regardless of the setting (#344).
  - `FlowExecutor` now documents and supports a real concurrency contract:
    `stream_flow` registers its event collector as per-thread run-scoped
    middleware (no more shared-list mutation), and `InMemoryStepCache` /
    `InMemoryCheckpointer` are internally locked (#336).
  - `execute_flow_async` rejects unsupported constructs (branching,
    `decision_candidates`, composed sub-flows) up front with the new typed
    `AsyncLaneUnsupportedError`, listing every offending construct (#332).
  - `FlowRegistry.update_flow_state` performs copy-on-write state transitions;
    `accept_drift` / `set_flow_status` no longer mutate registry-shared `Flow`
    objects in place (#335).
  - The executor determinism invariants (no LLM / no network / no randomness)
    are now mechanically enforced by an AST import-contract test over
    `executor.py` and `_execution/` (#354).

- **Coding-agent macro-flow compilation loop** (#254, #256, #257, #260,
  #261, #262, #263, #266, #267, #312, #313, #314): a new `chainweaver.traces`
  module makes the *observe → mine → score → draft → backtest* loop
  first-class for coding agents. Adds a vendor-neutral coding-agent trace
  format (`AgentTraceEvent` / `load_agent_trace`), a deterministic candidate
  scorer (`CandidateScore` / `score_candidate`) covering support, success
  rate, schema stability, determinism, token savings, and a conservative
  safety classifier, draft-flow generation with mapping warnings
  (`draft_flow_from_candidate`), a human-friendly suggestion report
  (`render_candidate_report`), and an offline backtester (`backtest_flow`).
  A new `chainweaver traces mine / draft-flows / backtest` CLI group and a
  `chainweaver doctor --preflight` structural validator wire these into the
  CLI. Ships runnable `examples/coding_agent_macro_flows.py`, a
  `benchmarks/bench_coding_agent_macroflow.py` raw-loop-vs-macro-flow
  benchmark, a Daily Driver guide, macro-flow safety guidance, a
  ChainWeaver + contextweaver token-reduction architecture page, and
  `CLAIMS.md`. All analysis is offline and banned from `executor.py`.
- **PR-first release and distribution automation** (#304, #305, #306, #307,
  #308, #309): make `chainweaver.__version__` authoritative, add one-command
  release preparation and consistency checks, create and tag reviewed release
  PRs, verify PyPI/MCP/Action surfaces after publication, decouple pre-publish
  Action smoke tests from unreleased pins, and restrict 2x benchmark alerts to
  execution-sensitive changes.
- **Governed macro-flow lifecycle and safe MCP exposure** (#259, #268, #294):
  flows now carry serializable `FlowGovernance` metadata with explicit
  `observed → suggested → draft → reviewed → active` promotion states plus
  `ignored` and `archived`. `chainweaver record` writes draft candidates,
  persists ignored decisions, and reports lifecycle state; `chainweaver flows
  promote` / `flows ignore` update candidate files deterministically.
  `FlowServer` now exposes only active, read-only, approval-free flows with
  known safety by default, while explicit `flow_names` remains an operator
  override. MCP descriptions and `_meta` include replacement-tool, review,
  version, model-call, and token-saving metadata.
- **First-class operational safety metadata** (#293): `ToolSafetyContract`
  now covers destructive effects, derived read-only status, retry safety,
  dry-run support, approval requirements, and approval rationale. Flows can
  persist an explicit safety contract in JSON/YAML, tools report whether their
  safety was explicitly declared, and MCP annotations are derived from the
  effective contract.

### Deprecated

- `ToolSafetyContract.requires_review` is retained as a deprecated alias for
  `requires_approval`; legacy serialized contracts are migrated on load.

### Fixed

- **Source-attributed loading errors** (#343): JSON/YAML flow loaders now carry
  optional source context through `FlowSerializationError`, CLI/file-store
  callers pass flow paths into deserialization, and skipped plugin entry-point
  warnings include tracebacks for the underlying loader failure.

## [0.12.1] - 2026-06-08

### Fixed

- **MCP registry publication prerequisites** (#230): add the exact PyPI
  ownership marker for `io.github.dgenio/chainweaver`, shorten the manifest
  description to the official schema's 100-character limit, and declare the
  required flow file as a `filepath` while keeping `--tools` optional and
  repeatable.
- **Fresh `uvx` tool-module imports** (#230): installed console-script launches
  now import `--tools` modules from the client's current working directory, so
  `uvx --from "chainweaver[mcp]" chainweaver serve <flow_file> --tools
  <tools_module>` works outside an editable repository install.
- **Floor-dependency conformance** (#311): validate the installed
  `weaver-contracts` version against the declared `>=0.6,<1.0` range instead
  of requiring the compatibility document to name one exact installed release.

## [0.12.0] - 2026-06-08

### Added

- **Interactive web playground — zero-install onboarding** (#81): a new
  `playground/` directory with a Streamlit app (`playground/app.py`) that lets
  visitors pick a pre-loaded flow, edit its JSON input, run it, and inspect the
  step-by-step LLM-free trace and a Mermaid execution diagram — driven by the
  real `FlowExecutor`. Ships three example flows (arithmetic, a data flow,
  an MCP-style search), stateless `?share=<token>` links that round-trip a run
  through the URL, and deploy instructions for Streamlit Community Cloud. All
  flow-building/execution/diagram/share logic lives in a Streamlit-free
  `playground/core.py` covered by `tests/test_playground.py`; the app shell is a
  thin UI layer. Linked from the README.

- **`trace_to_lesson_candidate()` — runtime failures to reviewable lessons** (#210):
  a new `chainweaver.lessons` module exposing `trace_to_lesson_candidate()` plus
  `LessonCandidate`, `LessonEvidenceStep`, and the `LessonReview` outcome enum.
  It projects an `ExecutionResult` into a neutral, workflow-scoped lesson
  candidate the Weaver Stack's `lessonweaver` (or any reviewer) can promote into
  a skill instruction, eval, guardrail, or workflow change. ChainWeaver
  identifies *where* a deterministic workflow failed but never asserts the
  lesson outcome, and the candidate is a plain Pydantic model — **no hard
  dependency on `lessonweaver`**. New design note
  [`docs/lessons-from-traces.md`](docs/lessons-from-traces.md), linked from the
  README Weaver Stack table. Banned from `executor.py` like the other offline
  analysis modules.
- **Ecosystem-validation research synthesis** (#17): a one-time positioning
  spike committed as [`docs/research/ecosystem-validation.md`](docs/research/ecosystem-validation.md)
  — overlap analysis vs LangGraph / LangChain LCEL / LlamaIndex Workflows /
  OpenAI Agents SDK / Prefect / Dagster / Temporal, the MCP context-bloat
  evidence, a one-line differentiator, and a findings→backlog priority table.
- **`chainweaver` GitHub Action — flow validation in CI** (#149): the reusable
  composite action at `.github/actions/chainweaver` now runs
  `chainweaver check --format json` and emits inline `::error` PR annotations
  for each invalid flow file (new `annotate.py`), adds an `annotations` toggle
  input, and is covered by an `action-smoke` workflow that exercises the action
  against valid and invalid fixtures plus unit tests (`test_annotate.py`) that
  lock the annotation escaping (`:` / `,` / `%` / CR / LF) against injection.
  New docs page
  [`docs/github-action.md`](docs/github-action.md), surfaced from the README
  Integrations section and the distribution checklist. The `chainweaver-version`
  default is pinned to the current release (`0.12.0`); Marketplace publishing is
  a release-time step tracked in `docs/distribution.md`.

- **`chainweaver serve` — first-class MCP server** (#230): a new CLI command that
  loads a flow file plus its `--tools` modules and exposes the compiled flow as MCP
  tools over `stdio` / `sse` / `streamable-http`, so MCP-aware agents call a whole
  flow as one deterministic tool. Wraps the existing `chainweaver.mcp.FlowServer`
  (#72); the MCP SDK stays behind the `chainweaver[mcp]` extra via a guarded lazy
  import, so the base CLI is unaffected. New docs page
  [`docs/mcp-server.md`](docs/mcp-server.md), a ready-to-submit MCP registry manifest
  (`server.json`), and a distribution/listing checklist
  ([`docs/distribution.md`](docs/distribution.md)).
- **README Integrations section + verified recipe matrix** (#231): a consolidated
  README "Integrations" section surfacing the MCP server, MCP adapter, and the
  LangGraph / OpenAI Agents SDK / LangChain / LlamaIndex entry points. Recipes and
  the MCP server verified runnable against current framework versions (mcp 1.27.2,
  langgraph 1.2.4, openai-agents 0.17.4, langchain-core 1.4.0, llama-index-core
  0.14.22), recorded in `docs/distribution.md`.
- **Real Weaver Stack interop** (#233, #234): `chainweaver.integrations.weaver_spec`
  now consumes the published [`weaver-contracts`](https://pypi.org/project/weaver-contracts/)
  package directly (behind the `chainweaver[weaver-stack]` extra, pinned
  `weaver-contracts>=0.6,<1.0`) instead of carrying internal mirror types. New
  routing-consumption helpers — `make_routing_decision()`,
  `selected_capability_id()`, and `resolve_flow_from_routing_decision()` — let a
  Weaver router hand a `RoutingDecision` straight to ChainWeaver, which resolves
  it to a registered flow for deterministic execution. A new runnable example,
  `examples/weaver_stack_golden_path/`, wires contextweaver routing → ChainWeaver
  execution → agent-kernel gating with a printed `weaver_contracts.TraceEvent`
  audit trail, degrading gracefully when the extra is absent.
- **Offline LLM-assisted flow compiler** (#28): a new `chainweaver.compiler_llm`
  module exposing `LLMProposal`, `llm_propose_flows()`, and `write_proposals()`.
  It proposes deterministic `Flow` definitions from tool metadata using an LLM
  reached only through a provider-agnostic `llm_fn(prompt) -> completion`
  callable — **offline, at build time, never in the executor**. Proposals are
  returned as reviewable data (and optionally written as PR-ready `.flow.yaml`
  files plus a `PROPOSALS.md`); they are never auto-registered. Proposed flow
  names are validated as safe filenames before `write_proposals()` writes them,
  so a malformed completion cannot escape the target directory (path traversal).
- **Offline tool-description optimizer** (#100): a new `chainweaver.optimizer`
  module exposing `OptimizationStrategy`, `ToolDescriptionProposal`,
  `optimize_tool_descriptions()`, and `optimize_new_tool_description()`. It
  rewrites tool descriptions for ecosystem-wide discriminability (or
  conciseness / structure) via the same offline `llm_fn` seam, returning
  proposals with an approximate `token_delta` for human review.
  Both modules share a private `chainweaver._offline_llm` helper and a new
  typed `OfflineLLMError`; a guard test keeps `executor.py` free of any LLM
  import (core invariant #1). YAML parsing uses the existing `chainweaver[yaml]`
  extra, so the base install is unaffected.
- **Official Python 3.14 support** (#215): `pyproject.toml` classifiers and the
  CI test matrix now cover Python 3.10–3.14 inclusive.
- **Library-grade dependency hygiene** (#236): a `floor-deps` CI job installs
  the minimum declared dependency versions (`uv pip install --resolution
  lowest-direct`) and runs the full suite on Python 3.10, exercising the
  declared `>=` floors; a weekly scheduled `latest-deps` job runs the suite against the newest
  (incl. pre-release) dependencies on Python 3.14 as an early-warning canary.
  The dependency-constraint policy is documented in `CONTRIBUTING.md`.

- **Property-based fuzzing harness for flows** (#220): a new `chainweaver.fuzz`
  module exposing `FlowFuzzer`, `FlowProperty`, `FaultConfig`, `FuzzCase`,
  `FuzzFailure`, `FuzzReport`, and `BUILTIN_PROPERTIES`. The fuzzer generates or
  mutates initial inputs from a flow's `input_schema` (or a supplied base
  input), optionally injects malformed tool outputs via a seeded fault hook,
  executes the flow, and records any property violation as a replayable
  `ExecutionResult`. All randomness is seeded (`random.Random(seed)`) so runs
  are reproducible; the executor stays randomness-free. Fault injection now runs
  under a clone that preserves the executor's full configuration (middleware,
  caches, cost profile, redaction policy, decision callback) via the new
  `FlowExecutor.with_replaced_tools(...)`, and the schema-driven value generator
  is shared as the supported `chainweaver.attest.generate_value`.
- **Trace minimization** (#221): `minimize_failure(...)` delta-debugs a failing
  input down to the smallest reproducer that still violates a property,
  re-verifying every reduction via `FlowExecutor.execute_flow`.
- **`chainweaver fuzz` CLI command** (#222): runs property-based tests against a
  `.flow.{yaml,yml,json}` file with `--property` (built-in name or `module:attr`
  path), `--runs`, `--seed`, `--input`/`--input-file`, `--output-fault-prob`,
  `--minimize`, and `--save-failures`. Exits non-zero on a violation; saves
  redacted, replayable failure traces. `--redact` (the default) also redacts
  the failing/minimized inputs printed to stdout so secrets do not leak into CI
  logs; duplicate `--property` names are rejected up front; and saved-failure
  filenames are sanitized for cross-platform safety. Documented in
  `docs/cli.md`.
- **Trace-redaction helpers** (#217): `RedactionPolicy.redact_step_record` and
  `RedactionPolicy.redact_execution_result` return redacted copies of a
  `StepRecord` / `ExecutionResult` (used by `chainweaver fuzz --save-failures`
  to keep persisted artifacts secret-safe by default).
- New `FuzzConfigError` (a `ChainWeaverError`) for misconfigured fuzzing runs.

### Changed

- **MCP server now runs on standalone `fastmcp`** (#243, breaking for the
  `[mcp]` extra): `chainweaver.mcp.FlowServer` migrated from the SDK-bundled
  `mcp.server.fastmcp.FastMCP` to the standalone
  [`fastmcp`](https://github.com/jlowin/fastmcp) package (3.x). The `[mcp]`
  extra now installs `fastmcp>=3.4` alongside `mcp>=1.0` — the inbound
  `MCPToolAdapter` still imports `mcp.ClientSession`, and `fastmcp` re-uses
  `mcp.types.ToolAnnotations`. `FlowServer`'s public API is unchanged
  (constructor, `serve()`/`serve_async()`, `.fastmcp`, `.registered_tool_names`);
  `.fastmcp` now returns a `fastmcp.FastMCP` instance. Rationale (#243): the
  FastMCP bundled in the `mcp` SDK is effectively frozen, while the standalone
  [`fastmcp`](https://github.com/jlowin/fastmcp) (3.x) is where active
  development continues — so this is a maintenance/longevity move that resolves
  the #243 evaluation in favour of switching. The added dependency and its
  transitive footprint land only in the opt-in `[mcp]`/`[dev]` extras; the base
  install is unaffected.
- **Weaver Stack types are now the upstream `weaver-contracts` dataclasses**
  (#233, breaking): the previous internal Pydantic mirror types
  (`SelectableItem`, `RoutingDecision`, `CapabilityToken`) are replaced by the
  upstream contract shapes, so importing
  `chainweaver.integrations.weaver_spec` / `contextweaver` / `agent_kernel`
  now requires the `weaver-stack` extra. `flow_to_selectable_item()` returns the
  upstream `SelectableItem` (flow version/schema/tags live in `metadata`), and
  `KernelProtocol.invoke(capability_id, token, inputs)` takes the capability id
  explicitly and gates on the token's `scope`. `WEAVER_SPEC_VERSION` now tracks
  the installed contract (`0.6.0`). The base install is unaffected.
- **Dependency floors are now proven, not aspirational** (#236): bumped to the
  lowest versions the suite actually passes on — `deepdiff>=9.0` (was `>=8.0`;
  8.x imported `numpy` unconditionally and emitted a different tree-view diff
  shape), `typer>=0.24` (was `>=0.9`; needed for `click>=8.2` stderr capture),
  and `pydantic>=2.11` (was `>=2.0`). Removed the speculative `mcp<2` upper-bound
  cap (now `mcp>=1.0`), per the no-caps policy.

### Fixed

- **MCP registry manifest now resolves the `mcp` extra on a fresh launch**
  (#250): `server.json` carries a `--from 'chainweaver[mcp]'` `uvx` runtime
  argument so a fresh client installs `fastmcp`/`mcp` before running
  `chainweaver serve <flow_file>`, instead of launching bare `chainweaver`
  (which lacks the MCP dependencies). New `tests/test_server_manifest.py` guards
  the manifest version alignment and the `[mcp]`-extra launch. Publishing
  `chainweaver==0.12.0` to PyPI and running `mcp-publisher` remain external
  prerequisites tracked in #250 / #230.

## [0.11.0] - 2026-05-29

### Added

- **Framework recipes and workflow-template examples** (#204, #205, #206, #211,
  #213): a batch of runnable, mostly-offline examples plus paired cookbook pages
  that show how to adopt ChainWeaver from existing runtimes and use it as a
  deterministic workflow engine.
  - `examples/mcp_style_before_after_demo.py` (#204) — a before/after demo of an
    MCP-style path (`search_docs → extract_facts → validate_schema →
    format_answer`) showing model decisions avoided, and writing a saved
    `.flow.json` and an `ExecutionResult` trace artifact.
  - `examples/integrations/langgraph_node.py` (#205) — call a ChainWeaver flow
    from a LangGraph node; new optional `chainweaver[langgraph]` extra.
  - `examples/integrations/openai_agents_tool.py` (#206) — expose a flow as an
    OpenAI Agents SDK `FunctionTool` with a key-free dry-run; new optional
    `chainweaver[openai-agents]` extra.
  - `examples/release_readiness_flow/release_readiness.py` (#211) — a
    deterministic release-readiness `DAGFlow` that branches on placeholder test
    and repository-check results via `ConditionalEdge`.
  - `examples/skdr_policy_eval_flow.py` (#213) — a fixture-based offline
    policy-evaluation workflow with a deterministic support-health gate.
  - New cookbook pages under `docs/cookbook/` and a smoke-test module
    (`tests/test_workflow_recipe_examples.py`) that keeps every script runnable
    in CI; the dangling LangGraph/OpenAI-Agents recipe links in the README now
    resolve.

## [0.10.0] - 2026-05-28

### Added

- **`chainweaver.testing` subpackage and pytest plugin** (#132): new
  `chainweaver/testing/` subpackage exposing a public test harness for
  ChainWeaver flows.  `FlowTestRunner` is a thin facade over
  `FlowRegistry`+`FlowExecutor` that collapses the typical 10-line
  test setup into 3 lines (`register`, `fake_tool`/`passthrough_tool`,
  `execute`).  `fake_tool(name, output)` builds a permissive `Tool`
  whose `input_schema` / `output_schema` accept any dict, removing the
  Pydantic-schema boilerplate from unit tests; `output` may be a static
  dict or a `Callable[[dict], dict]` for ergonomic dynamic responses.
  `capture_steps(executor)` is a context manager that wires a
  `FlowExecutorMiddleware` into the executor and yields a live list of
  `StepRecord` events, removed cleanly on exit.
  `assert_result_matches(actual, expected, ignore=...)` does deep
  equality with `trace_id`, `started_at`, `ended_at`, `duration_ms`,
  and `total_duration_ms` ignored by default (`DEFAULT_IGNORE_FIELDS`).
  A pytest plugin shipped via the new `pytest11` entry-point at the
  top-level `pytest_chainweaver` module exposes a function-scoped
  `flow_runner` fixture, a session-scoped `flow_runner_session`
  fixture, and registers `@pytest.mark.flow(name)` so the marker no
  longer triggers `PytestUnknownMarkWarning`.  The plugin module
  deliberately lives outside the `chainweaver` package so that
  pytest's entry-point loader does not import the library before
  `pytest-cov` can start coverage tracking.
- **`record_then_replay` decorator** (#153): new
  `chainweaver.testing.record_then_replay(fixture_path,
  redaction=...)` decorator that captures every `Tool.fn` invocation
  inside the wrapped function on first run (when
  `CHAINWEAVER_RECORD=1` is set in the environment) and writes a
  deterministic-JSON fixture; subsequent runs serve the recording back
  to the executor without invoking the real callable, preserving full
  Pydantic input/output validation.  Recordings are looked up by
  `(tool_name, canonical(input_dict))` and consumed in FIFO order so
  the same `(tool, input)` pair appearing multiple times is
  disambiguated by occurrence order.  Unmatched invocations raise the
  new `FixtureStaleError` (re-exported from the `chainweaver` top level
  and listed in the README error table, like every other
  `ChainWeaverError` subclass) with a message that includes the
  re-record command and the fixture path.  The decorator hooks at the
  `Tool._call_fn` **and** `Tool._call_fn_async` boundaries — never
  inside `chainweaver/executor.py` — so both the synchronous
  (`execute_flow`) and asynchronous (`execute_flow_async`) executor
  lanes are recorded/replayed exactly once while the three hard executor
  invariants remain intact.  PII redaction is applied to every captured `input`
  and `output` dict before the fixture is written, defaulting to the
  shared `RedactionPolicy()` (masks `password`, `token`, `api_key`,
  `secret`, `authorization`); callers can disable it with
  `RedactionPolicy(redact_keys=frozenset())` or extend it explicitly.
- **`[project.entry-points.pytest11]`**: registered the pytest plugin
  via the standard entry-point mechanism so installing ChainWeaver
  makes `flow_runner` available in any pytest run without conftest
  edits.
- **`FlowExecutor.remove_middleware(middleware)`**: public counterpart
  to `add_middleware` that unregisters a middleware instance, silently
  ignoring one that is not currently registered.  Lets test helpers
  such as `capture_steps` tear down their collector through a stable
  API instead of reaching into the private `_middleware` list.

### Notes

- **#151 (`ResultStore` Protocol)** is closed as already satisfied by
  the existing `chainweaver.cache.StepCache` + `InMemoryStepCache` +
  `FileStepCache` (shipped in #127).  Every acceptance criterion in
  #151 — keyed lookups, schema-change invalidation, atomic file
  writes, public exports, no new runtime dependency — is met by the
  current cache implementation.  Naming differs (`StepCache` vs
  `ResultStore`), but functionally a parallel module would be pure
  duplication.

## [0.9.0] - 2026-05-27

### Added

- **MCP integration package** (#70, #72, #150): new `chainweaver.mcp`
  subpackage built on the official `mcp` Python SDK.
  - `MCPToolAdapter(session).discover_tools(server_prefix="…")` wraps
    each tool advertised by an MCP `ClientSession` as a ChainWeaver
    `Tool`.  Server-prefixed naming policy (#150) keeps multi-server
    catalogues collision-free.  Wrapped tools default to
    `cacheable=False` since remote calls can touch external state.
    `include` / `exclude` name filters select which tools to wrap, and
    `schema_overrides={tool: Model}` substitutes a custom Pydantic input
    model when the server's advertised `inputSchema` is insufficient
    (#70).
  - `FlowServer(executor, *, name, flow_names=None, server_prefix="")`
    mounts registered flows on a FastMCP server.  Each flow is
    advertised as one MCP tool whose `inputSchema` is derived from the
    flow's input schema (or first-step tool's input).  Dispatcher
    signatures are synthesised from `input_schema.model_fields` so MCP
    clients call `tool(field=value)` directly rather than wrapping
    everything under a `payload` parameter.  `serve()` (blocking) and
    `serve_async(transport=...)` (event-loop friendly) both expose
    stdio / SSE / Streamable-HTTP transports via FastMCP.
  - `jsonschema_to_pydantic(schema, name=…)` + companion
    `pydantic_to_jsonschema` bridge the wire format both directions.
  - New optional extra: `pip install 'chainweaver[mcp]'`.
- **Async executor lane** (#80): `FlowExecutor.execute_flow_async`
  coroutine that mirrors `execute_flow` natively in the calling event
  loop.  Each step is dispatched through `Tool.run_async`; async-fn
  tools (e.g. the MCP-wrapped ones) are awaited natively while sync
  tools are offloaded via `asyncio.to_thread`.  Retries use
  `asyncio.sleep` for backoff; middleware and `on_error` policies fire
  on the same surface as the sync path (including `fallback_used`
  bookkeeping on recovered steps).  Linear and DAG flows both
  supported.  Step cache + crash-resume checkpoint will follow.  Flows
  using conditional branching (#9) or decision callbacks (#102) raise
  `FlowExecutionError` up front on the async lane rather than silently
  dropping those directives — use the sync `execute_flow` until the
  async lane reaches parity.
- **`Tool.run_async`** + **`Tool.is_async`** (#80): `Tool` now accepts
  a sync or async `fn`; the cached `is_async` flag is computed once
  during construction and exercised by both runners.  `Tool.run`
  (sync) drives async tools via `asyncio.run` when no loop is running,
  and raises `ToolDefinitionError` when invoked from inside a running
  loop so callers don't silently break event-loop ownership.
- **New exception family**: `MCPError`, `MCPSchemaConversionError`,
  `MCPToolInvocationError`.  All inherit `ChainWeaverError` and are
  exported in `chainweaver.__all__`.
- **Examples**: `examples/mcp_adapter.py` (inbound) and
  `examples/mcp_flow_server.py` (outbound) — both runnable against the
  in-memory FastMCP transport.
- **Weaver Stack execution backend** (#89): new
  `chainweaver/integrations/agent_kernel.py` exposing
  `KernelBackedExecutor`, a `FlowExecutor` subclass that delegates
  `DAGFlowStep` instances with `step_type="capability"` through a
  structural `KernelProtocol`.  Capability steps produce the same
  `StepRecord` shape as tool steps and emit the same
  `on_step_start` / `on_step_end` middleware events, so observability,
  tracing, and `stream_flow` are uniform.  Ships an in-process
  `InMemoryKernel` for tests and offline
  runs and a new `KernelInvocationError` exception.  No agent-kernel
  PyPI dependency — `KernelProtocol` is a structural protocol so any
  transport (in-process, gRPC, HTTP, stub) can satisfy it.
- **Flow as Capability** (#90): `Flow` and `DAGFlow` gain an optional
  `capability_id: str | None = None` field.  When set, the flow is
  exposed as a routable Weaver Stack capability via
  `flow_to_selectable_item()`.  Round-trips through `flow_to_dict` /
  `flow_to_json` / `flow_to_yaml`.  See
  `docs/agent-context/flow-as-capability.md` for the full semantics.
- **Weaver-spec compatibility declaration + CI gate** (#91): new
  `docs/SPEC_COMPAT.md` plus the
  `chainweaver.integrations.weaver_spec.WEAVER_SPEC_VERSION` constant
  declare conformance to `weaver-spec` v0.1.0.  A new pytest
  `conformance` marker tags
  `tests/test_weaver_spec_conformance.py`; a dedicated CI job
  (`.github/workflows/ci.yml` → `conformance`) runs `pytest -m
  conformance` on the Python 3.10 / ubuntu-latest lane.
- **`DecisionCallback` Protocol** (#102): new `chainweaver/decisions.py`
  module with `DecisionCallback`, `DecisionContext`,
  `BaseDecisionCallback`, `DecisionCallable`, and
  `coerce_decision_callback`.  `FlowStep` gains an optional
  `decision_candidates: list[str] | None` field; `FlowExecutor` gains
  a `decision_callback=` constructor kwarg.  Steps with
  `decision_candidates` set call the registered callback to pick which
  candidate to invoke; failures (callback raises, or returns outside
  the candidate set) abort the step with a new `DecisionCallbackError`
  rather than silently falling back to the static `tool_name`.
  `FlowStep` validates at construction that `tool_name` is itself a
  member of `decision_candidates` (it is the default a callback may
  return).  Steps without `decision_candidates` never invoke the
  callback — existing flows behave identically.
- **Contextweaver routing adapter** (#106): new
  `chainweaver/integrations/contextweaver.py` exposing
  `RoutingDecisionAdapter` (a `DecisionCallback` impl that asks a
  duck-typed `ContextweaverClient` for a `RoutingDecision` and returns
  the selected capability id), plus a `StaticRoutingClient` for tests
  and offline runs.  No `contextweaver` PyPI dep.
- **`SelectableItem` capability exporter** (#107): new
  `chainweaver/integrations/weaver_spec.py` exposing the mirror types
  `SelectableItem`, `RoutingDecision`, and `CapabilityToken` (matching
  the weaver-spec v0.1.0 contract), plus the `flow_to_selectable_item()`
  function that projects a `Flow` or `DAGFlow` to a `SelectableItem`
  ready for contextweaver catalog ingestion.  Capability id resolves
  via explicit kwarg → `flow.capability_id` → `flow.name`.  Schemas
  are derived from `input_schema_ref` / `output_schema_ref` when set.
- **`[weaver-stack]` optional extra** in `pyproject.toml`: placeholder
  marker for the Weaver Stack sibling SDKs when they ship on PyPI.
  The mirror types in `chainweaver.integrations.weaver_spec` keep the
  integration self-contained until then.
- **Determinism + safety contracts** (#19): new `chainweaver/contracts.py`
  module exposing `ToolSafetyContract` (Pydantic, frozen) plus the
  `SideEffectLevel` / `StabilityLevel` / `DeterminismLevel` enums that
  describe a tool's safety surface.  Defaults are maximally permissive
  (`SideEffectLevel.NONE`, `StabilityLevel.STABLE`,
  `DeterminismLevel.FULL`, `idempotent=True`, `cacheable=True`,
  `requires_review=False`) so bare `Tool(...)` constructors keep working
  unchanged.  `merge_safety(contracts)` computes the most-restrictive
  contract across an iterable — used by `Tool.from_flow`.
- **`Tool.safety` attribute and `Tool.from_flow(..., safety=...)` derivation**
  (#125): every `Tool` instance now carries a `ToolSafetyContract`.
  `Tool.from_flow` derives the wrapped flow's contract via `merge_safety`
  over the constituent step tools (most-restrictive wins) and accepts an
  explicit `safety=` override that bypasses derivation entirely.  A
  `Tool`'s `cacheable` flag and its contract's `cacheable` are kept in
  lockstep: passing `cacheable=` seeds the default contract, an explicit
  `safety=` drives the flag, and a conflicting pair raises `ValueError`.
- **DAG conditional branching** (#9): `DAGFlowStep` gains two optional
  fields — `branches: list[ConditionalEdge]` and `default_next: str | None`.
  After a decision step runs, the executor evaluates each
  `ConditionalEdge.predicate` against the merged context; the first match
  picks the active downstream path.  Non-selected immediate dependents
  are recorded as `StepRecord(skipped=True)`, and the skip propagates to
  steps whose every predecessor is itself skipped.  `default_next` is the
  fallback when no edge matches.  Branch targets must be direct dependents
  — enforced at registration time by `validate_dag_topology`, which now
  raises `DAGDefinitionError(reason="unknown_branch_target")`.
- **Safe AST-based predicate evaluator** (#9): `evaluate_predicate(expr, ctx)`
  parses the expression with `ast.parse(mode="eval")` and walks the tree
  against an explicit node allow-list.  Supports variable lookups,
  subscript, unary `+`/`-` (for signed literals such as `n == -1`),
  `==`/`!=`/`<`/`<=`/`>`/`>=`, `in`/`not in`, and `and`/`or`/`not`
  (short-circuiting like Python, so the right operand of a settled
  `and`/`or` is never evaluated), plus literal constants.  Binary
  arithmetic, attribute access, and function calls are rejected.
  `eval`/`exec` are **never** called.  Syntax errors, unsupported nodes,
  and unresolved names raise the new `PredicateSyntaxError` exception.
- **Structural determinism inference on flows** (#8): `Flow.determinism_level`
  and `DAGFlow.determinism_level` computed properties return
  `DeterminismLevel.FULL` / `PARTIAL` / `NONE`.  Linear `Flow` →
  `FULL` (downgraded to `NONE` when `deterministic=False`); `DAGFlow`
  with any non-empty `branches` → `PARTIAL` (downgraded to `NONE` when
  `deterministic=False`).  Reflects flow *structure* only — tool-level
  contracts are not consulted here.
- **Public API exports** added to `chainweaver.__all__`:
  `BaseDecisionCallback`, `ConditionalEdge`, `DecisionCallable`,
  `DecisionCallback`, `DecisionCallbackError`, `DecisionContext`,
  `DeterminismLevel`, `KernelInvocationError`, `PredicateSyntaxError`,
  `SideEffectLevel`, `StabilityLevel`, `ToolSafetyContract`,
  `coerce_decision_callback`, `evaluate_predicate`, `merge_safety`.
- **New Weaver Stack integration symbols** (import from the submodule —
  not re-exported from `chainweaver` to keep the public surface narrow):
  `chainweaver.integrations.weaver_spec`
  (`WEAVER_SPEC_VERSION`, `CapabilityToken`, `RoutingDecision`,
  `SelectableItem`, `SpecCompatibilityReport`, `flow_to_selectable_item`,
  `spec_compatibility_report`),
  `chainweaver.integrations.contextweaver`
  (`ContextweaverClient`, `RoutingDecisionAdapter`, `StaticRoutingClient`),
  and `chainweaver.integrations.agent_kernel`
  (`InMemoryKernel`, `KernelBackedExecutor`, `KernelProtocol`).
- **Typed step input / output contracts** (#172): `FlowStep` gains
  optional `input_contract` and `output_contract` fields (each a
  `"module:qualname"` string ref to a Pydantic `BaseModel` subclass).
  When set, `FlowExecutor` validates the resolved inputs against
  `input_contract` *before* the tool runs and the tool's outputs against
  `output_contract` *after* the tool runs.  Failures surface as
  `SchemaValidationError` with `context="step_input_contract"` /
  `"step_output_contract"` and abort the step.  `FlowStep` exposes
  `resolved_input_contract` / `resolved_output_contract` properties and
  a `contract_ref_from(cls)` static helper mirroring
  `Flow.schema_ref_from`.  `DAGFlowStep` inherits both fields; the
  executor forwards them through the DAG-step proxy.
- **`Flow.context_schema_ref` / `DAGFlow.context_schema_ref`** (#152):
  optional class ref to a Pydantic `BaseModel` describing the shape of
  the accumulated execution context.  The executor validates the final
  context against the resolved schema at flow end (mirroring
  `output_schema_ref`).  Primary value is static typing — mypy + IDE
  autocomplete over a single source of truth for context keys; runtime
  validation at the flow boundary is a secondary safety net.  Both
  models expose a lazy `.context_schema` property.
- **JSON Schema export for flow files** (#135): new `chainweaver/schemas.py`
  module exposing `flow_schema_json()` which returns a draft-2020-12
  JSON Schema describing the on-disk `.flow.json` / `.flow.yaml`
  format.  Derived from the live Pydantic models via
  `model_json_schema()` so it never drifts from the runtime types.
  Combined `oneOf` over Flow and DAGFlow discriminated by the existing
  `type` field; nested `$defs` are merged.  Exported in
  `chainweaver.__all__`.
- **CLI `dump-schema`** (#135): `chainweaver dump-schema [--output PATH] [--check]`
  writes the schema to disk (default stdout) and supports a CI-friendly
  `--check` mode that fails with exit 1 when the on-disk artifact
  drifts from the Pydantic source of truth.  Recommended in-repo path:
  `schemas/flow.schema.json` (now checked in).
- **SchemaStore submission template** (#139): new
  `schemas/schemastore-catalog-entry.json` (maintainer-facing payload
  to drop into SchemaStore/schemastore's `catalog.json`) plus
  `docs/json-schema.md` documenting the editor setup today (VS Code
  YAML, JetBrains) and the upstream submission workflow.
- **`@tool(output_schema=…)` keyword** (#118): the decorator now
  accepts an explicit `output_schema` parameter so user code can type
  the function body's return as `dict[str, Any]` without
  `# type: ignore[return-value]`.  When unset, the existing
  return-annotation path still works.  Function bodies may now also
  return a `BaseModel` instance directly; the adapter calls
  `model_dump()` on the way out.  All 22 `type: ignore[return-value]`
  suppressions in `tests/test_decorators.py` were removed.
- **CLI `doctor`** (#175): `chainweaver doctor --check-drift <path>`
  loads every flow file under *path* (single file or recursive
  directory), imports tools from the modules passed via `--tools`, and
  reports per-flow `missing_tool` and `schema_mismatch` issues using
  `check_flow_compatibility`.  Flows without a recorded
  `tool_schema_hashes` snapshot are surfaced as
  `fingerprints_present=False` so callers can distinguish "fingerprints
  match" from "no fingerprints were recorded".  Supports
  `--format table|json`.  Exit codes: 0 = no drift, 1 = drift detected
  or malformed flow file, 2 = path or `--tools` module missing.
- **`FlowExecutor.registered_tools`** (#178): public read-only accessor
  that returns a snapshot of currently registered tools as
  `dict[str, Tool]`.  Replaces ad-hoc private `_tools` access in
  downstream consumers; `doctor --check-drift` and `attest_flow`
  now use the public accessor.
- **Profile reliability aggregates** (#176): `chainweaver profile`
  JSON output now carries `retry_count`, `skipped`, `fallback_used`,
  `cached`, and `error_type` on every step entry, plus an
  `aggregates` block with totals (`retry_count`, `skip_count`,
  `fallback_count`, `failure_count`, `cached_count`) and a `by_tool`
  breakdown keyed by tool name with `invocation_count` and the same
  per-bucket counts.  Multi-trace mode sums these across every trace.
  The table view surfaces the same data as a "Reliability:" footer
  plus a per-tool problem list (only emitted when at least one count
  is non-zero, so happy-path runs keep their compact output).
- **`StepRecord.fallback_used`** (#176): new boolean field set when
  the step's `on_error="fallback:<tool_name>"` policy invoked a
  fallback tool — set regardless of whether the fallback itself
  succeeded or failed (covers the case where the configured fallback
  tool is missing too).

### Changed

- **`Tool.__init__` `fn` parameter type** widened to
  `Callable[[Any], dict[str, Any] | Awaitable[dict[str, Any]]]` (#80)
  — previously the sync return shape only.
- **`docs/agent-context/architecture.md`** module-boundaries table
  gained the `mcp/` row; planned-modules table flips `mcp/` to
  delivered.
- **`AGENTS.md`** repo map and Key entry points expanded with
  `execute_flow_async`, `MCPToolAdapter`, and `FlowServer`.

### Fixed

- **`dump-schema --check` guidance** (#181): both error messages now
  interpolate the real `--output` path (single-quoted, matching the
  surrounding exception-message style) instead of printing the literal
  `{path}` token to stderr.  Locked with regression assertions in
  `tests/test_cli_dump_schema.py`.
- **DAG step retry / on_error parity** (#181): the DAG executor proxy
  was forwarding the `#172` step-contract refs but silently dropping
  `retry` and `on_error`, so DAG steps ignored per-step retry policy
  and `on_error` handling.  The proxy now forwards both fields; new
  `TestDAGStepRetryParity` and `TestDAGStepOnErrorParity` in
  `tests/test_step_contracts.py` lock the parity contract.
- **Public API snapshot** order-independence (mirroring the fix being
  shipped in #177): `tests/public_api_snapshot.py` now skips
  constructor signatures for Pydantic models (which differ depending
  on forward-ref resolution state inside the same pytest process),
  treats `types.GenericAlias` (`ToolChain = tuple[str, ...]`) before
  class inspection, and normalises unresolved forward references
  through `chainweaver.__all__`.  Regenerated `tests/fixtures/public_api.json`
  to match.

## [0.8.0] - 2026-05-22

### Added

- **CLI `suggest`** (#155): `chainweaver suggest <flow.yaml|json>` emits
  advisory static optimization suggestions for a flow.  Four suggestion
  families with stable codes:
  - `CW001` — wasteful-passthrough: a step passes the full context to a
    tool whose input schema uses only a subset of keys.
  - `CW002` — parallelizable-pair: two adjacent linear steps read
    disjoint context keys and could run concurrently.  Requires
    `--tools`.
  - `CW003` — dead-step: a step's outputs are not referenced by any
    downstream step's `input_mapping`.  Requires `--tools`.
  - `CW004` — cacheable-step: across two or more observed trace files
    the step produces identical outputs for identical inputs.  Requires
    `--trace`.
  Accepts `--tools` (repeatable Python module path), `--trace` (repeatable
  path to `ExecutionResult` JSON files for CW004), and `--format
  table|json`.  Exit code is always 0 (the suggester is advisory).
  `suggest_optimizations(flow, *, tools, traces)` and the `Suggestion`
  model are exported in `chainweaver.__all__`.

### Fixed

- `suggest_optimizations` no longer emits false-positive CW002 or CW003
  suggestions when a step has an empty `input_mapping` (which passes the
  full context — that step cannot be treated as having disjoint or
  dead outputs without full schema information).
- CW001 docstring now correctly states that `--tools` is required to
  detect wasteful-passthrough for steps without explicit `input_mapping`.

### Tests

- **Property-based determinism harness** (#143): new
  `tests/property/test_idempotence.py` and
  `tests/property/test_dag_equivalence.py` using Hypothesis strategies
  (defined in `tests/property/strategies.py`) to assert that linear and
  DAG flows produce identical results across repeated executions with
  the same inputs.  Tagged `@pytest.mark.property`; run as part of the
  standard `pytest` suite.
- **Public-API snapshot guard** (#140): `tests/test_public_api_snapshot.py`
  pins the exact set of names exported in `chainweaver.__all__` against
  a golden fixture (`tests/fixtures/public_api.json`), catching accidental
  additions or removals before they reach a release.

### CI / Infrastructure

- **Performance-budget guard** (#144): `bench.yml` workflow now uses
  `github-action-benchmark` to store naive-vs-compiled benchmark results
  on `gh-pages` and fail PRs whose median `total_duration_ms` regresses
  beyond 125 % of the baseline.  Baseline bootstraps automatically on the
  first push to `gh-pages`.
- **Reusable `chainweaver-action`** (#149): composite GitHub Action that
  wraps the CLI; lets downstream workflows call
  `uses: dgenio/ChainWeaver/.github/actions/chainweaver-action@main`
  without installing ChainWeaver separately.
- **Pre-commit hooks** (#137): `.pre-commit-config.yaml` mirrors the four
  AGENTS.md §7 validation commands (`ruff check`, `ruff format --check`,
  `mypy`, `pytest`).  Install with `pre-commit install`.

### Docs

- Added `docs/comparisons.md` comparing ChainWeaver to LangChain,
  LangGraph, Prefect, Dagster, and Temporal (#141).
- Added OSS health files: `CODE_OF_CONDUCT.md`, `SECURITY.md`, and
  expanded `CONTRIBUTING.md` with pre-commit hook installation
  instructions (#138).

## [0.7.0] - 2026-05-20

### Added

- **Observed-determinism attestation** (#154): new `chainweaver/attest.py`
  module exposing `attest_flow(flow, executor, n, repeats, seed,
  seed_inputs=None)` → `AttestationReport`.  Runs a flow N×M times with
  seeded inputs and verifies that every repeat for a given input produces
  identical `final_output`.  Emits a reproducible `aggregate_fingerprint`
  when all repeats agree; sets `observed_deterministic=False` on the first
  divergence.  Input synthesis covers `int`, `float`, `bool`, `str`,
  `list[...]`, `dict`, `Literal[...]`, `Optional[X]`, and nested Pydantic
  `BaseModel` subclasses; unsupported annotations raise the new
  `AttestationInputError`.  The private `random.Random(seed)` instance used
  for input generation never touches the global random state, preserving
  the executor's randomness-free invariant.  `attest_flow`,
  `AttestationReport`, and `AttestationInputError` are exported in
  `chainweaver.__all__`.
- **CLI `attest`** (#154): `chainweaver attest <file.flow.yaml|json>`
  runs observed-determinism attestation from the command line.  Accepts
  `--tools` (repeatable Python module path), `--runs N` (number of seeded
  inputs, default 3), `--repeats M` (executions per input, default 3),
  `--seed` (integer seed for reproducibility), `--seed-input` (path to a
  JSON object used as the single seed input), and `--format json|table`.
  Default output is the full attestation JSON artifact; `table` prints a
  compact human-readable summary.  Exit codes: 0 = observed deterministic,
  1 = non-deterministic or attestation error, 2 = file or module not found.
- **Public API snapshot guard** (#140): new `tests/test_public_api_snapshot.py`
  and `tests/fixtures/public_api.json` that pin the exact set of exported
  names in `chainweaver.__all__`, catching accidental additions or removals
  before they reach a release.

### Fixed

- `attest_flow` now raises `AttestationInputError` immediately when `n < 1`
  or `repeats < 1` rather than silently completing with an empty report.

## [0.6.0] - 2026-05-19

### Added

- **`ChainAnalyzer`** (#77): new `chainweaver/analyzer.py` module with a
  `ChainAnalyzer` class for offline, static schema-compatibility analysis.
  Answers three questions: pairwise compatibility
  (`ChainAnalyzer.compatibility_matrix`), N-step chain enumeration
  (`ChainAnalyzer.find_chains(max_depth, *, start, end)`), and flow
  suggestion (`ChainAnalyzer.suggest_flows(...)`) which promotes discovered
  chains to ready-to-register `Flow` objects with auto-wired
  `input_mapping`.  The analysis is a pure-Python static pass — no LLM, no
  network, no randomness.  `ChainAnalyzer` and the `ToolChain` type alias
  are exported in `chainweaver.__all__`.  See `examples/chain_analyzer.py`.
- **CLI `run`** (#129): `chainweaver run <file.flow.yaml|json>` executes a
  flow definition from disk.  Accepts `--tools` (repeatable Python module
  path to import `Tool` instances from), `--input` (JSON string) or
  `--input-file` (path to a JSON object file), `--format table|json`, and
  `--quiet` (suppress all output, communicate result via exit code only).
  Exit codes: 0 = success, 1 = flow/import failure, 2 = file or module not
  found.
- **CLI `profile`** (#147): `chainweaver profile <trace.json>...` analyzes
  `ExecutionResult` JSON files and surfaces bottlenecks.  Single-file mode
  renders a per-step duration bar chart with total / step-sum /
  orchestration-overhead metrics.  Multi-file mode (all files must share
  `flow_name` and step count) computes p50 / p95 / p99 / mean / stdev per
  step and flags consistency warnings when stdev exceeds 50 % of mean.
  Supports `--top N` and `--format table|json`.
  Exit codes: 0 = ok, 1 = malformed trace or incompatible aggregation,
  2 = file not found.
- **CLI `diff`** (#148): `chainweaver diff <a.json> <b.json>` compares two
  `ExecutionResult` JSON files step-by-step.  Aligns records by position
  and checks `outputs` / `error_type` / `error_message` / `success`;
  non-deterministic fields (`trace_id`, timestamps, durations) are ignored
  by default.  Optional `--perf-tolerance N` (percent) flags per-step
  duration regressions.  Output uses `deepdiff` for nested-dict semantics.
  Supports `--format table|json`.
  Exit codes: 0 = identical, 1 = differs, 2 = file not found or malformed.

## [0.5.0] - 2026-05-17

### Changed

- **PR #136 review-feedback fixes** for the executor extensibility
  stack (#126/#127/#128/#131/#134):
  - `FileStepCache._file_path` now includes a SHA-256 digest of the
    original ``tool_name`` in the filename, eliminating a silent
    cross-tool cache-collision when distinct tool names sanitize to
    the same form (e.g. ``"foo/bar"`` vs ``"foo_bar"``) and share
    schemas + inputs.
  - `FileStepCache.set` is now atomic (``tempfile.mkstemp`` +
    ``os.replace``), matching the pre-existing ``FileCheckpointer.save``
    pattern.  Corrupt files left behind by older non-atomic writes
    are still treated as misses.
  - `OTelTraceExporter` keeps its open spans in dicts keyed by
    ``trace_id`` rather than scalar instance attributes, so sharing a
    single exporter across executors no longer leaks the first
    flow's parent span.
  - `FlowExecutor.resume_flow` now raises two typed exceptions
    inheriting from `ChainWeaverError` — ``CheckpointerNotConfiguredError``
    and ``CheckpointNotFoundError`` — instead of the previous opaque
    `ValueError`s.  Both are exported in ``chainweaver.__all__``.
  - `_datetime_to_ns` in the OTel integration now asserts
    ``dt.tzinfo is not None`` rather than silently reinterpreting
    naive datetimes as UTC.
  - `stream_flow` emits a ``WARNING`` via the ``chainweaver.executor``
    logger when the consumer breaks out of iteration mid-flow (the
    background thread still runs to completion — cancellation lands
    with #80).
  - ``FlowExecutor`` class docstring now explicitly states the
    single-thread-per-instance contract; ``InMemoryStepCache`` /
    ``InMemoryCheckpointer`` docstrings note their dict-backed,
    no-internal-locking semantics.
  - ``ExecutionResult.total_duration_ms`` docstring now explains that
    after a ``resume_flow`` it covers only the resume process's
    wall-clock (not the elapsed time across the original crash and
    resume).
  - Test suite no longer reaches into ``FlowExecutor._middleware``
    or ``FlowExecutor._tools`` private attributes — uses public
    ``register_tool`` re-registration and behavioral assertions
    instead.
  - New regression test pins the resume-log invariant:
    ``len(resumed.execution_log) == len(snapshot.execution_log) +
    steps_remaining``.

### Added

- **OpenTelemetry trace exporter** (#126): new
  `chainweaver/integrations/opentelemetry.py` module exposing
  `OTelTraceExporter` (a `FlowExecutorMiddleware` that emits one
  parent `chainweaver.flow.{name}` span + one child
  `chainweaver.tool.{name}` span per `StepRecord`) and
  `export_result_to_otel(result, tracer=...)` for after-the-fact
  emission from a completed `ExecutionResult`.  Span attributes
  carry `chainweaver.trace_id`, `chainweaver.flow_version`,
  `chainweaver.total_steps`, `chainweaver.step_index`,
  `chainweaver.tool_name`, `chainweaver.step.success`,
  `chainweaver.step.duration_ms`, `chainweaver.step.retry_count`,
  `chainweaver.step.cached`, `chainweaver.step.skipped`, and on
  failure `chainweaver.step.error_type`; the span status is set to
  `ERROR` and the message becomes the status description.
  `chainweaver.step.input_keys` reports the sorted list of input
  field names (not values — a privacy and cardinality hazard).
  Pre-resolution failures (tool-not-found / input-mapping) emit a
  zero-duration step span at `on_step_end` so the failure is still
  visible.  Optional dependency declared as `chainweaver[otel]`;
  importing the module without the extra raises a clear
  `ImportError`.  See `examples/otel_export.py`.
- **Crash-resume checkpointing** (#128): new `chainweaver/checkpoint.py`
  module with a `Checkpointer` `typing.Protocol`, an
  `ExecutionSnapshot` Pydantic model, `InMemoryCheckpointer`
  (dict-backed), and `FileCheckpointer` (JSON-on-disk, one file per
  `trace_id`, written atomically via `tempfile.mkstemp` +
  `os.replace`).  `FlowExecutor.__init__` accepts a `checkpointer=`
  argument and a `delete_on_success=True` flag; when set, an
  `ExecutionSnapshot` is written after every successful linear step
  or DAG level.  New `FlowExecutor.resume_flow(trace_id)` loads a
  snapshot, validates the recorded flow version and every relevant
  tool's `schema_hash` against the current registry (mismatches raise
  the new `CheckpointDriftError`), and continues execution with the
  original trace id — the resulting `ExecutionResult.execution_log`
  contains both recovered and freshly executed records.  On terminal
  success the snapshot is deleted; on failure it is preserved so
  operators can fix the underlying issue and call `resume_flow`
  again.  DAG checkpoints live at level boundaries (within a level
  the steps are replayed from scratch on resume — the simplest
  correct semantics).  See `examples/checkpoint_resume.py`.
- **Step-result caching layer** (#127): new `chainweaver/cache.py`
  module with a `StepCache` `typing.Protocol`, `InMemoryStepCache`
  (dict-backed), `FileStepCache` (JSON-on-disk, one file per
  `(tool, schema, input)` triple), and a `StepCacheKey` Pydantic
  model.  `FlowExecutor.__init__` accepts an optional `step_cache=`
  argument; when set, eligible step outputs are read from / written
  to the cache around the step boundary.  Cache keys include the
  tool's `schema_hash`, so schema changes invalidate entries
  automatically.  Cache hits skip `Tool.fn` entirely — including
  retries and `timeout_seconds` — and the resulting record reports
  `StepRecord.cached=True`.  Cache writes happen *after* output
  schema validation so invalid output never poisons the cache; on
  disk, corrupt cache files are treated as misses.  `Tool` gains a
  `cacheable: bool = True` parameter — set `cacheable=False` for
  tools with side effects or that read external state to force them
  to always run.  `replay_flow` always bypasses the cache (replay
  must always re-execute).
- **Streaming `stream_flow` generator** (#134): new
  `FlowExecutor.stream_flow(flow_name, initial_input, *, force=False)`
  method returns a sync `Iterator[FlowEvent]` that yields lifecycle
  events as the flow runs (`flow_start` → `(step_start, step_end)*` →
  `flow_end`).  Implementation reuses the lifecycle hook seam from
  #131 — an internal `_StreamCollectorMiddleware` writes events to a
  `queue.Queue` from a worker thread.  `flow_end` always fires (even
  on failure); steps that fail before input resolution emit
  `step_end` without a preceding `step_start`, matching the
  middleware lifecycle contract.  `FlowEvent` is a frozen Pydantic
  model that round-trips through `model_dump_json` /
  `model_validate_json`.  Sync-variant cancellation is intentionally
  not supported: if the consumer stops iterating, the background
  worker runs the flow to completion and exits.  The async variant
  (`stream_flow_async`) is gated on issue #80.  See
  `examples/streaming_flow.py`.
- **Middleware lifecycle seam** (#131): new `chainweaver/middleware.py`
  module exposing a `FlowExecutorMiddleware` `typing.Protocol` with
  four hooks — `on_flow_start`, `on_step_start`, `on_step_end`,
  `on_flow_end` — plus the matching Pydantic context models
  (`FlowStartContext`, `StepStartContext`, `StepEndContext`,
  `FlowEndContext`) and an optional `BaseMiddleware` no-op base class.
  `FlowExecutor` accepts a `middleware=` list and exposes
  `add_middleware(...)`; hooks fire in registration order at fixed
  boundaries.  Middleware exceptions are caught and logged at
  `WARNING` via the `chainweaver.middleware` logger — observability
  bugs cannot abort a flow execution.  Steps that fail before input
  resolution (tool-not-found, input-mapping) emit `on_step_end`
  without a preceding `on_step_start`; every other code path emits
  the symmetric `start` / `end` pair.  This is the extension point
  the upcoming OpenTelemetry exporter (#126), step-result cache
  (#127), `Checkpointer` (#128), and streaming-events generator
  (#134) will all plug into.  In-tree migration of `log_utils` and
  cost reporting onto the seam will follow in a separate change.
- **`Tool.from_flow`** (#24): wrap a registered `Flow` or `DAGFlow` as a
  single `Tool` whose `fn` delegates back to a `FlowExecutor`.  The
  resulting tool is registrable like any other tool, so a compiled flow
  can be composed as a step inside another flow or exposed as one
  capability to external consumers.  Schemas are derived from explicit
  overrides, then the flow-level `input_schema_ref` / `output_schema_ref`,
  then the first/last step's tool schema (or unique DAG sink).  Inner
  flow failures surface as `FlowExecutionError`.  See
  `examples/virtual_tool.py`.

## [0.4.0] - 2026-05-12

### Added

- **Flow serialization** (#14): `Flow.to_yaml` / `to_json` /
  `from_yaml` / `from_json` (and `DAGFlow` equivalents) plus the
  module-level helpers `flow_to_dict`, `flow_from_dict`, `flow_to_json`,
  `flow_from_json`, `flow_to_yaml`, `flow_from_yaml`. JSON support has
  no extra runtime dependency; YAML support requires the new optional
  extra `chainweaver[yaml]` (`pyyaml>=6.0`).
- **`FlowSerializationError`** exception covering malformed payloads,
  unknown `type` discriminators, unresolvable class refs, and
  wrong-base refs.
- **Pluggable registry storage** (#16): new `chainweaver/storage.py`
  with a `RegistryStore` `typing.Protocol`, an `InMemoryStore` default
  (preserves prior in-process behavior), and a `FileStore` that
  persists each flow as `{name}@{version}.flow.json`. `FlowRegistry`
  now accepts an optional `store=` parameter; the latest-version
  pointer is rebuilt from the store on construction so file-backed
  registries survive process restarts.
- **CLI `validate`** (#45) — validate a single
  `.flow.yaml` / `.flow.yml` / `.flow.json` file. Exit codes:
  0 = valid, 1 = validation error, 2 = file not found.
- **CLI `check`** (#45) — validate every flow file in a directory
  (recursive). Supports `--quiet` and `--format json`. Exit codes:
  0 = all valid, 1 = at least one invalid, 2 = directory not found.
- **CLI `viz`** (#46) — render a registered flow as ASCII (default)
  or DOT/Graphviz text. `chainweaver viz my_flow --format dot |
  dot -Tpng -o my_flow.png` produces a rendered image.
- **`flow_to_dot`** renderer in `chainweaver/viz.py`, plus
  `Flow.to_dot()` / `DAGFlow.to_dot()` convenience methods.
- **Benchmarks** (#29): new top-level `benchmarks/` directory with
  `bench_naive_vs_compiled.py` (standalone, no test-framework deps)
  and `benchmarks/README.md`.
- **CI matrix** (#34): `ubuntu-latest`, `windows-latest`, and
  `macos-latest` × Python 3.10–3.13 (12 jobs total). Lint, format, and
  mypy remain pinned to the canonical Python 3.10 / Ubuntu leg.
- **`docs/versioning-policy.md`** documenting the SemVer policy, public
  API surface, and deprecation process.

### Changed

- **BREAKING:** `Flow.version` and `DAGFlow.version` are now **required**
  fields (no `"0.0.0"` default). Callers that previously relied on the
  implicit default must pass an explicit `version="..."`.
- **BREAKING:** `Flow.input_schema` / `output_schema` (and the
  `DAGFlow` equivalents) are no longer `type[BaseModel] | None` fields.
  They are now read-only properties that lazy-resolve new
  `input_schema_ref` / `output_schema_ref` fields holding
  `"module:qualname"` strings. Use
  `Flow.schema_ref_from(MySchema)` to derive the ref string from a
  class. This change makes flows fully JSON/YAML-serializable; the
  cost is that schemas referenced by serialized flows **must** live at
  module top level (Python cannot reach `<locals>` via `importlib`).
- **BREAKING:** `RetryPolicy.retryable_errors` is now a
  `tuple[str, ...]` of `"module:qualname"` references rather than a
  `tuple[type[BaseException], ...]`. The default value is
  `("builtins:Exception",)`. `RetryPolicy.resolved_retryable_errors()`
  resolves the refs to live classes just before the executor's retry
  loop. Migrate `retryable_errors=(KeyError,)` to
  `retryable_errors=("builtins:KeyError",)`.
- `FlowBuilder` gains a `with_version(...)` method; if not called, the
  builder picks a sensible `"0.1.0"` default to keep prototypes terse.
- The CLI top-level help string now lists all four subcommands
  (`inspect`, `validate`, `check`, `viz`).
- `flow_to_ascii` (and the `Flow.to_ascii()` / `DAGFlow.to_ascii()`
  convenience methods, which it backs) now emits the unicode arrow `→`
  between steps instead of `-->`, matching issue #46's acceptance
  criterion. Consumers that string-matched `[a] --> [b]` should update
  their expectations to `[a] → [b]`. The Mermaid renderer
  (`flow_to_mermaid`) is unaffected — Mermaid grammar still requires
  `-->`.

### Migration guide (0.2.x → 0.4.0)

```python
# Before
flow = Flow(
    name="example",
    description="...",
    steps=[...],
    input_schema=MyInput,
    output_schema=MyOutput,
)
policy = RetryPolicy(retryable_errors=(ValueError,))

# After
flow = Flow(
    name="example",
    version="1.0.0",            # now required
    description="...",
    steps=[...],
    input_schema_ref=Flow.schema_ref_from(MyInput),
    output_schema_ref=Flow.schema_ref_from(MyOutput),
)
policy = RetryPolicy(retryable_errors=("builtins:ValueError",))
```

Reading the resolved schema is still ergonomic:

```python
flow.input_schema   # → MyInput (resolves the ref lazily)
```

## [0.2.0] and earlier

This file starts at 0.4.0.  See the git history for the contents of the
0.1.0 and 0.2.0 releases.

[Unreleased]: https://github.com/dgenio/ChainWeaver/compare/v0.12.1...HEAD
[0.12.1]: https://github.com/dgenio/ChainWeaver/compare/v0.12.0...v0.12.1
[0.12.0]: https://github.com/dgenio/ChainWeaver/compare/v0.11.0...v0.12.0
[0.11.0]: https://github.com/dgenio/ChainWeaver/compare/v0.10.0...v0.11.0
[0.10.0]: https://github.com/dgenio/ChainWeaver/compare/v0.9.0...v0.10.0
[0.9.0]: https://github.com/dgenio/ChainWeaver/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/dgenio/ChainWeaver/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/dgenio/ChainWeaver/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/dgenio/ChainWeaver/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/dgenio/ChainWeaver/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/dgenio/ChainWeaver/releases/tag/v0.4.0
