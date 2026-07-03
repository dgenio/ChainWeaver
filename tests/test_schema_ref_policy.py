"""Schema-ref module-resolution policy tests (issue #345).

Covers the allowlist matcher, pre-import rejection (a denied module's
top-level code never runs), context-manager scoping, the process-global
setter, and the ``--schema-ref-allow`` CLI flag end to end.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import pytest
from typer.testing import CliRunner

from chainweaver import cli
from chainweaver.exceptions import SchemaRefPolicyError
from chainweaver.flow import (
    SchemaRefAllowlist,
    get_schema_ref_policy,
    resolve_class_ref,
    schema_ref_policy,
    set_schema_ref_policy,
)

_RUNNER = CliRunner()

_SENTINEL_MODULE = "schema_ref_sentinel"
_SENTINEL_REF = f"{_SENTINEL_MODULE}:SentinelSchema"


@pytest.fixture(autouse=True)
def _clear_policy() -> Iterator[None]:
    """Each test starts and ends with the permissive default policy."""
    set_schema_ref_policy(None)
    yield
    set_schema_ref_policy(None)


@pytest.fixture
def _fresh_sentinel() -> Iterator[None]:
    """Ensure the sentinel module is unimported so a real import is observable."""
    sys.modules.pop(_SENTINEL_MODULE, None)
    yield
    sys.modules.pop(_SENTINEL_MODULE, None)


# ---------------------------------------------------------------------------
# SchemaRefAllowlist matcher
# ---------------------------------------------------------------------------


def test_allowlist_permits_exact_and_submodules() -> None:
    allow = SchemaRefAllowlist(["myapp.schemas"])
    assert allow("myapp.schemas") is True
    assert allow("myapp.schemas.orders") is True


def test_allowlist_rejects_non_prefix_and_prefix_lookalikes() -> None:
    allow = SchemaRefAllowlist(["myapp.schemas"])
    assert allow("myapp") is False
    assert allow("myapp.schemasX") is False  # not a dotted submodule
    assert allow("other") is False


def test_empty_allowlist_rejects_everything() -> None:
    allow = SchemaRefAllowlist([])
    assert allow("builtins") is False


# ---------------------------------------------------------------------------
# resolve_class_ref enforcement
# ---------------------------------------------------------------------------


def test_allowlisted_ref_resolves() -> None:
    with schema_ref_policy(SchemaRefAllowlist(["builtins"])):
        assert resolve_class_ref("builtins:ValueError") is ValueError


@pytest.mark.usefixtures("_fresh_sentinel")
def test_rejected_ref_raises_before_importing() -> None:
    set_schema_ref_policy(SchemaRefAllowlist(["builtins"]))
    with pytest.raises(SchemaRefPolicyError) as excinfo:
        resolve_class_ref(_SENTINEL_REF)

    err = excinfo.value
    assert err.code == "CW-E051"
    assert err.module_path == _SENTINEL_MODULE
    assert err.ref == _SENTINEL_REF
    # The decisive property: the denied module was never imported.
    assert _SENTINEL_MODULE not in sys.modules


@pytest.mark.usefixtures("_fresh_sentinel")
def test_allowlisted_sentinel_actually_imports() -> None:
    with schema_ref_policy(SchemaRefAllowlist([_SENTINEL_MODULE])):
        resolved = resolve_class_ref(_SENTINEL_REF)
    assert resolved.__name__ == "SentinelSchema"
    assert sys.modules[_SENTINEL_MODULE].IMPORT_LOG == ["imported"]


def test_no_policy_is_permissive() -> None:
    assert get_schema_ref_policy() is None
    assert resolve_class_ref("builtins:KeyError") is KeyError


# ---------------------------------------------------------------------------
# Scoping
# ---------------------------------------------------------------------------


def test_context_manager_restores_previous_policy() -> None:
    outer = SchemaRefAllowlist(["builtins"])
    set_schema_ref_policy(outer)
    with schema_ref_policy(SchemaRefAllowlist(["json"])):
        assert get_schema_ref_policy() is not outer
    assert get_schema_ref_policy() is outer


def test_context_manager_restores_on_exception() -> None:
    set_schema_ref_policy(None)
    with pytest.raises(RuntimeError), schema_ref_policy(SchemaRefAllowlist(["builtins"])):
        raise RuntimeError("boom")
    assert get_schema_ref_policy() is None


# ---------------------------------------------------------------------------
# CLI flag (issue #345) — exercised through `chainweaver run`
# ---------------------------------------------------------------------------

_FLOW_WITH_REF = """type: Flow
name: ref_flow
version: 0.1.0
description: Flow whose input schema references the sentinel module.
input_schema_ref: schema_ref_sentinel:SentinelSchema
steps:
  - tool_name: double
    input_mapping: {number: number}
"""


def test_cli_run_rejects_non_allowlisted_ref(tmp_path: Path) -> None:
    flow_file = tmp_path / "ref.flow.yaml"
    flow_file.write_text(_FLOW_WITH_REF, encoding="utf-8")

    result = _RUNNER.invoke(
        cli.app,
        [
            "run",
            str(flow_file),
            "--tools",
            "examples.simple_linear_flow",
            "--schema-ref-allow",
            "myapp.only",
            "--input",
            '{"value": 1}',
        ],
    )

    assert result.exit_code == 1
    assert "schema_ref_sentinel" in result.output or "rejected" in result.output
