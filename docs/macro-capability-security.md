# Macro-capability security boundary

ChainWeaver can turn a reviewed multi-tool path into one named deterministic
capability. That convenience creates a security risk if callers start treating
"allowed to invoke the macro" as equivalent to "allowed to perform every child
operation inside it."

The target invariant is:

> **ChainWeaver may remove unnecessary reasoning boundaries. It must never
> silently remove authorization or approval boundaries.**

This page documents what the current implementation already enforces and the
caller-specific authorization guarantee that is **not yet implemented as a v1
contract**. The design work is tracked in
[#554](https://github.com/dgenio/ChainWeaver/issues/554), with independent
threat-model review requested in
[#558](https://github.com/dgenio/ChainWeaver/issues/558).

## What exists today

The current code has several useful but distinct security layers.

### Tool safety contracts

A `ToolSafetyContract` can describe:

- side-effect level;
- read-only status;
- stability and determinism;
- idempotency;
- cache/retry safety;
- dry-run support;
- whether explicit approval is required.

When contracts are aggregated, `merge_safety()` chooses the most restrictive
combination rather than the most permissive one.

### Executor safety gate

`FlowExecutor` can enforce an opt-in execution-time safety policy before each
tool runs:

- `max_side_effect_level` can refuse tools above a configured ceiling;
- an `approval_callback` can approve or deny a tool whose contract declares
  `requires_approval=True`;
- `strict_safety=True` fails closed when an approval-required tool has no
  approval callback;
- fallback tools pass through the same safety gate;
- strict safety suppresses unsafe retries for non-idempotent/side-effecting
  tools.

These controls are **per child tool**, which is important: wrapping several
tools in a flow does not make their safety metadata disappear.

### FlowServer request boundary

For network-exposed MCP flows, `FlowServer` can call host-supplied:

1. authentication;
2. rate limiting;
3. authorization.

The authorization context includes an authenticated `CallerIdentity` and the
flow's aggregate safety classification. `FlowServer` also filters which flows
are exposed based on lifecycle, side-effect, approval, and owner policy unless
an operator deliberately force-exposes them.

## The important gap

These two seams do not currently form one compositional caller-authorization
chain.

The current MCP path is conceptually:

```text
authenticate caller
→ authorize the flow-as-one-MCP-tool
→ execute_flow_async(...)
→ child ToolSafetyContract / approval gates
```

`CallerIdentity` exists at the FlowServer boundary, but it is not passed into
`FlowExecutor`. The current per-step `ApprovalContext` contains the flow/tool
identity, resolved inputs, trace/step identity, and `ToolSafetyContract`; it does
not contain the authenticated principal, scopes, resource authorization context,
or the macro-level policy decision.

Therefore ChainWeaver can currently enforce:

> "This child operation is side-effecting and requires approval."

It cannot yet provide the generic v1 guarantee:

> "The principal authorized for the macro is also authorized for this exact
> child operation and resource scope."

A most-restrictive aggregate `ToolSafetyContract` is valuable classification,
but it is **not equivalent to caller-specific child authorization**.

## What this means for deployments today

Do not claim compositional child authorization simply because a `FlowServer`
authorizer is configured.

Until #554 is implemented and independently reviewed, use one or more of these
host controls for sensitive flows:

- expose only flows whose complete child operation set is already allowed for
  the intended caller population;
- use conservative FlowServer lifecycle/side-effect filters;
- keep side-effecting or approval-sensitive flows behind `strict_safety=True`
  and a per-step approval callback;
- narrow the server to a trusted principal/environment instead of exposing one
  macro to callers with heterogeneous child permissions;
- reject a candidate entirely when its authorization/approval boundaries cannot
  be preserved cleanly;
- keep the underlying host/tool authorization checks active even when
  ChainWeaver invokes the tool.

The last point is especially important: ChainWeaver should orchestrate a
capability; it should not become a way to bypass authorization already enforced
by the capability's host service.

## Target v1 model

The current design proposal is intentionally not frozen yet. Independent review
may change it. The minimum semantics needed are:

```text
Invocation principal/context
  ↓
macro-level authorization
  ↓
for each executed child:
  child authorization for principal + operation + resource
  AND safety / approval gate
  ↓
auditable execution
```

A provider-neutral core context should carry enough information to correlate the
run with the host principal and policy without coupling `FlowExecutor` to MCP.
A host-specific adapter can map MCP `CallerIdentity`, an agent-kernel principal,
or another identity representation into that core context.

The child authorization decision should have a stable reason code and policy or
approval reference. The audit record must distinguish:

- macro authorization;
- child authorization;
- human/policy approval required by the safety contract.

A top-level `ALLOW` must never be displayed as proof that child authorization
also occurred.

## Sub-flows, fallbacks, retries, and resume

The v1 guarantee must apply to every path a promoted capability can actually
take:

- **sub-flows:** inherit the same effective principal/policy context;
- **fallbacks:** a stronger fallback cannot borrow the primary operation's
  authorization;
- **retries:** authorization does not make a non-idempotent side effect safe to
  repeat;
- **checkpoint/resume:** a run must not silently continue when the principal,
  authorization context, approved artifact, or relevant policy has changed;
- **drift:** schema equality does not prove safety/policy equality.

## Approval audit identity

Today an `ApprovalRecord` records `APPROVE`/`DENY` and an optional reason. That
is useful but insufficient for a strong governed-deployment audit claim.

For v1-sensitive paths, the eventual record needs enough information to answer:

- who or what policy approved the operation;
- for which principal;
- under which policy/version/reference;
- for which operation/resource scope;
- whether the approval had an expiry or bounded scope where applicable.

Do not add these fields merely to make the trace larger. Add only the minimum
stable references required to reconstruct the decision without persisting
sensitive policy payloads.

## Adversarial acceptance cases

The #554 implementation should prove at least these cases:

1. caller may invoke the macro but lacks permission for one child → child does
   not run;
2. caller may read resource A but resolved child input targets resource B → deny;
3. nested sub-flow contains a privileged child → same principal/policy is
   evaluated there;
4. fallback requires stronger permission than primary → fallback is denied;
5. approval-required child keeps its approval boundary after compilation;
6. resumed run under changed/missing principal or policy does not silently
   continue;
7. safety/policy drift suspends governed deployment rather than rewriting the
   historical approval basis;
8. the trace cannot confuse macro authorization with child authorization.

## Independent review before freezing the API

The principal/child-authorization API is intentionally not being rushed into the
core merely because the gap is now visible. #558 asks an independent security
reviewer to attack the threat model first.

Blocking findings must be fixed before v1 or the affected governed macro surface
must be removed/narrowed. That is preferable to stabilizing the wrong security
abstraction and supporting it indefinitely.
