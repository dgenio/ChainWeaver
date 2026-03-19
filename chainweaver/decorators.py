"""Zero-boilerplate ``@tool`` decorator for ChainWeaver.

The :func:`tool` decorator creates a :class:`~chainweaver.tools.Tool` directly
from a type-annotated function, eliminating the need to define separate Pydantic
input/output models and a ``Tool()`` constructor call.

Example::

    import chainweaver
    from pydantic import BaseModel

    class ValueOutput(BaseModel):
        value: int

    @chainweaver.tool(description="Doubles a number.")
    def double(number: int) -> ValueOutput:
        return {"value": number * 2}

    # double is a fully configured Tool instance
    assert double.name == "double"
    # …and still callable as a normal function
    assert double(number=5) == {"value": 10}
"""

from __future__ import annotations

import inspect
import typing
from collections.abc import Callable
from typing import Any, overload

from pydantic import BaseModel, create_model

from chainweaver.exceptions import ToolDecoratorError
from chainweaver.tools import Tool


@overload
def tool(fn: Callable[..., Any]) -> Tool: ...


@overload
def tool(
    fn: None = ...,
    *,
    name: str | None = ...,
    description: str | None = ...,
) -> Callable[[Callable[..., Any]], Tool]: ...


def tool(
    fn: Callable[..., Any] | None = None,
    *,
    name: str | None = None,
    description: str | None = None,
) -> Tool | Callable[[Callable[..., Any]], Tool]:
    """Decorator that creates a :class:`~chainweaver.tools.Tool` from a type-annotated function.

    Can be used with or without arguments:

    .. code-block:: python

        @chainweaver.tool
        def my_tool(x: int) -> MyOutput: ...

        @chainweaver.tool(description="Custom description.", name="renamed")
        def my_tool(x: int) -> MyOutput: ...

    Args:
        fn: The function to decorate.  Provided automatically by Python when
            the decorator is used without parentheses (``@tool``).
        name: Override the tool name.  Defaults to the function name.
        description: Human-readable description.  Falls back to the function's
            docstring, then to an empty string.

    Returns:
        A :class:`~chainweaver.tools.Tool` instance whose :attr:`name`,
        :attr:`input_schema`, and :attr:`output_schema` are derived from the
        function signature.

    Raises:
        :exc:`~chainweaver.exceptions.ToolDecoratorError`: When type hints are
            missing or the return type is not a :class:`pydantic.BaseModel`
            subclass.
    """

    def _build(func: Callable[..., Any]) -> Tool:
        # Resolve type hints — handles 'from __future__ import annotations'.
        try:
            hints = typing.get_type_hints(func)
        except Exception as exc:
            raise ToolDecoratorError(
                func.__name__,
                f"Failed to resolve type hints: {exc}",
            ) from exc

        # ------------------------------------------------------------------ #
        # Output schema — return type annotation must be a BaseModel subclass.
        # ------------------------------------------------------------------ #
        return_type = hints.get("return")
        if return_type is None:
            raise ToolDecoratorError(
                func.__name__,
                "Missing return type annotation. Provide a BaseModel subclass as the return type.",
            )
        if not (isinstance(return_type, type) and issubclass(return_type, BaseModel)):
            raise ToolDecoratorError(
                func.__name__,
                f"Return type must be a BaseModel subclass, got {return_type!r}.",
            )

        # ------------------------------------------------------------------ #
        # Input schema — build dynamically from parameter annotations.
        # ------------------------------------------------------------------ #
        sig = inspect.signature(func)
        fields: dict[str, Any] = {}
        for param_name, param in sig.parameters.items():
            hint = hints.get(param_name)
            if hint is None:
                raise ToolDecoratorError(
                    func.__name__,
                    f"Parameter '{param_name}' has no type annotation.",
                )
            if param.default is inspect.Parameter.empty:
                fields[param_name] = (hint, ...)
            else:
                fields[param_name] = (hint, param.default)

        tool_name = name or func.__name__
        tool_description = description or inspect.getdoc(func) or ""
        # Use func.__qualname__ for the model name to avoid collisions when
        # multiple decorated functions are assigned the same tool name via the
        # name= parameter.
        input_schema = create_model(f"{func.__qualname__}_input", **fields)

        # Adapter: Tool.fn must accept a single BaseModel instance.
        # func is typed as Callable[..., Any]; cast the result so mypy knows
        # we expect a dict[str, Any] at runtime.
        # Note: output validation happens in Tool.run() (used by FlowExecutor).
        # Tool.__call__() returns the raw dict without output schema validation,
        # which is intentional for direct/standalone invocation.
        def _fn(inp: BaseModel) -> dict[str, Any]:
            result: dict[str, Any] = func(**inp.model_dump())
            return result

        return Tool(
            name=tool_name,
            description=tool_description,
            input_schema=input_schema,
            output_schema=return_type,
            fn=_fn,
        )

    if fn is not None:
        return _build(fn)
    return _build
