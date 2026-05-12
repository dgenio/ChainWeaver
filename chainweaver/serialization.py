"""Flow serialization helpers (issue #14).

Round-trips :class:`~chainweaver.flow.Flow` and :class:`~chainweaver.flow.DAGFlow`
through JSON or YAML strings.  A ``"type": "Flow"`` / ``"type": "DAGFlow"``
discriminator at the top of the payload disambiguates the two flow shapes
on deserialization.

JSON serialization has no extra dependencies.  YAML serialization requires
``pyyaml`` (available via ``pip install chainweaver[yaml]``); the YAML
helpers raise :class:`~chainweaver.exceptions.FlowSerializationError` with
an informative message when it is missing.

Schema references (``input_schema_ref`` / ``output_schema_ref``) round-trip
as ``"module:qualname"`` strings.  Retry exception types likewise round-trip
as strings.  No live class objects are written to the payload, so flow
files stay JSON-compatible end-to-end.
"""

from __future__ import annotations

import json
from typing import Any

from chainweaver.exceptions import FlowSerializationError
from chainweaver.flow import DAGFlow, Flow

_TYPE_KEY = "type"
_FLOW_DISCRIMINATOR = "Flow"
_DAG_DISCRIMINATOR = "DAGFlow"

AnyFlow = Flow | DAGFlow


# ---------------------------------------------------------------------------
# dict <-> Flow|DAGFlow
# ---------------------------------------------------------------------------


def flow_to_dict(flow: AnyFlow) -> dict[str, Any]:
    """Return a JSON-serializable dict representation of *flow*.

    Adds a ``type`` discriminator so the inverse :func:`flow_from_dict` can
    re-instantiate the correct class.
    """
    payload = flow.model_dump(mode="json")
    if isinstance(flow, DAGFlow):
        payload[_TYPE_KEY] = _DAG_DISCRIMINATOR
    else:
        payload[_TYPE_KEY] = _FLOW_DISCRIMINATOR
    return payload


def flow_from_dict(data: dict[str, Any]) -> AnyFlow:
    """Reconstruct a :class:`Flow` or :class:`DAGFlow` from a dict payload.

    The dict must contain a ``type`` key whose value is either ``"Flow"`` or
    ``"DAGFlow"``.

    Raises:
        FlowSerializationError: When the payload is not a dict, lacks a
            valid ``type`` discriminator, or fails Pydantic validation
            against the chosen model.
    """
    if not isinstance(data, dict):
        raise FlowSerializationError(
            f"Expected a mapping at the top level, got {type(data).__name__}"
        )
    flow_type = data.get(_TYPE_KEY)
    if flow_type not in (_FLOW_DISCRIMINATOR, _DAG_DISCRIMINATOR):
        raise FlowSerializationError(
            f"Missing or invalid 'type' discriminator (got {flow_type!r}); "
            f"expected 'Flow' or 'DAGFlow'"
        )
    payload = {k: v for k, v in data.items() if k != _TYPE_KEY}
    model: type[AnyFlow] = DAGFlow if flow_type == _DAG_DISCRIMINATOR else Flow
    try:
        return model.model_validate(payload)
    except Exception as exc:
        raise FlowSerializationError(
            f"Validation failed while reconstructing {flow_type}: {exc}"
        ) from exc


# ---------------------------------------------------------------------------
# JSON
# ---------------------------------------------------------------------------


def flow_to_json(flow: AnyFlow, *, indent: int | None = 2) -> str:
    """Serialize *flow* to a JSON string.

    Args:
        flow: The flow to serialize.
        indent: Indentation level for pretty-printing.  ``None`` produces a
            compact single-line representation.

    Returns:
        A JSON string that round-trips via :func:`flow_from_json`.
    """
    return json.dumps(flow_to_dict(flow), indent=indent, sort_keys=True)


def flow_from_json(data: str) -> AnyFlow:
    """Deserialize a JSON string produced by :func:`flow_to_json`.

    Raises:
        FlowSerializationError: When *data* is not valid JSON, when the
            payload is not a JSON object, or when validation fails (see
            :func:`flow_from_dict`).
    """
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError as exc:
        raise FlowSerializationError(f"Invalid JSON: {exc}") from exc
    return flow_from_dict(parsed)


# ---------------------------------------------------------------------------
# YAML
# ---------------------------------------------------------------------------


def _require_yaml() -> Any:
    """Return the ``yaml`` module, or raise :class:`FlowSerializationError`."""
    try:
        import yaml
    except ImportError as exc:
        raise FlowSerializationError(
            "YAML support requires 'pyyaml' to be installed. "
            "Install it via 'pip install chainweaver[yaml]'"
        ) from exc
    return yaml


def flow_to_yaml(flow: AnyFlow) -> str:
    """Serialize *flow* to a YAML string.

    Requires ``pyyaml`` to be installed.  The output uses block style
    (``default_flow_style=False``) and emits keys in alphabetical order
    (``sort_keys=True``) so the same flow always renders identically and
    diffs stay stable across processes.

    Raises:
        FlowSerializationError: When ``pyyaml`` is not available.
    """
    yaml = _require_yaml()
    return str(
        yaml.safe_dump(
            flow_to_dict(flow),
            default_flow_style=False,
            sort_keys=True,
        )
    )


def flow_from_yaml(data: str) -> AnyFlow:
    """Deserialize a YAML string produced by :func:`flow_to_yaml`.

    Raises:
        FlowSerializationError: When ``pyyaml`` is not available, when *data*
            is not valid YAML, or when validation fails.
    """
    yaml = _require_yaml()
    try:
        parsed = yaml.safe_load(data)
    except yaml.YAMLError as exc:
        raise FlowSerializationError(f"Invalid YAML: {exc}") from exc
    if parsed is None:
        raise FlowSerializationError("YAML payload is empty")
    return flow_from_dict(parsed)
