"""Weaver-spec conformance gate (issues #91, #233).

This module is the CI conformance signal for ChainWeaver's declared
weaver-spec compatibility.  It is collected by the default ``pytest``
run *and* by the dedicated CI job in ``.github/workflows/ci.yml`` so
drift between :data:`chainweaver.integrations.weaver_spec.WEAVER_SPEC_VERSION`
and ``docs/SPEC_COMPAT.md`` fails the build.

The tests are intentionally narrow:

- They consume the **published** ``weaver-contracts`` package directly
  (issue #233) — the integration is no longer a self-contained mirror.
  Each test skips cleanly if the ``weaver-stack`` extra is not installed.
- They verify the contract types re-exported by
  :mod:`chainweaver.integrations.weaver_spec` are the upstream
  dataclasses and that the exporter/resolvers are at their documented
  paths.
- They cross-check the declared version against
  ``docs/SPEC_COMPAT.md`` so the compat statement and the code stay
  in sync.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

pytest.importorskip("weaver_contracts")

from chainweaver.integrations.weaver_spec import (
    WEAVER_SPEC_VERSION,
    CapabilityToken,
    RoutingDecision,
    SelectableItem,
    flow_to_selectable_item,
    is_compatible,
    spec_compatibility_report,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC_COMPAT_PATH = REPO_ROOT / "docs" / "SPEC_COMPAT.md"


@pytest.mark.conformance
def test_weaver_spec_version_format() -> None:
    """The declared version is a PEP 440-style ``major.minor.patch`` string."""
    parts = WEAVER_SPEC_VERSION.split(".")
    assert len(parts) == 3, f"Expected 'X.Y.Z'; got {WEAVER_SPEC_VERSION!r}"
    for p in parts:
        assert p.isdigit(), f"Non-numeric version segment in {WEAVER_SPEC_VERSION!r}"


@pytest.mark.conformance
def test_declared_version_matches_installed_contract() -> None:
    """The declared version is the version actually importable from the package."""
    from weaver_contracts.version import CONTRACT_VERSION

    assert WEAVER_SPEC_VERSION == CONTRACT_VERSION
    assert is_compatible(WEAVER_SPEC_VERSION) is True


@pytest.mark.conformance
def test_spec_compat_doc_references_declared_version() -> None:
    """``docs/SPEC_COMPAT.md`` must mention the declared spec version."""
    assert SPEC_COMPAT_PATH.is_file(), f"Missing {SPEC_COMPAT_PATH}"
    text = SPEC_COMPAT_PATH.read_text(encoding="utf-8")
    assert WEAVER_SPEC_VERSION in text, (
        f"docs/SPEC_COMPAT.md does not reference declared "
        f"WEAVER_SPEC_VERSION={WEAVER_SPEC_VERSION!r}. "
        f"Update the doc or bump the constant in lock-step."
    )


@pytest.mark.conformance
def test_contract_types_are_upstream_dataclasses() -> None:
    """The re-exported contract types are the upstream weaver-contracts dataclasses."""
    import weaver_contracts as wc

    assert SelectableItem is wc.SelectableItem
    assert RoutingDecision is wc.RoutingDecision
    assert CapabilityToken is wc.CapabilityToken
    for cls in (SelectableItem, RoutingDecision, CapabilityToken):
        assert dataclasses.is_dataclass(cls)


@pytest.mark.conformance
def test_selectable_item_json_round_trip() -> None:
    """A SelectableItem round-trips through JSON byte-for-byte via ``asdict``."""
    item = SelectableItem(
        id="data.ingest",
        label="ingest",
        description="d",
        capability_id="data.ingest",
        metadata={"version": "0.1.0", "tags": ["data"]},
    )
    restored = SelectableItem(**json.loads(json.dumps(dataclasses.asdict(item))))
    assert restored == item


@pytest.mark.conformance
def test_spec_compatibility_report_fields() -> None:
    """The compat report shape is stable."""
    report = spec_compatibility_report()
    assert report.spec_version == WEAVER_SPEC_VERSION
    assert report.exporter_present is True
    assert set(report.contract_types) == {
        "CapabilityToken",
        "RoutingDecision",
        "SelectableItem",
    }


@pytest.mark.conformance
def test_flow_to_selectable_item_is_exported() -> None:
    """The exporter function is at the documented path."""
    assert callable(flow_to_selectable_item)


@pytest.mark.conformance
def test_routing_resolvers_are_exported() -> None:
    """The routing-consumption helpers are at their documented path (issue #233)."""
    from chainweaver.integrations.weaver_spec import (
        make_routing_decision,
        resolve_flow_from_routing_decision,
        selected_capability_id,
    )

    assert callable(make_routing_decision)
    assert callable(selected_capability_id)
    assert callable(resolve_flow_from_routing_decision)


@pytest.mark.conformance
def test_decision_callback_seam_is_exported() -> None:
    """The DecisionCallback protocol is part of the public API."""
    from chainweaver import (
        BaseDecisionCallback,
        DecisionCallback,
        DecisionCallbackError,
        DecisionContext,
    )

    assert DecisionCallback is not None
    assert DecisionContext is not None
    assert BaseDecisionCallback is not None
    assert issubclass(DecisionCallbackError, Exception)


@pytest.mark.conformance
def test_kernel_backed_executor_is_exported() -> None:
    """The kernel adapter is at the documented path."""
    from chainweaver.integrations.agent_kernel import (
        InMemoryKernel,
        KernelBackedExecutor,
        KernelProtocol,
    )

    assert KernelBackedExecutor is not None
    assert KernelProtocol is not None
    assert InMemoryKernel is not None


@pytest.mark.conformance
def test_contextweaver_adapter_is_exported() -> None:
    """The contextweaver adapter is at the documented path."""
    from chainweaver.integrations.contextweaver import (
        ContextweaverClient,
        RoutingDecisionAdapter,
        StaticRoutingClient,
    )

    assert RoutingDecisionAdapter is not None
    assert ContextweaverClient is not None
    assert StaticRoutingClient is not None
