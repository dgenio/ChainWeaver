"""Smoke tests for hosted-docs cookbook example scripts (#146)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
COOKBOOK_SCRIPTS = sorted((ROOT / "examples" / "cookbook").glob("recipe_*.py"))
assert COOKBOOK_SCRIPTS, "Expected cookbook recipe scripts under examples/cookbook/."


@pytest.mark.parametrize("script", COOKBOOK_SCRIPTS, ids=lambda path: path.name)
def test_cookbook_recipe_script_runs_cleanly(script: Path) -> None:
    """Each cookbook recipe is a standalone script that must stay runnable."""
    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
    assert completed.returncode == 0, output
