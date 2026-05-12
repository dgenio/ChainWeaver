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

``Tool.from_flow`` (issue #24) wraps a registered :class:`~chainweaver.flow.Flow`
or :class:`~chainweaver.flow.DAGFlow` as a single :class:`Tool` whose
``fn`` delegates back to a :class:`~chainweaver.executor.FlowExecutor`.  This
collapses an N-step compiled flow into one tool-shaped capability that can be
composed into other flows, exposed to external frameworks (OpenAI/Anthropic
function schemas, MCP servers), or registered in a contextweaver catalog.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from functools import cached_property
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from chainweaver.compat import schema_fingerprint
from chainweaver.exceptions import FlowExecutionError, ToolOutputSizeError, ToolTimeoutError
from chainweaver.flow import DAGFlow, DAGFlowStep, Flow, FlowStep

if TYPE_CHECKING:
    from chainweaver.executor import FlowExecutor


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
        schema_version: str = "0.0.0",
    ) -> None:
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.output_schema = output_schema
        self.fn = fn
        self.timeout_seconds = timeout_seconds
        self.max_output_size = max_output_size
        self.schema_version = schema_version

    @cached_property
    def input_schema_hash(self) -> str:
        """SHA-256 fingerprint of the input schema (cached per instance)."""
        return schema_fingerprint(self.input_schema)

    @cached_property
    def output_schema_hash(self) -> str:
        """SHA-256 fingerprint of the output schema (cached per instance)."""
        return schema_fingerprint(self.output_schema)

    @cached_property
    def schema_hash(self) -> str:
        """Combined hash of input + output schemas (cached per instance)."""
        combined = self.input_schema_hash + self.output_schema_hash
        return hashlib.sha256(combined.encode()).hexdigest()[:16]

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

    # ------------------------------------------------------------------
    # Flow-as-Tool adapter (issue #24)
    # ------------------------------------------------------------------

    @classmethod
    def from_flow(
        cls,
        flow: Flow | DAGFlow,
        executor: FlowExecutor,
        *,
        name: str | None = None,
        description: str | None = None,
        input_schema: type[BaseModel] | None = None,
        output_schema: type[BaseModel] | None = None,
    ) -> Tool:
        """Wrap a registered flow as a :class:`Tool` (issue #24).

        The returned tool behaves like any other ``Tool``: its ``fn``
        validates inputs against the derived ``input_schema``, dispatches
        the flow through *executor*, and returns the validated final
        output.  This makes a compiled flow composable as a step inside
        another flow, or exportable as a single capability to external
        consumers (OpenAI / Anthropic / MCP / weaver-spec).

        Schema derivation prefers, in order:

        1. The explicit ``input_schema`` / ``output_schema`` keyword overrides.
        2. The flow's own ``input_schema_ref`` / ``output_schema_ref`` (when set).
        3. The first step's tool's ``input_schema`` (for inputs) and the
           last step's tool's ``output_schema`` (for outputs).  For a
           :class:`DAGFlow`, "last step" means the unique sink node; if
           the DAG has multiple sinks, an ``output_schema`` override is
           required.

        Args:
            flow: A :class:`Flow` or :class:`DAGFlow` whose steps reference
                tools registered on *executor*.  The flow itself does not
                need to be registered on *executor*'s registry; the
                returned tool calls ``executor.execute_flow(flow.name, …)``
                so registration is the caller's responsibility.
            executor: The :class:`~chainweaver.executor.FlowExecutor` that
                will run the wrapped flow.  Captured by reference; later
                changes to its tool/flow registries are visible through
                the returned tool.
            name: Override for the resulting tool's name.  Defaults to
                ``flow.name``.
            description: Override for the resulting tool's description.
                Defaults to ``flow.description``.
            input_schema: Override for the derived input schema.  Useful
                when the first step's tool input contains fields the
                caller should not have to provide directly.
            output_schema: Override for the derived output schema.
                Required for DAG flows with multiple sink nodes when no
                flow-level ``output_schema_ref`` is set.

        Returns:
            A :class:`Tool` instance whose ``fn`` executes *flow*.  The
            tool can be registered via
            :meth:`~chainweaver.executor.FlowExecutor.register_tool` just
            like any other tool, enabling flow composition by name.

        Raises:
            ToolDefinitionError: When the flow has no steps, or when
                neither the explicit override, the flow-level ref, nor a
                step-level fallback can produce a required schema (or
                when a DAG has multiple sinks without an explicit
                ``output_schema`` override).
        """
        from chainweaver.exceptions import ToolDefinitionError, ToolNotFoundError

        if not flow.steps:
            raise ToolDefinitionError(flow.name, "Cannot wrap a flow with no steps as a tool.")

        tool_name = name if name is not None else flow.name
        tool_description = description if description is not None else flow.description

        # --- Input schema resolution --------------------------------------
        if input_schema is not None:
            resolved_input = input_schema
        elif flow.input_schema_ref is not None:
            flow_input = flow.input_schema
            if flow_input is None:
                raise ToolDefinitionError(
                    flow.name,
                    f"Flow.input_schema_ref '{flow.input_schema_ref}' did not "
                    "resolve to a schema.",
                )
            resolved_input = flow_input
        else:
            first_step = flow.steps[0]
            try:
                first_tool = executor.get_tool(first_step.tool_name)
            except ToolNotFoundError as exc:
                raise ToolDefinitionError(
                    flow.name,
                    f"Cannot derive input schema: first step's tool "
                    f"'{first_step.tool_name}' is not registered on the executor. "
                    "Pass input_schema=... or register the tool first.",
                ) from exc
            resolved_input = first_tool.input_schema

        # --- Output schema resolution -------------------------------------
        if output_schema is not None:
            resolved_output = output_schema
        elif flow.output_schema_ref is not None:
            flow_output = flow.output_schema
            if flow_output is None:
                raise ToolDefinitionError(
                    flow.name,
                    f"Flow.output_schema_ref '{flow.output_schema_ref}' did not "
                    "resolve to a schema.",
                )
            resolved_output = flow_output
        else:
            terminal_step = _terminal_step(flow)
            try:
                terminal_tool = executor.get_tool(terminal_step.tool_name)
            except ToolNotFoundError as exc:
                raise ToolDefinitionError(
                    flow.name,
                    f"Cannot derive output schema: terminal step's tool "
                    f"'{terminal_step.tool_name}' is not registered on the executor. "
                    "Pass output_schema=... or register the tool first.",
                ) from exc
            resolved_output = terminal_tool.output_schema

        flow_name = flow.name

        def _flow_fn(validated_input: BaseModel) -> dict[str, Any]:
            result = executor.execute_flow(flow_name, validated_input.model_dump())
            if not result.success:
                # Surface the first failed step's context so the caller can
                # diagnose without inspecting the full execution log.
                failed = next((r for r in result.execution_log if not r.success), None)
                if failed is None:
                    detail = "Flow execution failed without recording a failing step."
                    step_index = -1
                else:
                    detail = failed.error_message or failed.error_type or "Unknown error."
                    step_index = failed.step_index
                raise FlowExecutionError(tool_name=flow_name, step_index=step_index, detail=detail)
            if result.final_output is None:
                # Defensive: a successful run should always have a final_output,
                # but the executor's contract allows None on failure paths and
                # this is the only place the closure can guarantee non-None.
                raise FlowExecutionError(
                    tool_name=flow_name,
                    step_index=-1,
                    detail="Flow reported success but produced no final output.",
                )
            return result.final_output

        return cls(
            name=tool_name,
            description=tool_description,
            input_schema=resolved_input,
            output_schema=resolved_output,
            fn=_flow_fn,
        )


