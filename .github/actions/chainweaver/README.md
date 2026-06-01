# `chainweaver` GitHub Action

A reusable composite action that runs `chainweaver check` (or another
`chainweaver` CLI verb) against a directory of `.flow.yaml` /
`.flow.json` files and fails the workflow step on validation errors.

Resolves [#149](https://github.com/dgenio/ChainWeaver/issues/149).

## Usage

```yaml
name: Validate flows
on: [push, pull_request]

jobs:
  validate:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v6
      - uses: dgenio/ChainWeaver/.github/actions/chainweaver@v0.4.0
        with:
          directory: flows/
```

### Inputs

| Input | Default | Description |
|---|---|---|
| `directory` | `.` | Directory scanned recursively for flow files. |
| `command` | `check` | Subcommand to invoke (`check`, `validate`, `inspect`, `viz`, …). Future verbs work via the same action. |
| `format` | `table` | Output format (`table` or `json`). |
| `python-version` | `3.10` | Python version used to install and run `chainweaver`. Must be one of ChainWeaver's supported versions (3.10–3.14). |
| `chainweaver-version` | `0.4.0` | Exact version of `chainweaver` to install from PyPI (passed through to `pip install "chainweaver==<version>"`). Pinned by default; pass an empty string for the latest published version. |
| `extra-args` | `""` | Additional arguments appended verbatim to the invocation (e.g. `--quiet`). |

### Outputs

| Output | Description |
|---|---|
| `exit-code` | Exit code from the `chainweaver` invocation. `0` = success, `1` = validation errors, `2` = missing / invalid directory. |

## Examples

### Validate every flow under `flows/`

```yaml
- uses: dgenio/ChainWeaver/.github/actions/chainweaver@v0.4.0
  with:
    directory: flows/
```

### Machine-readable output for downstream steps

```yaml
- uses: dgenio/ChainWeaver/.github/actions/chainweaver@v0.4.0
  id: cw
  with:
    directory: flows/
    format: json
- name: Forward to internal tool
  if: always()
  run: ./tools/upload-validation-report.sh "${{ steps.cw.outputs.exit-code }}"
```

### Pin to a specific ChainWeaver release

```yaml
- uses: dgenio/ChainWeaver/.github/actions/chainweaver@v0.4.0
  with:
    chainweaver-version: "0.4.0"
```

### Track the latest release instead

```yaml
- uses: dgenio/ChainWeaver/.github/actions/chainweaver@v0.4.0
  with:
    chainweaver-version: ""  # falls through to ``pip install chainweaver``
```

## Versioning

This action lives inside the `dgenio/ChainWeaver` repository, so it is
versioned with the package. Pin to a ChainWeaver release tag
(`@v0.4.0`) rather than `@main` to avoid implicit upgrades.

The `chainweaver-version` input default matches the action's tag — both
are bumped in lockstep when a new ChainWeaver release ships. If you
override `chainweaver-version`, the action will install whatever you ask
for; it will not refuse a mismatch.
