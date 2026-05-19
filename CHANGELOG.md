# Changelog

All notable changes to ChainWeaver will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
(see [docs/versioning-policy.md](docs/versioning-policy.md)).

## [Unreleased]

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

[Unreleased]: https://github.com/dgenio/ChainWeaver/compare/v0.5.0...HEAD
[0.5.0]: https://github.com/dgenio/ChainWeaver/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/dgenio/ChainWeaver/releases/tag/v0.4.0
