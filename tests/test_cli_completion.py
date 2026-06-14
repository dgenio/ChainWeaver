"""Tests for ``chainweaver`` shell completion (issue #436)."""

from __future__ import annotations

import re

import pytest
from typer.testing import CliRunner

from chainweaver import cli

_RUNNER = CliRunner()

# Typer renders --help through Rich, which colours option names with ANSI escape
# codes that split the leading dashes into separate spans (``-`` ``-install`` …).
# Strip them so substring assertions are stable across TTY / no-TTY environments.
_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _plain(text: str) -> str:
    return _ANSI_RE.sub("", text)


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
        out = _plain(result.stdout)
        assert "--install-completion" in out
        assert "--show-completion" in out

    def test_help_lists_every_command(self) -> None:
        result = _RUNNER.invoke(cli.app, ["--help"])
        assert result.exit_code == 0
        out = _plain(result.stdout)
        for name in _EXPECTED_COMMANDS:
            assert name in out, f"--help is missing the {name!r} command"

    @pytest.mark.parametrize("shell", ["bash", "zsh", "fish"])
    def test_show_completion_emits_a_script(self, shell: str) -> None:
        result = _RUNNER.invoke(cli.app, ["--show-completion", shell])
        assert result.exit_code == 0
        # The generated script references the program's completion machinery.
        assert "_CHAINWEAVER_COMPLETE" in result.stdout or "chainweaver" in result.stdout
