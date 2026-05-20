# The `@tool` decorator

The `@tool` decorator inspects a function's type hints and auto-generates the Pydantic
input schema. It's the lowest-boilerplate path to a `Tool`.

```python
from chainweaver import tool


@tool
def double(number: int) -> dict:
    """Doubles a number."""
    return {"value": number * 2}
```

The decorator inspects `double`'s parameters and builds a Pydantic `BaseModel` with one
field `number: int`. The function's docstring becomes the tool's `description`. The
returned `Tool` is callable just like one constructed manually:

```python
double.name           # "double"
double.description    # "Doubles a number."
double.input_schema   # auto-generated BaseModel with one int field
```

## Explicit output schemas

`@tool` does not infer output schemas — the return type annotation `-> dict` is a sentinel.
Provide an explicit `output_schema=` kwarg when you need output validation:

```python
from pydantic import BaseModel
from chainweaver import tool


class ValueOutput(BaseModel):
    value: int


@tool(output_schema=ValueOutput)
def double(number: int) -> dict:
    """Doubles a number."""
    return {"value": number * 2}
```

## Overrides

```python
@tool(
    name="double_int",
    description="Doubles an integer.",
    output_schema=ValueOutput,
    timeout_seconds=5.0,
    max_output_size=1024,
)
def double(number: int) -> dict:
    return {"value": number * 2}
```

All `Tool` constructor kwargs flow through (`timeout_seconds`, `max_output_size`,
`schema_version`, `cacheable`).

## Limits

`@tool` cannot infer schemas for parameters with complex types (e.g., nested Pydantic
models, generics). For those, drop down to the explicit `Tool(...)` constructor — see
[Your first flow](first-flow.md).
