"""LlamaIndex ↔ ChainWeaver bidirectional adapters (issue #82).

Mirror of :mod:`chainweaver.integrations.langchain` for LlamaIndex's
``FunctionTool``.  LlamaIndex tools expose:

- ``metadata.name``, ``metadata.description``
- ``metadata.fn_schema`` — a Pydantic ``BaseModel`` describing inputs.
- ``call(**kwargs)`` — the invocation surface (returns a ``ToolOutput``
  in modern LlamaIndex releases).
- ``fn`` — the underlying Python callable.

We round-trip those four fields.

Optional extra
--------------

This module requires ``llama-index-core>=0.10``.  Install with::

    pip install 'chainweaver[llamaindex]'

The third-party import is guarded so importing this module without
the extra raises a clear :class:`ImportError` instead of a cryptic
``ModuleNotFoundError``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

try:  # Optional dependency.
    from llama_index.core.tools import FunctionTool as _LIFunctionTool
    from llama_index.core.tools import ToolMetadata as _LIToolMetadata
except ImportError as exc:  # pragma: no cover — depends on install layout
    raise ImportError(
        "chainweaver.integrations.llamaindex requires llama-index-core>=0.10. "
        "Install with: pip install 'chainweaver[llamaindex]'."
    ) from exc

from pydantic import BaseModel, create_model

from chainweaver.tools import Tool

if TYPE_CHECKING:  # pragma: no cover — type-only references
    pass


class _LIResult(BaseModel):
    """Default output schema for LlamaIndex tools that return unstructured values."""

    result: str


def from_llamaindex_tool(
    li_tool: _LIFunctionTool,
    *,
    name: str | None = None,
    description: str | None = None,
    output_schema: type[BaseModel] | None = None,
) -> Tool:
    """Convert a LlamaIndex ``FunctionTool`` into a ChainWeaver :class:`Tool`.

    Args:
        li_tool: A LlamaIndex ``FunctionTool`` (or any duck-typed
            object exposing ``metadata`` with ``name``, ``description``,
            ``fn_schema`` plus a ``call(**kwargs)`` / ``fn`` interface).
        name: Override for the resulting tool's name.  Defaults to
            ``li_tool.metadata.name``.
        description: Override for the description.  Defaults to
            ``li_tool.metadata.description``.
        output_schema: Override for the output schema.  When ``None``,
            outputs are wrapped under ``{"result": str(value)}``.

    Returns:
        A ChainWeaver :class:`Tool` whose ``fn`` invokes the underlying
        LlamaIndex callable and validates its output against the
        declared (or default) output schema.
    """
    metadata = getattr(li_tool, "metadata", None)
    if metadata is None:
        raise TypeError(
            "from_llamaindex_tool requires an object with a '.metadata' attribute; "
            f"got {type(li_tool).__name__}."
        )
    tool_name = name if name is not None else metadata.name
    tool_description = (
        description if description is not None else getattr(metadata, "description", "") or ""
    )
    input_schema = _coerce_input_schema(metadata, tool_name=tool_name)
    resolved_output = output_schema if output_schema is not None else _LIResult

    def _fn(inp: BaseModel) -> dict[str, Any]:
        payload = inp.model_dump()
        if hasattr(li_tool, "call"):
            raw = li_tool.call(**payload)
        elif hasattr(li_tool, "fn"):
            raw = li_tool.fn(**payload)
        else:
            raise TypeError(
                f"LlamaIndex tool '{tool_name}' has neither 'call' nor 'fn'; cannot dispatch."
            )
        # LlamaIndex wraps results in a ``ToolOutput`` object with a
        # ``raw_output`` attribute.  Unwrap when present.
        if hasattr(raw, "raw_output"):
            raw = raw.raw_output

        if resolved_output is _LIResult:
            return {"result": raw if isinstance(raw, str) else str(raw)}
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, BaseModel):
            return raw.model_dump()
        fields = list(resolved_output.model_fields)
        if len(fields) == 1:
            return {fields[0]: raw}
        raise TypeError(
            f"LlamaIndex tool '{tool_name}' returned {type(raw).__name__}, "
            f"which cannot be mapped to output schema '{resolved_output.__name__}'."
        )

    return Tool(
        name=tool_name,
        description=tool_description,
        input_schema=input_schema,
        output_schema=resolved_output,
        fn=_fn,
    )


def to_llamaindex_tool(tool: Tool) -> _LIFunctionTool:
    """Convert a ChainWeaver :class:`Tool` into a LlamaIndex ``FunctionTool``.

    The returned ``FunctionTool`` carries:

    - ``metadata.name`` → ``tool.name``
    - ``metadata.description`` → ``tool.description``
    - ``metadata.fn_schema`` → ``tool.input_schema``
    - underlying ``fn`` → ``tool.run`` wrapped so single-field outputs
      are unwrapped to their scalar value (same convention used by the
      LangChain adapter).
    """

    def _call(**kwargs: Any) -> Any:
        out = tool.run(kwargs)
        if len(out) == 1:
            return next(iter(out.values()))
        return out

    metadata = _LIToolMetadata(
        name=tool.name,
        description=tool.description,
        fn_schema=tool.input_schema,
    )
    return _LIFunctionTool(fn=_call, metadata=metadata)


def _coerce_input_schema(metadata: Any, *, tool_name: str) -> type[BaseModel]:
    """Return a Pydantic ``BaseModel`` describing the LlamaIndex tool's inputs."""
    fn_schema = getattr(metadata, "fn_schema", None)
    if isinstance(fn_schema, type) and issubclass(fn_schema, BaseModel):
        return fn_schema
    return create_model(f"{tool_name}_input")
