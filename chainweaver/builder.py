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

from typing import Any, ClassVar

from pydantic import BaseModel

from chainweaver.exceptions import ChainWeaverError
from chainweaver.flow import Flow, FlowStep


class FlowBuilderError(ChainWeaverError):
    """Raised when :class:`FlowBuilder` cannot produce a valid :class:`Flow`."""

    code: ClassVar[str] = "CW-E037"

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(f"FlowBuilder error: {detail}")


class FlowBuilder:
    """Fluent builder for :class:`~chainweaver.flow.Flow` objects.

    Accumulates steps and optional flow-level metadata, then produces a
    validated :class:`~chainweaver.flow.Flow` via :meth:`build`.

    Args:
        name: Optional unique name for the flow.  May also be set via
            :meth:`name`.
        description: Optional human-readable description of what the flow does.
            May also be set via :meth:`description`.

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

    _DEFAULT_VERSION: str = "0.1.0"

    def __init__(self, name: str | None = None, description: str | None = None) -> None:
        self._name: str = name or ""
        self._description: str = description or ""
        self._version: str = self._DEFAULT_VERSION
        self._steps: list[FlowStep] = []
        self._input_schema: type[BaseModel] | None = None
        self._output_schema: type[BaseModel] | None = None
        self._trigger_conditions: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # Step accumulation
    # ------------------------------------------------------------------

    def step(
        self,
        tool_name: str,
        *,
        output_mapping: dict[str, str] | None = None,
        **mapping: Any,
    ) -> FlowBuilder:
        """Add a step that invokes *tool_name* with the given *mapping*.

        Keyword arguments become the ``input_mapping`` for the step.  String
        values are treated as context lookups — a plain key is a top-level
        lookup and a string starting with ``/`` is an RFC-6901 JSON pointer into
        the nested context (issue #387); non-string values are literal
        constants.  Omitting keyword arguments produces an empty mapping
        (full-context passthrough).

        Args:
            tool_name: Name of the tool to invoke.
            output_mapping: Optional ``{context_key: output_key}`` projection
                applied to the tool's outputs before they merge into the context
                (issue #386); ``None`` (the default) merges every output key
                verbatim.
            **mapping: Keyword arguments that form the ``input_mapping`` dict.

        Returns:
            ``self`` — supports method chaining.
        """
        self._steps.append(
            FlowStep(
                tool_name=tool_name,
                input_mapping=dict(mapping),
                output_mapping=output_mapping,
            )
        )
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

    def name(self, value: str) -> FlowBuilder:
        """Set the flow name.

        This compatibility alias supports older fluent examples that start
        with ``FlowBuilder().name("...")``.
        """
        self._name = value
        return self

    def description(self, value: str) -> FlowBuilder:
        """Set the flow description.

        This compatibility alias supports older fluent examples that start
        with ``FlowBuilder().description("...")``.
        """
        self._description = value
        return self

    def version(self, value: str) -> FlowBuilder:
        """Set the flow version.

        Alias for :meth:`with_version` retained for older fluent examples.
        """
        return self.with_version(value)

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

    def with_version(self, version: str) -> FlowBuilder:
        """Set the flow's PEP 440 version string.

        Defaults to ``"0.1.0"`` when not called, matching the
        :class:`Flow` constructor default.

        Args:
            version: A PEP 440-compatible version string (e.g. ``"1.2.0"``).

        Returns:
            ``self`` — supports method chaining.
        """
        self._version = version
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
            version=self._version,
            description=self._description,
            steps=list(self._steps),
            input_schema_ref=(
                Flow.schema_ref_from(self._input_schema)
                if self._input_schema is not None
                else None
            ),
            output_schema_ref=(
                Flow.schema_ref_from(self._output_schema)
                if self._output_schema is not None
                else None
            ),
            trigger_conditions=(
                dict(self._trigger_conditions) if self._trigger_conditions is not None else None
            ),
        )
