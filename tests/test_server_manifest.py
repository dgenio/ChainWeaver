"""Guard the MCP registry manifest (``server.json``) against regressions (#250).

These checks encode the two in-repo registry-publish prerequisites:

1. The declared ``version`` stays aligned with the package version, so the
   manifest never advertises a release that does not match the code.
2. A fresh ``uvx`` client launch resolves the ``[mcp]`` extra and is handed a
   required flow file, so the served command can actually start.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import chainweaver

_MANIFEST = Path(__file__).resolve().parents[1] / "server.json"
_README = Path(__file__).resolve().parents[1] / "README.md"
_MCP_NAME_MARKER = "<!-- mcp-name: io.github.dgenio/chainweaver -->"


def _load_manifest() -> dict[str, Any]:
    manifest: dict[str, Any] = json.loads(_MANIFEST.read_text(encoding="utf-8"))
    return manifest


def _pypi_package(manifest: dict[str, Any]) -> dict[str, Any]:
    pypi: list[dict[str, Any]] = [
        pkg for pkg in manifest["packages"] if pkg.get("registryType") == "pypi"
    ]
    assert len(pypi) == 1, "Expected exactly one PyPI package entry in server.json."
    return pypi[0]


def test_manifest_is_valid_json() -> None:
    manifest = _load_manifest()
    assert manifest["$schema"] == (
        "https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json"
    )
    assert manifest["name"] == "io.github.dgenio/chainweaver"
    assert len(manifest["description"]) <= 100


def test_manifest_version_matches_package() -> None:
    manifest = _load_manifest()
    assert manifest["version"] == chainweaver.__version__
    assert _pypi_package(manifest)["version"] == chainweaver.__version__


def test_uvx_launch_resolves_mcp_extra() -> None:
    """A fresh client must install ``chainweaver[mcp]``, not bare ``chainweaver``."""
    package = _pypi_package(_load_manifest())
    assert package["registryBaseUrl"] == "https://pypi.org"
    assert package["identifier"] == "chainweaver"
    assert package["runtimeHint"] == "uvx"
    assert package["transport"] == {"type": "stdio"}
    runtime_args = package.get("runtimeArguments", [])
    from_args = [
        arg for arg in runtime_args if arg.get("type") == "named" and arg.get("name") == "--from"
    ]
    assert from_args, "server.json must pass '--from' so uvx resolves the [mcp] extra."
    assert from_args[0]["value"] == "chainweaver[mcp]"


def test_serve_command_takes_required_flow_file() -> None:
    package = _pypi_package(_load_manifest())
    package_args = package["packageArguments"]
    assert package_args[0]["value"] == "serve"
    required_positional = [
        arg for arg in package_args if arg.get("type") == "positional" and arg.get("isRequired")
    ]
    assert required_positional, "server.json must require a flow-file positional."
    assert required_positional[0]["valueHint"] == "flow_file"
    assert required_positional[0]["format"] == "filepath"


def test_tools_module_argument_is_optional_and_repeatable() -> None:
    package_args = _pypi_package(_load_manifest())["packageArguments"]
    tools_args = [
        arg for arg in package_args if arg.get("type") == "named" and arg.get("name") == "--tools"
    ]
    assert len(tools_args) == 1
    assert tools_args[0]["isRepeated"] is True
    assert tools_args[0]["isRequired"] is False
    assert "value" not in tools_args[0]


def test_pypi_readme_contains_registry_ownership_marker() -> None:
    readme = _README.read_text(encoding="utf-8")
    assert readme.count(_MCP_NAME_MARKER) == 1
