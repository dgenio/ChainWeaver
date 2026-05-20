# Schema validation

Every step boundary in a ChainWeaver flow is **Pydantic-validated** in both directions:

```text
context  ─┐                      ┌─ context (merged)
          ├──► tool.input_schema  ──► fn ──►  tool.output_schema  ──┤
                  (validate)               (validate)
```

If validation fails, the executor raises `SchemaValidationError` with the failing field
and the step index — no partial state is committed.

## Tool boundaries

A tool's `input_schema` and `output_schema` are Pydantic `BaseModel` subclasses. The
executor:

1. Builds the input dict from the step's `input_mapping` and the accumulated context.
2. Calls `input_schema.model_validate(input_dict)` — raises on type mismatches, missing
   required fields, or unknown fields (Pydantic v2 default).
3. Invokes `tool.fn(validated_input)`; expects a `dict`.
4. Calls `output_schema.model_validate(output_dict)` — same guarantees.
5. Merges the validated output back into the context.

## Flow boundaries (optional)

A `Flow` can also declare `input_schema` and `output_schema`:

```python
from chainweaver import Flow

flow = Flow(
    name="etl",
    description="...",
    steps=[...],
    input_schema_ref=Flow.schema_ref_from(InitialInput),
    output_schema_ref=Flow.schema_ref_from(FinalOutput),
)
```

When set, the executor validates `initial_input` before the first step and the merged
`final_output` after the last step. Flow-level validation surfaces in the trace as
records with `step_index=-1` (input) and `step_index=len(steps)` (output).

## Schema hashing and drift

Every `Tool` exposes a `schema_hash` derived from its input and output schemas:

```python
tool.schema_hash       # SHA-256 of (input_schema, output_schema, schema_version)
tool.input_schema_hash # input only
tool.output_schema_hash # output only
```

The hash is stable across processes, sorted-keys-canonicalized, and short enough
(16 hex chars) to log. When a tool's schema changes and its `schema_hash` no longer
matches what a registered flow recorded at registration time, `FlowExecutor` surfaces a
`DriftInfo` entry via `get_drift_report()`.

See [Cookbook recipe 5 — Schema drift in CI](../cookbook/05-schema-drift.md) for the
governance pattern.

## Compile-time validation

`compile_flow(flow, tools)` performs **all** of the above checks statically — before any
tool function runs:

- Every `tool_name` in the flow resolves to a registered tool.
- Every `input_mapping` key resolves to either a literal, a key in the initial-input
  schema, or a field in an upstream step's output schema.
- Type compatibility between mapped fields (basic Python types + Pydantic models).
- Optional warning for shadowed context keys.

```python
from chainweaver import compile_flow

result = compile_flow(flow, tools={"double": double_tool, ...})
if result.errors:
    for err in result.errors:
        print(err)
```

The CLI exposes this as `chainweaver validate flows/etl.flow.yaml`.
