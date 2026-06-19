"""FlowServer trust-boundary controls (issues #347, #360, #362, #443, #446)."""

from __future__ import annotations

import asyncio
import re
from typing import Any

import pytest
from mcp.shared.memory import create_connected_server_and_client_session
from pydantic import BaseModel

from chainweaver import (
    Flow,
    FlowAuthenticationError,
    FlowAuthorizationError,
    FlowExecutor,
    FlowGovernance,
    FlowLifecycle,
    FlowRegistry,
    FlowStep,
    RedactionPolicy,
    SideEffectLevel,
    Tool,
    ToolSafetyContract,
)
from chainweaver.mcp import FlowServer
from chainweaver.mcp.security import (
    AuditEvent,
    AuthorizationContext,
    AuthorizationDecision,
    CallerIdentity,
    FixedWindowRateLimiter,
    MCPRequestContext,
    MCPServerProfile,
    ReadinessFinding,
    _RequestGate,
    coerce_authorizer,
    evaluate_readiness,
    render_error_detail,
)


class _NumIn(BaseModel):
    n: int


class _NumOut(BaseModel):
    value: int


def _double(inp: _NumIn) -> dict[str, Any]:
    return {"value": inp.n * 2}


def _boom(inp: _NumIn) -> dict[str, Any]:
    raise RuntimeError("token=abc123 secret at /etc/passwd")


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _ok_executor() -> FlowExecutor:
    registry = FlowRegistry()
    registry.register_flow(
        Flow(
            name="num",
            version="1.0.0",
            description="Double.",
            steps=[FlowStep(tool_name="double", input_mapping={"n": "n"})],
            input_schema_ref=Flow.schema_ref_from(_NumIn),
            output_schema_ref=Flow.schema_ref_from(_NumOut),
            safety=ToolSafetyContract(side_effects=SideEffectLevel.NONE),
        )
    )
    executor = FlowExecutor(registry=registry)
    executor.register_tool(
        Tool(name="double", description="", input_schema=_NumIn, output_schema=_NumOut, fn=_double)
    )
    return executor


def _boom_executor() -> FlowExecutor:
    registry = FlowRegistry()
    registry.register_flow(
        Flow(
            name="boom",
            version="1.0.0",
            description="Fails.",
            steps=[FlowStep(tool_name="boom", input_mapping={"n": "n"})],
            input_schema_ref=Flow.schema_ref_from(_NumIn),
            safety=ToolSafetyContract(side_effects=SideEffectLevel.NONE),
        )
    )
    executor = FlowExecutor(registry=registry)
    executor.register_tool(
        Tool(name="boom", description="", input_schema=_NumIn, output_schema=_NumOut, fn=_boom)
    )
    return executor


def _call(server: FlowServer, tool: str, args: dict[str, Any]) -> Any:
    async def go() -> Any:
        async with create_connected_server_and_client_session(
            server.fastmcp._mcp_server
        ) as client:
            return await client.call_tool(tool, args)

    return _run(go())


def _content_text(result: Any) -> str:
    return " ".join(getattr(c, "text", "") for c in (result.content or []))


# ---------------------------------------------------------------------------
# Authorization (issue #443)
# ---------------------------------------------------------------------------


