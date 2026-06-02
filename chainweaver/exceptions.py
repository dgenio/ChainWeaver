"""Custom exceptions for ChainWeaver."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from chainweaver.executor import ExecutionResult


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


class FlowCancelledError(ChainWeaverError):
    """Raised when a flow is cancelled at a step boundary (issue #142).

    Cooperative cancellation is requested by a wall-clock ``deadline`` and/or
    a :class:`~chainweaver.cancellation.CancellationToken` passed to
    :meth:`~chainweaver.executor.FlowExecutor.execute_flow`.  The executor
    checks both **between** steps (and between DAG levels) — never inside a
    tool invocation — so the hard executor invariants are preserved.

    The error is raised *after* the partial trace has been recorded, so the
    :attr:`result` carries every step that completed before the cancellation
    point.  When both the deadline expired and the token was cancelled, the
    message names both reasons.

    Attributes:
        flow_name: Name of the flow that was cancelled.
        step_index: Zero-based index of the step that *would* have run next
            (the boundary at which the cancellation was observed).  For DAG
            flows this is the number of step records completed so far.
        result: The partial :class:`~chainweaver.executor.ExecutionResult`
            populated up to (but excluding) ``step_index``.
        deadline_exceeded: ``True`` when a wall-clock deadline had passed.
        token_cancelled: ``True`` when the cancellation token was set.
    """

    def __init__(
        self,
        flow_name: str,
        step_index: int,
        *,
        result: ExecutionResult,
        deadline_exceeded: bool = False,
        token_cancelled: bool = False,
    ) -> None:
        self.flow_name = flow_name
        self.step_index = step_index
        self.result = result
        self.deadline_exceeded = deadline_exceeded
        self.token_cancelled = token_cancelled
        reasons = []
        if deadline_exceeded:
            reasons.append("wall-clock deadline exceeded")
        if token_cancelled:
            reasons.append("cancellation requested")
        reason = " and ".join(reasons) if reasons else "cancellation requested"
        super().__init__(f"Flow '{flow_name}' cancelled before step {step_index} ({reason}).")


class FlowCompositionError(ChainWeaverError):
    """Raised when a composed flow's sub-flow references are invalid (issue #75).

    Flow composition lets a :class:`~chainweaver.flow.FlowStep` reference a
    registered sub-flow by ``flow_name`` instead of a tool.  Before executing,
    the executor walks the composition graph and rejects:

    * **cycles** — e.g. ``A`` references ``B`` which references ``A``;
    * **excessive nesting** — chains deeper than the executor's configured
      ``max_composition_depth``;
    * **dangling references** — a ``flow_name`` that is not registered.

    Attributes:
        flow_name: Name of the flow whose composition is invalid.
        reason: Machine-readable reason code — one of ``"cycle"``,
            ``"max_depth_exceeded"``, or ``"unknown_flow"``.
        detail: Human-readable explanation (includes the offending chain).
    """

    def __init__(self, flow_name: str, reason: str, detail: str) -> None:
        self.flow_name = flow_name
        self.reason = reason
        self.detail = detail
        super().__init__(f"Invalid flow composition for '{flow_name}' ({reason}): {detail}")


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


class PluginDiscoveryError(ChainWeaverError):
    """Raised when an entry-point plugin loader fails irrecoverably.

    Plugin discovery (issue #130) is *tolerant* by default: a misbehaving
    third-party plugin emits a warning and is skipped so other plugins
    continue to load.  This exception exists for callers that opt into
    strict mode (``discover_tools(strict=True)`` / ``discover_flows(strict=True)``)
    and want bad plugins to abort discovery instead.

    Attributes:
        entry_point: Fully-qualified entry-point name (``"<dist>:<name>"``)
            that failed.
        detail: Human-readable explanation of what went wrong.
    """

    def __init__(self, entry_point: str, detail: str) -> None:
        self.entry_point = entry_point
        self.detail = detail
        super().__init__(f"Plugin discovery failed for entry point '{entry_point}': {detail}.")


class ContribError(ChainWeaverError):
    """Raised by tools in :mod:`chainweaver.contrib.tools` on contract violations.

    Used for first-party contrib tools (issue #145) to surface
    deterministic failures — missing JSON-pointer keys, predicate
    sub-flow producing the wrong shape, assertion mismatches — without
    falling back to bare ``ValueError`` / ``KeyError`` that would not
    inherit from :class:`ChainWeaverError`.

    Attributes:
        tool_name: Name of the contrib tool that failed.
        detail: Human-readable explanation.
    """

    def __init__(self, tool_name: str, detail: str) -> None:
        self.tool_name = tool_name
        self.detail = detail
        super().__init__(f"Contrib tool '{tool_name}' failed: {detail}.")


class MCPError(ChainWeaverError):
    """Base class for errors raised by the ``chainweaver.mcp`` package
    (issues #70, #72, #150).

    All MCP-adapter / MCP-server failures inherit from this class so
    callers can catch the whole family with a single ``except MCPError``.
    """


class MCPSchemaConversionError(MCPError):
    """Raised when an MCP tool's JSON Schema cannot be projected to Pydantic.

    Attributes:
        tool_name: Name of the MCP tool whose schema could not be converted.
        detail: Human-readable explanation of which JSON Schema construct
            tripped the converter.
    """

    def __init__(self, tool_name: str, detail: str) -> None:
        self.tool_name = tool_name
        self.detail = detail
        super().__init__(f"Failed to convert JSON Schema for MCP tool '{tool_name}': {detail}.")


class MCPToolInvocationError(MCPError):
    """Raised when an MCP tool invocation returns ``isError=True``
    or the SDK call itself raises.

    Attributes:
        tool_name: Name of the MCP tool that failed (server-prefixed).
        detail: Human-readable explanation of the failure, including any
            ``content`` text returned by the server when available.
    """

    def __init__(self, tool_name: str, detail: str) -> None:
        self.tool_name = tool_name
        self.detail = detail
        super().__init__(f"MCP tool '{tool_name}' invocation failed: {detail}.")


class DecisionCallbackError(ChainWeaverError):
    """Raised when a :class:`~chainweaver.decisions.DecisionCallback` fails (issue #102).

    Wraps both failure modes of the callback path: the callback raised, or
    it returned a tool name outside the step's ``decision_candidates``
    list.  The original exception (if any) is preserved on the
    ``__cause__`` chain for debugging.

    Attributes:
        tool_name: Name of the step's static ``tool_name`` at the
            decision point.
        step_index: Zero-based position of the step inside the flow.
        detail: Human-readable description of the failure.
    """

    def __init__(self, tool_name: str, step_index: int, detail: str) -> None:
        self.tool_name = tool_name
        self.step_index = step_index
        self.detail = detail
        super().__init__(
            f"Decision callback for step {step_index} (default tool '{tool_name}') failed: "
            f"{detail}"
        )


class KernelInvocationError(ChainWeaverError):
    """Raised when a :class:`~chainweaver.integrations.agent_kernel.KernelBackedExecutor`
    cannot dispatch a capability step (issue #89).

    Attributes:
        capability_id: The capability identifier the executor tried to invoke.
        step_index: Zero-based position of the step inside the flow.
        detail: Human-readable description of the failure.
    """

    def __init__(self, capability_id: str, step_index: int, detail: str) -> None:
        self.capability_id = capability_id
        self.step_index = step_index
        self.detail = detail
        super().__init__(
            f"Kernel invocation for capability '{capability_id}' at step {step_index} "
            f"failed: {detail}"
        )


class CostProfileError(ChainWeaverError):
    """Raised when a cost estimate is requested for an unknown provider/model (issue #156).

    :func:`~chainweaver.cost.lookup_price` and
    :meth:`~chainweaver.cost.CostProfile.from_provider` consult the maintained
    :data:`~chainweaver.cost.PROVIDER_PRICES` snapshot table.  A
    ``(provider, model)`` pair that is not present in the table raises this
    exception rather than silently returning a zero or guessed price.

    Attributes:
        provider: The provider key that was looked up (e.g. ``"anthropic"``).
        model: The model key that was looked up (e.g. ``"claude-opus-4-7"``).
        detail: Human-readable explanation, including the known providers.
    """

    def __init__(self, provider: str, model: str, detail: str) -> None:
        self.provider = provider
        self.model = model
        self.detail = detail
        super().__init__(
            f"No maintained price for provider '{provider}' model '{model}': {detail}."
        )


class PredicateSyntaxError(ChainWeaverError):
    """Raised when a conditional-branch predicate cannot be parsed or evaluated.

    Conditional branches (issue #9) use a restricted boolean grammar that
    :func:`~chainweaver.contracts.evaluate_predicate` walks with :mod:`ast`
    — never :func:`eval`.  Any syntax error, unsupported node, or
    unresolved name raises this exception with a precise detail so the
    operator can fix the flow definition.

    Attributes:
        predicate: The offending predicate string.
        detail: Human-readable explanation of what failed.
    """

    def __init__(self, predicate: str, detail: str) -> None:
        self.predicate = predicate
        self.detail = detail
        super().__init__(f"Invalid predicate '{predicate}': {detail}")
