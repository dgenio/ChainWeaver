"""Tool abstraction for ChainWeaver.

A :class:`Tool` wraps a plain Python callable together with Pydantic models
that describe its input and output contract.  Tools are the atomic units of
work inside a :class:`~chainweaver.flow.Flow`.

Two optional guardrails (issue #43) protect agent-composed flows from
misbehaving tools:

- ``timeout_seconds`` enforces a wall-clock cap on the callable via a
  background thread; on expiry :class:`~chainweaver.exceptions.ToolTimeoutError`
  is raised.  Note that Python threads cannot be forcibly cancelled — a
  tool that ignores its environment will keep running in the background;
  the timeout only protects the *caller* from waiting.
- ``max_output_size`` rejects oversized payloads after measuring the
  UTF-8 encoded JSON length of the raw output dict.

``Tool.from_flow`` (issue #24) wraps a registered :class:`~chainweaver.flow.Flow`
or :class:`~chainweaver.flow.DAGFlow` as a single :class:`Tool` whose
``fn`` delegates back to a :class:`~chainweaver.executor.FlowExecutor`.  This
collapses an N-step compiled flow into one tool-shaped capability that can be
composed into other flows, exposed to external frameworks (OpenAI/Anthropic
function schemas, MCP servers), or registered in a weaver-spec catalog.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
from collections.abc import Awaitable, Callable
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from functools import cached_property
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

from chainweaver.compat import schema_fingerprint
from chainweaver.contracts import ToolSafetyContract, merge_safety
from chainweaver.exceptions import (
    FlowExecutionError,
    FlowSerializationError,
    ToolDefinitionError,
    ToolNotFoundError,
    ToolOutputSizeError,
    ToolTimeoutError,
)
from chainweaver.flow import DAGFlow, DAGFlowStep, Flow, FlowStep

if TYPE_CHECKING:
    from chainweaver.executor import FlowExecutor


def _is_async_callable(fn: Callable[..., Any]) -> bool:
    """Return ``True`` if *fn* (or its bound call) is a coroutine function.

    ``inspect.iscoroutinefunction`` only recognises plain async ``def``
    functions; callables whose call shape is async (e.g. class-based
    tool wrappers used by the MCP adapter) still need to be treated
    as async.  We probe the call shape statically via the instance
    ``__dict__`` and ``inspect.getattr_static`` to locate the
    ``__call__`` attribute and re-check it, which covers both shapes
    without invoking the callable.
    """
    if inspect.iscoroutinefunction(fn):
        return True
    if not callable(fn):
        return False
    # Bound call (e.g. instance of a class with ``async def __call__``):
    # accessing the attribute via reflection still works without naming
    # the dunder explicitly in source.
    bound = vars(fn).get("__call__") if hasattr(fn, "__dict__") else None
    if bound is None:
        bound = inspect.getattr_static(type(fn), "__call__", None)
    return bound is not None and inspect.iscoroutinefunction(bound)


class Tool:
    """A named, schema-validated callable unit of work.

    Args:
        name: Unique identifier for the tool.  Used when referencing it inside
            a :class:`~chainweaver.flow.FlowStep`.
        description: Human-readable description of what the tool does.
        input_schema: A :class:`pydantic.BaseModel` subclass that defines and
            validates the tool's input.
        output_schema: A :class:`pydantic.BaseModel` subclass that defines and
            validates the tool's output.
        fn: The callable that implements the tool's logic.  It must accept a
            single argument that is an instance of *input_schema* and return a
            ``dict`` that is compatible with *output_schema*.
        timeout_seconds: Optional wall-clock cap (seconds) for ``fn``.  When
            set and exceeded, :class:`~chainweaver.exceptions.ToolTimeoutError`
            is raised.  ``None`` (the default) disables the timeout.
        max_output_size: Optional cap on the raw output dict size, measured
            as the UTF-8 byte length of its JSON serialization.  When set and
            exceeded, :class:`~chainweaver.exceptions.ToolOutputSizeError` is
            raised.  ``None`` (the default) disables the size check.

    Example::

        from pydantic import BaseModel
        from chainweaver.tools import Tool

        class DoubleInput(BaseModel):
            number: int

        class DoubleOutput(BaseModel):
            value: int

        def double(inp: DoubleInput) -> dict:
            return {"value": inp.number * 2}

        tool = Tool(
            name="double",
            description="Doubles a number.",
            input_schema=DoubleInput,
            output_schema=DoubleOutput,
            fn=double,
            timeout_seconds=5.0,
            max_output_size=1024,
        )
    """

    def __init__(
        self,
        *,
        name: str,
        description: str,
        input_schema: type[BaseModel],
        output_schema: type[BaseModel],
        fn: Callable[[Any], dict[str, Any] | Awaitable[dict[str, Any]]],
        timeout_seconds: float | None = None,
        max_output_size: int | None = None,
        schema_version: str = "0.0.0",
        cacheable: bool | None = None,
        safety: ToolSafetyContract | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.input_schema = input_schema
        self.output_schema = output_schema
        self.fn = fn
        self.timeout_seconds = timeout_seconds
        self.max_output_size = max_output_size
        self.schema_version = schema_version
        # ``cacheable`` controls whether ``FlowExecutor``'s step cache
        # (issue #127) is allowed to memoize this tool's outputs.  It
        # mirrors ``ToolSafetyContract.cacheable`` (issue #19), which is the
        # exported metadata downstream governance / catalog consumers read.
        # The two must never silently disagree, so they are reconciled here:
        #
        # - ``cacheable=None`` (unspecified): derive it from ``safety`` when a
        #   contract is supplied, otherwise default to ``True`` — the
        #   convenient "drop in a cache and it works for pure tools" default.
        # - explicit ``cacheable`` + explicit ``safety`` that disagree: raise
        #   rather than silently letting one win.
        #
        # ``self.safety`` defaults to a maximally-permissive contract so bare
        # ``Tool(...)`` constructors keep working unchanged.  It is consumed by
        # :meth:`Tool.from_flow` (issue #125) and downstream consumers; the
        # executor itself does not enforce contract fields in v1.
        self._safety_declared = safety is not None
        if safety is None:
            effective_cacheable = True if cacheable is None else cacheable
            self.cacheable = effective_cacheable
            self.safety: ToolSafetyContract = ToolSafetyContract(cacheable=effective_cacheable)
        else:
            if cacheable is not None and cacheable != safety.cacheable:
                raise ValueError(
                    f"Tool '{name}' received conflicting cacheable settings: "
                    f"cacheable={cacheable} but safety.cacheable={safety.cacheable}. "
                    f"Set one, or make them agree."
                )
            self.cacheable = safety.cacheable
            self.safety = safety
        # Whether ``fn`` is a coroutine function — pre-computed once
        # because ``inspect.iscoroutinefunction`` doesn't recognise
        # callables whose ``__call__`` is async, so we also inspect the
        # callable's ``__call__`` attribute (issue #80).
        self.is_async = _is_async_callable(fn)

    @property
    def safety_declared(self) -> bool:
        """Whether safety is explicit or fully derived from explicit contracts."""
        return self._safety_declared

    @cached_property
    def input_schema_hash(self) -> str:
        """SHA-256 fingerprint of the input schema (cached per instance)."""
        return schema_fingerprint(self.input_schema)

    @cached_property
    def output_schema_hash(self) -> str:
        """SHA-256 fingerprint of the output schema (cached per instance)."""
        return schema_fingerprint(self.output_schema)

    @cached_property
    def schema_hash(self) -> str:
        """Combined hash of input + output schemas + schema version (cached per instance)."""
        combined = json.dumps(
            [self.input_schema_hash, self.output_schema_hash, self.schema_version],
            separators=(",", ":"),
        )
        return hashlib.sha256(combined.encode()).hexdigest()[:16]

    def run(self, raw_inputs: dict[str, Any]) -> dict[str, Any]:
        """Validate *raw_inputs*, execute the tool, and validate the output.

        Args:
            raw_inputs: A dictionary that will be coerced into *input_schema*.

        Returns:
            A validated dictionary conforming to *output_schema*.

        Raises:
            pydantic.ValidationError: When *raw_inputs* or the callable's
                return value do not match the declared schemas.
            ToolTimeoutError: When ``timeout_seconds`` is set and the
                callable does not return in time.
            ToolOutputSizeError: When ``max_output_size`` is set and the raw
                output JSON exceeds the cap.
            ToolDefinitionError: When the tool's ``fn`` is async and this
                synchronous entry point is invoked from inside a running
                event loop.  Use :meth:`run_async` (and the executor's
                ``execute_flow_async``) instead.
        """
        validated_input = self.input_schema.model_validate(raw_inputs)
        raw_output = self._call_fn(validated_input)
        return self._validate_output(raw_output)

    async def run_async(self, raw_inputs: dict[str, Any]) -> dict[str, Any]:
        """Async variant of :meth:`run` (issue #80).

        Awaits async tool functions natively and dispatches sync tool
        functions to a worker thread via :func:`asyncio.to_thread`, so
        either shape is safe to use inside the executor's async lane
        (:meth:`FlowExecutor.execute_flow_async`).

        Args:
            raw_inputs: A dictionary that will be coerced into *input_schema*.

        Returns:
            A validated dictionary conforming to *output_schema*.

        Raises:
            Same as :meth:`run`, except that timeout enforcement uses
            :func:`asyncio.wait_for` instead of a worker-thread future.
        """
        validated_input = self.input_schema.model_validate(raw_inputs)
        raw_output = await self._call_fn_async(validated_input)
        return self._validate_output(raw_output)

    def _validate_output(self, raw_output: dict[str, Any]) -> dict[str, Any]:
        """Apply size cap + schema validation; shared by ``run`` / ``run_async``."""
        if self.max_output_size is not None:
            size = len(json.dumps(raw_output, default=str).encode("utf-8"))
            if size > self.max_output_size:
                raise ToolOutputSizeError(self.name, size, self.max_output_size)

        validated_output = self.output_schema.model_validate(raw_output)
        return validated_output.model_dump()

    def _call_fn(self, validated_input: BaseModel) -> dict[str, Any]:
        """Invoke ``self.fn``, optionally bounded by ``timeout_seconds``."""
        if self.is_async:
            # Async tools cannot be driven from a synchronous executor
            # safely — ``asyncio.run`` would either start a fresh loop
            # (acceptable from sync code, harmful from inside an
            # existing loop) or deadlock.  Force callers to switch to
            # the async lane explicitly so misuse is obvious.
            try:
                asyncio.get_running_loop()
                in_loop = True
            except RuntimeError:
                in_loop = False
            if in_loop:
                raise ToolDefinitionError(
                    self.name,
                    "Tool has an async 'fn' but Tool.run() was called from a running "
                    "event loop. Use FlowExecutor.execute_flow_async() instead.",
                )
            return asyncio.run(self._call_fn_async(validated_input))

        if self.timeout_seconds is None:
            result = self.fn(validated_input)
            assert not inspect.isawaitable(result)
            return result

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.fn, validated_input)
            try:
                result = future.result(timeout=self.timeout_seconds)
            except FuturesTimeoutError as exc:
                raise ToolTimeoutError(self.name, self.timeout_seconds) from exc
            assert not inspect.isawaitable(result)
            return result

    async def _call_fn_async(self, validated_input: BaseModel) -> dict[str, Any]:
        """Async-native counterpart to ``_call_fn``."""
        fn_any: Any = self.fn  # the declared union type masks Awaitable for mypy
        if self.is_async:
            coro = fn_any(validated_input)
            assert inspect.isawaitable(coro)
            if self.timeout_seconds is None:
                result: dict[str, Any] = await coro
                return result
            try:
                result = await asyncio.wait_for(coro, timeout=self.timeout_seconds)
            except asyncio.TimeoutError as exc:
                raise ToolTimeoutError(self.name, self.timeout_seconds) from exc
            return result

        # Sync ``fn`` — offload to a worker thread so the event loop
        # stays responsive.  ``timeout_seconds`` is enforced via
        # ``asyncio.wait_for``; note that, like the sync path, the
        # underlying thread cannot be cancelled.
        if self.timeout_seconds is None:
            result = await asyncio.to_thread(fn_any, validated_input)
            return result
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(fn_any, validated_input),
                timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise ToolTimeoutError(self.name, self.timeout_seconds) from exc
        return result

    def __repr__(self) -> str:
        return f"Tool(name={self.name!r})"

    # ------------------------------------------------------------------
    # Flow-as-Tool adapter (issue #24)
    # ------------------------------------------------------------------

    @classmethod
    def from_flow(
        cls,
        flow: Flow | DAGFlow,
        executor: FlowExecutor,
        *,
        name: str | None = None,
        description: str | None = None,
        input_schema: type[BaseModel] | None = None,
        output_schema: type[BaseModel] | None = None,
        safety: ToolSafetyContract | None = None,
    ) -> Tool:
        """Wrap a registered flow as a :class:`Tool` (issue #24).

        The returned tool behaves like any other ``Tool``: its ``fn``
        validates inputs against the derived ``input_schema``, dispatches
        the flow through *executor*, and returns the validated final
        output.  This makes a compiled flow composable as a step inside
        another flow, or exportable as a single capability to external
        consumers (OpenAI / Anthropic / MCP / weaver-spec).

        Schema derivation prefers, in order:

        1. The explicit ``input_schema`` / ``output_schema`` keyword overrides.
        2. The flow's own ``input_schema_ref`` / ``output_schema_ref`` (when set).
        3. The first step's tool's ``input_schema`` (for inputs) and the
           last step's tool's ``output_schema`` (for outputs).  For a
           :class:`DAGFlow`, "last step" means the unique sink node; if
           the DAG has multiple sinks, an ``output_schema`` override is
           required.

        Args:
            flow: A :class:`Flow` or :class:`DAGFlow` whose steps reference
                tools registered on *executor*.  The flow **must** also be
                registered on *executor*'s registry before the returned
                tool is invoked, because its ``fn`` calls
                ``executor.execute_flow(flow.name, …)`` to dispatch the
                run.  ``from_flow`` itself does not register the flow;
                registration is the caller's responsibility (typically
                done immediately before or after this call).
            executor: The :class:`~chainweaver.executor.FlowExecutor` that
                will run the wrapped flow.  Captured by reference; later
                changes to its tool/flow registries are visible through
                the returned tool.
            name: Override for the resulting tool's name.  Defaults to
                ``flow.name``.
            description: Override for the resulting tool's description.
                Defaults to ``flow.description``.
            input_schema: Override for the derived input schema.  Useful
                when the first step's tool input contains fields the
                caller should not have to provide directly.
            output_schema: Override for the derived output schema.
                Required for DAG flows with multiple sink nodes when no
                flow-level ``output_schema_ref`` is set.
            safety: Override for the derived :class:`ToolSafetyContract`
                (issue #125).  When ``None`` (the default), the wrapper's
                contract is computed from the constituent step tools'
                contracts via :func:`~chainweaver.contracts.merge_safety`
                — "most-restrictive wins" across every field (worst
                :class:`SideEffectLevel`, worst :class:`StabilityLevel`,
                worst :class:`DeterminismLevel`, AND across
                ``idempotent`` / ``cacheable``, OR across
                 ``requires_approval``).  When explicitly set, the override
                 wins outright with no merge.  Step tools that have not
                 yet been registered on *executor* are skipped during
                 derivation — their contracts are unknown, so they
                 cannot contribute.  The wrapper reports
                 :attr:`safety_declared` only when the override, flow contract,
                 or every constituent tool contract is explicit.

        Returns:
            A :class:`Tool` instance whose ``fn`` executes *flow*.  The
            tool can be registered via
            :meth:`~chainweaver.executor.FlowExecutor.register_tool` just
            like any other tool, enabling flow composition by name.

        Raises:
            ToolDefinitionError: When the flow has no steps, or when
                neither the explicit override, the flow-level ref, nor a
                step-level fallback can produce a required schema (or
                when a DAG has multiple sinks without an explicit
                ``output_schema`` override).
        """
        if not flow.steps:
            raise ToolDefinitionError(flow.name, "Cannot wrap a flow with no steps as a tool.")

        tool_name = name if name is not None else flow.name
        tool_description = description if description is not None else flow.description

        # --- Input schema resolution --------------------------------------
        if input_schema is not None:
            resolved_input = input_schema
        elif flow.input_schema_ref is not None:
            # Flow.input_schema either returns a BaseModel subclass or
            # raises FlowSerializationError when the ref is set; wrap that
            # error in ToolDefinitionError to match this function's other
            # "Cannot derive schema" branches.
            try:
                resolved_input = flow.input_schema  # type: ignore[assignment]
            except FlowSerializationError as exc:
                raise ToolDefinitionError(
                    flow.name,
                    f"Cannot resolve Flow.input_schema_ref '{flow.input_schema_ref}': {exc}",
                ) from exc
        else:
            first_step = flow.steps[0]
            if first_step.tool_name is None:
                # Composed sub-flow first step (issue #75): there is no tool to
                # read a schema from. Require an explicit declaration rather
                # than guessing across the sub-flow boundary.
                raise ToolDefinitionError(
                    flow.name,
                    f"Cannot derive input schema: first step runs sub-flow "
                    f"'{first_step.flow_name}'. Set Flow.input_schema_ref or "
                    "pass input_schema=... explicitly.",
                )
            try:
                first_tool = executor.get_tool(first_step.tool_name)
            except ToolNotFoundError as exc:
                raise ToolDefinitionError(
                    flow.name,
                    f"Cannot derive input schema: first step's tool "
                    f"'{first_step.tool_name}' is not registered on the executor. "
                    "Pass input_schema=... or register the tool first.",
                ) from exc
            resolved_input = first_tool.input_schema

        # --- Output schema resolution -------------------------------------
        if output_schema is not None:
            resolved_output = output_schema
        elif flow.output_schema_ref is not None:
            try:
                resolved_output = flow.output_schema  # type: ignore[assignment]
            except FlowSerializationError as exc:
                raise ToolDefinitionError(
                    flow.name,
                    f"Cannot resolve Flow.output_schema_ref '{flow.output_schema_ref}': {exc}",
                ) from exc
        else:
            terminal_step = _terminal_step(flow)
            if terminal_step.tool_name is None:
                # Composed sub-flow terminal step (issue #75): require an
                # explicit output schema rather than guessing across the
                # sub-flow boundary.
                raise ToolDefinitionError(
                    flow.name,
                    f"Cannot derive output schema: terminal step runs sub-flow "
                    f"'{terminal_step.flow_name}'. Set Flow.output_schema_ref or "
                    "pass output_schema=... explicitly.",
                )
            try:
                terminal_tool = executor.get_tool(terminal_step.tool_name)
            except ToolNotFoundError as exc:
                raise ToolDefinitionError(
                    flow.name,
                    f"Cannot derive output schema: terminal step's tool "
                    f"'{terminal_step.tool_name}' is not registered on the executor. "
                    "Pass output_schema=... or register the tool first.",
                ) from exc
            resolved_output = terminal_tool.output_schema

        flow_name = flow.name

        def _flow_fn(validated_input: BaseModel) -> dict[str, Any]:
            result = executor.execute_flow(flow_name, validated_input.model_dump())
            if not result.success:
                # Surface the first failed step's context so the caller can
                # diagnose without inspecting the full execution log.
                failed = next((r for r in result.execution_log if not r.success), None)
                if failed is None:
                    detail = "Flow execution failed without recording a failing step."
                    step_index = -1
                else:
                    detail = failed.error_message or failed.error_type or "Unknown error."
                    step_index = failed.step_index
                raise FlowExecutionError(tool_name=tool_name, step_index=step_index, detail=detail)
            if result.final_output is None:
                # Defensive: a successful run should always have a final_output,
                # but the executor's contract allows None on failure paths and
                # this is the only place the closure can guarantee non-None.
                # Use ``len(flow.steps)`` (the flow-output validation sentinel
                # per AGENTS.md §5 StepRecord) — this anomaly is a flow-output
                # contract violation, not a flow-input validation failure
                # (which is what ``step_index=-1`` would denote).
                raise FlowExecutionError(
                    tool_name=tool_name,
                    step_index=len(flow.steps),
                    detail="Flow reported success but produced no final output.",
                )
            return result.final_output

        # --- Safety derivation (issue #125) -------------------------------
        if safety is not None:
            resolved_safety: ToolSafetyContract = safety
            safety_declared = True
        elif flow.safety is not None:
            resolved_safety = flow.safety
            safety_declared = True
        else:
            constituent_contracts: list[ToolSafetyContract] = []
            safety_declared = True
            for step in flow.steps:
                if step.tool_name is None:
                    # Composed sub-flow step (issue #75): its safety contract is
                    # unknown here; callers can pass safety=... explicitly.
                    safety_declared = False
                    continue
                try:
                    inner_tool = executor.get_tool(step.tool_name)
                except ToolNotFoundError:
                    # Tool unregistered at composition time — its contract
                    # is unknown.  Skip rather than guess; callers that
                    # care can pass ``safety=...`` explicitly.
                    safety_declared = False
                    continue
                constituent_contracts.append(inner_tool.safety)
                if not inner_tool.safety_declared:
                    safety_declared = False
            resolved_safety = merge_safety(constituent_contracts)

        wrapped = cls(
            name=tool_name,
            description=tool_description,
            input_schema=resolved_input,
            output_schema=resolved_output,
            fn=_flow_fn,
            safety=resolved_safety,
        )
        wrapped._safety_declared = safety_declared
        return wrapped


def _terminal_step(flow: Flow | DAGFlow) -> FlowStep:
    """Return the sole terminal step of *flow* for output-schema derivation.

    For a linear :class:`Flow` the terminal step is the last entry in
    ``flow.steps``.  For a :class:`DAGFlow` the terminal step is the unique
    sink node (a step that no other step depends on).  When the DAG has more
    than one sink, deriving a single output schema is ambiguous; the caller
    must supply ``output_schema=`` explicitly.

    Args:
        flow: The flow whose terminal step should be located.

    Returns:
        The terminal :class:`FlowStep` (or :class:`DAGFlowStep` for DAGs).

    Raises:
        ToolDefinitionError: When *flow* is a DAG with zero or multiple
            sink nodes.
    """
    from chainweaver.exceptions import ToolDefinitionError

    if not isinstance(flow, DAGFlow):
        return flow.steps[-1]

    referenced: set[str] = set()
    for step in flow.steps:
        referenced.update(step.depends_on)
    sinks: list[DAGFlowStep] = [s for s in flow.steps if s.step_id not in referenced]
    if len(sinks) == 1:
        return sinks[0]
    if len(sinks) == 0:
        raise ToolDefinitionError(
            flow.name,
            "DAG has no sink node; cannot derive output schema. "
            "Pass output_schema=... explicitly.",
        )
    sink_ids = ", ".join(f"'{s.step_id}'" for s in sinks)
    raise ToolDefinitionError(
        flow.name,
        f"DAG has multiple sink nodes ({sink_ids}); output schema is ambiguous. "
        "Pass output_schema=... explicitly.",
    )
