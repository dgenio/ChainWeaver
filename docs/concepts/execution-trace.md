# Execution trace

Every `FlowExecutor.execute_flow` call produces an `ExecutionResult` with a structured
trace. The trace is a Pydantic model — JSON-serializable, replay-compatible, and stable
across releases.

## `ExecutionResult`

| Field | Type | Meaning |
|---|---|---|
| `flow_name` | `str` | Name of the executed flow. |
| `success` | `bool` | `True` when all steps completed without error. |
| `final_output` | `dict \| None` | Merged execution context, or `None` on failure. |
| `execution_log` | `list[StepRecord]` | Ordered per-step records. |
| `trace_id` | `str` | UUID4 hex assigned at execution start. |
| `started_at` / `ended_at` | `datetime` | UTC timestamps. |
| `total_duration_ms` | `float` | Wall-clock duration in milliseconds. |

## `StepRecord`

| Field | Type | Meaning |
|---|---|---|
| `step_index` | `int` | Zero-based position (`-1` for input-validation record). |
| `tool_name` | `str` | Tool invoked. |
| `inputs` | `dict` | Validated inputs passed to the tool. |
| `outputs` | `dict \| None` | Validated outputs, or `None` on failure. |
| `error_type` | `str \| None` | Exception class name on failure. |
| `error_message` | `str \| None` | Human-readable error message on failure. |
| `success` | `bool` | Step status. |
| `started_at` / `ended_at` | `datetime` | UTC timestamps. |
| `duration_ms` | `float` | Wall-clock duration in milliseconds. |

## Serialization

```python
result = executor.execute_flow("calc", {"number": 5})

# To JSON
payload = result.model_dump_json(indent=2)

# Back from JSON
from chainweaver import ExecutionResult

round_tripped = ExecutionResult.model_validate_json(payload)
```

Errors are stored as `error_type` / `error_message` strings rather than live `Exception`
instances so the trace round-trips cleanly through any JSON pipeline.

## Replay

A serialized trace can be re-executed:

```python
from chainweaver import ReplayMode

replay = executor.replay_flow(
    trace=result,
    mode=ReplayMode.STRICT,  # or VERIFY, SKIP_VALIDATION
)
assert replay.matches  # outputs identical to recorded trace
```

`ReplayMode.STRICT` requires byte-identical step outputs. `VERIFY` only checks structural
shape. `SKIP_VALIDATION` runs the trace without comparison (useful for re-running on a
new tool implementation).

## Out-of-band capture

If you have agent traffic that does **not** go through `FlowExecutor` (ad-hoc tool calls
made by an LLM-driven loop, for instance), use `TraceRecorder` from
`chainweaver.observation` to capture an `ObservedTrace` manually. The same `ObservedStep`
fields apply; downstream analysis with `ChainAnalyzer` finds promotable patterns.
