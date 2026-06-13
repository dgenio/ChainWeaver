"""Flow executor for ChainWeaver.

The :class:`FlowExecutor` runs a registered :class:`~chainweaver.flow.Flow`
step-by-step without any LLM involvement between steps.  All data passing is
structured and schema-validated via Pydantic.

Every :meth:`FlowExecutor.execute_flow` call produces a fully serializable
:class:`ExecutionResult` that doubles as an execution trace: it carries a
unique ``trace_id``, wall-clock timestamps, and per-step ``duration_ms``
measurements.  Errors are stored as ``error_type`` / ``error_message``
strings so the result is JSON-serializable end-to-end.
"""

from __future__ import annotations

import asyncio
import contextlib
import queue
import threading
import time
import uuid
from collections.abc import Callable, Iterable, Iterator
from datetime import datetime, timezone
from enum import Enum
from graphlib import TopologicalSorter
from typing import Any, NoReturn

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from tenacity import RetryError, Retrying, retry_if_exception_type, stop_after_attempt, wait_fixed

from chainweaver._execution import merge_step_outputs
from chainweaver.cache import StepCache, StepCacheKey, compute_input_value_hash
from chainweaver.cancellation import CancellationToken
from chainweaver.checkpoint import Checkpointer, ExecutionSnapshot
from chainweaver.contracts import evaluate_predicate
from chainweaver.cost import CostProfile, CostReport, compute_cost_report
from chainweaver.decisions import (
    DecisionCallable,
    DecisionCallback,
    DecisionContext,
    coerce_decision_callback,
)
from chainweaver.events import FlowEvent
from chainweaver.exceptions import (
    AsyncLaneUnsupportedError,
    CheckpointDriftError,
    CheckpointerNotConfiguredError,
    CheckpointNotFoundError,
    DecisionCallbackError,
    FlowCancelledError,
    FlowCompositionError,
    FlowExecutionError,
    FlowNotFoundError,
    FlowStatusError,
    InputMappingError,
    PredicateSyntaxError,
    SchemaValidationError,
    ToolNotFoundError,
    ToolOutputSizeError,
    ToolTimeoutError,
)
from chainweaver.flow import (
    DAGFlow,
    DAGFlowStep,
    DriftInfo,
    FlowStatus,
    FlowStep,
    RetryPolicy,
    validate_dag_topology,
)
from chainweaver.log_utils import (
    RedactionPolicy,
    get_logger,
    log_step_end,
    log_step_error,
    log_step_start,
)
from chainweaver.middleware import (
    BaseMiddleware,
    FlowEndContext,
    FlowExecutorMiddleware,
    FlowStartContext,
    StepEndContext,
    StepStartContext,
)
from chainweaver.observation import TraceRecorder
from chainweaver.registry import AnyFlow, FlowRegistry
from chainweaver.tools import Tool

_logger = get_logger("chainweaver.executor")
_middleware_logger = get_logger("chainweaver.middleware")


def _now_utc() -> datetime:
    """Return the current UTC time as a timezone-aware ``datetime``."""
    return datetime.now(timezone.utc)


def _new_trace_id() -> str:
    """Return a fresh UUID4 hex string for trace correlation."""
    return uuid.uuid4().hex


def _exc_to_strings(exc: Exception) -> tuple[str, str]:
    """Render an exception as ``(error_type, error_message)`` strings."""
    return type(exc).__name__, str(exc)


class _StreamSentinel:
    """Internal marker placed on the event queue to signal completion."""


_STREAM_SENTINEL: _StreamSentinel = _StreamSentinel()


class _StreamCollectorMiddleware(BaseMiddleware):
    """Per-call middleware that pushes lifecycle events onto a queue.

    Used by :meth:`FlowExecutor.stream_flow` to bridge the lifecycle
    hook surface to a generator yielding :class:`FlowEvent` payloads.
    """

    def __init__(self, events: queue.Queue[FlowEvent | _StreamSentinel]) -> None:
        self._events = events

    def on_flow_start(self, ctx: FlowStartContext) -> None:
        self._events.put(
            FlowEvent(
                kind="flow_start",
                flow_name=ctx.flow_name,
                trace_id=ctx.trace_id,
                timestamp=_now_utc(),
                flow_version=ctx.flow_version,
                initial_input=dict(ctx.initial_input),
                total_steps=ctx.total_steps,
            )
        )

    def on_step_start(self, ctx: StepStartContext) -> None:
        self._events.put(
            FlowEvent(
                kind="step_start",
                flow_name=ctx.flow_name,
                trace_id=ctx.trace_id,
                timestamp=_now_utc(),
                step_index=ctx.step_index,
                tool_name=ctx.tool_name,
                inputs=dict(ctx.inputs),
            )
        )

    def on_step_end(self, ctx: StepEndContext) -> None:
        self._events.put(
            FlowEvent(
                kind="step_end",
                flow_name=ctx.flow_name,
                trace_id=ctx.trace_id,
                timestamp=_now_utc(),
                step_index=ctx.step_record.step_index,
                tool_name=ctx.step_record.tool_name,
                step_record=ctx.step_record,
            )
        )

    def on_flow_end(self, ctx: FlowEndContext) -> None:
        self._events.put(
            FlowEvent(
                kind="flow_end",
                flow_name=ctx.flow_name,
                trace_id=ctx.trace_id,
                timestamp=_now_utc(),
                result=ctx.result,
            )
        )


def _schema_field_shape(schema: type[BaseModel]) -> dict[str, str]:
    """Return ``{field_name: type_repr}`` for a Pydantic schema.

    Used by :meth:`FlowExecutor.explain_flow` to project per-step input and
    output shapes without instantiating the model.
    """
    shape: dict[str, str] = {}
    for name, info in schema.model_fields.items():
        annotation = info.annotation
        type_repr = getattr(annotation, "__name__", None) or str(annotation)
        shape[name] = type_repr
    return shape


class StepPlan(BaseModel):
    """Static plan for a single step (issue #73).

    Captures everything :meth:`FlowExecutor.explain_flow` knows about a step
    *without* calling its tool function.  Schema fields are reported as
    ``{field_name: type_str}`` pairs derived from
    ``BaseModel.model_fields``.

    Attributes:
        step_index: Zero-based position of the step in the flow.
        tool_name: Name of the tool the step would invoke.
        input_sources: For each tool input field, a human-readable
            description of where the value would come from
            (``"context['key']"``, ``"literal(<value>)"``, or
            ``"context (full)"`` for an empty mapping).
        input_schema: ``{field_name: type_str}`` for the tool's
            ``input_schema``.  Empty when the tool is unresolved.
        output_schema: ``{field_name: type_str}`` for the tool's
            ``output_schema``.  Empty when the tool is unresolved.
        unresolved_keys: Mapping keys that would not resolve against the
            current cumulative context (warnings, not errors).
        warnings: Free-form warnings flagged for this step (e.g. the
            tool is not registered).
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    step_index: int
    tool_name: str
    input_sources: dict[str, str]
    input_schema: dict[str, str] = Field(default_factory=dict)
    output_schema: dict[str, str] = Field(default_factory=dict)
    unresolved_keys: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class ExecutionPlan(BaseModel):
    """A read-only execution plan returned by :meth:`FlowExecutor.explain_flow`.

    The plan never calls any tool functions; it only inspects the flow,
    its registered tools, and Pydantic schemas.  Any unresolvable input
    mappings are flagged as warnings instead of raising exceptions.

    Attributes:
        flow_name: Name of the flow that was explained.
        step_count: Number of steps in the flow.
        steps: Per-step :class:`StepPlan` records, in order.
        final_context_shape: ``{field_name: type_str}`` for the keys that
            would be present in the cumulative context after all steps,
            assuming every tool succeeded.
        all_resolvable: ``True`` when no step has unresolved mapping keys
            or warnings.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    flow_name: str
    step_count: int
    steps: list[StepPlan] = Field(default_factory=list)
    final_context_shape: dict[str, str] = Field(default_factory=dict)
    all_resolvable: bool = True

    def __str__(self) -> str:
        check = "OK" if self.all_resolvable else "WARN"
        lines = [
            f"Flow: {self.flow_name} ({self.step_count} steps) [{check}]",
            "─" * 40,
        ]
        for plan in self.steps:
            lines.append(f"Step {plan.step_index}: {plan.tool_name}")
            for tgt, src in plan.input_sources.items():
                lines.append(f"  in  {tgt}: {src}")
            if plan.output_schema:
                shape = ", ".join(f"{k}: {v}" for k, v in plan.output_schema.items())
                lines.append(f"  out {{{shape}}}")
            for warn in plan.warnings:
                lines.append(f"  ! {warn}")
            lines.append("")
        if self.final_context_shape:
            shape = ", ".join(f"{k}: {v}" for k, v in self.final_context_shape.items())
            lines.append(f"Final context: {{{shape}}}")
        lines.append(
            "✓ All input mappings resolvable"
            if self.all_resolvable
            else "⚠ Unresolved mappings present"
        )
        return "\n".join(lines)


class ReplayMode(str, Enum):
    """Modes accepted by :meth:`FlowExecutor.replay_flow`.

    - ``VERIFY`` re-runs the flow and compares each step's outputs against
      the recorded trace; differences are reported as :class:`StepDiff`
      entries on the :class:`ReplayResult`.
    - ``EXECUTE`` re-runs the flow with the recorded ``initial_input``
      and returns the new result without comparing it to the original.
    - ``STRICT`` is a compatibility alias for ``VERIFY``.
    - ``SKIP_VALIDATION`` is a compatibility alias for ``EXECUTE``.
    """

    VERIFY = "verify"
    STRICT = "verify"
    EXECUTE = "execute"
    SKIP_VALIDATION = "execute"


class StepDiff(BaseModel):
    """A single field-level difference between an original and replayed step."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    step_index: int
    tool_name: str
    field: str
    expected: Any
    actual: Any


class ReplayResult(BaseModel):
    """Outcome of :meth:`FlowExecutor.replay_flow`.

    Attributes:
        original_trace_id: The ``trace_id`` of the :class:`ExecutionResult`
            that was replayed.
        new_result: The fresh :class:`ExecutionResult` produced by the
            replay.
        mode: The :class:`ReplayMode` requested.
        diffs: Field-level differences (only populated in
            :attr:`ReplayMode.VERIFY` mode).
        all_steps_match: ``True`` when no diffs were detected (always
            ``True`` for ``EXECUTE`` mode and for empty flows).
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    original_trace_id: str
    new_result: ExecutionResult
    mode: ReplayMode
    diffs: list[StepDiff] = Field(default_factory=list)
    all_steps_match: bool = True


