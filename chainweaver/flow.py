"""Flow abstractions for ChainWeaver.

A :class:`Flow` is a named, ordered list of :class:`FlowStep` objects that
wire tool outputs into the next tool's inputs.  Flows are registered in a
:class:`~chainweaver.registry.FlowRegistry` and executed by a
:class:`~chainweaver.executor.FlowExecutor`.

:class:`DAGFlow` extends this with a directed-acyclic-graph model where each
:class:`DAGFlowStep` declares explicit ``depends_on`` edges.  Topology
validation (cycle detection, duplicate IDs, unknown deps) is performed at
registration time via :func:`validate_dag_topology`.
"""

from __future__ import annotations

from graphlib import CycleError, TopologicalSorter
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from chainweaver.exceptions import DAGDefinitionError


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
        input_schema: An optional Pydantic :class:`~pydantic.BaseModel`
            subclass describing the shape of the *initial_input* dictionary
            that a caller must provide when executing this flow.  When set,
            the :class:`~chainweaver.executor.FlowExecutor` validates
            *initial_input* against this schema **before** the first step
            runs.
        output_schema: An optional Pydantic :class:`~pydantic.BaseModel`
            subclass describing the shape of the final merged context
            produced after every step has completed.  When set, the
            :class:`~chainweaver.executor.FlowExecutor` validates the
            accumulated context against this schema **after** the last step
            finishes.

    Example::

        flow = Flow(
            name="double_add_format",
            description="Doubles a number, adds 10, and formats the result.",
            steps=[
                FlowStep(tool_name="double",    input_mapping={"number": "number"}),
                FlowStep(tool_name="add_ten",   input_mapping={"value": "value"}),
                FlowStep(tool_name="format_result", input_mapping={"value": "value"}),
            ],
            input_schema=NumberInput,
            output_schema=FormattedOutput,
        )
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    description: str
    steps: list[FlowStep]
    deterministic: bool = True
    trigger_conditions: dict[str, Any] | None = None
    input_schema: type[BaseModel] | None = None
    output_schema: type[BaseModel] | None = None


# ---------------------------------------------------------------------------
# DAG model
# ---------------------------------------------------------------------------


class DAGFlowStep(FlowStep):
    """A single step inside a :class:`DAGFlow`.

    Extends :class:`FlowStep` with an explicit identity and dependency
    declaration so that the executor can build a dependency graph and execute
    steps in topological order.

    Attributes:
        step_id: Unique identifier for this step within the flow.  Used to
            reference the step in ``depends_on`` lists of other steps.
        depends_on: List of ``step_id`` values that must complete before this
            step can start.  An empty list (the default) means the step has
            no dependencies and runs in the first execution level.
        step_type: Discriminator that indicates how the step is executed.
            ``"tool"`` (the default) means a locally-registered
            :class:`~chainweaver.tools.Tool` is invoked.  The reserved value
            ``"capability"`` is a forward-compat slot for kernel-delegated
            capability invocations via the Weaver Stack agent-kernel contract
            (see invariant I-07 in weaver-spec).  Only ``"tool"`` is executed
            today; ``"capability"`` will be dispatched by
            ``KernelBackedExecutor`` in a future release.
        capability_id: Weaver Stack capability identifier used when
            ``step_type == "capability"``.  Ignored (and should be ``None``)
            for ``step_type == "tool"``.

    Example::

        step = DAGFlowStep(
            tool_name="fetch_data",
            step_id="fetch",
            depends_on=[],
        )
        step_b = DAGFlowStep(
            tool_name="transform",
            step_id="transform",
            depends_on=["fetch"],
        )
    """

    step_id: str
    depends_on: list[str] = Field(default_factory=list)
    step_type: Literal["tool", "capability"] = "tool"
    capability_id: str | None = None


class DAGFlow(BaseModel):
    """A deterministic, DAG-structured sequence of tool invocations.

    Steps are ordered by their ``depends_on`` declarations.  Independent
    steps (no unmet predecessors) form an execution *level* and run
    sequentially within that level (parallel execution is a planned v0.4
    optimisation).

    Attributes:
        name: Unique identifier for the flow.
        description: Human-readable description of what the flow does.
        steps: List of :class:`DAGFlowStep` objects.  Order within the list
            does not imply execution order — the executor derives order from
            ``depends_on`` edges.
        deterministic: When ``True`` (the default) the executor guarantees
            that no LLM calls are inserted between steps.
        trigger_conditions: Optional free-form metadata for agent-level
            dispatch (not evaluated by ChainWeaver itself).
        input_schema: Optional Pydantic :class:`~pydantic.BaseModel` subclass
            validated against ``initial_input`` before the first step runs.
        output_schema: Optional Pydantic :class:`~pydantic.BaseModel` subclass
            validated against the final merged context after all steps finish.

    Raises:
        DAGDefinitionError: If topology is invalid (cycle, duplicate
            ``step_id``, or unknown ``depends_on`` reference).  Raised at
            model-validation time so callers learn about the error before any
            execution attempt.

    Example::

        dag = DAGFlow(
            name="diamond",
            description="A → (B, C) → D",
            steps=[
                DAGFlowStep(tool_name="a", step_id="A", depends_on=[]),
                DAGFlowStep(tool_name="b", step_id="B", depends_on=["A"]),
                DAGFlowStep(tool_name="c", step_id="C", depends_on=["A"]),
                DAGFlowStep(tool_name="d", step_id="D", depends_on=["B", "C"]),
            ],
        )
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    name: str
    description: str
    steps: list[DAGFlowStep]
    deterministic: bool = True
    trigger_conditions: dict[str, Any] | None = None
    input_schema: type[BaseModel] | None = None
    output_schema: type[BaseModel] | None = None


# ---------------------------------------------------------------------------
# Topology validation helper
# ---------------------------------------------------------------------------


def validate_dag_topology(flow: DAGFlow) -> None:
    """Validate the topology of a :class:`DAGFlow`.

    Checks (in order):

    1. No duplicate ``step_id`` values.
    2. Every ``depends_on`` entry refers to a ``step_id`` that exists.
    3. No cycles (via :class:`graphlib.TopologicalSorter`).

    Args:
        flow: The :class:`DAGFlow` to validate.

    Raises:
        DAGDefinitionError: On any topology violation with a structured
            ``reason`` attribute (``"duplicate_step_id"``,
            ``"unknown_dependency"``, or ``"cycle"``).
    """
    step_ids: set[str] = set()
    for step in flow.steps:
        if step.step_id in step_ids:
            raise DAGDefinitionError(
                flow.name,
                "duplicate_step_id",
                f"Step id '{step.step_id}' appears more than once.",
            )
        step_ids.add(step.step_id)

    for step in flow.steps:
        for dep in step.depends_on:
            if dep not in step_ids:
                raise DAGDefinitionError(
                    flow.name,
                    "unknown_dependency",
                    f"Step '{step.step_id}' depends on unknown step id '{dep}'.",
                )

    graph: dict[str, set[str]] = {step.step_id: set(step.depends_on) for step in flow.steps}
    sorter: TopologicalSorter[str] = TopologicalSorter(graph)
    try:
        sorter.prepare()
    except CycleError as exc:
        raise DAGDefinitionError(
            flow.name,
            "cycle",
            f"Dependency cycle detected: {exc}.",
        ) from exc
