"""Dependency- and import-contract guards for the minimal-core promise.

ChainWeaver's positioning rests on two related, currently-implicit guarantees:

* **Zero-LLM-SDK base package** (#378): installing ``chainweaver`` never drags
  in a provider SDK (``openai`` / ``anthropic`` / ``langchain`` / …) and
  importing it at runtime imports none of them. The provider-agnostic ``LLMFn``
  seam and the offline proposers keep provider libraries behind optional extras.
* **Minimal-core, optional-extras scope** (#431): the base runtime dependency
  set is deliberately small (five packages); every integration or heavy
  capability lives behind an optional extra. New base dependencies should be a
  reviewed, explicit decision — not an accident.

Both are documented in ``docs/comparisons.md`` / AGENTS.md but were unenforced.
These tests turn them into mechanical CI guards, mirroring
``test_executor_import_contract.py``. A related concern (#418) — that the base
import stays cold-start cheap and never eagerly pulls a heavy optional module —
is covered by the same import-isolation check here; the wall-clock half of #418
belongs in the (non-blocking) benchmark lane, not a timing assertion in pytest.
"""

from __future__ import annotations

import subprocess
import sys
from importlib.metadata import requires

from packaging.requirements import Requirement

# The five packages the base install is allowed to depend on. Keep in lockstep
# with ``[project.dependencies]`` in pyproject.toml and AGENTS.md §1. Adding a
# name here is the explicit, reviewed sign-off #431 asks for.
ALLOWED_BASE_DEPENDENCIES = frozenset(
    {
        "deepdiff",
        "packaging",
        "pydantic",
        "tenacity",
        "typer",
    }
)

# Modules that must never be imported by ``import chainweaver`` (the base
# package). Provider SDKs (#378) plus heavy optional integrations and any
# network/IO client (#418 cold-start guard). Each lives behind an extra.
FORBIDDEN_BASE_IMPORTS = frozenset(
    {
        "openai",
        "anthropic",
        "langchain_core",
        "langgraph",
        "llama_index",
        "mcp",
        "fastmcp",
        "opentelemetry",
        "weaver_contracts",
        "httpx",
        "requests",
        "aiohttp",
    }
)

# Provider-SDK distribution names that must never appear as a base dependency
# (#378). A subset of the forbidden-import set, expressed as PyPI names.
PROVIDER_SDK_NAMES = frozenset(
    {
        "openai",
        "anthropic",
        "langchain-core",
        "langgraph",
        "llama-index-core",
        "mcp",
        "fastmcp",
    }
)


def _declared_base_dependencies() -> set[str]:
    """Return the distribution's unconditional (non-extra) dependency names."""
    base: set[str] = set()
    for raw in requires("chainweaver") or []:
        req = Requirement(raw)
        # A dependency gated behind an extra carries an ``extra == "..."`` marker;
        # base deps have no marker.
        if req.marker is None:
            base.add(req.name)
    return base


def test_base_dependencies_match_allowlist() -> None:
    """The base runtime dependency set is exactly the reviewed allowlist (#431)."""
    declared = _declared_base_dependencies()
    unexpected = declared - ALLOWED_BASE_DEPENDENCIES
    missing = ALLOWED_BASE_DEPENDENCIES - declared
    assert not unexpected, (
        "New base runtime dependency introduced without sign-off "
        f"(#431): {sorted(unexpected)}. If this is intended, add it to "
        "ALLOWED_BASE_DEPENDENCIES and pyproject.toml [project.dependencies], "
        "and document the decision in AGENTS.md."
    )
    assert not missing, (
        f"Declared base dependencies dropped below the allowlist: {sorted(missing)}. "
        "Update ALLOWED_BASE_DEPENDENCIES to match pyproject.toml."
    )


def test_no_provider_sdk_in_base_dependencies() -> None:
    """No LLM-provider SDK is an unconditional dependency (#378)."""
    declared = _declared_base_dependencies()
    leaked = declared & PROVIDER_SDK_NAMES
    assert not leaked, (
        f"Provider SDK(s) {sorted(leaked)} leaked into base dependencies (#378). "
        "Provider libraries must stay behind an optional extra."
    )


def test_base_import_pulls_no_forbidden_module() -> None:
    """``import chainweaver`` imports no provider SDK or heavy optional module.

    Runs in a fresh interpreter so the result is unaffected by modules other
    tests already imported into this process. The guarantee is meaningfully
    enforced when the optional dependencies are installed (as in CI's ``[dev]``
    lane): if a module is not installed it simply cannot appear in
    ``sys.modules``, so this test can only pass — never falsely fail — in a
    minimal environment.
    """
    forbidden = sorted(FORBIDDEN_BASE_IMPORTS)
    program = (
        "import json, sys\n"
        "import chainweaver  # noqa: F401\n"
        f"forbidden = {forbidden!r}\n"
        "print(json.dumps([m for m in forbidden if m in sys.modules]))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        check=True,
    )
    leaked = __import__("json").loads(result.stdout.strip() or "[]")
    assert not leaked, (
        f"import chainweaver eagerly imported forbidden module(s): {leaked} "
        "(#378/#418). Move the offending import behind its optional extra or "
        "make it lazy."
    )
