"""Structural checks for release and performance workflows."""

from __future__ import annotations

import os
import subprocess
import sys
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


def test_release_workflow_tags_the_untagged_source_version() -> None:
    workflow = _workflow("release.yml")

    assert "workflow_dispatch:" in workflow
    assert 'workflows: ["CI"]' in workflow
    assert "github.event.workflow_run.conclusion == 'success'" in workflow
    assert "github.event.workflow_run.head_sha" in workflow
    # Detection is version/tag drift, not PR branch name or label, so a
    # release PR merged from a manually named branch still gets tagged.
    assert 'version="$(python scripts/release.py version)"' in workflow
    assert 'git rev-parse -q --verify "refs/tags/${tag}^{commit}"' in workflow
    # Explicit tag fetch — the tag-existence check must not depend on an
    # implicit corollary of fetch-depth: 0 to see every existing tag.
    assert "fetch-tags: true" in workflow
    # The detect step must NOT compare the existing tag's SHA to MERGE_SHA —
    # this job runs on every merge to main, and the source version legitimately
    # stays at the last released value (whose tag legitimately points at an
    # older commit) for every ordinary commit between releases. Re-tagging
    # safety lives in the create-tag step instead, guarded by a real behavioral
    # test below rather than a string assertion.
    assert "existing_sha" not in workflow
    assert 'remote_sha="$(git ls-remote origin "refs/tags/${tag}" | cut -f1)"' in workflow
    assert 'test "${remote_sha}" = "${MERGE_SHA}"' in workflow
    assert 'startswith("release/v")' not in workflow
    assert "commits/${MERGE_SHA}/pulls" not in workflow
    assert "token: ${{ secrets.RELEASE_PR_TOKEN }}" in workflow
    assert "secrets.RELEASE_PR_TOKEN || github.token" not in workflow
    assert 'python scripts/release.py check --expected-version "${version}"' in workflow
    assert 'gh workflow run publish.yml --ref "v${VERSION}"' in workflow


_GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True, env=_GIT_ENV
    ).stdout.strip()


def _run_detect_step(*, repo: Path, merge_sha: str) -> tuple[int, str, str]:
    """Extract and execute the tag job's detect step against a scratch repo."""
    workflow = yaml.safe_load(_workflow("release.yml"))
    steps = workflow["jobs"]["tag"]["steps"]
    script = next(s["run"] for s in steps if s.get("name") == "Detect an untagged release version")

    github_output = repo / "github_output.txt"
    github_output.write_text("")
    result = subprocess.run(
        ["bash", "-c", script],
        cwd=repo,
        env={**os.environ, "MERGE_SHA": merge_sha, "GITHUB_OUTPUT": str(github_output)},
        capture_output=True,
        text=True,
    )
    return result.returncode, github_output.read_text(), result.stderr


def _init_release_repo(repo: Path, *, version: str) -> str:
    """Create a scratch git repo with a release commit; return its SHA."""
    _git(repo, "init", "-q")
    (repo / "chainweaver").mkdir()
    (repo / "chainweaver" / "__init__.py").write_text(f'__version__ = "{version}"\n')
    (repo / "scripts").mkdir()
    (repo / "scripts" / "release.py").write_bytes((_ROOT / "scripts" / "release.py").read_bytes())
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "release commit")
    return _git(repo, "rev-parse", "HEAD")


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="release.yml's tag job runs on ubuntu-latest only; this executes "
    "the real bash script, and bash-on-Windows stderr capture isn't reliable "
    "enough on the Windows test runners to be worth chasing here",
)
def test_release_workflow_detect_step_skips_ordinary_merge_between_releases(
    tmp_path: Path,
) -> None:
    """Regression test for a bug caught in #535 review.

    Comparing the existing tag's SHA to MERGE_SHA in the *detect* step (rather
    than the create-tag step) misfires on every ordinary commit to main
    between releases: the source version legitimately stays at the last
    released value, and that version's tag legitimately points at an older
    (the actual release) commit — not a "reused version" bug.
    """
    repo = tmp_path
    release_sha = _init_release_repo(repo, version="0.14.1")
    _git(repo, "tag", "v0.14.1", release_sha)

    (repo / "README.md").write_text("an ordinary, unrelated change\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "ordinary post-release merge")
    merge_sha = _git(repo, "rev-parse", "HEAD")
    assert merge_sha != release_sha

    returncode, output, stderr = _run_detect_step(repo=repo, merge_sha=merge_sha)

    assert returncode == 0, stderr
    assert "release=false" in output
    assert "release=true" not in output


@pytest.mark.skipif(
    sys.platform == "win32",
    reason="release.yml's tag job runs on ubuntu-latest only; this executes "
    "the real bash script, and bash-on-Windows stderr capture isn't reliable "
    "enough on the Windows test runners to be worth chasing here",
)
def test_release_workflow_detect_step_flags_genuine_pending_release(tmp_path: Path) -> None:
    """Sanity check: an untagged version bump is still detected as a release."""
    repo = tmp_path
    merge_sha = _init_release_repo(repo, version="0.15.0")

    returncode, _output, stderr = _run_detect_step(repo=repo, merge_sha=merge_sha)

    # scripts/release.py check fails here (no CHANGELOG/server.json fixture),
    # which is the correct outcome for a bare scratch repo — the point of this
    # test is that it reaches that check at all, i.e. release detection fired.
    assert returncode == 1
    assert "release error:" in stderr


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
