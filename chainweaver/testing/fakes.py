"""Build permissive :class:`~chainweaver.tools.Tool` instances for tests.

The real :class:`~chainweaver.tools.Tool` constructor demands explicit
Pydantic ``input_schema`` and ``output_schema`` subclasses — the right
contract for production code, but heavy boilerplate for unit tests
whose author just wants to wire up a fixed response::

    runner.fake_tool("fetch", {"data": [1, 2, 3]})
    runner.fake_tool("transform", lambda inp: {"data": [x * 2 for x in inp["data"]]})

:func:`fake_tool` collapses that boilerplate by binding both schemas to
permissive ``extra="allow"`` :class:`~pydantic.BaseModel` shells.  Any
dict round-trips through validation cleanly; the fake never has to
declare its fields.  Fakes default to ``cacheable=False`` so the
executor's :class:`~chainweaver.cache.StepCache` (when configured)
does not memoize their outputs and surprise tests asserting call
counts.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict

from chainweaver.tools import Tool

# Schema shared by every fake tool.  Both input and output use the same
# permissive shell — extra fields are allowed so any dict validates.
# Sharing one class across fakes is intentional: it produces a stable
# ``schema_hash`` for all fakes so a test author can assert hashes
# without worrying about which fake produced them.  Since cache keys
# include ``tool_name``, distinct fakes never collide on the cache.


class _AnyDict(BaseModel):
    """Permissive Pydantic shell used as both input and output schema for fakes."""

    model_config = ConfigDict(extra="allow", arbitrary_types_allowed=True)


# Type aliases that document the two accepted shapes for the fake tool's
# behaviour.  A static dict snapshots the response; a callable receives
# the resolved input as a plain dict (not a BaseModel) for test-author
# ergonomics and returns the response dict.
StaticOutput = dict[str, Any]
DynamicOutput = Callable[[dict[str, Any]], dict[str, Any]]


def fake_tool(
    name: str,
    output: StaticOutput | DynamicOutput,
    *,
    description: str | None = None,
    cacheable: bool = False,
) -> Tool:
    """Return a permissive :class:`~chainweaver.tools.Tool` for tests.

    Args:
        name: Tool name as it appears in :class:`~chainweaver.flow.FlowStep`
            references.
        output: Either a ``dict`` to return verbatim on every call, or a
            ``Callable[[dict], dict]`` that receives the validated inputs
            (as a plain dict — not a Pydantic model — for ergonomic ease)
            and returns the response dict.
        description: Optional description; defaults to a generic
            ``"Fake tool '{name}' for tests."`` so test diffs stay quiet.
        cacheable: Whether the executor's step cache may memoize this
            fake's outputs.  Defaults to ``False`` so tests that assert
            call counts behave intuitively (re-running the same input
            always invokes the fake).  Set to ``True`` to dogfood cache
            semantics.

    Returns:
        A :class:`~chainweaver.tools.Tool` instance ready for
        :meth:`~chainweaver.executor.FlowExecutor.register_tool`.

    Example::

        from chainweaver.testing import fake_tool

        # Static response.
        fetch = fake_tool("fetch", {"data": [1, 2, 3]})

        # Dynamic response — input is a plain dict.
        transform = fake_tool(
            "transform",
            lambda inp: {"data": [x * 2 for x in inp["data"]]},
        )
    """
    tool_description = description if description is not None else f"Fake tool '{name}' for tests."

    if callable(output):
        # Capture the user callable in a local so the closure has a
        # stable reference even if the caller rebinds the name.
        user_fn = output

        def _dynamic_fn(validated_input: BaseModel) -> dict[str, Any]:
            inputs_dict = validated_input.model_dump()
            result = user_fn(inputs_dict)
            return dict(result)

        fn: Callable[[BaseModel], dict[str, Any]] = _dynamic_fn
    else:
        # Snapshot the static dict so later mutation by the caller does
        # not poison subsequent invocations.
        snapshot = dict(output)

        def _static_fn(_validated_input: BaseModel) -> dict[str, Any]:
            return dict(snapshot)

        fn = _static_fn

    return Tool(
        name=name,
        description=tool_description,
        input_schema=_AnyDict,
        output_schema=_AnyDict,
        fn=fn,
        cacheable=cacheable,
    )


__all__ = ["fake_tool"]
