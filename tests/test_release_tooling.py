"""Release automation tests (#304, #307, #308, #309)."""

from __future__ import annotations

import importlib.util
import json
import shutil
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType
from typing import Any
from uuid import uuid4

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[1]
_SCRIPT = _REPO_ROOT / "scripts/release.py"
_RELEASE_FILES = (
    Path("pyproject.toml"),
    Path("chainweaver/__init__.py"),
    Path("server.json"),
    Path(".github/actions/chainweaver/action.yml"),
    Path(".github/actions/chainweaver/README.md"),
    Path(".github/workflows/release.yml"),
    Path(".github/workflows/distribution-check.yml"),
    Path("docs/github-action.md"),
    Path("CHANGELOG.md"),
)


def _load_release_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("chainweaver_release", _SCRIPT)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def release_module() -> ModuleType:
    return _load_release_module()


@pytest.fixture()
def release_tree() -> Iterator[Path]:
    root = _REPO_ROOT / "build" / f"release-test-{uuid4().hex}"
    root.mkdir(parents=True)
    try:
        for relative in _RELEASE_FILES:
            source = _REPO_ROOT / relative
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        yield root
    finally:
        shutil.rmtree(root)


def test_prepare_release_updates_all_governed_references(
    release_module: ModuleType,
    release_tree: Path,
) -> None:
    current = release_module.source_version(release_tree)
    assert current.startswith("0.")
    parts = [int(p) for p in current.split(".")]
    target = f"{parts[0]}.{parts[1]}.{parts[2] + 1}"

    release_module.prepare_release(release_tree, target, "2026-06-09")

    assert release_module.source_version(release_tree) == target
    assert release_module.release_issues(release_tree, expected_version=target) == []

    manifest = json.loads((release_tree / "server.json").read_text(encoding="utf-8"))
    assert manifest["version"] == target
    assert manifest["packages"][0]["version"] == target

    changelog = (release_tree / "CHANGELOG.md").read_text(encoding="utf-8")
    assert f"## [Unreleased]\n\n## [{target}] - 2026-06-09" in changelog
    compare_link = (
        f"[{target}]: https://github.com/dgenio/ChainWeaver/compare/v{current}...v{target}"
    )
    assert compare_link in changelog


@pytest.mark.parametrize("target", ["0.12.1", "0.12.0", "v0.12.2", "0.12"])
def test_prepare_release_rejects_invalid_or_non_increasing_versions(
    release_module: ModuleType,
    release_tree: Path,
    target: str,
) -> None:
    with pytest.raises(ValueError):
        release_module.prepare_release(release_tree, target, "2026-06-09")


def test_release_status_reports_manual_trackers(
    release_module: ModuleType,
    release_tree: Path,
) -> None:
    current = release_module.source_version(release_tree)
    older = "0.0.0"
    action = release_tree / ".github/actions/chainweaver/action.yml"
    action.write_text(
        action.read_text(encoding="utf-8").replace(
            f'    default: "{current}"',
            f'    default: "{older}"',
            1,
        ),
        encoding="utf-8",
    )
    status = release_module.release_status(
        release_tree,
        expected_version=current,
        generated_on="2026-06-08",
    )

    assert "Generated: 2026-06-08" in status
    assert "| Release metadata consistency | FAIL |" in status
    assert f"action default is {older}, expected {current}" in status
    assert "[Tracked in #325](https://github.com/dgenio/ChainWeaver/issues/325)" in status
    assert "[Tracked in #231](https://github.com/dgenio/ChainWeaver/issues/231)" in status
    assert "| MANUAL | Not completed |" in status


def test_verify_pypi_retries_until_exact_version(release_module: ModuleType) -> None:
    responses: list[dict[str, Any] | Exception] = [
        OSError("not propagated yet"),
        {"info": {"version": "0.12.2"}},
    ]
    sleeps: list[float] = []

    def fetch(_url: str) -> dict[str, Any]:
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    release_module.verify_pypi(
        "0.12.2",
        attempts=2,
        delay=0.25,
        fetch=fetch,
        sleep=sleeps.append,
    )

    assert sleeps == [0.25]


def test_verify_pypi_fails_after_bounded_attempts(release_module: ModuleType) -> None:
    def fetch(_url: str) -> dict[str, Any]:
        raise OSError("still missing")

    with pytest.raises(RuntimeError, match="did not resolve after 2 attempts"):
        release_module.verify_pypi(
            "0.12.2",
            attempts=2,
            delay=0,
            fetch=fetch,
            sleep=lambda _delay: None,
        )
