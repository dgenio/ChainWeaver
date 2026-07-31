# Execution Semantics Reference

> Field-level reference for the executor's data contracts: `Flow`,
> `FlowStep`, `DAGFlowStep`, `ExecutionResult`, and `StepRecord`, plus the
> collision, concurrency, composition, and mapping semantics that govern
> them. Moved from AGENTS.md §5 so the root contract stays stable; the
> **normative invariants** (deterministic executor, async parity matrix,
> single-merge-point rule) remain in
> [AGENTS.md § Executor and flow semantics](/AGENTS.md#5-executor-and-flow-semantics).
> Consult this file when adding or changing fields, mappings, or execution
> behavior; keep it consistent with the Pydantic models it describes.

---

## `Flow` (Pydantic model)

The rows below are the actual Pydantic fields (`Flow.model_fields`), in
declaration order, and the table is exhaustive. `DAGFlow` carries the same
field **names**, with two differences: `version` is **required** (no
default), and `steps` is typed `list[DAGFlowStep]` (which extends `FlowStep`
with conditional `branches` — see the `DAGFlowStep` subsection below).

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
| `capability_id` | `str \| None` | `None` | Optional Weaver Stack capability identifier (#90); when set, the flow is routable as a `SelectableItem` via `flow_to_selectable_item`. See [flow-as-capability.md](flow-as-capability.md). |
| `governance` | `FlowGovernance` | active defaults | Review lifecycle, owner, replacement-tool list, savings estimates, and review notes (#259, #268). Separate from `FlowStatus`. |
| `safety` | `ToolSafetyContract \| None` | `None` | Explicit flow-level side-effect, retry, dry-run, idempotency, and approval metadata (#293). `None` means unknown, not safe. |
| `on_context_collision` | `Literal["overwrite", "warn", "error"]` | `"warn"` | Policy when a step output overwrites an existing context key (#337). `"overwrite"` = silent last-write-wins; `"warn"` = log at WARNING then overwrite; `"error"` = abort with `ContextKeyCollisionError`. Applied by the single shared merge helper (`chainweaver._execution.merge_step_outputs`) on both linear and DAG, sync and async. DAG *sibling* collisions within one level remain an unconditional error regardless. |
| `dynamic_params` | `tuple[str, ...]` | `()` | Declarative names of params injected at execute-time via `execute_flow(..., dynamic_params={...})` rather than `initial_input` (#316). Merged into the running context *after* `input_schema` validation, so they reach every step's `input_mapping` and the final output yet stay out of the LLM-visible `input_schema` — for per-request secrets a model must never see. Metadata only; the executor accepts any `dynamic_params` keys whether or not they are declared here. |

## Context-collision semantics (#337)

The accumulated context is the data plane of every flow. A step output that
overwrites an existing key (including an `initial_input` key) is governed by
`Flow.on_context_collision` and enforced in exactly one place —
`chainweaver._execution.merge_step_outputs` — for both flow kinds and both
lanes. `compile_flow` additionally emits a `context_collision` warning for
statically detectable overwrites (suppressed under `"overwrite"`). See
[docs/data-integrity.md](../data-integrity.md#context-key-collisions-337).

## Concurrency contract (#336)

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

## Async lane support (#332)

The authoritative per-feature support matrix lives in
[AGENTS.md § Executor and flow semantics](/AGENTS.md#5-executor-and-flow-semantics)
— it is a protected root contract, not duplicated here. Summary of the
mechanism: `execute_flow_async` raises `AsyncLaneUnsupportedError` **before
any step runs** for the features it does not yet honour (conditional
branching, `decision_candidates`), rather than diverging silently. Composed
sub-flows, the step cache, and checkpoint resume run at parity with the sync
lane since #388.

## State transitions (#335)

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

## `DAGFlowStep` conditional branching (#9)

| Field | Type | Default | Meaning |
|-------|------|---------|---------|
| `branches` | `list[ConditionalEdge]` | `[]` | Outgoing guards.  After this step runs, the first `ConditionalEdge` whose `predicate` evaluates truthy against the merged context picks the active downstream path; non-selected immediate dependents are recorded as `StepRecord(skipped=True)`.  Empty list (default) → unconditional fan-out, every dependent runs. |
| `default_next` | `str \| None` | `None` | Fallback `target_step_id` when no `ConditionalEdge` matches.  Only meaningful alongside non-empty `branches`. |

Predicates are evaluated by `chainweaver.contracts.evaluate_predicate`, which parses the string with `ast` and walks the tree by hand — `eval()` is **never** called.  Predicate syntax errors and unsupported AST nodes raise `PredicateSyntaxError` and abort the flow with a synthetic failed `StepRecord`.

Branching is only supported on `step_type="tool"` steps.  Capability steps (`step_type="capability"`) are dispatched through `_execute_capability_step` before `_select_branch` runs, so `branches` / `default_next` are rejected on them at construction (a `DAGFlowStep` validator) rather than silently ignored.

## `FlowStep.tool_name` / `FlowStep.flow_name` (issue #75)

A step runs **either** a tool or a registered sub-flow — exactly one of
`tool_name` / `flow_name` must be set (a model validator enforces this; both
or neither raises `ValidationError`). When `flow_name` is set the executor
recursively runs that flow with the step's resolved inputs, merges its final
output into the parent context, and attaches the sub-flow's `ExecutionResult`
to `StepRecord.sub_result` (nested trace). The composition graph is validated
before execution — cycles, nesting beyond `FlowExecutor(max_composition_depth=...)`
(default 10), and references to unregistered flows raise `FlowCompositionError`.
Composition runs on both lanes: `execute_flow` executes sub-flow steps
recursively, and `execute_flow_async` does the same through
`execute_flow_async` since #388 (see the async support matrix in AGENTS.md §5).
`FlowStep.display_name` returns `tool_name` or `flow_name` for logs/records.
The parent's `deadline` / `cancel_token` are forwarded into the recursive
sub-flow run, so cancellation and the wall-clock budget are honoured between a
sub-flow's own steps (not just at the parent boundary). `ExecutionResult.cost_report.steps_executed`
counts the tool invocations a composed step actually drove (recursively), so
`llm_calls_avoided` is not under-counted for composed flows.

## `FlowStep.input_mapping`

| Value type | Behavior |
|------------|----------|
| `str` (plain key) | Looked up as a top-level key in the accumulated execution context. |
| `str` starting with `/` | An RFC-6901 JSON pointer (#387) resolved against the nested context — e.g. `"/user/address/city"` or `"/items/0/id"`. A miss raises `InputMappingError` naming the pointer. A top-level key that literally starts with `/` is addressed with the `~1` escape (the key `"/raw"` is the pointer `"/~1raw"`). |
| Non-string (`int`, `float`, `bool`, …) | Used as a literal constant. |
| Empty `{}` (default) | The tool receives the full current context. |

Pointer resolution is shared with the contrib `json_pluck` tool via the
dependency-free `chainweaver._pointer` module, so core never imports the
optional `contrib` extra.

## `FlowStep.output_mapping` (issue #386)

Optional `dict[str, str] | None` (default `None`), shaped `{context_key:
output_key}`. Applied to a tool's *validated* outputs before they merge into
the context: only the listed output keys merge, each renamed to its context
key; unlisted keys are pruned. `None` merges every output key verbatim (the
historical behaviour). A mapped `output_key` the tool did not produce raises
`OutputMappingError` (`CW-E041`). The raw outputs are still recorded on
`StepRecord.outputs` — the mapping affects only the context merge. `compile_flow`
understands the remapped keys and statically flags an unknown `output_key`.

## `FlowStep.decision_candidates` (issue #102)

Optional `list[str] | None` (default `None`).  When set together with an
executor-level `decision_callback`, the executor asks the callback to
choose which candidate tool to invoke for this step.  The callback
receives a `DecisionContext` and must return a member of
`decision_candidates`.  Callback failures (raise, or return outside the
list) abort the step with `DecisionCallbackError`.  When
`decision_candidates` is `None` *or* no callback is registered, the
step's static `tool_name` is used — flows stay runnable without the
integration.

## `ExecutionResult` (Pydantic `BaseModel`)

The table is exhaustive (all `ExecutionResult.model_fields`, declaration
order).

| Field | Type | Meaning |
|-------|------|---------|
| `trace_schema_version` | `str` | Library-stamped version of the trace *shape* (#393), currently `"1.1"`. Lets long-lived trace consumers detect shape evolution; distinct from `flow_version`. See [docs/versioning-policy.md](../versioning-policy.md#artifact-schema-versions). |
| `flow_name` | `str` | Name of the executed flow. |
| `flow_version` | `str` | Version of the flow that actually ran (#201); resolves the executor's `version=` selection. |
| `success` | `bool` | `True` when all steps completed without error. |
| `final_output` | `dict \| None` | Merged execution context, or `None` on failure. |
| `execution_log` | `list[StepRecord]` | Ordered per-step records. |
| `trace_id` | `str` | UUID4 hex string assigned at the start of execution; correlates with logs. |
| `started_at` | `datetime` | UTC timestamp when execution began. |
| `ended_at` | `datetime` | UTC timestamp when execution finished. |
| `total_duration_ms` | `float` | Wall-clock duration in ms (via `time.perf_counter`). |
| `cost_report` | `CostReport \| None` | Cost-avoided estimation for the run (#156); `None` when no `CostProfile` is configured. |
| `initial_input` | `dict[str, Any]` | The validated initial input the run started from (empty dict by default). |
| `dry_run` | `bool` | `True` when produced by `execute_flow(dry_run=True)` (#357); a rehearsal trace, never a real run. |

## `StepRecord` (Pydantic `BaseModel`)

The table is exhaustive (all `StepRecord.model_fields`, declaration order).

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
| `retry_count` | `int` | Number of retries the step's `RetryPolicy` actually performed (0 = first attempt succeeded or no policy). |
| `retry_errors` | `list[str]` | Error messages from each failed retry attempt, in order. |
| `skipped` | `bool` | `True` for a DAG dependent not selected by conditional branching (#9); the step did not run. |
| `cached` | `bool` | `True` when the step's output came from the step cache (#127) and `Tool.fn` was skipped. |
| `fallback_used` | `bool` | `True` when `on_error="fallback:<tool_name>"` attempted recovery, including missing or failing fallbacks. |
| `fallback_tool_name` | `str \| None` | The configured fallback target when `fallback_used=True`; `None` otherwise. |
| `flow_name` | `str \| None` | For a composed sub-flow step (#75), the sub-flow that ran; `None` for tool steps. |
| `sub_result` | `ExecutionResult \| None` | For a composed sub-flow step (#75), the nested trace of the sub-flow run; `None` otherwise. |
| `approval` | `ApprovalRecord \| None` | The decision for a step gated by an execution-time approval callback (#356); `None` when no approval was required. |
| `decision` | `DecisionRecord \| None` | The resolved decision for a step with `decision_candidates` (#102, #369); `None` when no decision point applied. |

> **Serialization:** `ExecutionResult` and `StepRecord` are Pydantic models;
> `result.model_dump_json()` and `ExecutionResult.model_validate_json(...)`
> round-trip cleanly. Errors are stored as `error_type` / `error_message`
> strings rather than live `Exception` instances so the trace is fully
> JSON-serializable.

---

## Update triggers

Update this file whenever a field is added to / removed from `Flow`,
`FlowStep`, `DAGFlowStep`, `ExecutionResult`, or `StepRecord`, or when
mapping/collision/concurrency/composition semantics change (same PR — see
[AGENTS.md § Update policy](/AGENTS.md#10-update-policy)). The two tables
marked exhaustive must stay exhaustive.
