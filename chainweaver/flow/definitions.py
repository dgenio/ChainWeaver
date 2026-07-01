"""Core linear-flow definitions and shared declarative types."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from chainweaver.contracts import DeterminismLevel, ToolSafetyContract
from chainweaver.exceptions import FlowSerializationError
from chainweaver.flow.governance import FlowGovernance
from chainweaver.flow.refs import _qualified_name, resolve_class_ref
from chainweaver.flow.steps import FlowStep


class FlowStatus(str, Enum):
    """Lifecycle status of a flow.

    Attributes:
        ACTIVE: Normal operation — the flow can be executed.
        NEEDS_REVIEW: Flagged by drift detection or manual review.
        DISABLED: Manually disabled — excluded from execution.
    """

    ACTIVE = "active"
    NEEDS_REVIEW = "needs_review"
    DISABLED = "disabled"


# Context key-collision policy (issue #337).  Governs what happens when a step
# produces an output key that already exists in the accumulated execution
# context (including the initial input).  ``"overwrite"`` keeps the historical
# silent last-write-wins behaviour; ``"warn"`` (the default) logs at WARNING
# before overwriting; ``"error"`` aborts the run with a typed
# ``ContextKeyCollisionError`` naming the step and colliding keys.  DAG
# *sibling* collisions within one level remain an unconditional error
# regardless of this policy — they are genuinely ambiguous.
ContextCollisionPolicy = Literal["overwrite", "warn", "error"]


class ConditionalEdge(BaseModel):
    """A guarded outgoing edge from a :class:`DAGFlowStep` (issue #9).

    Conditional edges drive runtime branching in a DAG: after a decision
    step runs successfully, the executor walks its ``branches`` in order
    and the *first* edge whose :attr:`predicate` evaluates truthy against
    the merged context picks the next active path.  Non-selected dependent
    steps are recorded as ``StepRecord(skipped=True)``.

    The predicate grammar is intentionally narrow — variable lookups,
    subscript, comparison operators, ``in`` / ``not in``, ``and`` / ``or``
    / ``not`` — and is evaluated by
    :func:`~chainweaver.contracts.evaluate_predicate`, which parses the
    string with :mod:`ast` and walks the tree by hand.  :func:`eval` is
    never called.  See :class:`~chainweaver.exceptions.PredicateSyntaxError`
    for failure modes.

    Attributes:
        target_step_id: The ``step_id`` of the dependent step to activate
            when :attr:`predicate` matches.  Must reference a step that
            also lists the branching step in its ``depends_on``.
        predicate: A restricted boolean expression evaluated against the
            merged execution context — for example
            ``"status == 'ok'"`` or ``"count > 0 and country in ('PT','ES')"``.

    Example::

        DAGFlowStep(
            tool_name="probe",
            step_id="probe",
            depends_on=[],
            branches=[
                ConditionalEdge(target_step_id="fast", predicate="cache_hit == True"),
                ConditionalEdge(target_step_id="slow", predicate="cache_hit == False"),
            ],
        )
    """

    model_config = ConfigDict(frozen=True)

    target_step_id: str
    predicate: str


class Flow(BaseModel):
    """A deterministic, ordered sequence of tool invocations.

    Attributes:
        name: Unique identifier for the flow.
        description: Human-readable description of what the flow does.
        steps: Ordered list of :class:`FlowStep` objects.
        deterministic: Metadata annotation for downstream orchestrators.
            When ``True`` (the default) this signals the flow is designed
            to run without LLM calls.  ``FlowExecutor`` is unconditionally
            LLM-free and does not evaluate this flag.
        trigger_conditions: Optional free-form metadata that an agent or
            higher-level orchestrator can use to decide when to invoke this
            flow.  ChainWeaver itself does not evaluate these conditions.
        input_schema_ref: An optional ``"module:qualname"`` reference to a
            Pydantic :class:`~pydantic.BaseModel` subclass describing the
            shape of the *initial_input* dictionary that a caller must
            provide when executing this flow.  When set, the
            :class:`~chainweaver.executor.FlowExecutor` validates
            *initial_input* against the resolved schema **before** the first
            step runs.

            String refs (rather than live class objects) keep the flow
            JSON/YAML-serializable; use :meth:`schema_ref_from` to derive
            the ref from a class.  The :attr:`input_schema` property
            resolves the ref lazily.
        output_schema_ref: An optional ``"module:qualname"`` reference to a
            Pydantic :class:`~pydantic.BaseModel` subclass describing the
            shape of the final merged context produced after every step has
            completed.  When set, the
            :class:`~chainweaver.executor.FlowExecutor` validates the
            accumulated context against the resolved schema **after** the
            last step finishes.
        capability_id: Optional Weaver Stack capability identifier (issue
            #90).  When set, this flow is exposed as a routable capability
            via :func:`chainweaver.integrations.weaver_spec.flow_to_selectable_item`
            and can be addressed by a ``RoutingDecision`` from
            contextweaver.  Should be a stable, dotted identifier (e.g.
            ``"data.ingest"``); ``None`` (the default) means the flow is
            not exposed as a capability.
        context_schema_ref: An optional ``"module:qualname"`` reference to
            a :class:`~pydantic.BaseModel` subclass describing the shape
            of the *accumulated execution context* (issue #152).  The
            executor validates the context against the resolved schema
            at flow end, once every step has completed successfully
            (skipped when an earlier step aborts the flow, since no
            ``final_output`` is produced in that case).  The primary
            value of this field is static typing — flow authors get
            mypy + IDE autocomplete + a single source of truth for
            context keys; runtime validation at the flow boundary is a
            secondary safety net.
        dynamic_params: Names of parameters injected at execution time via
            ``execute_flow(..., dynamic_params={...})`` rather than supplied in
            the LLM-visible ``initial_input`` (issue #316).  Dynamic params are
            merged into the running context *after* ``input_schema`` validation,
            so they are available to every step's ``input_mapping`` and flow
            through to the final output, yet are intentionally **not** part of
            ``input_schema`` — keeping per-request secrets (auth tokens, account
            numbers) out of any schema advertised to a model.  This field is
            declarative metadata for hosts and export adapters that want to know
            which params a flow expects out-of-band; the executor accepts any
            ``dynamic_params`` keys regardless of whether they are declared
            here.

    Example::

        flow = Flow(
            name="double_add_format",
            version="1.0.0",
            description="Doubles a number, adds 10, and formats the result.",
            steps=[
                FlowStep(tool_name="double",    input_mapping={"number": "number"}),
                FlowStep(tool_name="add_ten",   input_mapping={"value": "value"}),
                FlowStep(tool_name="format_result", input_mapping={"value": "value"}),
            ],
            input_schema_ref=Flow.schema_ref_from(NumberInput),
            output_schema_ref=Flow.schema_ref_from(FormattedOutput),
            context_schema_ref=Flow.schema_ref_from(MyFlowContext),
        )
    """

    name: str
    version: str = "0.1.0"
    description: str
    steps: list[FlowStep]
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

        Convenience helper so callers can write
        ``input_schema_ref=Flow.schema_ref_from(NumberInput)`` instead of
        hand-formatting the ref string.
        """
        return _qualified_name(cls)

    @property
    def input_schema(self) -> type[BaseModel] | None:
        """Resolve :attr:`input_schema_ref` to a class, or ``None`` if unset.

        Raises:
            FlowSerializationError: When the ref cannot be resolved or does
                not point to a :class:`BaseModel` subclass.
        """
        if self.input_schema_ref is None:
            return None
        resolved = resolve_class_ref(self.input_schema_ref, expected_base=BaseModel)
        return resolved

    @property
    def output_schema(self) -> type[BaseModel] | None:
        """Resolve :attr:`output_schema_ref` to a class, or ``None`` if unset.

        Raises:
            FlowSerializationError: When the ref cannot be resolved or does
                not point to a :class:`BaseModel` subclass.
        """
        if self.output_schema_ref is None:
            return None
        resolved = resolve_class_ref(self.output_schema_ref, expected_base=BaseModel)
        return resolved

    @property
    def determinism_level(self) -> DeterminismLevel:
        """Return the structural determinism level of this flow (issue #8).

        Linear :class:`Flow` instances are :class:`DeterminismLevel.FULL`
        by definition — every step always runs, in declared order — *unless*
        the flow author explicitly opts out by setting ``deterministic=False``
        (which yields :class:`DeterminismLevel.NONE`), or a step carries a
        non-empty :attr:`FlowStep.decision_candidates` list, which downgrades
        the flow to :class:`DeterminismLevel.PARTIAL` (issue #369).  Guided
        decision points (#102) let a registered callback pick which candidate
        tool runs, so the executed path is data-dependent at runtime even
        though the step sequence is fixed — the same reason :class:`DAGFlow`
        downgrades for ``branches``.

        This property reflects flow *structure* only.  Tool-level safety
        contracts are not consulted here because the flow does not have
        access to the tool registry; consumers that want a worst-case
        composite (this property combined with constituent tools'
        :attr:`ToolSafetyContract.determinism_level` values) should merge
        the two themselves.
        """
        if not self.deterministic:
            return DeterminismLevel.NONE
        if any(step.decision_candidates for step in self.steps):
            return DeterminismLevel.PARTIAL
        return DeterminismLevel.FULL

    @property
    def context_schema(self) -> type[BaseModel] | None:
        """Resolve :attr:`context_schema_ref` to a class, or ``None`` (issue #152).

        Raises:
            FlowSerializationError: When the ref cannot be resolved or does
                not point to a :class:`BaseModel` subclass.
        """
        if self.context_schema_ref is None:
            return None
        resolved = resolve_class_ref(self.context_schema_ref, expected_base=BaseModel)
        return resolved

    def to_ascii(self) -> str:
        """Return a single-line ASCII flow diagram (issue #79)."""
        from chainweaver.viz import flow_to_ascii

        return flow_to_ascii(self)

    def to_mermaid(self, *, direction: str = "LR", show_schemas: bool = False) -> str:
        """Return a Mermaid ``graph <direction>`` rendering of this flow (#79)."""
        from chainweaver.viz import flow_to_mermaid

        return flow_to_mermaid(self, direction=direction, show_schemas=show_schemas)

    def to_dot(self) -> str:
        """Return a DOT (Graphviz) rendering of this flow (issue #46)."""
        from chainweaver.viz import flow_to_dot

        return flow_to_dot(self)

    def to_json(self, *, indent: int | None = 2) -> str:
        """Serialize this flow to a JSON string (issue #14).

        Args:
            indent: Indentation level for pretty-printing.  ``None`` produces
                a compact single-line representation.

        Returns:
            A JSON string that round-trips via :meth:`from_json`.
        """
        from chainweaver.serialization import flow_to_json

        return flow_to_json(self, indent=indent)

    def to_yaml(self) -> str:
        """Serialize this flow to a YAML string (issue #14).

        Requires ``pyyaml`` to be installed (``pip install chainweaver[yaml]``).

        Returns:
            A YAML string that round-trips via :meth:`from_yaml`.

        Raises:
            FlowSerializationError: When ``pyyaml`` is not available.
        """
        from chainweaver.serialization import flow_to_yaml

        return flow_to_yaml(self)

    @classmethod
    def from_json(cls, data: str, *, source: str | None = None) -> Flow:
        """Deserialize a :class:`Flow` from a JSON string (issue #14).

        Raises:
            FlowSerializationError: When the JSON payload is malformed,
                missing required fields, or describes a :class:`DAGFlow`
                instead of a :class:`Flow`.
        """
        from chainweaver.serialization import flow_from_json

        result = flow_from_json(data, source=source)
        if not isinstance(result, cls):
            raise FlowSerializationError(
                f"Expected a Flow payload but got {type(result).__name__}",
                source=source,
            )
        return result

    @classmethod
    def from_yaml(cls, data: str, *, source: str | None = None) -> Flow:
        """Deserialize a :class:`Flow` from a YAML string (issue #14).

        Requires ``pyyaml`` to be installed (``pip install chainweaver[yaml]``).

        Raises:
            FlowSerializationError: When the YAML payload is malformed,
                missing required fields, or describes a :class:`DAGFlow`
                instead of a :class:`Flow`.
        """
        from chainweaver.serialization import flow_from_yaml

        result = flow_from_yaml(data, source=source)
        if not isinstance(result, cls):
            raise FlowSerializationError(
                f"Expected a Flow payload but got {type(result).__name__}",
                source=source,
            )
        return result
