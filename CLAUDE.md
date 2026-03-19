# CLAUDE.md — ChainWeaver

This file is the entry point for Claude Code. All project context, architecture details,
coding conventions, and guardrails are maintained in a single canonical source:

→ **Read [AGENTS.md](AGENTS.md) before making any changes.**

## Quick invariants (also in AGENTS.md § Core invariants)

1. No LLM calls in `executor.py` — deterministic by design.
2. All exceptions inherit from `ChainWeaverError`.
3. All public symbols exported in `__init__.py` `__all__`.
4. `from __future__ import annotations` at the top of every module.
5. All code must pass: `ruff check`, `ruff format --check`, `mypy`, `pytest`.
