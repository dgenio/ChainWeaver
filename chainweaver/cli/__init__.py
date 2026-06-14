"""ChainWeaver command-line interface (issue #333).

The CLI is organised as a command package rather than one large module:

- :mod:`chainweaver.cli._shared` holds the Typer ``app`` / sub-apps, the
  registry state (:func:`set_default_registry`), and the shared loading,
  error-handling, and output helpers used by every command.
- Each command group lives in its own submodule (``inspect``, ``validate``,
  ``run`` …) and registers its commands on the shared ``app`` at import time.

This package module imports the command submodules so their commands are
registered, defines the ``main`` console-script entry point, and re-exports
the stable surface that host applications and tests rely on.
"""

from __future__ import annotations

import typer

# Importing the command submodules registers their commands on ``app`` via the
# ``@app.command(...)`` / ``@flows_app.command(...)`` decorators that run at
# import time.  ``_shared`` is imported first (above) so it is fully
# initialised before any command module reaches back into it.
from chainweaver.cli import (  # noqa: F401  side-effect: command registration
    _shared,
    attest,
    diff,
    doctor,
    flows,
    fuzz,
    inspect,
    record,
    run,
    service,
    suggest,
    traces,
    validate,
)
from chainweaver.cli._shared import (
    OutputFormat,
    _error_line,
    _import_tools_from,  # noqa: F401  re-exported for host apps / tests
    app,
    flows_app,
    get_default_registry,
    set_default_registry,
    traces_app,
)
from chainweaver.cli.profile import profile_command
from chainweaver.cli.run import (
    ServeTransport,
    _build_flow_server,  # noqa: F401  re-exported for host apps / tests
    serve_command,
)
from chainweaver.exceptions import ChainWeaverError

__all__ = [
    "OutputFormat",
    "ServeTransport",
    "app",
    "flows_app",
    "get_default_registry",
    "main",
    "profile_command",
    "serve_command",
    "set_default_registry",
    "traces_app",
]


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``chainweaver`` console script.

    Wraps :data:`app` so it returns a process exit code instead of raising.
    With ``standalone_mode=False`` Click/typer returns the typer.Exit code
    rather than raising it; we forward that value as the process exit code.
    """
    args = list(argv) if argv is not None else None
    try:
        result = app(args=args, standalone_mode=False)
    except typer.Exit as exc:
        return int(exc.exit_code)
    except SystemExit as exc:
        code = exc.code
        return int(code) if isinstance(code, int) else 0
    except ChainWeaverError as exc:
        typer.echo(_error_line(exc), err=True)
        return 1
    except Exception as exc:
        typer.echo(f"chainweaver: error: {exc}", err=True)
        return 1
    if isinstance(result, int):
        return result
    return 0
