# JSON Schema for flow files

ChainWeaver flow files (`.flow.json` / `.flow.yaml`) are described by a JSON
Schema generated from the live Pydantic models. The schema lives at
`schemas/flow.schema.json` and is the same artifact published at the
canonical URL:

```
https://raw.githubusercontent.com/dgenio/ChainWeaver/main/schemas/flow.schema.json
```

This page explains how to use the schema in editors today and how the
SchemaStore registration shipped alongside issue #139 makes it zero-setup
once accepted upstream.

## Why

Flow files are written, edited, and reviewed by humans. Without an editor
that understands the schema, every typo in `tool_name`, `input_mapping`, or
`depends_on` waits until `chainweaver check` runs. With the schema wired in,
the editor flags the typo as you type and offers autocomplete for every
field name.

This file is the long-form rationale for issue #135 (export the schema) and
issue #139 (publish it to SchemaStore.org).

## Use the schema today

### VS Code

Install the
[YAML extension](https://marketplace.visualstudio.com/items?itemName=redhat.vscode-yaml)
(the de-facto YAML language server) and add to your workspace's
`.vscode/settings.json`:

```json
{
  "yaml.schemas": {
    "https://raw.githubusercontent.com/dgenio/ChainWeaver/main/schemas/flow.schema.json": [
      "*.flow.yaml",
      "*.flow.yml"
    ]
  },
  "json.schemas": [
    {
      "fileMatch": ["*.flow.json"],
      "url": "https://raw.githubusercontent.com/dgenio/ChainWeaver/main/schemas/flow.schema.json"
    }
  ]
}
```

### JetBrains (PyCharm, IntelliJ, GoLand, …)

Open **Settings → Languages & Frameworks → Schemas and DTDs → JSON Schema
Mappings** and add a mapping for the same URL with file patterns
`*.flow.yaml` and `*.flow.json`.

### Neovim

`coc-yaml` and `coc-json` honour the same settings shape as VS Code — drop
the snippet above into `coc-settings.json`.

## Regenerate the schema

The schema is derived from the Pydantic models, so it must stay in sync with
the runtime types. Regenerate it after any change to `Flow`, `DAGFlow`,
`FlowStep`, `DAGFlowStep`, or `RetryPolicy`:

```bash
chainweaver dump-schema --output schemas/flow.schema.json
```

CI runs the same command under `--check` to fail the build if the
checked-in schema drifts from the Pydantic source of truth:

```bash
chainweaver dump-schema --check --output schemas/flow.schema.json
```

## SchemaStore submission (issue #139)

The maintainer-facing how-to for registering with
[SchemaStore.org](https://www.schemastore.org/json/) — the catalogue that
VS Code's YAML extension and JetBrains both consult automatically. Once the
entry lands, no user-side setup is required: opening any `*.flow.yaml` file
lights up autocomplete + validation immediately.

The catalogue entry payload is checked in at
`schemas/schemastore-catalog-entry.json`. The submission workflow:

1. Confirm `schemas/flow.schema.json` is up to date on `main`
   (`chainweaver dump-schema --check --output schemas/flow.schema.json`).
2. Fork [SchemaStore/schemastore](https://github.com/SchemaStore/schemastore).
3. Copy the object from `schemas/schemastore-catalog-entry.json` (drop the
   `_comment` field) into the `schemas` array of
   `src/api/json/catalog.json`, alphabetically by `name`.
4. Open a PR to `SchemaStore/schemastore`. The maintainers' checks include
   a `jsonschema` lint against the URL — make sure the schema URL responds
   with a valid Draft 2020-12 document at submission time.
5. Once merged, editor support is automatic for any user with the YAML
   extension installed.

Update `schemas/schemastore-catalog-entry.json` whenever the schema's
`$id` URL or filename patterns change.