def _terminal_step(flow: Flow | DAGFlow) -> FlowStep:
    """Return the sole terminal step of *flow* for output-schema derivation.

    For a linear :class:`Flow` the terminal step is the last entry in
    ``flow.steps``.  For a :class:`DAGFlow` the terminal step is the unique
    sink node (a step that no other step depends on).  When the DAG has more
    than one sink, deriving a single output schema is ambiguous; the caller
    must supply ``output_schema=`` explicitly.

    Args:
        flow: The flow whose terminal step should be located.

    Returns:
        The terminal :class:`FlowStep` (or :class:`DAGFlowStep` for DAGs).

    Raises:
        ToolDefinitionError: When *flow* is a DAG with zero or multiple
            sink nodes.
    """
    from chainweaver.exceptions import ToolDefinitionError

    if not isinstance(flow, DAGFlow):
        return flow.steps[-1]

    referenced: set[str] = set()
    for step in flow.steps:
        referenced.update(step.depends_on)
    sinks: list[DAGFlowStep] = [s for s in flow.steps if s.step_id not in referenced]
    if len(sinks) == 1:
        return sinks[0]
    if len(sinks) == 0:
        raise ToolDefinitionError(
            flow.name,
            "DAG has no sink node; cannot derive output schema. "
            "Pass output_schema=... explicitly.",
        )
    sink_ids = ", ".join(f"'{s.step_id}'" for s in sinks)
    raise ToolDefinitionError(
        flow.name,
        f"DAG has multiple sink nodes ({sink_ids}); output schema is ambiguous. "
        "Pass output_schema=... explicitly.",
    )
