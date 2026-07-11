# Internal MCP platform governance with contextweaver + ChainWeaver

> Operational guide for issue #290. Reframed (per the batch red-team) to
> document **what exists today** and clearly mark **planned** capabilities,
> rather than describing the full end-to-end workflow before its pieces ship —
> the acceptance criteria's "complete workflow" spans open, unimplemented issues
> (#284 telemetry ingest, #285 decision engine, #289 capability reports) parked
> in milestone 4.3.
>
> **Date:** 2026-07-11 · **Method:** grounded in the current ChainWeaver
> surface (`FlowServer`, governance lifecycle, the traces subsystem) and the
> contextweaver interop adapters.
> **Status tags:** *Available* = shippable with today's code; *Planned (#N)* =
> depends on an open issue; do not build a runbook on it yet.

## 1. The two-layer value proposition

For internal MCP platform teams the split is:

- **contextweaver** — the gateway / telemetry layer in front of internal MCP
  servers (routing, capability catalog, usage telemetry).
- **ChainWeaver** — the analysis / governance / recommendation layer that turns
  repeated, deterministic tool paths into compiled, reviewable flows.

ChainWeaver integrates with the Weaver Stack today via
`chainweaver.integrations.weaver_spec` (`flow_to_selectable_item`) and
`chainweaver.integrations.contextweaver` (`RoutingDecisionAdapter`). *Available.*

## 2. What you can operate today (*Available*)

1. **Expose governed flows as MCP tools.** Stand up a `FlowServer`
   (`chainweaver.mcp.FlowServer`) over `stdio` or a network transport to serve
   registered flows to MCP clients, with the trust-boundary controls documented
   in `docs/security.md` (authn/authz hooks, rate limiting, error-detail
   redaction, readiness report). *Available.*
2. **Govern the flow lifecycle.** Use `FlowGovernance` / `FlowLifecycle`
   (proposal → review → promotion) and `FlowRegistry` status transitions
   (`ACTIVE` / `NEEDS_REVIEW` / `DISABLED`) to control which flows are
   executable. Copy-on-write state transitions (#335) keep shared references
   safe. *Available.*
3. **Ingest coding-agent traces.** The `chainweaver.traces` subsystem
   (`load_agent_trace`, `score_candidate`, `draft_flow_from_candidate`,
   `backtest_flow`) turns recorded tool traces into scored macro-flow
   candidates offline, and `chainweaver record` / `chainweaver traces` expose
   this on the CLI. *Available.*
4. **Persist traces safely.** Redact before persistence with
   `RedactionPolicy.recommended()` and a `TraceStore` (issue #292) so platform
   telemetry retained for analysis never carries raw secrets/PII. *Available.*
5. **Discover mapping candidates.** `ChainAnalyzer.suggest_schema_mappings`
   (issue #295) surfaces reviewable producer→consumer edges across catalog tools
   whose fields differ only by naming/typing. *Available.*

## 3. The target end-to-end workflow (mixed status)

The platform-governance loop the issue envisions, annotated by what is real:

| Step | Status |
|------|--------|
| Deploy contextweaver in front of internal MCP servers | contextweaver-side (out of ChainWeaver scope) |
| Add ownership / domain / risk / lifecycle metadata to catalogs | Partly *Available* via `capability_id` + `FlowGovernance`; richer catalog metadata is contextweaver-side |
| Export gateway telemetry | **Planned (#284)** — gateway-telemetry ingest not yet built |
| Import telemetry into ChainWeaver as usage traces | **Planned (#284)** |
| Decide macro-flow vs new atomic tool vs improve / deprecate / consolidate | **Planned (#285)** — the decision engine |
| Generate new-tool proposals from cross-server usage | **Planned (#286)** |
| Recommend deprecations / consolidation | **Planned (#287)** |
| Analyze output-shape quality / repair patterns | **Planned (#288)** |
| Generate capability-intelligence reports for platform teams | **Planned (#289)** |
| Review and promote recommendations | *Available* (governance lifecycle) once the recommendations upstream exist |
| Monitor adoption and cleanup | Partly *Available* via OpenTelemetry metrics (#435) for executed flows; adoption analytics is **Planned (#284/#289)** |

## 4. Recommended interim workflow (*Available* only)

Until the 4.3 telemetry/decision pieces land, a platform team can already run a
useful governance loop:

1. Record coding-agent / gateway tool traces to JSONL.
2. `chainweaver record` (or the `traces` subsystem) to mine and score
   candidate flows offline.
3. Human review; promote via the governance lifecycle to `ACTIVE`.
4. Serve promoted flows through `FlowServer` with the `docs/security.md`
   hardening profile.
5. Persist redacted execution traces via a `TraceStore`; watch aggregate
   health with the OpenTelemetry metrics middleware (#435).

## 5. Open questions / could not determine

- The exact contextweaver telemetry schema for #284 ingest — *Could not
  determine* here; it is the contract that unblocks the planned rows above.
- Whether capability-intelligence reports (#289) render in ChainWeaver or in
  contextweaver's UI — a 4.3 design decision.
