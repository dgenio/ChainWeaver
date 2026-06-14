"""Tests for ``chainweaver`` shell completion (issue #436)."""

from __future__ import annotations

import pytest
from typer.testing import CliRunner

from chainweaver import cli

_RUNNER = CliRunner()

# Every command/sub-app the CLI advertises; completion must cover them all.
_EXPECTED_COMMANDS = (
    "inspect",
    "viz",
    "validate",
    "check",
    "run",
    "serve",
    "profile",
    "diff",
    "attest",
    "suggest",
    "record",
    "doctor",
    "fuzz",
    "dump-schema",
    "service",
    "flows",
    "traces",
)


class TestCompletionEnabled:
    def test_help_exposes_completion_options(self) -> None:
        result = _RUNNER.invoke(cli.app, ["--help"])
        assert result.exit_code == 0
        assert "--install-completion" in result.stdout
        assert "--show-completion" in result.stdout

    def test_help_lists_every_command(self) -> None:
        result = _RUNNER.invoke(cli.app, ["--help"])
        assert result.exit_code == 0
        for name in _EXPECTED_COMMANDS:
            assert name in result.stdout, f"--help is missing the {name!r} command"

    @pytest.mark.parametrize("shell", ["bash", "zsh", "fish"])
    def test_show_completion_emits_a_script(self, shell: str) -> None:
        result = _RUNNER.invoke(cli.app, ["--show-completion", shell])
        assert result.exit_code == 0
        # The generated script references the program's completion machinery.
        assert "_CHAINWEAVER_COMPLETE" in result.stdout or "chainweaver" in result.stdout
