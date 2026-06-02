# Weaver Stack golden path (issue #234)

One runnable example showing the three Weaver Stack layers cooperating on a
single task, built on the published [`weaver-contracts`](https://pypi.org/project/weaver-contracts/)
types (issue #233):

1. **contextweaver (routing)** — a `RoutingDecision` selects *which* capability
   handles the request from a bounded candidate set.
2. **ChainWeaver (execution)** — `resolve_flow_from_routing_decision()` turns the
   verdict into a registered deterministic flow, which runs with strict schemas
   and no LLM between steps.
3. **agent-kernel (gating)** — the flow's `capability`-typed step is dispatched
   through a kernel that gates the call against a `CapabilityToken` scope.

The run prints a `weaver_contracts.TraceEvent` audit trail for the full
route → execute → gate path.

## Run it

```bash
pip install 'chainweaver[weaver-stack]'
python examples/weaver_stack_golden_path/weaver_stack_golden_path.py
```

Each layer is optional. Without the `weaver-stack` extra the script prints a
skip notice and exits 0, so it is safe to run from a base install.

## What each layer contributes

| Layer | Contribution | Key symbol |
|-------|--------------|------------|
| contextweaver | Picks the capability | `make_routing_decision`, `selected_capability_id` |
| ChainWeaver | Runs the deterministic flow | `resolve_flow_from_routing_decision`, `KernelBackedExecutor` |
| agent-kernel | Gates + executes the capability | `InMemoryKernel`, `CapabilityToken` |

Related: `contextweaver#334`, `agent-kernel#95`.
