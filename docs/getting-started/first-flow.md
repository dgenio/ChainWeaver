# Your first flow

This page walks the same example as
[`examples/simple_linear_flow.py`](https://github.com/dgenio/ChainWeaver/blob/main/examples/simple_linear_flow.py).
You'll declare three tools, wire them into a `Flow`, register everything, and run it
through `FlowExecutor` — zero LLM calls.

The expected execution is:

```text
double(5)         → {"value": 10}
add_ten(10)       → {"value": 20}
format_result(20) → {"result": "Final value: 20"}
```

## 1. Declare schemas

```python
from pydantic import BaseModel


class NumberInput(BaseModel):
    number: int


class ValueOutput(BaseModel):
    value: int


class ValueInput(BaseModel):
    value: int


class FormattedOutput(BaseModel):
    result: str
```

## 2. Implement tool functions

Tool callables take a validated Pydantic input and return a plain `dict` compatible with
the declared output schema:

```python
def double_fn(inp: NumberInput) -> dict:
    return {"value": inp.number * 2}


def add_ten_fn(inp: ValueInput) -> dict:
    return {"value": inp.value + 10}


def format_result_fn(inp: ValueInput) -> dict:
    return {"result": f"Final value: {inp.value}"}
```

## 3. Wrap as `Tool` objects

```python
from chainweaver import Tool

double = Tool(
    name="double",
    description="Doubles a number.",
    input_schema=NumberInput,
    output_schema=ValueOutput,
    fn=double_fn,
)
add_ten = Tool(
    name="add_ten",
    description="Adds 10 to the input value.",
    input_schema=ValueInput,
    output_schema=ValueOutput,
    fn=add_ten_fn,
)
format_result = Tool(
    name="format_result",
    description="Formats the value as a string.",
    input_schema=ValueInput,
    output_schema=FormattedOutput,
    fn=format_result_fn,
)
```

## 4. Define the flow

```python
from chainweaver import Flow, FlowStep

flow = Flow(
    name="double_add_format",
    description="Doubles a number, adds 10, and formats the result.",
    steps=[
        FlowStep(tool_name="double", input_mapping={"number": "number"}),
        FlowStep(tool_name="add_ten", input_mapping={"value": "value"}),
        FlowStep(tool_name="format_result", input_mapping={"value": "value"}),
    ],
)
```

`input_mapping` keys are the **target tool's input schema field names**; values are
either context keys (looked up from the accumulated execution context) or literal
constants.

## 5. Register and execute

```python
from chainweaver import FlowExecutor, FlowRegistry

registry = FlowRegistry()
registry.register_flow(flow)

executor = FlowExecutor(registry=registry)
executor.register_tool(double)
executor.register_tool(add_ten)
executor.register_tool(format_result)

result = executor.execute_flow("double_add_format", {"number": 5})

assert result.success
assert result.final_output == {
    "number": 5,
    "value": 20,
    "result": "Final value: 20",
}
```

`result.execution_log` is an ordered list of [`StepRecord`](../concepts/execution-trace.md)
entries — one per step, each carrying inputs, outputs, timing, and status.

## What next

- [The `@tool` decorator](decorator-api.md) — zero-boilerplate tool definition.
- [`FlowBuilder`](flow-builder.md) — fluent flow construction.
- [Cookbook](../cookbook/index.md) — six runnable recipes for common patterns.
