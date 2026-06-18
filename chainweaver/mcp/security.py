"""Trust-boundary controls for :class:`chainweaver.mcp.FlowServer`.

``FlowServer`` makes it one call to expose governed flows to any MCP client.
For stdio that inherits the host process's trust boundary, but SSE / HTTP
serving turns flows into a network service where callers expect an
authentication story, basic abuse protection, an authorization decision per
call, and control over how much failure detail leaks back across the wire.

This module provides the first-class seams that ``FlowServer`` wires into its
per-call dispatch path, plus reusable defaults:

* **Authentication** (issue #362) — :data:`Authenticator` resolves a
  :class:`CallerIdentity` from an :class:`MCPRequestContext`; returning ``None``
  or raising refuses the call with
  :class:`~chainweaver.exceptions.FlowAuthenticationError`.
* **Rate limiting** (issue #362) — the :class:`RateLimiter` protocol plus a
  deterministic in-memory :class:`FixedWindowRateLimiter`; a declined call
  raises :class:`~chainweaver.exceptions.RateLimitExceededError`.
* **Authorization** (issue #443) — an :class:`AuthorizationCallback` returns an
  :class:`AuthorizationDecision` (allow / deny + safe ``reason_code``) given an
  :class:`AuthorizationContext`; a deny raises
  :class:`~chainweaver.exceptions.FlowAuthorizationError`.
* **Error redaction** (issue #347) — :func:`render_error_detail` controls how
  much of a failing flow's error reaches the client.
* **Production profiles** (issue #446) — :class:`MCPServerProfile` bundles
  secure defaults (``strict`` / ``balanced`` / ``trusted-network``) with a
  :meth:`MCPServerProfile.diff` for audit reviews and a readiness check.

The mechanism deliberately mirrors :mod:`chainweaver.approvals`: ``FlowServer``
only ever *calls* host-supplied hooks, so it never performs authentication,
authorization, or rate-limiting policy itself — those stay in the host's trust
boundary, where a token check, policy service, or RPC belongs.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from chainweaver.contracts import SideEffectLevel, ToolSafetyContract
from chainweaver.exceptions import (
    FlowAuthenticationError,
    FlowAuthorizationError,
    RateLimitExceededError,
)
from chainweaver.flow import FlowLifecycle
from chainweaver.log_utils import DEFAULT_REDACT_KEYS, RedactionPolicy

if TYPE_CHECKING:  # pragma: no cover — type-checking only
    from collections.abc import Iterable, Mapping

_AUDIT_LOGGER = logging.getLogger("chainweaver.mcp.security")

ErrorDetail = Literal["full", "type_only", "generic"]
"""How much of a failing flow's error reaches an MCP client (issue #347).

* ``"full"`` — ``"{error_type}: {error_message}"`` (after optional redaction).
  The historical, developer-friendly default.
