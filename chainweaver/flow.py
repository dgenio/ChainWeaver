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

import importlib
import random
from dataclasses import dataclass
from enum import Enum
from graphlib import CycleError, TopologicalSorter
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from chainweaver.contracts import DeterminismLevel, ToolSafetyContract
from chainweaver.exceptions import DAGDefinitionError, FlowSerializationError


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


class FlowLifecycle(str, Enum):
    """Review lifecycle for a macro-flow candidate.

    This is intentionally separate from :class:`FlowStatus`: lifecycle
    describes governance and promotion, while status controls whether the
    executor may run an already-registered flow.
    """

    OBSERVED = "observed"
    SUGGESTED = "suggested"
    DRAFT = "draft"
    REVIEWED = "reviewed"
    ACTIVE = "active"
    IGNORED = "ignored"
    ARCHIVED = "archived"


_LIFECYCLE_TRANSITIONS: dict[FlowLifecycle, frozenset[FlowLifecycle]] = {
    FlowLifecycle.OBSERVED: frozenset({FlowLifecycle.SUGGESTED, FlowLifecycle.IGNORED}),
    FlowLifecycle.SUGGESTED: frozenset({FlowLifecycle.DRAFT, FlowLifecycle.IGNORED}),
    FlowLifecycle.DRAFT: frozenset({FlowLifecycle.REVIEWED, FlowLifecycle.IGNORED}),
    FlowLifecycle.REVIEWED: frozenset(
        {FlowLifecycle.DRAFT, FlowLifecycle.ACTIVE, FlowLifecycle.ARCHIVED}
    ),
    FlowLifecycle.ACTIVE: frozenset({FlowLifecycle.ARCHIVED}),
    FlowLifecycle.IGNORED: frozenset({FlowLifecycle.SUGGESTED}),
    FlowLifecycle.ARCHIVED: frozenset({FlowLifecycle.REVIEWED}),
}


class FlowGovernance(BaseModel):
    """Review, ownership, and savings metadata for a macro-flow."""

    model_config = ConfigDict(frozen=True)

    lifecycle: FlowLifecycle = FlowLifecycle.ACTIVE
    owner: str | None = None
    replaces_tools: tuple[str, ...] = ()
    estimated_model_calls_removed: int = Field(default=0, ge=0)
    estimated_token_savings: int | None = Field(default=None, ge=0)
    reviewed_by: str | None = None
    review_notes: str | None = None

    def transition_to(
        self,
        target: FlowLifecycle,
        *,
        reviewed_by: str | None = None,
        review_notes: str | None = None,
    ) -> FlowGovernance:
        """Return a copy transitioned to *target* after validating the move."""
        allowed = _LIFECYCLE_TRANSITIONS[self.lifecycle]
        if target not in allowed:
            raise ValueError(
                f"Flow lifecycle cannot transition from '{self.lifecycle.value}' "
                f"to '{target.value}'."
            )
        updates: dict[str, Any] = {"lifecycle": target}
        if reviewed_by is not None:
            updates["reviewed_by"] = reviewed_by
        if review_notes is not None:
            updates["review_notes"] = review_notes
        return self.model_copy(update=updates)


def _qualified_name(cls: type) -> str:
    """Return ``"module:qualname"`` for *cls*, suitable for storage and lookup."""
    return f"{cls.__module__}:{cls.__qualname__}"


