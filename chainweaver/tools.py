"""Tool abstraction for ChainWeaver.

A :class:`Tool` wraps a plain Python callable together with Pydantic models
that describe its input and output contract.  Tools are the atomic units of
work inside a :class:`~chainweaver.flow.Flow`.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel


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
    ) -> None:
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.output_schema = output_schema
        self.fn = fn

    def run(self, raw_inputs: dict[str, Any]) -> dict[str, Any]:
        """Validate *raw_inputs*, execute the tool, and validate the output.

        Args:
            raw_inputs: A dictionary that will be coerced into *input_schema*.

        Returns:
            A validated dictionary conforming to *output_schema*.

        Raises:
            pydantic.ValidationError: When *raw_inputs* or the callable's
                return value do not match the declared schemas.
        """
        validated_input = self.input_schema.model_validate(raw_inputs)
        raw_output = self.fn(validated_input)
        validated_output = self.output_schema.model_validate(raw_output)
        return validated_output.model_dump()

    def __call__(self, **kwargs: Any) -> dict[str, Any]:
        """Call the tool directly with keyword arguments.

        Validates *kwargs* against *input_schema*, invokes the underlying
        callable, and returns the raw ``dict`` result **without** output schema
        validation.  This makes a :class:`Tool` usable as a plain function in
        addition to being usable inside a :class:`~chainweaver.flow.Flow`.

        For full schema-validated execution (including output validation), use
        :meth:`run` directly or let :class:`~chainweaver.executor.FlowExecutor`
        invoke the tool inside a flow.

        Args:
            **kwargs: Keyword arguments matching the fields of *input_schema*.

        Returns:
            The ``dict`` returned by the underlying callable.
        """
        validated_input = self.input_schema(**kwargs)
        return self.fn(validated_input)

    def __repr__(self) -> str:
        return f"Tool(name={self.name!r})"
