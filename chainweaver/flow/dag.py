"""DAG flow definitions and topology validation."""

from __future__ import annotations

from graphlib import CycleError, TopologicalSorter
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from chainweaver.contracts import DeterminismLevel, ToolSafetyContract
from chainweaver.exceptions import DAGDefinitionError, FlowSerializationError
from chainweaver.flow.definitions import (
    ConditionalEdge,
    ContextCollisionPolicy,
    FlowStatus,
)
from chainweaver.flow.governance import FlowGovernance
from chainweaver.flow.refs import _qualified_name, resolve_class_ref
from chainweaver.flow.steps import FlowStep


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
        branches: Optional list of :class:`ConditionalEdge` outgoing
            guards (issue #9).  When non-empty, this step is a *decision*
            step: after it runs, the executor evaluates each branch's
            predicate against the merged context and the first match
            selects the active downstream path.  Non-selected immediate
            dependents are skipped (their :class:`StepRecord` carries
            ``skipped=True``), and the skip propagates to dependents whose
            only inbound paths are themselves skipped.  When ``branches``
            is empty (the default), the step is a regular DAG node and
            every dependent runs.
        default_next: Step id activated when none of :attr:`branches` match
            (issue #9).  Treated as if it were a final-fallback
            ``ConditionalEdge`` whose predicate is always true.  Ignored
            when ``branches`` is empty.

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
    branches: list[ConditionalEdge] = Field(default_factory=list)
    default_next: str | None = None

    @model_validator(mode="after")
    def _check_tool_has_no_capability_id(self) -> DAGFlowStep:
        """Ensure ``capability_id`` is ``None`` when ``step_type`` is ``'tool'``."""
        if self.step_type == "tool" and self.capability_id is not None:
            msg = (
                f"Step '{self.step_id}' has step_type='tool' but capability_id="
                f"'{self.capability_id}'. capability_id must be None for tool steps."
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _check_default_next_requires_branches(self) -> DAGFlowStep:
        """``default_next`` is only meaningful alongside at least one branch."""
        if self.default_next is not None and not self.branches:
            msg = (
                f"Step '{self.step_id}' sets default_next='{self.default_next}' "
                f"but has no branches. default_next is the fallback when no "
                f"branch matches and is ignored without branches; remove it "
                f"or add the first branch."
            )
            raise ValueError(msg)
        return self

    @model_validator(mode="after")
    def _check_capability_has_no_branches(self) -> DAGFlowStep:
        """Conditional branching is unsupported on capability steps.

        The DAG runner dispatches ``step_type='capability'`` steps through the
        ``_execute_capability_step`` hook, which returns before
        ``FlowExecutor._select_branch`` runs, so ``branches`` / ``default_next``
        would be silently ignored.  Reject the combination at construction
        (fail-loud) rather than dropping the edges at runtime.
        """
        if self.step_type == "capability" and self.branches:
            msg = (
                f"Step '{self.step_id}' has step_type='capability' with "
                f"conditional branches. Branching is only supported on "
                f"step_type='tool' steps; capability steps cannot carry "
                f"branches or default_next."
            )
            raise ValueError(msg)
        return self


class DAGFlow(BaseModel):
    """A deterministic, DAG-structured sequence of tool invocations.

    Steps are ordered by their ``depends_on`` declarations.  Independent
    steps (no unmet predecessors) form an execution *level* and run
    sequentially within that level (parallel/async execution for independent
    levels is planned for v0.2).

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
        input_schema_ref: Optional ``"module:qualname"`` ref to a Pydantic
            :class:`~pydantic.BaseModel` subclass validated against
            ``initial_input`` before the first step runs.  Resolved lazily
            via the :attr:`input_schema` property.
        output_schema_ref: Optional ``"module:qualname"`` ref to a Pydantic
            :class:`~pydantic.BaseModel` subclass validated against the
            final merged context after all steps finish.  Resolved lazily
            via the :attr:`output_schema` property.
        capability_id: Optional Weaver Stack capability identifier (issue
            #90); see :attr:`Flow.capability_id` for full semantics.
        context_schema_ref: Optional ``"module:qualname"`` ref to a
            :class:`~pydantic.BaseModel` subclass validated against the
            accumulated context at flow end, once every step has
            completed successfully (issue #152; validation is skipped
            when an earlier step aborts the flow).  Mirrors the
            :class:`Flow` field of the same name; see there for the
            DX motivation.
        dynamic_params: Names of parameters injected at execution time via
            ``execute_flow(..., dynamic_params={...})`` rather than supplied in
            ``initial_input`` (issue #316).  Mirrors the :class:`Flow` field of
            the same name; see there for full semantics.

    Raises:
        DAGDefinitionError: If topology is invalid (cycle, duplicate
            ``step_id``, or unknown ``depends_on`` reference) when
            :func:`validate_dag_topology` is invoked, such as during flow
            registration or before execution.

    Example::

        dag = DAGFlow(
            name="diamond",
            version="1.0.0",
            description="A → (B, C) → D",
            steps=[
                DAGFlowStep(tool_name="a", step_id="A", depends_on=[]),
                DAGFlowStep(tool_name="b", step_id="B", depends_on=["A"]),
                DAGFlowStep(tool_name="c", step_id="C", depends_on=["A"]),
                DAGFlowStep(tool_name="d", step_id="D", depends_on=["B", "C"]),
            ],
        )
    """

    name: str
    version: str
    description: str
    steps: list[DAGFlowStep]
    deterministic: bool = True
    status: FlowStatus = FlowStatus.ACTIVE
    trigger_conditions: dict[str, Any] | None = None
    input_schema_ref: str | None = None
    output_schema_ref: str | None = None
    context_schema_ref: str | None = None
    tool_schema_hashes: dict[str, str] | None = None
    capability_id: str | None = None
    governance: FlowGovernance = Field(default_factory=FlowGovernance)
    safety: ToolSafetyContract | None = None
    on_context_collision: ContextCollisionPolicy = "warn"
    dynamic_params: tuple[str, ...] = ()

    @staticmethod
    def schema_ref_from(cls: type[BaseModel]) -> str:
        """Return a ``"module:qualname"`` ref string for *cls*.

        See :meth:`Flow.schema_ref_from` for full docs.
        """
        return _qualified_name(cls)

    @property
    def input_schema(self) -> type[BaseModel] | None:
        """Resolve :attr:`input_schema_ref` to a class, or ``None`` if unset."""
        if self.input_schema_ref is None:
            return None
        resolved = resolve_class_ref(self.input_schema_ref, expected_base=BaseModel)
        return resolved

    @property
    def output_schema(self) -> type[BaseModel] | None:
        """Resolve :attr:`output_schema_ref` to a class, or ``None`` if unset."""
        if self.output_schema_ref is None:
            return None
        resolved = resolve_class_ref(self.output_schema_ref, expected_base=BaseModel)
        return resolved

    @property
    def determinism_level(self) -> DeterminismLevel:
        """Return the structural determinism level of this DAG flow (issue #8).

        :class:`DAGFlow` instances downgrade to
        :class:`DeterminismLevel.PARTIAL` whenever **any** step carries a
        non-empty :attr:`DAGFlowStep.branches` list — branches make the
        executed path data-dependent at runtime, even though the graph
        itself is fixed — or a non-empty
        :attr:`DAGFlowStep.decision_candidates` list, where a registered
        decision callback picks the tool at runtime (issue #369).  A DAG with
        neither is :class:`DeterminismLevel.FULL`, and any flow that
        explicitly opts out via ``deterministic=False`` is
        :class:`DeterminismLevel.NONE`.
        """
        if not self.deterministic:
            return DeterminismLevel.NONE
        if any(step.branches or step.decision_candidates for step in self.steps):
            return DeterminismLevel.PARTIAL
        return DeterminismLevel.FULL

    @property
    def context_schema(self) -> type[BaseModel] | None:
        """Resolve :attr:`context_schema_ref` to a class, or ``None`` (issue #152)."""
        if self.context_schema_ref is None:
            return None
        resolved = resolve_class_ref(self.context_schema_ref, expected_base=BaseModel)
        return resolved

    def to_ascii(self) -> str:
        """Return a multi-line ASCII rendering of this DAG (issue #79)."""
        from chainweaver.viz import flow_to_ascii

        return flow_to_ascii(self)

    def to_mermaid(self, *, direction: str = "LR", show_schemas: bool = False) -> str:
        """Return a Mermaid graph rendering of this DAG (issue #79)."""
        from chainweaver.viz import flow_to_mermaid

        return flow_to_mermaid(self, direction=direction, show_schemas=show_schemas)

    def to_dot(self) -> str:
        """Return a DOT (Graphviz) rendering of this DAG (issue #46)."""
        from chainweaver.viz import flow_to_dot

        return flow_to_dot(self)

    def to_json(self, *, indent: int | None = 2) -> str:
        """Serialize this DAG flow to a JSON string (issue #14)."""
        from chainweaver.serialization import flow_to_json

        return flow_to_json(self, indent=indent)

    def to_yaml(self) -> str:
        """Serialize this DAG flow to a YAML string (issue #14).

        Raises:
            FlowSerializationError: When ``pyyaml`` is not available.
        """
        from chainweaver.serialization import flow_to_yaml

        return flow_to_yaml(self)

    @classmethod
    def from_json(cls, data: str, *, source: str | None = None) -> DAGFlow:
        """Deserialize a :class:`DAGFlow` from a JSON string (issue #14).

        Raises:
            FlowSerializationError: When the JSON payload is malformed,
                missing required fields, or describes a :class:`Flow`
                instead of a :class:`DAGFlow`.
        """
        from chainweaver.serialization import flow_from_json

        result = flow_from_json(data, source=source)
        if not isinstance(result, cls):
            raise FlowSerializationError(
                f"Expected a DAGFlow payload but got {type(result).__name__}",
                source=source,
            )
        return result

    @classmethod
    def from_yaml(cls, data: str, *, source: str | None = None) -> DAGFlow:
        """Deserialize a :class:`DAGFlow` from a YAML string (issue #14).

        Raises:
            FlowSerializationError: When ``pyyaml`` is not available or when
                the payload is malformed or refers to a :class:`Flow`.
        """
        from chainweaver.serialization import flow_from_yaml

        result = flow_from_yaml(data, source=source)
        if not isinstance(result, cls):
            raise FlowSerializationError(
                f"Expected a DAGFlow payload but got {type(result).__name__}",
                source=source,
            )
        return result


# ---------------------------------------------------------------------------
# Topology validation helper
# ---------------------------------------------------------------------------


def validate_dag_topology(flow: DAGFlow) -> None:
    """Validate the topology of a :class:`DAGFlow`.

    Checks (in order):

    1. No duplicate ``step_id`` values.
    2. Every ``depends_on`` entry refers to a ``step_id`` that exists.
    3. No cycles (via :class:`graphlib.TopologicalSorter`).
    4. Every :class:`ConditionalEdge` target (and any ``default_next``) is a
       direct dependent of the branching step — that is, the target lists
       the branching step in its own ``depends_on``.  This keeps branch
       routing local: a branch picks among the step's *immediate* successors
       rather than jumping into an unrelated part of the graph.

    Args:
        flow: The :class:`DAGFlow` to validate.

    Raises:
        DAGDefinitionError: On any topology violation with a structured
            ``reason`` attribute (``"duplicate_step_id"``,
            ``"unknown_dependency"``, ``"cycle"``, or
            ``"unknown_branch_target"``).
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

    # Branch validation (issue #9): every conditional edge target must be a
    # direct dependent of the branching step.  This keeps routing local and
    # makes "skipped" computation in the executor a one-hop decision.
    dependents: dict[str, set[str]] = {sid: set() for sid in step_ids}
    for step in flow.steps:
        for dep in step.depends_on:
            dependents[dep].add(step.step_id)

    for step in flow.steps:
        candidates: list[tuple[str, str]] = [
            (edge.target_step_id, "branch target") for edge in step.branches
        ]
        if step.default_next is not None:
            candidates.append((step.default_next, "default_next target"))
        for target, label in candidates:
            if target not in step_ids:
                raise DAGDefinitionError(
                    flow.name,
                    "unknown_branch_target",
                    f"Step '{step.step_id}' {label} '{target}' is not a declared step id.",
                )
            if target not in dependents[step.step_id]:
                raise DAGDefinitionError(
                    flow.name,
                    "unknown_branch_target",
                    f"Step '{step.step_id}' {label} '{target}' is not a "
                    f"direct dependent (target must list '{step.step_id}' "
                    f"in its depends_on).",
                )
