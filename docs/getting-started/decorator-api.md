# The `@tool` decorator

The `@tool` decorator inspects a function's type hints and auto-generates the Pydantic
input schema. It's the lowest-boilerplate path to a `Tool`.

```python
from chainweaver import tool
from pydantic import BaseModel


class ValueOutput(BaseModel):
    value: int


@tool
def double(number: int) -> ValueOutput:
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
double.output_schema  # ValueOutput
```

## Explicit output schemas

By default, `@tool` infers the output schema from a `BaseModel` return annotation. If
you prefer a `-> dict` return annotation, provide `output_schema=` explicitly:

```python
from pydantic import BaseModel
from chainweaver import tool


class ValueOutput(BaseModel):
    value: int


@tool(output_schema=ValueOutput)
def double(number: int) -> dict[str, int]:
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
def double(number: int) -> dict[str, int]:
    return {"value": number * 2}
```

The decorator supports the common `Tool` constructor kwargs: `name`, `description`,
`output_schema`, `timeout_seconds`, `max_output_size`, `schema_version`, and `cacheable`.

## Limits

`@tool` rejects positional-only parameters, `*args`, `**kwargs`, and missing parameter
annotations because those cannot be converted into a reliable Pydantic input schema.
For hand-shaped schemas or unusual call signatures, use the explicit `Tool(...)`
constructor — see [Your first flow](first-flow.md).
