# Error table

Every exception ChainWeaver raises is typed and inherits from `ChainWeaverError`. Each
carries context attributes (e.g. `tool_name`, `step_index`, `detail`) so callers can
inspect failures programmatically rather than parsing strings.

## Stable diagnostic codes

Each exception class carries a stable `code` (e.g. `CW-E006`), exposed as a class
attribute and on `exc.code`. The CLI prefixes it on error output
(`chainweaver: [CW-E006] …`) and failing `StepRecord`s carry it as
`error_code`, so failures are greppable in logs/issues and `--format json`
consumers can branch on the code instead of string-matching messages. Codes are
**append-only**: once released they are never renumbered or reused. The
`tests/test_error_codes.py` consistency check fails if any public exception
lacks a code, a code is duplicated, or a code is missing from this table.

| Code | Exception | When it is raised |
|---|---|---|
| `CW-E000` | `ChainWeaverError` | Base class for every error below. |
| `CW-E001` | `ToolNotFoundError` | A flow step references an unregistered tool. |
| `CW-E002` | `FlowNotFoundError` | The requested flow (and optionally a specific version) is not registered. |
| `CW-E003` | `FlowAlreadyExistsError` | A registration would overwrite an existing `(name, version)` without `overwrite=True`. |
| `CW-E004` | `SchemaValidationError` | Input or output failed Pydantic validation at a step boundary. |
| `CW-E005` | `InputMappingError` | A step's `input_mapping` references a context key that does not exist. |
| `CW-E006` | `FlowExecutionError` | A tool callable raised an unexpected exception during execution. |
| `CW-E007` | `ToolDefinitionError` | The `@tool` decorator (or `Tool.from_flow`) cannot construct a tool from the given inputs. |
| `CW-E008` | `ToolTimeoutError` | A `Tool` with `timeout_seconds` set exceeded the configured wall-clock cap. |
| `CW-E009` | `ToolOutputSizeError` | A `Tool` with `max_output_size` set returned output larger than the configured cap. |
| `CW-E010` | `DAGDefinitionError` | A `DAGFlow` has a cycle, a duplicate `step_id`, or an unknown dependency. The `reason` attribute is `"duplicate_step_id"`, `"unknown_dependency"`, or `"cycle"`. |
| `CW-E011` | `FlowStatusError` | Execution attempted on a flow whose status is not `ACTIVE` (without `force=True`). |
| `CW-E012` | `FlowCancelledError` | A `deadline` passed or a `CancellationToken` was cancelled at a step boundary. Carries `step_index`, the partial `result`, and `deadline_exceeded` / `token_cancelled` flags. |
| `CW-E013` | `ContextKeyCollisionError` | A step output collides with an existing context key under `on_context_collision="error"`. |
| `CW-E014` | `AsyncLaneUnsupportedError` | `execute_flow_async` was given a flow using features the async lane does not support (branching, `decision_candidates`, composed sub-flows). |
| `CW-E015` | `FlowCompositionError` | A composed flow's sub-flow references form a cycle, exceed `max_composition_depth`, or point to an unregistered flow. The `reason` attribute is `"cycle"`, `"max_depth_exceeded"`, or `"unknown_flow"`. |
| `CW-E016` | `InvalidFlowVersionError` | A flow's `version` field is not a valid PEP 440 string. |
| `CW-E017` | `FlowSerializationError` | A `.flow.yaml` / `.flow.json` file is malformed, carries an incompatible `format_version`, or references an unresolvable class. |
| `CW-E018` | `CheckpointDriftError` | A `resume_flow` call detected schema drift since the snapshot was written. |
| `CW-E019` | `CheckpointerNotConfiguredError` | `resume_flow` was called on an executor without a configured checkpointer. |
| `CW-E020` | `CheckpointNotFoundError` | `resume_flow` could not locate the snapshot for the given `trace_id`. |
| `CW-E021` | `CheckpointVersionError` | A snapshot's `snapshot_version` has an incompatible MAJOR relative to the running library. |
| `CW-E022` | `PluginDiscoveryError` | An entry-point plugin loader failed irrecoverably under `strict=True`. |
| `CW-E023` | `ContribError` | A first-party `chainweaver.contrib.tools` tool hit a deterministic contract violation. |
| `CW-E024` | `MCPError` | Base class for the `chainweaver.mcp` adapter / server error family. |
| `CW-E025` | `MCPSchemaConversionError` | An MCP tool's JSON Schema cannot be projected to a Pydantic model. |
| `CW-E026` | `MCPToolInvocationError` | An MCP tool invocation returned `isError=True` or the SDK call raised. |
| `CW-E027` | `MCPMetadataError` | Server-provided MCP tool metadata violates the configured `MetadataPolicy`. |
| `CW-E028` | `MCPSchemaDriftError` | A discovered MCP tool schema no longer matches its pin under `on_drift="error"`. |
| `CW-E029` | `ApprovalDeniedError` | An execution-time `ApprovalCallback` denied (or failed to approve) a gated step. |
| `CW-E030` | `SafetyCeilingError` | A step's side-effect level exceeds the executor's configured `max_side_effect_level`. |
| `CW-E031` | `DecisionCallbackError` | A `DecisionCallback` raised or returned a tool outside the step's `decision_candidates`. |
| `CW-E032` | `KernelInvocationError` | A `KernelBackedExecutor` could not dispatch a capability step. |
| `CW-E033` | `CostProfileError` | A cost estimate was requested for an unknown `(provider, model)` pair. |
| `CW-E034` | `OfflineLLMError` | An offline, build-time LLM proposer could not use a completion (blank/invalid/malformed). |
| `CW-E035` | `AgentTraceImportError` | A coding-agent tool-use trace (JSONL) could not be imported. |
| `CW-E036` | `PredicateSyntaxError` | A conditional-branch predicate could not be parsed or evaluated. |
| `CW-E037` | `FlowBuilderError` | `FlowBuilder.build()` was called without a name or description. |
| `CW-E038` | `FuzzConfigError` | A fuzzing run could not be configured (no properties, `runs < 1`, no input source). |
| `CW-E039` | `AttestationInputError` | The attestation input generator cannot synthesize a value for a schema field. |
| `CW-E040` | `FixtureStaleError` | A `record_then_replay` invocation could not be matched to a recording. |
| `CW-E041` | `OutputMappingError` | A step's `output_mapping` references an output key the tool did not produce. |
| `CW-E042` | `PromptBudgetExceededError` | An offline proposer prompt exceeded its configured `PromptBudget.max_tokens` under `overflow="error"`. |
| `CW-E043` | `LLMProviderError` | An optional `chainweaver.integrations.llm_*` provider adapter could not complete an LLM call (retries exhausted, timeout, or unusable response). |
| `CW-E044` | `LLMBudgetExceededError` | A provider adapter would exceed its configured `max_calls` / `max_cost_usd` ceiling. |
| `CW-E045` | `FlowAuthenticationError` | A `FlowServer` authenticator returned `None` or raised; the call is refused before dispatch. |
| `CW-E046` | `RateLimitExceededError` | A `FlowServer` rate limiter declined the call. |
| `CW-E047` | `FlowAuthorizationError` | A `FlowServer` authorization callback denied the call (client-safe reason code only). |
| `CW-E048` | `OpenCodeAdapterError` | An OpenCode plugin payload could not be normalized into a trace event, or a flow name has no name-safe characters. |
| `CW-E049` | `DecisionTimeoutError` | A decision callback exceeded the `DecisionPolicy.timeout_s` budget while `on_timeout="error"` was in effect. |
| `CW-E050` | `DecisionBudgetExceededError` | A flow exceeded its `DecisionPolicy.max_decisions_per_flow` budget. |
| `CW-E051` | `SchemaRefPolicyError` | The active schema-ref policy rejected a `"module:qualname"` ref's module path before importing it (`set_schema_ref_policy` / `SchemaRefAllowlist`). |

## Catching strategy

For most application code:

```python
from chainweaver.exceptions import ChainWeaverError

try:
    result = executor.execute_flow(name, payload)
except ChainWeaverError as exc:
    log.exception("Flow %s failed", name, extra={"detail": getattr(exc, "detail", None)})
    raise
```

For drift-aware governance, catch `CheckpointDriftError` separately — it is the only
error that indicates "the snapshot is intact but the world changed underneath it".
