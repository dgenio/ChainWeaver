"""Reusable step and retry definitions for flows."""

from __future__ import annotations

import random
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from chainweaver.flow.refs import _qualified_name, resolve_class_ref


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
            SchemaRefPolicyError: When an active schema-ref policy (issue
                #345) rejects a ref's module path.
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

            If a value is a string it is treated as a lookup in the context.
            A plain key (e.g. ``"value"``) is a top-level lookup; a string that
            starts with ``/`` is an RFC-6901 JSON pointer (issue #387) resolved
            against the nested context (e.g. ``"/user/address/city"`` or
            ``"/items/0/id"``).  A top-level key that literally starts with
            ``/`` is addressed with the ``~1`` escape (the key ``"/raw"`` is the
            pointer ``"/~1raw"``).  If a value is any other type (int, float,
            bool, …) it is used as a literal constant.

            An empty mapping (the default) means the tool receives the full
            current context as-is.
        output_mapping: Optional ``{context_key: output_key}`` mapping applied
            to the tool's *validated* outputs before they merge into the
            accumulated context (issue #386).  When ``None`` (the default) every
            output key merges verbatim — the historical behaviour.  When set,
            only the listed output keys merge, each renamed to its context key;
            an unlisted output key is dropped, and a listed ``output_key`` the
            tool did not produce raises
            :class:`~chainweaver.exceptions.OutputMappingError`.  The raw,
            unmapped outputs are still recorded on the step's
            :class:`~chainweaver.executor.StepRecord`; the mapping affects only
            the context merge.
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
    output_mapping: dict[str, str] | None = None
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
