# Weaver-spec compatibility

ChainWeaver declares conformance to a specific revision of the
[weaver-spec](https://github.com/dgenio/weaver-spec) contract.  The
declaration lives in source so CI fails any change that bumps the
contract without also touching this document.

## Declared compatibility

- **weaver-spec version:** `0.1.0`
- **Source of truth:**
  [`chainweaver.integrations.weaver_spec.WEAVER_SPEC_VERSION`](../chainweaver/integrations/weaver_spec.py)
- **Conformance test suite:**
  [`tests/test_weaver_spec_conformance.py`](../tests/test_weaver_spec_conformance.py)
- **CI gate:**
  [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) — the
  `conformance` job runs `pytest -m conformance` on the canonical
  Python 3.10 / `ubuntu-latest` lane.

The version above must match
[`WEAVER_SPEC_VERSION`](../chainweaver/integrations/weaver_spec.py)
verbatim.  The conformance test asserts this — bumping the constant
without updating this document, or vice versa, breaks CI.

## Supported invariants

ChainWeaver targets weaver-spec v0.1.0's three core invariants:

| Invariant | What it requires | Where it lives in ChainWeaver |
|-----------|------------------|-------------------------------|
| **I-03 — `SelectableItem`** | Each routable capability publishes a stable id, schema, and version. | [`flow_to_selectable_item()`](../chainweaver/integrations/weaver_spec.py) projects a [`Flow`](../chainweaver/flow.py) (or `DAGFlow`) to a `SelectableItem` for contextweaver catalog ingestion. |
| **I-04 — `RoutingDecision`** | Routers pick from a bounded candidate set with a stable verdict shape. | [`RoutingDecision`](../chainweaver/integrations/weaver_spec.py) is the mirror Pydantic model; [`RoutingDecisionAdapter`](../chainweaver/integrations/contextweaver.py) consumes it as a `DecisionCallback`. |
| **I-07 — `CapabilityToken`** | Capability execution is delegated to a kernel via a bearer token. | [`CapabilityToken`](../chainweaver/integrations/weaver_spec.py) is the mirror type; [`KernelBackedExecutor`](../chainweaver/integrations/agent_kernel.py) dispatches `step_type="capability"` steps through a `KernelProtocol` with a token. |

The mirror types are intentionally self-contained — ChainWeaver does
not depend on a `weaver-spec` PyPI package because the spec lives as a
sibling repo, not a published distribution.  When the upstream package
ships, callers can swap the mirror types for the upstream ones with a
one-line adapter (the field names and JSON shape are identical).

## How to bump the declared version

1. Audit ChainWeaver's mirror types against the new spec revision.
2. Update fields and validators in
   `chainweaver/integrations/weaver_spec.py` as needed.
3. Bump
   [`WEAVER_SPEC_VERSION`](../chainweaver/integrations/weaver_spec.py)
   to the new value.
4. Update this document — the "Declared compatibility" section *and*
   any invariant rows that changed.
5. Update `tests/test_weaver_spec_conformance.py` to cover any new
   round-trip / shape assertions.
6. Run `pytest -m conformance` locally — it must pass.
7. Mention the bump in `CHANGELOG.md` under the same release.

The `conformance` pytest marker is registered in `pyproject.toml`;
``pytest -m conformance`` is the canonical command CI runs.
