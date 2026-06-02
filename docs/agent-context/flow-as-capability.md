# Flow as Capability

> Canonical reference for treating a ChainWeaver flow as a routable
> Weaver Stack capability.  Read this when adding capability identity
> to a flow, integrating with contextweaver, or wiring an
> agent-kernel backend.

---

## Why "Flow as Capability"

ChainWeaver flows live in a registry by `(name, version)`.  The
Weaver Stack contract goes one step further: every routable unit —
tool, flow, or anything else an agent might invoke — is a
**capability** with a stable `capability_id` that contextweaver can
ingest into its catalog and that agent-kernel can dispatch through a
`CapabilityToken`.

A flow is, by construction, a capability:

- It has a stable name and version (the registry key).
- It exposes typed inputs and outputs via `input_schema_ref` /
  `output_schema_ref`.
- The executor guarantees deterministic-by-default semantics.

The only missing piece was an identifier that lives at the flow level
rather than only at the step level.  Issue #90 adds it.

---

## The `capability_id` field

Both `Flow` and
`DAGFlow` gained an optional
`capability_id: str | None = None` field.

When set, the flow is routable as a capability — contextweaver can
include it in its catalog and a `RoutingDecision` can target it by id.
When `None` (the default), the flow is still executable locally — it
just isn't advertised as a capability.

### Resolution order

`flow_to_selectable_item` resolves the identifier in this order:

1. The explicit `capability_id=` keyword argument.
2. The flow's `capability_id` field.
3. `flow.name` (fallback).

This means a flow without an explicit `capability_id` still produces a
`SelectableItem` — its id just defaults to `flow.name`.

### Recommended naming

Use a stable, dotted identifier with namespace.subspace structure:

| Bad | Good |
|-----|------|
| `"ingest"` | `"data.ingest"` |
| `"summarize_v2"` | `"summarize.text"` |
| `"my_flow_12345"` | `"reporting.daily"` |

The id is the public face of your flow — it's harder to rename later
than to choose well now.

---

## Exporting to contextweaver

`flow_to_selectable_item`
projects a flow to a `SelectableItem`
ready for contextweaver catalog ingestion:

```python
from chainweaver import Flow, FlowStep
from chainweaver.integrations.weaver_spec import flow_to_selectable_item

flow = Flow(
    name="ingest",
    version="1.0.0",
    description="Ingest data from a source.",
    capability_id="data.ingest",
    steps=[FlowStep(tool_name="extract", input_mapping={"src": "source"})],
    input_schema_ref=Flow.schema_ref_from(IngestInput),
    output_schema_ref=Flow.schema_ref_from(IngestOutput),
)

item = flow_to_selectable_item(flow, tags=("data", "ingest"))
# item.capability_id              == "data.ingest"
# item.label                      == "ingest"
# item.metadata["input_schema"]   == IngestInput.model_json_schema()
# item.metadata["output_schema"]  == IngestOutput.model_json_schema()
```

`flow_to_selectable_item` returns the upstream `weaver_contracts.SelectableItem`
dataclass; flow-specific routing metadata (version, determinism, tags, and the
resolved JSON Schemas) is carried in its `metadata` map.

The exporter is a **pure function** — it doesn't talk to a network
contextweaver, it just returns the data structure.  Ingesting the
`SelectableItem` into a live catalog is the caller's responsibility.

---

## Capability vs tool: two layers

`DAGFlowStep` already carried a per-step
`capability_id` field used for
kernel-delegated execution (`step_type="capability"`).  That field is
**different** from `Flow.capability_id` — they sit at two layers:

| Field | Layer | Used by |
|-------|-------|---------|
| `Flow.capability_id` / `DAGFlow.capability_id` | Flow-level — names the *flow itself* as a routable capability. | `flow_to_selectable_item()` (issue #107) — contextweaver catalog ingestion |
| `DAGFlowStep.capability_id` | Step-level — names a capability that a single DAG step delegates to. | `KernelBackedExecutor._execute_capability_step()` (issue #89) — agent-kernel dispatch |

Both can coexist on the same `DAGFlow`: the flow's `capability_id` is
how callers address it; each step's `capability_id` is how the kernel
dispatches the step's work.

---

## Boundaries

- The base `FlowExecutor` does **not**
  invoke any weaver-spec or contextweaver imports — the executor stays
  standalone and deterministic.  The seam that exposes flows as
  capabilities (`flow_to_selectable_item`) lives in
  `chainweaver.integrations.weaver_spec`.
- Setting `capability_id` does not change execution semantics.  The
  flow runs the same way whether or not it's advertised as a
  capability.
- `capability_id` is opt-in.  Existing flows that never set it work
  identically to before (`capability_id=None` is the default).

---

## Related issues

- **#90** — this doc + the `capability_id` field.
- **#107** — `flow_to_selectable_item()` exporter.
- **#106** — `RoutingDecisionAdapter` consumes a
  `RoutingDecision` whose selected item resolves (via
  `selected_capability_id()`) to a `SelectableItem.capability_id`.
- **#233** — `chainweaver.integrations.weaver_spec` consumes the published
  `weaver-contracts` types and adds `make_routing_decision()` /
  `resolve_flow_from_routing_decision()` so a router can hand a verdict
  straight to ChainWeaver for execution.
- **#89** — `KernelBackedExecutor` dispatches per-step
  `capability_id` via `KernelProtocol.invoke`.
- **#91** — declared weaver-spec compatibility lives in
  [`docs/SPEC_COMPAT.md`](../SPEC_COMPAT.md).
