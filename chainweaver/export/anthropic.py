"""Anthropic ``tool_use`` schema export (issue #25).

Emits the dict shape that Anthropic's Messages API accepts in its
``tools`` array:

.. code-block:: python

    {
        "name": "<flow or tool name>",
        "description": "...",
        "input_schema": { ...JSON Schema object... },
    }

Like :mod:`chainweaver.export.openai`, this module imports nothing
from the ``anthropic`` package — runtime client integration is the
consumer's responsibility.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from chainweaver.export._schema import (
    derive_flow_input_schema,
    model_input_schema_json,
)

if TYPE_CHECKING:  # pragma: no cover — type-only references
    from chainweaver.executor import FlowExecutor
    from chainweaver.flow import DAGFlow, Flow
    from chainweaver.tools import Tool


def flow_to_anthropic_tool(
    flow: Flow | DAGFlow,
    executor: FlowExecutor,
    *,
    name: str | None = None,
    description: str | None = None,
    input_schema: type[BaseModel] | None = None,
) -> dict[str, Any]:
    """Export *flow* as an Anthropic ``tool_use`` specification.

    See :func:`chainweaver.export.openai.flow_to_openai_function` for
    parameter semantics — the only difference is the emitted shape.
    """
    resolved_input = (
        input_schema if input_schema is not None else derive_flow_input_schema(flow, executor)
    )
    return _build_payload(
        name=name if name is not None else flow.name,
        description=description if description is not None else flow.description,
        input_schema=resolved_input,
    )


def tool_to_anthropic_tool(
    tool: Tool,
    *,
    name: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """Export *tool* as an Anthropic ``tool_use`` specification.

    See :func:`chainweaver.export.openai.tool_to_openai_function` — the
    only difference is the emitted shape.
    """
    return _build_payload(
        name=name if name is not None else tool.name,
        description=description if description is not None else tool.description,
        input_schema=tool.input_schema,
    )


def _build_payload(
    *,
    name: str,
    description: str,
    input_schema: type[BaseModel],
) -> dict[str, Any]:
    schema = model_input_schema_json(input_schema)
    schema.pop("title", None)
    return {
        "name": name,
        "description": description,
        "input_schema": schema,
    }
