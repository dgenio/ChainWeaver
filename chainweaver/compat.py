"""Schema fingerprinting and compatibility utilities for ChainWeaver.

Provides deterministic hashing of Pydantic model JSON schemas and
compatibility checking between flows and their registered tools.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from chainweaver.flow import DAGFlow, Flow
    from chainweaver.tools import Tool

from pydantic import BaseModel


def schema_fingerprint(model: type[BaseModel]) -> str:
    """Compute a deterministic SHA-256 fingerprint of a Pydantic model's JSON Schema.

    The fingerprint is a 16-character hex string derived from the canonical
    JSON representation of the model's schema (sorted keys, compact separators).

    Args:
        model: A Pydantic BaseModel subclass.

    Returns:
        A 16-character hex digest string.
    """
    schema = model.model_json_schema()
    canonical = json.dumps(schema, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def schema_dict_fingerprint(raw_schema: dict[str, object]) -> str:
    """Compute a deterministic fingerprint of a *raw* JSON Schema dict (issue #358).

    Counterpart to :func:`schema_fingerprint`, which fingerprints a Pydantic
    model.  This variant fingerprints a JSON Schema *mapping* directly — used by
    :class:`~chainweaver.mcp.adapter.MCPToolAdapter` to pin the schemas a remote
    MCP server advertises *before* they are projected to Pydantic, so a server
    silently changing a tool's ``inputSchema`` / ``outputSchema`` between sessions
    is detectable.

    The canonicalisation (sorted keys, compact separators) makes the fingerprint
    insensitive to JSON key ordering, so a server reordering schema keys without
    changing their meaning does not register as drift.

    Args:
        raw_schema: A JSON-Schema mapping (e.g. an MCP tool's ``inputSchema``).

    Returns:
        A 16-character hex digest string, matching :func:`schema_fingerprint`.
    """
    canonical = json.dumps(raw_schema, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


@dataclass
class CompatibilityIssue:
    """A single compatibility problem detected between a flow and its tools.

    Attributes:
        flow_name: Name of the flow with the issue.
        step_index: Zero-based step index where the issue occurs.
        tool_name: Tool referenced by the step.
        issue_type: Machine-readable issue category.
        detail: Human-readable explanation.
    """

    flow_name: str
    step_index: int
    tool_name: str
    issue_type: str
    detail: str


def check_flow_compatibility(
    flow: Flow | DAGFlow,
    tools: dict[str, Tool],
) -> list[CompatibilityIssue]:
    """Check that each step's tool exists and its schema matches expectations.

    Compares each step's tool against the flow's stored ``tool_schema_hashes``
    snapshot (if present). Returns a list of issues (empty means compatible).

    Accepts both :class:`~chainweaver.flow.Flow` and
    :class:`~chainweaver.flow.DAGFlow` — the implementation only touches
    ``name``, ``steps``, and ``tool_schema_hashes``, which exist on both.

    Args:
        flow: The flow (or DAG flow) to check.
        tools: A mapping of tool name to Tool instance.

    Returns:
        A list of :class:`CompatibilityIssue` objects. Empty means fully compatible.
    """
    issues: list[CompatibilityIssue] = []

    for idx, step in enumerate(flow.steps):
        if step.tool_name is None:
            # Composed sub-flow step (issue #75) — not a tool reference, so
            # tool-schema compatibility checks do not apply here.
            continue
        if step.tool_name not in tools:
            issues.append(
                CompatibilityIssue(
                    flow_name=flow.name,
                    step_index=idx,
                    tool_name=step.tool_name,
                    issue_type="missing_tool",
                    detail=f"Tool '{step.tool_name}' is not registered.",
                )
            )
            continue

        if flow.tool_schema_hashes is not None:
            expected_hash = flow.tool_schema_hashes.get(step.tool_name)
            if expected_hash is not None:
                actual_hash = tools[step.tool_name].schema_hash
                if expected_hash != actual_hash:
                    issues.append(
                        CompatibilityIssue(
                            flow_name=flow.name,
                            step_index=idx,
                            tool_name=step.tool_name,
                            issue_type="schema_mismatch",
                            detail=(
                                f"Tool '{step.tool_name}' schema hash changed: "
                                f"expected '{expected_hash}', got '{actual_hash}'."
                            ),
                        )
                    )

    return issues
