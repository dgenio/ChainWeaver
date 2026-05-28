"""Anti-drift guards for the CLI documentation and the shipped example flow.

These tests fail when:

- a CLI command is added without a matching reference section in
  ``docs/cli.md`` (issues #193, #197); or
- the example flow file referenced by the README / ``docs/cli.md`` quick
  start stops validating or running end-to-end (issue #195).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from chainweaver import cli
from chainweaver.cli import app

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CLI_DOC = _REPO_ROOT / "docs" / "cli.md"
_EXAMPLE_FLOW = _REPO_ROOT / "examples" / "double_add_format.flow.yaml"


def _registered_command_names() -> list[str]:
    """Return every command name registered on the typer ``app``."""
    names = [
        command.name or (command.callback.__name__ if command.callback else "")
        for command in app.registered_commands
    ]
    return [name for name in names if name]


def test_every_cli_command_has_a_docs_section() -> None:
    doc_text = _CLI_DOC.read_text(encoding="utf-8")
    missing = [
        name
        for name in _registered_command_names()
        if not re.search(rf"(?m)^###\s+`{re.escape(name)}`\s*$", doc_text)
    ]
    assert not missing, f"docs/cli.md is missing reference sections for: {missing}"


def test_example_flow_file_ships_with_type_discriminator() -> None:
    assert _EXAMPLE_FLOW.is_file(), f"missing shipped example flow: {_EXAMPLE_FLOW}"
    text = _EXAMPLE_FLOW.read_text(encoding="utf-8")
    assert "type: Flow" in text


def test_example_flow_file_validates(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.syspath_prepend(str(_REPO_ROOT))
    exit_code = cli.main(["validate", str(_EXAMPLE_FLOW)])
    assert exit_code == 0


def test_example_flow_file_runs_end_to_end(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.syspath_prepend(str(_REPO_ROOT))
    exit_code = cli.main(
        [
            "run",
            str(_EXAMPLE_FLOW),
            "--tools",
            "examples.simple_linear_flow",
            "--input",
            '{"number": 5}',
        ]
    )
    assert exit_code == 0
    out = capsys.readouterr().out
    assert '"result": "Final value: 20"' in out
