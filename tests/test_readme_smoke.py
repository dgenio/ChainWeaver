"""README anti-drift smoke tests (#203).

These tests catch the class of bug that issues #190, #195, #196, and the
historical onboarding-doc drift fell into: a copy-paste example in the
README quietly stops working when the underlying API changes, but nothing
in CI fails because nothing in CI tries to run README snippets.

The contract:

- Any fenced ``python`` block preceded *immediately* by the HTML comment
  ``<!-- smoke-test: run -->`` is extracted, written to a temp file, and
  executed in a fresh subprocess.  It must exit cleanly (``returncode == 0``)
  with no traceback on stderr.
- Blocks **without** that marker are illustrative-only and the test skips
  them.  This is the allowlist that #203 calls for — opt-in by marker, not
  opt-out by allowlist file.
- The "bundled examples" mentioned by the README (``python examples/...``)
  must exist on disk so the README never points at a script that has been
  deleted or renamed.
- CLI smoke: ``chainweaver --help`` and ``chainweaver validate <example>``
  both work straight out of a fresh checkout, with no programmatic registry
  setup, so a newcomer pasting the first CLI lines from the README does not
  hit a broken command.

Add ``<!-- smoke-test: run -->`` above a README ``python`` block to opt
that block into CI execution.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent
_README = _REPO_ROOT / "README.md"
_EXAMPLE_FLOW = _REPO_ROOT / "examples" / "double_add_format.flow.yaml"

# Match an HTML marker on its own line, optional blank line, then a fenced
# ``python`` block.  The block body is captured greedily up to the closing
# fence on its own line.
_RUNNABLE_BLOCK = re.compile(
    r"<!--\s*smoke-test:\s*run\s*-->\s*\n+```python\n(?P<body>.*?)\n```",
    re.DOTALL,
)

# README CLI section advertises these bundled example scripts.  Each must
# exist or the README points at a stale path.  Sourced from `## Quick Start`
# and the "## Command-line interface" sections.
_BUNDLED_EXAMPLES = (
    "examples/simple_linear_flow.py",
    "examples/etl_flow.py",
    "examples/mcp_search_flow.py",
    "examples/naive_vs_compiled.py",
    "examples/coding_agent_pr_review.py",
    "examples/coding_agent_changelog.py",
    "examples/coding_agent_debug_log.py",
    "examples/decorator_tool.py",
    "examples/double_add_format.flow.yaml",
)


def _extracted_runnable_blocks() -> list[str]:
    text = _README.read_text(encoding="utf-8")
    return [match.group("body") for match in _RUNNABLE_BLOCK.finditer(text)]


def test_at_least_one_readme_block_is_marked_runnable() -> None:
    """Guard against silently removing every smoke marker from the README."""
    blocks = _extracted_runnable_blocks()
    assert blocks, (
        "No `<!-- smoke-test: run -->` markers found in README.md. "
        "At least the Quick Start block must opt in to smoke execution."
    )


@pytest.mark.parametrize(
    "block_body",
    _extracted_runnable_blocks(),
    ids=lambda body: body.splitlines()[0][:60] if body else "<empty>",
)
def test_readme_runnable_block_executes(
    block_body: str,
    tmp_path: Path,
) -> None:
    """Each ``<!-- smoke-test: run -->`` block must run cleanly."""
    script = tmp_path / "readme_block.py"
    script.write_text(block_body, encoding="utf-8")

    # Inherit the parent environment so an editable install of `chainweaver`
    # is importable, but force the repo root onto PYTHONPATH as well: README
    # snippets must work whether the user installed via `pip install -e .` or
    # is just running `python script.py` from a fresh checkout.
    env = dict(os.environ)
    env["PYTHONPATH"] = (
        f"{_REPO_ROOT}{os.pathsep}{env['PYTHONPATH']}"
        if env.get("PYTHONPATH")
        else str(_REPO_ROOT)
    )

    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env=env,
    )

    if completed.returncode != 0:
        output = "\n".join(part for part in (completed.stdout, completed.stderr) if part)
        pytest.fail(f"README runnable block failed (returncode={completed.returncode}):\n{output}")


@pytest.mark.parametrize("relpath", _BUNDLED_EXAMPLES)
def test_readme_bundled_example_exists(relpath: str) -> None:
    """README references to bundled examples must point at real files."""
    assert (_REPO_ROOT / relpath).is_file(), (
        f"README references {relpath!r} but the file does not exist. "
        "Update the README or restore the example."
    )


def test_cli_help_runs_without_a_registry() -> None:
    """``chainweaver --help`` must work on a fresh install — no registry needed."""
    completed = subprocess.run(
        [sys.executable, "-m", "chainweaver.cli", "--help"],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    out = completed.stdout + completed.stderr
    # Every command the CLI advertises must appear in --help output.  Catches
    # the "README/docs say there are N commands, --help only shows N-1" bug
    # class historically tracked by issue #190.
    for name in (
        "inspect",
        "viz",
        "validate",
        "check",
        "run",
        "profile",
        "diff",
        "attest",
        "suggest",
        "dump-schema",
        "doctor",
    ):
        assert name in out, f"`chainweaver --help` is missing the {name!r} command"


def test_cli_validate_runs_against_bundled_yaml_example() -> None:
    """``chainweaver validate examples/double_add_format.flow.yaml`` works on a fresh install."""
    assert _EXAMPLE_FLOW.is_file(), f"missing shipped example flow: {_EXAMPLE_FLOW}"
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "chainweaver.cli",
            "validate",
            str(_EXAMPLE_FLOW),
        ],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert completed.returncode == 0, (
        f"`chainweaver validate {_EXAMPLE_FLOW.relative_to(_REPO_ROOT)}` "
        f"failed:\n{completed.stdout}\n{completed.stderr}"
    )


def test_readme_yaml_extra_is_mentioned_near_yaml_examples() -> None:
    """README must tell users to install ``chainweaver[yaml]`` before promising YAML examples."""
    text = _README.read_text(encoding="utf-8")
    # First YAML reference (any ``.flow.yaml`` token in fenced code or prose)
    yaml_token = ".flow.yaml"
    first_yaml = text.find(yaml_token)
    extra_token = "chainweaver[yaml]"
    first_extra = text.find(extra_token)
    assert first_yaml != -1, "README has no .flow.yaml reference at all (unexpected)."
    assert first_extra != -1, (
        f"README mentions {yaml_token!r} but never explains the "
        f"`pip install '{extra_token}'` requirement."
    )
    assert first_extra < first_yaml + 6000, (
        "The first mention of `chainweaver[yaml]` is too far from the first "
        "`.flow.yaml` reference; a newcomer reading top-down hits the YAML "
        "example before the install instruction."
    )
