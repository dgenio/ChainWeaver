"""JSON Schema export for flow files (issue #135).

Emits a single JSON Schema document that describes the on-disk shape of
``.flow.json`` / ``.flow.yaml`` files — the format produced by
:func:`chainweaver.serialization.flow_to_dict` and consumed by
:func:`chainweaver.serialization.flow_from_dict`.

The schema is derived from the live Pydantic models
(:class:`~chainweaver.flow.Flow` and :class:`~chainweaver.flow.DAGFlow`)
via Pydantic v2's :meth:`~pydantic.BaseModel.model_json_schema`, so it
stays in lock-step with the runtime models — there is no hand-maintained
shadow copy to drift.

The combined document is a ``oneOf`` over the two flow shapes,
discriminated by the ``type`` field that :func:`flow_to_dict` adds to
every payload.  Editors that consume JSON Schema (VS Code via
``redhat.vscode-yaml``, JetBrains, etc.) will then offer autocomplete,
inline validation, and hover documentation for flow files without any
user-side setup beyond pointing the editor at the schema URL.

The companion entry-point :func:`flow_schema_json` is exported in
:mod:`chainweaver.__all__`; the CLI's ``dump-schema`` subcommand writes
the schema to disk (or stdout) and is the canonical way to regenerate
the in-repo ``schemas/flow.schema.json`` artifact.
"""

from __future__ import annotations

from typing import Any

from pydantic.json_schema import GenerateJsonSchema

from chainweaver.flow import DAGFlow, Flow

#: ``$id`` for the published schema.  Stable across patch releases; bump
#: the path segment when a breaking schema change ships so old editor
#: caches don't silently validate against a newer shape.
SCHEMA_ID = "https://raw.githubusercontent.com/dgenio/ChainWeaver/main/schemas/flow.schema.json"

#: JSON Schema dialect.  Draft 2020-12 is what Pydantic v2 emits by
#: default and what both ``redhat.vscode-yaml`` and the JetBrains JSON
#: Schema engines understand.
SCHEMA_DIALECT = "https://json-schema.org/draft/2020-12/schema"

#: Filename patterns SchemaStore.org will associate with this schema
#: when the entry ships there (issue #139).  Editors that consult
#: SchemaStore (the de-facto YAML extension for VS Code, plus JetBrains)
#: light up autocomplete on these patterns with zero user setup.
FILE_MATCH_PATTERNS = ("**/*.flow.json", "**/*.flow.yaml", "**/*.flow.yml")


def _model_schema(model: type[Any], title: str) -> dict[str, Any]:
    """Return the JSON Schema for *model*, augmented with the ``type``
    discriminator that :func:`chainweaver.serialization.flow_to_dict`
    writes into every payload.
    """
    schema = model.model_json_schema(
        ref_template="#/$defs/{model}",
        schema_generator=GenerateJsonSchema,
    )
    # Pydantic emits ``$defs`` for nested models — hoist them into the
    # combined document later via ``flow_schema_json``.
    schema = dict(schema)
    # Inject the ``type`` discriminator that ``flow_to_dict`` adds and
    # ``flow_from_dict`` requires.  Without this, the schema validates
    # the bare model payload but the on-disk shape (which always
    # carries ``type``) silently fails strict validation against the
    # raw Pydantic schema.
    properties = dict(schema.get("properties", {}))
    properties["type"] = {
        "type": "string",
        "const": title,
        "description": (
            "Discriminator written by chainweaver.serialization.flow_to_dict; "
            "distinguishes Flow ('Flow') from DAGFlow ('DAGFlow') on load."
        ),
    }
    # Inject the ``format_version`` stamp that ``flow_to_dict`` writes (#394).
    # Optional on read (legacy files omit it), so it is not added to ``required``.
    properties["format_version"] = {
        "type": "string",
        "description": (
            "Flow file format version written by chainweaver.serialization.flow_to_dict; "
            "readers reject an incompatible MAJOR. Distinct from the flow's own 'version'. "
            "See docs/versioning-policy.md."
        ),
    }
    schema["properties"] = properties
    required = list(schema.get("required", []))
    if "type" not in required:
        required.append("type")
    schema["required"] = required
    schema["title"] = title
    return schema


def flow_schema_json() -> dict[str, Any]:
    """Return the combined JSON Schema for ``.flow.json`` / ``.flow.yaml`` files.

    Combines the schemas for :class:`~chainweaver.flow.Flow` and
    :class:`~chainweaver.flow.DAGFlow` into a single ``oneOf`` document
    discriminated by the ``type`` field.  Nested ``$defs`` are merged
    across the two models; conflicting definitions raise
    :class:`ValueError` (this is a structural bug rather than a
    deserialization error, hence the standard exception).

    Returns:
        A ``dict`` ready to be serialized as JSON (e.g. via
        ``json.dumps(flow_schema_json(), indent=2, sort_keys=True)``)
        and consumed by any JSON-Schema-aware editor or validator.
    """
    flow_schema = _model_schema(Flow, "Flow")
    dag_schema = _model_schema(DAGFlow, "DAGFlow")

    flow_defs = dict(flow_schema.pop("$defs", {}))
    dag_defs = dict(dag_schema.pop("$defs", {}))

    merged_defs: dict[str, Any] = dict(flow_defs)
    for def_name, def_body in dag_defs.items():
        existing = merged_defs.get(def_name)
        if existing is not None and existing != def_body:
            raise ValueError(
                f"Definition '{def_name}' has conflicting bodies between "
                f"Flow and DAGFlow schemas. This indicates a bug in the "
                f"Pydantic model layout."
            )
        merged_defs[def_name] = def_body

    return {
        "$schema": SCHEMA_DIALECT,
        "$id": SCHEMA_ID,
        "title": "ChainWeaver flow file",
        "description": (
            "JSON Schema for ChainWeaver flow files (.flow.json / .flow.yaml). "
            "Discriminated by the 'type' field: 'Flow' for linear flows, "
            "'DAGFlow' for directed-acyclic-graph flows."
        ),
        "oneOf": [
            {"$ref": "#/$defs/Flow"},
            {"$ref": "#/$defs/DAGFlow"},
        ],
        "$defs": {
            "Flow": flow_schema,
            "DAGFlow": dag_schema,
            **merged_defs,
        },
    }
