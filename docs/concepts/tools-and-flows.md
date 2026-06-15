# Tools and flows

Two domain terms anchor the entire library. Use them consistently — never substitute
"chain" for flow or "function" for tool.

## `Tool`

A `Tool` is a **named, schema-validated callable**. Every tool carries:

| Field | Meaning |
|---|---|
| `name` | Unique identifier (referenced by `FlowStep.tool_name`). |
| `description` | Human-readable summary. Surfaces in agent prompts and exports. |
| `input_schema` | Pydantic `BaseModel` subclass; validates inputs before `fn` runs. |
| `output_schema` | Pydantic `BaseModel` subclass; validates outputs after `fn` returns. |
| `fn` | `Callable[[input_schema], dict]` — the actual logic. |
| `timeout_seconds` | Optional wall-clock cap; raises `ToolTimeoutError` when exceeded. |
| `max_output_size` | Optional cap on output dict size (JSON bytes); raises `ToolOutputSizeError`. |
| `schema_version` | Free-form version string; surfaces in `schema_hash`. |
| `cacheable` | Whether the executor's `StepCache` is allowed to memoize this tool. |

The function signature is fixed: `fn(validated_input: BaseModel) -> dict[str, Any]`.
Tools never receive raw kwargs and never return raw values.

## `Flow`

A `Flow` is a **named, ordered sequence of tool invocations**. Two flow kinds exist:

- **`Flow`** — a linear sequence (`steps: list[FlowStep]`).
- **`DAGFlow`** — a directed acyclic graph (`steps: list[DAGFlowStep]`,
  each declaring `depends_on`); the executor groups steps into topological levels and
  runs each level's steps in parallel.

Both kinds are Pydantic models, serializable to JSON and (with the `yaml` extra) to YAML.

```python
from chainweaver import Flow, FlowStep, DAGFlow, DAGFlowStep

linear = Flow(
    name="etl",
    description="Fetch → validate → store",
    steps=[
        FlowStep(tool_name="fetch", input_mapping={"url": "url"}),
        FlowStep(tool_name="validate", input_mapping={"data": "data"}),
        FlowStep(tool_name="store", input_mapping={"records": "records"}),
    ],
)

graph = DAGFlow(
    name="fanout",
    description="Two sources merged into one sink",
    steps=[
        DAGFlowStep(step_id="src_a", tool_name="fetch_a"),
        DAGFlowStep(step_id="src_b", tool_name="fetch_b"),
        DAGFlowStep(step_id="merge", tool_name="merge", depends_on=["src_a", "src_b"]),
    ],
)
```

## `FlowStep`

| Field | Meaning |
|---|---|
| `tool_name` | Name of the tool to invoke at this step. |
| `input_mapping` | `dict[str, Any]` — see below. |
| `retry_policy` | Optional `RetryPolicy` (delegated to `tenacity`). |
| `on_error` | Error policy: `fail`, `skip`, or `fallback:<tool_name>`. |

### `input_mapping` semantics

| Value type | Behavior |
|---|---|
| `str` | Looked up as a key in the accumulated execution context. |
| Non-string (`int`, `float`, `bool`, …) | Used as a literal constant. |
| Empty `{}` (default) | The tool receives the full current context (use sparingly). |

The accumulated context starts as the `initial_input` dict and grows as each step's
validated outputs are merged in.

### Fallback semantics

`on_error="fallback:<tool_name>"` runs the named fallback after the primary
tool exhausts its attempts. The fallback receives the same resolved input
dictionary that was passed to the primary tool, then `Tool.run` or
`Tool.run_async` validates that dictionary against the fallback's own input
schema before its callable runs.

`compile_flow()` applies the same contract statically: the fallback must be
registered, every mapped target must exist on its input schema, required
fields must be supplied, and mapped types must be compatible. These are
blocking compilation errors because the fallback would deterministically fail
whenever recovery was needed.

In the execution trace, `StepRecord.tool_name` remains the primary tool so a
step keeps one stable identity across runs. `fallback_used=True` records that
recovery was attempted, and `fallback_tool_name` identifies the target. A
fallback schema failure is a `SchemaValidationError` attributed to the
fallback tool.

## `FlowRegistry` and `FlowExecutor`

- `FlowRegistry` is a **multi-version catalogue** of `Flow` definitions. Flows are
  registered by `(name, version)`; the registry tracks lifecycle status
  (`DRAFT`, `ACTIVE`, `DEPRECATED`, `RETIRED`).
- `FlowExecutor` is the **graph runner**. It holds a tool registry and a `FlowRegistry`,
  and exposes `execute_flow`, `stream_flow`, `replay_flow`, `resume_flow`.

Together they form the operational core: define tools once, register many flows that
combine them, execute by `(name, version)`.

## What's deliberately not here

ChainWeaver is not an agent framework. It does not own:

- LLM clients or prompts.
- Plan generation, intent routing, or "what tool next" reasoning.
- Long-running daemons, schedulers, or event loops.

Those concerns belong to the agent that owns the conversation. See
[When ChainWeaver fits](../boundaries.md) for the full fit/non-fit breakdown.
