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

import time
import uuid
from collections.abc import Callable
from datetime import datetime, timezone
from enum import Enum
from graphlib import TopologicalSorter
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError
from tenacity import RetryError, Retrying, retry_if_exception_type, stop_after_attempt, wait_fixed

from chainweaver.cost import CostProfile, CostReport, compute_cost_report
from chainweaver.exceptions import (
    FlowExecutionError,
    FlowStatusError,
    InputMappingError,
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
    FlowEndContext,
    FlowExecutorMiddleware,
    FlowStartContext,
    StepEndContext,
    StepStartContext,
)
from chainweaver.observation import TraceRecorder
from chainweaver.registry import FlowRegistry
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
    """

    VERIFY = "verify"
    EXECUTE = "execute"


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


class ExecutionResult(BaseModel):
    """The final result of a :meth:`FlowExecutor.execute_flow` call.

    ``ExecutionResult`` is a fully serializable execution trace: every field
    round-trips through :meth:`pydantic.BaseModel.model_dump_json` and
    :meth:`pydantic.BaseModel.model_validate_json`.

    Attributes:
        flow_name: Name of the flow that was executed.
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
            milliseconds, measured with :func:`time.perf_counter`.
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
    ) -> None:
        self._registry = registry
        self._tools: dict[str, Tool] = {}
        self._cost_profile = cost_profile
        self._redaction_policy = redaction_policy
        self._trace_recorder = trace_recorder
        self._middleware: list[FlowExecutorMiddleware] = list(middleware) if middleware else []

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
        for idx, mw in enumerate(self._middleware):
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
            if step.tool_name in self._tools:
                new_hashes[step.tool_name] = self._tools[step.tool_name].schema_hash
        flow.tool_schema_hashes = new_hashes
        flow.status = FlowStatus.ACTIVE

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

        if resume_from_step <= 0:
            new_result = self.execute_flow(result.flow_name, dict(result.initial_input))
        else:
            if isinstance(flow, DAGFlow):
                raise ValueError("resume_from_step is not supported for DAGFlow yet.")
            new_result = self._replay_linear_from(flow, result, resume_from_step)

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

            try:
                tool = self.get_tool(step.tool_name)
            except ToolNotFoundError:
                tool = None
                warnings.append(f"Tool '{step.tool_name}' is not registered.")

            input_sources = self._describe_input_sources(step, projected_context, unresolved)
            input_schema_shape: dict[str, str] = {}
            output_schema_shape: dict[str, str] = {}

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
                    tool_name=step.tool_name,
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
        force: bool = False,
    ) -> ExecutionResult:
        """Execute a registered flow from *initial_input*.

        Args:
            flow_name: Name of the flow to execute.
            initial_input: Initial key/value context passed to the first step.
            force: When ``True``, bypass the status guard and execute even if
                the flow is ``NEEDS_REVIEW`` or ``DISABLED``.

        Returns:
            An :class:`ExecutionResult` describing the outcome and containing
            the full execution log.  Step-level validation, input-mapping,
            and execution errors are recorded in the execution log and
            reported via ``ExecutionResult.success`` instead of being raised.

        Raises:
            FlowNotFoundError: When *flow_name* is not registered.
            FlowStatusError: When the flow's status is not ``ACTIVE`` and
                *force* is ``False``.
        """
        flow = self._registry.get_flow(flow_name)

        if not force and flow.status != FlowStatus.ACTIVE:
            raise FlowStatusError(flow_name, flow.status.value)

        if isinstance(flow, DAGFlow):
            return self._execute_dag_flow(flow, initial_input)

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
            record = self._execute_step(idx, step, context, flow_name, trace_id)
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
                    f"Step {idx} ({step.tool_name}) succeeded but produced no outputs"
                )

            for key in record.outputs:
                if key in context:
                    _logger.debug(
                        "Step %d (%s): context key '%s' overwritten",
                        idx,
                        step.tool_name,
                        key,
                    )
            context.update(record.outputs)

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

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

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
                not append validation records.
        """
        ended_at = _now_utc()
        total_ms = (time.perf_counter() - perf_start) * 1000.0
        cost_report: CostReport | None = None
        if self._cost_profile is not None:
            cost_report = compute_cost_report(
                steps_executed=(
                    tool_step_count if tool_step_count is not None else len(execution_log)
                ),
                actual_execution_ms=total_ms,
                profile=self._cost_profile,
            )
        result = ExecutionResult(
            flow_name=flow_name,
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
        self._fire_flow_end(
            FlowEndContext(
                trace_id=trace_id,
                flow_name=flow_name,
                result=result,
            )
        )
        return result

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
        for target_key, source in step.input_mapping.items():
            if isinstance(source, str):
                if source not in context:
                    raise InputMappingError(step.tool_name, step_index, source)
                resolved[target_key] = context[source]
            else:
                # Literal constant — use the value directly.
                resolved[target_key] = source
        return resolved

    def _execute_step(
        self,
        step_index: int,
        step: FlowStep,
        context: dict[str, Any],
        flow_name: str,
        trace_id: str,
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
        ) -> StepRecord:
            err_type, err_msg = (None, None) if error is None else _exc_to_strings(error)
            # ``retry_count`` = retries beyond the initial invocation.
            # Derive from the actual primary-tool attempt count so that
            # ``on_error="skip"`` / ``on_error="fallback:…"`` paths (which
            # may decorate ``retry_errors``) don't distort the value.
            retry_count = max(0, tool_attempts[0] - 1)
            return StepRecord(
                step_index=step_index,
                tool_name=step.tool_name,
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
            tool = self.get_tool(step.tool_name)
        except ToolNotFoundError as exc:
            log_step_error(_logger, step_index, step.tool_name, exc)
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
            log_step_error(_logger, step_index, step.tool_name, exc)
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
                tool_name=step.tool_name,
                inputs=dict(inputs),
                started_at=started_at,
            )
        )

        log_step_start(
            _logger,
            step_index,
            step.tool_name,
            inputs,
            redaction=self._redaction_policy,
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
            log_step_error(_logger, step_index, step.tool_name, wrapped)
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
            step.tool_name,
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
            return SchemaValidationError(step.tool_name, step_index, str(exc))
        if isinstance(exc, (ToolTimeoutError, ToolOutputSizeError)):
            return exc
        return FlowExecutionError(step.tool_name, step_index, str(exc))

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
            return make_record(
                inputs=inputs,
                outputs=None,
                error=missing,
                success=False,
                skipped=False,
                retry_errors=[*retry_errors, str(wrapped_error)],
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
            )

        return make_record(
            inputs=inputs,
            outputs=outputs,
            error=None,
            success=True,
            skipped=False,
            retry_errors=[*retry_errors, str(wrapped_error)],
        )

    # ------------------------------------------------------------------
    # DAG execution
    # ------------------------------------------------------------------

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

        Returns:
            An :class:`ExecutionResult` with the full execution log.
        """
        trace_id = _new_trace_id()
        flow_started_at = _now_utc()
        flow_t0 = time.perf_counter()
        _logger.info(
            "DAGFlow '%s' started | trace_id=%s | steps=%d",
            flow.name,
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

        # -- Flow-level input validation ------------------------------------
        if flow.input_schema is not None:
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

        context: dict[str, Any] = dict(initial_input)
        log: list[StepRecord] = []
        levels = self._compute_dag_levels(flow)
        # Flat index for StepRecord.step_index (mirrors linear flow behaviour).
        flat_index = 0

        for level_steps in levels:
            level_outputs: dict[str, Any] = {}
            level_records: list[StepRecord] = []

            for step in level_steps:
                # Reject non-tool step types until KernelBackedExecutor exists.
                if step.step_type != "tool":
                    err = FlowExecutionError(
                        step.tool_name,
                        flat_index,
                        f"Step '{step.step_id}' has step_type='{step.step_type}' "
                        f"which is not supported by FlowExecutor. "
                        f"Only step_type='tool' can be executed.",
                    )
                    log_step_error(_logger, flat_index, step.tool_name, err)
                    err_type, err_msg = _exc_to_strings(err)
                    now = _now_utc()
                    log.extend(level_records)
                    log.append(
                        StepRecord(
                            step_index=flat_index,
                            tool_name=step.tool_name,
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

                # Build a lightweight FlowStep-compatible view so _execute_step
                # can be reused without modification.
                proxy = FlowStep(
                    tool_name=step.tool_name,
                    input_mapping=step.input_mapping,
                )
                record = self._execute_step(flat_index, proxy, context, flow.name, trace_id)
                level_records.append(record)
                flat_index += 1

                if not record.success:
                    log.extend(level_records)
                    _logger.error(
                        "DAGFlow '%s' aborted at step %d (%s) | trace_id=%s",
                        flow.name,
                        record.step_index,
                        step.tool_name,
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
                            step.tool_name,
                            record.step_index,
                            f"Key '{key}' produced by both '{step.tool_name}' and a "
                            f"sibling step in the same DAG level. "
                            f"Use distinct output keys or sequential steps.",
                        )
                        err_type, err_msg = _exc_to_strings(conflict_err)
                        record_conflict = StepRecord(
                            step_index=record.step_index,
                            tool_name=step.tool_name,
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

            log.extend(level_records)
            # Merge all level outputs into context after the level completes.
            for key in level_outputs:
                if key in context:
                    _logger.debug(
                        "DAGFlow '%s': context key '%s' overwritten by level output",
                        flow.name,
                        key,
                    )
            context.update(level_outputs)

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
