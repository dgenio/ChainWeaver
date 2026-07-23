"""Custom exceptions for ChainWeaver."""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from chainweaver.executor import ExecutionResult


# Bumped whenever a ChainWeaverError subclass is defined (including in sibling
# modules, on import).  error_code_registry() reads it to cache its result and
# rebuild only when the live subclass tree actually changes.
_ERROR_CODE_GENERATION = 0


class ChainWeaverError(Exception):
    """Base exception for all ChainWeaver errors.

    Every subclass carries a stable diagnostic ``code`` (issue #390) — e.g.
    ``"CW-E007"``.  Most codes are assigned from the append-only registry at the
    bottom of this module; subclasses that live in sibling modules to avoid
    import cycles (``FlowBuilderError``, ``FuzzConfigError``,
    ``AttestationInputError``, ``FixtureStaleError``) declare their ``code`` in
    place instead.  When adding a new exception, register its code in whichever
    of those two places matches where the class is defined.  Codes are
    searchable in logs, issues, and docs, let coding agents
    map a failure to a documented remediation deterministically, and let
    ``--format json`` consumers branch on a code instead of string-matching
    messages.  The code is exposed as a class attribute (and surfaced in CLI
    error output and on :attr:`~chainweaver.executor.StepRecord.error_code`); it
    is deliberately *not* injected into ``str(exc)`` so existing message
    contracts are preserved.  Each code maps to an anchored section in
    ``docs/reference/error-table.md``.
    """

    #: Stable diagnostic code; overridden per subclass via the registry below.
    code: ClassVar[str] = "CW-E000"

    def __init_subclass__(cls, **kwargs: object) -> None:
        # Bump the generation counter so error_code_registry() knows the live
        # subclass tree has grown and rebuilds its cache (subclasses defined in
        # sibling modules register here on import).
        super().__init_subclass__(**kwargs)
        global _ERROR_CODE_GENERATION
        _ERROR_CODE_GENERATION += 1


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


