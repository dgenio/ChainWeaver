"""Schema-drift records for registered flows."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DriftInfo:
    """Describes a schema drift between a flow's stored hash and a tool's current hash.

    Attributes:
        flow_name: Name of the affected flow.
        tool_name: Name of the tool whose schema drifted.
        expected_hash: The hash stored in the flow's ``tool_schema_hashes``.
        actual_hash: The tool's current ``schema_hash``.
    """

    flow_name: str
    tool_name: str
    expected_hash: str
    actual_hash: str
