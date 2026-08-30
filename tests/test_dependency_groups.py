"""Maintainer tooling stays out of published metadata (issue #550).

ChainWeaver publishes extras that describe *downstream capability* and keeps
lint/type/test tooling in PEP 735 dependency groups, which never reach the
wheel's metadata.  The old ``dev`` extra mixed the two, so ``pip install
chainweaver[dev]`` pulled ruff, mypy and a notebook kernel into environments
that only wanted the library.

These tests fail when that separation erodes, and when the composition CI
installs stops being named in exactly one place.  The second half matters
most: before this split, three workflows hand-copied the pytest runner list,
and one of those copies never gained ``pytest-timeout`` when issue #543 added
it — the free-threaded lane, the one lane most likely to hang, ran unbounded
for as long as the copy existed.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
_PYPROJECT = _ROOT / "pyproject.toml"
_WORKFLOWS = _ROOT / ".github" / "workflows"

# Distributions a consumer of the library never needs.  Naming them explicitly
# (rather than pattern-matching "looks like a tool") keeps the assertion
# readable when it fails.
_MAINTAINER_ONLY = {
    "pytest",
    "pytest-cov",
    "pytest-asyncio",
    "pytest-timeout",
    "ruff",
    "mypy",
    "types-pyyaml",
    "griffe",
    "nbmake",
    "ipykernel",
    "opentelemetry-sdk",
}

# Extras that describe downstream capability.  ``docs`` is deliberately absent
# from the maintainer set: building the documentation site is something a
# reader may reasonably want, and it stays a published extra.
_INTEGRATION_EXTRAS = {
    "yaml",
    "otel",
    "contrib",
    "langchain",
    "llamaindex",
    "langgraph",
    "openai-agents",
    "mcp",
    "weaver-stack",
    "test",
}

_needs_tomllib = pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="tomllib is stdlib from 3.11; ChainWeaver supports 3.10 without tomli",
)


def _pyproject() -> dict:
    import tomllib

    with _PYPROJECT.open("rb") as handle:
        return tomllib.load(handle)


def _requirement_names(entries: list) -> set[str]:
    """Distribution names from a requirement list, ignoring include-group refs."""
    names = set()
    for entry in entries:
        if isinstance(entry, dict):  # {"include-group": ...}
            continue
        match = re.match(r"^\s*([A-Za-z0-9._-]+)", entry)
        assert match is not None, entry
        names.add(match.group(1).lower().replace("_", "-"))
    return names


def _workflow_texts() -> dict[str, str]:
    texts = {
        path.name: path.read_text(encoding="utf-8") for path in sorted(_WORKFLOWS.glob("*.yml"))
    }
    assert texts, "no workflows found — the scan below would pass vacuously"
    return texts


@_needs_tomllib
def test_no_dev_extra_is_published() -> None:
    extras = _pyproject()["project"]["optional-dependencies"]

    assert "dev" not in extras, (
        "the dev extra is back: maintainer tooling belongs in [dependency-groups], "
        "which is not published in the wheel's metadata"
    )


@_needs_tomllib
def test_published_extras_carry_no_maintainer_tooling() -> None:
    extras = _pyproject()["project"]["optional-dependencies"]

    for name, entries in extras.items():
        if name == "docs":  # documented as a user-facing extra
            continue
        leaked = _requirement_names(entries) & _MAINTAINER_ONLY
        assert not leaked, f"extra {name!r} publishes maintainer tooling: {sorted(leaked)}"


@_needs_tomllib
def test_dev_group_holds_the_maintainer_tooling() -> None:
    groups = _pyproject()["dependency-groups"]

    direct = _requirement_names(groups["dev"]) | _requirement_names(groups["test-runners"])
    assert direct == _MAINTAINER_ONLY, (
        "the dev group and the maintainer-only set disagree; "
        f"missing={sorted(_MAINTAINER_ONLY - direct)} "
        f"unexpected={sorted(direct - _MAINTAINER_ONLY)}"
    )


@_needs_tomllib
def test_dev_group_includes_the_runner_group_rather_than_copying_it() -> None:
    groups = _pyproject()["dependency-groups"]

    assert {"include-group": "test-runners"} in groups["dev"], (
        "dev must include the test-runners group, not restate the runners — "
        "a second copy is what drifted before #550"
    )
    assert not (_requirement_names(groups["dev"]) & _requirement_names(groups["test-runners"]))


@_needs_tomllib
def test_integrations_extra_covers_every_integration_extra() -> None:
    extras = _pyproject()["project"]["optional-dependencies"]

    assert len(extras["integrations"]) == 1, "the composition is one self-reference"
    inside = re.search(r"\[([^\]]+)\]", extras["integrations"][0])
    assert inside is not None, extras["integrations"][0]
    referenced = {part.strip() for part in inside.group(1).split(",")}

    assert referenced == _INTEGRATION_EXTRAS, (
        "the integrations composition and the integration extras disagree; "
        f"missing={sorted(_INTEGRATION_EXTRAS - referenced)} "
        f"unexpected={sorted(referenced - _INTEGRATION_EXTRAS)}"
    )
    # llm-anthropic / llm-openai pull real provider SDKs; evals.yml adds the one
    # it needs explicitly, so the shared composition must not drag both in.
    assert "llm-anthropic" not in referenced
    assert "llm-openai" not in referenced


def test_no_workflow_installs_a_dev_extra() -> None:
    for name, text in _workflow_texts().items():
        assert ".[dev]" not in text, f"{name} installs the removed dev extra"
        assert "[dev," not in text, f"{name} installs the removed dev extra"


def test_workflows_do_not_hand_copy_the_pytest_runners() -> None:
    """A workflow that names a pytest runner and its floor is a second copy."""
    hand_copied = re.compile(r'"pytest(-cov|-asyncio|-timeout)?>=')

    for name, text in _workflow_texts().items():
        assert not hand_copied.search(text), (
            f"{name} pins a pytest runner inline; use --group test-runners so the "
            "floor is declared once in pyproject.toml"
        )


def test_group_installs_upgrade_pip_first() -> None:
    """``pip install --group`` needs pip >= 25.1 — do not assume the image's."""
    for name, text in _workflow_texts().items():
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped.startswith("pip install") or "--group" not in stripped:
                continue
            assert "python -m pip install --upgrade pip" in text, (
                f"{name} runs `pip install --group` without upgrading pip first; "
                "PEP 735 support landed in pip 25.1"
            )
