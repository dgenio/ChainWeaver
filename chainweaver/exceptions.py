"""Custom exceptions for ChainWeaver."""

from __future__ import annotations


class ChainWeaverError(Exception):
    """Base exception for all ChainWeaver errors."""


class ToolNotFoundError(ChainWeaverError):
    """Raised when a referenced tool is not registered."""

    def __init__(self, tool_name: str) -> None:
        self.tool_name = tool_name
        super().__init__(f"Tool '{tool_name}' is not registered.")


class FlowNotFoundError(ChainWeaverError):
    """Raised when a referenced flow is not registered."""

    def __init__(self, flow_name: str) -> None:
        self.flow_name = flow_name
        super().__init__(f"Flow '{flow_name}' is not registered.")


class FlowAlreadyExistsError(ChainWeaverError):
    """Raised when attempting to register a flow that already exists."""

    def __init__(self, flow_name: str) -> None:
        self.flow_name = flow_name
        super().__init__(f"Flow '{flow_name}' is already registered.")


class SchemaValidationError(ChainWeaverError):
    """Raised when input or output data fails schema validation."""

    def __init__(
        self,
        tool_name: str,
        step_index: int,
        detail: str,
        *,
        context: str = "tool",
    ) -> None:
        self.tool_name = tool_name
        self.step_index = step_index
        self.detail = detail
        self.context = context
        super().__init__(
            f"Schema validation failed for {context} '{tool_name}' at step {step_index}: {detail}"
        )


class InputMappingError(ChainWeaverError):
    """Raised when an input mapping cannot be resolved."""

    def __init__(self, tool_name: str, step_index: int, key: str) -> None:
        self.tool_name = tool_name
        self.step_index = step_index
        self.key = key
        super().__init__(
            f"Input mapping key '{key}' not found for tool '{tool_name}' at step {step_index}."
        )


class FlowExecutionError(ChainWeaverError):
    """Raised when a flow step raises an unexpected runtime error."""

    def __init__(self, tool_name: str, step_index: int, detail: str) -> None:
        self.tool_name = tool_name
        self.step_index = step_index
        self.detail = detail
        super().__init__(f"Execution error in tool '{tool_name}' at step {step_index}: {detail}")


class ToolDefinitionError(ChainWeaverError):
    """Raised when the ``@tool`` decorator cannot build a tool from a function."""

    def __init__(self, function_name: str, detail: str) -> None:
        self.function_name = function_name
        self.detail = detail
        super().__init__(f"Cannot define tool from function '{function_name}': {detail}")