class StepRecord(BaseModel):
    """Record of a single executed step.

    Attributes:
        step_index: Position of this record in the flow.  For normal steps
            this is the zero-based step index.  Two sentinel values are
            used for flow-level schema validation:
            ``-1`` — input validation (before any step runs),
            ``len(steps)`` — output validation (after all steps complete).
        tool_name: Name of the tool that was invoked (or the flow name for
            flow-level validation records).
        inputs: The validated inputs that were passed to the tool.
        outputs: The validated outputs produced by the tool, or ``None`` if
            the step failed.
        error_type: Exception class name (e.g. ``"FlowExecutionError"``)
            when the step failed, or ``None`` on success.
        error_message: Human-readable error message when the step failed,
            or ``None`` on success.
        success: ``True`` when the step completed without error (including
            steps that were retried successfully).
        started_at: UTC timestamp when the step began.
        ended_at: UTC timestamp when the step finished (success or failure).
        duration_ms: Wall-clock duration of the step in milliseconds,
            measured with :func:`time.perf_counter`.
        retry_count: Number of retries beyond the initial invocation.  ``0``
            when no retry policy is configured or the first attempt
            succeeded.
        retry_errors: Error messages from each failed attempt, in order.
            Empty when no retries occurred.
        skipped: ``True`` when the step exhausted its retries and the
            configured ``on_error="skip"`` action let the flow continue
            without merging any output.
        cached: ``True`` when the step's outputs were served from the
            executor's ``step_cache`` (issue #127) and the tool's
            callable was not invoked.  ``duration_ms`` for cached steps
            reflects only the cache lookup time.  ``False`` for normal
            executions (the default).
        fallback_used: ``True`` when the primary tool failed and the
            step's ``on_error="fallback:<tool_name>"`` policy invoked a
            fallback tool (issue #176).  Set regardless of whether the
            fallback itself succeeded or failed; ``False`` for normal
            execution, retry-success, ``skip``, and ``fail`` paths.
        flow_name: For a composed sub-flow step (issue #75), the name of the
            sub-flow that was executed; ``None`` for ordinary tool steps.
            When set, ``tool_name`` mirrors it so existing trace consumers
            still see a stable display name.
        sub_result: For a composed sub-flow step (issue #75), the nested
            :class:`ExecutionResult` of the sub-flow run, so the parent trace
            retains the full sub-flow execution log.  ``None`` for tool steps.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    step_index: int
    tool_name: str
    inputs: dict[str, Any]
    outputs: dict[str, Any] | None = None
    error_type: str | None = None
    error_message: str | None = None
    success: bool = True
    started_at: datetime
    ended_at: datetime
    duration_ms: float
    retry_count: int = 0
    retry_errors: list[str] = Field(default_factory=list)
    skipped: bool = False
    cached: bool = False
    fallback_used: bool = False
    flow_name: str | None = None
    sub_result: ExecutionResult | None = None


class ExecutionResult(BaseModel):
    """The final result of a :meth:`FlowExecutor.execute_flow` call.

    ``ExecutionResult`` is a fully serializable execution trace: every field
    round-trips through :meth:`pydantic.BaseModel.model_dump_json` and
    :meth:`pydantic.BaseModel.model_validate_json`.

    Attributes:
        flow_name: Name of the flow that was executed.
        flow_version: The exact registered version of the flow that
            executed (issue #201).  When :meth:`FlowExecutor.execute_flow`
            is called with ``version=...`` this is that version; otherwise
            it is the latest registered version that was resolved.  Audit,
            replay, and external-routing feedback loops use this to
            correlate a result with the precise flow definition that ran.
        success: ``True`` when all steps completed without error.
        final_output: The merged execution context (initial input combined
            with all step outputs), or ``None`` on failure.
        execution_log: Ordered list of :class:`StepRecord` objects.  Contains
            one entry per executed tool step.  When ``input_schema`` or
            ``output_schema`` is set on the flow and the corresponding
            validation **fails**, a synthetic record is appended carrying
            the validation error (``step_index == -1`` for input failures,
            ``step_index == len(steps)`` for output failures); successful
            validations do not produce records, so the log is unchanged
            on the happy path.
        trace_id: UUID4 hex string assigned at the start of the execution.
            Use this to correlate the result with logs or external systems.
        started_at: UTC timestamp when the execution began.
        ended_at: UTC timestamp when the execution finished.
        total_duration_ms: Wall-clock duration of the full execution in
            milliseconds, measured with :func:`time.perf_counter`.  For
            executions produced by :meth:`FlowExecutor.resume_flow`
            (issue #128), this covers **only** the resume process's
            wall-clock — not the elapsed time between
            ``started_at`` (captured in the original, crashed run) and
            ``ended_at``.  In other words, ``total_duration_ms`` is the
            time the executor *spent running tools* and is not
            equivalent to ``(ended_at - started_at)`` after a resume.
            Recovered step records still carry their original
            ``started_at``/``ended_at`` timestamps; freshly executed
            records carry resume-process timestamps.
        cost_report: Optional :class:`~chainweaver.cost.CostReport` estimating
            the LLM-call cost and latency avoided by running this compiled
            flow.  ``None`` unless the executor was constructed with a
            ``cost_profile``.
        initial_input: The initial context dictionary that was passed to
            ``execute_flow``.  Stored on the result so the trace can be
            replayed deterministically by :meth:`FlowExecutor.replay_flow`.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    flow_name: str
    flow_version: str
    success: bool
    final_output: dict[str, Any] | None
    execution_log: list[StepRecord] = Field(default_factory=list)
    trace_id: str
    started_at: datetime
    ended_at: datetime
    total_duration_ms: float
    cost_report: CostReport | None = None
    initial_input: dict[str, Any] = Field(default_factory=dict)

    def to_mermaid(self, *, direction: str = "LR") -> str:
        """Return a Mermaid graph overlaying this result on the flow (#79)."""
        from chainweaver.viz import result_to_mermaid

        return result_to_mermaid(self, direction=direction)


# ``StepRecord.sub_result`` (issue #75) is a forward reference to
# ``ExecutionResult``, which is defined after ``StepRecord``.  Rebuild the
# model now that both classes exist so Pydantic can bind the recursive
# (StepRecord ↔ ExecutionResult) schema.
StepRecord.model_rebuild()


class FlowExecutor:
    """Executes registered flows deterministically.

    The executor maintains a :class:`~chainweaver.registry.FlowRegistry` of
    flows and a separate registry of :class:`~chainweaver.tools.Tool` objects.
    On each :meth:`execute_flow` call it:

    1. Resolves the flow from the registry.
    2. Iterates over steps sequentially (or level-by-level for DAGs).
    3. Resolves each step's inputs by mapping context keys (or literal values).
    4. Validates inputs against the tool's *input_schema*.
    5. Calls the tool's callable.
    6. Validates outputs against the tool's *output_schema*.
    7. Merges the outputs into the shared context.
    8. Records every step in an :class:`ExecutionResult` together with a
       unique trace id, wall-clock timestamps, and per-step durations.

    There are **no LLM calls** at any point in this process.

    **Concurrency contract** (issue #336): a single :class:`FlowExecutor`
    instance supports **concurrent** :meth:`execute_flow`,
    :meth:`execute_flow_async`, and :meth:`stream_flow` calls.  Run-scoped
    state — the stream event collector and (where applicable) replay/resume
    markers — is held per-thread on a :class:`threading.local` slot rather
    than the shared instance, so concurrent runs never dispatch each other's
    lifecycle events.  The bundled :class:`~chainweaver.cache.InMemoryStepCache`
    and :class:`~chainweaver.checkpoint.InMemoryCheckpointer` are internally
    locked, so sharing them across one executor's concurrent runs is safe.

    The contract has one rule: **mutating operations must not run concurrently
    with executions.**  :meth:`register_tool`, :meth:`add_middleware`,
    :meth:`remove_middleware`, and :meth:`accept_drift` mutate shared
    configuration and are expected to happen during setup, before (or between)
    runs — not while another thread is mid-execution.  Read-only execution is
    concurrency-safe; reconfiguration is not.

    See ``tests/test_executor_concurrency.py`` for the enforced stress tests.

    Args:
        registry: The :class:`~chainweaver.registry.FlowRegistry` that holds
            the flows to execute.
        cost_profile: Optional :class:`~chainweaver.cost.CostProfile` enabling
            per-execution cost-avoided estimation.  When set, every
            :class:`ExecutionResult` carries a populated ``cost_report``;
            when ``None`` (the default), ``cost_report`` stays ``None``.
        redaction_policy: Optional
            :class:`~chainweaver.log_utils.RedactionPolicy` applied to log
            output for every step.  When ``None`` (the default), inputs and
            outputs are logged verbatim.  The trace itself
            (``ExecutionResult.execution_log``) always stores raw values —
            redaction is for logs and display only.
        trace_recorder: Optional
            :class:`~chainweaver.observation.TraceRecorder` that captures
            an :class:`~chainweaver.observation.ObservedTrace` for every
            ``execute_flow`` call so ad-hoc agent sequences and compiled
            flow runs share a uniform observation store.
        max_composition_depth: Maximum nesting depth for ``flow_name``
            sub-flow references (issue #75).  Defaults to ``10``.  The
            composition graph is validated before execution; deeper chains
            (or cycles) raise
            :class:`~chainweaver.exceptions.FlowCompositionError`.
        max_step_concurrency: Maximum number of independent steps within a
            single DAG level that :meth:`execute_flow_async` dispatches
            concurrently (issue #344).  Defaults to ``1`` (strictly
            sequential — bit-identical to the historical behaviour).  Values
            ``> 1`` bound concurrent dispatch via an
            :class:`asyncio.Semaphore`; results are deterministic regardless of
            the setting, but opted-in tools must be safe to run concurrently.
            The synchronous :meth:`execute_flow` lane currently always runs
            level steps sequentially.

    Example::

        executor = FlowExecutor(registry=my_registry)
        executor.register_tool(double_tool)
        executor.register_tool(add_tool)
        executor.register_tool(format_tool)

        result = executor.execute_flow("double_add_format", {"number": 5})
        print(result.final_output)  # {"result": "Final value: 20"}
        print(result.trace_id)      # e.g. "9b1c8e0d2a5f4..."
    """

    def __init__(
        self,
        registry: FlowRegistry,
        *,
        cost_profile: CostProfile | None = None,
        redaction_policy: RedactionPolicy | None = None,
        trace_recorder: TraceRecorder | None = None,
        middleware: list[FlowExecutorMiddleware] | None = None,
        step_cache: StepCache | None = None,
        checkpointer: Checkpointer | None = None,
        delete_on_success: bool = True,
        decision_callback: DecisionCallback | DecisionCallable | None = None,
        discover_plugins: bool = False,
        max_composition_depth: int = 10,
        max_step_concurrency: int = 1,
    ) -> None:
        if max_step_concurrency < 1:
            raise ValueError(f"max_step_concurrency must be >= 1, got {max_step_concurrency}.")
        self._registry = registry
        self._tools: dict[str, Tool] = {}
        # Opt-in concurrent execution of independent steps within a DAG level
        # (issue #344).  ``1`` (the default) preserves the historical
        # strictly-sequential behaviour exactly.  Higher values bound the number
        # of a level's steps that ``execute_flow_async`` dispatches at once via
        # an :class:`asyncio.Semaphore`; ``StepRecord`` ordering, context-merge
        # results, and sibling-collision detection stay identical regardless of
        # the setting.  Tools must be safe to run concurrently to opt in.
        self._max_step_concurrency = max_step_concurrency
        self._cost_profile = cost_profile
        self._redaction_policy = redaction_policy
        self._trace_recorder = trace_recorder
        self._middleware: list[FlowExecutorMiddleware] = list(middleware) if middleware else []
        # Per-run, per-thread middleware (issue #336).  ``stream_flow`` and any
        # other run-scoped observer registers here instead of mutating the
        # shared ``self._middleware`` list, so two concurrent runs on one
        # executor never dispatch each other's events.  Keyed by thread because
        # each run executes within a single thread (the calling thread, or the
        # stream worker thread).
        self._local = threading.local()
        # Guided decision-point callback (issue #102).  Wraps a bare
        # callable in an adapter so the executor can call
        # ``self._decision_callback.decide(ctx)`` uniformly regardless
        # of whether the user passed a class or a function.  ``None``
        # means decision_candidates steps fall back to their static
        # ``tool_name``.
        self._decision_callback: DecisionCallback | None = coerce_decision_callback(
            decision_callback
        )
        # Step-result cache (issue #127).  ``None`` (the default)
        # disables caching entirely — every tool runs every call.
        # When set, eligible step outputs are read from / written to
        # this cache before the tool callable runs.
        self._step_cache = step_cache
        # ``True`` while inside replay_flow / _replay_linear_from so
        # the cache is bypassed — replay must always re-execute (per
        # the existing replay semantics).
        self._in_replay = False
        # Crash-resume checkpointer (issue #128).  When set, an
        # ExecutionSnapshot is written after every successful linear
        # step or DAG level.  On terminal completion the snapshot is
        # deleted iff ``delete_on_success`` is ``True``.
        self._checkpointer = checkpointer
        self._delete_on_success = delete_on_success
        # Resumption state — populated by ``resume_flow`` before
        # invoking the relevant ``_execute_*`` path so the loops know
        # where to start and which records to prepend.
        self._resume_snapshot: ExecutionSnapshot | None = None
        # Version of the flow currently executing (issue #201).  Set at the
        # top of every result-producing path so ``_make_result`` can stamp
        # ``ExecutionResult.flow_version`` without threading the value
        # through ~30 call sites.  Sub-flow composition (issue #75) recurses
        # through ``execute_flow``; ``_execute_step`` save/restores this
        # around the recursive call so the parent's value is not clobbered.
        # Like ``_in_replay`` / ``_resume_snapshot`` this assumes the
        # documented "one executor per concurrent run" contract.
        self._active_flow_version: str = ""
        # Flow composition (issue #75): the maximum nesting depth of
        # ``flow_name`` sub-flow references.  Checked statically before
        # execution so runaway / cyclic recursion fails loudly.
        self._max_composition_depth = max_composition_depth
        # Plugin discovery (issue #130).  When ``True``, every Tool
        # advertised under the ``chainweaver.tools`` entry-point group
        # is registered eagerly so end-users don't have to call
        # ``register_tool`` once per installed plugin package.  Run
        # last so all internal state is in place before user-supplied
        # tools go through the normal ``register_tool`` path (which
        # triggers drift detection).  Off by default to keep startup
        # cheap and to quarantine third-party plugin failures.
        if discover_plugins:
            from chainweaver.plugins import discover_tools

            for plugin_tool in discover_tools():
                self.register_tool(plugin_tool)

    @property
    def registry(self) -> FlowRegistry:
        """The :class:`~chainweaver.registry.FlowRegistry` backing this executor.

        Read-only accessor so callers (notably
        :class:`chainweaver.mcp.FlowServer`) can enumerate registered
        flows without reaching into the private ``_registry`` attribute.
        """
        return self._registry

    def add_middleware(self, middleware: FlowExecutorMiddleware) -> None:
        """Register an additional :class:`FlowExecutorMiddleware`.

        Middlewares fire in registration order; calling :meth:`add_middleware`
        appends to the end of the registration chain.

        Args:
            middleware: An object implementing any subset of the
                :class:`~chainweaver.middleware.FlowExecutorMiddleware`
                hooks.  Hooks with default no-op behavior may be omitted.
        """
        self._middleware.append(middleware)

    def remove_middleware(self, middleware: FlowExecutorMiddleware) -> None:
        """Unregister a previously added :class:`FlowExecutorMiddleware`.

        Removes the first occurrence of *middleware* (matched by ``==``,
        i.e. identity for the usual unique-instance case) from the
        registration chain.  A middleware that is not currently registered
        is silently ignored, so callers can unregister defensively from a
        ``finally`` block without guarding against double-removal.

        Args:
            middleware: The middleware instance to remove.
        """
        with contextlib.suppress(ValueError):
            self._middleware.remove(middleware)

    # ------------------------------------------------------------------
    # Middleware dispatch
    #
    # Hook exceptions are caught and logged at WARNING; observability
    # bugs must never abort a flow execution (issue #131).  Hooks fire
    # in registration order.
    # ------------------------------------------------------------------

    def _fire_hook(
        self,
        hook: str,
        ctx: FlowStartContext | StepStartContext | StepEndContext | FlowEndContext,
    ) -> None:
        """Dispatch *hook* to every registered middleware, catching exceptions.

        Middlewares that do not define *hook* are silently skipped so that
        users can implement only the hooks they care about (the ones they
        do define still satisfy the :class:`FlowExecutorMiddleware`
        Protocol structurally — partial implementers typically inherit
        from :class:`~chainweaver.middleware.BaseMiddleware` to satisfy
        strict static type checkers).

        Hooks that raise are logged at ``WARNING`` and the iteration
        continues — middleware bugs never abort a flow.
        """
        run_scoped = getattr(self._local, "middleware", None)
        chain = self._middleware if not run_scoped else [*self._middleware, *run_scoped]
        for idx, mw in enumerate(chain):
            handler = getattr(mw, hook, None)
            if handler is None:
                continue
            try:
                handler(ctx)
            except Exception as exc:
                _middleware_logger.warning(
                    "Middleware %d (%s) raised in %s: %s",
                    idx,
                    type(mw).__name__,
                    hook,
                    exc,
                )

    @contextlib.contextmanager
    def _scoped_middleware(self, middleware: FlowExecutorMiddleware) -> Iterator[None]:
        """Register *middleware* for the duration of the current thread's run.

        Run-scoped middleware lives on a :class:`threading.local` slot rather
        than the shared ``self._middleware`` list, so concurrent runs on one
        executor (issue #336) never see each other's run-scoped observers.
        """
        existing: list[FlowExecutorMiddleware] = getattr(self._local, "middleware", [])
        self._local.middleware = [*existing, middleware]
        try:
            yield
        finally:
            self._local.middleware = existing

    def _fire_flow_start(self, ctx: FlowStartContext) -> None:
        self._fire_hook("on_flow_start", ctx)

    def _fire_step_start(self, ctx: StepStartContext) -> None:
        self._fire_hook("on_step_start", ctx)

    def _fire_step_end(self, ctx: StepEndContext) -> None:
        self._fire_hook("on_step_end", ctx)

    def _fire_flow_end(self, ctx: FlowEndContext) -> None:
        self._fire_hook("on_flow_end", ctx)

    def register_tool(self, tool: Tool) -> None:
        """Register a :class:`~chainweaver.tools.Tool` with the executor.

        If a tool with the same name already exists and its schema has changed,
        affected flows are marked ``NEEDS_REVIEW``.

        Args:
            tool: The tool to register.
        """
        if tool.name in self._tools:
            old_tool = self._tools[tool.name]
            if old_tool.schema_hash != tool.schema_hash:
                self._handle_schema_drift(old_tool, tool)
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> Tool:
        """Return a registered tool by name.

        Args:
            name: Tool name.

        Raises:
            ToolNotFoundError: When no tool with *name* has been registered.
        """
        if name not in self._tools:
            raise ToolNotFoundError(name)
        return self._tools[name]

    @property
    def registered_tools(self) -> dict[str, Tool]:
        """Return a snapshot of currently registered tools (issue #178).

        Returns a *copy* of the internal ``{name: Tool}`` registry, so callers
        can safely iterate or mutate the returned dict without affecting the
        executor's state.  Use this instead of reaching for the private
        ``_tools`` attribute when computing tool schema hashes, building
        compatibility reports, or attestation artifacts.
        """
        return dict(self._tools)

    def with_replaced_tools(self, tools: Iterable[Tool]) -> FlowExecutor:
        """Return a new executor sharing this one's configuration and registry.

        The clone preserves every executor-level setting (cost profile,
        redaction policy, trace recorder, middleware, step cache, checkpointer,
        ``delete_on_success`` flag, and decision callback) but starts with an
        empty tool set populated from *tools*.  Plugin discovery is not re-run,
        because the caller passes the already-resolved tools explicitly.

        This is used by the fuzzing harness to run a flow under the same
        executor configuration with fault-injecting tool wrappers, so behavior
        does not diverge depending on whether fault injection is enabled
        (issue #220 review follow-up).

        Args:
            tools: Tools to register on the cloned executor.

        Returns:
            A new :class:`FlowExecutor` with matching configuration.
        """
        clone = FlowExecutor(
            registry=self._registry,
            cost_profile=self._cost_profile,
            redaction_policy=self._redaction_policy,
            trace_recorder=self._trace_recorder,
            middleware=list(self._middleware),
            step_cache=self._step_cache,
            checkpointer=self._checkpointer,
            delete_on_success=self._delete_on_success,
            decision_callback=self._decision_callback,
            max_composition_depth=self._max_composition_depth,
            max_step_concurrency=self._max_step_concurrency,
        )
        for tool in tools:
            clone.register_tool(tool)
        return clone

    def get_drift_report(self) -> list[DriftInfo]:
        """Compare registered tools' current schema hashes against each flow's snapshot.

        Returns:
            A list of :class:`~chainweaver.flow.DriftInfo` objects for each mismatch.
        """
        report: list[DriftInfo] = []
        for flow in self._registry.list_flows():
            if flow.tool_schema_hashes is None:
                continue
            for tool_name, expected_hash in flow.tool_schema_hashes.items():
                if tool_name in self._tools:
                    actual_hash = self._tools[tool_name].schema_hash
                    if expected_hash != actual_hash:
                        report.append(
                            DriftInfo(
                                flow_name=flow.name,
                                tool_name=tool_name,
                                expected_hash=expected_hash,
                                actual_hash=actual_hash,
                            )
                        )
        return report

    def accept_drift(self, flow_name: str, *, version: str | None = None) -> None:
        """Re-snapshot tool_schema_hashes for a flow and set status back to ACTIVE.

        Args:
            flow_name: The name of the flow to accept drift for.
            version: If provided, target the given version. Otherwise target the
                latest registered version. Mirrors
                :meth:`~chainweaver.registry.FlowRegistry.get_flow`.

        Raises:
            FlowNotFoundError: When no flow with *flow_name* (and *version*) is
                registered.
        """
        flow = self._registry.get_flow(flow_name, version=version)
        new_hashes: dict[str, str] = {}
        for step in flow.steps:
            if step.display_name in self._tools:
                new_hashes[step.display_name] = self._tools[step.display_name].schema_hash
        # Copy-on-write via the registry (issue #335): never mutate the shared
        # registry-held Flow in place — that would silently alter the state
        # observed by other holders of the same object (e.g. a FlowServer).
        self._registry.update_flow_state(
            flow_name,
            version=version,
            status=FlowStatus.ACTIVE,
            tool_schema_hashes=new_hashes,
        )

    def _handle_schema_drift(self, old_tool: Tool, new_tool: Tool) -> None:
        """Mark affected flows as NEEDS_REVIEW when a tool's schema changes."""
        for flow in self._registry.list_flows():
            if flow.tool_schema_hashes is None:
                continue
            if new_tool.name not in flow.tool_schema_hashes:
                continue
            if flow.tool_schema_hashes[new_tool.name] != new_tool.schema_hash:
                self._registry.set_flow_status(
                    flow.name, FlowStatus.NEEDS_REVIEW, version=flow.version
                )
                _logger.warning(
                    "Schema drift detected: tool '%s' schema changed. "
                    "Flow '%s' version '%s' marked as NEEDS_REVIEW.",
                    new_tool.name,
                    flow.name,
                    flow.version,
                )

    def replay_flow(
        self,
        result: ExecutionResult,
        *,
        mode: ReplayMode = ReplayMode.VERIFY,
        resume_from_step: int = 0,
    ) -> ReplayResult:
        """Re-execute a flow from a previously recorded :class:`ExecutionResult`.

        ``VERIFY`` re-runs the flow with ``result.initial_input`` and
        diffs each step's outputs against the original.  ``EXECUTE`` only
        re-runs and returns the new result without comparing.

        ``resume_from_step`` (linear flows only) skips the first *N* steps
        and rebuilds the cumulative context from those steps' recorded
        outputs.  Flow-level input validation is skipped on resume since
        the original execution already validated the input.

        Args:
            result: A previously produced :class:`ExecutionResult`.  Its
                ``initial_input`` and ``execution_log`` drive the replay.
            mode: One of :class:`ReplayMode`.
            resume_from_step: Number of leading steps to skip (linear
                flows only).  ``0`` (the default) replays from the start.

        Returns:
            A :class:`ReplayResult`.

        Raises:
            FlowNotFoundError: When ``result.flow_name`` is no longer
                registered.
            ValueError: When ``resume_from_step > 0`` is requested for a
                ``DAGFlow`` (not yet supported).
        """
        flow = self._registry.get_flow(result.flow_name)

        # Bypass the step cache for the duration of replay — replay
        # must always re-execute tools (per the existing replay
        # semantics and issue #127's acceptance criteria).
        previous_in_replay = self._in_replay
        self._in_replay = True
        try:
            if resume_from_step <= 0:
                new_result = self.execute_flow(result.flow_name, dict(result.initial_input))
            else:
                if isinstance(flow, DAGFlow):
                    raise ValueError("resume_from_step is not supported for DAGFlow yet.")
                new_result = self._replay_linear_from(flow, result, resume_from_step)
        finally:
            self._in_replay = previous_in_replay

        diffs: list[StepDiff] = []
        if mode is ReplayMode.VERIFY:
            diffs = self._compute_diffs(result, new_result, resume_from_step)

        return ReplayResult(
            original_trace_id=result.trace_id,
            new_result=new_result,
            mode=mode,
            diffs=diffs,
            all_steps_match=(len(diffs) == 0),
        )

    def _replay_linear_from(
        self,
        flow: Any,
        result: ExecutionResult,
        resume_from_step: int,
    ) -> ExecutionResult:
        """Re-run *flow* starting at index *resume_from_step* with a
        context seeded from the original execution log.
        """
        self._active_flow_version = flow.version
        if resume_from_step > len(flow.steps):
            raise ValueError(
                f"resume_from_step={resume_from_step} exceeds step count {len(flow.steps)}."
            )
        # Reconstruct the context that would have existed before the
        # resume point by replaying the recorded outputs (no tool
        # invocations).
        context: dict[str, Any] = dict(result.initial_input)
        for record in result.execution_log[:resume_from_step]:
            if record.outputs:
                context.update(record.outputs)

        trace_id = _new_trace_id()
        flow_started_at = _now_utc()
        flow_t0 = time.perf_counter()
        log: list[StepRecord] = []

        self._fire_flow_start(
            FlowStartContext(
                trace_id=trace_id,
                flow_name=flow.name,
                flow_version=flow.version,
                initial_input=dict(result.initial_input),
                started_at=flow_started_at,
                total_steps=len(flow.steps),
            )
        )

        for idx in range(resume_from_step, len(flow.steps)):
            step = flow.steps[idx]
            step_record = self._execute_step(idx, step, context, flow.name, trace_id)
            log.append(step_record)

            if not step_record.success:
                return self._make_result(
                    flow_name=flow.name,
                    success=False,
                    final_output=None,
                    execution_log=log,
                    trace_id=trace_id,
                    started_at=flow_started_at,
                    perf_start=flow_t0,
                    initial_input=dict(result.initial_input),
                )

            assert step_record.outputs is not None
            context.update(step_record.outputs)

        return self._make_result(
            flow_name=flow.name,
            success=True,
            final_output=context,
            execution_log=log,
            trace_id=trace_id,
            started_at=flow_started_at,
            perf_start=flow_t0,
            initial_input=dict(result.initial_input),
        )

    def _compute_diffs(
        self,
        original: ExecutionResult,
        new: ExecutionResult,
        resume_from_step: int,
    ) -> list[StepDiff]:
        """Field-level diffs between the original and replayed step outputs."""
        diffs: list[StepDiff] = []
        for new_idx, new_step in enumerate(new.execution_log):
            original_idx = new_idx + resume_from_step
            if original_idx >= len(original.execution_log):
                break
            orig_step = original.execution_log[original_idx]
            new_out = new_step.outputs or {}
            orig_out = orig_step.outputs or {}
            if new_out == orig_out:
                continue
            for key in set(new_out) | set(orig_out):
                if new_out.get(key) != orig_out.get(key):
                    diffs.append(
                        StepDiff(
                            step_index=new_step.step_index,
                            tool_name=new_step.tool_name,
                            field=key,
                            expected=orig_out.get(key),
                            actual=new_out.get(key),
                        )
                    )
        return diffs

    def explain_flow(
        self,
        flow_name: str,
        initial_input: dict[str, Any],
    ) -> ExecutionPlan:
        """Build a static execution plan for *flow_name* without calling any tool.

        Resolves each step's input mapping against a *projected* cumulative
        context (initial input + every previous step's output schema), reports
        the schema shapes pulled from each tool's Pydantic models, and flags
        any unresolvable mapping keys as warnings.  Tool functions are
        **not** invoked.

        Args:
            flow_name: Name of the flow to explain.
            initial_input: The initial context the caller would pass to
                :meth:`execute_flow`.

        Returns:
            A populated :class:`ExecutionPlan`.

        Raises:
            FlowNotFoundError: When *flow_name* is not registered.
        """
        flow = self._registry.get_flow(flow_name)
        steps: list[FlowStep | DAGFlowStep]
        if isinstance(flow, DAGFlow):
            # Flatten DAG levels so the plan still reports a deterministic order.
            ordered: list[DAGFlowStep] = []
            for level in self._compute_dag_levels(flow):
                ordered.extend(level)
            steps = list(ordered)
        else:
            steps = list(flow.steps)

        projected_context: dict[str, str] = {k: type(v).__name__ for k, v in initial_input.items()}
        plans: list[StepPlan] = []
        any_warnings = False

        for idx, step in enumerate(steps):
            warnings: list[str] = []
            unresolved: list[str] = []
            input_schema_shape: dict[str, str] = {}
            output_schema_shape: dict[str, str] = {}

            if step.flow_name is not None:
                # Composed sub-flow step (issue #75): project the sub-flow's
                # declared output schema (if any) into the cumulative context.
                display_name = step.flow_name
                try:
                    sub_flow = self._registry.get_flow(step.flow_name)
                except FlowNotFoundError:
                    sub_flow = None
                    warnings.append(f"Sub-flow '{step.flow_name}' is not registered.")
                input_sources = self._describe_input_sources(step, projected_context, unresolved)
                if sub_flow is not None and sub_flow.output_schema is not None:
                    output_schema_shape = _schema_field_shape(sub_flow.output_schema)
                    for field_name, field_type in output_schema_shape.items():
                        projected_context[field_name] = field_type
            else:
                display_name = step.display_name or "<unknown>"
                try:
                    tool = self.get_tool(step.display_name) if step.display_name else None
                except ToolNotFoundError:
                    tool = None
                if tool is None:
                    warnings.append(f"Tool '{step.display_name}' is not registered.")

                input_sources = self._describe_input_sources(step, projected_context, unresolved)

                if tool is not None:
                    input_schema_shape = _schema_field_shape(tool.input_schema)
                    output_schema_shape = _schema_field_shape(tool.output_schema)
                    # Merge the projected output keys into the cumulative context.
                    for field_name, field_type in output_schema_shape.items():
                        projected_context[field_name] = field_type

            if unresolved:
                any_warnings = True
            if warnings:
                any_warnings = True

            plans.append(
                StepPlan(
                    step_index=idx,
                    tool_name=display_name,
                    input_sources=input_sources,
                    input_schema=input_schema_shape,
                    output_schema=output_schema_shape,
                    unresolved_keys=unresolved,
                    warnings=warnings,
                )
            )

        return ExecutionPlan(
            flow_name=flow_name,
            step_count=len(steps),
            steps=plans,
            final_context_shape=dict(projected_context),
            all_resolvable=not any_warnings,
        )

    def _describe_input_sources(
        self,
        step: FlowStep,
        projected_context: dict[str, str],
        unresolved: list[str],
    ) -> dict[str, str]:
        """Return a per-input-field description of the resolved value source."""
        if not step.input_mapping:
            return {"<all>": "context (full)"}

        sources: dict[str, str] = {}
        for target_key, raw in step.input_mapping.items():
            if isinstance(raw, str):
                if raw in projected_context:
                    sources[target_key] = f"context['{raw}']"
                else:
                    sources[target_key] = f"context['{raw}'] (UNRESOLVED)"
                    unresolved.append(raw)
            else:
                sources[target_key] = f"literal({raw!r})"
        return sources

    def execute_flow(
        self,
        flow_name: str,
        initial_input: dict[str, Any],
        *,
        version: str | None = None,
        force: bool = False,
        deadline: float | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> ExecutionResult:
        """Execute a registered flow from *initial_input*.

        Args:
            flow_name: Name of the flow to execute.
            initial_input: Initial key/value context passed to the first step.
            version: When provided, execute that exact registered flow
                version (issue #201).  When ``None`` (the default), execute
                the latest registered version for *flow_name* — preserving
                the historical behaviour.  External routers and audit/replay
                systems use this to correlate a routing decision with the
                precise flow version that ran; the version that executed is
                always recorded on :attr:`ExecutionResult.flow_version`.
            force: When ``True``, bypass the status guard and execute even if
                the flow is ``NEEDS_REVIEW`` or ``DISABLED``.
            deadline: Optional absolute wall-clock deadline in
                :func:`time.time` seconds (issue #142).  Checked **between**
                steps (and between DAG levels) — never inside a tool — so an
                in-flight step always completes.  When the deadline has
                passed at a step boundary the executor raises
                :class:`~chainweaver.exceptions.FlowCancelledError` carrying
                the partial result.
            cancel_token: Optional :class:`CancellationToken` (issue #142).
                Calling :meth:`CancellationToken.cancel` from another thread
                requests that the flow stop at its next step boundary, again
                raising :class:`~chainweaver.exceptions.FlowCancelledError`.
                Cancellation is cooperative: a tool that never returns cannot
                be force-stopped.

        Returns:
            An :class:`ExecutionResult` describing the outcome and containing
            the full execution log.  Step-level validation, input-mapping,
            and execution errors are recorded in the execution log and
            reported via ``ExecutionResult.success`` instead of being raised.

        Raises:
            FlowNotFoundError: When *flow_name* (at *version*, when given) is
                not registered.
            FlowStatusError: When the flow's status is not ``ACTIVE`` and
                *force* is ``False``.
            FlowCancelledError: When *deadline* has passed or *cancel_token*
                is cancelled at a step boundary.
        """
        flow = self._registry.get_flow(flow_name, version=version)
        self._active_flow_version = flow.version

        if not force and flow.status != FlowStatus.ACTIVE:
            raise FlowStatusError(flow_name, flow.status.value)

        # Validate sub-flow composition up front (issue #75): reject cycles,
        # over-deep nesting, and dangling references before any step runs.
        self._validate_composition(flow)

        if isinstance(flow, DAGFlow):
            return self._execute_dag_flow(
                flow, initial_input, deadline=deadline, cancel_token=cancel_token
            )

        trace_id = _new_trace_id()
        flow_started_at = _now_utc()
        flow_t0 = time.perf_counter()
        _logger.info(
            "Flow '%s' started | trace_id=%s | steps=%d",
            flow_name,
            trace_id,
            len(flow.steps),
        )
        self._fire_flow_start(
            FlowStartContext(
                trace_id=trace_id,
                flow_name=flow_name,
                flow_version=flow.version,
                initial_input=dict(initial_input),
                started_at=flow_started_at,
                total_steps=len(flow.steps),
            )
        )

        # -- Flow-level input validation ------------------------------------
        if flow.input_schema is not None:
            validation_record = self._validate_flow_schema(
                flow_name=flow_name,
                payload=initial_input,
                schema=flow.input_schema,
                step_index=-1,
                context_label="flow_input",
            )
            if validation_record is not None:
                _logger.error(
                    "Flow '%s' input validation failed: %s",
                    flow_name,
                    validation_record.error_message,
                )
                return self._make_result(
                    flow_name=flow_name,
                    success=False,
                    final_output=None,
                    execution_log=[validation_record],
                    trace_id=trace_id,
                    started_at=flow_started_at,
                    perf_start=flow_t0,
                    initial_input=initial_input,
                    tool_step_count=0,
                )

        context: dict[str, Any] = dict(initial_input)
        log: list[StepRecord] = []

        for idx, step in enumerate(flow.steps):
            # Cooperative cancellation check at the step boundary (issue #142):
            # an in-flight step always finishes; we only stop *before* the
            # next one. Pure clock/boolean reads — invariants preserved.
            self._check_cancellation(
                flow_name=flow_name,
                next_step_index=idx,
                deadline=deadline,
                cancel_token=cancel_token,
                execution_log=log,
                trace_id=trace_id,
                started_at=flow_started_at,
                perf_start=flow_t0,
                initial_input=initial_input,
            )
            try:
                record = self._execute_step(
                    idx,
                    step,
                    context,
                    flow_name,
                    trace_id,
                    deadline=deadline,
                    cancel_token=cancel_token,
                )
            except FlowCancelledError as exc:
                # Cancellation fired inside a composed sub-flow; re-anchor it to
                # this parent flow so the parent's flow_end fires and the
                # surfaced partial carries the parent's completed steps.
                self._reraise_subflow_cancellation(
                    exc,
                    parent_flow_name=flow_name,
                    step=step,
                    flat_step_index=idx,
                    prior_log=log,
                    trace_id=trace_id,
                    started_at=flow_started_at,
                    perf_start=flow_t0,
                    initial_input=initial_input,
                )
            log.append(record)

            if not record.success:
                _logger.error(
                    "Flow '%s' aborted at step %d | trace_id=%s", flow_name, idx, trace_id
                )
                return self._make_result(
                    flow_name=flow_name,
                    success=False,
                    final_output=None,
                    execution_log=log,
                    trace_id=trace_id,
                    started_at=flow_started_at,
                    perf_start=flow_t0,
                    initial_input=initial_input,
                )

            # Merge step outputs into the shared context.
            if record.outputs is None:
                raise RuntimeError(
                    f"Step {idx} ({step.display_name}) succeeded but produced no outputs"
                )

            merge_step_outputs(
                context,
                record.outputs,
                policy=flow.on_context_collision,
                flow_name=flow_name,
                step_index=idx,
                step_name=step.display_name,
                logger=_logger,
            )

            # Crash-resume checkpoint (issue #128) — write after every
            # successful step so a fresh process can resume from here.
            self._save_linear_snapshot(
                trace_id=trace_id,
                flow=flow,
                initial_input=initial_input,
                started_at=flow_started_at,
                context=context,
                log=log,
                completed_steps=idx + 1,
            )

        # -- Flow-level output validation -----------------------------------
        if flow.output_schema is not None:
            validation_record = self._validate_flow_schema(
                flow_name=flow_name,
                payload=context,
                schema=flow.output_schema,
                step_index=len(flow.steps),
                context_label="flow_output",
            )
            if validation_record is not None:
                _logger.error(
                    "Flow '%s' output validation failed: %s",
                    flow_name,
                    validation_record.error_message,
                )
                return self._make_result(
                    flow_name=flow_name,
                    success=False,
                    final_output=None,
                    execution_log=[*log, validation_record],
                    trace_id=trace_id,
                    started_at=flow_started_at,
                    perf_start=flow_t0,
                    initial_input=initial_input,
                    tool_step_count=len(log),
                )

        # -- Flow-level context-schema validation (issue #152) --------------
        if flow.context_schema is not None:
            context_record = self._validate_flow_schema(
                flow_name=flow_name,
                payload=context,
                schema=flow.context_schema,
                step_index=len(flow.steps),
                context_label="flow_context",
            )
            if context_record is not None:
                _logger.error(
                    "Flow '%s' context-schema validation failed: %s",
                    flow_name,
                    context_record.error_message,
                )
                return self._make_result(
                    flow_name=flow_name,
                    success=False,
                    final_output=None,
                    execution_log=[*log, context_record],
                    trace_id=trace_id,
                    started_at=flow_started_at,
                    perf_start=flow_t0,
                    initial_input=initial_input,
                    tool_step_count=len(log),
                )

        _logger.info("Flow '%s' completed successfully | trace_id=%s", flow_name, trace_id)
        return self._make_result(
            flow_name=flow_name,
            success=True,
            final_output=context,
            execution_log=log,
            trace_id=trace_id,
            started_at=flow_started_at,
            perf_start=flow_t0,
            initial_input=initial_input,
        )

    async def execute_flow_async(
        self,
        flow_name: str,
        initial_input: dict[str, Any],
        *,
        version: str | None = None,
        force: bool = False,
        deadline: float | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> ExecutionResult:
        """Asynchronously execute a registered flow (issue #80).

        Coroutine variant of :meth:`execute_flow`.  Runs the flow
        lifecycle natively in the calling event loop and dispatches
        each tool through :meth:`Tool.run_async`:

        * Async-fn tools (e.g. the wrappers produced by
          :class:`chainweaver.mcp.MCPToolAdapter`) are ``await``-ed
          directly so I/O resources bound to the calling loop —
          notably MCP ``ClientSession`` streams — are usable.
        * Sync-fn tools are offloaded to a worker thread via
          :func:`asyncio.to_thread`, keeping the event loop
          responsive to other tasks while a blocking tool runs.

        Linear and DAG flows are both supported.  The async lane
        preserves middleware, retries, the ``on_error`` policy, and
        flow-level input/output validation.  It deliberately bypasses
        the step cache and crash-resume checkpointer for v0.1 — those
        features are async-unaware today and will be folded into the
        async lane in a follow-up.

        The async lane does **not** yet honour conditional branching
        (``branches`` / ``default_next``, #9), decision callbacks
        (``decision_candidates``, #102), or composed sub-flow steps
        (``flow_name``, #75).  Flows declaring those features raise
        :class:`AsyncLaneUnsupportedError` up front — listing every
        unsupported construct — rather than executing with the directives
        silently dropped (issue #332); use the synchronous
        :meth:`execute_flow` for such flows until the async lane reaches
        parity.

        Args:
            flow_name: Name of the flow to execute.
            initial_input: Initial key/value context passed to the first step.
            version: When provided, execute that exact registered flow
                version (issue #201); when ``None`` (the default), execute
                the latest registered version.  Mirrors the synchronous
                :meth:`execute_flow`.
            force: When ``True``, bypass the status guard and execute even
                if the flow is ``NEEDS_REVIEW`` or ``DISABLED``.
            deadline: Optional wall-clock deadline (issue #142); checked
                between steps / DAG levels, mirroring :meth:`execute_flow`.
            cancel_token: Optional :class:`CancellationToken` (issue #142);
                checked between steps / DAG levels.

        Returns:
            An :class:`ExecutionResult` with the full execution log.

        Raises:
            AsyncLaneUnsupportedError: When the flow uses conditional
                branching, decision callbacks, or composed sub-flow steps,
                which the async lane does not yet support (issue #332).
            FlowCancelledError: When *deadline* has passed or *cancel_token*
                is cancelled at a step boundary.
        """
        flow = self._registry.get_flow(flow_name, version=version)

        if not force and flow.status != FlowStatus.ACTIVE:
            raise FlowStatusError(flow_name, flow.status.value)

        self._assert_async_lane_supported(flow)

        if isinstance(flow, DAGFlow):
            return await self._execute_dag_flow_async(
                flow, initial_input, deadline=deadline, cancel_token=cancel_token
            )
        return await self._execute_linear_flow_async(
            flow, initial_input, deadline=deadline, cancel_token=cancel_token
        )

    @staticmethod
    def _assert_async_lane_supported(flow: Any) -> None:
        """Reject flows using execution features the async lane can't honour.

        ``execute_flow_async`` is a v0.1 lane (issue #80).  It does not
        yet implement the conditional-branching (#9), decision-callback
        (#102), or composed sub-flow (#75) semantics the synchronous
        :meth:`execute_flow` supports.  The async DAG path builds a plain
        tool proxy per step, so those directives would be **silently
        dropped** — producing a different result than the sync lane for the
        same flow.  This collects *every* unsupported construct in the flow
        and raises a single :class:`AsyncLaneUnsupportedError` **before any
        step runs** (issue #332), so callers see the full set of reasons at
        once and route such flows through :meth:`execute_flow` until the
        async lane gains parity.
        """
        unsupported: list[str] = []
        for idx, step in enumerate(flow.steps):
            if getattr(step, "flow_name", None) is not None:
                unsupported.append(
                    f"step {idx} ('{step.flow_name}'): composed sub-flow "
                    "(flow_name) steps (issue #75)"
                )
            if getattr(step, "decision_candidates", None):
                unsupported.append(
                    f"step {idx} ('{step.display_name}'): decision_candidates (issue #102)"
                )
            if getattr(step, "branches", None):
                unsupported.append(
                    f"step {idx} ('{step.display_name}'): conditional branches (issue #9)"
                )
            if getattr(step, "default_next", None) is not None:
                unsupported.append(
                    f"step {idx} ('{step.display_name}'): default_next routing (issue #9)"
                )
        if unsupported:
            raise AsyncLaneUnsupportedError(flow.name, unsupported)

    async def _execute_linear_flow_async(
        self,
        flow: Any,
        initial_input: dict[str, Any],
        *,
        deadline: float | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> ExecutionResult:
        """Async-native counterpart to the linear branch of :meth:`execute_flow`."""
        self._active_flow_version = flow.version
        trace_id = _new_trace_id()
        flow_started_at = _now_utc()
        flow_t0 = time.perf_counter()
        flow_name = flow.name

        _logger.info(
            "Flow '%s' (async) started | trace_id=%s | steps=%d",
            flow_name,
            trace_id,
            len(flow.steps),
        )
        self._fire_flow_start(
            FlowStartContext(
                trace_id=trace_id,
                flow_name=flow_name,
                flow_version=flow.version,
                initial_input=dict(initial_input),
                started_at=flow_started_at,
                total_steps=len(flow.steps),
            )
        )

        if flow.input_schema is not None:
            validation_record = self._validate_flow_schema(
                flow_name=flow_name,
                payload=initial_input,
                schema=flow.input_schema,
                step_index=-1,
                context_label="flow_input",
            )
            if validation_record is not None:
                return self._make_result(
                    flow_name=flow_name,
                    success=False,
                    final_output=None,
                    execution_log=[validation_record],
                    trace_id=trace_id,
                    started_at=flow_started_at,
                    perf_start=flow_t0,
                    initial_input=initial_input,
                    tool_step_count=0,
                )

        context: dict[str, Any] = dict(initial_input)
        log: list[StepRecord] = []
        for idx, step in enumerate(flow.steps):
            # Cooperative cancellation at the step boundary (issue #142).
            self._check_cancellation(
                flow_name=flow_name,
                next_step_index=idx,
                deadline=deadline,
                cancel_token=cancel_token,
                execution_log=log,
                trace_id=trace_id,
                started_at=flow_started_at,
                perf_start=flow_t0,
                initial_input=initial_input,
            )
            record = await self._execute_step_async(idx, step, context, flow_name, trace_id)
            log.append(record)
            if not record.success:
                return self._make_result(
                    flow_name=flow_name,
                    success=False,
                    final_output=None,
                    execution_log=log,
                    trace_id=trace_id,
                    started_at=flow_started_at,
                    perf_start=flow_t0,
                    initial_input=initial_input,
                )
            if record.outputs is None:
                raise RuntimeError(
                    f"Step {idx} ({step.display_name}) succeeded but produced no outputs"
                )
            merge_step_outputs(
                context,
                record.outputs,
                policy=flow.on_context_collision,
                flow_name=flow_name,
                step_index=idx,
                step_name=step.display_name,
                logger=_logger,
            )

        if flow.output_schema is not None:
            validation_record = self._validate_flow_schema(
                flow_name=flow_name,
                payload=context,
                schema=flow.output_schema,
                step_index=len(flow.steps),
                context_label="flow_output",
            )
            if validation_record is not None:
                return self._make_result(
                    flow_name=flow_name,
                    success=False,
                    final_output=None,
                    execution_log=[*log, validation_record],
                    trace_id=trace_id,
                    started_at=flow_started_at,
                    perf_start=flow_t0,
                    initial_input=initial_input,
                    tool_step_count=len(log),
                )

        return self._make_result(
            flow_name=flow_name,
            success=True,
            final_output=context,
            execution_log=log,
            trace_id=trace_id,
            started_at=flow_started_at,
            perf_start=flow_t0,
            initial_input=initial_input,
        )

    async def _execute_dag_flow_async(
        self,
        flow: DAGFlow,
        initial_input: dict[str, Any],
        *,
        deadline: float | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> ExecutionResult:
        """Async-native counterpart to :meth:`_execute_dag_flow`.

        Level-by-level execution mirrors the sync path: steps within a
        level run sequentially (concurrent intra-level execution is a
        follow-up — see issue #80 acceptance criteria), and outputs are
        merged with sibling-key-conflict detection between levels.
        Cancellation (issue #142) is checked between levels.
        """
        self._active_flow_version = flow.version
        trace_id = _new_trace_id()
        flow_started_at = _now_utc()
        flow_t0 = time.perf_counter()

        self._fire_flow_start(
            FlowStartContext(
                trace_id=trace_id,
                flow_name=flow.name,
                flow_version=flow.version,
                initial_input=dict(initial_input),
                started_at=flow_started_at,
                total_steps=len(flow.steps),
            )
        )

        if flow.input_schema is not None:
            validation_record = self._validate_flow_schema(
                flow_name=flow.name,
                payload=initial_input,
                schema=flow.input_schema,
                step_index=-1,
                context_label="flow_input",
            )
            if validation_record is not None:
                return self._make_result(
                    flow_name=flow.name,
                    success=False,
                    final_output=None,
                    execution_log=[validation_record],
                    trace_id=trace_id,
                    started_at=flow_started_at,
                    perf_start=flow_t0,
                    initial_input=initial_input,
                    tool_step_count=0,
                )

        context: dict[str, Any] = dict(initial_input)
        log: list[StepRecord] = []
        flat_index = 0
        levels = self._compute_dag_levels(flow)

        for level_steps in levels:
            # Cooperative cancellation between topological levels (issue #142).
            self._check_cancellation(
                flow_name=flow.name,
                next_step_index=flat_index,
                deadline=deadline,
                cancel_token=cancel_token,
                execution_log=log,
                trace_id=trace_id,
                started_at=flow_started_at,
                perf_start=flow_t0,
                initial_input=initial_input,
            )
            level_outputs: dict[str, Any] = {}

            # Assign each step its declaration-order flat index up front so the
            # execution log is identical regardless of concurrency (#344), and
            # reject capability steps (async lane runs tool steps only).
            indexed_steps: list[tuple[int, Any]] = []
            for step in level_steps:
                if step.step_type != "tool":
                    err = FlowExecutionError(
                        step.display_name,
                        flat_index,
                        f"Step '{step.step_id}' has step_type='{step.step_type}' "
                        f"which is not supported by FlowExecutor.",
                    )
                    err_type, err_msg = _exc_to_strings(err)
                    now = _now_utc()
                    log.append(
                        StepRecord(
                            step_index=flat_index,
                            tool_name=step.display_name,
                            inputs={},
                            error_type=err_type,
                            error_message=err_msg,
                            success=False,
                            started_at=now,
                            ended_at=now,
                            duration_ms=0.0,
                        )
                    )
                    return self._make_result(
                        flow_name=flow.name,
                        success=False,
                        final_output=None,
                        execution_log=log,
                        trace_id=trace_id,
                        started_at=flow_started_at,
                        perf_start=flow_t0,
                        initial_input=initial_input,
                    )
                indexed_steps.append((flat_index, step))
                flat_index += 1

            # Run the level's steps — bounded-concurrent when opted in (#344),
            # strictly sequential by default.  Records come back in declaration
            # order in either case; ``context`` is read-only during the level
            # (outputs are merged only after it completes), so concurrent input
            # resolution is safe.
            records = await self._run_dag_level_async(indexed_steps, context, flow.name, trace_id)

            # Process results in declaration order: append to the log, abort on
            # the first failure, and reject sibling key collisions — identical
            # to sequential execution regardless of the concurrency setting.
            for (_, step), record in zip(indexed_steps, records, strict=True):
                log.append(record)
                if not record.success:
                    return self._make_result(
                        flow_name=flow.name,
                        success=False,
                        final_output=None,
                        execution_log=log,
                        trace_id=trace_id,
                        started_at=flow_started_at,
                        perf_start=flow_t0,
                        initial_input=initial_input,
                    )
                assert record.outputs is not None
                for key, value in record.outputs.items():
                    if key in level_outputs:
                        conflict_err = FlowExecutionError(
                            step.display_name,
                            record.step_index,
                            f"Key '{key}' produced by both '{step.display_name}' and a "
                            f"sibling step in the same DAG level.",
                        )
                        err_type, err_msg = _exc_to_strings(conflict_err)
                        log[-1] = StepRecord(
                            step_index=record.step_index,
                            tool_name=step.display_name,
                            inputs=record.inputs,
                            error_type=err_type,
                            error_message=err_msg,
                            success=False,
                            started_at=record.started_at,
                            ended_at=_now_utc(),
                            duration_ms=record.duration_ms,
                        )
                        return self._make_result(
                            flow_name=flow.name,
                            success=False,
                            final_output=None,
                            execution_log=log,
                            trace_id=trace_id,
                            started_at=flow_started_at,
                            perf_start=flow_t0,
                            initial_input=initial_input,
                        )
                    level_outputs[key] = value
            # Level-to-level merge honours the flow's collision policy (#337);
            # within-level sibling collisions were already rejected above.
            merge_step_outputs(
                context,
                level_outputs,
                policy=flow.on_context_collision,
                flow_name=flow.name,
                step_index=flat_index,
                step_name="DAG level",
                logger=_logger,
            )

        if flow.output_schema is not None:
            validation_record = self._validate_flow_schema(
                flow_name=flow.name,
                payload=context,
                schema=flow.output_schema,
                step_index=len(flow.steps),
                context_label="flow_output",
            )
            if validation_record is not None:
                return self._make_result(
                    flow_name=flow.name,
                    success=False,
                    final_output=None,
                    execution_log=[*log, validation_record],
                    trace_id=trace_id,
                    started_at=flow_started_at,
                    perf_start=flow_t0,
                    initial_input=initial_input,
                    tool_step_count=len(log),
                )

        return self._make_result(
            flow_name=flow.name,
            success=True,
            final_output=context,
            execution_log=log,
            trace_id=trace_id,
            started_at=flow_started_at,
            perf_start=flow_t0,
            initial_input=initial_input,
        )

    async def _run_dag_level_async(
        self,
        indexed_steps: list[tuple[int, Any]],
        context: dict[str, Any],
        flow_name: str,
        trace_id: str,
    ) -> list[StepRecord]:
        """Execute one DAG level's steps, returning records in declaration order.

        With ``max_step_concurrency == 1`` (the default) steps run strictly
        sequentially — bit-identical to the historical async DAG path.  With a
        higher bound the steps are dispatched concurrently under an
        :class:`asyncio.Semaphore` (issue #344); :func:`asyncio.gather`
        preserves the order of the awaitables, so the returned records are
        always in *declaration* order regardless of completion order.

        ``context`` is only read here (input resolution) — level outputs are
        merged into it by the caller after the level completes — so concurrent
        execution introduces no shared-state writes on the executor's side.
        Opted-in tools must themselves be safe to run concurrently.
        """

        async def _run_one(step_index: int, step: Any) -> StepRecord:
            proxy = FlowStep(
                tool_name=step.display_name,
                input_mapping=step.input_mapping,
            )
            return await self._execute_step_async(step_index, proxy, context, flow_name, trace_id)

        if self._max_step_concurrency <= 1 or len(indexed_steps) <= 1:
            return [await _run_one(idx, step) for idx, step in indexed_steps]

        semaphore = asyncio.Semaphore(self._max_step_concurrency)

        async def _run_bounded(step_index: int, step: Any) -> StepRecord:
            async with semaphore:
                return await _run_one(step_index, step)

        return list(
            await asyncio.gather(*(_run_bounded(idx, step) for idx, step in indexed_steps))
        )

    async def _execute_step_async(
        self,
        step_index: int,
        step: FlowStep,
        context: dict[str, Any],
        flow_name: str,
        trace_id: str,
    ) -> StepRecord:
        """Async-native counterpart to :meth:`_execute_step`.

        Mirrors the sync path's tool-not-found / input-mapping /
        invocation / wrap / on-error machinery, but uses
        :meth:`Tool.run_async` so async-fn tools never trigger a
        cross-loop dispatch.

        Retries and middleware hooks (which are sync APIs) are
        applied in the same order as the sync path; ``on_error``
        fallback tools are also dispatched via ``run_async`` so MCP
        fallbacks compose correctly.
        """
        started_at = _now_utc()
        t0 = time.perf_counter()
        tool_attempts = [0]

        def _record(
            *,
            inputs: dict[str, Any],
            outputs: dict[str, Any] | None,
            error: Exception | None,
            success: bool,
            skipped: bool,
            retry_errors: list[str],
            fallback_used: bool = False,
        ) -> StepRecord:
            err_type, err_msg = (None, None) if error is None else _exc_to_strings(error)
            retry_count = max(0, tool_attempts[0] - 1)
            return StepRecord(
                step_index=step_index,
                tool_name=step.display_name,
                inputs=inputs,
                outputs=outputs,
                error_type=err_type,
                error_message=err_msg,
                success=success,
                started_at=started_at,
                ended_at=_now_utc(),
                duration_ms=(time.perf_counter() - t0) * 1000.0,
                retry_count=retry_count,
                retry_errors=list(retry_errors),
                skipped=skipped,
                cached=False,
                fallback_used=fallback_used,
            )

        def _finish(record: StepRecord) -> StepRecord:
            self._fire_step_end(
                StepEndContext(
                    trace_id=trace_id,
                    flow_name=flow_name,
                    step_record=record,
                )
            )
            return record

        try:
            tool = self.get_tool(step.display_name)
        except ToolNotFoundError as exc:
            log_step_error(_logger, step_index, step.display_name, exc)
            return _finish(
                _record(
                    inputs={},
                    outputs=None,
                    error=exc,
                    success=False,
                    skipped=False,
                    retry_errors=[],
                )
            )

        try:
            inputs = self._resolve_inputs(step, context, step_index)
        except InputMappingError as exc:
            log_step_error(_logger, step_index, step.display_name, exc)
            return _finish(
                _record(
                    inputs={},
                    outputs=None,
                    error=exc,
                    success=False,
                    skipped=False,
                    retry_errors=[],
                )
            )

        self._fire_step_start(
            StepStartContext(
                trace_id=trace_id,
                flow_name=flow_name,
                step_index=step_index,
                tool_name=step.display_name,
                inputs=dict(inputs),
                started_at=started_at,
            )
        )
        log_step_start(
            _logger,
            step_index,
            step.display_name,
            inputs,
            redaction=self._redaction_policy,
        )

        retry_errors: list[str] = []
        try:
            outputs = await self._invoke_tool_async(
                tool, inputs, step.retry, retry_errors, tool_attempts
            )
        except Exception as exc:
            wrapped = self._wrap_tool_exception(step, step_index, exc)
            log_step_error(_logger, step_index, step.display_name, wrapped)
            # Re-use the sync ``_apply_on_error`` for fail / skip; the
            # fallback path needs an async dispatch, so route through
            # an async-aware helper.
            return _finish(
                await self._apply_on_error_async(
                    step=step,
                    step_index=step_index,
                    inputs=inputs,
                    wrapped_error=wrapped,
                    retry_errors=retry_errors,
                    make_record=_record,
                )
            )

        log_step_end(
            _logger,
            step_index,
            step.display_name,
            outputs,
            redaction=self._redaction_policy,
        )
        return _finish(
            _record(
                inputs=inputs,
                outputs=outputs,
                error=None,
                success=True,
                skipped=False,
                retry_errors=retry_errors,
            )
        )

    async def _invoke_tool_async(
        self,
        tool: Tool,
        inputs: dict[str, Any],
        policy: RetryPolicy | None,
        retry_errors: list[str],
        attempts: list[int],
    ) -> dict[str, Any]:
        """Async counterpart to :meth:`_invoke_tool`.

        Applies the same backoff schedule via :func:`asyncio.sleep`
        instead of tenacity's blocking ``time.sleep``, so retries don't
        starve the calling event loop.
        """
        if policy is None:
            attempts[0] += 1
            try:
                return await tool.run_async(inputs)
            except Exception as exc:
                retry_errors.append(str(exc))
                raise

        retryable = policy.resolved_retryable_errors()
        last_exc: Exception | None = None
        for attempt_number in range(1, policy.max_retries + 2):
            attempts[0] += 1
            try:
                return await tool.run_async(inputs)
            except Exception as exc:
                retry_errors.append(str(exc))
                last_exc = exc
                if not isinstance(exc, retryable):
                    raise
                if attempt_number >= policy.max_retries + 1:
                    raise
                delay = policy.compute_delay(attempt_number)
                if delay > 0:
                    await asyncio.sleep(delay)
        # Unreachable in practice (the loop either returns or re-raises).
        assert last_exc is not None
        raise last_exc  # pragma: no cover

    async def _apply_on_error_async(
        self,
        *,
        step: FlowStep,
        step_index: int,
        inputs: dict[str, Any],
        wrapped_error: Exception,
        retry_errors: list[str],
        make_record: Callable[..., StepRecord],
    ) -> StepRecord:
        """Async counterpart to :meth:`_apply_on_error`.

        Identical fail / skip behaviour to the sync path; the
        ``fallback:<tool_name>`` branch dispatches the fallback tool
        via :meth:`Tool.run_async` so async fallbacks compose.
        """
        on_error = step.on_error
        if on_error == "fail":
            return make_record(
                inputs=inputs,
                outputs=None,
                error=wrapped_error,
                success=False,
                skipped=False,
                retry_errors=retry_errors,
            )
        if on_error == "skip":
            return make_record(
                inputs=inputs,
                outputs={},
                error=None,
                success=True,
                skipped=True,
                retry_errors=retry_errors,
            )
        # fallback:<tool_name>
        prefix = "fallback:"
        if on_error.startswith(prefix):
            fb_name = on_error[len(prefix) :]
            try:
                fb_tool = self.get_tool(fb_name)
            except ToolNotFoundError as exc:
                retry_errors.append(f"fallback '{fb_name}' not registered")
                return make_record(
                    inputs=inputs,
                    outputs=None,
                    error=exc,
                    success=False,
                    skipped=False,
                    retry_errors=retry_errors,
                    fallback_used=True,
                )
            try:
                outputs = await fb_tool.run_async(inputs)
            except Exception as exc:
                retry_errors.append(f"fallback '{fb_name}' failed: {exc}")
                wrapped_fb = self._wrap_tool_exception(step, step_index, exc)
                return make_record(
                    inputs=inputs,
                    outputs=None,
                    error=wrapped_fb,
                    success=False,
                    skipped=False,
                    retry_errors=retry_errors,
                    fallback_used=True,
                )
            return make_record(
                inputs=inputs,
                outputs=outputs,
                error=None,
                success=True,
                skipped=False,
                retry_errors=retry_errors,
                fallback_used=True,
            )
        # Unrecognised on_error → treat as fail.
        return make_record(
            inputs=inputs,
            outputs=None,
            error=wrapped_error,
            success=False,
            skipped=False,
            retry_errors=retry_errors,
        )

    def stream_flow(
        self,
        flow_name: str,
        initial_input: dict[str, Any],
        *,
        force: bool = False,
    ) -> Iterator[FlowEvent]:
        """Execute a flow and yield :class:`FlowEvent` lifecycle events (#134).

        Events arrive in strict order::

            flow_start
            (step_start, step_end)*       # one pair per executed step
            flow_end                       # always — inspect result.success

        Steps that fail before input resolution (tool-not-found,
        input-mapping) emit ``step_end`` without a preceding
        ``step_start`` — same contract as the underlying middleware
        hooks.

        The flow runs on a background worker thread; events are delivered
        through a synchronized queue.

        **Cancellation is not supported** for the sync variant.  If the
        consumer breaks out of the iteration (or otherwise lets the
        generator be garbage-collected), the generator's ``finally``
        block blocks on ``thread.join()`` until the background flow
        finishes — for a 10-step flow with a long step 3 that means
        the caller's "stop iterating" intent is silently translated
        into "block here until everything completes".  A ``WARNING``
        is logged via the ``chainweaver.executor`` logger when this
        happens so the behavior shows up in production traces.  For
        proper cancellation use the async variant once issue #80
        lands.

        Hook exceptions and middleware exceptions still follow the
        catch-and-log contract from :class:`FlowExecutorMiddleware`: a
        consumer that mishandles an event cannot abort the flow.

        Args:
            flow_name: Name of the flow to execute.
            initial_input: Initial key/value context passed to the first
                step.
            force: When ``True``, bypass the status guard and execute
                even if the flow is ``NEEDS_REVIEW`` or ``DISABLED``.

        Yields:
            :class:`~chainweaver.events.FlowEvent` instances in the order
            described above.

        Raises:
            FlowNotFoundError: When *flow_name* is not registered.  This
                is raised eagerly by the worker thread and re-raised
                from the generator before any event is yielded.
            FlowStatusError: When the flow's status is not ``ACTIVE`` and
                *force* is ``False``.  Same re-raise behavior.
        """
        events: queue.Queue[FlowEvent | _StreamSentinel] = queue.Queue()
        collector = _StreamCollectorMiddleware(events)
        exc_holder: list[BaseException] = []

        # Register the event collector as *run-scoped* middleware on the worker
        # thread (issue #336): it is visible only to this run's execution, so
        # concurrent ``stream_flow`` / ``execute_flow`` calls on the same
        # executor never receive each other's events.  The shared
        # ``self._middleware`` list is never mutated.

        def _worker() -> None:
            try:
                with self._scoped_middleware(collector):
                    self.execute_flow(flow_name, initial_input, force=force)
            except BaseException as exc:
                exc_holder.append(exc)
            finally:
                events.put(_STREAM_SENTINEL)

        thread = threading.Thread(
            target=_worker,
            name=f"chainweaver-stream-{flow_name}",
            daemon=True,
        )
        thread.start()
        consumer_abandoned = False
        try:
            while True:
                item = events.get()
                if isinstance(item, _StreamSentinel):
                    if exc_holder:
                        raise exc_holder[0]
                    return
                yield item
        except GeneratorExit:
            consumer_abandoned = True
            raise
        finally:
            if consumer_abandoned and thread.is_alive():
                _logger.warning(
                    "stream_flow consumer abandoned the generator for flow '%s'; "
                    "background worker continues to completion (cancellation is "
                    "not supported in the sync variant — see #80).",
                    flow_name,
                )
            thread.join()
            # No cleanup needed: the collector lived on the worker thread's
            # run-scoped middleware slot (issue #336) and was popped when the
            # worker's ``_scoped_middleware`` context exited.

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _check_cancellation(
        self,
        *,
        flow_name: str,
        next_step_index: int,
        deadline: float | None,
        cancel_token: CancellationToken | None,
        execution_log: list[StepRecord],
        trace_id: str,
        started_at: datetime,
        perf_start: float,
        initial_input: dict[str, Any],
    ) -> None:
        """Raise :class:`FlowCancelledError` if cancellation is due (issue #142).

        Invoked only at step boundaries (between linear steps and between DAG
        levels).  The check is a pure :func:`time.time` read plus a pure
        boolean token read, so it never touches the network, an LLM, or a
        randomness source — the three hard executor invariants hold.

        No-op when neither ``deadline`` nor ``cancel_token`` is supplied, or
        when neither has fired.  When one (or both) has fired it builds the
        partial :class:`ExecutionResult` from the records gathered so far
        (``success=False``) and raises, so the partial trace survives on the
        error and the crash-resume snapshot is preserved.
        """
        if deadline is None and cancel_token is None:
            return
        deadline_exceeded = deadline is not None and time.time() >= deadline
        token_cancelled = cancel_token is not None and cancel_token.is_cancelled
        if not (deadline_exceeded or token_cancelled):
            return
        partial = self._make_result(
            flow_name=flow_name,
            success=False,
            final_output=None,
            execution_log=execution_log,
            trace_id=trace_id,
            started_at=started_at,
            perf_start=perf_start,
            initial_input=initial_input,
            tool_step_count=len(execution_log),
        )
        raise FlowCancelledError(
            flow_name,
            next_step_index,
            result=partial,
            deadline_exceeded=deadline_exceeded,
            token_cancelled=token_cancelled,
        )

    def _reraise_subflow_cancellation(
        self,
        exc: FlowCancelledError,
        *,
        parent_flow_name: str,
        step: FlowStep,
        flat_step_index: int,
        prior_log: list[StepRecord],
        trace_id: str,
        started_at: datetime,
        perf_start: float,
        initial_input: dict[str, Any],
    ) -> NoReturn:
        """Re-anchor a sub-flow `FlowCancelledError` to its parent (issue #142 / #75).

        When a `deadline` / `cancel_token` fires *between* a composed sub-flow's
        own steps, the recursive `execute_flow` builds and fires the sub-flow's
        (nested) result and raises. Left unhandled, that error escapes the
        parent carrying only the sub-flow's partial, and the parent's
        `flow_end` middleware never fires (it pairs with `flow_start` solely via
        `_make_result`). This records the cancelled composed step — with the
        sub-flow's partial attached as `sub_result` — builds the parent's
        partial via `_make_result` (firing the parent `flow_end`), and re-raises
        a `FlowCancelledError` carrying the parent's flow name, step index, and
        partial so the cancellation contract holds at every nesting level.

        Args:
            exc: The `FlowCancelledError` raised inside the sub-flow.
            parent_flow_name: Name of the enclosing (parent) flow.
            step: The composed `FlowStep` whose sub-flow was cancelled.
            flat_step_index: The composed step's index in the parent flow.
            prior_log: The parent's step records completed before this step.
            trace_id: The parent flow's trace id.
            started_at: The parent flow's start timestamp.
            perf_start: The parent flow's `perf_counter` start.
            initial_input: The parent flow's initial input.

        Raises:
            FlowCancelledError: Always, re-anchored to the parent flow.
        """
        now = _now_utc()
        composed = StepRecord(
            step_index=flat_step_index,
            tool_name=step.display_name,
            flow_name=step.flow_name,
            inputs={},
            outputs=None,
            error_type="FlowCancelledError",
            error_message=str(exc),
            success=False,
            started_at=now,
            ended_at=now,
            duration_ms=0.0,
            sub_result=exc.result,
        )
        full_log = [*prior_log, composed]
        partial = self._make_result(
            flow_name=parent_flow_name,
            success=False,
            final_output=None,
            execution_log=full_log,
            trace_id=trace_id,
            started_at=started_at,
            perf_start=perf_start,
            initial_input=initial_input,
            tool_step_count=len(full_log),
        )
        raise FlowCancelledError(
            parent_flow_name,
            flat_step_index,
            result=partial,
            deadline_exceeded=exc.deadline_exceeded,
            token_cancelled=exc.token_cancelled,
        ) from exc

    @staticmethod
    def _count_composed_tool_steps(records: list[StepRecord]) -> int:
        """Count genuine tool invocations in a step log, descending through
        composed sub-flows (issue #75).

        A composed sub-flow step is a *container*, not a tool invocation, so it
        contributes only the tool steps its sub-flow actually ran (recursively,
        for nested composition).  Every other record counts as one invocation.

        Args:
            records: A flow's ``execution_log`` (or a sub-flow's).

        Returns:
            The total number of tool invocations the log represents.
        """
        total = 0
        for rec in records:
            if rec.sub_result is not None:
                total += FlowExecutor._count_composed_tool_steps(rec.sub_result.execution_log)
            else:
                total += 1
        return total

    def _make_result(
        self,
        *,
        flow_name: str,
        success: bool,
        final_output: dict[str, Any] | None,
        execution_log: list[StepRecord],
        trace_id: str,
        started_at: datetime,
        perf_start: float,
        initial_input: dict[str, Any],
        tool_step_count: int | None = None,
    ) -> ExecutionResult:
        """Build an :class:`ExecutionResult` and stamp the closing timestamps.

        Args:
            tool_step_count: Number of *tool* step records in
                ``execution_log`` (excluding the synthetic flow-level
                schema-validation records that may carry ``step_index ==
                -1`` or ``step_index == len(steps)``).  Used to compute
                ``cost_report.llm_calls_avoided`` so validation records
                don't inflate the estimate.  When ``None`` (the default),
                falls back to ``len(execution_log)`` for callers that do
                not append validation records.  Composed sub-flow steps
                (issue #75) are expanded to their nested tool invocations
                on top of this count via
                :meth:`_count_composed_tool_steps`, so the cost estimate
                reflects every tool that ran across the composition.
        """
        ended_at = _now_utc()
        total_ms = (time.perf_counter() - perf_start) * 1000.0
        cost_report: CostReport | None = None
        if self._cost_profile is not None:
            base_steps = tool_step_count if tool_step_count is not None else len(execution_log)
            # Composed sub-flow steps (issue #75) each count as a single record
            # in ``execution_log`` but actually drive a whole sub-flow's worth
            # of tool invocations.  Replace each composed step's lone count
            # with the recursive count of the genuine tools it ran, so
            # ``steps_executed`` — and thus ``llm_calls_avoided`` — reflects
            # every tool that executed across the composition, not just the
            # top-level steps.
            composition_adjustment = sum(
                self._count_composed_tool_steps(rec.sub_result.execution_log) - 1
                for rec in execution_log
                if rec.sub_result is not None
            )
            cost_report = compute_cost_report(
                steps_executed=base_steps + composition_adjustment,
                actual_execution_ms=total_ms,
                profile=self._cost_profile,
            )
        result = ExecutionResult(
            flow_name=flow_name,
            flow_version=self._active_flow_version,
            success=success,
            final_output=final_output,
            execution_log=execution_log,
            trace_id=trace_id,
            started_at=started_at,
            ended_at=ended_at,
            total_duration_ms=total_ms,
            cost_report=cost_report,
            initial_input=dict(initial_input),
        )
        if self._trace_recorder is not None:
            self._record_observed_trace(result)
        # On terminal success delete the snapshot — the resume window
        # is closed.  Failed runs preserve the snapshot so the operator
        # can choose to retry the failed step manually (issue #128).
        if self._checkpointer is not None and self._delete_on_success and result.success:
            self._checkpointer.delete(result.trace_id)
        self._fire_flow_end(
            FlowEndContext(
                trace_id=trace_id,
                flow_name=flow_name,
                result=result,
            )
        )
        return result

    def _save_linear_snapshot(
        self,
        *,
        trace_id: str,
        flow: Any,
        initial_input: dict[str, Any],
        started_at: datetime,
        context: dict[str, Any],
        log: list[StepRecord],
        completed_steps: int,
    ) -> None:
        """Write a snapshot for a linear flow execution (issue #128).

        No-op when no checkpointer is configured.  Captures every
        relevant tool's current ``schema_hash`` so resume can detect
        drift since the snapshot was written.
        """
        if self._checkpointer is None:
            return
        tool_hashes: dict[str, str] = {}
        for step in flow.steps:
            tool = self._tools.get(step.display_name)
            if tool is not None:
                tool_hashes[step.display_name] = tool.schema_hash
        snapshot = ExecutionSnapshot(
            trace_id=trace_id,
            flow_name=flow.name,
            flow_version=flow.version,
            initial_input=dict(initial_input),
            started_at=started_at,
            context=dict(context),
            execution_log=list(log),
            completed_steps=completed_steps,
            tool_schema_hashes=tool_hashes,
        )
        self._checkpointer.save(snapshot)

    def _save_dag_snapshot(
        self,
        *,
        trace_id: str,
        flow: DAGFlow,
        initial_input: dict[str, Any],
        started_at: datetime,
        context: dict[str, Any],
        log: list[StepRecord],
        completed_levels: int,
    ) -> None:
        """Write a snapshot at a DAG level boundary (issue #128).

        DAG resume uses level granularity — within a level all steps
        run sequentially, but on resume the level is replayed from
        scratch.  No-op when no checkpointer is configured.
        """
        if self._checkpointer is None:
            return
        tool_hashes: dict[str, str] = {}
        for step in flow.steps:
            tool = self._tools.get(step.display_name)
            if tool is not None:
                tool_hashes[step.display_name] = tool.schema_hash
        snapshot = ExecutionSnapshot(
            trace_id=trace_id,
            flow_name=flow.name,
            flow_version=flow.version,
            initial_input=dict(initial_input),
            started_at=started_at,
            context=dict(context),
            execution_log=list(log),
            completed_dag_levels=completed_levels,
            tool_schema_hashes=tool_hashes,
        )
        self._checkpointer.save(snapshot)

    def resume_flow(self, trace_id: str) -> ExecutionResult:
        """Resume an in-flight execution from a stored snapshot (issue #128).

        Loads the snapshot via the configured ``checkpointer``, validates
        the snapshot's flow version and tool ``schema_hash`` values
        against the current registry, then continues execution from the
        step (linear) or DAG level (DAG) where the previous run left
        off.  The returned :class:`ExecutionResult` carries the
        original ``trace_id`` and ``started_at`` from the snapshot, and
        ``execution_log`` includes both the recovered records and the
        freshly executed ones.

        On terminal success the snapshot is deleted iff
        ``delete_on_success=True`` (the default).

        Args:
            trace_id: Trace id of the snapshot to resume.

        Returns:
            An :class:`ExecutionResult` for the (now-completed) flow.

        Raises:
            CheckpointerNotConfiguredError: When no checkpointer was
                passed to ``FlowExecutor(...)``.
            CheckpointNotFoundError: When no snapshot exists for
                *trace_id*.
            FlowNotFoundError: When the snapshot's flow is no longer
                registered.
            CheckpointDriftError: When the flow's version or any tool's
                ``schema_hash`` has changed since the snapshot was
                written.
        """
        if self._checkpointer is None:
            raise CheckpointerNotConfiguredError()
        snapshot = self._checkpointer.load(trace_id)
        if snapshot is None:
            raise CheckpointNotFoundError(trace_id)

        flow = self._registry.get_flow(snapshot.flow_name)
        if flow.version != snapshot.flow_version:
            raise CheckpointDriftError(
                trace_id,
                snapshot.flow_name,
                f"flow version changed: snapshot='{snapshot.flow_version}' "
                f"current='{flow.version}'",
            )
        for tool_name, snap_hash in snapshot.tool_schema_hashes.items():
            current = self._tools.get(tool_name)
            if current is None:
                raise CheckpointDriftError(
                    trace_id,
                    snapshot.flow_name,
                    f"tool '{tool_name}' is no longer registered",
                )
            if current.schema_hash != snap_hash:
                raise CheckpointDriftError(
                    trace_id,
                    snapshot.flow_name,
                    f"tool '{tool_name}' schema_hash changed: "
                    f"snapshot='{snap_hash}' current='{current.schema_hash}'",
                )

        if isinstance(flow, DAGFlow):
            return self._resume_dag_flow(flow, snapshot)
        return self._resume_linear_flow(flow, snapshot)

    def _resume_linear_flow(
        self,
        flow: Any,
        snapshot: ExecutionSnapshot,
    ) -> ExecutionResult:
        """Continue a linear execution from *snapshot.completed_steps*."""
        self._active_flow_version = flow.version
        trace_id = snapshot.trace_id
        flow_name = snapshot.flow_name
        flow_started_at = snapshot.started_at
        # perf_start anchors total_duration_ms; resume time is the wall
        # clock from the resume point on, not the original elapsed
        # duration.  Document this in the result interpretation if
        # users want cross-resume totals they can sum execution_log
        # durations.
        flow_t0 = time.perf_counter()
        _logger.info(
            "Flow '%s' resuming | trace_id=%s | from_step=%d",
            flow_name,
            trace_id,
            snapshot.completed_steps,
        )
        self._fire_flow_start(
            FlowStartContext(
                trace_id=trace_id,
                flow_name=flow_name,
                flow_version=flow.version,
                initial_input=dict(snapshot.initial_input),
                started_at=flow_started_at,
                total_steps=len(flow.steps),
            )
        )

        context: dict[str, Any] = dict(snapshot.context)
        log: list[StepRecord] = list(snapshot.execution_log)

        for idx in range(snapshot.completed_steps, len(flow.steps)):
            step = flow.steps[idx]
            record = self._execute_step(idx, step, context, flow_name, trace_id)
            log.append(record)

            if not record.success:
                return self._make_result(
                    flow_name=flow_name,
                    success=False,
                    final_output=None,
                    execution_log=log,
                    trace_id=trace_id,
                    started_at=flow_started_at,
                    perf_start=flow_t0,
                    initial_input=dict(snapshot.initial_input),
                )

            assert record.outputs is not None  # success guarantees outputs
            context.update(record.outputs)

            self._save_linear_snapshot(
                trace_id=trace_id,
                flow=flow,
                initial_input=snapshot.initial_input,
                started_at=flow_started_at,
                context=context,
                log=log,
                completed_steps=idx + 1,
            )

        # Flow-level output validation (mirrors execute_flow).
        if flow.output_schema is not None:
            validation_record = self._validate_flow_schema(
                flow_name=flow_name,
                payload=context,
                schema=flow.output_schema,
                step_index=len(flow.steps),
                context_label="flow_output",
            )
            if validation_record is not None:
                return self._make_result(
                    flow_name=flow_name,
                    success=False,
                    final_output=None,
                    execution_log=[*log, validation_record],
                    trace_id=trace_id,
                    started_at=flow_started_at,
                    perf_start=flow_t0,
                    initial_input=dict(snapshot.initial_input),
                    tool_step_count=len(log),
                )

        # Flow-level context-schema validation (issue #152).
        if flow.context_schema is not None:
            context_record = self._validate_flow_schema(
                flow_name=flow_name,
                payload=context,
                schema=flow.context_schema,
                step_index=len(flow.steps),
                context_label="flow_context",
            )
            if context_record is not None:
                return self._make_result(
                    flow_name=flow_name,
                    success=False,
                    final_output=None,
                    execution_log=[*log, context_record],
                    trace_id=trace_id,
                    started_at=flow_started_at,
                    perf_start=flow_t0,
                    initial_input=dict(snapshot.initial_input),
                    tool_step_count=len(log),
                )

        return self._make_result(
            flow_name=flow_name,
            success=True,
            final_output=context,
            execution_log=log,
            trace_id=trace_id,
            started_at=flow_started_at,
            perf_start=flow_t0,
            initial_input=dict(snapshot.initial_input),
        )

    def _resume_dag_flow(
        self,
        flow: DAGFlow,
        snapshot: ExecutionSnapshot,
    ) -> ExecutionResult:
        """Continue a DAG execution from *snapshot.completed_dag_levels*."""
        # Use the resume slot the existing _execute_dag_flow consults
        # to seed context, log, and starting level.  Cleanup happens
        # via the try/finally in resume_flow's caller — but resume_flow
        # doesn't wrap in try/finally; we wrap here instead to keep
        # the contract local.
        self._resume_snapshot = snapshot
        try:
            return self._execute_dag_flow(flow, dict(snapshot.initial_input))
        finally:
            self._resume_snapshot = None

    def _record_observed_trace(self, result: ExecutionResult) -> None:
        """Mirror an :class:`ExecutionResult` into the configured TraceRecorder."""
        recorder = self._trace_recorder
        assert recorder is not None
        ad_hoc_id = recorder.start_trace(source=f"executor:{result.flow_name}")
        for record in result.execution_log:
            recorder.record_step(
                ad_hoc_id,
                record.tool_name,
                inputs=record.inputs,
                outputs=record.outputs,
                duration_ms=record.duration_ms,
            )
        recorder.end_trace(ad_hoc_id)

    def _validate_flow_schema(
        self,
        *,
        flow_name: str,
        payload: dict[str, Any],
        schema: type[BaseModel],
        step_index: int,
        context_label: str,
    ) -> StepRecord | None:
        """Validate flow-level input or output against *schema*.

        Returns ``None`` on success, or a failed :class:`StepRecord` on
        validation error.
        """
        started_at = _now_utc()
        t0 = time.perf_counter()
        try:
            schema.model_validate(payload)
        except ValidationError as exc:
            wrapped = SchemaValidationError(flow_name, step_index, str(exc), context=context_label)
            err_type, err_msg = _exc_to_strings(wrapped)
            ended_at = _now_utc()
            return StepRecord(
                step_index=step_index,
                tool_name=flow_name,
                inputs=dict(payload),
                error_type=err_type,
                error_message=err_msg,
                success=False,
                started_at=started_at,
                ended_at=ended_at,
                duration_ms=(time.perf_counter() - t0) * 1000.0,
            )
        return None

    def _check_step_contract(
        self,
        *,
        step: FlowStep,
        step_index: int,
        payload: dict[str, Any],
        contract: type[BaseModel],
        context_label: str,
    ) -> SchemaValidationError | None:
        """Validate a step-level contract against *payload* (issue #172).

        Returns ``None`` on success, or a :class:`SchemaValidationError`
        ready to be wrapped into a :class:`StepRecord` by the caller's
        normal ``on_error`` / ``_record`` machinery.
        """
        try:
            contract.model_validate(payload)
        except ValidationError as exc:
            return SchemaValidationError(
                step.display_name,
                step_index,
                str(exc),
                context=context_label,
            )
        return None

    def _resolve_inputs(
        self,
        step: FlowStep,
        context: dict[str, Any],
        step_index: int,
    ) -> dict[str, Any]:
        """Resolve a step's *input_mapping* against the current *context*.

        If *input_mapping* is empty the full *context* is returned as-is.

        Args:
            step: The flow step whose inputs need to be resolved.
            context: The accumulated context built from the initial input and
                all previous step outputs.
            step_index: Zero-based index used for error messages.

        Returns:
            A dictionary ready to be passed to the tool.

        Raises:
            InputMappingError: When a string mapping value is not present in
                *context*.
        """
        if not step.input_mapping:
            return dict(context)

        resolved: dict[str, Any] = {}
        step_label = step.display_name or step.flow_name or "<step>"
        for target_key, source in step.input_mapping.items():
            if isinstance(source, str):
                if source not in context:
                    raise InputMappingError(step_label, step_index, source)
                resolved[target_key] = context[source]
            else:
                # Literal constant — use the value directly.
                resolved[target_key] = source
        return resolved

    def _execute_capability_step(
        self,
        step_index: int,
        step: DAGFlowStep,
        context: dict[str, Any],
        flow_name: str,
        trace_id: str,
    ) -> StepRecord:
        """Dispatch a ``step_type != "tool"`` step (issue #89).

        Hook for subclasses such as
        :class:`~chainweaver.integrations.agent_kernel.KernelBackedExecutor`
        to delegate capability steps to an external runner.  The base
        :class:`FlowExecutor` does not know how to execute capabilities
        and always returns a failed :class:`StepRecord` carrying a
        :class:`~chainweaver.exceptions.FlowExecutionError`.

        Args:
            step_index: Zero-based position of the step in the flow.
            step: The :class:`DAGFlowStep` whose ``step_type`` is not
                ``"tool"``.
            context: The current accumulated context (read-only here).
            flow_name: Name of the enclosing flow, for diagnostics.
            trace_id: Trace id of the enclosing execution, for diagnostics.

        Returns:
            A :class:`StepRecord` describing the failure.  Subclasses
            return a successful record after dispatching the capability.
        """
        err = FlowExecutionError(
            step.display_name,
            step_index,
            f"Step '{step.step_id}' has step_type='{step.step_type}' "
            f"which is not supported by FlowExecutor. "
            f"Only step_type='tool' can be executed — use "
            f"KernelBackedExecutor for capability-typed steps.",
        )
        log_step_error(_logger, step_index, step.display_name, err)
        err_type, err_msg = _exc_to_strings(err)
        now = _now_utc()
        return StepRecord(
            step_index=step_index,
            tool_name=step.display_name,
            inputs={},
            outputs=None,
            error_type=err_type,
            error_message=err_msg,
            success=False,
            started_at=now,
            ended_at=now,
            duration_ms=0.0,
        )

    def _validate_composition(self, flow: AnyFlow) -> None:
        """Reject invalid sub-flow composition before execution (issue #75).

        Walks the ``flow_name`` reference graph reachable from *flow* and
        raises :class:`FlowCompositionError` on a cycle, on nesting deeper
        than :attr:`_max_composition_depth`, or on a reference to a flow that
        is not registered.  A flow with no ``flow_name`` steps is validated in
        O(steps) and never recurses.
        """

        def visit(current: AnyFlow, path: tuple[str, ...]) -> None:
            for step in current.steps:
                sub_name = getattr(step, "flow_name", None)
                if sub_name is None:
                    continue
                if sub_name in path:
                    chain = " -> ".join([*path, sub_name])
                    raise FlowCompositionError(
                        flow.name, "cycle", f"circular sub-flow reference: {chain}"
                    )
                if len(path) > self._max_composition_depth:
                    chain = " -> ".join([*path, sub_name])
                    raise FlowCompositionError(
                        flow.name,
                        "max_depth_exceeded",
                        f"nesting exceeds max_composition_depth="
                        f"{self._max_composition_depth}: {chain}",
                    )
                try:
                    sub_flow = self._registry.get_flow(sub_name)
                except FlowNotFoundError as exc:
                    raise FlowCompositionError(
                        flow.name,
                        "unknown_flow",
                        f"step references unregistered sub-flow '{sub_name}'",
                    ) from exc
                visit(sub_flow, (*path, sub_name))

        visit(flow, (flow.name,))

    def _execute_subflow_step(
        self,
        step_index: int,
        step: FlowStep,
        context: dict[str, Any],
        flow_name: str,
        trace_id: str,
        *,
        started_at: datetime,
        perf_start: float,
        deadline: float | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> StepRecord:
        """Execute a composed sub-flow step (issue #75).

        Resolves the step's inputs (the same ``input_mapping`` machinery used
        for tool steps), recursively runs the named sub-flow via
        :meth:`execute_flow`, and folds the sub-flow's final output back into
        the parent context.  The nested :class:`ExecutionResult` is attached
        to the returned :class:`StepRecord` as ``sub_result`` so the parent
        trace keeps the full sub-flow log.

        Cycles and over-deep nesting are already rejected by
        :meth:`_validate_composition` before any step runs, so the recursion
        here is bounded.
        """
        sub_name = step.flow_name
        assert sub_name is not None  # guaranteed by the caller / FlowStep validator
        try:
            sub_input = self._resolve_inputs(step, context, step_index)
        except InputMappingError as exc:
            # Pre-resolution failure: no on_step_start, mirroring the tool path.
            log_step_error(_logger, step_index, sub_name, exc)
            err_type, err_msg = _exc_to_strings(exc)
            now = _now_utc()
            return StepRecord(
                step_index=step_index,
                tool_name=sub_name,
                flow_name=sub_name,
                inputs={},
                outputs=None,
                error_type=err_type,
                error_message=err_msg,
                success=False,
                started_at=started_at,
                ended_at=now,
                duration_ms=(time.perf_counter() - perf_start) * 1000.0,
            )

        self._fire_step_start(
            StepStartContext(
                trace_id=trace_id,
                flow_name=flow_name,
                step_index=step_index,
                tool_name=sub_name,
                inputs=dict(sub_input),
                started_at=started_at,
            )
        )

        # Recurse. ``execute_flow`` resets ``_active_flow_version`` to the
        # sub-flow's version; save and restore so the parent's result is
        # stamped with the parent's version.  Forward the parent's
        # ``deadline`` / ``cancel_token`` so flow-level cancellation and the
        # wall-clock budget are observed *between* the sub-flow's own steps,
        # not just at the parent boundary (issue #142). The deadline is an
        # absolute wall-clock instant, so passing it through unchanged keeps
        # one shared budget across the whole composed run.
        saved_version = self._active_flow_version
        try:
            sub_result = self.execute_flow(
                sub_name,
                sub_input,
                deadline=deadline,
                cancel_token=cancel_token,
            )
        finally:
            self._active_flow_version = saved_version

        ended_at = _now_utc()
        duration_ms = (time.perf_counter() - perf_start) * 1000.0
        error_type: str | None = None
        error_message: str | None = None
        if not sub_result.success:
            error_type = "FlowExecutionError"
            error_message = f"Sub-flow '{sub_name}' failed."
        record = StepRecord(
            step_index=step_index,
            tool_name=sub_name,
            flow_name=sub_name,
            inputs=sub_input,
            outputs=sub_result.final_output if sub_result.success else None,
            error_type=error_type,
            error_message=error_message,
            success=sub_result.success,
            started_at=started_at,
            ended_at=ended_at,
            duration_ms=duration_ms,
            sub_result=sub_result,
        )
        self._fire_step_end(
            StepEndContext(
                trace_id=trace_id,
                flow_name=flow_name,
                step_record=record,
            )
        )
        return record

    def _execute_step(
        self,
        step_index: int,
        step: FlowStep,
        context: dict[str, Any],
        flow_name: str,
        trace_id: str,
        *,
        step_id: str | None = None,
        deadline: float | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> StepRecord:
        """Execute a single :class:`~chainweaver.flow.FlowStep`.

        Honors any :class:`RetryPolicy` attached to *step* via
        :mod:`tenacity` and applies the ``on_error`` policy
        (``"fail"`` / ``"skip"`` / ``"fallback:<tool_name>"``) when all
        attempts are exhausted.

        Fires :class:`~chainweaver.middleware.StepStartContext` once the
        step's inputs have been resolved, and always fires
        :class:`~chainweaver.middleware.StepEndContext` for the resulting
        :class:`StepRecord` (success *and* failure paths).  Steps that
        fail before input resolution — tool-not-found, input-mapping —
        do not produce a ``on_step_start`` call but still produce
        ``on_step_end``.

        Args:
            step_index: Zero-based position of the step.
            step: The step to execute.
            context: The current accumulated context.
            flow_name: Name of the enclosing flow, threaded through for
                middleware contexts.
            trace_id: Trace id of the enclosing execution, threaded
                through for middleware contexts.

        Returns:
            A :class:`StepRecord` describing the outcome with full timing.
        """
        started_at = _now_utc()
        t0 = time.perf_counter()
        # Composed sub-flow step (issue #75): recurse into the named flow
        # instead of invoking a tool.  Shared by the linear and DAG sync
        # paths since both dispatch tool steps through ``_execute_step``.
        if step.flow_name is not None:
            return self._execute_subflow_step(
                step_index,
                step,
                context,
                flow_name,
                trace_id,
                started_at=started_at,
                perf_start=t0,
                deadline=deadline,
                cancel_token=cancel_token,
            )
        # Resolve guided decision points (issue #102).  When the step
        # declares ``decision_candidates`` *and* the executor has a
        # ``decision_callback`` registered, ask the callback which
        # candidate to invoke and rebind the step to that tool for the
        # remainder of this call.  No callback registered → fall back to
        # the static ``tool_name`` so flows stay runnable without the
        # integration.  Callback failures fail the step early via
        # ``DecisionCallbackError`` — silent fall-through would mask
        # configuration bugs.
        if step.decision_candidates is not None and self._decision_callback is not None:
            try:
                chosen = self._decision_callback.decide(
                    DecisionContext(
                        trace_id=trace_id,
                        flow_name=flow_name,
                        step_index=step_index,
                        step_id=step_id,
                        default_tool_name=step.display_name,
                        candidates=list(step.decision_candidates),
                        context=dict(context),
                    )
                )
            except Exception as exc:
                err = DecisionCallbackError(
                    step.display_name,
                    step_index,
                    f"callback raised {type(exc).__name__}: {exc}",
                )
                err.__cause__ = exc
                log_step_error(_logger, step_index, step.display_name, err)
                err_type, err_msg = _exc_to_strings(err)
                now = _now_utc()
                record = StepRecord(
                    step_index=step_index,
                    tool_name=step.display_name,
                    inputs={},
                    outputs=None,
                    error_type=err_type,
                    error_message=err_msg,
                    success=False,
                    started_at=started_at,
                    ended_at=now,
                    duration_ms=(time.perf_counter() - t0) * 1000.0,
                )
                self._fire_step_end(
                    StepEndContext(trace_id=trace_id, flow_name=flow_name, step_record=record)
                )
                return record
            if chosen not in step.decision_candidates:
                err = DecisionCallbackError(
                    step.display_name,
                    step_index,
                    f"callback returned '{chosen}' which is not in "
                    f"decision_candidates={list(step.decision_candidates)!r}",
                )
                log_step_error(_logger, step_index, step.display_name, err)
                err_type, err_msg = _exc_to_strings(err)
                now = _now_utc()
                record = StepRecord(
                    step_index=step_index,
                    tool_name=step.display_name,
                    inputs={},
                    outputs=None,
                    error_type=err_type,
                    error_message=err_msg,
                    success=False,
                    started_at=started_at,
                    ended_at=now,
                    duration_ms=(time.perf_counter() - t0) * 1000.0,
                )
                self._fire_step_end(
                    StepEndContext(trace_id=trace_id, flow_name=flow_name, step_record=record)
                )
                return record
            if chosen != step.display_name:
                step = step.model_copy(update={"tool_name": chosen})
        # Mutable holder so ``_invoke_tool`` can report how many times the
        # primary tool was actually called.  Threading this through (instead
        # of deriving from ``len(retry_errors)``) keeps ``retry_count``
        # accurate when ``on_error="skip"`` or ``on_error="fallback:…"``
        # appends extra entries to ``retry_errors`` for context.
        tool_attempts = [0]

        def _record(
            *,
            inputs: dict[str, Any],
            outputs: dict[str, Any] | None,
            error: Exception | None,
            success: bool,
            skipped: bool,
            retry_errors: list[str],
            cached: bool = False,
            fallback_used: bool = False,
        ) -> StepRecord:
            err_type, err_msg = (None, None) if error is None else _exc_to_strings(error)
            # ``retry_count`` = retries beyond the initial invocation.
            # Derive from the actual primary-tool attempt count so that
            # ``on_error="skip"`` / ``on_error="fallback:…"`` paths (which
            # may decorate ``retry_errors``) don't distort the value.
            retry_count = max(0, tool_attempts[0] - 1)
            return StepRecord(
                step_index=step_index,
                tool_name=step.display_name,
                inputs=inputs,
                outputs=outputs,
                error_type=err_type,
                error_message=err_msg,
                success=success,
                started_at=started_at,
                ended_at=_now_utc(),
                duration_ms=(time.perf_counter() - t0) * 1000.0,
                retry_count=retry_count,
                retry_errors=list(retry_errors),
                skipped=skipped,
                cached=cached,
                fallback_used=fallback_used,
            )

        def _finish(record: StepRecord) -> StepRecord:
            self._fire_step_end(
                StepEndContext(
                    trace_id=trace_id,
                    flow_name=flow_name,
                    step_record=record,
                )
            )
            return record

        try:
            tool = self.get_tool(step.display_name)
        except ToolNotFoundError as exc:
            log_step_error(_logger, step_index, step.display_name, exc)
            return _finish(
                _record(
                    inputs={},
                    outputs=None,
                    error=exc,
                    success=False,
                    skipped=False,
                    retry_errors=[],
                )
            )

        try:
            inputs = self._resolve_inputs(step, context, step_index)
        except InputMappingError as exc:
            log_step_error(_logger, step_index, step.display_name, exc)
            return _finish(
                _record(
                    inputs={},
                    outputs=None,
                    error=exc,
                    success=False,
                    skipped=False,
                    retry_errors=[],
                )
            )

        # Step-level input contract (issue #172).  Validates the resolved
        # inputs against the step's declared shape before the tool runs.
        # Surfaces input_mapping mistakes with a typed error rather than
        # waiting for the tool's own validation to fail.
        if step.input_contract is not None:
            input_contract_cls = step.resolved_input_contract
            assert input_contract_cls is not None
            contract_err = self._check_step_contract(
                step=step,
                step_index=step_index,
                payload=inputs,
                contract=input_contract_cls,
                context_label="step_input_contract",
            )
            if contract_err is not None:
                log_step_error(_logger, step_index, step.display_name, contract_err)
                return _finish(
                    _record(
                        inputs=inputs,
                        outputs=None,
                        error=contract_err,
                        success=False,
                        skipped=False,
                        retry_errors=[],
                    )
                )

        self._fire_step_start(
            StepStartContext(
                trace_id=trace_id,
                flow_name=flow_name,
                step_index=step_index,
                tool_name=step.display_name,
                inputs=dict(inputs),
                started_at=started_at,
            )
        )

        log_step_start(
            _logger,
            step_index,
            step.display_name,
            inputs,
            redaction=self._redaction_policy,
        )

        # Cache lookup (issue #127).  Skip caching during replay_flow
        # (replay always re-executes) and for tools that opt out via
        # ``cacheable=False``.  Input validation runs inside the cache
        # path so we can hash the *validated* form — equivalent inputs
        # that differ only in field ordering or coercion collapse onto
        # the same key.  If validation fails, fall through to the
        # normal execution path, which surfaces the same error.
        cache_key: StepCacheKey | None = None
        if self._step_cache is not None and tool.cacheable and not self._in_replay:
            try:
                validated = tool.input_schema.model_validate(inputs)
            except ValidationError:
                validated = None  # let the normal path raise
            if validated is not None:
                cache_key = StepCacheKey(
                    tool_name=tool.name,
                    schema_hash=tool.schema_hash,
                    input_value_hash=compute_input_value_hash(validated),
                )
                cached_output = self._step_cache.get(cache_key)
                if cached_output is not None:
                    # Apply step-level output contract on cache-hit too —
                    # different steps may share a cache entry via the same
                    # (tool_name, schema_hash, input_value_hash) but declare
                    # different output_contract refs.  Without this check
                    # the contract-bearing step silently accepts whatever
                    # was cached by a contract-less step.
                    if step.output_contract is not None:
                        cached_contract_cls = step.resolved_output_contract
                        assert cached_contract_cls is not None
                        cached_contract_err = self._check_step_contract(
                            step=step,
                            step_index=step_index,
                            payload=cached_output,
                            contract=cached_contract_cls,
                            context_label="step_output_contract",
                        )
                        if cached_contract_err is not None:
                            log_step_error(
                                _logger, step_index, step.display_name, cached_contract_err
                            )
                            return _finish(
                                _record(
                                    inputs=inputs,
                                    outputs=None,
                                    error=cached_contract_err,
                                    success=False,
                                    skipped=False,
                                    retry_errors=[],
                                )
                            )

                    log_step_end(
                        _logger,
                        step_index,
                        step.display_name,
                        cached_output,
                        redaction=self._redaction_policy,
                    )
                    return _finish(
                        _record(
                            inputs=inputs,
                            outputs=cached_output,
                            error=None,
                            success=True,
                            skipped=False,
                            retry_errors=[],
                            cached=True,
                        )
                    )

        retry_errors: list[str] = []
        outputs: dict[str, Any] | None = None
        final_raw_exc: Exception | None = None

        try:
            outputs = self._invoke_tool(tool, inputs, step.retry, retry_errors, tool_attempts)
        except Exception as exc:
            final_raw_exc = exc

        if final_raw_exc is not None:
            wrapped = self._wrap_tool_exception(step, step_index, final_raw_exc)
            log_step_error(_logger, step_index, step.display_name, wrapped)
            return _finish(
                self._apply_on_error(
                    step=step,
                    step_index=step_index,
                    inputs=inputs,
                    wrapped_error=wrapped,
                    retry_errors=retry_errors,
                    make_record=_record,
                )
            )

        assert outputs is not None
        log_step_end(
            _logger,
            step_index,
            step.display_name,
            outputs,
            redaction=self._redaction_policy,
        )

        # Step-level output contract (issue #172).  Validates the tool's
        # outputs against the step's declared shape before the cache
        # records anything and before the outputs are merged into the
        # accumulated context.
        if step.output_contract is not None:
            output_contract_cls = step.resolved_output_contract
            assert output_contract_cls is not None
            contract_err = self._check_step_contract(
                step=step,
                step_index=step_index,
                payload=outputs,
                contract=output_contract_cls,
                context_label="step_output_contract",
            )
            if contract_err is not None:
                log_step_error(_logger, step_index, step.display_name, contract_err)
                return _finish(
                    _record(
                        inputs=inputs,
                        outputs=None,
                        error=contract_err,
                        success=False,
                        skipped=False,
                        retry_errors=retry_errors,
                    )
                )

        # Cache write happens *after* the output has been schema-validated
        # by ``Tool.run`` — never store invalid output.
        if cache_key is not None and self._step_cache is not None:
            self._step_cache.set(cache_key, outputs)
        return _finish(
            _record(
                inputs=inputs,
                outputs=outputs,
                error=None,
                success=True,
                skipped=False,
                retry_errors=retry_errors,
            )
        )

    def _invoke_tool(
        self,
        tool: Tool,
        inputs: dict[str, Any],
        policy: RetryPolicy | None,
        retry_errors: list[str],
        attempts: list[int],
    ) -> dict[str, Any]:
        """Invoke ``tool.run(inputs)``, optionally retrying via *policy*.

        Each failed attempt's message is appended to *retry_errors* in order.
        Every primary-tool invocation increments ``attempts[0]`` (a mutable
        single-element holder), so the caller can compute ``retry_count``
        without conflating it with on-error decorations.  The final
        exception (after exhaustion or a non-retryable error) is re-raised;
        the caller is responsible for wrapping it.
        """
        if policy is None:
            attempts[0] += 1
            try:
                return tool.run(inputs)
            except Exception as exc:
                retry_errors.append(str(exc))
                raise

        def _wait_fn(retry_state: Any) -> float:
            return policy.compute_delay(retry_state.attempt_number)

        retryer = Retrying(
            stop=stop_after_attempt(policy.max_retries + 1),
            wait=_wait_fn if policy.max_retries > 0 else wait_fixed(0),
            retry=retry_if_exception_type(policy.resolved_retryable_errors()),
            reraise=True,
        )

        def _wrapped() -> dict[str, Any]:
            attempts[0] += 1
            try:
                return tool.run(inputs)
            except Exception as exc:
                retry_errors.append(str(exc))
                raise

        try:
            return retryer(_wrapped)
        except RetryError as exc:  # pragma: no cover — reraise=True avoids this
            inner = exc.last_attempt.exception()
            assert inner is not None
            raise inner from exc

    def _wrap_tool_exception(
        self,
        step: FlowStep,
        step_index: int,
        exc: Exception,
    ) -> Exception:
        """Convert a tool-side exception into the right ChainWeaver type.

        - :class:`ValidationError` → :class:`SchemaValidationError`
        - :class:`ToolTimeoutError` / :class:`ToolOutputSizeError` are passed
          through (their ``error_type`` is preserved on the StepRecord).
        - Any other exception → :class:`FlowExecutionError`.
        """
        if isinstance(exc, ValidationError):
            return SchemaValidationError(step.display_name, step_index, str(exc))
        if isinstance(exc, (ToolTimeoutError, ToolOutputSizeError)):
            return exc
        return FlowExecutionError(step.display_name, step_index, str(exc))

    def _apply_on_error(
        self,
        *,
        step: FlowStep,
        step_index: int,
        inputs: dict[str, Any],
        wrapped_error: Exception,
        retry_errors: list[str],
        make_record: Callable[..., StepRecord],
    ) -> StepRecord:
        """Apply the step's ``on_error`` policy and return a final record.

        - ``"fail"``: return a failed record (default).
        - ``"skip"``: return a successful, ``skipped=True`` record with
          empty outputs so the flow continues without merging anything.
        - ``"fallback:<tool_name>"``: invoke the named tool with the same
          inputs.  If it succeeds, return a successful record using its
          outputs.  If it fails, return a failed record carrying the
          fallback's exception (the original error stays in ``retry_errors``).
        """
        on_error = step.on_error
        if on_error == "fail":
            return make_record(
                inputs=inputs,
                outputs=None,
                error=wrapped_error,
                success=False,
                skipped=False,
                retry_errors=retry_errors,
            )

        if on_error == "skip":
            return make_record(
                inputs=inputs,
                outputs={},
                error=wrapped_error,
                success=True,
                skipped=True,
                retry_errors=retry_errors,
            )

        # on_error == "fallback:<tool_name>"
        fallback_name = on_error[len("fallback:") :]
        try:
            fallback_tool = self.get_tool(fallback_name)
        except ToolNotFoundError as missing:
            # The fallback tool itself is missing — we attempted the
            # fallback policy, so the record reflects that even though
            # no fallback tool actually ran.
            return make_record(
                inputs=inputs,
                outputs=None,
                error=missing,
                success=False,
                skipped=False,
                retry_errors=[*retry_errors, str(wrapped_error)],
                fallback_used=True,
            )

        try:
            outputs = fallback_tool.run(inputs)
        except Exception as fallback_exc:
            wrapped = self._wrap_tool_exception(step, step_index, fallback_exc)
            return make_record(
                inputs=inputs,
                outputs=None,
                error=wrapped,
                success=False,
                skipped=False,
                retry_errors=[*retry_errors, str(wrapped_error)],
                fallback_used=True,
            )

        return make_record(
            inputs=inputs,
            outputs=outputs,
            error=None,
            success=True,
            skipped=False,
            retry_errors=[*retry_errors, str(wrapped_error)],
            fallback_used=True,
        )

    # ------------------------------------------------------------------
    # DAG execution
    # ------------------------------------------------------------------

    def _select_branch(
        self,
        *,
        step: DAGFlowStep,
        context: dict[str, Any],
        level_outputs: dict[str, Any],
        step_outputs: dict[str, Any] | None,
    ) -> str | None | PredicateSyntaxError:
        """Resolve a branching step's outgoing edge (issue #9).

        Builds the post-step view of the execution context (initial
        context + completed levels + sibling outputs from the current
        level + this step's outputs), walks ``step.branches`` in order,
        and returns the first matching target.  Falls back to
        ``step.default_next`` when no predicate matches.  Returns
        ``None`` when nothing matches and no default is set — branching
        had no effect and every dependent runs as usual.

        Returns the :class:`PredicateSyntaxError` instance instead of
        raising so the caller can fold the failure into the standard
        synthetic-record / abort path.
        """
        post_context: dict[str, Any] = {**context, **level_outputs}
        if step_outputs:
            post_context.update(step_outputs)
        try:
            for edge in step.branches:
                if evaluate_predicate(edge.predicate, post_context):
                    return edge.target_step_id
        except PredicateSyntaxError as exc:
            return exc
        if step.default_next is not None:
            return step.default_next
        return None

    def _compute_dag_levels(self, flow: DAGFlow) -> list[list[DAGFlowStep]]:
        """Return steps grouped into topological execution levels.

        Within each level all steps are independent (no inter-level edges).
        Steps in the same level can conceptually run in parallel; today they
        run sequentially in list order.

        Topology is normally validated at registration time.  This method
        still calls ``validate_dag_topology`` as a belt-and-suspenders guard
        for flows that are created and executed without going through
        :class:`~chainweaver.registry.FlowRegistry`, so invalid DAGs may
        raise :class:`~chainweaver.exceptions.DAGDefinitionError` here.

        Level computation uses :class:`graphlib.TopologicalSorter` to iterate
        steps in dependency order, so the result is correct regardless of the
        declaration order of steps in ``flow.steps``.

        Args:
            flow: A valid :class:`~chainweaver.flow.DAGFlow`.

        Returns:
            A list of levels, each level being a list of
            :class:`~chainweaver.flow.DAGFlowStep` objects.
        """
        validate_dag_topology(flow)
        step_by_id = {s.step_id: s for s in flow.steps}
        graph: dict[str, set[str]] = {s.step_id: set(s.depends_on) for s in flow.steps}
        sorter: TopologicalSorter[str] = TopologicalSorter(graph)
        topo_order = list(sorter.static_order())

        # level[step_id] = 0-based level index
        levels: dict[str, int] = {}
        for step_id in topo_order:
            step = step_by_id[step_id]
            if not step.depends_on:
                levels[step_id] = 0
            else:
                levels[step_id] = max(levels[dep] for dep in step.depends_on) + 1

        max_level = max(levels.values(), default=-1)
        grouped: list[list[DAGFlowStep]] = [[] for _ in range(max_level + 1)]
        for step_id in topo_order:
            grouped[levels[step_id]].append(step_by_id[step_id])
        return grouped

    def _execute_dag_flow(
        self,
        flow: DAGFlow,
        initial_input: dict[str, Any],
        *,
        deadline: float | None = None,
        cancel_token: CancellationToken | None = None,
    ) -> ExecutionResult:
        """Execute a :class:`~chainweaver.flow.DAGFlow`.

        Steps are executed level-by-level in topological order.  Within each
        level steps run sequentially.  Outputs from all steps in a level are
        collected and merged into the shared context before the next level
        starts.  If two sibling steps (same level) produce the same output
        key a :class:`~chainweaver.exceptions.FlowExecutionError` is raised
        immediately to preserve determinism.

        Args:
            flow: The :class:`~chainweaver.flow.DAGFlow` to execute.
            initial_input: Initial key/value context.
            deadline: Optional wall-clock deadline (issue #142), checked
                between topological levels — in-flight level steps complete.
            cancel_token: Optional :class:`CancellationToken` (issue #142),
                checked between topological levels.

        Returns:
            An :class:`ExecutionResult` with the full execution log.
        """
        self._active_flow_version = flow.version
        # Resume support (issue #128): when _resume_snapshot is set,
        # reuse its trace_id / started_at / context / log and skip the
        # already-completed DAG levels.
        resume = self._resume_snapshot
        if resume is not None:
            trace_id = resume.trace_id
            flow_started_at = resume.started_at
            start_level = resume.completed_dag_levels
        else:
            trace_id = _new_trace_id()
            flow_started_at = _now_utc()
            start_level = 0
        flow_t0 = time.perf_counter()
        _logger.info(
            "DAGFlow '%s' %s | trace_id=%s | steps=%d",
            flow.name,
            "resuming" if resume is not None else "started",
            trace_id,
            len(flow.steps),
        )
        self._fire_flow_start(
            FlowStartContext(
                trace_id=trace_id,
                flow_name=flow.name,
                flow_version=flow.version,
                initial_input=dict(initial_input),
                started_at=flow_started_at,
                total_steps=len(flow.steps),
            )
        )

        # -- Flow-level input validation (skipped on resume — already done) ----
        if resume is None and flow.input_schema is not None:
            validation_record = self._validate_flow_schema(
                flow_name=flow.name,
                payload=initial_input,
                schema=flow.input_schema,
                step_index=-1,
                context_label="flow_input",
            )
            if validation_record is not None:
                _logger.error(
                    "DAGFlow '%s' input validation failed: %s",
                    flow.name,
                    validation_record.error_message,
                )
                return self._make_result(
                    flow_name=flow.name,
                    success=False,
                    final_output=None,
                    execution_log=[validation_record],
                    trace_id=trace_id,
                    started_at=flow_started_at,
                    perf_start=flow_t0,
                    initial_input=initial_input,
                    tool_step_count=0,
                )

        if resume is not None:
            context = dict(resume.context)
            log = list(resume.execution_log)
            flat_index = len(log)
        else:
            context = dict(initial_input)
            log = []
            flat_index = 0
        levels = self._compute_dag_levels(flow)

        # Conditional-branch bookkeeping (issue #9).
        #
        # ``skipped_ids`` accumulates step ids that branch routing has
        # deactivated — either by direct selection (a branch picked a
        # sibling) or by transitive skip-propagation (every predecessor
        # of the step is itself skipped, so no live path reaches it).
        #
        # ``dependents_map`` is the inverse of ``depends_on``: for each
        # step id, the set of step ids that list it as a predecessor.
        # Building it once up front lets the "select target X, skip
        # other dependents" step run in O(|dependents|).
        skipped_ids: set[str] = set()
        dependents_map: dict[str, set[str]] = {step.step_id: set() for step in flow.steps}
        for s in flow.steps:
            for dep in s.depends_on:
                dependents_map[dep].add(s.step_id)

        for relative_level_idx, level_steps in enumerate(levels[start_level:]):
            # Cooperative cancellation between topological levels (issue #142):
            # steps already dispatched in the previous level have completed;
            # we stop before starting the next one. Pure clock/boolean reads.
            self._check_cancellation(
                flow_name=flow.name,
                next_step_index=flat_index,
                deadline=deadline,
                cancel_token=cancel_token,
                execution_log=log,
                trace_id=trace_id,
                started_at=flow_started_at,
                perf_start=flow_t0,
                initial_input=initial_input,
            )
            absolute_level_idx = start_level + relative_level_idx
            level_outputs: dict[str, Any] = {}
            level_records: list[StepRecord] = []

            for step in level_steps:
                # Skip propagation (issue #9): a step whose every predecessor
                # is already skipped has no live path reaching it, so it is
                # also skipped.  Roots (depends_on == []) are never skipped
                # by this rule — they always run unless explicitly marked.
                if (
                    step.step_id not in skipped_ids
                    and step.depends_on
                    and all(dep in skipped_ids for dep in step.depends_on)
                ):
                    skipped_ids.add(step.step_id)

                if step.step_id in skipped_ids:
                    now = _now_utc()
                    level_records.append(
                        StepRecord(
                            step_index=flat_index,
                            tool_name=step.display_name,
                            inputs={},
                            outputs={},
                            success=True,
                            skipped=True,
                            started_at=now,
                            ended_at=now,
                            duration_ms=0.0,
                        )
                    )
                    flat_index += 1
                    continue

                # Dispatch ``step_type="capability"`` through the
                # subclass hook (issue #89).  The base FlowExecutor
                # rejects capability steps; KernelBackedExecutor
                # overrides ``_execute_capability_step`` to delegate to
                # an agent-kernel.  Either way the result is a
                # StepRecord we can append and (on failure) abort the
                # flow on.
                if step.step_type != "tool":
                    record = self._execute_capability_step(
                        flat_index, step, context, flow.name, trace_id
                    )
                    # Capability steps are dispatched through the
                    # ``_execute_capability_step`` hook, bypassing
                    # ``_execute_step``'s lifecycle firing.  Emit the same
                    # events here so middleware, tracing, and ``stream_flow``
                    # observe capability steps too.  Mirror ``_execute_step``:
                    # ``on_step_start`` fires only once the step ran past input
                    # resolution (skipped for pre-resolution failures such as
                    # the base-class rejection or a missing input mapping);
                    # ``on_step_end`` always fires.
                    if record.success or record.inputs:
                        self._fire_step_start(
                            StepStartContext(
                                trace_id=trace_id,
                                flow_name=flow.name,
                                step_index=record.step_index,
                                tool_name=step.display_name,
                                inputs=dict(record.inputs),
                                started_at=record.started_at,
                            )
                        )
                    self._fire_step_end(
                        StepEndContext(
                            trace_id=trace_id,
                            flow_name=flow.name,
                            step_record=record,
                        )
                    )
                    level_records.append(record)
                    flat_index += 1
                    if not record.success:
                        log.extend(level_records)
                        return self._make_result(
                            flow_name=flow.name,
                            success=False,
                            final_output=None,
                            execution_log=log,
                            trace_id=trace_id,
                            started_at=flow_started_at,
                            perf_start=flow_t0,
                            initial_input=initial_input,
                        )
                    assert record.outputs is not None
                    for key, value in record.outputs.items():
                        if key in level_outputs:
                            conflict_err = FlowExecutionError(
                                step.display_name,
                                record.step_index,
                                f"Key '{key}' produced by both '{step.display_name}' and a "
                                f"sibling step in the same DAG level — execution "
                                f"would be order-dependent.",
                            )
                            log_step_error(
                                _logger, record.step_index, step.display_name, conflict_err
                            )
                            err_type, err_msg = _exc_to_strings(conflict_err)
                            now = _now_utc()
                            level_records[-1] = StepRecord(
                                step_index=record.step_index,
                                tool_name=step.display_name,
                                inputs=record.inputs,
                                outputs=None,
                                error_type=err_type,
                                error_message=err_msg,
                                success=False,
                                started_at=record.started_at,
                                ended_at=now,
                                duration_ms=record.duration_ms,
                            )
                            log.extend(level_records)
                            return self._make_result(
                                flow_name=flow.name,
                                success=False,
                                final_output=None,
                                execution_log=log,
                                trace_id=trace_id,
                                started_at=flow_started_at,
                                perf_start=flow_t0,
                                initial_input=initial_input,
                            )
                        level_outputs[key] = value
                    continue

                # Build a lightweight FlowStep-compatible view so _execute_step
                # can be reused without modification.  Forward the step
                # contract refs (issue #172), retry / on_error, and
                # ``decision_candidates`` (issue #102) so DAG steps honour
                # per-step contracts and guided decision points just like
                # linear flows; otherwise the proxy silently drops them.
                proxy = FlowStep(
                    tool_name=step.tool_name,
                    flow_name=step.flow_name,
                    input_mapping=step.input_mapping,
                    input_contract=step.input_contract,
                    output_contract=step.output_contract,
                    retry=step.retry,
                    on_error=step.on_error,
                    decision_candidates=step.decision_candidates,
                )
                try:
                    record = self._execute_step(
                        flat_index,
                        proxy,
                        context,
                        flow.name,
                        trace_id,
                        step_id=step.step_id,
                        deadline=deadline,
                        cancel_token=cancel_token,
                    )
                except FlowCancelledError as exc:
                    # Cancellation fired inside a composed sub-flow; re-anchor it
                    # to this parent DAG so its flow_end fires and the partial
                    # carries the levels completed so far + this level's siblings.
                    self._reraise_subflow_cancellation(
                        exc,
                        parent_flow_name=flow.name,
                        step=proxy,
                        flat_step_index=flat_index,
                        prior_log=[*log, *level_records],
                        trace_id=trace_id,
                        started_at=flow_started_at,
                        perf_start=flow_t0,
                        initial_input=initial_input,
                    )
                level_records.append(record)
                flat_index += 1

                if not record.success:
                    log.extend(level_records)
                    _logger.error(
                        "DAGFlow '%s' aborted at step %d (%s) | trace_id=%s",
                        flow.name,
                        record.step_index,
                        step.display_name,
                        trace_id,
                    )
                    return self._make_result(
                        flow_name=flow.name,
                        success=False,
                        final_output=None,
                        execution_log=log,
                        trace_id=trace_id,
                        started_at=flow_started_at,
                        perf_start=flow_t0,
                        initial_input=initial_input,
                    )

                assert record.outputs is not None  # success guarantees outputs
                # Detect sibling key conflicts to preserve determinism.
                for key, value in record.outputs.items():
                    if key in level_outputs:
                        conflict_err = FlowExecutionError(
                            step.display_name,
                            record.step_index,
                            f"Key '{key}' produced by both '{step.display_name}' and a "
                            f"sibling step in the same DAG level. "
                            f"Use distinct output keys or sequential steps.",
                        )
                        err_type, err_msg = _exc_to_strings(conflict_err)
                        record_conflict = StepRecord(
                            step_index=record.step_index,
                            tool_name=step.display_name,
                            inputs=record.inputs,
                            error_type=err_type,
                            error_message=err_msg,
                            success=False,
                            started_at=record.started_at,
                            ended_at=_now_utc(),
                            duration_ms=record.duration_ms,
                        )
                        log.extend(level_records[:-1])
                        log.append(record_conflict)
                        _logger.error(
                            "DAGFlow '%s': sibling key conflict on '%s'",
                            flow.name,
                            key,
                        )
                        return self._make_result(
                            flow_name=flow.name,
                            success=False,
                            final_output=None,
                            execution_log=log,
                            trace_id=trace_id,
                            started_at=flow_started_at,
                            perf_start=flow_t0,
                            initial_input=initial_input,
                        )
                    level_outputs[key] = value

                # Branch evaluation (issue #9): the step succeeded; if it
                # carries conditional edges, pick the active downstream
                # path and mark non-selected dependents as skipped.
                if step.branches:
                    branch_outcome = self._select_branch(
                        step=step,
                        context=context,
                        level_outputs=level_outputs,
                        step_outputs=record.outputs,
                    )
                    if isinstance(branch_outcome, PredicateSyntaxError):
                        err_type, err_msg = _exc_to_strings(branch_outcome)
                        # The step ran exactly once, so its log must hold one
                        # record.  Convert the step's own (successful) record
                        # to a failure in place rather than appending a second
                        # record at ``flat_index`` — a second record would make
                        # ``len(log)`` exceed the number of executed steps and
                        # shift step indexes.  Mirrors the sibling-conflict
                        # handling above.
                        record_failed = StepRecord(
                            step_index=record.step_index,
                            tool_name=step.display_name,
                            inputs=record.inputs,
                            error_type=err_type,
                            error_message=err_msg,
                            success=False,
                            started_at=record.started_at,
                            ended_at=_now_utc(),
                            duration_ms=record.duration_ms,
                        )
                        log.extend(level_records[:-1])
                        log.append(record_failed)
                        _logger.error(
                            "DAGFlow '%s' branch evaluation failed at step '%s': %s",
                            flow.name,
                            step.step_id,
                            err_msg,
                        )
                        return self._make_result(
                            flow_name=flow.name,
                            success=False,
                            final_output=None,
                            execution_log=log,
                            trace_id=trace_id,
                            started_at=flow_started_at,
                            perf_start=flow_t0,
                            initial_input=initial_input,
                        )
                    selected = branch_outcome
                    if selected is not None:
                        for dep_id in dependents_map[step.step_id]:
                            if dep_id != selected:
                                skipped_ids.add(dep_id)

            log.extend(level_records)
            # Merge all level outputs into context after the level completes,
            # honouring the flow's collision policy (#337).  Within-level
            # sibling collisions were already rejected above.
            merge_step_outputs(
                context,
                level_outputs,
                policy=flow.on_context_collision,
                flow_name=flow.name,
                step_index=absolute_level_idx,
                step_name=f"DAG level {absolute_level_idx}",
                logger=_logger,
            )

            # DAG snapshot at level boundary (issue #128).  A resume
            # restarts from the next un-completed level — within a
            # level there is no checkpoint, so the level is replayed
            # from scratch on resume (the simplest correct semantics).
            self._save_dag_snapshot(
                trace_id=trace_id,
                flow=flow,
                initial_input=initial_input,
                started_at=flow_started_at,
                context=context,
                log=log,
                completed_levels=absolute_level_idx + 1,
            )

        # -- Flow-level output validation -----------------------------------
        if flow.output_schema is not None:
            validation_record = self._validate_flow_schema(
                flow_name=flow.name,
                payload=context,
                schema=flow.output_schema,
                step_index=len(flow.steps),
                context_label="flow_output",
            )
            if validation_record is not None:
                _logger.error(
                    "DAGFlow '%s' output validation failed: %s",
                    flow.name,
                    validation_record.error_message,
                )
                return self._make_result(
                    flow_name=flow.name,
                    success=False,
                    final_output=None,
                    execution_log=[*log, validation_record],
                    trace_id=trace_id,
                    started_at=flow_started_at,
                    perf_start=flow_t0,
                    initial_input=initial_input,
                    tool_step_count=len(log),
                )

        # -- Flow-level context-schema validation (issue #152) --------------
        if flow.context_schema is not None:
            context_record = self._validate_flow_schema(
                flow_name=flow.name,
                payload=context,
                schema=flow.context_schema,
                step_index=len(flow.steps),
                context_label="flow_context",
            )
            if context_record is not None:
                _logger.error(
                    "DAGFlow '%s' context-schema validation failed: %s",
                    flow.name,
                    context_record.error_message,
                )
                return self._make_result(
                    flow_name=flow.name,
                    success=False,
                    final_output=None,
                    execution_log=[*log, context_record],
                    trace_id=trace_id,
                    started_at=flow_started_at,
                    perf_start=flow_t0,
                    initial_input=initial_input,
                    tool_step_count=len(log),
                )

        _logger.info(
            "DAGFlow '%s' completed successfully | trace_id=%s",
            flow.name,
            trace_id,
        )
        return self._make_result(
            flow_name=flow.name,
            success=True,
            final_output=context,
            execution_log=log,
            trace_id=trace_id,
            started_at=flow_started_at,
            perf_start=flow_t0,
            initial_input=initial_input,
        )
