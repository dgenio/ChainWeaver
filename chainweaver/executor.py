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
from datetime import datetime, timezone
from graphlib import TopologicalSorter
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from chainweaver.cost import CostProfile, CostReport, compute_cost_report
from chainweaver.exceptions import (
    FlowExecutionError,
    InputMappingError,
    SchemaValidationError,
    ToolNotFoundError,
    ToolOutputSizeError,
    ToolTimeoutError,
)
from chainweaver.flow import DAGFlow, DAGFlowStep, FlowStep, validate_dag_topology
from chainweaver.log_utils import get_logger, log_step_end, log_step_error, log_step_start
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool

_logger = get_logger("chainweaver.executor")


def _now_utc() -> datetime:
    """Return the current UTC time as a timezone-aware ``datetime``."""
    return datetime.now(timezone.utc)


def _new_trace_id() -> str:
    """Return a fresh UUID4 hex string for trace correlation."""
    return uuid.uuid4().hex


def _exc_to_strings(exc: Exception) -> tuple[str, str]:
    """Render an exception as ``(error_type, error_message)`` strings."""
    return type(exc).__name__, str(exc)


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
        success: ``True`` when the step completed without error.
        started_at: UTC timestamp when the step began.
        ended_at: UTC timestamp when the step finished (success or failure).
        duration_ms: Wall-clock duration of the step in milliseconds,
            measured with :func:`time.perf_counter`.
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
            one entry per executed step, plus up to two additional entries
            for flow-level input/output schema validation when
            ``input_schema`` or ``output_schema`` are set on the flow.
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
    ) -> None:
        self._registry = registry
        self._tools: dict[str, Tool] = {}
        self._cost_profile = cost_profile

    def register_tool(self, tool: Tool) -> None:
        """Register a :class:`~chainweaver.tools.Tool` with the executor.

        Args:
            tool: The tool to register.
        """
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

    def execute_flow(
        self,
        flow_name: str,
        initial_input: dict[str, Any],
    ) -> ExecutionResult:
        """Execute a registered flow from *initial_input*.

        Args:
            flow_name: Name of the flow to execute.
            initial_input: Initial key/value context passed to the first step.

        Returns:
            An :class:`ExecutionResult` describing the outcome and containing
            the full execution log.  Step-level validation, input-mapping,
            and execution errors are recorded in the execution log and
            reported via ``ExecutionResult.success`` instead of being raised.

        Raises:
            FlowNotFoundError: When *flow_name* is not registered.
        """
        flow = self._registry.get_flow(flow_name)
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
                )

        context: dict[str, Any] = dict(initial_input)
        log: list[StepRecord] = []

        for idx, step in enumerate(flow.steps):
            record = self._execute_step(idx, step, context)
            log.append(record)

            if not record.success:
                _logger.error("Flow '%s' aborted at step %d", flow_name, idx)
                return self._make_result(
                    flow_name=flow_name,
                    success=False,
                    final_output=None,
                    execution_log=log,
                    trace_id=trace_id,
                    started_at=flow_started_at,
                    perf_start=flow_t0,
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
    ) -> ExecutionResult:
        """Build an :class:`ExecutionResult` and stamp the closing timestamps."""
        ended_at = _now_utc()
        total_ms = (time.perf_counter() - perf_start) * 1000.0
        cost_report: CostReport | None = None
        if self._cost_profile is not None:
            cost_report = compute_cost_report(
                steps_executed=len(execution_log),
                actual_execution_ms=total_ms,
                profile=self._cost_profile,
            )
        return ExecutionResult(
            flow_name=flow_name,
            success=success,
            final_output=final_output,
            execution_log=execution_log,
            trace_id=trace_id,
            started_at=started_at,
            ended_at=ended_at,
            total_duration_ms=total_ms,
            cost_report=cost_report,
        )

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
    ) -> StepRecord:
        """Execute a single :class:`~chainweaver.flow.FlowStep`.

        Args:
            step_index: Zero-based position of the step.
            step: The step to execute.
            context: The current accumulated context.

        Returns:
            A :class:`StepRecord` describing the outcome with full timing.
        """
        started_at = _now_utc()
        t0 = time.perf_counter()

        def _failed(inputs: dict[str, Any], exc: Exception) -> StepRecord:
            err_type, err_msg = _exc_to_strings(exc)
            return StepRecord(
                step_index=step_index,
                tool_name=step.tool_name,
                inputs=inputs,
                error_type=err_type,
                error_message=err_msg,
                success=False,
                started_at=started_at,
                ended_at=_now_utc(),
                duration_ms=(time.perf_counter() - t0) * 1000.0,
            )

        try:
            tool = self.get_tool(step.tool_name)
        except ToolNotFoundError as exc:
            log_step_error(_logger, step_index, step.tool_name, exc)
            return _failed({}, exc)

        try:
            inputs = self._resolve_inputs(step, context, step_index)
        except InputMappingError as exc:
            log_step_error(_logger, step_index, step.tool_name, exc)
            return _failed({}, exc)

        log_step_start(_logger, step_index, step.tool_name, inputs)

        try:
            outputs = tool.run(inputs)
        except ValidationError as exc:
            schema_err = SchemaValidationError(step.tool_name, step_index, str(exc))
            log_step_error(_logger, step_index, step.tool_name, schema_err)
            return _failed(inputs, schema_err)
        except (ToolTimeoutError, ToolOutputSizeError) as exc:
            # Guardrail failures (#43) keep their specific error_type so the
            # caller can distinguish a timeout / size violation from a generic
            # execution error.
            log_step_error(_logger, step_index, step.tool_name, exc)
            return _failed(inputs, exc)
        except Exception as exc:
            exec_err = FlowExecutionError(step.tool_name, step_index, str(exc))
            log_step_error(_logger, step_index, step.tool_name, exec_err)
            return _failed(inputs, exec_err)

        log_step_end(_logger, step_index, step.tool_name, outputs)
        return StepRecord(
            step_index=step_index,
            tool_name=step.tool_name,
            inputs=inputs,
            outputs=outputs,
            success=True,
            started_at=started_at,
            ended_at=_now_utc(),
            duration_ms=(time.perf_counter() - t0) * 1000.0,
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
                    )

                # Build a lightweight FlowStep-compatible view so _execute_step
                # can be reused without modification.
                proxy = FlowStep(
                    tool_name=step.tool_name,
                    input_mapping=step.input_mapping,
                )
                record = self._execute_step(flat_index, proxy, context)
                level_records.append(record)
                flat_index += 1

                if not record.success:
                    log.extend(level_records)
                    _logger.error(
                        "DAGFlow '%s' aborted at step %d (%s)",
                        flow.name,
                        record.step_index,
                        step.tool_name,
                    )
                    return self._make_result(
                        flow_name=flow.name,
                        success=False,
                        final_output=None,
                        execution_log=log,
                        trace_id=trace_id,
                        started_at=flow_started_at,
                        perf_start=flow_t0,
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
        )
