"""Deterministic stdlib tools shipped with ChainWeaver (issue #145).

Six curated tools that show up in nearly every adopter's first flow:

================ ===========================================================
Tool             Purpose
================ ===========================================================
``passthrough``  Identity — return the input context unchanged.
``json_pluck``   Extract one value from a nested dict by RFC-6901 pointer.
``json_set``     Set one value in a nested dict by RFC-6901 pointer.
``assert_equal`` Raise :class:`ContribError` when two context keys differ.
``map_list``     Apply a registered sub-flow to each element of a list.
``filter_list``  Drop elements whose predicate sub-flow returns ``False``.
================ ===========================================================

The first four are plain tools created with the
:func:`~chainweaver.decorators.tool` decorator.  ``map_list`` and
``filter_list`` are *factories* — they take a registered sub-flow's
name (and an executor reference) and return a :class:`Tool` whose
``fn`` iterates the sub-flow.  This is a small deviation from a pure
``@tool`` definition because the executor / sub-flow binding can't
exist at module import time; it must be supplied by the caller.

Determinism rules
-----------------

Every tool in this module is deterministic.  No network I/O, no file
I/O, no RNG, no time.  Anything stateful belongs in user code.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

from chainweaver.decorators import tool
from chainweaver.exceptions import ContribError
from chainweaver.tools import Tool

if TYPE_CHECKING:  # pragma: no cover — type-only references
    from chainweaver.executor import FlowExecutor


# ---------------------------------------------------------------------------
# JSON pointer (RFC 6901) — minimal, dependency-free implementation
# ---------------------------------------------------------------------------


def _parse_pointer(pointer: str, *, tool_name: str) -> list[str]:
    """Split a RFC-6901 JSON pointer into its decoded reference tokens.

    Tokens are decoded per the spec: ``~1`` → ``/``, ``~0`` → ``~``,
    in that order.  An empty pointer ``""`` refers to the whole
    document and yields ``[]``.

    Raises:
        ContribError: When *pointer* does not start with ``"/"`` (the
            only legal form for a non-empty pointer).
    """
    if pointer == "":
        return []
    if not pointer.startswith("/"):
        raise ContribError(
            tool_name,
            f"JSON pointer '{pointer}' must start with '/' (RFC 6901)",
        )
    # Strip the leading "/" before splitting so ``"/"`` yields ``[""]``
    # (the root child whose key is the empty string — a legal RFC-6901
    # token, even if rare).
    raw_tokens = pointer[1:].split("/")
    return [t.replace("~1", "/").replace("~0", "~") for t in raw_tokens]


def _pointer_get(data: Any, pointer: str, *, tool_name: str) -> Any:
    """Resolve *pointer* against *data*, returning the referenced value.

    Walks ``dict`` and ``list`` shapes per RFC 6901.  Missing keys,
    out-of-range list indices, and non-integer tokens on a list raise
    :class:`ContribError` rather than ``KeyError`` / ``IndexError`` so
    callers can match on a single ChainWeaver exception type.
    """
    tokens = _parse_pointer(pointer, tool_name=tool_name)
    current: Any = data
    for idx, token in enumerate(tokens):
        path = "/" + "/".join(tokens[: idx + 1])
        if isinstance(current, dict):
            if token not in current:
                raise ContribError(tool_name, f"JSON pointer '{path}' not found")
            current = current[token]
        elif isinstance(current, list):
            try:
                position = int(token)
            except ValueError as exc:
                raise ContribError(
                    tool_name,
                    f"JSON pointer '{path}' addresses a list but token "
                    f"'{token}' is not an integer",
                ) from exc
            if position < 0 or position >= len(current):
                raise ContribError(
                    tool_name,
                    f"JSON pointer '{path}' out of range for list of length {len(current)}",
                )
            current = current[position]
        else:
            raise ContribError(
                tool_name,
                f"JSON pointer '{path}' cannot descend into {type(current).__name__}",
            )
    return current


def _pointer_set(
    data: dict[str, Any],
    pointer: str,
    value: Any,
    *,
    tool_name: str,
) -> dict[str, Any]:
    """Return a *new* dict with *value* set at *pointer*, leaving *data* unchanged.

    Walks intermediate ``dict`` containers, creating them on demand
    when a token is missing.  Lists may be addressed but not extended
    — writing to an out-of-range list index raises :class:`ContribError`.

    The root document is required to be a ``dict`` (the input contract
    of every :class:`Tool` in ChainWeaver), so an empty pointer would
    replace the whole document and is forbidden — callers should use
    a top-level key instead.
    """
    tokens = _parse_pointer(pointer, tool_name=tool_name)
    if not tokens:
        raise ContribError(
            tool_name,
            "JSON pointer '' (root) cannot be set; use a top-level key",
        )

    # Shallow-copy along the write path so we do not mutate the caller's
    # input.  Every container we descend into is freshly copied; siblings
    # remain shared.  This matches the immutability story implicit in
    # ChainWeaver's step-cache invariants.
    root = dict(data)
    current: Any = root
    for token in tokens[:-1]:
        if isinstance(current, dict):
            child = current.get(token)
            if isinstance(child, dict):
                child = dict(child)
            elif isinstance(child, list):
                child = list(child)
            else:
                child = {}
            current[token] = child
            current = child
        elif isinstance(current, list):
            try:
                position = int(token)
            except ValueError as exc:
                raise ContribError(tool_name, f"List index '{token}' is not an integer") from exc
            if position < 0 or position >= len(current):
                raise ContribError(
                    tool_name,
                    f"List index {position} out of range for length {len(current)}",
                )
            entry = current[position]
            if isinstance(entry, dict):
                entry = dict(entry)
            elif isinstance(entry, list):
                entry = list(entry)
            current[position] = entry
            current = entry
        else:
            raise ContribError(
                tool_name,
                f"Cannot descend into {type(current).__name__} while setting '{pointer}'",
            )

    last = tokens[-1]
    if isinstance(current, dict):
        current[last] = value
    elif isinstance(current, list):
        try:
            position = int(last)
        except ValueError as exc:
            raise ContribError(tool_name, f"List index '{last}' is not an integer") from exc
        if position < 0 or position >= len(current):
            raise ContribError(
                tool_name,
                f"List index {position} out of range for length {len(current)}",
            )
        current[position] = value
    else:
        raise ContribError(
            tool_name,
            f"Cannot set final token '{last}' on {type(current).__name__}",
        )
    return root


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class _PassthroughInput(BaseModel):
    """Identity input — any JSON-compatible payload is accepted."""

    data: dict[str, Any] = Field(default_factory=dict)


class _PassthroughOutput(BaseModel):
    """Identity output — the same payload, unchanged."""

    data: dict[str, Any] = Field(default_factory=dict)


class _PluckInput(BaseModel):
    data: dict[str, Any]
    pointer: str = Field(description="RFC-6901 JSON pointer; ``''`` yields the whole document.")


class _PluckOutput(BaseModel):
    value: Any


class _SetInput(BaseModel):
    data: dict[str, Any]
    pointer: str = Field(description="RFC-6901 JSON pointer; root ``''`` is forbidden.")
    value: Any


class _SetOutput(BaseModel):
    data: dict[str, Any]


class _AssertEqualInput(BaseModel):
    left: Any
    right: Any


class _AssertEqualOutput(BaseModel):
    equal: bool


class _MapListInput(BaseModel):
    items: list[Any]


class _MapListOutput(BaseModel):
    items: list[Any]


class _FilterListInput(BaseModel):
    items: list[Any]


class _FilterListOutput(BaseModel):
    items: list[Any]


# ---------------------------------------------------------------------------
# Tools — the four pure tools
# ---------------------------------------------------------------------------


@tool(description="Identity tool — return the input context unchanged.")
def passthrough(data: dict[str, Any]) -> _PassthroughOutput:
    """Return *data* unchanged.

    Useful as a no-op step in DAG topologies, as a placeholder during
    flow scaffolding, or as a sentinel ``Tool`` in tests.
    """
    return _PassthroughOutput(data=data)


@tool(description="Extract one value from a nested dict by RFC-6901 JSON pointer.")
def json_pluck(data: dict[str, Any], pointer: str) -> _PluckOutput:
    """Resolve *pointer* against *data* and return the referenced value.

    Pointer syntax is RFC 6901: ``"/a/0/b"`` means "key ``a``, index 0,
    key ``b``".  ``"~1"`` is escape for ``/``; ``"~0"`` is escape for
    ``~``.  An empty pointer ``""`` yields the whole document.

    Raises:
        ContribError: When the pointer is malformed, references a
            missing key / out-of-range index, or tries to descend into
            a scalar.
    """
    return _PluckOutput(value=_pointer_get(data, pointer, tool_name="json_pluck"))


@tool(description="Set one value in a nested dict by RFC-6901 JSON pointer (returns a new dict).")
def json_set(data: dict[str, Any], pointer: str, value: Any) -> _SetOutput:
    """Return a new dict with *value* set at *pointer*; *data* is not mutated.

    Intermediate ``dict`` containers are created on demand.  Lists may
    be addressed but not extended — writing to an out-of-range list
    index raises :class:`ContribError`.

    Raises:
        ContribError: For the same reasons as :func:`json_pluck`, plus
            attempts to set the root pointer ``""``.
    """
    return _SetOutput(data=_pointer_set(data, pointer, value, tool_name="json_set"))


@tool(description="Assert that two values are equal; raise ContribError otherwise.")
def assert_equal(left: Any, right: Any) -> _AssertEqualOutput:
    """Return ``{"equal": True}`` when ``left == right``; raise otherwise.

    Useful as a contract check between flow steps — e.g., assert that
    the row count after a transformation matches the row count before
    the transformation.

    Raises:
        ContribError: When ``left != right``, with both values rendered
            in the error message (truncated to 80 chars each to keep
            traces readable).
    """
    if left != right:
        left_repr = repr(left)
        right_repr = repr(right)
        if len(left_repr) > 80:
            left_repr = left_repr[:77] + "..."
        if len(right_repr) > 80:
            right_repr = right_repr[:77] + "..."
        raise ContribError(
            "assert_equal",
            f"values differ: left={left_repr} right={right_repr}",
        )
    return _AssertEqualOutput(equal=True)


# ---------------------------------------------------------------------------
# Tools — the two sub-flow-dispatching factories
# ---------------------------------------------------------------------------


def map_list(
    *,
    subflow_name: str,
    executor: FlowExecutor,
    item_key: str = "item",
    name: str | None = None,
    description: str | None = None,
) -> Tool:
    """Return a :class:`Tool` that applies a registered sub-flow to each list element.

    The returned tool consumes a list of items, dispatches the sub-flow
    once per item, and returns the list of sub-flow outputs.  Each
    sub-flow run receives a one-key context: ``{item_key: <element>}``.

    Args:
        subflow_name: Name of a :class:`~chainweaver.flow.Flow` already
            registered on *executor*'s registry.
        executor: The executor that owns the sub-flow.  Captured by
            reference.
        item_key: The context key used to pass each element to the
            sub-flow.  Defaults to ``"item"``.  Must align with the
            sub-flow's first step's ``input_mapping``.
        name: Optional override for the resulting tool's name.  Defaults
            to ``"map_list[{subflow_name}]"``.
        description: Optional override for the description.

    Returns:
        A :class:`Tool` that the caller can register on the executor
        alongside any other tool.

    Raises:
        ContribError: At call time, when the sub-flow run fails or
            returns no final output.
    """
    resolved_name = name if name is not None else f"map_list[{subflow_name}]"
    resolved_description = (
        description
        if description is not None
        else (f"Apply sub-flow '{subflow_name}' to each element of the input list.")
    )

    def _fn(inp: _MapListInput) -> dict[str, Any]:
        out: list[Any] = []
        for index, item in enumerate(inp.items):
            result = executor.execute_flow(subflow_name, {item_key: item})
            if not result.success or result.final_output is None:
                raise ContribError(
                    resolved_name,
                    f"sub-flow '{subflow_name}' failed on item index {index}",
                )
            out.append(result.final_output)
        return {"items": out}

    return Tool(
        name=resolved_name,
        description=resolved_description,
        input_schema=_MapListInput,
        output_schema=_MapListOutput,
        fn=_fn,
        cacheable=False,
    )


def filter_list(
    *,
    subflow_name: str,
    executor: FlowExecutor,
    item_key: str = "item",
    predicate_key: str = "keep",
    name: str | None = None,
    description: str | None = None,
) -> Tool:
    """Return a :class:`Tool` that drops list elements whose predicate sub-flow returns ``False``.

    Each element is passed to *subflow_name* under ``{item_key: <element>}``.
    The sub-flow's final output must contain a boolean under
    *predicate_key*.  Elements for which the predicate is truthy are
    kept; elements for which it is falsy are dropped.

    Args:
        subflow_name: Name of the predicate sub-flow.
        executor: The executor that owns the sub-flow.
        item_key: Context key for the per-element input.  Defaults to ``"item"``.
        predicate_key: Output key on the sub-flow's final output that
            holds the boolean predicate value.  Defaults to ``"keep"``.
        name: Optional override for the resulting tool's name.
        description: Optional override.

    Returns:
        A :class:`Tool` that the caller can register on the executor.

    Raises:
        ContribError: At call time, when the predicate sub-flow fails,
            returns no final output, or omits *predicate_key*.
    """
    resolved_name = name if name is not None else f"filter_list[{subflow_name}]"
    resolved_description = (
        description
        if description is not None
        else (
            f"Keep elements for which sub-flow '{subflow_name}' returns truthy "
            f"under key '{predicate_key}'."
        )
    )

    def _fn(inp: _FilterListInput) -> dict[str, Any]:
        kept: list[Any] = []
        for index, item in enumerate(inp.items):
            result = executor.execute_flow(subflow_name, {item_key: item})
            if not result.success or result.final_output is None:
                raise ContribError(
                    resolved_name,
                    f"predicate sub-flow '{subflow_name}' failed on item index {index}",
                )
            if predicate_key not in result.final_output:
                raise ContribError(
                    resolved_name,
                    f"predicate sub-flow '{subflow_name}' did not produce key "
                    f"'{predicate_key}' on item index {index}",
                )
            if result.final_output[predicate_key]:
                kept.append(item)
        return {"items": kept}

    return Tool(
        name=resolved_name,
        description=resolved_description,
        input_schema=_FilterListInput,
        output_schema=_FilterListOutput,
        fn=_fn,
        cacheable=False,
    )
