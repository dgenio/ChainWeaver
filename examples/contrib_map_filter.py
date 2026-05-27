"""Standard contrib tools: ``map_list`` and ``filter_list`` over sub-flows.

Both factories take a registered sub-flow's name plus an executor
reference; the returned tool dispatches the sub-flow once per list
element.  This is how composition currently flows through
:meth:`Tool.from_flow` without growing native sub-flow support into
:class:`FlowStep` itself.

Run::

    python examples/contrib_map_filter.py
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from chainweaver.contrib.tools import filter_list, map_list
from chainweaver.executor import FlowExecutor
from chainweaver.flow import Flow, FlowStep
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool

# ---------------------------------------------------------------------------
# Schemas + per-element tools
# ---------------------------------------------------------------------------


class _ItemInput(BaseModel):
    item: int


class _DoubleOutput(BaseModel):
    value: int


class _EvenOutput(BaseModel):
    keep: bool


def _double(inp: _ItemInput) -> dict[str, Any]:
    return {"value": inp.item * 2}


def _is_even(inp: _ItemInput) -> dict[str, Any]:
    return {"keep": inp.item % 2 == 0}


# ---------------------------------------------------------------------------
# Wire registry + executor + sub-flows
# ---------------------------------------------------------------------------

registry = FlowRegistry()
registry.register_flow(
    Flow(
        name="double_item",
        version="0.1.0",
        description="Doubles the input item.",
        steps=[FlowStep(tool_name="double", input_mapping={"item": "item"})],
    )
)
registry.register_flow(
    Flow(
        name="is_even",
        version="0.1.0",
        description="Even predicate.",
        steps=[FlowStep(tool_name="is_even", input_mapping={"item": "item"})],
    )
)

executor = FlowExecutor(registry=registry)
executor.register_tool(
    Tool(
        name="double",
        description="Doubles.",
        input_schema=_ItemInput,
        output_schema=_DoubleOutput,
        fn=_double,
    )
)
executor.register_tool(
    Tool(
        name="is_even",
        description="Even predicate.",
        input_schema=_ItemInput,
        output_schema=_EvenOutput,
        fn=_is_even,
    )
)


# ---------------------------------------------------------------------------
# map_list — apply ``double_item`` per element
# ---------------------------------------------------------------------------

doubler = map_list(subflow_name="double_item", executor=executor)
doubled = doubler.run({"items": [1, 2, 3]})
print("doubled =", doubled)
# {'items': [{'item': 1, 'value': 2}, {'item': 2, 'value': 4}, {'item': 3, 'value': 6}]}


# ---------------------------------------------------------------------------
# filter_list — drop elements whose predicate sub-flow returns falsy
# ---------------------------------------------------------------------------

even_only = filter_list(subflow_name="is_even", executor=executor)
filtered = even_only.run({"items": [1, 2, 3, 4, 5]})
print("evens =", filtered)
# {'items': [2, 4]}
