# Scoped guidance — `chainweaver/mcp/`

> Root `AGENTS.md` is authoritative and cannot be weakened here; on conflict,
> the root wins — flag and fix the conflict in the same PR. This file adds
> durable local rules only.

## Trust boundary

This package is ChainWeaver's trust boundary in both directions. Changes here
are security-relevant and get the fullest review.

- **Outbound (`server.py`)**: `FlowServer` exposes only flows that pass the
  governance gate by default — active lifecycle plus known read-only,
  approval-free safety. Explicit operator overrides (`flow_names`,
  `force_expose`) must stay explicit, warned, and auditable. Never widen the
  default exposure set.
- **Inbound (`adapter.py`)**: MCP server metadata is **untrusted input**.
  Tool names/descriptions go through `MetadataPolicy` sanitisation;
  annotation-derived safety honours `annotation_trust`; schema-hash pinning
  and `on_drift` handling must not be bypassed or defaulted off.
- **Security seams (`security.py`)**: authentication, authorization,
  rate-limiting, audit events, and `error_detail` redaction are opt-in
  seams; keep failure behavior fail-closed and error details redacted by
  default.

## Package rules

- Requires the `[mcp]` extra: guard third-party imports so the base install
  never hard-depends on `mcp`/FastMCP.
- Enumerate flows through `FlowExecutor.registry` — never reach into
  executor internals.
- Deep-dive: [mcp-integration.md](/docs/agent-context/mcp-integration.md);
  operator-facing rules: [docs/security.md](/docs/security.md).
