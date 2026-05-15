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
    """Raised when a referenced flow (and optionally a specific version) is not registered."""

    def __init__(self, flow_name: str, *, version: str | None = None) -> None:
        self.flow_name = flow_name
        self.version = version
        if version is None:
            super().__init__(f"Flow '{flow_name}' is not registered.")
        else:
            super().__init__(f"Flow '{flow_name}' version '{version}' is not registered.")


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


class ToolTimeoutError(ChainWeaverError):
    """Raised when a tool exceeds its configured execution timeout.

    Attributes:
        tool_name: Name of the tool that timed out.
        timeout_seconds: The configured timeout that was exceeded.
    """

    def __init__(self, tool_name: str, timeout_seconds: float) -> None:
        self.tool_name = tool_name
        self.timeout_seconds = timeout_seconds
        super().__init__(f"Tool '{tool_name}' exceeded timeout of {timeout_seconds}s.")


class ToolOutputSizeError(ChainWeaverError):
    """Raised when a tool's output exceeds the maximum allowed size.

    Attributes:
        tool_name: Name of the tool whose output was rejected.
        size: Actual output size in bytes (UTF-8 encoded JSON length).
        max_size: Configured maximum allowed size in bytes.
    """

    def __init__(self, tool_name: str, size: int, max_size: int) -> None:
        self.tool_name = tool_name
        self.size = size
        self.max_size = max_size
        super().__init__(f"Tool '{tool_name}' output size {size} exceeds max {max_size}.")


class DAGDefinitionError(ChainWeaverError):
    """Raised when a :class:`~chainweaver.flow.DAGFlow` definition is invalid.

    Attributes:
        flow_name: Name of the flow that failed validation.
        reason: Machine-readable reason code.  One of ``"cycle"``,
            ``"duplicate_step_id"``, or ``"unknown_dependency"``.
        detail: Human-readable explanation.
    """

    def __init__(
        self,
        flow_name: str,
        reason: str,
        detail: str,
    ) -> None:
        self.flow_name = flow_name
        self.reason = reason
        self.detail = detail
        super().__init__(f"Invalid DAG flow '{flow_name}' ({reason}): {detail}")


class FlowStatusError(ChainWeaverError):
    """Raised when a flow cannot be executed due to its status."""

    def __init__(self, flow_name: str, status: str) -> None:
        self.flow_name = flow_name
        self.status = status
        super().__init__(
            f"Flow '{flow_name}' has status '{status}'. Use force=True to execute anyway."
        )


class InvalidFlowVersionError(ChainWeaverError):
    """Raised when a flow's version string cannot be parsed as a PEP 440 version."""

    def __init__(self, flow_name: str, version: str, detail: str) -> None:
        self.flow_name = flow_name
        self.version = version
        self.detail = detail
        super().__init__(f"Flow '{flow_name}' has invalid version '{version}': {detail}.")


class FlowSerializationError(ChainWeaverError):
    """Raised when a flow cannot be serialized or deserialized.

    Covers malformed YAML/JSON payloads, unknown ``type`` discriminators,
    unresolvable schema/exception class references, and missing required
    fields.

    Attributes:
        detail: Human-readable explanation of what failed.
        source: Optional identifier for the input source (e.g. file path).
    """

    def __init__(self, detail: str, *, source: str | None = None) -> None:
        self.detail = detail
        self.source = source
        if source is None:
            super().__init__(f"Flow serialization failed: {detail}.")
        else:
            super().__init__(f"Flow serialization failed for '{source}': {detail}.")


class CheckpointDriftError(ChainWeaverError):
    """Raised when a resumed flow's snapshot disagrees with current registry state.

    Crash-resume (issue #128) is only safe when the flow definition and
    every tool schema referenced by the snapshot are unchanged.  When the
    registered flow's version or any tool's ``schema_hash`` has rolled
    since the snapshot was written, resuming would silently mix old
    intermediate outputs with new tool behavior — this exception stops
    that before it happens.

    Attributes:
        trace_id: Trace id of the snapshot that could not be safely resumed.
        flow_name: Name of the flow recorded in the snapshot.
        detail: Human-readable explanation of which hash mismatched.
    """

    def __init__(self, trace_id: str, flow_name: str, detail: str) -> None:
        self.trace_id = trace_id
        self.flow_name = flow_name
        self.detail = detail
        super().__init__(f"Cannot resume trace '{trace_id}' for flow '{flow_name}': {detail}.")


class CheckpointerNotConfiguredError(ChainWeaverError):
    """Raised when :meth:`FlowExecutor.resume_flow` is called without a checkpointer.

    Crash-resume is an opt-in feature — the executor needs a
    :class:`~chainweaver.checkpoint.Checkpointer` passed at
    construction time to know where snapshots live.  Callers that
    omit ``checkpointer=`` and then call :meth:`resume_flow` hit this
    error instead of a generic ``ValueError`` so wrapping code can
    distinguish "configuration mistake" from arbitrary value errors.
    """

    def __init__(self) -> None:
        super().__init__(
            "FlowExecutor has no checkpointer configured. "
            "Pass checkpointer=... to FlowExecutor(...) to enable resume_flow."
        )


class CheckpointNotFoundError(ChainWeaverError):
    """Raised when :meth:`FlowExecutor.resume_flow` cannot find a snapshot.

    Attributes:
        trace_id: The trace id that was looked up and missed.
    """

    def __init__(self, trace_id: str) -> None:
        self.trace_id = trace_id
        super().__init__(f"No snapshot found for trace_id '{trace_id}'.")
