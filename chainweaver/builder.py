"""Fluent builder API for constructing :class:`~chainweaver.flow.Flow` objects.

Example::

    from chainweaver import FlowBuilder

    flow = (
        FlowBuilder("double_add_format", "Doubles a number, adds 10, and formats.")
        .step("double", number="number")
        .step("add_ten", value="value")
        .step("format_result", value="value")
        .build()
    )
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel

from chainweaver.exceptions import ChainWeaverError
from chainweaver.flow import Flow, FlowStep


class FlowBuilderError(ChainWeaverError):
    """Raised when :class:`FlowBuilder` cannot produce a valid :class:`Flow`."""

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"FlowBuilder error: {detail}")


class FlowBuilder:
    """Fluent builder for :class:`~chainweaver.flow.Flow` objects.

    Accumulates steps and optional flow-level metadata, then produces a
    validated :class:`~chainweaver.flow.Flow` via :meth:`build`.

    Args:
        name: Unique name for the flow.
        description: Human-readable description of what the flow does.

    Example::

        flow = (
            FlowBuilder("my_flow", "Does something useful.")
            .step("tool_a", x="x")
            .step("tool_b", y="y")
            .with_input_schema(MyInput)
            .with_output_schema(MyOutput)
            .build()
        )
    """

    def __init__(self, name: str, description: str) -> None:
        self._name: str = name
        self._description: str = description
        self._steps: list[FlowStep] = []
        self._input_schema: type[BaseModel] | None = None
        self._output_schema: type[BaseModel] | None = None
        self._trigger_conditions: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # Step accumulation
    # ------------------------------------------------------------------

    def step(self, tool_name: str, **mapping: Any) -> FlowBuilder:
        """Add a step that invokes *tool_name* with the given *mapping*.

        Keyword arguments become the ``input_mapping`` for the step.  String
        values are treated as context-key lookups; non-string values are used
        as literal constants.  Omitting keyword arguments produces an empty
        mapping (full-context passthrough).

        Args:
            tool_name: Name of the tool to invoke.
            **mapping: Keyword arguments that form the ``input_mapping`` dict.

        Returns:
            ``self`` — supports method chaining.
        """
        self._steps.append(FlowStep(tool_name=tool_name, input_mapping=dict(mapping)))
        return self

    def step_from(self, flow_step: FlowStep) -> FlowBuilder:
        """Add a pre-built :class:`~chainweaver.flow.FlowStep`.

        Useful for interop with code that already constructs
        :class:`~chainweaver.flow.FlowStep` objects directly.

        Args:
            flow_step: An already-constructed step to append.

        Returns:
            ``self`` — supports method chaining.
        """
        self._steps.append(flow_step.model_copy())
        return self

    # ------------------------------------------------------------------
    # Schema and metadata
    # ------------------------------------------------------------------

    def with_input_schema(self, schema: type[BaseModel]) -> FlowBuilder:
        """Set the flow-level input schema.

        Args:
            schema: A Pydantic :class:`~pydantic.BaseModel` subclass that the
                executor will use to validate the caller's *initial_input*.

        Returns:
            ``self`` — supports method chaining.
        """
        self._input_schema = schema
        return self

    def with_output_schema(self, schema: type[BaseModel]) -> FlowBuilder:
        """Set the flow-level output schema.

        Args:
            schema: A Pydantic :class:`~pydantic.BaseModel` subclass that the
                executor will use to validate the final merged context.

        Returns:
            ``self`` — supports method chaining.
        """
        self._output_schema = schema
        return self

    def with_trigger(self, conditions: dict[str, Any]) -> FlowBuilder:
        """Set optional trigger conditions (free-form metadata).

        ChainWeaver itself does not evaluate these conditions; they are
        available to higher-level orchestrators.

        Args:
            conditions: Arbitrary key/value metadata.

        Returns:
            ``self`` — supports method chaining.
        """
        self._trigger_conditions = dict(conditions)
        return self

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def build(self) -> Flow:
        """Construct and return a validated :class:`~chainweaver.flow.Flow`.

        This method is non-destructive — it can be called multiple times and
        will return a new :class:`~chainweaver.flow.Flow` instance each time,
        reflecting the builder's current state.

        Raises:
            FlowBuilderError: When *name* or *description* is empty.

        Returns:
            A :class:`~chainweaver.flow.Flow` equivalent to constructing one
            directly with the same arguments.
        """
        if not self._name:
            raise FlowBuilderError("'name' must be a non-empty string.")
        if not self._description:
            raise FlowBuilderError("'description' must be a non-empty string.")

        return Flow(
            name=self._name,
            description=self._description,
            steps=list(self._steps),
            input_schema=self._input_schema,
            output_schema=self._output_schema,
            trigger_conditions=(
                dict(self._trigger_conditions) if self._trigger_conditions is not None else None
            ),
        )
