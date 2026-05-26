"""Decorator for zero-boilerplate tool definition.

The :func:`tool` decorator creates a :class:`~chainweaver.tools.Tool` from a
type-annotated Python function, eliminating the need to manually define
Pydantic input/output schemas and the ``Tool()`` constructor call.

Two complementary forms are supported (issue #118):

1. **Annotated return** — type the function's return as a
   :class:`~pydantic.BaseModel` subclass.  The decorator extracts the
   output schema from the annotation::

       class ValueOutput(BaseModel):
           value: int

       @tool(description="Doubles a number.")
       def double(number: int) -> ValueOutput:
           return ValueOutput(value=number * 2)

2. **Explicit ``output_schema=``** — declare the output schema as a
   keyword to the decorator.  The function is then free to type its
   return as ``dict[str, Any]`` (or anything compatible with
   ``output_schema.model_validate``) without triggering a mypy
   ``[return-value]`` error::

       @tool(output_schema=ValueOutput)
       def double(number: int) -> dict[str, Any]:
           return {"value": number * 2}

When both an explicit ``output_schema=`` and a ``BaseModel`` return
annotation are given the explicit kwarg wins; the annotation is used as
a tie-breaker only when ``output_schema`` is omitted.
"""

from __future__ import annotations

import inspect
from collections.abc import Callable
from typing import Any, get_type_hints, overload

from pydantic import BaseModel, create_model

from chainweaver.exceptions import ToolDefinitionError
from chainweaver.tools import Tool


class _DecoratedTool(Tool):
    """A Tool created via the ``@tool`` decorator that is also directly callable.

    Behaves exactly like a :class:`~chainweaver.tools.Tool` but additionally
    supports calling with the original function signature.
    """

    def __init__(
        self,
        *,
        original_fn: Callable[..., Any],
        name: str,
        description: str,
        input_schema: type[BaseModel],
        output_schema: type[BaseModel],
        fn: Callable[[Any], dict[str, Any]],
        timeout_seconds: float | None = None,
        max_output_size: int | None = None,
        schema_version: str = "0.0.0",
        cacheable: bool = True,
    ) -> None:
        super().__init__(
            name=name,
            description=description,
            input_schema=input_schema,
            output_schema=output_schema,
            fn=fn,
            timeout_seconds=timeout_seconds,
            max_output_size=max_output_size,
            schema_version=schema_version,
            cacheable=cacheable,
        )
        self._original_fn = original_fn

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        """Call the original function directly, bypassing schema validation."""
        return self._original_fn(*args, **kwargs)


def _build_tool(
    fn: Callable[..., Any],
    *,
    name: str | None,
    description: str | None,
    output_schema: type[BaseModel] | None,
    timeout_seconds: float | None,
    max_output_size: int | None,
    schema_version: str,
    cacheable: bool,
) -> _DecoratedTool:
    """Build a :class:`_DecoratedTool` from a type-annotated function."""
    tool_name = name if name is not None else fn.__name__
    tool_description = description if description is not None else (fn.__doc__ or "").strip()

    try:
        hints = get_type_hints(fn, include_extras=True)
    except (NameError, TypeError) as exc:
        raise ToolDefinitionError(
            fn.__name__,
            f"Failed to resolve type hints: {exc}. "
            f"Ensure all annotations are importable and any forward references "
            f"are either quoted or resolvable in the tool's module.",
        ) from exc
    sig = inspect.signature(fn)

    # -- Resolve output schema (issue #118) ---------------------------------
    # Explicit ``output_schema=`` wins.  Otherwise, fall back to the
    # function's return annotation, which must be a BaseModel subclass.
    resolved_output_schema: type[BaseModel]
    if output_schema is not None:
        if not (isinstance(output_schema, type) and issubclass(output_schema, BaseModel)):
            raise ToolDefinitionError(
                fn.__name__,
                f"output_schema must be a BaseModel subclass, got '{output_schema!r}'.",
            )
        resolved_output_schema = output_schema
    else:
        return_type = hints.get("return")
        if return_type is None:
            raise ToolDefinitionError(
                fn.__name__,
                "Missing a return type annotation. "
                "Either annotate the return type as a BaseModel subclass "
                "or pass output_schema=... to the decorator.",
            )

        if not (isinstance(return_type, type) and issubclass(return_type, BaseModel)):
            raise ToolDefinitionError(
                fn.__name__,
                f"Return type must be a BaseModel subclass, got '{return_type}'. "
                f"Pass output_schema=... explicitly if the function returns a dict.",
            )

        resolved_output_schema = return_type

    # -- Build input schema fields ------------------------------------------
    fields: dict[str, Any] = {}
    for param_name, param in sig.parameters.items():
        # Positional-only parameters cannot be passed as keyword arguments,
        # but the adapter always calls the function via **kwargs.
        if param.kind is inspect.Parameter.POSITIONAL_ONLY:
            raise ToolDefinitionError(
                fn.__name__,
                "Uses positional-only parameters, "
                "which are not supported by the @tool decorator. "
                "Use the explicit Tool() constructor instead.",
            )

        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            raise ToolDefinitionError(
                fn.__name__,
                "Uses *args or **kwargs, "
                "which cannot be introspected into a schema. "
                "Use the explicit Tool() constructor instead.",
            )

        if param_name not in hints:
            raise ToolDefinitionError(
                fn.__name__,
                f"Parameter '{param_name}' is missing a type annotation. "
                f"Use the explicit Tool() constructor for functions "
                f"without full type hints.",
            )

        param_type = hints[param_name]
        if param.default is inspect.Parameter.empty:
            fields[param_name] = (param_type, ...)
        else:
            fields[param_name] = (param_type, param.default)

    input_schema: type[BaseModel] = create_model(f"{tool_name}_input", **fields)

    # -- Create adapter for Tool.fn signature --------------------------------
    # The adapter accepts a Pydantic model, projects it back to **kwargs
    # for the user's function, and trusts ``Tool.run`` to validate the
    # returned dict against ``resolved_output_schema``.  Callers may
    # return either a dict OR a BaseModel — Pydantic accepts both via
    # ``model_validate`` (see ``Tool.run``).
    def _adapter(inp: Any) -> dict[str, Any]:
        result = fn(**inp.model_dump())
        if isinstance(result, BaseModel):
            return result.model_dump()
        # Trust the caller: ``Tool.run`` re-validates via
        # ``output_schema.model_validate(raw_output)`` so any non-dict
        # / non-BaseModel return is rejected with a clear ValidationError.
        return result  # type: ignore[no-any-return]

    return _DecoratedTool(
        original_fn=fn,
        name=tool_name,
        description=tool_description,
        input_schema=input_schema,
        output_schema=resolved_output_schema,
        fn=_adapter,
        timeout_seconds=timeout_seconds,
        max_output_size=max_output_size,
        schema_version=schema_version,
        cacheable=cacheable,
    )


