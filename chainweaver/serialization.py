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

.. warning::

    **Trust boundary**: deserialization resolves ``input_schema_ref``,
    ``output_schema_ref``, and ``RetryPolicy.retryable_errors`` via
    :func:`chainweaver.flow.resolve_class_ref`, which calls
    :func:`importlib.import_module` on the module half of every ``"module:qualname"``
    string in the payload.  Importing a module runs its top-level code, so a
    crafted flow file can trigger arbitrary side effects in any module that
    happens to be available on ``sys.path``.  The subsequent ``isinstance``
    and ``expected_base`` checks reject the *resolved attribute* but do not
    undo the import.

    Load flow files only from sources you trust (your own repo, a controlled
    registry, etc.).  Treat untrusted flow payloads with the same caution as
    untrusted ``pickle`` input.  See :func:`chainweaver.flow.set_schema_ref_policy`
    (issue #345) to restrict which modules schema refs may import.

Parse guardrails
----------------
Flow files are the primary untrusted input surface (repos, contributor PRs
validated by the GitHub Action, generated drafts).  Every deserialization
entry point applies conservative :class:`FlowParseLimits` (issue #416): a
maximum input size, node count, nesting depth, string length, and step count.
A file that exceeds any limit fails fast with a :class:`FlowSerializationError`
naming the limit, *before* the structure is fully realized — so a malformed or
hostile ``.flow.yaml``/``.flow.json`` (huge string, deep nesting, YAML
alias/anchor expansion) cannot exhaust memory or CPU.  Pass ``limits=`` to
override the defaults, or :meth:`FlowParseLimits.unlimited` to opt out for
fully trusted input.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from chainweaver._versions import FLOW_FORMAT_VERSION, same_major
from chainweaver.exceptions import FlowSerializationError
from chainweaver.flow import DAGFlow, Flow

_TYPE_KEY = "type"
_FORMAT_VERSION_KEY = "format_version"
_FLOW_DISCRIMINATOR = "Flow"
_DAG_DISCRIMINATOR = "DAGFlow"

AnyFlow = Flow | DAGFlow


# ---------------------------------------------------------------------------
# Parse-size and structural guardrails (issue #416)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FlowParseLimits:
    """Conservative bounds applied when deserializing untrusted flow files.

    Each limit is a positive integer, or ``None`` to disable that single
    check.  Defaults are well above realistic hand-authored flows but small
    enough to stop resource-exhaustion inputs.  A violated limit raises
    :class:`~chainweaver.exceptions.FlowSerializationError` naming the limit.

    Attributes:
        max_bytes: Maximum UTF-8 size of the raw string payload, checked
            before parsing.  Defaults to 5 MiB.
        max_nodes: Maximum number of container/scalar nodes visited while
            validating structure.  Bounds traversal of YAML alias/anchor
            expansion, where shared references could otherwise be walked
            super-linearly.  Defaults to 100_000.
        max_depth: Maximum nesting depth of mappings/sequences.  Defaults to 64.
        max_string_length: Maximum length of any single string value or key.
            Defaults to 100_000.
        max_steps: Maximum length of the top-level ``steps`` list.  Defaults
            to 1_000.
    """

    max_bytes: int | None = 5 * 1024 * 1024
    max_nodes: int | None = 100_000
    max_depth: int | None = 64
    max_string_length: int | None = 100_000
    max_steps: int | None = 1_000

    @classmethod
    def unlimited(cls) -> FlowParseLimits:
        """Return limits with every check disabled (for fully trusted input)."""
        return cls(
            max_bytes=None,
            max_nodes=None,
            max_depth=None,
            max_string_length=None,
            max_steps=None,
        )


#: The conservative limits applied by default to every deserialization path.
DEFAULT_PARSE_LIMITS = FlowParseLimits()


def _check_byte_size(data: str, limits: FlowParseLimits, source: str | None) -> None:
    """Reject *data* before parsing when it exceeds ``limits.max_bytes``."""
    if limits.max_bytes is None:
        return
    size = len(data.encode("utf-8"))
    if size > limits.max_bytes:
        raise FlowSerializationError(
            f"Flow file is {size} bytes, exceeding the max_bytes limit "
            f"({limits.max_bytes}); refusing to parse",
            source=source,
        )


def _enforce_structure(value: Any, limits: FlowParseLimits, source: str | None) -> None:
    """Walk *value* enforcing node-count, depth, and string-length limits.

    Iterative (no recursion limit surprises) and bounded: the node counter
    aborts after ``max_nodes`` visits, so even a YAML alias bomb whose shared
    references form an exponentially large logical tree fails fast.
    """
    visited = 0
    stack: list[tuple[Any, int]] = [(value, 1)]
    while stack:
        node, depth = stack.pop()
        visited += 1
        if limits.max_nodes is not None and visited > limits.max_nodes:
            raise FlowSerializationError(
                f"Flow structure exceeds the max_nodes limit ({limits.max_nodes})",
                source=source,
            )
        if limits.max_depth is not None and depth > limits.max_depth:
            raise FlowSerializationError(
                f"Flow structure is nested deeper than the max_depth limit ({limits.max_depth})",
                source=source,
            )
        if isinstance(node, str):
            _check_string_length(node, limits, source)
        elif isinstance(node, dict):
            for key, child in node.items():
                if isinstance(key, str):
                    _check_string_length(key, limits, source)
                stack.append((child, depth + 1))
        elif isinstance(node, (list, tuple)):
            for item in node:
                stack.append((item, depth + 1))


def _check_string_length(text: str, limits: FlowParseLimits, source: str | None) -> None:
    if limits.max_string_length is not None and len(text) > limits.max_string_length:
        raise FlowSerializationError(
            f"Flow contains a string of length {len(text)}, exceeding the "
            f"max_string_length limit ({limits.max_string_length})",
            source=source,
        )


def _check_step_count(data: dict[str, Any], limits: FlowParseLimits, source: str | None) -> None:
    """Reject a payload whose top-level ``steps`` list exceeds ``max_steps``."""
    if limits.max_steps is None:
        return
    steps = data.get("steps")
    if isinstance(steps, list) and len(steps) > limits.max_steps:
        raise FlowSerializationError(
            f"Flow declares {len(steps)} steps, exceeding the max_steps limit "
            f"({limits.max_steps})",
            source=source,
        )


# ---------------------------------------------------------------------------
# dict <-> Flow|DAGFlow
# ---------------------------------------------------------------------------


def flow_to_dict(flow: AnyFlow) -> dict[str, Any]:
    """Return a JSON-serializable dict representation of *flow*.

    Adds a ``type`` discriminator so the inverse :func:`flow_from_dict` can
    re-instantiate the correct class, and a ``format_version`` stamp (issue
    #394) so future format changes can be handled deliberately.  ``format_version``
    versions the *file format* (the serialization shape), which is distinct from
    the flow's own SemVer ``Flow.version``.
    """
    payload = flow.model_dump(mode="json")
    payload[_FORMAT_VERSION_KEY] = FLOW_FORMAT_VERSION
    if isinstance(flow, DAGFlow):
        payload[_TYPE_KEY] = _DAG_DISCRIMINATOR
    else:
        payload[_TYPE_KEY] = _FLOW_DISCRIMINATOR
    return payload


def flow_from_dict(
    data: dict[str, Any],
    *,
    source: str | None = None,
    limits: FlowParseLimits = DEFAULT_PARSE_LIMITS,
) -> AnyFlow:
    """Reconstruct a :class:`Flow` or :class:`DAGFlow` from a dict payload.

    The dict must contain a ``type`` key whose value is either ``"Flow"`` or
    ``"DAGFlow"``.  A ``format_version`` key (issue #394) is honored when
    present: a file whose MAJOR format version differs from this library's is
    rejected with an actionable error.  Files written before versioning (no
    ``format_version`` key) are treated as the current major and load unchanged.

    The structural guardrails in *limits* (issue #416) are applied before
    Pydantic validation.

    Raises:
        FlowSerializationError: When the payload is not a dict, exceeds a
            structural limit in *limits*, lacks a valid ``type`` discriminator,
            carries an incompatible ``format_version`` major, or fails Pydantic
            validation against the chosen model.
    """
    if not isinstance(data, dict):
        raise FlowSerializationError(
            f"Expected a mapping at the top level, got {type(data).__name__}",
            source=source,
        )
    _enforce_structure(data, limits, source)
    _check_step_count(data, limits, source)
    flow_type = data.get(_TYPE_KEY)
    if flow_type not in (_FLOW_DISCRIMINATOR, _DAG_DISCRIMINATOR):
        raise FlowSerializationError(
            f"Missing or invalid 'type' discriminator (got {flow_type!r}); "
            f"expected 'Flow' or 'DAGFlow'",
            source=source,
        )
    file_format_version = data.get(_FORMAT_VERSION_KEY)
    if file_format_version is not None and not same_major(
        str(file_format_version), FLOW_FORMAT_VERSION
    ):
        raise FlowSerializationError(
            f"Unsupported flow file format_version {file_format_version!r}; "
            f"this ChainWeaver writes format_version '{FLOW_FORMAT_VERSION}'. "
            f"Use a compatible ChainWeaver version to read this file",
            source=source,
        )
    payload = {k: v for k, v in data.items() if k not in (_TYPE_KEY, _FORMAT_VERSION_KEY)}
    model: type[AnyFlow] = DAGFlow if flow_type == _DAG_DISCRIMINATOR else Flow
    try:
        return model.model_validate(payload)
    except Exception as exc:
        raise FlowSerializationError(
            f"Validation failed while reconstructing {flow_type}: {exc}",
            source=source,
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


def flow_from_json(
    data: str,
    *,
    source: str | None = None,
    limits: FlowParseLimits = DEFAULT_PARSE_LIMITS,
) -> AnyFlow:
    """Deserialize a JSON string produced by :func:`flow_to_json`.

    The *limits* guardrails (issue #416) are applied: the raw size is checked
    before parsing and the parsed structure is bounded before validation.

    Raises:
        FlowSerializationError: When *data* exceeds a limit in *limits*, is not
            valid JSON, when the payload is not a JSON object, or when
            validation fails (see :func:`flow_from_dict`).
    """
    _check_byte_size(data, limits, source)
    try:
        parsed = json.loads(data)
    except json.JSONDecodeError as exc:
        raise FlowSerializationError(f"Invalid JSON: {exc}", source=source) from exc
    return flow_from_dict(parsed, source=source, limits=limits)


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


def flow_from_yaml(
    data: str,
    *,
    source: str | None = None,
    limits: FlowParseLimits = DEFAULT_PARSE_LIMITS,
) -> AnyFlow:
    """Deserialize a YAML string produced by :func:`flow_to_yaml`.

    The *limits* guardrails (issue #416) are applied: the raw size is checked
    before parsing, and the parsed structure's node count bounds traversal of
    any YAML alias/anchor expansion before validation.

    Raises:
        FlowSerializationError: When ``pyyaml`` is not available, when *data*
            exceeds a limit in *limits*, when *data* is not valid YAML, or when
            validation fails.
    """
    yaml = _require_yaml()
    _check_byte_size(data, limits, source)
    try:
        parsed = yaml.safe_load(data)
    except yaml.YAMLError as exc:
        raise FlowSerializationError(f"Invalid YAML: {exc}", source=source) from exc
    if parsed is None:
        raise FlowSerializationError("YAML payload is empty", source=source)
    return flow_from_dict(parsed, source=source, limits=limits)
