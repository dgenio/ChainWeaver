# Changelog

All notable changes to ChainWeaver will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
(see [docs/versioning-policy.md](docs/versioning-policy.md)).

## [Unreleased]

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
  new `FixtureStaleError` (exported from `chainweaver.testing`) with a
  message that includes the re-record command and the fixture path.
  The decorator hooks at the `Tool._call_fn` boundary — never inside
  `chainweaver/executor.py` — so the three hard executor invariants
  remain intact.  PII redaction is applied to every captured `input`
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

[Unreleased]: https://github.com/dgenio/ChainWeaver/compare/v0.9.0...HEAD
[0.9.0]: https://github.com/dgenio/ChainWeaver/compare/v0.8.0...v0.9.0
[0.8.0]: https://github.com/dgenio/ChainWeaver/compare/v0.7.0...v0.8.0
[0.7.0]: https://github.com/dgenio/ChainWeaver/compare/v0.6.0...v0.7.0
[0.6.0]: https://github.com/dgenio/ChainWeaver/compare/v0.5.0...v0.6.0
[0.5.0]: https://github.com/dgenio/ChainWeaver/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/dgenio/ChainWeaver/releases/tag/v0.4.0
