"""The Claude Code / VS Code adapters are experimental and namespaced (#518).

Per maintainer direction, these vendor observe adapters must be reachable only
through their explicit module namespaces (``chainweaver.claude`` /
``chainweaver.vscode``) and must NOT be part of the stable top-level
``chainweaver.__all__`` surface (which carries the same compatibility promise as
``Tool`` / ``Flow`` / ``FlowExecutor``). This test pins that boundary.
"""

from __future__ import annotations

import chainweaver

_CLAUDE_SYMBOLS = (
    "CLAUDE_TRACE_SINK",
    "ClaudeCodeAdapterError",
    "normalize_claude_hook_event",
    "normalize_claude_hook_events",
    "render_posttooluse_hook",
)
_VSCODE_SYMBOLS = (
    "VSCODE_TRACE_SINK",
    "VSCodeAdapterError",
    "copilot_otel_settings_snippet",
    "normalize_vscode_event",
    "normalize_vscode_events",
)


def test_adapters_import_through_explicit_namespaces() -> None:
    import chainweaver.claude as claude
    import chainweaver.vscode as vscode

    for name in _CLAUDE_SYMBOLS:
        assert hasattr(claude, name), f"chainweaver.claude missing {name}"
    for name in _VSCODE_SYMBOLS:
        assert hasattr(vscode, name), f"chainweaver.vscode missing {name}"


def test_adapter_symbols_are_not_in_stable_top_level_api() -> None:
    for name in (*_CLAUDE_SYMBOLS, *_VSCODE_SYMBOLS):
        assert name not in chainweaver.__all__, (
            f"{name} must stay out of the stable top-level chainweaver.__all__ "
            "(experimental vendor adapter — see #518/#522)"
        )
