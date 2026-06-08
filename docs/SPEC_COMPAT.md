# Weaver-spec compatibility

ChainWeaver consumes a supported range of the
[weaver-spec](https://github.com/dgenio/weaver-spec) contract, published
to PyPI as the [`weaver-contracts`](https://pypi.org/project/weaver-contracts/)
distribution. The dependency range lives in `pyproject.toml`;
`WEAVER_SPEC_VERSION` reports the version installed at runtime.

## Declared compatibility

- **Supported `weaver-contracts` range:** `>=0.6,<1.0`
- **Minimum version tested in CI:** `0.6.0`
- **Runtime version signal:**
  `chainweaver.integrations.weaver_spec.WEAVER_SPEC_VERSION`
  (read from the installed `weaver_contracts.version.CONTRACT_VERSION`)
- **Optional extra:** `pip install 'chainweaver[weaver-stack]'`
- **Conformance test suite:**
  `tests/test_weaver_spec_conformance.py`
- **CI gate:**
  `.github/workflows/ci.yml` — the `conformance` job validates the normally
  resolved dependency, while `floor-deps` validates the declared minimum.

The conformance test asserts that the installed `WEAVER_SPEC_VERSION`
satisfies the package metadata's declared range and that this document
lists the same lower and upper bounds.

## Supported invariants

ChainWeaver consumes `weaver-contracts>=0.6,<1.0`'s three core routing /
execution invariants directly (no internal mirror types):

| Invariant | What it requires | Where it lives in ChainWeaver |
|-----------|------------------|-------------------------------|
| **I-03 — `SelectableItem`** | Each routable capability publishes a stable id, label, and routing metadata. | `flow_to_selectable_item()` projects a `Flow` (or `DAGFlow`) to a `weaver_contracts.SelectableItem` for contextweaver catalog ingestion (schema/version/tags carried in `metadata`). |
| **I-04 — `RoutingDecision`** | Routers pick from a bounded candidate set (choice cards) with a stable verdict shape. | `make_routing_decision()` builds a `RoutingDecision`; `selected_capability_id()` reads the verdict; `resolve_flow_from_routing_decision()` resolves it to a registered flow; `RoutingDecisionAdapter` consumes it as a `DecisionCallback`. |
| **I-07 — `CapabilityToken`** | Capability execution is delegated to a kernel via a scoped bearer token. | `CapabilityToken` is the upstream type; `KernelBackedExecutor` dispatches `step_type="capability"` steps through a `KernelProtocol`, gating each call against the token's `scope`. |

ChainWeaver consumes the upstream dataclasses directly, so there is no
mirror-vs-spec drift to police — the only seam is the declared range
above.  Importing `chainweaver.integrations.weaver_spec` (or the
`contextweaver` / `agent_kernel` adapters that build on it) requires the
`weaver-stack` extra; the base install is unaffected.

## How to change the supported range

1. Install the new `weaver-contracts` release and review its changelog
   for shape changes to `SelectableItem` / `RoutingDecision` /
   `CapabilityToken`.
2. Update the adapters in
   `chainweaver/integrations/weaver_spec.py`,
   `contextweaver.py`, and `agent_kernel.py` if any consumed field
   changed.
3. Update the range in `pyproject.toml` (`weaver-stack` extra and `dev`).
   `WEAVER_SPEC_VERSION` continues to track the installed package.
4. Update this document — the "Declared compatibility" section *and*
   any invariant rows that changed.
5. Update `tests/test_weaver_spec_conformance.py` to cover any new
   round-trip / shape assertions.
6. Run `pytest -m conformance` locally — it must pass.
7. Mention the bump in `CHANGELOG.md` under the same release.

The `conformance` pytest marker is registered in `pyproject.toml`;
the canonical CI command is::

    python -m pytest tests/test_weaver_spec_conformance.py -m conformance --no-cov

``--no-cov`` opts out of the package-wide coverage gate for this
subset — coverage is enforced by the main ``test`` job that runs the
full suite.
