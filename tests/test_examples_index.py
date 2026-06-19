"""Anti-drift test for the examples index (#409).

`examples/README.md` is a categorized index of the standalone scripts in
`examples/`. Without a guard it rots the moment someone adds a script and
forgets to list it. This test enumerates every root-level ``examples/*.py``
script and asserts it is referenced in the index, so a newcomer's map of the
examples directory cannot silently fall behind the directory itself.

Only root-level scripts are enforced. Multi-file examples in subdirectories
(``cookbook/``, ``integrations/``, ``release_readiness_flow/``,
``weaver_stack_golden_path/``) are covered by their own narrative sections.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_EXAMPLES_DIR = _REPO_ROOT / "examples"
_INDEX = _EXAMPLES_DIR / "README.md"


def _root_example_scripts() -> list[str]:
    """Filenames of the root-level ``examples/*.py`` scripts, sorted."""
    return sorted(p.name for p in _EXAMPLES_DIR.glob("*.py"))


def test_examples_index_exists() -> None:
    """The index file must exist (it is the entry point newcomers land on)."""
    assert _INDEX.is_file(), f"missing examples index: {_INDEX}"


def test_there_is_at_least_one_root_example() -> None:
    """Guard against the enforcement below silently passing on an empty glob."""
    assert _root_example_scripts(), "no root-level examples/*.py scripts found"


@pytest.mark.parametrize("script", _root_example_scripts())
def test_root_example_is_listed_in_index(script: str) -> None:
    """Every ``examples/*.py`` script must be referenced in ``examples/README.md``."""
    index_text = _INDEX.read_text(encoding="utf-8")
    assert script in index_text, (
        f"examples/{script} exists but is not listed in examples/README.md. "
        f"Add it to the appropriate section of the index."
    )
