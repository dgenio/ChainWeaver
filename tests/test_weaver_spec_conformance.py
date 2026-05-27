"""Weaver-spec conformance gate (issue #91).

This module is the CI conformance signal for ChainWeaver's declared
weaver-spec compatibility.  It is collected by the default ``pytest``
run *and* by the dedicated CI job in ``.github/workflows/ci.yml`` so
drift between :data:`chainweaver.integrations.weaver_spec.WEAVER_SPEC_VERSION`
and ``docs/SPEC_COMPAT.md`` fails the build.

The tests are intentionally narrow:

- They do not depend on any external ``weaver-spec`` Python package
  (the spec is a sibling repo, not a PyPI distribution).
- They verify the **mirror types** declared in
  :mod:`chainweaver.integrations.weaver_spec` exist, are
  pydantic-validated, and round-trip through JSON.
- They cross-check the declared version against
  ``docs/SPEC_COMPAT.md`` so the compat statement and the code stay
  in sync.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from chainweaver.integrations.weaver_spec import (
    WEAVER_SPEC_VERSION,
    CapabilityToken,
    RoutingDecision,
    SelectableItem,
    flow_to_selectable_item,
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
def test_mirror_types_all_present() -> None:
    """All three mirror types are importable and Pydantic models."""
    from pydantic import BaseModel

    assert issubclass(CapabilityToken, BaseModel)
    assert issubclass(RoutingDecision, BaseModel)
    assert issubclass(SelectableItem, BaseModel)


@pytest.mark.conformance
def test_mirror_types_json_round_trip() -> None:
    """Each mirror type round-trips through JSON byte-identically."""
    tok = CapabilityToken(
        capability_id="data.ingest", version="1.0.0", token="s", scopes=("read",)
    )
    assert CapabilityToken.model_validate_json(tok.model_dump_json()) == tok

    rd = RoutingDecision(
        selected_capability_id="data.ingest",
        candidates=("data.ingest", "data.batch"),
        rationale="r",
        confidence=0.9,
        token=tok,
    )
    assert RoutingDecision.model_validate_json(rd.model_dump_json()) == rd

    item = SelectableItem(
        capability_id="data.ingest",
        name="ingest",
        description="d",
        version="0.1.0",
        tags=("data",),
    )
    assert SelectableItem.model_validate_json(item.model_dump_json()) == item


@pytest.mark.conformance
def test_spec_compatibility_report_fields() -> None:
    """The compat report shape is stable."""
    report = spec_compatibility_report()
    assert report.spec_version == WEAVER_SPEC_VERSION
    assert report.exporter_present is True
    assert set(report.mirror_types) == {
        "CapabilityToken",
        "RoutingDecision",
        "SelectableItem",
    }


@pytest.mark.conformance
def test_flow_to_selectable_item_is_exported() -> None:
    """The exporter function is at the documented path."""
    assert callable(flow_to_selectable_item)


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
