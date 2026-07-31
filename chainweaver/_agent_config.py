"""Shared, editor-agnostic config helpers for coding-agent integrations.

The OpenCode (#276-#280), Claude Code (#271/#273), and VS Code (#269) setup
commands all merge a single ChainWeaver ``FlowServer`` entry into an editor's
MCP-server map and back files up before writing. The only thing that differs
between editors is the *key* that holds the server map:

* OpenCode  → ``"mcp"``
* Claude Code → ``"mcpServers"``
* VS Code   → ``"servers"``

This module holds the one copy of that merge/remove/backup logic, parameterized
by ``servers_key``, so the three thin adapters (:mod:`chainweaver.opencode`,
:mod:`chainweaver.claude`, :mod:`chainweaver.vscode`) don't each re-derive it.
It is private (underscore-prefixed): the editor modules expose their own
key-bound wrappers as the public surface.

Like the rest of the coding-agent tooling it is offline and deterministic, and
is banned from :mod:`chainweaver.executor`.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any


def add_flow_server(
    config: Mapping[str, Any] | None,
    entry: Mapping[str, Any],
    *,
    servers_key: str,
    name: str,
) -> dict[str, Any]:
    """Return a copy of *config* with the ChainWeaver server *entry* merged in.

    Existing, unrelated servers under *servers_key* are preserved; only the
    ChainWeaver entry (keyed by *name*) is added or replaced. *config* is never
    mutated.

    Args:
        config: The existing editor config (or ``None`` for a fresh one).
        entry: The MCP server command entry to install.
        servers_key: The editor-specific key holding the server map
            (``"mcp"`` / ``"mcpServers"`` / ``"servers"``).
        name: The server-map key ChainWeaver manages.
    """
    new_config: dict[str, Any] = dict(config) if isinstance(config, Mapping) else {}
    servers_obj = new_config.get(servers_key)
    servers = dict(servers_obj) if isinstance(servers_obj, Mapping) else {}
    servers[name] = dict(entry)
    new_config[servers_key] = servers
    return new_config


def remove_flow_server(
    config: Mapping[str, Any] | None,
    *,
    servers_key: str,
    name: str,
) -> tuple[dict[str, Any], bool]:
    """Return (*config copy without the ChainWeaver entry*, *removed?*).

    Only the ChainWeaver-managed entry (keyed by *name* under *servers_key*) is
    removed; all other editor config — including unrelated servers — is left
    untouched. The server map is dropped entirely when it becomes empty.
    """
    new_config: dict[str, Any] = dict(config) if isinstance(config, Mapping) else {}
    servers_obj = new_config.get(servers_key)
    if not isinstance(servers_obj, Mapping) or name not in servers_obj:
        return new_config, False
    servers = {key: value for key, value in servers_obj.items() if key != name}
    if servers:
        new_config[servers_key] = servers
    else:
        new_config.pop(servers_key, None)
    return new_config, True


def backup_file(path: Path) -> Path | None:
    """Copy *path* to ``<path>.bak`` before modifying it; return the backup.

    Returns ``None`` when *path* does not yet exist (nothing to back up).
    """
    if not path.is_file():
        return None
    backup = path.with_suffix(path.suffix + ".bak")
    backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
    return backup
