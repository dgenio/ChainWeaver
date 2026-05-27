# Error table

Every exception ChainWeaver raises is typed and inherits from `ChainWeaverError`. Each
carries context attributes (e.g. `tool_name`, `step_index`, `detail`) so callers can
inspect failures programmatically rather than parsing strings.

| Exception | When it is raised |
|---|---|
| `ChainWeaverError` | Base class for every error below. |
| `ToolNotFoundError` | A flow step references an unregistered tool. |
| `ToolDefinitionError` | The `@tool` decorator (or `Tool.from_flow`) cannot construct a tool from the given inputs. |
| `ToolTimeoutError` | A `Tool` with `timeout_seconds` set exceeded the configured wall-clock cap. |
| `ToolOutputSizeError` | A `Tool` with `max_output_size` set returned output larger than the configured cap. |
| `FlowNotFoundError` | The requested flow is not registered. |
| `FlowAlreadyExistsError` | A registration would overwrite an existing `(name, version)` without `overwrite=True`. |
| `FlowStatusError` | Execution attempted on a flow whose status is not `ACTIVE` (without `force=True`). |
| `FlowExecutionError` | A tool callable raised an unexpected exception during execution. |
| `FlowSerializationError` | A `.flow.yaml` / `.flow.json` file is malformed or references an unresolvable class. |
| `InvalidFlowVersionError` | A flow's `version` field is not a valid PEP 440 string. |
| `InputMappingError` | A step's `input_mapping` references a context key that does not exist. |
| `SchemaValidationError` | Input or output failed Pydantic validation at a step boundary. |
| `DAGDefinitionError` | A `DAGFlow` has a cycle, a duplicate `step_id`, or an unknown dependency. The `reason` attribute is `"duplicate_step_id"`, `"unknown_dependency"`, or `"cycle"`. |
| `FlowBuilderError` | `FlowBuilder.build()` was called without a name or description. |
| `CheckpointDriftError` | A `resume_flow` call detected schema drift since the snapshot was written. |
| `CheckpointNotFoundError` | `resume_flow` could not locate the snapshot for the given `trace_id`. |
| `CheckpointerNotConfiguredError` | `resume_flow` was called on an executor without a configured checkpointer. |
| `AttestationInputError` | The attestation input generator cannot synthesize a value for a schema field. |

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