class TestAuthorization:
    def test_allow_lets_the_call_through(self) -> None:
        server = FlowServer(_ok_executor(), authorizer=lambda ctx: AuthorizationDecision.allow())
        result = _call(server, "num", {"n": 5})
        assert result.isError is False
        assert result.structuredContent == {"value": 10}

    def test_deny_decision_blocks_with_reason_code(self) -> None:
        server = FlowServer(
            _ok_executor(),
            authorizer=lambda ctx: AuthorizationDecision.deny(reason_code="out_of_scope"),
        )
        result = _call(server, "num", {"n": 5})
        assert result.isError is True
        assert "out_of_scope" in _content_text(result)

    def test_bare_bool_false_denies(self) -> None:
        server = FlowServer(_ok_executor(), authorizer=lambda ctx: False)
        result = _call(server, "num", {"n": 5})
        assert result.isError is True
        assert "forbidden" in _content_text(result)

    def test_bare_bool_true_allows(self) -> None:
        server = FlowServer(_ok_executor(), authorizer=lambda ctx: True)
        assert _call(server, "num", {"n": 5}).isError is False

    def test_deny_detail_is_not_sent_to_client(self) -> None:
        server = FlowServer(
            _ok_executor(),
            authorizer=lambda ctx: AuthorizationDecision.deny(
                reason_code="forbidden", detail="caller 42 lacks role billing.admin"
            ),
        )
        text = _content_text(_call(server, "num", {"n": 5}))
        assert "billing.admin" not in text

    def test_authorizer_receives_redacted_input_summary(self) -> None:
        seen: dict[str, Any] = {}

        def authz(ctx: AuthorizationContext) -> AuthorizationDecision:
            seen["summary"] = dict(ctx.input_summary)
            seen["flow"] = ctx.flow_name
            return AuthorizationDecision.allow()

        gate = _RequestGate(authorizer=coerce_authorizer(authz))
        gate.check(
            request_id="r1",
            flow_name="num",
            flow_version="1.0.0",
            mcp_tool_name="num",
            raw_inputs={"n": 5, "api_key": "sk-supersecret"},
            safety=None,
            http_headers={},
        )
        assert seen["flow"] == "num"
        assert seen["summary"]["n"] == 5
        assert seen["summary"]["api_key"] == "***REDACTED***"

    def test_authorizer_raising_is_converted_to_forbidden(self) -> None:
        def authz(ctx: AuthorizationContext) -> AuthorizationDecision:
            raise ValueError("policy backend down")

        gate = _RequestGate(authorizer=coerce_authorizer(authz))
        with pytest.raises(FlowAuthorizationError) as exc_info:
            gate.check(
                request_id="r1",
                flow_name="num",
                flow_version="1.0.0",
                mcp_tool_name="num",
                raw_inputs={"n": 5},
                safety=None,
                http_headers={},
            )
        # The internal "policy backend down" never reaches the client-facing message.
        assert "policy backend down" not in str(exc_info.value)
        assert "forbidden" in str(exc_info.value)

    def test_coerce_authorizer_accepts_object_callable_and_none(self) -> None:
        class Obj:
            def authorize(self, ctx: AuthorizationContext) -> AuthorizationDecision:
                return AuthorizationDecision.allow()

        assert coerce_authorizer(None) is None
        obj = Obj()
        assert coerce_authorizer(obj) is obj
        assert coerce_authorizer(lambda ctx: True) is not None

    def test_coerce_authorizer_rejects_non_callable(self) -> None:
        with pytest.raises(TypeError, match="AuthorizationCallback"):
            coerce_authorizer(object())  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Authentication (issue #362)
# ---------------------------------------------------------------------------


class TestAuthentication:
    def test_identity_allows_and_threads_to_authorizer(self) -> None:
        captured: dict[str, Any] = {}

        def authn(req: MCPRequestContext) -> CallerIdentity:
            return CallerIdentity(id="svc-1", scopes=("read",))

        def authz(ctx: AuthorizationContext) -> bool:
            captured["caller"] = ctx.caller
            return True

        gate = _RequestGate(authenticator=authn, authorizer=coerce_authorizer(authz))
        gate.check(
            request_id="r1",
            flow_name="num",
            flow_version="1.0.0",
            mcp_tool_name="num",
            raw_inputs={"n": 5},
            safety=None,
            http_headers={"authorization": "Bearer x"},
        )
        assert captured["caller"] == CallerIdentity(id="svc-1", scopes=("read",))

    def test_none_identity_denies_end_to_end(self) -> None:
        server = FlowServer(_ok_executor(), authenticator=lambda req: None)
        result = _call(server, "num", {"n": 5})
        assert result.isError is True
        assert "unauthenticated" in _content_text(result)

    def test_authenticator_raising_is_unauthenticated(self) -> None:
        def authn(req: MCPRequestContext) -> CallerIdentity | None:
            raise RuntimeError("token store unreachable")

        gate = _RequestGate(authenticator=authn)
        with pytest.raises(FlowAuthenticationError) as exc_info:
            gate.check(
                request_id="r1",
                flow_name="num",
                flow_version="1.0.0",
                mcp_tool_name="num",
                raw_inputs={"n": 5},
                safety=None,
                http_headers={},
            )
        assert "token store unreachable" not in str(exc_info.value)
        assert "unauthenticated" in str(exc_info.value)


# ---------------------------------------------------------------------------
# Rate limiting (issue #362)
# ---------------------------------------------------------------------------


class TestRateLimiter:
    def test_fixed_window_allows_then_denies(self) -> None:
        clock = {"t": 0.0}
        limiter = FixedWindowRateLimiter(2, 10.0, time_fn=lambda: clock["t"])
        assert limiter.acquire(None, "num") is True
        assert limiter.acquire(None, "num") is True
        assert limiter.acquire(None, "num") is False

    def test_fixed_window_resets_after_window(self) -> None:
        clock = {"t": 0.0}
        limiter = FixedWindowRateLimiter(1, 10.0, time_fn=lambda: clock["t"])
        assert limiter.acquire(None, "num") is True
        assert limiter.acquire(None, "num") is False
        clock["t"] = 10.0
        assert limiter.acquire(None, "num") is True

    def test_per_caller_buckets_are_isolated(self) -> None:
        limiter = FixedWindowRateLimiter(1, 10.0, time_fn=lambda: 0.0)
        a = CallerIdentity(id="a")
        b = CallerIdentity(id="b")
        assert limiter.acquire(a, "num") is True
        assert limiter.acquire(a, "num") is False
        assert limiter.acquire(b, "num") is True

    def test_per_flow_keying(self) -> None:
        limiter = FixedWindowRateLimiter(1, 10.0, per_flow=True, time_fn=lambda: 0.0)
        assert limiter.acquire(None, "flow_a") is True
        assert limiter.acquire(None, "flow_a") is False
        assert limiter.acquire(None, "flow_b") is True

    @pytest.mark.parametrize(("max_calls", "window"), [(0, 10.0), (1, 0.0), (1, -1.0)])
    def test_invalid_config_raises(self, max_calls: int, window: float) -> None:
        with pytest.raises(ValueError):
            FixedWindowRateLimiter(max_calls, window)

    def test_invalid_max_tracked_raises(self) -> None:
        with pytest.raises(ValueError, match="max_tracked"):
            FixedWindowRateLimiter(1, 10.0, max_tracked=0)

    def test_expired_keys_are_evicted_to_bound_memory(self) -> None:
        clock = {"t": 0.0}
        limiter = FixedWindowRateLimiter(
            5, 10.0, per_flow=True, max_tracked=3, time_fn=lambda: clock["t"]
        )
        # Fill three distinct keys inside the window.
        for i in range(3):
            assert limiter.acquire(None, f"flow_{i}") is True
        assert len(limiter._hits) == 3
        # Advance past the window so all three are now expired, then add a new
        # key: the sweep reclaims the stale entries instead of growing forever.
        clock["t"] = 20.0
        assert limiter.acquire(None, "flow_new") is True
        assert len(limiter._hits) == 1
        assert ("anonymous", "flow_new") in limiter._hits

    def test_throttled_call_blocks_end_to_end(self) -> None:
        limiter = FixedWindowRateLimiter(1, 60.0)
        server = FlowServer(_ok_executor(), rate_limiter=limiter)
        assert _call(server, "num", {"n": 5}).isError is False
        throttled = _call(server, "num", {"n": 5})
        assert throttled.isError is True
        assert "rate_limited" in _content_text(throttled)


# ---------------------------------------------------------------------------
# Error redaction at the boundary (issue #347)
# ---------------------------------------------------------------------------


class TestErrorRedaction:
    def test_full_mode_is_the_default(self) -> None:
        assert render_error_detail("RuntimeError", "boom") == "RuntimeError: boom"

    def test_type_only_explicit(self) -> None:
        assert render_error_detail("RuntimeError", "secret", mode="type_only") == "RuntimeError"

    def test_generic_mode_is_fixed(self) -> None:
        out = render_error_detail("RuntimeError", "secret /etc/passwd", mode="generic")
        assert "secret" not in out
        assert "/etc/passwd" not in out

    def test_full_mode_applies_redaction_policy(self) -> None:
        policy = RedactionPolicy(redact_pattern=re.compile(r"token=\S+"))
        out = render_error_detail(
            "RuntimeError", "token=abc123 failed", mode="full", redaction=policy
        )
        assert "abc123" not in out
        assert "RuntimeError" in out

    def test_generic_mode_hides_failure_end_to_end(self) -> None:
        server = FlowServer(_boom_executor(), error_detail="generic")
        text = _content_text(_call(server, "boom", {"n": 1}))
        assert "abc123" not in text
        assert "/etc/passwd" not in text

    def test_full_mode_still_surfaces_detail_end_to_end(self) -> None:
        server = FlowServer(_boom_executor())  # default error_detail="full"
        assert "abc123" in _content_text(_call(server, "boom", {"n": 1}))


# ---------------------------------------------------------------------------
# Audit events (issues #362, #443)
# ---------------------------------------------------------------------------


class TestAudit:
    def test_allow_and_deny_emit_events(self) -> None:
        events: list[AuditEvent] = []
        gate = _RequestGate(
            authenticator=lambda req: CallerIdentity(id="svc"),
            authorizer=coerce_authorizer(
                lambda ctx: AuthorizationDecision.deny(reason_code="nope")
            ),
            audit_hook=events.append,
        )
        with pytest.raises(FlowAuthorizationError):
            gate.check(
                request_id="req-1",
                flow_name="num",
                flow_version="1.0.0",
                mcp_tool_name="num",
                raw_inputs={"n": 5},
                safety=None,
                http_headers={},
            )
        assert [(e.action, e.decision) for e in events] == [
            ("authenticate", "allow"),
            ("authorize", "deny"),
        ]
        deny = events[-1]
        assert deny.reason_code == "nope"
        assert deny.caller_id == "svc"
        assert deny.request_id == "req-1"

    def test_audit_hook_exception_does_not_break_the_call(self) -> None:
        def bad_hook(event: AuditEvent) -> None:
            raise RuntimeError("sink down")

        gate = _RequestGate(authorizer=coerce_authorizer(lambda ctx: True), audit_hook=bad_hook)
        # Must not raise despite the hook blowing up.
        gate.check(
            request_id="r",
            flow_name="num",
            flow_version="1.0.0",
            mcp_tool_name="num",
            raw_inputs={"n": 5},
            safety=None,
            http_headers={},
        )


# ---------------------------------------------------------------------------
# Production profiles (issue #446)
# ---------------------------------------------------------------------------


class TestProfiles:
    def test_strict_profile_values(self) -> None:
        p = MCPServerProfile.strict()
        assert p.error_detail == "generic"
        assert p.allowed_side_effects == frozenset({SideEffectLevel.NONE, SideEffectLevel.READ})
        assert p.require_authorizer is True
        assert p.require_authenticator is True
        assert p.force_expose is False

    def test_trusted_network_allows_write_and_approval(self) -> None:
        p = MCPServerProfile.trusted_network()
        assert SideEffectLevel.WRITE in p.allowed_side_effects
        assert p.allow_requires_approval is True
        assert FlowLifecycle.REVIEWED in p.allowed_lifecycles

    def test_named_lookup_and_unknown(self) -> None:
        assert MCPServerProfile.named("balanced").name == "balanced"
        assert MCPServerProfile.named("trusted-network").name == "trusted-network"
        with pytest.raises(ValueError, match="Unknown MCP server profile"):
            MCPServerProfile.named("nope")

    def test_diff_reports_changed_fields(self) -> None:
        diff = MCPServerProfile.strict().diff(MCPServerProfile.trusted_network())
        assert diff["error_detail"] == ("generic", "full")
        assert "allowed_side_effects" in diff
        assert "allow_requires_approval" in diff

    def test_profile_supplies_defaults_to_flow_server(self) -> None:
        server = FlowServer(_ok_executor(), profile=MCPServerProfile.strict())
        assert server.error_detail == "generic"
        assert server.allowed_side_effects == frozenset(
            {SideEffectLevel.NONE, SideEffectLevel.READ}
        )

    def test_explicit_argument_overrides_profile(self) -> None:
        server = FlowServer(_ok_executor(), profile=MCPServerProfile.strict(), error_detail="full")
        assert server.error_detail == "full"


class TestReadiness:
    def test_no_profile_returns_info(self) -> None:
        report = FlowServer(_ok_executor()).readiness_report()
        assert [f.code for f in report] == ["no-profile"]

    def test_strict_without_hooks_is_not_ready(self) -> None:
        server = FlowServer(_ok_executor(), profile=MCPServerProfile.strict())
        report = server.readiness_report()
        codes = {f.code for f in report if f.severity == "error"}
        assert "missing-authorizer" in codes
        assert "missing-authenticator" in codes

    def test_strict_with_hooks_is_ready(self) -> None:
        server = FlowServer(
            _ok_executor(),
            profile=MCPServerProfile.strict(),
            authenticator=lambda req: CallerIdentity(id="svc"),
            authorizer=lambda ctx: True,
        )
        report = server.readiness_report()
        assert all(f.severity != "error" for f in report)
        assert any(f.code == "ready" for f in report)

    def test_force_expose_over_ceiling_is_flagged(self) -> None:
        registry = FlowRegistry()
        registry.register_flow(
            Flow(
                name="writer",
                description="Writes.",
                steps=[FlowStep(tool_name="double")],
                governance=FlowGovernance(lifecycle=FlowLifecycle.REVIEWED),
                safety=ToolSafetyContract(side_effects=SideEffectLevel.WRITE),
            )
        )
        executor = FlowExecutor(registry=registry)
        executor.register_tool(
            Tool(
                name="double",
                description="",
                input_schema=_NumIn,
                output_schema=_NumOut,
                fn=_double,
            )
        )
        server = FlowServer(
            executor,
            flow_names=["writer"],
            force_expose=True,
            profile=MCPServerProfile.strict(),
            authenticator=lambda req: CallerIdentity(id="svc"),
            authorizer=lambda ctx: True,
        )
        codes = {f.code for f in server.readiness_report() if f.severity == "error"}
        assert "side-effects-over-ceiling" in codes

    def test_evaluate_readiness_is_pure(self) -> None:
        findings = evaluate_readiness(
            MCPServerProfile.balanced(),
            has_authorizer=False,
            has_authenticator=False,
            has_rate_limiter=False,
            error_detail="type_only",
            exposed_side_effects=[SideEffectLevel.READ],
        )
        assert findings == [
            ReadinessFinding(
                severity="info",
                code="ready",
                message="Server configuration satisfies profile 'balanced'.",
            )
        ]
