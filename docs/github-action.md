# Validate flows in CI with the GitHub Action

ChainWeaver ships a reusable composite GitHub Action that runs
[`chainweaver check`](cli.md) against your flow files on every push or pull
request, and surfaces invalid files as inline PR annotations. It turns "validate
my `.flow.yaml` files in CI" into a single `uses:` line — no hand-wired Python
setup, dependency install, or JSON parsing.

The action lives in this repository at `.github/actions/chainweaver`, so it is
versioned with the package: pin it to a release tag.

## Quick start

```yaml
name: Validate flows
on: [push, pull_request]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: dgenio/ChainWeaver/.github/actions/chainweaver@v0.12.0
        with:
          directory: flows/
```

Every `.flow.yaml` / `.flow.yml` / `.flow.json` file under `flows/` is parsed.
If any file is malformed, the step fails and each bad file gets an inline
`::error` annotation on the PR.

## How it works

1. Sets up Python (`python-version`, default `3.10`) and `pip install`s the
   pinned `chainweaver` release with the `[yaml]` extra, so `.flow.yaml` files
   parse out of the box.
2. Runs `chainweaver check <directory> --format json` and prints the JSON
   result to the job log.
3. Pipes that JSON through `annotate.py`, which emits one
   `::error file=<path>::<message>` per invalid file.
4. Exits with `chainweaver`'s own exit code (`0` valid, `1` invalid, `2`
   directory missing), failing the workflow step on any error.

Annotations are **file-scoped** (no line numbers): the flow serializer reports
structural errors per file, not per line.

## Inputs

| Input | Default | Description |
|---|---|---|
| `directory` | `.` | Directory scanned recursively for flow files. |
| `annotations` | `true` | Emit `::error` annotations for invalid files. Set `false` to disable. |
| `python-version` | `3.10` | Python used to install and run `chainweaver` (3.10–3.14). |
| `chainweaver-version` | `0.12.0` | Exact PyPI version to install. Pass `""` for the latest published release. |
| `extra-args` | `""` | Extra args appended verbatim (e.g. `--quiet`). |

## Outputs

| Output | Description |
|---|---|
| `exit-code` | The `chainweaver` exit code (`0` / `1` / `2`). Read it from a downstream step via `steps.<id>.outputs.exit-code`. |

To branch on the result without failing the job, set `continue-on-error: true`
on the action step and inspect `exit-code`:

```yaml
- uses: dgenio/ChainWeaver/.github/actions/chainweaver@v0.12.0
  id: cw
  continue-on-error: true
  with:
    directory: flows/
- name: Report
  if: always()
  run: ./tools/report.sh "${{ steps.cw.outputs.exit-code }}"
```

## Versioning

Pin to a ChainWeaver release tag (`@v0.12.0`) rather than `@main` to avoid
implicit upgrades. The `chainweaver-version` input default tracks the action's
tag; both move in lockstep on each release.

See also the [action's README](https://github.com/dgenio/ChainWeaver/tree/main/.github/actions/chainweaver)
and the [distribution checklist](distribution.md).
