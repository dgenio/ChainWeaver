# Runtime Responsibilities for ChainWeaver Hosts

ChainWeaver is a **library**, not a runtime.  `FlowExecutor` runs one flow
when you call `execute_flow()` and returns.  Everything *around* that call
— deciding *when* to run, *what to log*, *what to do with the result*,
*how to handle side effects* — is the responsibility of the host
application that embeds ChainWeaver.

This page tells host authors which of those responsibilities ChainWeaver
explicitly does **not** assume, and how to discharge them in practice.

> **Audience.** Engineers wrapping ChainWeaver behind an HTTP service, an
> MCP server, an agent loop, a CLI batch runner, or any other process
> that imports `chainweaver` and calls `FlowExecutor.execute_flow()`.

---

## 1. Deciding when to invoke a flow

ChainWeaver does **not** decide when a flow should run.  It does not
listen for triggers, schedule itself, or watch external state.

What the host owns:

- Matching the agent's request (or queue message, or HTTP body) to a
  registered `Flow` name.  `FlowRegistry.match_flow_by_intent()` is a
  basic substring match — augment it or replace it with a real router
  for production traffic.
- Validating that the caller is allowed to run *this* flow.  ChainWeaver
  does not authenticate or authorise — `executor.execute_flow()` runs
  whatever you pass it.
- Rate-limiting, queueing, and back-pressure.  ChainWeaver runs as fast
  as its tools and will happily saturate downstream systems if you let
  it.

The reference path is: *host receives a request → host picks a flow
name → host calls `execute_flow(name, initial_input)`*.  Everything
before the arrow is host territory.

---

## 2. Treating stored execution traces

`ExecutionResult` contains `execution_log: list[StepRecord]` with full
inputs and outputs.  ChainWeaver does not persist these — the host
decides where they go.

What the host owns:

- **Storage lifecycle.** Pick a backend (database, object store,
  append-only log).  Set a retention policy.  Encrypt at rest if the
  tool outputs include sensitive data.
- **Redaction.** Use `chainweaver.RedactionPolicy` *before* persisting
  if the inputs or outputs contain secrets, PII, or anything else you
  don't want in your trace store.  ChainWeaver does not redact by
  default — `StepRecord.inputs` and `StepRecord.outputs` are recorded
  verbatim.
- **Index and search.** Decide whether traces are queried by
  `trace_id`, `flow_name`, `flow_version`, time range, or correlation
  ID.  ChainWeaver provides the fields; the host indexes them.
- **Replay correctness.** If the host promises "we can replay any past
  run," it must guarantee that the same flow version and tool versions
  are still loadable.  `Flow.tool_schema_hashes` and
  `chainweaver doctor --check-drift` are the seams for that guarantee.

The host's storage backend is what gives `ExecutionResult.trace_id` its
durable meaning.  ChainWeaver only generates the UUID.

---

## 3. Describing tools with side effects

`Tool` does not distinguish read-only tools from tools that mutate the
world.  As far as `FlowExecutor` is concerned, every tool is a pure
function from `inputs → outputs`.  In reality, your `send_email` tool
sends email.

What the host owns:

- **Idempotency.** If a flow may be retried (by the executor's tool
  retry policy, by your service's request-retry policy, or by a human
  hitting "rerun"), the host's side-effect tools must be safe to
  invoke more than once with the same inputs.  Use idempotency keys,
  conditional writes, or upserts as appropriate.
