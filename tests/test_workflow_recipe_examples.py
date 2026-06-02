"""Smoke tests for the framework-recipe and workflow-template examples.

Covers the example scripts added for issues #204, #205, #206, #211, and #213.
Each script follows the standalone-script rule for ``examples/`` (no pytest
imports, asserts inline) and must keep running cleanly from a fresh checkout so
the docs that reference it cannot silently rot.

The two integration recipes (#205 LangGraph, #206 OpenAI Agents SDK) need an
optional extra; their tests skip when the extra is not installed, mirroring
``tests/test_integrations_langchain.py``.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _run_script(relative_path: str) -> subprocess.CompletedProcess[str]:
    """Run an example script via ``python examples/...`` from the repo root."""
    return subprocess.run(
        [sys.executable, str(ROOT / relative_path)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


# ---------------------------------------------------------------------------
# Dependency-free examples (#204, #211, #213)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("examples/mcp_style_before_after_demo.py", "Decisions avoided : 4"),
        ("examples/release_readiness_flow/release_readiness.py", "[READY]"),
        ("examples/skdr_policy_eval_flow.py", "[continue]"),
    ],
    ids=["before_after_204", "release_readiness_211", "policy_eval_213"],
)
def test_dependency_free_example_runs(script: str, expected: str) -> None:
    completed = _run_script(script)
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    assert completed.returncode == 0, output
    assert expected in completed.stdout, output


def test_release_readiness_shows_both_branches() -> None:
    """The release-readiness demo must exercise both the ready and blocked edges."""
    completed = _run_script("examples/release_readiness_flow/release_readiness.py")
    assert completed.returncode == 0, completed.stderr
    assert "[READY]" in completed.stdout
    assert "[BLOCKED]" in completed.stdout


def test_policy_eval_shows_all_three_gates() -> None:
    """The policy-eval demo must show the continue / manual_review / block gates."""
    completed = _run_script("examples/skdr_policy_eval_flow.py")
    assert completed.returncode == 0, completed.stderr
    for gate in ("[continue]", "[manual_review]", "[block]"):
        assert gate in completed.stdout, completed.stdout


# ---------------------------------------------------------------------------
# Integration recipes (#205, #206) — skip when the optional extra is missing
# ---------------------------------------------------------------------------


def test_langgraph_node_recipe_runs() -> None:
    pytest.importorskip("langgraph")
    completed = _run_script("examples/integrations/langgraph_node.py")
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    assert completed.returncode == 0, output
    assert "word_count : 3" in completed.stdout, output


def test_openai_agents_tool_recipe_runs() -> None:
    pytest.importorskip("agents")
    completed = _run_script("examples/integrations/openai_agents_tool.py")
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    assert completed.returncode == 0, output
    assert "tool name   : price_with_tax" in completed.stdout, output


def test_weaver_stack_golden_path_runs() -> None:
    """The route -> execute -> gate demo runs the full path with the extra (#233, #234)."""
    pytest.importorskip("weaver_contracts")
    completed = _run_script("examples/weaver_stack_golden_path/weaver_stack_golden_path.py")
    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    assert completed.returncode == 0, output
    assert "contextweaver routed -> 'report.generate'" in completed.stdout, output
    assert "[weaver-stack] golden path OK" in completed.stdout, output


def test_weaver_stack_golden_path_degrades_without_extra() -> None:
    """Without the extra the demo prints a skip notice and exits 0 (#234)."""
    import importlib.util

    if importlib.util.find_spec("weaver_contracts") is not None:
        pytest.skip("weaver-contracts installed; graceful-degrade path not exercised")
    completed = _run_script("examples/weaver_stack_golden_path/weaver_stack_golden_path.py")
    assert completed.returncode == 0, completed.stderr
    assert "[weaver-stack] skipped" in completed.stdout, completed.stdout
