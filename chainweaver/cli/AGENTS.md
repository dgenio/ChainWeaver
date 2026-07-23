# Scoped guidance — `chainweaver/cli/`

> Root `AGENTS.md` is authoritative and cannot be weakened here; on conflict,
> the root wins — flag and fix the conflict in the same PR. This file adds
> durable local rules only.

## Command registration

- One module per command group; each registers on the shared Typer `app`
  (from `_shared.py`) at import time, and `cli/__init__.py` wires the
  submodules and re-exports the stable surface (`app`,
  `set_default_registry`, `main`). A new command group is a new module plus
  its wiring import — never a mega-module.

## Error and output contract

- Errors map to exit codes through the shared error→exit-code handling in
  `_shared.py`. Never `sys.exit()` ad hoc or print raw tracebacks; raise the
  typed `ChainWeaverError` and let the shared handler render it.
- Commands that support `--format json` emit the shared envelope from
  `_shared.py`. Human-readable output goes to stdout; diagnostics to stderr.
- Flow/result loading and flow-resolution/discovery go through the shared
  helpers in `_shared.py` — do not re-implement file loading per command.
- The CLI is presentation only: no execution semantics live here. Behavior
  belongs in the library; the CLI calls it.