* ``"type_only"`` — the exception class name only; no message text.
* ``"generic"`` — a fixed, non-leaky message regardless of the failure.
"""

GENERIC_ERROR_MESSAGE = "The flow failed; contact the server operator for details."
"""Client-facing message used under ``error_detail="generic"`` (issue #347)."""

# A default policy that masks well-known secret key names in the input summary
# handed to an authorizer, so wiring an authorizer never widens secret exposure.
_DEFAULT_SUMMARY_REDACTION = RedactionPolicy(redact_keys=DEFAULT_REDACT_KEYS, max_value_length=200)


# ---------------------------------------------------------------------------
# Caller identity and request context (authentication, issue #362)
# ---------------------------------------------------------------------------


class CallerIdentity(BaseModel):
    """Identity of the caller invoking a flow over MCP (issue #362).

    Produced by an :data:`Authenticator` and threaded into the
    :class:`AuthorizationContext` and :class:`AuditEvent` so authorization and
    audit can reason about *who* is calling.

    Attributes:
        id: Stable principal identifier (e.g. a user id, service account, or
            API-key id).  Never put a raw secret here — it is logged in audit.
        scopes: Granted scopes / roles, for coarse authorization checks.
        metadata: Free-form, non-sensitive attributes the host wants to carry.
    """

    model_config = ConfigDict(frozen=True)

    id: str
    scopes: tuple[str, ...] = ()
    metadata: dict[str, Any] = Field(default_factory=dict)


class MCPRequestContext(BaseModel):
    """Snapshot of an inbound MCP tool call passed to an :data:`Authenticator`.

    For network transports the host typically authenticates from
    :attr:`http_headers` (best-effort populated from the active FastMCP HTTP
    request; empty for stdio).  ``transport`` lets a host apply different rules
    per transport — e.g. trust stdio but require a bearer token over HTTP.

    Attributes:
        flow_name: Name of the flow being invoked.
        flow_version: Version of the flow being invoked.
        mcp_tool_name: The advertised MCP tool name (server-prefixed).
        http_headers: Lower-cased request headers when serving over HTTP/SSE.
        request_id: Per-call correlation id (also stamped on audit events).
    """

    model_config = ConfigDict(frozen=True)

    flow_name: str
    flow_version: str
    mcp_tool_name: str
    http_headers: dict[str, str] = Field(default_factory=dict)
    request_id: str


Authenticator = Callable[[MCPRequestContext], "CallerIdentity | None"]
"""Resolve a :class:`CallerIdentity` from a request, or ``None`` to refuse it."""


# ---------------------------------------------------------------------------
# Authorization (issue #443)
# ---------------------------------------------------------------------------


class AuthorizationDecision(BaseModel):
    """Outcome of an :class:`AuthorizationCallback` — allow or deny with reason.

    Attributes:
        allowed: ``True`` to permit the call, ``False`` to refuse it.
        reason_code: Stable, **client-safe** code surfaced on
            :class:`~chainweaver.exceptions.FlowAuthorizationError`.  Keep it
            opaque (e.g. ``"forbidden"``, ``"out_of_scope"``) — never embed
            secrets or internal policy detail here.
        detail: Optional operational explanation for the audit hook and server
            logs only; it is **not** returned to the MCP client.
    """

    model_config = ConfigDict(frozen=True)

    allowed: bool
    reason_code: str = "forbidden"
    detail: str | None = None

    @classmethod
    def allow(cls) -> AuthorizationDecision:
        """Return an allow decision."""
        return cls(allowed=True, reason_code="allowed")

    @classmethod
    def deny(
        cls, reason_code: str = "forbidden", detail: str | None = None
    ) -> AuthorizationDecision:
        """Return a deny decision with a client-safe *reason_code*."""
        return cls(allowed=False, reason_code=reason_code, detail=detail)


class AuthorizationContext(BaseModel):
    """State handed to an :class:`AuthorizationCallback` before dispatch (issue #443).

    Attributes:
        request_id: Per-call correlation id (shared with the audit event).
        flow_name: Name of the flow about to run.
        flow_version: Version of the flow about to run.
        mcp_tool_name: The advertised MCP tool name (server-prefixed).
        caller: The authenticated :class:`CallerIdentity`, or ``None`` when no
            authenticator is configured (e.g. trusted stdio).
        input_summary: The call's arguments, already redacted with a default
            secret-masking policy so the authorizer (and its logs) never see
            raw secret values.
        safety: The flow's effective :class:`ToolSafetyContract`, or ``None``
            when it cannot be derived.
    """

    model_config = ConfigDict(frozen=True, arbitrary_types_allowed=True)

    request_id: str
    flow_name: str
    flow_version: str
    mcp_tool_name: str
    caller: CallerIdentity | None
    input_summary: dict[str, Any]
    safety: ToolSafetyContract | None


@runtime_checkable
class AuthorizationCallback(Protocol):
    """Structural protocol for per-call FlowServer authorization (issue #443)."""

    def authorize(self, ctx: AuthorizationContext) -> AuthorizationDecision | bool:
        """Return an :class:`AuthorizationDecision` (or a bare ``bool``)."""
        ...


AuthorizerCallable = Callable[[AuthorizationContext], "AuthorizationDecision | bool"]


class _CallableAuthorizer:
    """Adapt a bare callable into an :class:`AuthorizationCallback`."""

    __slots__ = ("_fn",)

    def __init__(self, fn: AuthorizerCallable) -> None:
        self._fn = fn

    def authorize(self, ctx: AuthorizationContext) -> AuthorizationDecision | bool:
        return self._fn(ctx)


def coerce_authorizer(
    authorizer: AuthorizationCallback | AuthorizerCallable | None,
) -> AuthorizationCallback | None:
    """Normalize *authorizer* into an :class:`AuthorizationCallback`, or ``None``.

    Accepts an object implementing ``authorize(ctx)`` or a bare callable with
    the equivalent signature (wrapped so the call site stays uniform), mirroring
    :func:`chainweaver.approvals.coerce_approval_callback`.

    Raises:
        TypeError: If *authorizer* is neither an :class:`AuthorizationCallback`
            nor callable.
    """
    if authorizer is None:
        return None
    if isinstance(authorizer, AuthorizationCallback):
        return authorizer
    if callable(authorizer):
        return _CallableAuthorizer(authorizer)
    raise TypeError(
        f"authorizer must implement AuthorizationCallback or be callable; "
        f"got {type(authorizer).__name__}."
    )


# ---------------------------------------------------------------------------
# Rate limiting (issue #362)
# ---------------------------------------------------------------------------


@runtime_checkable
class RateLimiter(Protocol):
    """Structural protocol for FlowServer rate limiting (issue #362)."""

    def acquire(self, caller: CallerIdentity | None, flow_name: str) -> bool:
        """Return ``True`` to permit the call, ``False`` to throttle it."""
        ...


class FixedWindowRateLimiter:
    """A deterministic, thread-safe fixed-window in-memory :class:`RateLimiter`.

    Allows at most ``max_calls`` per ``window_seconds`` per key.  The key is the
    caller id (``"anonymous"`` when unauthenticated), optionally combined with
    the flow name when ``per_flow=True``.  Time is read through an injectable
    ``time_fn`` (default :func:`time.monotonic`) so tests are deterministic.

    This is a single-process convenience for local / single-replica serving;
    multi-replica deployments should supply a shared-store limiter implementing
    the :class:`RateLimiter` protocol.
    """

    def __init__(
        self,
        max_calls: int,
        window_seconds: float,
        *,
        per_flow: bool = False,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        if max_calls < 1:
            raise ValueError("max_calls must be >= 1.")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be > 0.")
        self.max_calls = max_calls
        self.window_seconds = window_seconds
        self.per_flow = per_flow
        self._time_fn = time_fn
        self._lock = threading.Lock()
        # key -> (window_start, count)
        self._hits: dict[tuple[str, str], tuple[float, int]] = {}

    def acquire(self, caller: CallerIdentity | None, flow_name: str) -> bool:
        caller_key = caller.id if caller is not None else "anonymous"
        key = (caller_key, flow_name if self.per_flow else "")
        now = self._time_fn()
        with self._lock:
            start, count = self._hits.get(key, (now, 0))
            if now - start >= self.window_seconds:
                start, count = now, 0
            if count >= self.max_calls:
                self._hits[key] = (start, count)
                return False
            self._hits[key] = (start, count + 1)
            return True


# ---------------------------------------------------------------------------
# Audit (issues #362, #443)
# ---------------------------------------------------------------------------


class AuditEvent(BaseModel):
    """A structured allow/deny audit record emitted at the trust boundary.

    Emitted for every authentication, rate-limit, and authorization decision so
    operators get a complete record of who was allowed or refused and why.

    Attributes:
        action: Which gate produced the event.
        decision: ``"allow"`` or ``"deny"``.
        flow_name: Name of the flow being invoked.
        mcp_tool_name: The advertised MCP tool name (server-prefixed).
        request_id: Per-call correlation id.
        caller_id: Authenticated caller id, when known.
        reason_code: Client-safe reason code on a deny (``None`` on allow).
        detail: Operational detail for logs / SIEM (never sent to the client).
    """

    model_config = ConfigDict(frozen=True)

    action: Literal["authenticate", "rate_limit", "authorize"]
    decision: Literal["allow", "deny"]
    flow_name: str
    mcp_tool_name: str
    request_id: str
    caller_id: str | None = None
    reason_code: str | None = None
    detail: str | None = None


AuditHook = Callable[[AuditEvent], None]
"""Receives every :class:`AuditEvent`; exceptions are swallowed and logged."""


# ---------------------------------------------------------------------------
# Error redaction at the boundary (issue #347)
# ---------------------------------------------------------------------------


def render_error_detail(
    error_type: str | None,
    error_message: str | None,
    *,
    mode: ErrorDetail = "full",
    redaction: RedactionPolicy | None = None,
) -> str:
    """Render a failing flow's error for an MCP client per *mode* (issue #347).

    ``"generic"`` returns :data:`GENERIC_ERROR_MESSAGE`; ``"type_only"`` returns
    just the exception class name; ``"full"`` returns ``"{type}: {message}"``
    after applying *redaction* (when given) to the message text.
    """
    if mode == "generic":
        return GENERIC_ERROR_MESSAGE
    etype = error_type or "FlowExecutionError"
    if mode == "type_only":
        return etype
    message = error_message or ""
    if redaction is not None:
        message = redaction.redact_text(message)
    return f"{etype}: {message}" if message else etype


# ---------------------------------------------------------------------------
# Production profile packs (issue #446)
# ---------------------------------------------------------------------------


class ReadinessFinding(BaseModel):
    """A single result from :meth:`chainweaver.mcp.FlowServer.readiness_report`.

    Attributes:
        severity: ``"error"`` (deployment-blocking), ``"warning"``, or ``"info"``.
        code: Stable machine-readable finding code (e.g. ``"missing-authorizer"``).
        message: Human-readable explanation.
    """

    model_config = ConfigDict(frozen=True)

    severity: Literal["error", "warning", "info"]
    code: str
    message: str


class MCPServerProfile(BaseModel):
    """A named bundle of secure :class:`~chainweaver.mcp.FlowServer` defaults (issue #446).

    Profiles give operators a repeatable production baseline instead of
    assembling a dozen knobs by hand.  Pass one as ``FlowServer(..., profile=...)``;
    explicit keyword arguments always win over the profile's values.

    Threat notes
    ------------
    * ``strict`` — least privilege for hostile / multi-tenant networks: only
      read-only ``ACTIVE`` flows, approval-gated flows excluded, **generic**
      error text (no leakage), and an authorizer **and** authenticator are
      required to pass the readiness check.
    * ``balanced`` — single-tenant internal services: read-only ``ACTIVE``
      flows, error text limited to the exception type, hooks optional.
    * ``trusted-network`` — a locked-down network segment where richer behaviour
      is acceptable: ``ACTIVE``+``REVIEWED`` flows up to ``WRITE`` side effects,
      approval-gated flows allowed, full error detail.

    Attributes mirror the matching ``FlowServer`` constructor arguments, plus
    ``require_authorizer`` / ``require_authenticator`` / ``require_rate_limiter``
    which only drive :meth:`chainweaver.mcp.FlowServer.readiness_report`.
    """

    model_config = ConfigDict(frozen=True)

    name: str
    allowed_lifecycles: frozenset[FlowLifecycle]
    allowed_side_effects: frozenset[SideEffectLevel]
    allow_requires_approval: bool
    force_expose: bool
    error_detail: ErrorDetail
    require_authorizer: bool = False
    require_authenticator: bool = False
    require_rate_limiter: bool = False

    @classmethod
    def strict(cls) -> MCPServerProfile:
        """Least-privilege profile for hostile / multi-tenant exposure."""
        return cls(
            name="strict",
            allowed_lifecycles=frozenset({FlowLifecycle.ACTIVE}),
            allowed_side_effects=frozenset({SideEffectLevel.NONE, SideEffectLevel.READ}),
            allow_requires_approval=False,
            force_expose=False,
            error_detail="generic",
            require_authorizer=True,
            require_authenticator=True,
        )

    @classmethod
    def balanced(cls) -> MCPServerProfile:
        """Sensible defaults for single-tenant internal services."""
        return cls(
            name="balanced",
            allowed_lifecycles=frozenset({FlowLifecycle.ACTIVE}),
            allowed_side_effects=frozenset({SideEffectLevel.NONE, SideEffectLevel.READ}),
            allow_requires_approval=False,
            force_expose=False,
            error_detail="type_only",
        )

    @classmethod
    def trusted_network(cls) -> MCPServerProfile:
        """Broader behaviour for a locked-down, trusted network segment."""
        return cls(
            name="trusted-network",
            allowed_lifecycles=frozenset({FlowLifecycle.ACTIVE, FlowLifecycle.REVIEWED}),
            allowed_side_effects=frozenset(
                {SideEffectLevel.NONE, SideEffectLevel.READ, SideEffectLevel.WRITE}
            ),
            allow_requires_approval=True,
            force_expose=False,
            error_detail="full",
        )

    @classmethod
    def named(cls, name: str) -> MCPServerProfile:
        """Return a built-in profile by name (``strict`` / ``balanced`` / ``trusted-network``)."""
        builders = {
            "strict": cls.strict,
            "balanced": cls.balanced,
            "trusted-network": cls.trusted_network,
        }
        try:
            return builders[name]()
        except KeyError:
            raise ValueError(
                f"Unknown MCP server profile '{name}'. "
                f"Expected one of: {', '.join(sorted(builders))}."
            ) from None

    def diff(self, other: MCPServerProfile) -> dict[str, tuple[Any, Any]]:
        """Return ``{field: (self_value, other_value)}`` for every differing field.

        Sets are normalised to sorted value lists so the output is stable and
        readable in an audit review.
        """

        def _norm(value: Any) -> Any:
            if isinstance(value, frozenset):
                return sorted(getattr(v, "value", v) for v in value)
            return value

        out: dict[str, tuple[Any, Any]] = {}
        for field in type(self).model_fields:
            mine = getattr(self, field)
            theirs = getattr(other, field)
            if mine != theirs:
                out[field] = (_norm(mine), _norm(theirs))
        return out


def evaluate_readiness(
    profile: MCPServerProfile,
    *,
    has_authorizer: bool,
    has_authenticator: bool,
    has_rate_limiter: bool,
    error_detail: ErrorDetail,
    exposed_side_effects: Iterable[SideEffectLevel],
) -> list[ReadinessFinding]:
    """Check a configured server against *profile* and return findings (issue #446).

    Pure and side-effect free so it can be unit-tested directly.  ``error``
    findings are deployment-blocking; ``warning`` / ``info`` are advisory.
    """
    findings: list[ReadinessFinding] = []
    if profile.require_authorizer and not has_authorizer:
        findings.append(
            ReadinessFinding(
                severity="error",
                code="missing-authorizer",
                message=(
                    f"Profile '{profile.name}' requires an authorizer, but none is configured."
                ),
            )
        )
    if profile.require_authenticator and not has_authenticator:
        findings.append(
            ReadinessFinding(
                severity="error",
                code="missing-authenticator",
                message=(
                    f"Profile '{profile.name}' requires an authenticator, but none is configured."
                ),
            )
        )
    if profile.require_rate_limiter and not has_rate_limiter:
        findings.append(
            ReadinessFinding(
                severity="warning",
                code="missing-rate-limiter",
                message=(
                    f"Profile '{profile.name}' recommends a rate limiter, but none is configured."
                ),
            )
        )
    if error_detail != profile.error_detail:
        findings.append(
            ReadinessFinding(
                severity="warning",
                code="error-detail-relaxed",
                message=(
                    f"error_detail is '{error_detail}', looser than profile "
                    f"'{profile.name}' baseline '{profile.error_detail}'."
                ),
            )
        )
    over_ceiling = sorted(
        {se.value for se in exposed_side_effects if se not in profile.allowed_side_effects}
    )
    if over_ceiling:
        findings.append(
            ReadinessFinding(
                severity="error",
                code="side-effects-over-ceiling",
                message=(
                    "Exposed flows have side-effect levels above the profile ceiling: "
                    f"{', '.join(over_ceiling)} (likely force_expose=True)."
                ),
            )
        )
    if not findings:
        findings.append(
            ReadinessFinding(
                severity="info",
                code="ready",
                message=f"Server configuration satisfies profile '{profile.name}'.",
            )
        )
    return findings


# ---------------------------------------------------------------------------
# Per-call request gate wiring the hooks together (private)
# ---------------------------------------------------------------------------


class _RequestGate:
    """Run authenticate → rate-limit → authorize for one MCP call, then redact errors.

    Held by :class:`chainweaver.mcp.FlowServer` and invoked from the synthesized
    tool dispatcher.  All hooks are optional; when none are configured
    :meth:`check` is a no-op and :meth:`render_error` reproduces the historical
    ``"{type}: {message}"`` boundary message.
    """

    def __init__(
        self,
        *,
        authenticator: Authenticator | None = None,
        rate_limiter: RateLimiter | None = None,
        authorizer: AuthorizationCallback | None = None,
        audit_hook: AuditHook | None = None,
        error_detail: ErrorDetail = "full",
        error_redaction: RedactionPolicy | None = None,
    ) -> None:
        self._authenticator = authenticator
        self._rate_limiter = rate_limiter
        self._authorizer = authorizer
        self._audit_hook = audit_hook
        self._error_detail: ErrorDetail = error_detail
        self._error_redaction = error_redaction

    @property
    def has_authenticator(self) -> bool:
        return self._authenticator is not None

    @property
    def has_authorizer(self) -> bool:
        return self._authorizer is not None

    @property
    def has_rate_limiter(self) -> bool:
        return self._rate_limiter is not None

    def _emit(
        self,
        action: Literal["authenticate", "rate_limit", "authorize"],
        decision: Literal["allow", "deny"],
        *,
        flow_name: str,
        mcp_tool_name: str,
        request_id: str,
        caller_id: str | None = None,
        reason_code: str | None = None,
        detail: str | None = None,
    ) -> None:
        event = AuditEvent(
            action=action,
            decision=decision,
            flow_name=flow_name,
            mcp_tool_name=mcp_tool_name,
            request_id=request_id,
            caller_id=caller_id,
            reason_code=reason_code,
            detail=detail,
        )
        if self._audit_hook is not None:
            try:
                self._audit_hook(event)
            except Exception:  # pragma: no cover — audit must never break a call
                _AUDIT_LOGGER.warning("MCP audit hook raised; continuing.", exc_info=True)
        log = _AUDIT_LOGGER.warning if decision == "deny" else _AUDIT_LOGGER.info
        log(
            "MCP %s %s | flow=%s tool=%s caller=%s request=%s reason=%s",
            action,
            decision,
            flow_name,
            mcp_tool_name,
            caller_id,
            request_id,
            reason_code,
        )

    def check(
        self,
        *,
        request_id: str,
        flow_name: str,
        flow_version: str,
        mcp_tool_name: str,
        raw_inputs: Mapping[str, Any],
        safety: ToolSafetyContract | None,
        http_headers: Mapping[str, str],
    ) -> None:
        """Enforce the configured gates, raising the matching typed error on refusal."""
        caller = self._authenticate(
            request_id=request_id,
            flow_name=flow_name,
            flow_version=flow_version,
            mcp_tool_name=mcp_tool_name,
            http_headers=http_headers,
        )
        self._rate_limit(
            caller, request_id=request_id, flow_name=flow_name, mcp_tool_name=mcp_tool_name
        )
        self._authorize(
            caller,
            request_id=request_id,
            flow_name=flow_name,
            flow_version=flow_version,
            mcp_tool_name=mcp_tool_name,
            raw_inputs=raw_inputs,
            safety=safety,
        )

    def _authenticate(
        self,
        *,
        request_id: str,
        flow_name: str,
        flow_version: str,
        mcp_tool_name: str,
        http_headers: Mapping[str, str],
    ) -> CallerIdentity | None:
        if self._authenticator is None:
            return None
        ctx = MCPRequestContext(
            flow_name=flow_name,
            flow_version=flow_version,
            mcp_tool_name=mcp_tool_name,
            http_headers=dict(http_headers),
            request_id=request_id,
        )
        try:
            caller = self._authenticator(ctx)
        except FlowAuthenticationError as exc:
            self._emit(
                "authenticate",
                "deny",
                flow_name=flow_name,
                mcp_tool_name=mcp_tool_name,
                request_id=request_id,
                reason_code=exc.reason_code,
            )
            raise
        except Exception as exc:
            self._emit(
                "authenticate",
                "deny",
                flow_name=flow_name,
                mcp_tool_name=mcp_tool_name,
                request_id=request_id,
                reason_code="unauthenticated",
                detail=f"authenticator raised: {type(exc).__name__}",
            )
            raise FlowAuthenticationError(flow_name) from exc
        if caller is None:
            self._emit(
                "authenticate",
                "deny",
                flow_name=flow_name,
                mcp_tool_name=mcp_tool_name,
                request_id=request_id,
                reason_code="unauthenticated",
            )
            raise FlowAuthenticationError(flow_name)
        self._emit(
            "authenticate",
            "allow",
            flow_name=flow_name,
            mcp_tool_name=mcp_tool_name,
            request_id=request_id,
            caller_id=caller.id,
        )
        return caller

    def _rate_limit(
        self,
        caller: CallerIdentity | None,
        *,
        request_id: str,
        flow_name: str,
        mcp_tool_name: str,
    ) -> None:
        if self._rate_limiter is None:
            return
        caller_id = caller.id if caller is not None else None
        if not self._rate_limiter.acquire(caller, flow_name):
            self._emit(
                "rate_limit",
                "deny",
                flow_name=flow_name,
                mcp_tool_name=mcp_tool_name,
                request_id=request_id,
                caller_id=caller_id,
                reason_code="rate_limited",
            )
            raise RateLimitExceededError(flow_name)
        self._emit(
            "rate_limit",
            "allow",
            flow_name=flow_name,
            mcp_tool_name=mcp_tool_name,
            request_id=request_id,
            caller_id=caller_id,
        )

    def _authorize(
        self,
        caller: CallerIdentity | None,
        *,
        request_id: str,
        flow_name: str,
        flow_version: str,
        mcp_tool_name: str,
        raw_inputs: Mapping[str, Any],
        safety: ToolSafetyContract | None,
    ) -> None:
        if self._authorizer is None:
            return
        caller_id = caller.id if caller is not None else None
        ctx = AuthorizationContext(
            request_id=request_id,
            flow_name=flow_name,
            flow_version=flow_version,
            mcp_tool_name=mcp_tool_name,
            caller=caller,
            input_summary=_DEFAULT_SUMMARY_REDACTION.redact(dict(raw_inputs)),
            safety=safety,
        )
        try:
            raw_decision = self._authorizer.authorize(ctx)
        except FlowAuthorizationError as exc:
            self._emit(
                "authorize",
                "deny",
                flow_name=flow_name,
                mcp_tool_name=mcp_tool_name,
                request_id=request_id,
                caller_id=caller_id,
                reason_code=exc.reason_code,
            )
            raise
        except Exception as exc:
            self._emit(
                "authorize",
                "deny",
                flow_name=flow_name,
                mcp_tool_name=mcp_tool_name,
                request_id=request_id,
                caller_id=caller_id,
                reason_code="forbidden",
                detail=f"authorizer raised: {type(exc).__name__}",
            )
            raise FlowAuthorizationError(flow_name) from exc
        decision = (
            AuthorizationDecision(allowed=raw_decision)
            if isinstance(raw_decision, bool)
            else raw_decision
        )
        if not decision.allowed:
            self._emit(
                "authorize",
                "deny",
                flow_name=flow_name,
                mcp_tool_name=mcp_tool_name,
                request_id=request_id,
                caller_id=caller_id,
                reason_code=decision.reason_code,
                detail=decision.detail,
            )
            raise FlowAuthorizationError(flow_name, decision.reason_code)
        self._emit(
            "authorize",
            "allow",
            flow_name=flow_name,
            mcp_tool_name=mcp_tool_name,
            request_id=request_id,
            caller_id=caller_id,
        )

    def render_error(self, error_type: str | None, error_message: str | None) -> str:
        """Render a failing flow's error for the client per the configured mode."""
        return render_error_detail(
            error_type,
            error_message,
            mode=self._error_detail,
            redaction=self._error_redaction,
        )


__all__ = [
    "GENERIC_ERROR_MESSAGE",
    "AuditEvent",
    "AuditHook",
    "Authenticator",
    "AuthorizationCallback",
    "AuthorizationContext",
    "AuthorizationDecision",
    "AuthorizerCallable",
    "CallerIdentity",
    "ErrorDetail",
    "FixedWindowRateLimiter",
    "MCPRequestContext",
    "MCPServerProfile",
    "RateLimiter",
    "ReadinessFinding",
    "coerce_authorizer",
    "evaluate_readiness",
    "render_error_detail",
]
