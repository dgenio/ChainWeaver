"""Package metadata anti-drift (#203, #209).

These tests fail when the three version sources fall out of sync:

- ``pyproject.toml`` ``[project]`` ``version``
- ``chainweaver.__version__`` at runtime
- the latest released heading in ``CHANGELOG.md`` (``## [x.y.z] - YYYY-MM-DD``)

Historical drift example: ``pyproject.toml`` was bumped to 0.10.0 in the
release commit but ``chainweaver/__init__.py`` still reported 0.9.0 to
``pip show`` consumers and to anyone introspecting ``chainweaver.__version__``.
This file catches that class of bug at CI time, before the next release.

The tests also check that ``pyproject.toml`` declares the project URLs the
PyPI sidebar and ``pip show chainweaver`` expose to users.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Any, cast

import pytest

import chainweaver

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PYPROJECT = _REPO_ROOT / "pyproject.toml"
_CHANGELOG = _REPO_ROOT / "CHANGELOG.md"


def _pyproject_table() -> dict[str, Any]:
    """Load ``pyproject.toml`` via stdlib ``tomllib`` (3.11+) or a regex fallback.

    ChainWeaver supports Python >=3.10 (see ``pyproject.toml``).  ``tomllib``
    ships with the stdlib from 3.11.  Rather than add ``tomli`` to the dev
    deps for the single 3.10 leg, we fall back to a minimal regex parser
    that only handles the keys we read here.
    """
    if sys.version_info >= (3, 11):
        import tomllib

        with _PYPROJECT.open("rb") as handle:
            return tomllib.load(handle)
    # Fallback: read just the keys we need.
    text = _PYPROJECT.read_text(encoding="utf-8")
    table: dict[str, Any] = {"project": {}, "urls": {}}
    version_match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    if version_match:
        table["project"]["version"] = version_match.group(1)
    urls_block = re.search(
        r"^\[project\.urls\]\n(.*?)(?=^\[|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    if urls_block:
        for line in urls_block.group(1).splitlines():
            entry = re.match(r'\s*"([^"]+)"\s*=\s*"([^"]+)"', line)
            if entry:
                table["urls"][entry.group(1)] = entry.group(2)
    table["project"]["urls"] = table["urls"]
    return table


def _pyproject_version() -> str:
    return cast(str, _pyproject_table()["project"]["version"])


def _latest_changelog_version() -> str:
    """Return the most recent released version heading from ``CHANGELOG.md``.

    Skips the ``## [Unreleased]`` heading.  Expects ``## [x.y.z] - YYYY-MM-DD``.
    """
    text = _CHANGELOG.read_text(encoding="utf-8")
    for match in re.finditer(r"^## \[(.+?)\]", text, re.MULTILINE):
        version = match.group(1).strip()
        if version.lower() != "unreleased":
            return version
    pytest.fail(f"No released version heading found in {_CHANGELOG}")


def test_pyproject_version_matches_runtime_version() -> None:
    """``pyproject.toml`` and ``chainweaver.__version__`` must agree."""
    assert _pyproject_version() == chainweaver.__version__, (
        f"version drift: pyproject.toml={_pyproject_version()!r} "
        f"but chainweaver.__version__={chainweaver.__version__!r}"
    )


def test_changelog_top_release_matches_runtime_version() -> None:
    """The latest released ``## [x.y.z]`` heading must match the package version."""
    top = _latest_changelog_version()
    assert top == chainweaver.__version__, (
        f"CHANGELOG.md top release heading is {top!r}, "
        f"chainweaver.__version__ is {chainweaver.__version__!r}. "
        "Bump the changelog or the package version so they agree."
    )


def test_pyproject_publishes_user_navigation_urls() -> None:
    """``pyproject.toml`` must expose the URLs the PyPI sidebar surfaces."""
    urls = _pyproject_table()["project"]["urls"]
    required = {"Homepage", "Documentation", "Source", "Changelog", "Issues"}
    missing = required - urls.keys()
    assert not missing, (
        f"pyproject.toml [project.urls] is missing required entries: {sorted(missing)}. "
        f"Present: {sorted(urls.keys())}."
    )
    # Sanity-check that the URLs are absolute https — relative paths would
    # render as broken links on PyPI.
    for label, value in urls.items():
        assert value.startswith("https://"), (
            f"[project.urls] {label!r} must be an absolute https:// URL, got {value!r}"
        )
