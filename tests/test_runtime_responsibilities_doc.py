"""Anti-drift guards for ``docs/runtime-responsibilities.md`` (#208).

These tests fail when:

- the page goes missing from ``docs/`` (e.g. someone moves it without
  updating the references);
- a top-level section the issue's acceptance criteria call for disappears;
- the README stops linking to it from the MCP integration section
  (#208 acceptance criterion: "README links to it from the architecture
  or MCP section");
- ``mkdocs.yml`` stops including it in the published nav.
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
_DOC = _REPO_ROOT / "docs" / "runtime-responsibilities.md"
_README = _REPO_ROOT / "README.md"
_MKDOCS = _REPO_ROOT / "mkdocs.yml"

# Section H2 headings the page must keep — these map 1:1 to the
# responsibilities #208 enumerates in its acceptance criteria.
_REQUIRED_SECTIONS: tuple[str, ...] = (
    "1. Deciding when to invoke a flow",
    "2. Treating stored execution traces",
    "3. Describing tools with side effects",
    "4. Treating compiled flows as higher-level operations",
    "5. MCP examples must preserve the same expectations",
)


def test_runtime_responsibilities_page_exists() -> None:
    assert _DOC.is_file(), f"missing docs page: {_DOC}"


def test_runtime_responsibilities_page_has_required_sections() -> None:
    text = _DOC.read_text(encoding="utf-8")
    missing = [heading for heading in _REQUIRED_SECTIONS if f"## {heading}" not in text]
    assert not missing, (
        f"docs/runtime-responsibilities.md is missing required H2 sections: {missing}"
    )


def test_runtime_responsibilities_page_includes_concrete_example() -> None:
    """Acceptance criterion: the page includes one concrete example."""
    text = _DOC.read_text(encoding="utf-8")
    # The example uses ``handle_request`` as its entry point — a stable marker.
    assert "```python" in text, "page must include at least one Python code block"
    assert "handle_request" in text, (
        "the concrete example (host's `handle_request`) is missing from the page"
    )


def test_readme_links_to_runtime_responsibilities_page() -> None:
    """Acceptance criterion: README links to it from architecture or MCP section."""
    text = _README.read_text(encoding="utf-8")
    assert "docs/runtime-responsibilities.md" in text, (
        "README.md must link to docs/runtime-responsibilities.md "
        "(currently missing — see issue #208 acceptance criteria)."
    )


def test_mkdocs_includes_runtime_responsibilities_in_nav() -> None:
    text = _MKDOCS.read_text(encoding="utf-8")
    assert "runtime-responsibilities.md" in text, (
        "mkdocs.yml nav does not reference runtime-responsibilities.md — "
        "the page would build but not show up in the hosted site nav."
    )
