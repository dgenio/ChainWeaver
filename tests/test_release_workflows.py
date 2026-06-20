"""Structural checks for release and performance workflows."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

_ROOT = Path(__file__).resolve().parents[1]
_WORKFLOWS = _ROOT / ".github/workflows"


def _workflow(name: str) -> str:
    return (_WORKFLOWS / name).read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "name",
    [
        "release.yml",
        "publish.yml",
        "distribution-check.yml",
        "action-smoke.yml",
        "bench.yml",
    ],
)
def test_changed_workflow_is_valid_yaml(name: str) -> None:
    document = yaml.load(_workflow(name), Loader=yaml.BaseLoader)

    assert isinstance(document, dict)
    assert "jobs" in document


def test_release_workflow_tags_the_merged_release_pr_commit() -> None:
    workflow = _workflow("release.yml")

    assert "workflow_dispatch:" in workflow
    assert 'workflows: ["CI"]' in workflow
    assert "github.event.workflow_run.conclusion == 'success'" in workflow
    assert "github.event.workflow_run.head_sha" in workflow
    assert 'startswith("release/v")' in workflow
    assert "commits/${MERGE_SHA}/pulls" in workflow
    assert "token: ${{ secrets.RELEASE_PR_TOKEN }}" in workflow
    assert "secrets.RELEASE_PR_TOKEN || github.token" not in workflow
    assert 'python scripts/release.py check --expected-version "${VERSION}"' in workflow
    assert 'gh workflow run publish.yml --ref "v${VERSION}"' in workflow


def test_publish_workflow_accepts_tag_push_or_explicit_dispatch() -> None:
    workflow = _workflow("publish.yml")

    assert 'tags:\n      - "v*"' in workflow
    assert "workflow_dispatch:" in workflow
    assert (
        "group: publish-${{ github.event_name == 'workflow_dispatch' "
        "&& format('v{0}', inputs.version) || github.ref_name }}"
    ) in workflow
    assert "python scripts/release.py check --expected-version" in workflow
    assert "ref: v${{ needs.release.outputs.version }}" in workflow
    assert "skip-existing: true" in workflow
    assert "tag_name: v${{ needs.release.outputs.version }}" in workflow


def test_distribution_check_runs_after_successful_publication() -> None:
    workflow = _workflow("distribution-check.yml")

    assert 'workflows: ["Publish to PyPI"]' in workflow
    assert "github.event.workflow_run.conclusion == 'success'" in workflow
    assert "python scripts/release.py verify-pypi" in workflow
    # SC2086: the ${RUNNER_TEMP}/mcp-publisher path must be quoted. Assert the full
    # quoted form (including the opening quote) is present and the unquoted pre-fix
    # form is gone, so this test fails if the SC2086 fix ever regresses.
    assert '"${RUNNER_TEMP}/mcp-publisher" validate server.json' in workflow
    assert "mcp-publisher validate server.json" not in workflow
    assert "sha256sum --check -" in workflow
    assert "uses: ./.github/actions/chainweaver" in workflow
    assert "chainweaver-version: ${{ steps.release.outputs.version }}" in workflow


def test_pre_publish_action_smoke_uses_latest_published_package() -> None:
    workflow = _workflow("action-smoke.yml")

    assert workflow.count('chainweaver-version: ""') == 2


def test_benchmark_alerts_only_for_execution_sensitive_changes() -> None:
    workflow = _workflow("bench.yml")

    assert "chainweaver/(cache|checkpoint|compiler|contracts|decisions|events|executor" in workflow
    assert "benchmarks/.*" in workflow
    assert "pyproject\\.toml" in workflow
    assert 'alert-threshold: "200%"' in workflow
    assert "steps.changes.outputs.execution == 'true'" in workflow
    assert "auto-push:" in workflow


def test_distribution_document_has_no_untracked_checkboxes() -> None:
    document = (_ROOT / "docs/distribution.md").read_text(encoding="utf-8")

    assert "- [ ]" not in document
