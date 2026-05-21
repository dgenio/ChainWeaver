"""LangChain ↔ ChainWeaver bidirectional adapters (issue #82).

ChainWeaver should act as a *compilation layer* that sits on top of
any tool ecosystem, not compete with it.  This module exposes thin
adapters so users can:

- Pull existing LangChain ``BaseTool`` instances *into* ChainWeaver,
  preserving names, descriptions, Pydantic input schemas, and the
  underlying callable.
- Push ChainWeaver :class:`~chainweaver.tools.Tool` instances *out* to
  LangChain so they can be used inside an existing LangChain agent.

Optional extra
--------------

This module requires ``langchain-core>=0.3`` (Pydantic v2 era).
Install with::

    pip install 'chainweaver[langchain]'

The third-party import is guarded so importing this module without
the extra raises a clear :class:`ImportError` instead of a cryptic
``ModuleNotFoundError`` deep in a conversion call.

Design notes
------------

- LangChain ``BaseTool`` outputs are conventionally strings.  When the
  source LangChain tool does not declare a structured output, we wrap
  the string under a single-key Pydantic ``{"result": str}`` output
  schema.  Consumers that want structured outputs should declare a
  ChainWeaver-side output schema via the ``output_schema=`` override.
- Round-trip is best-effort.  Inputs and the underlying function
  round-trip cleanly; descriptions round-trip; the wrapped-string
  output convention means that emitting back to LangChain unwraps
  the ``"result"`` key when present.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

try:  # Optional dependency.
    from langchain_core.tools import BaseTool as _LCBaseTool
    from langchain_core.tools import StructuredTool as _LCStructuredTool
except ImportError as exc:  # pragma: no cover — depends on install layout
    raise ImportError(
        "chainweaver.integrations.langchain requires langchain-core>=0.3. "
        "Install with: pip install 'chainweaver[langchain]'."
    ) from exc

from pydantic import BaseModel, create_model

from chainweaver.tools import Tool

if TYPE_CHECKING:  # pragma: no cover — type-only references
    from collections.abc import Iterable


class _LCResult(BaseModel):
    """Default output schema used when a LangChain tool returns an unstructured string."""

    result: str


def from_langchain_tool(
    lc_tool: _LCBaseTool,
    *,
    name: str | None = None,
    description: str | None = None,
    output_schema: type[BaseModel] | None = None,
) -> Tool:
    """Convert a LangChain ``BaseTool`` into a ChainWeaver :class:`Tool`.

    The LangChain tool's ``args_schema`` (a Pydantic v2 ``BaseModel``)
    is used as the ChainWeaver tool's ``input_schema``.  LangChain
    tools without an ``args_schema`` get a synthesized empty input
    schema named ``"<tool_name>_input"``.

    Args:
        lc_tool: A LangChain ``BaseTool`` (or any duck-typed object
            exposing ``name``, ``description``, ``args_schema``, and
            ``invoke(input)`` / ``_run(...)``).
        name: Override for the resulting tool's name.  Defaults to
            ``lc_tool.name``.
        description: Override for the description.  Defaults to
            ``lc_tool.description``.
        output_schema: Override for the output schema.  When ``None``
            (the default), the tool is treated as unstructured and the
            adapter wraps its return value under ``{"result": str(value)}``.

    Returns:
        A ChainWeaver :class:`Tool` whose ``fn`` invokes the original
        LangChain callable and validates its output against
        *output_schema* (or the default ``{"result": str}`` model).

    Raises:
        TypeError: When ``lc_tool`` is missing required attributes
            (``name``, ``description``, callable interface).
    """
    if not hasattr(lc_tool, "name") or not hasattr(lc_tool, "description"):
        raise TypeError(
            "from_langchain_tool requires an object with 'name' and 'description' attributes; "
            f"got {type(lc_tool).__name__}."
        )

    tool_name = name if name is not None else lc_tool.name
    tool_description = description if description is not None else lc_tool.description

    input_schema = _coerce_input_schema(lc_tool, tool_name=tool_name)
    resolved_output = output_schema if output_schema is not None else _LCResult

    def _fn(inp: BaseModel) -> dict[str, Any]:
        payload = inp.model_dump()
        # ``BaseTool.invoke`` is the v0.3 public surface; fall back to
        # ``_run(**payload)`` for older / custom subclasses that only
        # define the private method.
        if hasattr(lc_tool, "invoke"):
            raw = lc_tool.invoke(payload)
        elif hasattr(lc_tool, "_run"):
            raw = lc_tool._run(**payload)
        else:
            raise TypeError(
                f"LangChain tool '{tool_name}' has neither 'invoke' nor '_run'; cannot dispatch."
            )

        if resolved_output is _LCResult:
            return {"result": raw if isinstance(raw, str) else str(raw)}
        if isinstance(raw, dict):
            return raw
        if isinstance(raw, BaseModel):
            return raw.model_dump()
        # Single-field output schema with a string field — emit ``{field: raw}``.
        fields = list(resolved_output.model_fields)
        if len(fields) == 1:
            return {fields[0]: raw}
        raise TypeError(
            f"LangChain tool '{tool_name}' returned {type(raw).__name__}, "
            f"which cannot be mapped to output schema '{resolved_output.__name__}'."
        )

    return Tool(
        name=tool_name,
        description=tool_description,
        input_schema=input_schema,
        output_schema=resolved_output,
        fn=_fn,
    )


def to_langchain_tool(tool: Tool) -> _LCStructuredTool:
    """Convert a ChainWeaver :class:`Tool` into a LangChain ``StructuredTool``.

    The returned ``StructuredTool``:

    - Carries ``tool.name`` and ``tool.description``.
    - Uses ``tool.input_schema`` as ``args_schema`` (LangChain v0.3 accepts
      Pydantic v2 models directly).
    - Wraps ``tool.run(...)`` as the underlying callable so input /
      output validation (and ``timeout_seconds`` / ``max_output_size``
      guardrails) still apply.  Single-key dict outputs are unwrapped
      to their scalar value, matching the LangChain convention of
      returning a single value rather than a dict for trivial tools.

    Args:
        tool: The ChainWeaver tool to expose to LangChain.

    Returns:
        A LangChain ``StructuredTool`` ready to be passed to an agent
        executor or any other consumer that accepts ``BaseTool``.
    """

    def _call(**kwargs: Any) -> Any:
        out = tool.run(kwargs)
        # Convention: when the output schema has a single field, return
        # that field's value directly (matches LangChain's typical
        # "tool returns a string" expectation).  Multi-field outputs
        # round-trip as a dict.
        if len(out) == 1:
            return next(iter(out.values()))
        return out

    return _LCStructuredTool.from_function(
        func=_call,
        name=tool.name,
        description=tool.description,
        args_schema=tool.input_schema,
    )


def from_langchain_toolkit(toolkit: Any) -> list[Tool]:
    """Convert every tool in a LangChain toolkit into ChainWeaver tools.

    Most LangChain toolkits expose a ``.get_tools()`` method returning
    a list of ``BaseTool`` instances.  This helper iterates over that
    list and applies :func:`from_langchain_tool` to each, returning a
    flat list of ChainWeaver tools — typically the next step is to
    register them on a :class:`~chainweaver.executor.FlowExecutor`.

    Args:
        toolkit: Anything with a ``.get_tools()`` method that returns
            an iterable of ``BaseTool`` instances.

    Returns:
        A list of converted :class:`Tool` instances.

    Raises:
        TypeError: When ``toolkit`` does not expose ``.get_tools()``.
    """
    if not hasattr(toolkit, "get_tools"):
        raise TypeError(
            f"from_langchain_toolkit requires an object with a 'get_tools()' method; "
            f"got {type(toolkit).__name__}."
        )
    lc_tools: Iterable[_LCBaseTool] = toolkit.get_tools()
    return [from_langchain_tool(t) for t in lc_tools]


def _coerce_input_schema(lc_tool: _LCBaseTool, *, tool_name: str) -> type[BaseModel]:
    """Return a Pydantic ``BaseModel`` describing *lc_tool*'s inputs.

    Reads ``lc_tool.args_schema`` when present; synthesizes an empty
    model when missing so the resulting ChainWeaver tool still has a
    well-defined input schema (an empty object passes ``model_validate({})``).
    """
    args_schema = getattr(lc_tool, "args_schema", None)
    if isinstance(args_schema, type) and issubclass(args_schema, BaseModel):
        return args_schema
    # No declared schema; synthesize an empty one so the ChainWeaver
    # Tool still has a valid Pydantic model on its input boundary.
    return create_model(f"{tool_name}_input")