def resolve_class_ref(ref: str, *, expected_base: type | None = None) -> type:
    """Resolve a ``"module:qualname"`` string to the referenced class object.

    Used for both schema refs (``Flow.input_schema_ref``, etc.) and exception
    refs (``RetryPolicy.retryable_errors``).  All breakage modes raise
    :class:`~chainweaver.exceptions.FlowSerializationError` with a precise
    detail so that callers can surface actionable error messages.

    Args:
        ref: A reference of the form ``"package.module:ClassName"`` or
            ``"package.module:Outer.Inner"`` (for nested classes).
        expected_base: When provided, the resolved class must be a subclass
            of this type.  Useful to enforce that schema refs resolve to
            ``BaseModel`` subclasses or that error refs resolve to
            ``BaseException`` subclasses.

    Returns:
        The resolved class object.

    Raises:
        FlowSerializationError: When *ref* is not in ``module:qualname`` form,
            when the module cannot be imported, when the attribute does not
            exist, when the attribute is not a class, or when it does not
            subclass *expected_base*.
    """
    if ":" not in ref:
        raise FlowSerializationError(f"Class ref '{ref}' must be in 'module:qualname' form")
    module_path, qualname = ref.split(":", 1)
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        raise FlowSerializationError(
            f"Cannot import module '{module_path}' for ref '{ref}': {exc}"
        ) from exc
    obj: Any = module
    for part in qualname.split("."):
        try:
            obj = getattr(obj, part)
        except AttributeError as exc:
            raise FlowSerializationError(
                f"Attribute '{qualname}' not found in module '{module_path}' for ref '{ref}'"
            ) from exc
    if not isinstance(obj, type):
        raise FlowSerializationError(
            f"Ref '{ref}' resolved to {type(obj).__name__}, expected a class"
        )
    if expected_base is not None and not issubclass(obj, expected_base):
        raise FlowSerializationError(
            f"Ref '{ref}' resolved to {obj.__name__}, "
            f"which is not a subclass of {expected_base.__name__}"
        )
    return obj


