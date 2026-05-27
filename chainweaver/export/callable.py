"""Plain ``Callable[[dict], dict]`` export adapters (issue #25).

The simplest and most general export shape: a Python callable that
takes a single ``dict`` and returns a single ``dict``.  Suitable for
wrapping in any framework — LangChain ``BaseTool._run``, FastAPI route
handlers, Click commands, you name it.

Inputs are validated against the derived input schema before the flow
runs.  Outputs are returned as the validated ``ExecutionResult.final_output``
mapping when execution succeeds; failures raise
:class:`~chainweaver.exceptions.FlowExecutionError` carrying the first
failed step's details so the caller can diagnose without inspecting
the full execution log.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from chainweaver.exceptions import FlowExecutionError
from chainweaver.export._schema import derive_flow_input_schema

if TYPE_CHECKING:  # pragma: no cover — type-only references
    from chainweaver.executor import FlowExecutor
    from chainweaver.flow import DAGFlow, Flow
    from chainweaver.tools import Tool


def flow_to_callable(
    flow: Flow | DAGFlow,
    executor: FlowExecutor,
    *,
    input_schema: type[BaseModel] | None = None,
    name: str | None = None,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Return a ``dict → dict`` callable that runs *flow* through *executor*.

    Args:
        flow: The flow to wrap.  Must already be registered on
            ``executor``'s registry — the returned callable re-resolves
            it by name on every invocation, so the latest registered
            *implementation* runs.  The input schema, however, is derived
            once at wrap time (see ``input_schema`` below): if the flow is
            later re-registered with a different input schema, the callable
            keeps validating against the schema captured here.
        executor: Executor used to dispatch the flow.  Captured by
            reference; later changes to its registry are visible
            through the returned callable.
        input_schema: Override for the derived input schema.  When
            ``None`` the schema is derived in the same way as
            :func:`chainweaver.export.openai.flow_to_openai_function`.
        name: Optional ``__name__`` for the returned callable.  Defaults
            to ``flow.name`` — useful when consumers introspect the
            callable's identity (e.g., for logging).

    Returns:
        A callable that validates the input dict against the derived
        schema, dispatches the flow, and returns the final output dict.

    Raises:
        ToolDefinitionError: When the input schema cannot be derived.
            Raised eagerly at wrapping time, not lazily at first call,
            so misconfigurations surface immediately.
    """
    resolved_input = (
        input_schema if input_schema is not None else derive_flow_input_schema(flow, executor)
    )
    callable_name = name if name is not None else flow.name
    flow_name = flow.name

    def _call(raw_inputs: dict[str, Any]) -> dict[str, Any]:
        validated = resolved_input.model_validate(raw_inputs)
        result = executor.execute_flow(flow_name, validated.model_dump())
        if not result.success:
            failed = next((r for r in result.execution_log if not r.success), None)
            if failed is None:
                detail = "Flow execution failed without recording a failing step."
                step_index = -1
                tool_name = flow_name
            else:
                detail = failed.error_message or failed.error_type or "Unknown error."
                step_index = failed.step_index
                tool_name = failed.tool_name
            raise FlowExecutionError(tool_name=tool_name, step_index=step_index, detail=detail)
        if result.final_output is None:
            raise FlowExecutionError(
                tool_name=flow_name,
                step_index=len(flow.steps),
                detail="Flow reported success but produced no final output.",
            )
        return result.final_output

    _call.__name__ = callable_name
    _call.__qualname__ = callable_name
    _call.__doc__ = flow.description or f"Run the '{flow_name}' flow."
    return _call


def tool_to_callable(tool: Tool) -> Callable[[dict[str, Any]], dict[str, Any]]:
    """Return a ``dict → dict`` callable that runs *tool* with schema validation.

    The returned callable delegates to :meth:`Tool.run`, so it observes
    the tool's ``timeout_seconds`` / ``max_output_size`` guardrails and
    raises the same exceptions
    (:class:`~chainweaver.exceptions.ToolTimeoutError`,
    :class:`~chainweaver.exceptions.ToolOutputSizeError`,
    :class:`pydantic.ValidationError`) as direct ``tool.run(...)`` calls.
    """

    def _call(raw_inputs: dict[str, Any]) -> dict[str, Any]:
        return tool.run(raw_inputs)

    _call.__name__ = tool.name
    _call.__qualname__ = tool.name
    _call.__doc__ = tool.description or f"Run the '{tool.name}' tool."
    return _call