@overload
def tool(fn: Callable[..., Any], /) -> _DecoratedTool: ...


@overload
def tool(
    *,
    name: str | None = ...,
    description: str | None = ...,
    output_schema: type[BaseModel] | None = ...,
    timeout_seconds: float | None = ...,
    max_output_size: int | None = ...,
    schema_version: str = ...,
    cacheable: bool = ...,
) -> Callable[[Callable[..., Any]], _DecoratedTool]: ...


def tool(
    fn: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
    output_schema: type[BaseModel] | None = None,
    timeout_seconds: float | None = None,
    max_output_size: int | None = None,
    schema_version: str = "0.0.0",
    cacheable: bool = True,
) -> _DecoratedTool | Callable[[Callable[..., Any]], _DecoratedTool]:
    """Create a :class:`~chainweaver.tools.Tool` from a type-annotated function.

    Can be used as a bare decorator or as a decorator factory with keyword
    arguments:

    .. code-block:: python

        @tool
        def greet(name: str) -> GreetOutput:
            \"\"\"Say hello.\"\"\"
            return GreetOutput(message=f"Hello, {name}!")

        @tool(name="custom_double", description="Doubles a number.")
        def double(number: int) -> ValueOutput:
            return ValueOutput(value=number * 2)

        @tool(output_schema=ValueOutput)
        def triple(number: int) -> dict[str, Any]:
            # Returning a dict is mypy-clean when ``output_schema`` is
            # passed explicitly — no ``# type: ignore`` needed.
            return {"value": number * 3}

        @tool(output_schema=ValueOutput, timeout_seconds=5.0)
        def guarded_double(number: int) -> dict[str, int]:
            return {"value": number * 2}

    Args:
        fn: The function to wrap (used when the decorator is applied without
            parentheses).
        name: Override the tool name.  Defaults to the function name.
        description: Tool description.  Falls back to the function's docstring
            if not provided.
        output_schema: Explicit output schema.  When set, the function may
            type its return as ``dict[str, Any]`` (or any other type
            compatible with ``output_schema.model_validate``).  When unset,
            the decorator falls back to the function's return annotation,
            which must be a :class:`~pydantic.BaseModel` subclass.
        timeout_seconds: Optional wall-clock cap passed through to ``Tool``.
        max_output_size: Optional output-size cap passed through to ``Tool``.
        schema_version: Schema version passed through to ``Tool``.
        cacheable: Cache eligibility flag passed through to ``Tool``.

    Returns:
        A :class:`~chainweaver.tools.Tool` that is also directly callable with
        the original function's signature.

    Raises:
        ToolDefinitionError: When type hints are missing, when no output
            schema can be derived, or when the resolved output schema is
            not a :class:`~pydantic.BaseModel` subclass.
    """
    if fn is not None:
        return _build_tool(
            fn,
            name=name,
            description=description,
            output_schema=output_schema,
            timeout_seconds=timeout_seconds,
            max_output_size=max_output_size,
            schema_version=schema_version,
            cacheable=cacheable,
        )

    def _decorator(fn: Callable[..., Any]) -> _DecoratedTool:
        return _build_tool(
            fn,
            name=name,
            description=description,
            output_schema=output_schema,
            timeout_seconds=timeout_seconds,
            max_output_size=max_output_size,
            schema_version=schema_version,
            cacheable=cacheable,
        )

    return _decorator
