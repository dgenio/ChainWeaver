"""Export a compiled flow to OpenAI / Anthropic / generic-callable shapes.

Demonstrates the three adapters in :mod:`chainweaver.export`:

- :func:`flow_to_openai_function` — emits OpenAI's
  ``{"type": "function", "function": {...}}`` shape.
- :func:`flow_to_anthropic_tool` — emits Anthropic's tool_use shape.
- :func:`flow_to_callable` — wraps the flow as a plain
  ``dict → dict`` Python callable that any framework can consume.

None of these adapters imports the ``openai`` or ``anthropic``
packages — they only produce dicts and Python callables.  Runtime
integration with the upstream clients is the consumer's job.

Run::

    python examples/export_openai_anthropic.py
"""

from __future__ import annotations

import json

from pydantic import BaseModel

from chainweaver.executor import FlowExecutor
from chainweaver.export import (
    flow_to_anthropic_tool,
    flow_to_callable,
    flow_to_openai_function,
)
from chainweaver.flow import Flow, FlowStep
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool

# ---------------------------------------------------------------------------
# Tiny double → format flow
# ---------------------------------------------------------------------------


class _NumberInput(BaseModel):
    number: int


class _ValueOutput(BaseModel):
    value: int


class _FormattedOutput(BaseModel):
    result: str


def _double(inp: _NumberInput) -> dict[str, int]:
    return {"value": inp.number * 2}


def _format(inp: _ValueOutput) -> dict[str, str]:
    return {"result": f"Final value: {inp.value}"}


flow = Flow(
    name="double_and_format",
    version="0.1.0",
    description="Double an integer, then format it for display.",
    steps=[
        FlowStep(tool_name="double", input_mapping={"number": "number"}),
        FlowStep(tool_name="format_result", input_mapping={"value": "value"}),
    ],
)
registry = FlowRegistry()
registry.register_flow(flow)
executor = FlowExecutor(registry=registry)
executor.register_tool(
    Tool(
        name="double",
        description="Doubles a number.",
        input_schema=_NumberInput,
        output_schema=_ValueOutput,
        fn=_double,
    )
)
executor.register_tool(
    Tool(
        name="format_result",
        description="Format the value.",
        input_schema=_ValueOutput,
        output_schema=_FormattedOutput,
        fn=_format,
    )
)


# ---------------------------------------------------------------------------
# OpenAI function-calling shape
# ---------------------------------------------------------------------------

openai_spec = flow_to_openai_function(flow, executor)
print("--- OpenAI tool spec ---")
print(json.dumps(openai_spec, indent=2))


# ---------------------------------------------------------------------------
# Anthropic tool_use shape
# ---------------------------------------------------------------------------

anthropic_spec = flow_to_anthropic_tool(flow, executor)
print("\n--- Anthropic tool spec ---")
print(json.dumps(anthropic_spec, indent=2))


# ---------------------------------------------------------------------------
# Generic ``dict → dict`` callable
# ---------------------------------------------------------------------------

run = flow_to_callable(flow, executor)
print("\n--- Calling the wrapped flow ---")
result = run({"number": 7})
print("result =", result["result"])
