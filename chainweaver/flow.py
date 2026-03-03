"""Flow abstractions for ChainWeaver.

A :class:`Flow` is a named, ordered list of :class:`FlowStep` objects that
wire tool outputs into the next tool's inputs.  Flows are registered in a
:class:`~chainweaver.registry.FlowRegistry` and executed by a
:class:`~chainweaver.executor.FlowExecutor`.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class FlowStep(BaseModel):
    """A single step inside a :class:`Flow`.

    Attributes:
        tool_name: The name of the :class:`~chainweaver.tools.Tool` to invoke.
        input_mapping: Maps keys expected by the tool's *input_schema* to keys
            present in the accumulated execution context (initial input merged
            with all previous step outputs).

            If a value is a string it is treated as a key lookup in the context.
            If a value is any other type (int, float, bool, …) it is used as a
            literal constant.

            An empty mapping (the default) means the tool receives the full
            current context as-is.

    Example::

        # Pass the "value" from the previous step as "value" to this tool
        step = FlowStep(tool_name="add_ten", input_mapping={"value": "value"})

        # Mix a context lookup with a literal constant
        step = FlowStep(
            tool_name="scale",
            input_mapping={"number": "value", "factor": 3},
        )
    """

    tool_name: str
    input_mapping: dict[str, Any] = Field(default_factory=dict)


class Flow(BaseModel):
    """A deterministic, ordered sequence of tool invocations.

    Attributes:
        name: Unique identifier for the flow.
        description: Human-readable description of what the flow does.
        steps: Ordered list of :class:`FlowStep` objects.
        deterministic: When ``True`` (the default) the executor guarantees
            that no LLM calls are inserted between steps.
        trigger_conditions: Optional free-form metadata that an agent or
            higher-level orchestrator can use to decide when to invoke this
            flow.  ChainWeaver itself does not evaluate these conditions.

    Example::

        flow = Flow(
            name="double_add_format",
            description="Doubles a number, adds 10, and formats the result.",
            steps=[
                FlowStep(tool_name="double",    input_mapping={"number": "number"}),
                FlowStep(tool_name="add_ten",   input_mapping={"value": "value"}),
                FlowStep(tool_name="format_result", input_mapping={"value": "value"}),
            ],
        )
    """

    name: str
    description: str
    steps: list[FlowStep]
    deterministic: bool = True
    trigger_conditions: dict[str, Any] | None = None

    # TODO (Phase 2): Add support for DAG-based steps with explicit
    # dependency edges and parallel execution groups.

    # TODO (Phase 2): Add conditional branching — a step that inspects
    # context values and selects the next step(s) at runtime.

    # TODO (Phase 2): Add determinism scoring so that partially
    # deterministic flows can be marked and handled appropriately.
