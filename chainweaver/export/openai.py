"""OpenAI function-calling schema export (issue #25).

Emits the dict shape that OpenAI's chat-completions / responses APIs
accept under the ``tools`` array:

.. code-block:: python

    {
        "type": "function",
        "function": {
            "name": "<flow or tool name>",
            "description": "...",
            "parameters": { ...JSON Schema... },
        },
    }

The schema body is taken from Pydantic v2's ``model_json_schema()`` so
it round-trips with :func:`chainweaver.compat.schema_fingerprint`.
This module imports nothing from the ``openai`` package — runtime
client integration is left to the consumer.
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


def flow_to_openai_function(
    flow: Flow | DAGFlow,
    executor: FlowExecutor,
    *,
    name: str | None = None,
    description: str | None = None,
    input_schema: type[BaseModel] | None = None,
) -> dict[str, Any]:
    """Export *flow* as an OpenAI function-calling tool specification.

    Args:
        flow: The flow to export.
        executor: Executor used to look up the first step's tool when
            no explicit *input_schema* is given.
        name: Override the emitted ``function.name``.  Defaults to ``flow.name``.
        description: Override the emitted ``function.description``.
            Defaults to ``flow.description``.
        input_schema: Override the input Pydantic model.  When ``None``
            the schema is derived from ``flow.input_schema_ref`` first,
            then the first step's tool — same precedence as
            :meth:`Tool.from_flow`.

    Returns:
        A dict matching the OpenAI ``{"type": "function", "function": {...}}``
        shape.  Always carries ``function.parameters`` as a JSON Schema
        object — callers passing this straight into ``client.chat.completions.create``
        don't need to post-process.

    Raises:
        ToolDefinitionError: When the flow has no steps, or when the
            input schema cannot be derived.
    """
    resolved_input = (
        input_schema if input_schema is not None else derive_flow_input_schema(flow, executor)
    )
    return _build_payload(
        name=name if name is not None else flow.name,
        description=description if description is not None else flow.description,
        input_schema=resolved_input,
    )


def tool_to_openai_function(
    tool: Tool,
    *,
    name: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """Export *tool* as an OpenAI function-calling tool specification.

    Args:
        tool: The tool to export.
        name: Override the emitted ``function.name``.  Defaults to ``tool.name``.
        description: Override the emitted ``function.description``.
            Defaults to ``tool.description``.

    Returns:
        A dict matching OpenAI's tool spec — identical shape to the
        flow-level variant, derived from ``tool.input_schema``.
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
    # OpenAI's spec expects ``parameters`` to be an *object* JSON Schema.
    # Pydantic's emitter always produces one for ``BaseModel`` subclasses,
    # but we drop the ``title`` field (informational only) for a cleaner
    # payload — most users would strip it anyway.
    schema.pop("title", None)
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": schema,
        },
    }
