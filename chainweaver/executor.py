"""Flow executor for ChainWeaver.

The :class:`FlowExecutor` runs a registered :class:`~chainweaver.flow.Flow`
step-by-step without any LLM involvement between steps.  All data passing is
structured and schema-validated via Pydantic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from pydantic import ValidationError

from chainweaver.exceptions import (
    FlowExecutionError,
    InputMappingError,
    SchemaValidationError,
    ToolNotFoundError,
)
from chainweaver.flow import FlowStep
from chainweaver.log_utils import get_logger, log_step_end, log_step_error, log_step_start
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool

_logger = get_logger("chainweaver.executor")


@dataclass
class StepRecord:
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
        error: The exception that was raised, or ``None`` on success.
        success: ``True`` when the step completed without error.
    """

    step_index: int
    tool_name: str
    inputs: dict[str, Any]
    outputs: dict[str, Any] | None = None
    error: Exception | None = None
    success: bool = True


@dataclass
class ExecutionResult:
    """The final result of a :meth:`FlowExecutor.execute_flow` call.

    Attributes:
        flow_name: Name of the flow that was executed.
        success: ``True`` when all steps completed without error.
        final_output: The merged execution context (initial input combined
            with all step outputs), or ``None`` on failure.
        execution_log: Ordered list of :class:`StepRecord` objects.  Contains
            one entry per executed step, plus up to two additional entries
            for flow-level input/output schema validation when
            ``input_schema`` or ``output_schema`` are set on the flow.
    """

    flow_name: str
    success: bool
    final_output: dict[str, Any] | None
    execution_log: list[StepRecord] = field(default_factory=list)


class FlowExecutor:
    """Executes registered flows deterministically.

    The executor maintains a :class:`~chainweaver.registry.FlowRegistry` of
    flows and a separate registry of :class:`~chainweaver.tools.Tool` objects.
    On each :meth:`execute_flow` call it:

    1. Resolves the flow from the registry.
    2. Iterates over steps sequentially.
    3. Resolves each step's inputs by mapping context keys (or literal values).
    4. Validates inputs against the tool's *input_schema*.
    5. Calls the tool's callable.
    6. Validates outputs against the tool's *output_schema*.
    7. Merges the outputs into the shared context.
    8. Records every step in an :class:`ExecutionResult`.

    There are **no LLM calls** at any point in this process.

    Args:
        registry: The :class:`~chainweaver.registry.FlowRegistry` that holds
            the flows to execute.

    Example::

        executor = FlowExecutor(registry=my_registry)
        executor.register_tool(double_tool)
        executor.register_tool(add_tool)
        executor.register_tool(format_tool)

        result = executor.execute_flow("double_add_format", {"number": 5})
        print(result.final_output)  # {"result": "Final value: 20"}

    # TODO (Phase 2): Add async execution mode for I/O-bound tool chains.
    # TODO (Phase 2): Support DAG execution with dependency resolution and
    #   parallel step groups.
    # TODO (Phase 2): Add middleware hooks (before_step / after_step) for
    #   observability and tracing integrations.
    """

    def __init__(self, registry: FlowRegistry) -> None:
        self._registry = registry
        self._tools: dict[str, Tool] = {}

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
            the full execution log. Step-level validation, input-mapping, and
            execution errors are recorded in the execution log and reported via
            ``ExecutionResult.success`` instead of being raised.

        Raises:
            FlowNotFoundError: When *flow_name* is not registered.
        """
        flow = self._registry.get_flow(flow_name)
        _logger.info("Flow '%s' started | steps=%d", flow_name, len(flow.steps))

        # -- Flow-level input validation ------------------------------------
        if flow.input_schema is not None:
            try:
                flow.input_schema.model_validate(initial_input)
            except ValidationError as exc:
                wrapped = SchemaValidationError(flow_name, -1, str(exc))
                _logger.error(
                    "Flow '%s' input validation failed: %s", flow_name, wrapped
                )
                return ExecutionResult(
                    flow_name=flow_name,
                    success=False,
                    final_output=None,
                    execution_log=[
                        StepRecord(
                            step_index=-1,
                            tool_name=flow_name,
                            inputs=initial_input,
                            error=wrapped,
                            success=False,
                        )
                    ],
                )

        context: dict[str, Any] = dict(initial_input)
        log: list[StepRecord] = []

        for idx, step in enumerate(flow.steps):
            record = self._execute_step(idx, step, context)
            log.append(record)

            if not record.success:
                _logger.error("Flow '%s' aborted at step %d", flow_name, idx)
                return ExecutionResult(
                    flow_name=flow_name,
                    success=False,
                    final_output=None,
                    execution_log=log,
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
            try:
                flow.output_schema.model_validate(context)
            except ValidationError as exc:
                wrapped = SchemaValidationError(
                    flow_name, len(flow.steps), str(exc)
                )
                _logger.error(
                    "Flow '%s' output validation failed: %s", flow_name, wrapped
                )
                return ExecutionResult(
                    flow_name=flow_name,
                    success=False,
                    final_output=None,
                    execution_log=log
                    + [
                        StepRecord(
                            step_index=len(flow.steps),
                            tool_name=flow_name,
                            inputs=context,
                            error=wrapped,
                            success=False,
                        )
                    ],
                )

        _logger.info("Flow '%s' completed successfully", flow_name)
        return ExecutionResult(
            flow_name=flow_name,
            success=True,
            final_output=context,
            execution_log=log,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

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
            A :class:`StepRecord` describing the outcome.
        """
        try:
            tool = self.get_tool(step.tool_name)
        except ToolNotFoundError as exc:
            log_step_error(_logger, step_index, step.tool_name, exc)
            return StepRecord(
                step_index=step_index,
                tool_name=step.tool_name,
                inputs={},
                error=exc,
                success=False,
            )

        try:
            inputs = self._resolve_inputs(step, context, step_index)
        except InputMappingError as exc:
            log_step_error(_logger, step_index, step.tool_name, exc)
            return StepRecord(
                step_index=step_index,
                tool_name=step.tool_name,
                inputs={},
                error=exc,
                success=False,
            )

        log_step_start(_logger, step_index, step.tool_name, inputs)

        try:
            outputs = tool.run(inputs)
        except ValidationError as exc:
            wrapped = SchemaValidationError(step.tool_name, step_index, str(exc))
            log_step_error(_logger, step_index, step.tool_name, wrapped)
            return StepRecord(
                step_index=step_index,
                tool_name=step.tool_name,
                inputs=inputs,
                error=wrapped,
                success=False,
            )
        except Exception as exc:
            wrapped = FlowExecutionError(step.tool_name, step_index, str(exc))
            log_step_error(_logger, step_index, step.tool_name, wrapped)
            return StepRecord(
                step_index=step_index,
                tool_name=step.tool_name,
                inputs=inputs,
                error=wrapped,
                success=False,
            )

        log_step_end(_logger, step_index, step.tool_name, outputs)
        return StepRecord(
            step_index=step_index,
            tool_name=step.tool_name,
            inputs=inputs,
            outputs=outputs,
            success=True,
        )
