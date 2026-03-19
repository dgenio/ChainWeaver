"""Decorator for zero-boilerplate tool definition.

The :func:`tool` decorator creates a :class:`~chainweaver.tools.Tool` from a
type-annotated Python function, eliminating the need to manually define
Pydantic input/output schemas and the ``Tool()`` constructor call.

Example::

    from chainweaver import tool

    class ValueOutput(BaseModel):
        value: int

    @tool(description="Doubles a number.")
    def double(number: int) -> ValueOutput:
        return {"value": number * 2}
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
    ) -> None:
        super().__init__(
            name=name,
            description=description,
            input_schema=input_schema,
            output_schema=output_schema,
            fn=fn,
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

    # -- Validate return type -----------------------------------------------
    return_type = hints.get("return")
    if return_type is None:
        raise ToolDefinitionError(
            fn.__name__,
            "Missing a return type annotation. "
            "The return type must be a BaseModel subclass. "
            "Use the explicit Tool() constructor for functions without full type hints.",
        )

    if not (isinstance(return_type, type) and issubclass(return_type, BaseModel)):
        raise ToolDefinitionError(
            fn.__name__,
            f"Return type must be a BaseModel subclass, got '{return_type}'. "
            f"Use the explicit Tool() constructor for functions without full type hints.",
        )

    output_schema = return_type

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
    def _adapter(inp: Any) -> dict[str, Any]:
        return fn(**inp.model_dump())  # type: ignore[no-any-return]

    return _DecoratedTool(
        original_fn=fn,
        name=tool_name,
        description=tool_description,
        input_schema=input_schema,
        output_schema=output_schema,
        fn=_adapter,
    )


@overload
def tool(fn: Callable[..., Any], /) -> _DecoratedTool: ...


@overload
def tool(
    *,
    name: str | None = ...,
    description: str | None = ...,
) -> Callable[[Callable[..., Any]], _DecoratedTool]: ...


def tool(
    fn: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
) -> _DecoratedTool | Callable[[Callable[..., Any]], _DecoratedTool]:
    """Create a :class:`~chainweaver.tools.Tool` from a type-annotated function.

    Can be used as a bare decorator or as a decorator factory with keyword
    arguments:

    .. code-block:: python

        @tool
        def greet(name: str) -> GreetOutput:
            \"\"\"Say hello.\"\"\"
            return {"message": f"Hello, {name}!"}

        @tool(name="custom_double", description="Doubles a number.")
        def double(number: int) -> ValueOutput:
            return {"value": number * 2}

    Args:
        fn: The function to wrap (used when the decorator is applied without
            parentheses).
        name: Override the tool name.  Defaults to the function name.
        description: Tool description.  Falls back to the function's docstring
            if not provided.

    Returns:
        A :class:`~chainweaver.tools.Tool` that is also directly callable with
        the original function's signature.

    Raises:
        ToolDefinitionError: When type hints are missing or the return type is
            not a :class:`~pydantic.BaseModel` subclass.
    """
    if fn is not None:
        return _build_tool(fn, name=name, description=description)

    def _decorator(fn: Callable[..., Any]) -> _DecoratedTool:
        return _build_tool(fn, name=name, description=description)

    return _decorator
