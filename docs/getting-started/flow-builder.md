# `FlowBuilder`

`FlowBuilder` is a fluent API for constructing `Flow` objects. Use it when you'd rather
chain `.step()` calls than build a `list[FlowStep]` literal.

```python
from chainweaver import FlowBuilder

flow = (
    FlowBuilder()
    .name("double_add_format")
    .description("Doubles a number, adds 10, and formats the result.")
    .step("double", input_mapping={"number": "number"})
    .step("add_ten", input_mapping={"value": "value"})
    .step("format_result", input_mapping={"value": "value"})
    .build()
)
```

`.build()` returns a validated `Flow` (the same model
[constructed directly](first-flow.md#4-define-the-flow)). It raises `FlowBuilderError`
if name or description are missing.

## Versioning

```python
flow = (
    FlowBuilder()
    .name("etl")
    .version("1.2.0")
    .description("Extract, validate, store.")
    .step(...)
    .build()
)
```

Versions follow PEP 440. Invalid versions raise `InvalidFlowVersionError` at build time.

## Cross-reference

See `examples/builder_flow.py` for a complete runnable script. For programmatic flow
generation (e.g., from observed traces), the same builder pattern is the cleanest
target.
