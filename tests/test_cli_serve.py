"""Tests for the ``chainweaver serve`` MCP-server CLI command (issues #72, #230)."""

from __future__ import annotations

from pathlib import Path

import pytest
import typer

from chainweaver import cli
from chainweaver.cli import app

_REPO_ROOT = Path(__file__).resolve().parent.parent
_EXAMPLE_FLOW = _REPO_ROOT / "examples" / "double_add_format.flow.yaml"


class _FakeServer:
    """Stand-in FlowServer that records ``serve`` calls instead of blocking."""

    def __init__(self) -> None:
        self.registered_tool_names = ["double_add_format"]
        self.served_transport: str | None = None

    def serve(self, transport: str = "stdio") -> None:
        self.served_transport = transport


class TestServeCommandRegistration:
    def test_serve_is_a_registered_command(self) -> None:
        names = [c.name for c in app.registered_commands]
        assert "serve" in names

    def test_transport_enum_matches_library_literal(self) -> None:
        """``ServeTransport`` must stay in sync with ``mcp.server.TransportName``.

        The CLI mirrors the library's transport list as an ``Enum`` (typer needs
        an enum for the option); this guard fails if a transport is added to one
        source without the other.
        """
        pytest.importorskip("mcp")
        from typing import get_args

        from chainweaver.mcp.server import TransportName

        assert {t.value for t in cli.ServeTransport} == set(get_args(TransportName))


class TestBuildFlowServer:
    def test_exposes_one_tool_per_flow(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.syspath_prepend(str(_REPO_ROOT))
        server = cli._build_flow_server(
            _EXAMPLE_FLOW,
            ["examples.simple_linear_flow"],
            name="cw-test",
            server_prefix="",
        )
        assert server.registered_tool_names == ["double_add_format"]

    def test_prefix_namespaces_tool_names(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.syspath_prepend(str(_REPO_ROOT))
        server = cli._build_flow_server(
            _EXAMPLE_FLOW,
            ["examples.simple_linear_flow"],
            name="cw-test",
            server_prefix="cw",
        )
        assert server.registered_tool_names == ["cw__double_add_format"]

    def test_missing_flow_file_exits_2(self, tmp_path: Path) -> None:
        exit_code = cli.main(["serve", str(tmp_path / "nope.flow.yaml")])
        assert exit_code == 2

    def test_missing_mcp_extra_exits_1(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        def _raise_missing_extra() -> type:
            typer.echo(
                "chainweaver: the 'serve' command requires the MCP extra. "
                "Install with: pip install 'chainweaver[mcp]'.",
                err=True,
            )
            raise typer.Exit(code=1)

        monkeypatch.setattr(cli, "_import_flow_server", _raise_missing_extra)
        exit_code = cli.main(["serve", str(_EXAMPLE_FLOW)])
        assert exit_code == 1
        assert "requires the MCP extra" in capsys.readouterr().err


class TestServeCommandWiring:
    def test_serves_chosen_transport_and_banners_to_stderr(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        fake = _FakeServer()
        monkeypatch.setattr(cli, "_build_flow_server", lambda *a, **k: fake)
        cli.serve_command(
            flow_file=_EXAMPLE_FLOW,
            tools=[],
            transport=cli.ServeTransport.SSE,
            name="chainweaver",
            prefix="",
        )
        assert fake.served_transport == "sse"
        err = capsys.readouterr().err
        assert "double_add_format" in err
        assert "over sse" in err
