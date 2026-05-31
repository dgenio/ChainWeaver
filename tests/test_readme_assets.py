"""Guard the README landing-page assets against rot (issues #225, #227, #228, #229, #232).

These are cheap structural checks — they assert the committed assets exist and
that the README actually references them, so a future edit can't silently drop
the demo cast, the Colab notebook, the benchmark headline, or the Weaver Stack
diagram. They deliberately avoid asserting exact prose (which is expected to
change) and check for stable anchors instead.
"""

from __future__ import annotations

import json
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_README = (_REPO / "README.md").read_text(encoding="utf-8")


def test_demo_svg_committed_and_animated() -> None:
    """The demo cast (#228) is committed, animated, and shows real run output."""
    svg = _REPO / "docs" / "assets" / "quickstart.svg"
    assert svg.is_file(), "demo asset docs/assets/quickstart.svg is missing"
    body = svg.read_text(encoding="utf-8")
    assert "<svg" in body
    assert "@keyframes" in body, "SVG should be animated (CSS keyframes)"
    # Rendered from the real example output, not a hand-drawn mockup.
    assert "double_add_format" in body and "Final value" in body


def test_readme_embeds_demo_as_first_visual() -> None:
    """README embeds the demo SVG (#228) above the first prose section."""
    assert "docs/assets/quickstart.svg" in _README
    assert _README.index("docs/assets/quickstart.svg") < _README.index("## See it in 30 seconds")


def test_readme_has_colab_badge_to_notebook() -> None:
    """README carries an Open-in-Colab badge pointing at the quickstart notebook (#229)."""
    assert "Open in Colab" in _README
    colab_url = (
        "colab.research.google.com/github/dgenio/ChainWeaver/blob/main/notebooks/quickstart.ipynb"
    )
    assert colab_url in _README


def test_quickstart_notebook_is_valid_and_self_installing() -> None:
    """The Colab notebook (#229) is valid nbformat 4 and installs ChainWeaver when absent."""
    nb_path = _REPO / "notebooks" / "quickstart.ipynb"
    assert nb_path.is_file(), "notebooks/quickstart.ipynb is missing"
    nb = json.loads(nb_path.read_text(encoding="utf-8"))
    assert nb["nbformat"] == 4
    sources = ["".join(c.get("source", [])) for c in nb["cells"]]
    joined = "\n".join(sources)
    # Defensive install so the notebook runs both in Colab and in CI's nbmake.
    assert "pip" in joined and "chainweaver[yaml]" in joined
    # Exercises the documented surface: @tool, execution, and export adapters.
    assert "@tool" in joined
    assert "execute_flow" in joined
    assert "flow_to_openai_function" in joined


def test_readme_headline_number_links_report() -> None:
    """README hero surfaces a quantified, reproducible claim linked to the report (#227)."""
    report = _REPO / "benchmarks" / "results" / "latest.md"
    assert report.is_file(), "benchmark report artifact is missing"
    assert "benchmarks/results/latest.md" in _README
    assert "python benchmarks/report.py" in _README
    # The defensible headline metric: zero data corruption vs naive chaining.
    assert "0%" in _README


def test_readme_has_standardized_weaver_stack_section() -> None:
    """README has the standardized 'Part of the Weaver Stack' block + diagram (#232)."""
    assert "## Part of the Weaver Stack" in _README or "### Part of the Weaver Stack" in _README
    # The shared request-path diagram names every stage.
    for node in ("contextweaver", "agent-kernel", "agentfence"):
        assert node in _README, f"Weaver Stack diagram missing node: {node}"
    assert "no hard dependency" in _README.lower()


def test_readme_no_longer_leads_with_demoted_hero() -> None:
    """The old 'save LLM calls' hero tagline is demoted, not the lead (#225)."""
    stale = "Compile deterministic tool flows into LLM-free executable runs."
    assert stale not in _README