class OutputMappingError(ChainWeaverError):
    """Raised when a step's ``output_mapping`` references a missing output key.

    The mapping renames/prunes a tool's validated outputs before they merge into
    the execution context (issue #386); this fires when a mapped ``output_key``
    is not among the keys the tool actually produced.
    """

    def __init__(
        self, tool_name: str, step_index: int, output_key: str, available: list[str]
    ) -> None:
        self.tool_name = tool_name
        self.step_index = step_index
        self.output_key = output_key
        self.available = available
        super().__init__(
            f"Output mapping references key '{output_key}' not produced by tool "
            f"'{tool_name}' at step {step_index}. Available output keys: {sorted(available)}."
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


class ContextKeyCollisionError(ChainWeaverError):
    """Raised when a step output collides with an existing context key under the
    ``on_context_collision="error"`` policy (issue #337).

    The accumulated execution context is a flow's data plane.  By default a step
    that emits a key already present in the context (including the initial
    input) overwrites it — silently before #337, at ``WARNING`` since.  A flow
    that sets ``on_context_collision="error"`` opts into hard failure instead:
    rather than letting a reordering or an added step drop earlier data
    unnoticed, the run aborts with this typed error naming the offending step
    and the colliding keys.

    Attributes:
        flow_name: Name of the flow whose context collided.
        step_index: Zero-based index of the step that produced the collision.
        step_name: Display name of the offending step.
        keys: The output keys that collided with existing context keys.
    """

    def __init__(self, flow_name: str, step_index: int, step_name: str, keys: list[str]) -> None:
        self.flow_name = flow_name
        self.step_index = step_index
        self.step_name = step_name
        self.keys = list(keys)
        joined = ", ".join(repr(key) for key in keys)
        super().__init__(
            f"Flow '{flow_name}' step {step_index} ('{step_name}') would overwrite "
            f"existing context key(s) {joined}; on_context_collision='error' aborts "
            f"rather than dropping earlier data."
        )


class AsyncLaneUnsupportedError(ChainWeaverError):
    """Raised when :meth:`FlowExecutor.execute_flow_async` is given a flow that
    uses execution features the async lane does not yet support (issue #332).

    The async lane (issue #80) does not implement conditional branching
    (``branches`` / ``default_next``, #9) or guided decision callbacks
    (``decision_candidates``, #102).  Rather than executing such a flow with
    those directives **silently dropped** — which would yield a different
    result than the synchronous :meth:`execute_flow` and undermine the
    determinism promise — the executor fails fast, before the first step
    runs, listing every unsupported construct it found.  Route the flow
    through :meth:`execute_flow` until async parity lands.  Composed
    sub-flow steps (``flow_name``, #75) are supported on the async lane
    since #388 and no longer raise this error.

    Attributes:
        flow_name: Name of the flow that could not run on the async lane.
        unsupported: Human-readable descriptions of each unsupported construct
            found, one per offending step/feature.
    """

    def __init__(self, flow_name: str, unsupported: list[str]) -> None:
        self.flow_name = flow_name
        self.unsupported = list(unsupported)
        joined = "; ".join(unsupported)
        super().__init__(
            f"Flow '{flow_name}' uses features unsupported by execute_flow_async: "
            f"{joined}. Run it via the synchronous execute_flow until the async "
            f"lane reaches parity."
        )


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


class CheckpointVersionError(ChainWeaverError):
    """Raised when a snapshot's format version is incompatible with this library (issue #395).

    Crash-resume (issue #128) persists :class:`~chainweaver.checkpoint.ExecutionSnapshot`
    JSON designed to outlive the process — the very scenario where a library
    upgrade between write and resume is most likely.  Each snapshot carries a
    ``snapshot_version`` stamp; :meth:`~chainweaver.executor.FlowExecutor.resume_flow`
    accepts a snapshot whose MAJOR component matches the version this library
    writes and raises this typed error for an incompatible MAJOR, rather than
    surfacing an opaque Pydantic validation error mid-recovery.  Remediation:
    re-run the flow from the start, or resume with the matching library version.

    Attributes:
        trace_id: Trace id of the snapshot that could not be safely resumed.
        flow_name: Name of the flow recorded in the snapshot.
        snapshot_version: The ``snapshot_version`` read from the snapshot.
        expected_version: The snapshot version this library writes.
    """

    def __init__(
        self,
        trace_id: str,
        flow_name: str,
        snapshot_version: str,
        expected_version: str,
    ) -> None:
        self.trace_id = trace_id
        self.flow_name = flow_name
        self.snapshot_version = snapshot_version
        self.expected_version = expected_version
        super().__init__(
            f"Cannot resume trace '{trace_id}' for flow '{flow_name}': snapshot_version "
            f"'{snapshot_version}' is incompatible with this ChainWeaver "
            f"(writes '{expected_version}'). Re-run from the start or resume with the "
            f"matching library version."
        )


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


class FlowAuthenticationError(MCPError):
    """Raised when a FlowServer authenticator rejects a caller (issue #362).

    :class:`~chainweaver.mcp.FlowServer` exposes an optional ``authenticator``
    hook that runs **before** a flow is dispatched.  Network transports
    (SSE / streamable-HTTP) turn governed flows into a wire service where the
    host owns the authentication story; the hook resolves a
    :class:`~chainweaver.mcp.security.CallerIdentity` from the request (e.g. a
    bearer token in the HTTP headers).  When the hook returns ``None`` or
    raises, the call is refused with this typed error before any step runs.
    The message carries only a safe, non-leaky reason — operational ``detail``
    is sent to the audit hook and logs, not back to the MCP client.

    Attributes:
        flow_name: Name of the flow whose invocation was refused.
        reason_code: Stable, client-safe reason code (e.g. ``"unauthenticated"``).
    """

    def __init__(self, flow_name: str, reason_code: str = "unauthenticated") -> None:
        self.flow_name = flow_name
        self.reason_code = reason_code
        super().__init__(f"Authentication failed for flow '{flow_name}': {reason_code}.")


class RateLimitExceededError(MCPError):
    """Raised when a FlowServer rate limiter rejects a caller (issue #362).

    :class:`~chainweaver.mcp.FlowServer` exposes an optional ``rate_limiter``
    hook (see :class:`~chainweaver.mcp.security.RateLimiter`) that runs after
    authentication and before authorization.  When the limiter declines the
    call, the dispatcher refuses it with this typed error rather than executing
    the flow, providing basic abuse protection for network-exposed flows.

    Attributes:
        flow_name: Name of the flow whose invocation was throttled.
        reason_code: Stable, client-safe reason code (e.g. ``"rate_limited"``).
    """

    def __init__(self, flow_name: str, reason_code: str = "rate_limited") -> None:
        self.flow_name = flow_name
        self.reason_code = reason_code
        super().__init__(f"Rate limit exceeded for flow '{flow_name}': {reason_code}.")


class FlowAuthorizationError(MCPError):
    """Raised when a FlowServer authorization callback denies a call (issue #443).

    :class:`~chainweaver.mcp.FlowServer` exposes an optional ``authorizer`` hook
    that makes a per-call allow/deny decision *before* a flow is dispatched,
    receiving the flow name, a redacted input summary, the caller identity, and
    a request id (see :class:`~chainweaver.mcp.security.AuthorizationContext`).
    A deny decision aborts the call with this typed error carrying only the
    client-safe ``reason_code``; any operational ``detail`` is routed to the
    audit hook and logs, never back to the remote agent.

    Attributes:
        flow_name: Name of the flow whose invocation was denied.
        reason_code: Stable, client-safe reason code (e.g. ``"forbidden"``).
    """

    def __init__(self, flow_name: str, reason_code: str = "forbidden") -> None:
        self.flow_name = flow_name
        self.reason_code = reason_code
        super().__init__(f"Authorization denied for flow '{flow_name}': {reason_code}.")


class ApprovalDeniedError(ChainWeaverError):
    """Raised when an :class:`~chainweaver.approvals.ApprovalCallback` denies a step (issue #356).

    Execution-time enforcement of :class:`~chainweaver.contracts.ToolSafetyContract`
    is opt-in: when a step's effective contract has ``requires_approval=True`` and
    a callback is registered on the executor, the callback is asked to approve the
    step *before* the tool function runs.  A ``DENY`` decision (or a callback that
    raises, or a missing callback under ``strict_safety=True``) aborts the step
    with this typed error rather than running the side-effecting tool unattended.

    Attributes:
        tool_name: Name of the tool whose invocation was denied.
        step_index: Zero-based position of the step inside the flow.
        detail: Human-readable description of why approval was denied.
    """

    def __init__(self, tool_name: str, step_index: int, detail: str) -> None:
        self.tool_name = tool_name
        self.step_index = step_index
        self.detail = detail
        # Normalise so the message ends with exactly one period (repo convention,
        # AGENTS.md §6) regardless of whether *detail* already carried one.
        normalised = detail.rstrip(".")
        super().__init__(
            f"Approval denied for tool '{tool_name}' at step {step_index}: {normalised}."
        )


class SafetyCeilingError(ChainWeaverError):
    """Raised when a step's side-effect level exceeds the executor ceiling (issue #356).

    When :class:`~chainweaver.executor.FlowExecutor` is configured with
    ``max_side_effect_level=...``, a step whose effective
    :class:`~chainweaver.contracts.ToolSafetyContract` declares a
    :class:`~chainweaver.contracts.SideEffectLevel` above that ceiling is refused
    before it runs, rather than silently executing a higher-risk operation than
    the host opted into.

    Attributes:
        tool_name: Name of the tool that exceeded the ceiling.
        step_index: Zero-based position of the step inside the flow.
        level: The step's declared side-effect level (value string).
        ceiling: The configured maximum side-effect level (value string).
    """

    def __init__(self, tool_name: str, step_index: int, level: str, ceiling: str) -> None:
        self.tool_name = tool_name
        self.step_index = step_index
        self.level = level
        self.ceiling = ceiling
        super().__init__(
            f"Tool '{tool_name}' at step {step_index} has side-effect level "
            f"'{level}' which exceeds the configured ceiling '{ceiling}'."
        )


class GuardrailViolationError(ChainWeaverError):
    """Raised when a :class:`~chainweaver.guardrails.GuardrailCallback` blocks a step (issue #317).

    Guardrails are an opt-in content-safety seam: when a
    ``guardrail_callback`` is registered on the executor, it is consulted
    *before* each tool runs (the ``"input"`` stage) so a host can block prompt
    injection, disallowed inputs, or policy violations. A callback that rejects
    the step (by raising) aborts it with this typed error and a failed
    ``StepRecord`` — the same abort path a denied approval or a tool failure
    takes — rather than running the tool on unsafe input.

    Attributes:
        tool_name: Name of the tool whose invocation was blocked.
        step_index: Zero-based position of the step inside the flow.
        stage: The guardrail stage that blocked the step (``"input"``).
        detail: Human-readable description of why the guardrail blocked the step.
    """

    def __init__(self, tool_name: str, step_index: int, stage: str, detail: str) -> None:
        self.tool_name = tool_name
        self.step_index = step_index
        self.stage = stage
        self.detail = detail
        normalised = detail.rstrip(".")
        super().__init__(
            f"Guardrail ({stage}) blocked tool '{tool_name}' at step {step_index}: {normalised}."
        )


class MCPMetadataError(MCPError):
    """Raised when server-provided MCP tool metadata violates the metadata policy (issue #359).

    Tool names and descriptions wrapped from an MCP server are untrusted input:
    they become ChainWeaver :attr:`Tool.description` / :attr:`Tool.name` values and
    can be re-exported to LLM clients or rendered into proposer prompts.  When a
    server advertises a tool name that fails the configured validation pattern (and
    the policy is not in sanitising mode), :class:`MCPToolAdapter` refuses it with
    this error instead of adopting a look-alike or control-character-laden name.

    Attributes:
        tool_name: The offending server-provided tool name (server-prefixed when a
            prefix was supplied).
        detail: Human-readable explanation of which rule was violated.
    """

    def __init__(self, tool_name: str, detail: str) -> None:
        self.tool_name = tool_name
        self.detail = detail
        super().__init__(f"MCP tool metadata for '{tool_name}' rejected: {detail}.")


class MCPSchemaDriftError(MCPError):
    """Raised when a discovered MCP tool schema no longer matches its pin (issue #358).

    Tools wrapped from remote MCP servers get the same schema-drift discipline as
    locally registered tools: :class:`MCPToolAdapter` fingerprints each tool's raw
    JSON Schema at discovery and, when a pin is supplied, verifies it.  Under the
    ``on_drift="error"`` policy a mismatch raises this exception naming the tool and
    both fingerprints, rather than transparently rebuilding models around a silently
    changed remote schema.

    Attributes:
        tool_name: Name of the MCP tool whose schema drifted (server-side name).
        expected: The pinned fingerprint.
        actual: The fingerprint computed from the freshly discovered schema.
    """

    def __init__(self, tool_name: str, expected: str, actual: str) -> None:
        self.tool_name = tool_name
        self.expected = expected
        self.actual = actual
        super().__init__(
            f"MCP tool '{tool_name}' schema drifted: pinned '{expected}', discovered '{actual}'."
        )


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


class DecisionTimeoutError(ChainWeaverError):
    """Raised when a decision callback overruns its timeout (issue #370).

    Only raised when a :class:`~chainweaver.decisions.DecisionPolicy` with
    ``on_timeout="error"`` is active and the callback's ``decide`` call
    exceeds :attr:`~chainweaver.decisions.DecisionPolicy.timeout_s`.  Under
    ``on_timeout="default"`` the executor falls back to the step's static
    ``tool_name`` instead of raising.

    The orphaned callback thread cannot be force-killed and may complete in
    the background; its late return is discarded.

    Attributes:
        tool_name: The step's static ``tool_name`` at the decision point.
        step_index: Zero-based position of the step inside the flow.
        timeout_s: The configured per-decision timeout, in seconds.
    """

    def __init__(self, tool_name: str, step_index: int, timeout_s: float) -> None:
        self.tool_name = tool_name
        self.step_index = step_index
        self.timeout_s = timeout_s
        super().__init__(
            f"Decision callback for step {step_index} (default tool '{tool_name}') "
            f"exceeded the {timeout_s}s timeout."
        )


class DecisionBudgetExceededError(ChainWeaverError):
    """Raised when a flow exceeds its decision budget (issue #370).

    Raised when a :class:`~chainweaver.decisions.DecisionPolicy` sets
    ``max_decisions_per_flow`` and the running flow attempts more decision
    callbacks than that ceiling allows.  Unlike a callback failure (which
    aborts a single step), exceeding the budget aborts the whole flow run.

    Attributes:
        flow_name: Name of the flow that exhausted its decision budget.
        budget: The configured ``max_decisions_per_flow`` ceiling.
    """

    def __init__(self, flow_name: str, budget: int) -> None:
        self.flow_name = flow_name
        self.budget = budget
        super().__init__(
            f"Flow '{flow_name}' exceeded its decision budget of {budget} "
            f"decision callback(s) per execution."
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


class OfflineLLMError(ChainWeaverError):
    """Raised when an offline, build-time LLM-assisted proposer cannot use a completion.

    Shared by :mod:`chainweaver.compiler_llm` (issue #28) and
    :mod:`chainweaver.optimizer` (issue #100).  These modules run the LLM
    *offline, at build time* — never inside :mod:`chainweaver.executor` — and
    turn its completion into reviewable proposals.  This error surfaces a
    clear, typed failure when the completion is blank, is not valid YAML, is
    structurally malformed, or references tools/flows that do not exist —
    rather than leaking a raw ``yaml.YAMLError`` or ``KeyError`` to the
    caller.  It is also raised when ``pyyaml`` (the ``chainweaver[yaml]``
    extra) is needed to parse a completion but is not installed.

    Attributes:
        detail: Human-readable explanation of what failed.
    """

    def __init__(self, detail: str) -> None:
        self.detail = detail
        super().__init__(detail)


class PromptBudgetExceededError(OfflineLLMError):
    """Raised when an offline proposer prompt exceeds its configured token budget (issue #367).

    The offline proposers render every registered tool into the prompt
    unconditionally by default.  When a caller supplies a
    :class:`~chainweaver.proposals.PromptBudget` with ``overflow="error"`` (the
    default), the assembled prompt is estimated *before* any LLM call and this
    typed error is raised when the estimate exceeds ``max_tokens`` — failing
    early and clearly instead of paying for a call the provider would reject.
    It subclasses :class:`OfflineLLMError` so existing ``except OfflineLLMError``
    handlers keep working.

    Attributes:
        estimated_tokens: The estimated token count of the assembled prompt.
        max_tokens: The configured budget that was exceeded.
    """

    def __init__(self, estimated_tokens: int, max_tokens: int) -> None:
        self.estimated_tokens = estimated_tokens
        self.max_tokens = max_tokens
        super().__init__(
            f"Estimated prompt size {estimated_tokens} tokens exceeds the configured "
            f"budget of {max_tokens} tokens. Raise PromptBudget.max_tokens, or set "
            "overflow='truncate'/'batch'/'select' to fit the catalogue."
        )


class LLMProviderError(ChainWeaverError):
    """Raised when an optional provider adapter cannot complete an LLM call (issue #368).

    The shipped ``chainweaver.integrations.llm_*`` adapters wrap a provider SDK
    behind the :data:`~chainweaver._offline_llm.LLMFn` seam, adding retry,
    timeout, and usage accounting.  When a call fails after exhausting retries,
    times out, or the provider returns an unusable response, the adapter raises
    this typed error rather than leaking a provider-specific exception to the
    proposer.

    Attributes:
        provider: The provider key (e.g. ``"anthropic"``, ``"openai"``).
        detail: Human-readable explanation of what failed.
    """

    def __init__(self, provider: str, detail: str) -> None:
        self.provider = provider
        self.detail = detail
        super().__init__(f"LLM provider '{provider}' call failed: {detail}.")


class LLMBudgetExceededError(LLMProviderError):
    """Raised when a provider adapter would exceed a configured spend ceiling (issue #368).

    Adapters accept ``max_calls`` and ``max_cost_usd`` ceilings.  When the next
    call would push an adapter instance past one of those ceilings, it aborts
    with this error *before* making the call, so a runaway proposer loop cannot
    quietly burn budget.

    Attributes:
        provider: The provider key whose ceiling was hit.
        limit: Human-readable description of the ceiling that would be exceeded.
    """

    def __init__(self, provider: str, limit: str) -> None:
        self.provider = provider
        self.limit = limit
        # Skip LLMProviderError.__init__ to compose a budget-specific message.
        ChainWeaverError.__init__(
            self, f"LLM provider '{provider}' budget ceiling reached: {limit}."
        )
        self.detail = limit


class AgentTraceImportError(ChainWeaverError):
    """Raised when a coding-agent tool-use trace cannot be imported (issue #254).

    :func:`~chainweaver.traces.load_agent_trace` reads vendor-neutral JSONL
    logs of agent tool/model calls.  Malformed JSON, a non-object line, a
    record with an unknown ``event`` kind, or a ``tool_call`` missing its
    ``tool`` name raises this exception with a precise ``detail`` (including
    the offending line number when available) rather than leaking a raw
    ``json.JSONDecodeError`` / ``KeyError`` to the caller.

    Attributes:
        detail: Human-readable explanation of what failed.
        source: Optional identifier for the input source (e.g. file path).
        line: 1-based line number of the offending record, when applicable.
    """

    def __init__(self, detail: str, *, source: str | None = None, line: int | None = None) -> None:
        self.detail = detail
        self.source = source
        self.line = line
        location = source if source is not None else "trace"
        if line is not None:
            super().__init__(f"Cannot import agent trace '{location}' (line {line}): {detail}.")
        else:
            super().__init__(f"Cannot import agent trace '{location}': {detail}.")


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


class SchemaRefPolicyError(ChainWeaverError):
    """Raised when a schema/exception class ref is rejected by the active policy.

    Schema refs (``Flow.input_schema_ref`` etc.) and retry-error refs resolve a
    ``"module:qualname"`` string by importing the module half (issue #345).
    Importing a module runs its top-level code, so deployments that load flow
    files from semi-trusted sources can install an allowlist policy via
    :func:`chainweaver.flow.set_schema_ref_policy` /
    :func:`chainweaver.flow.schema_ref_policy`.  When a ref's module path fails
    that policy this is raised **before** any import is attempted.

    Attributes:
        module_path: The module half of the rejected ref.
        ref: The full ``"module:qualname"`` ref that was rejected.
        detail: Human-readable explanation of why the ref was rejected.
    """

    def __init__(self, module_path: str, ref: str, detail: str | None = None) -> None:
        self.module_path = module_path
        self.ref = ref
        self.detail = detail or (
            f"Module '{module_path}' is not permitted by the active schema-ref policy"
        )
        super().__init__(f"Class ref '{ref}' rejected: {self.detail}.")


# ---------------------------------------------------------------------------
# Stable diagnostic codes (issue #390)
# ---------------------------------------------------------------------------
#
# Append-only registry mapping each exception class to its stable ``CW-Exxx``
# code.  **Codes are forever**: once released, never renumber or reuse one — add
# new codes at the end with the next free number.  A consistency test
# (tests/test_error_codes.py) enforces uniqueness, that every public exception
# has a code, and that each code is documented in docs/reference/error-table.md.
#
# Exceptions defined in sibling modules (FlowBuilderError, FuzzConfigError,
# AttestationInputError, FixtureStaleError) declare their own ``code`` in place
# to avoid import cycles; they are validated by the same consistency test.
_ERROR_CODES: dict[type[ChainWeaverError], str] = {
    ChainWeaverError: "CW-E000",
    ToolNotFoundError: "CW-E001",
    FlowNotFoundError: "CW-E002",
    FlowAlreadyExistsError: "CW-E003",
    SchemaValidationError: "CW-E004",
    InputMappingError: "CW-E005",
    FlowExecutionError: "CW-E006",
    ToolDefinitionError: "CW-E007",
    ToolTimeoutError: "CW-E008",
    ToolOutputSizeError: "CW-E009",
    DAGDefinitionError: "CW-E010",
    FlowStatusError: "CW-E011",
    FlowCancelledError: "CW-E012",
    ContextKeyCollisionError: "CW-E013",
    AsyncLaneUnsupportedError: "CW-E014",
    FlowCompositionError: "CW-E015",
    InvalidFlowVersionError: "CW-E016",
    FlowSerializationError: "CW-E017",
    CheckpointDriftError: "CW-E018",
    CheckpointerNotConfiguredError: "CW-E019",
    CheckpointNotFoundError: "CW-E020",
    CheckpointVersionError: "CW-E021",
    PluginDiscoveryError: "CW-E022",
    ContribError: "CW-E023",
    MCPError: "CW-E024",
    MCPSchemaConversionError: "CW-E025",
    MCPToolInvocationError: "CW-E026",
    MCPMetadataError: "CW-E027",
    MCPSchemaDriftError: "CW-E028",
    ApprovalDeniedError: "CW-E029",
    SafetyCeilingError: "CW-E030",
    DecisionCallbackError: "CW-E031",
    KernelInvocationError: "CW-E032",
    CostProfileError: "CW-E033",
    OfflineLLMError: "CW-E034",
    AgentTraceImportError: "CW-E035",
    PredicateSyntaxError: "CW-E036",
    OutputMappingError: "CW-E041",
    PromptBudgetExceededError: "CW-E042",
    LLMProviderError: "CW-E043",
    LLMBudgetExceededError: "CW-E044",
    FlowAuthenticationError: "CW-E045",
    RateLimitExceededError: "CW-E046",
    FlowAuthorizationError: "CW-E047",
    DecisionTimeoutError: "CW-E049",
    DecisionBudgetExceededError: "CW-E050",
    SchemaRefPolicyError: "CW-E051",
    GuardrailViolationError: "CW-E052",
}

for _exc_cls, _exc_code in _ERROR_CODES.items():
    _exc_cls.code = _exc_code
del _exc_cls, _exc_code


def _iter_error_classes(
    root: type[ChainWeaverError] = ChainWeaverError,
) -> list[type[ChainWeaverError]]:
    """Return *root* and every (transitive) :class:`ChainWeaverError` subclass.

    Walks the live subclass tree so exceptions defined in sibling modules are
    included once those modules have been imported.
    """
    seen: list[type[ChainWeaverError]] = [root]
    for sub in root.__subclasses__():
        seen.extend(_iter_error_classes(sub))
    return seen


_CODE_MAP_CACHE: dict[str, str] = {}
_CODE_MAP_GENERATION = -1


def _error_code_map() -> dict[str, str]:
    """Return the cached ``{class name: code}`` map, shared across callers.

    The map is rebuilt only when the live :class:`ChainWeaverError` subclass
    tree has grown since the last build (tracked by ``_ERROR_CODE_GENERATION``).
    Failing :class:`~chainweaver.executor.StepRecord`s look up their code on
    every validation, so caching here avoids re-walking the subclass tree per
    record while still picking up exceptions defined in sibling modules once
    they are imported.
    """
    global _CODE_MAP_GENERATION
    if _CODE_MAP_GENERATION != _ERROR_CODE_GENERATION:
        _CODE_MAP_CACHE.clear()
        _CODE_MAP_CACHE.update((cls.__name__, cls.code) for cls in _iter_error_classes())
        _CODE_MAP_GENERATION = _ERROR_CODE_GENERATION
    return _CODE_MAP_CACHE


def error_code_registry() -> dict[str, str]:
    """Return a ``{exception class name: code}`` map over all loaded error types."""
    return dict(_error_code_map())


def error_code_for(name: str | None) -> str | None:
    """Return the stable code for an exception class *name*, or ``None``.

    *name* is an exception's ``__class__.__name__`` (as stored in
    :attr:`~chainweaver.executor.StepRecord.error_type`).  Returns ``None`` for
    foreign (non-:class:`ChainWeaverError`) exception names so trace records
    from arbitrary tool failures simply carry no code.
    """
    if name is None:
        return None
    return _error_code_map().get(name)
