"""MCP (Model Context Protocol) integration for ChainWeaver.

Two complementary surfaces ship in this package, both built on top of
the official ``mcp`` Python SDK (FastMCP):

* :class:`chainweaver.mcp.MCPToolAdapter` — wraps tools advertised by
  an MCP server as ChainWeaver :class:`~chainweaver.tools.Tool` objects
  so they can be composed into flows (issues #70, #150).
* :class:`chainweaver.mcp.FlowServer` — exposes registered ChainWeaver
  flows as MCP tools so MCP-aware agents see each compiled flow as a
  single deterministic call (issue #72).

Both rely on the new async executor lane added by issue #80
(:meth:`chainweaver.executor.FlowExecutor.execute_flow_async`).

Optional extra
--------------

Install with the ``mcp`` extra::

    pip install 'chainweaver[mcp]'

The submodules guard the third-party import so missing extras raise a
clear ``ImportError`` instead of a generic ``ModuleNotFoundError``.
"""

from __future__ import annotations

from chainweaver.mcp._schema import jsonschema_to_pydantic, pydantic_to_jsonschema
from chainweaver.mcp.adapter import (
    AnnotationTrust,
    DriftPolicy,
    MCPToolAdapter,
    MetadataPolicy,
    build_pin_file,
    load_pins,
)
from chainweaver.mcp.security import (
    AuditEvent,
    AuditHook,
    Authenticator,
    AuthorizationCallback,
    AuthorizationContext,
    AuthorizationDecision,
    AuthorizerCallable,
    CallerIdentity,
    ErrorDetail,
    FixedWindowRateLimiter,
    MCPRequestContext,
    MCPServerProfile,
    RateLimiter,
    ReadinessFinding,
    coerce_authorizer,
    evaluate_readiness,
    render_error_detail,
)
from chainweaver.mcp.server import FlowServer, TransportName

__all__ = [
    "AnnotationTrust",
    "AuditEvent",
    "AuditHook",
    "Authenticator",
    "AuthorizationCallback",
    "AuthorizationContext",
    "AuthorizationDecision",
    "AuthorizerCallable",
    "CallerIdentity",
    "DriftPolicy",
    "ErrorDetail",
    "FixedWindowRateLimiter",
    "FlowServer",
    "MCPRequestContext",
    "MCPServerProfile",
    "MCPToolAdapter",
    "MetadataPolicy",
    "RateLimiter",
    "ReadinessFinding",
    "TransportName",
    "build_pin_file",
    "coerce_authorizer",
    "evaluate_readiness",
    "jsonschema_to_pydantic",
    "load_pins",
    "pydantic_to_jsonschema",
    "render_error_detail",
]