- **Dry-run and preview modes.** Many hosts want a "show what this
  flow would do" mode.  Implement it inside the tool (an `dry_run:
  bool` field in the input schema) or by registering two variants and
  selecting at flow-build time.  ChainWeaver does not provide a
  framework-level dry-run flag.
- **Approval gates.** If a step must wait for human approval, encode
  that as an upstream tool that blocks until approved — *outside* the
  flow.  Do not embed approval logic in a ChainWeaver step; the
  executor's wall-clock budget is the only knob it offers for waiting.
- **Documentation.** Use the tool's `description` (which appears in
  every introspection surface, including MCP listings) to declare
  side-effect semantics so downstream agents and reviewers can audit
  what a flow will actually do when invoked.

This split — pure executor, host-described side effects — is what
makes ChainWeaver's "no LLM between steps" guarantee meaningful at
runtime: the executor is deterministic only if the *tools* are
deterministic in the way the host claims they are.

---

## 4. Treating compiled flows as higher-level operations

Once a `Flow` is registered, the host should present it to the rest of
its system as a **single named operation**, not as "a sequence of N
tool calls".  This is the whole point of compiling tool chains into
flows.

What the host owns:

- **Naming and discovery.** A flow's `name` and `description` are what
  agents, MCP clients, and human operators see.  Pick names that
  describe *the deterministic operation*, not the implementation steps
  inside.
- **Versioning policy.** `Flow.version` is a SemVer string.  The host
  decides what counts as a backwards-incompatible change to a flow:
  changing the set of input fields, changing the output schema, or
  swapping a tool that the host's downstream consumers depend on.
- **Stable inputs and outputs.** Even if the internal steps change, the
  flow's contract (its first-step input shape and its final-context
  shape) is what the host's callers depend on.  Use the optional
  `input_schema_ref` and `output_schema_ref` to lock that contract.
- **Surfacing flows as tools.** If the host re-exposes flows to an
  upstream agent (the canonical MCP integration), each flow should
  appear as a single tool with a single schema-validated input and
  output — not as N separate tools.

---

## 5. MCP examples must preserve the same expectations

`chainweaver[mcp]` ships an MCP adapter (`chainweaver/mcp/`).  When a
host exposes ChainWeaver flows over MCP, the same responsibilities apply
as for any direct tool registration — the MCP transport is not a
loophole.

What the host owns when wearing an MCP-server hat:

- **Authorisation per call.** Just because a tool is reachable over MCP
  does not mean every connected client should be able to call every
  flow.  Apply your auth model at the MCP server boundary.
- **Side-effect parity.** A flow that sends email when called directly
  must send email when called over MCP.  Do not silently switch tools
  to a no-op variant for the MCP transport "for safety" — that breaks
  the host's contract with its callers.  If you want a no-op variant
  for testing, expose it as a separately named flow.
- **Schema fidelity.** The MCP `inputSchema` should reflect the flow's
  *actual* first-step input schema (or its `input_schema_ref` if set),
  not a hand-written summary.  `flow_to_selectable_item` derives this
  correctly; prefer it over hand-rolled MCP descriptors.
- **Trace propagation.** If the MCP client passes a correlation ID,
  forward it into the host's trace store entry for the resulting
  `ExecutionResult`.  ChainWeaver does not parse MCP request metadata
  on the host's behalf.

---

## Concrete example: a deterministic invoice-reminder host

A representative host that owns all five responsibilities at once:

```python
from chainweaver import FlowExecutor, FlowRegistry, RedactionPolicy

# 1. Decide when to invoke — host's routing logic.
def handle_request(intent: str, payload: dict, caller_id: str) -> dict:
    if not host_acl.allows(caller_id, intent):     # host owns auth
        raise PermissionError(intent)

    flow = registry.match_flow_by_intent(intent)
    if flow is None:
        return {"status": "no_flow_matched"}

    # 2. Run the flow — ChainWeaver's deterministic step.
    result = executor.execute_flow(flow.name, payload)

    # 3. Persist with redaction — host owns the trace store.
    redacted = redactor.redact_execution_result(result)
    trace_store.put(redacted, correlation_id=payload.get("request_id"))

    # 4. Surface a single named operation back to the caller.
    return {
        "operation": flow.name,
        "version": result.flow_version,
        "success": result.success,
        "output": result.final_output,
        "trace_id": result.trace_id,
    }

registry = FlowRegistry()
executor = FlowExecutor(registry=registry)
redactor = RedactionPolicy(
    redact_fields=("customer_email", "internal_notes"),
)
```

ChainWeaver provides the inner two lines (`execute_flow`,
`RedactionPolicy`).  The host owns everything outside them.

---

## Scope of these guarantees

This page is **practical guidance**, not a contract.  ChainWeaver does
not enforce any of the responsibilities above at the framework level —
that would defeat the "just a library" property that lets you embed it
anywhere.  Treat this page as a checklist for host code review, not as
a list of features ChainWeaver promises to provide.

See also:

- [`docs/cli.md`](cli.md) — `chainweaver doctor --check-drift`, the
  seam for catching tool-schema drift that breaks replayability.
- [`docs/data-integrity.md`](data-integrity.md) — the correctness
  argument for why ChainWeaver's executor is the deterministic part.
- [`docs/security.md`](security.md) — the security model for the
  library proper (input validation, no `eval`, redaction primitives).
- [`AGENTS.md`](https://github.com/dgenio/ChainWeaver/blob/main/AGENTS.md)
  — the canonical contributor map, including the executor's three
  hard invariants.