class RetryPolicy(BaseModel):
    """Per-step retry configuration (issue #76).

    Drives the retry behaviour of :class:`~chainweaver.executor.FlowExecutor`
    when attached to a :class:`FlowStep`.  Backoff is exponential and
    deterministic by default: the first retry waits ``backoff_seconds``, the
    second waits ``backoff_seconds * backoff_multiplier``, and so on.

    Setting ``jitter=True`` opts a single retry loop into uniform jitter
    (multiplier in ``[0.5, 1.5)``).  This is the only place in the package
    where :mod:`random` is used; ``executor.py`` itself never imports it.
    See ``docs/agent-context/invariants.md`` for the carve-out.

    Attributes:
        max_retries: Number of retry attempts after the initial call (so
            ``max_retries=3`` allows up to 4 invocations total).
        backoff_seconds: Initial delay before the first retry, in seconds.
        backoff_multiplier: Geometric multiplier applied to ``backoff_seconds``
            between retries.  Must be ``>= 1.0``.
        jitter: When ``True``, multiply each computed delay by a uniform
            sample in ``[0.5, 1.5)``.
        retryable_errors: Exception class references that trigger a retry.
            Each entry is a ``"module:qualname"`` string (e.g.
            ``"builtins.ValueError"`` written as ``"builtins:ValueError"``).
            Anything else fails immediately.  Defaults to
            ``("builtins:Exception",)`` — retry on any error.

            String refs (rather than live class objects) keep the policy
            JSON/YAML-serializable; refs are resolved to types just before
            the retry loop in :mod:`chainweaver.executor`.
    """

    model_config = ConfigDict(frozen=True)

    max_retries: int = Field(default=3, ge=0)
    backoff_seconds: float = Field(default=1.0, ge=0.0)
    backoff_multiplier: float = Field(default=2.0, ge=1.0)
    jitter: bool = False
    retryable_errors: tuple[str, ...] = ("builtins:Exception",)

    @field_validator("retryable_errors")
    @classmethod
    def _validate_retryable_errors(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("retryable_errors must contain at least one class ref.")
        for ref in value:
            if ":" not in ref:
                raise ValueError(
                    f"retryable_errors entry '{ref}' must be in 'module:qualname' form "
                    f"(e.g. 'builtins:ValueError')."
                )
        return value

    def resolved_retryable_errors(self) -> tuple[type[BaseException], ...]:
        """Resolve ``retryable_errors`` ref strings to a tuple of exception classes.

        Raises:
            FlowSerializationError: When any ref cannot be resolved or does
                not point to a :class:`BaseException` subclass.
        """
        return tuple(
            resolve_class_ref(ref, expected_base=BaseException) for ref in self.retryable_errors
        )

    def compute_delay(self, attempt_number: int) -> float:
        """Return the wait, in seconds, before retry attempt *attempt_number*.

        ``attempt_number`` is 1-indexed: ``1`` is the delay before the first
        retry (i.e. the second total invocation).  When ``jitter`` is set,
        the deterministic delay is multiplied by a uniform sample in
        ``[0.5, 1.5)``.
        """
        if attempt_number < 1:
            return 0.0
        delay = self.backoff_seconds * (self.backoff_multiplier ** (attempt_number - 1))
        if self.jitter:
            delay *= 0.5 + random.random()
        return delay


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


class FlowStep(BaseModel):
    """A single step inside a :class:`Flow`.

    Attributes:
        tool_name: The name of the :class:`~chainweaver.tools.Tool` to invoke.
            Mutually exclusive with :attr:`flow_name`; exactly one must be set.
        flow_name: The name of a registered sub-:class:`Flow` to execute in
            place of a tool (issue #75 — flow composition).  When set, the
            executor resolves the named flow from the registry, runs it with
            this step's resolved inputs as its initial input, and merges the
            sub-flow's final output back into the parent context.  Mutually
            exclusive with :attr:`tool_name`.  Sub-flow references are checked
            for cycles and a configurable maximum nesting depth before
            execution (raising
            :class:`~chainweaver.exceptions.FlowCompositionError`).
        input_mapping: Maps keys expected by the tool's *input_schema* to keys
            present in the accumulated execution context (initial input merged
            with all previous step outputs).

            If a value is a string it is treated as a key lookup in the context.
            If a value is any other type (int, float, bool, …) it is used as a
            literal constant.

            An empty mapping (the default) means the tool receives the full
            current context as-is.
        decision_candidates: Optional list of tool names that an external
            :class:`~chainweaver.decisions.DecisionCallback` may pick from
            at execution time (issue #102).  When ``None`` (the default)
            the step always invokes ``tool_name``.  When set, the executor
            calls the registered ``decision_callback`` with the candidate
            list and the current context, and runs whichever tool the
            callback selects.  The callback's return value must be a
            member of ``decision_candidates``; if no callback is
            registered the executor falls back to ``tool_name``.
        retry: Optional :class:`RetryPolicy` driving the executor's retry
            behaviour for this step.
        on_error: How the executor reacts when all retry attempts are
            exhausted: ``"fail"`` (the default), ``"skip"``, or
            ``"fallback:<tool_name>"``.  Step-contract failures
            (:attr:`input_contract` / :attr:`output_contract`) intentionally
            bypass this policy and always abort the step — contract
            mismatches are wiring bugs rather than transient errors.
        input_contract: Optional ``"module:qualname"`` reference to a
            :class:`~pydantic.BaseModel` subclass that the executor
            validates against the *resolved* step inputs **before** the
            tool is invoked (issue #172).  This is independent from the
            tool's own ``input_schema``: it expresses a step-level
            contract that the wiring (``input_mapping`` + accumulated
            context) must satisfy, surfacing mapping mistakes with a
            schema-shaped error rather than waiting for the tool's own
            validation to fail.
        output_contract: Optional ``"module:qualname"`` reference to a
            :class:`~pydantic.BaseModel` subclass that the executor
            validates against the tool's outputs **after** the tool has
            run (issue #172).  Use this when the step has a tighter
            output contract than the tool's own ``output_schema`` — e.g.
            a tool that returns a superset of fields but this step only
            promises a subset.

    Example::

        # Pass the "value" from the previous step as "value" to this tool
        step = FlowStep(tool_name="add_ten", input_mapping={"value": "value"})

        # Mix a context lookup with a literal constant
        step = FlowStep(
            tool_name="scale",
            input_mapping={"number": "value", "factor": 3},
        )

        # Hybrid execution: let an external callback pick a tool
        step = FlowStep(
            tool_name="summarize_short",   # default if no callback set
            decision_candidates=["summarize_short", "summarize_long"],
        )

        # Add typed step contracts (issue #172)
        step = FlowStep(
            tool_name="scale",
            input_mapping={"number": "value", "factor": 3},
            input_contract=FlowStep.contract_ref_from(ScaleInput),
            output_contract=FlowStep.contract_ref_from(ScaleOutput),
        )
    """

    tool_name: str | None = None
    flow_name: str | None = None
    input_mapping: dict[str, Any] = Field(default_factory=dict)
    retry: RetryPolicy | None = None
    on_error: str = "fail"
    decision_candidates: list[str] | None = None
    input_contract: str | None = None
    output_contract: str | None = None

    @model_validator(mode="after")
    def _check_tool_or_flow(self) -> FlowStep:
        """Require exactly one of ``tool_name`` / ``flow_name`` (issue #75).

        A step either invokes a tool (``tool_name``) or recursively executes a
        registered sub-flow (``flow_name``) — never both, and never neither.
        Enforcing this at construction turns a wiring mistake into a loud
        validation error instead of a confusing execution-time failure.
        """
        if (self.tool_name is None) == (self.flow_name is None):
            raise ValueError(
                "FlowStep requires exactly one of 'tool_name' or 'flow_name' "
                f"(got tool_name={self.tool_name!r}, flow_name={self.flow_name!r})."
            )
        if self.flow_name is not None and self.decision_candidates is not None:
            raise ValueError(
                "FlowStep 'decision_candidates' is only valid for tool steps, "
                "not sub-flow (flow_name) steps."
            )
        return self

    @field_validator("decision_candidates")
    @classmethod
    def _validate_decision_candidates(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        if len(value) < 1:
            raise ValueError("decision_candidates must contain at least one tool name.")
        if len(set(value)) != len(value):
            raise ValueError("decision_candidates must not contain duplicates.")
        return value

    @field_validator("on_error")
    @classmethod
    def _validate_on_error(cls, value: str) -> str:
        if value in {"fail", "skip"}:
            return value
        if value.startswith("fallback:") and len(value) > len("fallback:"):
            return value
        raise ValueError(
            f"on_error must be 'fail', 'skip', or 'fallback:<tool_name>'; got '{value}'."
        )

    @model_validator(mode="after")
    def _check_tool_name_in_candidates(self) -> FlowStep:
        """Ensure ``tool_name`` is itself one of the ``decision_candidates``.

        ``DecisionContext`` documents ``default_tool_name`` (the step's
        ``tool_name``) as always present in ``candidates``, and a callback that
        returns the default must clear the executor's membership check.  Reject
        configurations where the default is not a candidate so the gap fails at
        construction rather than at execution time.
        """
        if self.decision_candidates is not None and self.tool_name not in self.decision_candidates:
            raise ValueError(
                f"tool_name '{self.tool_name}' must be a member of decision_candidates "
                f"{self.decision_candidates!r}; it is the default a callback may return."
            )
        return self

    @property
    def display_name(self) -> str:
        """A stable non-empty label for this step (issue #75).

        Returns :attr:`tool_name` for a tool step or :attr:`flow_name` for a
        composed sub-flow step.  The ``_check_tool_or_flow`` validator
        guarantees exactly one is set, so the result is always a ``str`` —
        useful for logs, error messages, and trace records that should not
        carry ``None``.
        """
        name = self.tool_name or self.flow_name
        assert name is not None  # guaranteed by _check_tool_or_flow
        return name

    @staticmethod
    def contract_ref_from(cls: type[BaseModel]) -> str:
        """Return a ``"module:qualname"`` ref string for *cls* (issue #172).

        Convenience helper mirroring :meth:`Flow.schema_ref_from`.
        """
        return _qualified_name(cls)

    @property
    def resolved_input_contract(self) -> type[BaseModel] | None:
        """Resolve :attr:`input_contract` to a class, or ``None`` if unset.

        Raises:
            FlowSerializationError: When the ref cannot be resolved or does
                not point to a :class:`BaseModel` subclass.
        """
        if self.input_contract is None:
            return None
        return resolve_class_ref(self.input_contract, expected_base=BaseModel)

    @property
    def resolved_output_contract(self) -> type[BaseModel] | None:
        """Resolve :attr:`output_contract` to a class, or ``None`` if unset.

        Raises:
            FlowSerializationError: When the ref cannot be resolved or does
                not point to a :class:`BaseModel` subclass.
        """
        if self.output_contract is None:
            return None
        return resolve_class_ref(self.output_contract, expected_base=BaseModel)


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
        the flow author explicitly opts out by setting ``deterministic=False``,
        in which case the level is :class:`DeterminismLevel.NONE`.

        This property reflects flow *structure* only.  Tool-level safety
        contracts are not consulted here because the flow does not have
        access to the tool registry; consumers that want a worst-case
        composite (this property combined with constituent tools'
        :attr:`ToolSafetyContract.determinism_level` values) should merge
        the two themselves.
        """
        if not self.deterministic:
            return DeterminismLevel.NONE
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
    def from_json(cls, data: str) -> Flow:
        """Deserialize a :class:`Flow` from a JSON string (issue #14).

        Raises:
            FlowSerializationError: When the JSON payload is malformed,
                missing required fields, or describes a :class:`DAGFlow`
                instead of a :class:`Flow`.
        """
        from chainweaver.serialization import flow_from_json

        result = flow_from_json(data)
        if not isinstance(result, cls):
            raise FlowSerializationError(
                f"Expected a Flow payload but got {type(result).__name__}"
            )
        return result

    @classmethod
    def from_yaml(cls, data: str) -> Flow:
        """Deserialize a :class:`Flow` from a YAML string (issue #14).

        Requires ``pyyaml`` to be installed (``pip install chainweaver[yaml]``).

        Raises:
            FlowSerializationError: When the YAML payload is malformed,
                missing required fields, or describes a :class:`DAGFlow`
                instead of a :class:`Flow`.
        """
        from chainweaver.serialization import flow_from_yaml

        result = flow_from_yaml(data)
        if not isinstance(result, cls):
            raise FlowSerializationError(
                f"Expected a Flow payload but got {type(result).__name__}"
            )
        return result


# TODO (Phase 2): Add conditional branching — a step that inspects
# context values and selects the next step(s) at runtime.

# TODO (Phase 2): Add determinism scoring so that partially
# deterministic flows can be marked and handled appropriately.


@dataclass
class DriftInfo:
    """Describes a schema drift between a flow's stored hash and a tool's current hash.

    Attributes:
        flow_name: Name of the affected flow.
        tool_name: Name of the tool whose schema drifted.
        expected_hash: The hash stored in the flow's ``tool_schema_hashes``.
        actual_hash: The tool's current ``schema_hash``.
    """

    flow_name: str
    tool_name: str
    expected_hash: str
    actual_hash: str


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
        itself is fixed.  A DAG with no branches is
        :class:`DeterminismLevel.FULL`, and any flow that explicitly opts
        out via ``deterministic=False`` is :class:`DeterminismLevel.NONE`.
        """
        if not self.deterministic:
            return DeterminismLevel.NONE
        if any(step.branches for step in self.steps):
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
    def from_json(cls, data: str) -> DAGFlow:
        """Deserialize a :class:`DAGFlow` from a JSON string (issue #14).

        Raises:
            FlowSerializationError: When the JSON payload is malformed,
                missing required fields, or describes a :class:`Flow`
                instead of a :class:`DAGFlow`.
        """
        from chainweaver.serialization import flow_from_json

        result = flow_from_json(data)
        if not isinstance(result, cls):
            raise FlowSerializationError(
                f"Expected a DAGFlow payload but got {type(result).__name__}"
            )
        return result

    @classmethod
    def from_yaml(cls, data: str) -> DAGFlow:
        """Deserialize a :class:`DAGFlow` from a YAML string (issue #14).

        Raises:
            FlowSerializationError: When ``pyyaml`` is not available or when
                the payload is malformed or refers to a :class:`Flow`.
        """
        from chainweaver.serialization import flow_from_yaml

        result = flow_from_yaml(data)
        if not isinstance(result, cls):
            raise FlowSerializationError(
                f"Expected a DAGFlow payload but got {type(result).__name__}"
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
