# `chainweaver` GitHub Action

A reusable composite action that runs `chainweaver check` against a directory
of `.flow.yaml` / `.flow.json` files, surfaces every invalid file as an inline
PR annotation, and fails the workflow step on validation errors.

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
      - uses: dgenio/ChainWeaver/.github/actions/chainweaver@v0.11.0
        with:
          directory: flows/
```

### Inputs

| Input | Default | Description |
|---|---|---|
| `directory` | `.` | Directory scanned recursively for flow files. |
| `command` | `check` | Subcommand to invoke. Designed for `check` / `validate` (the verbs that accept `--format json`); other verbs run but produce no annotations. |
| `annotations` | `true` | Emit GitHub `::error` annotations for each invalid flow file. Annotations are file-scoped — the flow serializer reports structural errors per file without line numbers. |
| `python-version` | `3.10` | Python version used to install and run `chainweaver`. Must be one of ChainWeaver's supported versions (3.10–3.14). |
| `chainweaver-version` | `0.11.0` | Exact version of `chainweaver` to install from PyPI (passed through to `pip install "chainweaver==<version>"`). Pinned by default; pass an empty string for the latest published version. |
| `extra-args` | `""` | Additional arguments appended verbatim to the invocation (e.g. `--quiet`). |

### Outputs

| Output | Description |
|---|---|
| `exit-code` | Exit code from the `chainweaver` invocation. `0` = success, `1` = validation errors, `2` = missing / invalid directory. |

## How annotations work

The action runs `chainweaver check <directory> --format json`, prints the raw
JSON to the job log, and pipes it through [`annotate.py`](annotate.py), which
emits one `::error file=<path>::<message>` per invalid file. GitHub renders
these as inline annotations on the PR's *Files changed* tab and in the run
summary. Set `annotations: false` to disable.

## Examples

### Validate every flow under `flows/`

```yaml
- uses: dgenio/ChainWeaver/.github/actions/chainweaver@v0.11.0
  with:
    directory: flows/
```

### Forward the result to a downstream step

```yaml
- uses: dgenio/ChainWeaver/.github/actions/chainweaver@v0.11.0
  id: cw
  continue-on-error: true
  with:
    directory: flows/
- name: Forward to internal tool
  if: always()
  run: ./tools/upload-validation-report.sh "${{ steps.cw.outputs.exit-code }}"
```

### Pin to a specific ChainWeaver release

```yaml
- uses: dgenio/ChainWeaver/.github/actions/chainweaver@v0.11.0
  with:
    chainweaver-version: "0.11.0"
```

### Track the latest release instead

```yaml
- uses: dgenio/ChainWeaver/.github/actions/chainweaver@v0.11.0
  with:
    chainweaver-version: ""  # falls through to ``pip install chainweaver``
```

## Versioning

This action lives inside the `dgenio/ChainWeaver` repository, so it is
versioned with the package. Pin to a ChainWeaver release tag
(`@v0.11.0`) rather than `@main` to avoid implicit upgrades.

The `chainweaver-version` input default matches the action's tag — both
are bumped in lockstep when a new ChainWeaver release ships. If you
override `chainweaver-version`, the action will install whatever you ask
for; it will not refuse a mismatch.
