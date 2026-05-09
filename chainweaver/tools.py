"""Tool abstraction for ChainWeaver.

A :class:`Tool` wraps a plain Python callable together with Pydantic models
that describe its input and output contract.  Tools are the atomic units of
work inside a :class:`~chainweaver.flow.Flow`.

Two optional guardrails (issue #43) protect agent-composed flows from
misbehaving tools:

- ``timeout_seconds`` enforces a wall-clock cap on the callable via a
  background thread; on expiry :class:`~chainweaver.exceptions.ToolTimeoutError`
  is raised.  Note that Python threads cannot be forcibly cancelled — a
  tool that ignores its environment will keep running in the background;
  the timeout only protects the *caller* from waiting.
- ``max_output_size`` rejects oversized payloads after measuring the
  UTF-8 encoded JSON length of the raw output dict.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from typing import Any

from pydantic import BaseModel

from chainweaver.exceptions import ToolOutputSizeError, ToolTimeoutError


class Tool:
    """A named, schema-validated callable unit of work.

    Args:
        name: Unique identifier for the tool.  Used when referencing it inside
            a :class:`~chainweaver.flow.FlowStep`.
        description: Human-readable description of what the tool does.
        input_schema: A :class:`pydantic.BaseModel` subclass that defines and
            validates the tool's input.
        output_schema: A :class:`pydantic.BaseModel` subclass that defines and
            validates the tool's output.
        fn: The callable that implements the tool's logic.  It must accept a
            single argument that is an instance of *input_schema* and return a
            ``dict`` that is compatible with *output_schema*.
        timeout_seconds: Optional wall-clock cap (seconds) for ``fn``.  When
            set and exceeded, :class:`~chainweaver.exceptions.ToolTimeoutError`
            is raised.  ``None`` (the default) disables the timeout.
        max_output_size: Optional cap on the raw output dict size, measured
            as the UTF-8 byte length of its JSON serialization.  When set and
            exceeded, :class:`~chainweaver.exceptions.ToolOutputSizeError` is
            raised.  ``None`` (the default) disables the size check.

    Example::

        from pydantic import BaseModel
        from chainweaver.tools import Tool

        class DoubleInput(BaseModel):
            number: int

        class DoubleOutput(BaseModel):
            value: int

        def double(inp: DoubleInput) -> dict:
            return {"value": inp.number * 2}

        tool = Tool(
            name="double",
            description="Doubles a number.",
            input_schema=DoubleInput,
            output_schema=DoubleOutput,
            fn=double,
            timeout_seconds=5.0,
            max_output_size=1024,
        )
    """

    def __init__(
        self,
        *,
        name: str,
        description: str,
        input_schema: type[BaseModel],
        output_schema: type[BaseModel],
        fn: Callable[[Any], dict[str, Any]],
        timeout_seconds: float | None = None,
        max_output_size: int | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.output_schema = output_schema
        self.fn = fn
        self.timeout_seconds = timeout_seconds
        self.max_output_size = max_output_size

    def run(self, raw_inputs: dict[str, Any]) -> dict[str, Any]:
        """Validate *raw_inputs*, execute the tool, and validate the output.

        Args:
            raw_inputs: A dictionary that will be coerced into *input_schema*.

        Returns:
            A validated dictionary conforming to *output_schema*.

        Raises:
            pydantic.ValidationError: When *raw_inputs* or the callable's
                return value do not match the declared schemas.
            ToolTimeoutError: When ``timeout_seconds`` is set and the
                callable does not return in time.
            ToolOutputSizeError: When ``max_output_size`` is set and the raw
                output JSON exceeds the cap.
        """
        validated_input = self.input_schema.model_validate(raw_inputs)
        raw_output = self._call_fn(validated_input)

        if self.max_output_size is not None:
            size = len(json.dumps(raw_output, default=str).encode("utf-8"))
            if size > self.max_output_size:
                raise ToolOutputSizeError(self.name, size, self.max_output_size)

        validated_output = self.output_schema.model_validate(raw_output)
        return validated_output.model_dump()

    def _call_fn(self, validated_input: BaseModel) -> dict[str, Any]:
        """Invoke ``self.fn``, optionally bounded by ``timeout_seconds``."""
        if self.timeout_seconds is None:
            return self.fn(validated_input)

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.fn, validated_input)
            try:
                return future.result(timeout=self.timeout_seconds)
            except FuturesTimeoutError as exc:
                raise ToolTimeoutError(self.name, self.timeout_seconds) from exc

    def __repr__(self) -> str:
        return f"Tool(name={self.name!r})"
