"""Offline eval harnesses for the LLM-backed proposers (issues #365, #374).

These live outside the ``chainweaver`` package — like ``benchmarks/`` — because
they are run on demand, never in the library runtime.  The harness code runs in
normal CI against a deterministic stub model (validating the plumbing); an
opt-in workflow runs it against real providers using repo secrets.
"""
