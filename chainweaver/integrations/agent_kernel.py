"""Agent-kernel execution backend for ChainWeaver flows (issue #89).

The Weaver Stack ``BOUNDARIES.md`` invariant states that ChainWeaver
orchestrates flows but does not execute capabilities directly — each
capability-typed step in a flow is delegated to an agent-kernel via a
:class:`~chainweaver.integrations.weaver_spec.CapabilityToken` plus a
:class:`~chainweaver.integrations.weaver_spec.RoutingDecision`.

The base :class:`~chainweaver.executor.FlowExecutor` is the
deterministic, tool-only graph runner — it stays untouched.
:class:`KernelBackedExecutor` is a subclass that overrides one hook
(``_execute_capability_step``) so flows containing
:class:`~chainweaver.flow.DAGFlowStep` instances with
``step_type="capability"`` execute against an agent-kernel instead of
failing.

ChainWeaver does not hard-depend on an ``agent_kernel`` Python
SDK — :class:`KernelProtocol` is a structural protocol so callers
wire whichever transport their kernel exposes (in-process, gRPC, HTTP,
test stub).

Example
-------

    from chainweaver.integrations.agent_kernel import (
        InMemoryKernel,
        KernelBackedExecutor,
    )
    from chainweaver.integrations.weaver_spec import CapabilityToken

    def ingest_capability(inputs, token):
        return {"rows": len(inputs.get("records", []))}

    kernel = InMemoryKernel({"data.ingest": ingest_capability})
    executor = KernelBackedExecutor(registry=registry, kernel=kernel)

Capability steps record their outputs in the standard ``StepRecord``
shape, so observability and tracing work identically to tool steps.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any, Protocol, runtime_checkable

from chainweaver.exceptions import KernelInvocationError
from chainweaver.executor import FlowExecutor, StepRecord
from chainweaver.flow import DAGFlowStep
from chainweaver.integrations.weaver_spec import CapabilityToken
from chainweaver.log_utils import get_logger, log_step_error

_logger = get_logger("chainweaver.integrations.agent_kernel")


def _now_utc() -> datetime:
    """Return the current UTC time as a timezone-aware ``datetime``.

    Kept local so this integration does not reach into
    :mod:`chainweaver.executor` private helpers — the executor stays free to
    refactor its internals without breaking the kernel backend.
    """
    return datetime.now(timezone.utc)


def _exc_to_strings(exc: Exception) -> tuple[str, str]:
    """Render an exception as ``(error_type, error_message)`` strings.

    Mirrors the executor's record-building convention locally; see
    :func:`_now_utc` for why the helper is duplicated rather than imported.
    """
    return type(exc).__name__, str(exc)


@runtime_checkable
class KernelProtocol(Protocol):
    """Structural protocol for an agent-kernel runner (issue #89).

    A kernel exposes a single :meth:`invoke` method that runs a
    capability identified by a
    :class:`~chainweaver.integrations.weaver_spec.CapabilityToken`
    against an input dictionary, returning the capability's outputs.

    The protocol is intentionally minimal so any transport (in-process
    callable, RPC client, HTTP wrapper) can satisfy it.  Errors should
    raise — :class:`KernelBackedExecutor` wraps them in a
    :class:`~chainweaver.exceptions.KernelInvocationError` and surfaces
    them as a failed :class:`StepRecord`.
    """

    def invoke(self, token: CapabilityToken, inputs: dict[str, Any]) -> dict[str, Any]:
        """Execute the capability identified by *token* against *inputs*.

        Args:
            token: The :class:`CapabilityToken` for the target capability.
            inputs: The resolved input dictionary for this step.

        Returns:
            The capability's output dictionary — merged into the flow's
            execution context just like a tool's outputs.

        Raises:
            Exception: Any exception is caught by
                :class:`KernelBackedExecutor` and wrapped in a
                :class:`~chainweaver.exceptions.KernelInvocationError`.
        """
        ...


class InMemoryKernel:
    """Deterministic in-process :class:`KernelProtocol` for tests and offline runs.

    Maps ``capability_id`` strings to plain Python callables of the
    shape ``(inputs, token) -> outputs``.  No network, no async, no
    state — same semantics as :class:`~chainweaver.tools.Tool` fn but
    keyed by capability identifier rather than tool name.
    """

    __slots__ = ("_capabilities",)

    def __init__(
        self,
        capabilities: dict[str, Callable[[dict[str, Any], CapabilityToken], dict[str, Any]]],
    ) -> None:
        """Initialise the kernel with a static capability registry.

        Args:
            capabilities: Mapping from ``capability_id`` to a callable
                of the shape ``(inputs, token) -> outputs``.
        """
        self._capabilities: dict[
            str, Callable[[dict[str, Any], CapabilityToken], dict[str, Any]]
        ] = dict(capabilities)

    def invoke(self, token: CapabilityToken, inputs: dict[str, Any]) -> dict[str, Any]:
        try:
            fn = self._capabilities[token.capability_id]
        except KeyError as exc:
            raise LookupError(
                f"InMemoryKernel has no capability registered for id='{token.capability_id}'."
            ) from exc
        return fn(inputs, token)


class KernelBackedExecutor(FlowExecutor):
    """A :class:`FlowExecutor` that delegates capability steps to an agent-kernel (issue #89).

    Behaves exactly like the base :class:`FlowExecutor` for
    ``step_type="tool"`` steps.  For ``step_type="capability"`` steps in
    a :class:`~chainweaver.flow.DAGFlow`, the executor:

    1. Resolves the step's inputs against the merged context (same path
       tool steps take).
    2. Builds a :class:`CapabilityToken` from the step's
       ``capability_id`` (the per-token field) — or uses
       :attr:`default_token` if the step omits a token but the
       executor was initialised with one.
    3. Calls ``kernel.invoke(token, inputs)``.
    4. Wraps the result in a :class:`StepRecord` with the same shape
       tool steps produce, so observability and tracing are uniform.

    Failures (kernel raises, no token resolvable) surface as
    :class:`~chainweaver.exceptions.KernelInvocationError` and abort
    the flow.

    The class deliberately holds no LLM/network state of its own — the
    base executor's three invariants (no LLM, no network I/O, no
    randomness) are concerns of the *kernel* implementation, not this
    adapter.
    """

    def __init__(
        self,
        *args: Any,
        kernel: KernelProtocol,
        default_token: CapabilityToken | None = None,
        **kwargs: Any,
    ) -> None:
        """Initialise the executor with a kernel and optional default token.

        Args:
            *args: Forwarded to :class:`FlowExecutor`.
            kernel: A :class:`KernelProtocol` implementation.
            default_token: Optional :class:`CapabilityToken` used when a
                step's ``capability_id`` is set but no per-step token
                is plumbed (the common case for tests and single-tenant
                deployments).  When ``None``, every capability step
                must resolve its own token via
                :meth:`_token_for_step` — subclasses can override that
                method for richer token sourcing.
            **kwargs: Forwarded to :class:`FlowExecutor`.
        """
        super().__init__(*args, **kwargs)
        if not isinstance(kernel, KernelProtocol):
            raise TypeError(
                f"KernelBackedExecutor requires a KernelProtocol; got {type(kernel).__name__}."
            )
        self._kernel = kernel
        self._default_token = default_token

    @property
    def kernel(self) -> KernelProtocol:
        """Return the bound :class:`KernelProtocol`."""
        return self._kernel

    @property
    def default_token(self) -> CapabilityToken | None:
        """Return the executor-wide default :class:`CapabilityToken`, if any."""
        return self._default_token

    def _token_for_step(self, step: DAGFlowStep) -> CapabilityToken:
        """Resolve the :class:`CapabilityToken` to use for *step*.

        Override in subclasses to mint or fetch per-step tokens (e.g. a
        scoped token issued by an auth server).  The default
        implementation uses the executor's :attr:`default_token` when
        the step's ``capability_id`` matches the default token's id,
        or mints a tokenless :class:`CapabilityToken` carrying just the
        ``capability_id`` otherwise.

        Args:
            step: The :class:`DAGFlowStep` being executed.

        Returns:
            A :class:`CapabilityToken` for the kernel call.

        Raises:
            KernelInvocationError: When no token can be resolved for
                *step*.
        """
        if step.capability_id is None:
            raise KernelInvocationError(
                "<unknown>",
                -1,
                f"Step '{step.step_id}' has step_type='capability' but capability_id is None.",
            )
        if (
            self._default_token is not None
            and self._default_token.capability_id == step.capability_id
        ):
            return self._default_token
        return CapabilityToken(capability_id=step.capability_id, token="")

    def _execute_capability_step(
        self,
        step_index: int,
        step: DAGFlowStep,
        context: dict[str, Any],
        flow_name: str,
        trace_id: str,
    ) -> StepRecord:
        """Dispatch *step* through the bound kernel.

        Overrides :meth:`FlowExecutor._execute_capability_step` to
        translate a ``step_type="capability"`` invocation into a
        :meth:`KernelProtocol.invoke` call.

        Args:
            step_index: Zero-based position of the step in the flow.
            step: The :class:`DAGFlowStep` whose ``step_type`` is
                ``"capability"``.
            context: The current accumulated context.
            flow_name: Name of the enclosing flow.
            trace_id: Trace id of the enclosing execution.

        Returns:
            A :class:`StepRecord` capturing the kernel-side outcome.
        """
        started_at = _now_utc()
        t0 = time.perf_counter()

        # Resolve inputs against the context using the same mapping
        # semantics the executor applies to tool steps.  A bare empty
        # mapping means "pass the full context".  Per-key lookups
        # follow the same rules as :meth:`FlowExecutor._resolve_inputs`.
        if not step.input_mapping:
            inputs: dict[str, Any] = dict(context)
        else:
            inputs = {}
            for target_key, source in step.input_mapping.items():
                if isinstance(source, str):
                    if source not in context:
                        err = KernelInvocationError(
                            step.capability_id or "<unknown>",
                            step_index,
                            f"Input mapping key '{source}' not found in "
                            f"context for step '{step.step_id}'.",
                        )
                        log_step_error(_logger, step_index, step.tool_name, err)
                        err_type, err_msg = _exc_to_strings(err)
                        now = _now_utc()
                        return StepRecord(
                            step_index=step_index,
                            tool_name=step.tool_name,
                            inputs={},
                            outputs=None,
                            error_type=err_type,
                            error_message=err_msg,
                            success=False,
                            started_at=started_at,
                            ended_at=now,
                            duration_ms=(time.perf_counter() - t0) * 1000.0,
                        )
                    inputs[target_key] = context[source]
                else:
                    inputs[target_key] = source

        try:
            token = self._token_for_step(step)
        except KernelInvocationError as exc:
            # Refine step_index now that we know it.
            err = KernelInvocationError(exc.capability_id, step_index, exc.detail)
            log_step_error(_logger, step_index, step.tool_name, err)
            err_type, err_msg = _exc_to_strings(err)
            now = _now_utc()
            return StepRecord(
                step_index=step_index,
                tool_name=step.tool_name,
                inputs=inputs,
                outputs=None,
                error_type=err_type,
                error_message=err_msg,
                success=False,
                started_at=started_at,
                ended_at=now,
                duration_ms=(time.perf_counter() - t0) * 1000.0,
            )

        try:
            outputs = self._kernel.invoke(token, dict(inputs))
        except Exception as exc:
            err = KernelInvocationError(
                token.capability_id,
                step_index,
                f"kernel raised {type(exc).__name__}: {exc}",
            )
            err.__cause__ = exc
            log_step_error(_logger, step_index, step.tool_name, err)
            err_type, err_msg = _exc_to_strings(err)
            now = _now_utc()
            return StepRecord(
                step_index=step_index,
                tool_name=step.tool_name,
                inputs=inputs,
                outputs=None,
                error_type=err_type,
                error_message=err_msg,
                success=False,
                started_at=started_at,
                ended_at=now,
                duration_ms=(time.perf_counter() - t0) * 1000.0,
            )

        if not isinstance(outputs, dict):
            err = KernelInvocationError(
                token.capability_id,
                step_index,
                f"kernel returned non-dict outputs ({type(outputs).__name__}).",
            )
            log_step_error(_logger, step_index, step.tool_name, err)
            err_type, err_msg = _exc_to_strings(err)
            now = _now_utc()
            return StepRecord(
                step_index=step_index,
                tool_name=step.tool_name,
                inputs=inputs,
                outputs=None,
                error_type=err_type,
                error_message=err_msg,
                success=False,
                started_at=started_at,
                ended_at=now,
                duration_ms=(time.perf_counter() - t0) * 1000.0,
            )

        now = _now_utc()
        return StepRecord(
            step_index=step_index,
            tool_name=step.tool_name,
            inputs=inputs,
            outputs=outputs,
            error_type=None,
            error_message=None,
            success=True,
            started_at=started_at,
            ended_at=now,
            duration_ms=(time.perf_counter() - t0) * 1000.0,
        )


__all__ = [
    "InMemoryKernel",
    "KernelBackedExecutor",
    "KernelProtocol",
]
