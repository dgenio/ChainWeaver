# Security Posture

> Reference document for ChainWeaver's security posture and recommended
> production configuration.  Skim this before deploying ChainWeaver in any
> environment that handles credentials, PII, or other sensitive data.

---

## What ChainWeaver does — and does not — do

ChainWeaver is a deterministic in-process orchestration layer.  It deliberately
omits behaviours that would expand its security surface:

| ChainWeaver does NOT… | …because |
|---|---|
| Make any LLM or AI client calls in `executor.py` | Hard executor invariant 1 |
| Perform network I/O in `executor.py` | Hard executor invariant 2 |
| Use randomness in `executor.py` | Hard executor invariant 3 (jitter is opt-in inside `flow.py`'s `RetryPolicy`) |
| Persist data, logs, or traces by default | The library is in-memory; persistence is the application's choice |
| Send telemetry | The library has no outbound calls |
| Pull additional dependencies at runtime | The runtime deps are limited to `pydantic`, `tenacity`, `typer`, and `packaging` |

Network I/O — when needed — happens inside individual `Tool.fn` callables
that the application registers, not in the executor itself.

---

## What ChainWeaver logs

`chainweaver/log_utils.py` emits structured log records via the standard
library `logging` module under the `chainweaver` logger namespace.

| Log point | Default contents |
|---|---|
| `Step <i> START` | step index, tool name, fully resolved input dict |
| `Step <i> END` | step index, tool name, output dict |
| `Step <i> ERROR` | step index, tool name, exception class + message |
| Flow `started`, `aborted at step`, `completed successfully` | flow name, trace id |

Log handlers are **not** attached by ChainWeaver.  A
`logging.NullHandler` is registered on the package logger so the application
controls verbosity, format, and destination via `logging.basicConfig`,
`logging.config.dictConfig`, or any other mechanism.

---

## Redaction (`RedactionPolicy`)

When tool inputs or outputs may carry secrets or PII, configure a
`RedactionPolicy` on the executor.  Redaction is applied to the log
output only — the raw values remain in the in-memory `ExecutionResult`
trace so authorized callers can still inspect what happened.

```python
import re
from chainweaver import FlowExecutor, RedactionPolicy

policy = RedactionPolicy(
    # Override the defaults if you want a different set:
    # redact_keys=frozenset({"password", "token", "ssn", ...}),
    redact_pattern=re.compile(r"sk-\w+"),  # OpenAI-style keys appearing in values
    max_value_length=200,                  # truncate long values in logs
)
executor = FlowExecutor(registry=registry, redaction_policy=policy)
```

**Defaults** (`DEFAULT_REDACT_KEYS`): `password`, `token`, `api_key`, `apikey`,
`secret`, `authorization`.  Matching is case-insensitive.  Redaction is
applied recursively to nested dicts and lists.

> **Trace fields are stored raw on purpose.**  Treat the `ExecutionResult`
> object as you would treat any other in-memory structure carrying tool
> data: don't serialize it to disk or send it across the network without an
> explicit decision about which fields are safe to expose.

---

## Execution-time safety enforcement (#356)

By default a `ToolSafetyContract` is **advisory** — the executor records it but
does not act on it.  Three opt-in `FlowExecutor` controls make it actionable for
hosts that expose flows to LLM clients, all behaviour-preserving when unset:

```python
from chainweaver import FlowExecutor, ApprovalContext, ApprovalDecision, SideEffectLevel

def approver(ctx: ApprovalContext) -> ApprovalDecision:
    # ctx carries trace_id, flow_name, step_index, tool_name, redacted inputs,
    # and the effective ToolSafetyContract.
    return ApprovalDecision.APPROVE if ctx.tool_name in TRUSTED else ApprovalDecision.DENY

executor = FlowExecutor(
    registry,
    approval_callback=approver,                       # gate requires_approval=True steps
    strict_safety=True,                               # refuse such steps if no callback
    max_side_effect_level=SideEffectLevel.WRITE,      # refuse DESTRUCTIVE/EXTERNAL-over-ceiling
)
```

* A step whose **effective contract** has `requires_approval=True` invokes the
  callback *before* the tool runs.  `DENY`, a callback exception, or an invalid
  return aborts the step with `ApprovalDeniedError` and a failed `StepRecord`;
  the decision is recorded on `StepRecord.approval`.
* With **no** callback registered, the default is unchanged (the step runs);
  `strict_safety=True` instead refuses approval-requiring steps.
* `max_side_effect_level` refuses any step whose `side_effects` exceeds the
  ceiling with `SafetyCeilingError`.
* The callback is a **user-supplied seam** — the executor never performs I/O
  itself, so the no-LLM / no-network / no-randomness invariants are preserved
  (the same model as `decision_callback`).  Enforcement applies on both the sync
  and async lanes.
* A step's `on_error="fallback:<tool_name>"` target is subject to the **same
  gate** as the primary tool (issue #486) — a fallback declaring
  `requires_approval=True` or exceeding `max_side_effect_level` is refused,
  not run ungated, and a side-effecting fallback with no `dry_run_fn` is
  stubbed rather than invoked under `dry_run=True` (sync lane only — the async
  lane has no dry-run mode).
* A `RetryPolicy` attached to a step whose tool declares `safe_to_retry=False`
  (or is non-idempotent and side-effecting) is **not honoured** under
  `strict_safety=True` (issue #488): the tool is invoked once, not retried,
  to avoid duplicating an uncertain side effect. `compile_flow` additionally
  emits a non-blocking `unsafe_retry` warning for this combination regardless
  of `strict_safety`.

## Dry-run rehearsals (#357)

`execute_flow(dry_run=True)` runs a side-effect-free rehearsal that validates
wiring and data shapes against real systems without committing side effects:

```python
deploy = Tool(name="deploy", fn=do_deploy, dry_run_fn=plan_deploy,
              safety=ToolSafetyContract(side_effects=SideEffectLevel.EXTERNAL,
                                        supports_dry_run=True))
result = executor.execute_flow("release", inputs, dry_run=True)
assert result.dry_run is True
```

* Read-only steps (`side_effects` in `NONE`/`READ`) run normally; tools that
  declare a `dry_run_fn` (and `supports_dry_run=True`) run it; other
  side-effecting steps are **skipped** (stubbed) by default, or fail the step
  under `dry_run_unsupported="abort"` for a high-fidelity rehearsal.
* The step cache and checkpointer are **bypassed** so a rehearsal never reads or
  writes real state, and `ExecutionResult.dry_run` is set so a dry-run trace can
  never be confused with a real run.  Composed sub-flows inherit the mode.

## Loading flow files from untrusted sources (#345, #416)

Flow files (`.flow.yaml` / `.flow.json`) are the primary **untrusted input
surface**: they arrive from repositories, contributor PRs validated by the
GitHub Action, and generated drafts. Two independent hardening layers apply.

### Parse-size and structural guardrails (#416)

Every deserialization entry point (`flow_from_json`, `flow_from_yaml`,
`flow_from_dict`, and the CLI loaders) applies conservative
`FlowParseLimits` — a maximum input size, node count, nesting depth, string
length, and step count. A file that exceeds any limit fails fast with a
`FlowSerializationError` naming the limit, *before* the structure is fully
realized, so a hostile file (a giant string, deeply nested mapping, or YAML
alias/anchor expansion) cannot exhaust memory or CPU. The defaults are well
above realistic flows; override with `limits=` (or `FlowParseLimits.unlimited()`
for fully trusted input):

```python
from chainweaver import FlowParseLimits, flow_from_yaml

flow = flow_from_yaml(text, limits=FlowParseLimits(max_bytes=1_000_000))
```

### Schema-ref module-resolution allowlist (#345)

Schema refs (`input_schema_ref`, `output_schema_ref`, `context_schema_ref`) and
`RetryPolicy.retryable_errors` resolve `"module:qualname"` strings by importing
the module half — and **importing a module runs its top-level code**. Install an
allowlist so a flow from a semi-trusted source can only reference modules you
permit; a rejected ref raises `SchemaRefPolicyError` **before** any import:

```python
from chainweaver import SchemaRefAllowlist, schema_ref_policy, flow_from_yaml

with schema_ref_policy(SchemaRefAllowlist(["myapp.schemas"])):
    flow = flow_from_yaml(text)            # resolving a non-allowlisted ref raises
```

`set_schema_ref_policy(...)` installs a process-wide policy (the `chainweaver
run` / `serve` CLIs expose this as `--schema-ref-allow PREFIX`); the default is
permissive for backward compatibility. The policy is held in a `ContextVar`, so
it is isolated per thread / async task. Even with an allowlist, treat untrusted
flow payloads with the same caution as untrusted `pickle` input.

## Trusting MCP-imported tool metadata (#358, #359, #371)

Tools wrapped from a remote MCP server arrive as **untrusted input**: their
names, descriptions, schemas, and annotations are server-declared and travel on
into `Tool` objects, re-exports, and proposer prompts.  `MCPToolAdapter` applies
conservative defaults:

```python
from chainweaver.mcp import MCPToolAdapter, MetadataPolicy

adapter = MCPToolAdapter(
    session,
    annotation_trust="cap",          # derive a conservative ToolSafetyContract (#371)
    metadata_policy=MetadataPolicy(),# sanitise names/descriptions (#359)
    on_drift="error",                # reject changed pinned schemas (#358)
    server_name="search-tools",
)
tools = await adapter.discover_tools(pins_path=".chainweaver/mcp-pins.json")
```

* **Annotations → contract (#371):** `readOnlyHint → READ` (never `NONE` — a
  remote call still observes the world), `destructiveHint → DESTRUCTIVE`,
  unannotated → `EXTERNAL`; remote `determinism_level` is always `NONE`.
  `annotation_trust` is `"cap"` (conservative, default), `"trust"` (declared
  only), or `"ignore"`.  The contract source is recorded on `tool.metadata`.
* **Metadata policy (#359):** control characters stripped, whitespace
  normalised, descriptions length-capped, names validated against
  `^[A-Za-z0-9._-]+$`; `description_mode="placeholder"` drops remote text
  entirely.  The raw server description is preserved on
  `tool.metadata["mcp_raw_description"]` for audit.  `MetadataPolicy.permissive()`
  restores the pre-hardening verbatim behaviour for a fully trusted server.
* **Schema pinning (#358):** each tool's raw JSON Schema is fingerprinted at
  discovery (`tool.metadata["mcp_schema_hash"]`); supply `pins` / `pins_path`
  (write one with `build_pin_file`) and a changed schema is handled per
  `on_drift` (`"error"` / `"warn"` / `"accept"`).

> These controls verify **declared** metadata and schemas, not remote
> *behaviour*.  Keep human review in your promotion workflow; a server can
> still change what a tool *does* without changing its schema.

---

## Hardening `FlowServer` for network exposure (#347, #360, #362, #443, #446)

`FlowServer` turns governed flows into MCP tools. Over **stdio** it inherits the
host process's trust boundary, but **SSE / streamable-HTTP** turns flows into a
network service. The server exposes first-class trust-boundary seams — it never
performs authentication or authorization policy itself; it only *calls*
host-supplied hooks, keeping policy in your trust boundary.

```python
from chainweaver.mcp import (
    FlowServer,
    MCPServerProfile,
    AuthorizationDecision,
    FixedWindowRateLimiter,
)

def authenticate(req):
    token = req.http_headers.get("authorization", "")
    identity = verify_bearer(token)          # your code; raise/return None to refuse
    return identity                           # a CallerIdentity

def authorize(ctx):
    if "flows:run" not in (ctx.caller.scopes if ctx.caller else ()):
        return AuthorizationDecision.deny(reason_code="out_of_scope")
    return AuthorizationDecision.allow()

server = FlowServer(
    executor,
    profile=MCPServerProfile.strict(),                 # secure defaults (#446)
    authenticator=authenticate,                        # #362
    rate_limiter=FixedWindowRateLimiter(60, 60.0),     # #362
    authorizer=authorize,                              # #443
    audit_hook=emit_to_siem,                           # allow/deny audit
)
for finding in server.readiness_report():              # fail the deploy on errors
    assert finding.severity != "error", finding.message
server.serve(transport="streamable-http")
```

* **Authentication (#362):** `authenticator` resolves a `CallerIdentity` from an
  `MCPRequestContext` (HTTP headers are populated best-effort per call).
  Returning `None` or raising refuses the call with `FlowAuthenticationError`
  before any step runs. `FixedWindowRateLimiter` provides basic abuse
  protection; supply a shared-store `RateLimiter` for multi-replica serving.
* **Authorization (#443):** `authorizer` makes a per-call allow/deny decision
  with the flow name, a **redacted** input summary, the caller, and a request
  id. A deny raises `FlowAuthorizationError` carrying only the client-safe
  `reason_code`; any `detail` goes to the audit hook and logs, never the client.
* **Uniform governance (#360):** the lifecycle / owner / side-effect / approval
  filters apply to **explicitly named** flows too. Bypassing them is a
  deliberate, reviewable `force_expose=True` rather than an easy-to-miss log line.
* **Error redaction (#347):** `error_detail` controls how much of a failing
  flow's error reaches the client — `"full"` (default), `"type_only"`, or
  `"generic"` (a fixed message). `error_redaction=RedactionPolicy(...)` scrubs the
  message text under `"full"`.
* **Profile packs (#446):** `MCPServerProfile.strict()` /
  `.balanced()` / `.trusted_network()` bundle secure defaults; explicit
  arguments always override the profile. `profile.diff(other)` supports audit
  reviews and `server.readiness_report()` flags missing required hooks or
  side-effects exposed above the profile ceiling.

| Profile | Lifecycles | Side effects | Approval flows | Error detail | Requires |
|---|---|---|---|---|---|
| `strict` | ACTIVE | none / read | excluded | `generic` | authorizer + authenticator |
| `balanced` | ACTIVE | none / read | excluded | `type_only` | — |
| `trusted-network` | ACTIVE, REVIEWED | up to write | allowed | `full` | — |

> These hooks gate **who may call** a flow and **what leaks back**. They do not
> change the executor's determinism guarantees, and they delegate the actual
> identity / policy decision to your host — wire them to your existing auth stack.

---

## Recommendations for production

1. **Always configure a `RedactionPolicy`** for flows whose tools handle
   credentials, PII, or PHI — even if you "trust" the upstream
   sanitization.  Defense in depth.
2. **Use the trace ID** (`ExecutionResult.trace_id`) as the correlator
   between log lines and any external logging or tracing system you
   forward records to.
3. **Set `max_output_size` on tools** that fetch arbitrary external data
   (HTTP, database queries) to bound the log volume and the in-memory
   trace.  See issue #43 — `Tool(timeout_seconds=..., max_output_size=...)`.
4. **Avoid logging the full raw trace** to long-term storage.  If you
   must persist execution data, redact first via
   `RedactionPolicy.redact(...)` on the inputs/outputs you care about, or
   serialize a derived/projected form.
5. **Keep tool functions side-effect-aware.**  ChainWeaver's executor is
   deterministic, but your tools may not be (network, files, databases).
   Apply your own least-privilege practices to tool implementations —
   limit credentials they can read, don't log secrets inside the
   function body, prefer scoped service accounts.
6. **Pin runtime dependencies.**  `pydantic`, `tenacity`, `typer`, and
   `packaging` are the runtime dependencies; all four are well-maintained,
   but pinning protects against supply-chain regressions.
7. **Harden network-exposed `FlowServer`s.**  When serving over SSE /
   streamable-HTTP, start from `MCPServerProfile.strict()`, wire an
   `authenticator` and `authorizer`, set a `rate_limiter`, prefer
   `error_detail="generic"`, and gate the deploy on `readiness_report()`.
   See [Hardening `FlowServer` for network exposure](#hardening-flowserver-for-network-exposure-347-360-362-443-446).

---

## Reporting a security issue

Open a GitHub issue using the bug-report form, or contact the
maintainers privately if the issue is sensitive.  Do not include
proof-of-concept exploits or production secrets in public issues.
