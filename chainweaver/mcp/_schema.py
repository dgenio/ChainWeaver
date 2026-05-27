"""JSON Schema ↔ Pydantic conversion helpers for the MCP integration.

MCP tools advertise their inputs (and, optionally, their outputs) as
JSON Schema documents.  ChainWeaver's ``Tool`` contract requires both
sides to be Pydantic ``BaseModel`` subclasses.  This module builds the
shallow bridge between the two without pulling in a heavyweight
"complete JSON Schema → Python types" library.

Scope (kept deliberately small for the v0.1 MCP adapter):

* Top-level ``"type": "object"`` schemas with named ``properties``.
* Primitive leaf types: ``string`` / ``integer`` / ``number`` /
  ``boolean`` / ``null``.
* ``array`` of any of the above (item shape is type-checked when
  available; falls back to ``list[Any]`` otherwise).
* Nested ``"type": "object"`` schemas (mapped to ``dict[str, Any]``;
  full nested-model recursion is intentionally out of scope for v0.1).
* ``required`` keyword controls optional-vs-required fields.
* ``description`` carries through as the Pydantic ``Field`` description.

Anything else — ``oneOf`` / ``anyOf`` / ``$ref`` / ``allOf`` /
enum-only / tuple-typed arrays — falls back to ``Any`` (or, for
unrecognised top-level schemas, a permissive "any dict" passthrough
model).  This keeps the adapter robust against the long tail of
real-world MCP tool schemas without crashing.
"""

from __future__ import annotations

import re
from typing import Any, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, create_model

from chainweaver.exceptions import MCPSchemaConversionError

ExtraValue = Literal["allow", "ignore", "forbid"]

_PRIMITIVE_TYPES: dict[str, type] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "null": type(None),
}


def _sanitise_model_name(raw: str) -> str:
    """Coerce *raw* into a valid Python identifier suitable for a model class."""
    cleaned = re.sub(r"[^0-9A-Za-z_]", "_", raw)
    if not cleaned:
        cleaned = "MCPModel"
    if cleaned[0].isdigit():
        cleaned = f"_{cleaned}"
    return cleaned


def _field_type_from_schema(prop_schema: dict[str, Any]) -> Any:
    """Map a JSON Schema property fragment to a Python type annotation.

    Best-effort: unknown / unsupported constructs collapse to ``Any``.
    """
    if not isinstance(prop_schema, dict):
        return Any

    raw_type = prop_schema.get("type")

    # Union types ("type": ["string", "null"]) — accept any of the
    # listed primitives, fall through to ``Any`` if any member is
    # outside the primitive set.
    if isinstance(raw_type, list):
        union_members: list[type] = []
        for member in raw_type:
            if member in _PRIMITIVE_TYPES:
                union_members.append(_PRIMITIVE_TYPES[member])
            else:
                return Any
        if not union_members:
            return Any
        if len(union_members) == 1:
            return union_members[0]
        # Build a typing.Union dynamically.
        result: Any = union_members[0]
        for member_type in union_members[1:]:
            result = result | member_type
        return result

    if raw_type in _PRIMITIVE_TYPES:
        return _PRIMITIVE_TYPES[raw_type]

    if raw_type == "array":
        items = prop_schema.get("items")
        if isinstance(items, dict):
            item_type = _field_type_from_schema(items)
            return list[item_type]  # type: ignore[valid-type]
        return list[Any]

    if raw_type == "object":
        # Nested object — build a nested model lazily.  We don't have a
        # name handle here; the caller (``jsonschema_to_pydantic``)
        # passes it through.  Falling back to ``dict[str, Any]`` keeps
        # the schema permissive without exploding on every nested
        # object.
        return dict[str, Any]

    return Any


def jsonschema_to_pydantic(
    schema: dict[str, Any] | None,
    *,
    name: str,
    tool_name: str | None = None,
    extra: str = "allow",
) -> type[BaseModel]:
    """Build a Pydantic model from an MCP-flavoured JSON Schema.

    Args:
        schema: JSON Schema document, typically the ``inputSchema`` or
            ``outputSchema`` of an MCP tool.  ``None`` produces a
            permissive empty model that accepts any kwargs.
        name: Human-friendly base name for the generated model class.
            Sanitised to a valid Python identifier.
        tool_name: Optional tool name surfaced in error messages — pass
            it through when the caller knows the MCP tool the schema
            belongs to.
        extra: Pydantic ``extra`` config value — defaults to ``"allow"``
            so unknown fields round-trip through the model (MCP tool
            authors often omit fields from the schema that they still
            accept at runtime).  Pass ``"forbid"`` for strict mode.

    Returns:
        A dynamically-constructed Pydantic ``BaseModel`` subclass with
        one field per property of the input schema.

    Raises:
        MCPSchemaConversionError: When *schema* is structurally invalid
            (e.g. a non-dict value passed in, or ``properties`` whose
            value isn't a mapping).
    """
    if schema is None:
        return _make_passthrough_model(name=name, extra=extra)

    if not isinstance(schema, dict):
        raise MCPSchemaConversionError(
            tool_name or name,
            f"expected a dict-shaped JSON Schema, got {type(schema).__name__}",
        )

    schema_type = schema.get("type")
    # Top-level types that aren't object/missing → fall back to a
    # permissive wrapper so we never crash on weird shapes.
    if schema_type not in (None, "object"):
        return _make_passthrough_model(name=name, extra=extra)

    properties = schema.get("properties") or {}
    if not isinstance(properties, dict):
        raise MCPSchemaConversionError(
            tool_name or name,
            f"'properties' must be a mapping, got {type(properties).__name__}",
        )

    required = set(schema.get("required") or [])

    fields: dict[str, Any] = {}
    for prop_name, prop_schema in properties.items():
        if not isinstance(prop_name, str):
            continue  # Skip non-string keys defensively.
        field_type = _field_type_from_schema(prop_schema if isinstance(prop_schema, dict) else {})
        description = prop_schema.get("description") if isinstance(prop_schema, dict) else None
        if prop_name in required:
            fields[prop_name] = (field_type, Field(..., description=description))
        else:
            optional_type: Any = field_type | None
            fields[prop_name] = (optional_type, Field(default=None, description=description))

    sanitised = _sanitise_model_name(name)
    config = ConfigDict(extra=cast(ExtraValue, extra))
    model: type[BaseModel] = create_model(
        sanitised,
        __config__=config,
        **fields,
    )
    return model


def _make_passthrough_model(*, name: str, extra: str) -> type[BaseModel]:
    """Construct a permissive empty model used as the schema fallback."""
    sanitised = _sanitise_model_name(name)
    config = ConfigDict(extra=cast(ExtraValue, extra))
    model: type[BaseModel] = create_model(
        sanitised,
        __config__=config,
    )
    return model


def pydantic_to_jsonschema(model: type[BaseModel]) -> dict[str, Any]:
    """Project a Pydantic model to a JSON Schema document for MCP advertising.

    Thin wrapper over ``model.model_json_schema()`` so callers (notably
    :class:`chainweaver.mcp.FlowServer`) have a single, named entry
    point and don't have to know about Pydantic's own helper.

    Args:
        model: Pydantic ``BaseModel`` subclass.

    Returns:
        JSON Schema document (Draft 2020-12) describing the model.
    """
    return model.model_json_schema()
