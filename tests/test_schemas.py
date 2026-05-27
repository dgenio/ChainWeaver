"""Tests for the JSON Schema exporter (issue #135)."""

from __future__ import annotations

import json

import pytest

from chainweaver.flow import DAGFlow, DAGFlowStep, Flow, FlowStep
from chainweaver.schemas import (
    FILE_MATCH_PATTERNS,
    SCHEMA_DIALECT,
    SCHEMA_ID,
    flow_schema_json,
)
from chainweaver.serialization import flow_to_dict


class TestSchemaShape:
    def test_top_level_keys(self) -> None:
        schema = flow_schema_json()
        assert schema["$schema"] == SCHEMA_DIALECT
        assert schema["$id"] == SCHEMA_ID
        assert "title" in schema
        assert "description" in schema
        assert "$defs" in schema
        assert schema["oneOf"] == [
            {"$ref": "#/$defs/Flow"},
            {"$ref": "#/$defs/DAGFlow"},
        ]

    def test_flow_def_has_type_discriminator(self) -> None:
        schema = flow_schema_json()
        flow_def = schema["$defs"]["Flow"]
        assert "type" in flow_def["properties"]
        assert flow_def["properties"]["type"] == {
            "type": "string",
            "const": "Flow",
            "description": flow_def["properties"]["type"]["description"],
        }
        assert "type" in flow_def["required"]

    def test_dag_def_has_type_discriminator(self) -> None:
        schema = flow_schema_json()
        dag_def = schema["$defs"]["DAGFlow"]
        assert dag_def["properties"]["type"] == {
            "type": "string",
            "const": "DAGFlow",
            "description": dag_def["properties"]["type"]["description"],
        }
        assert "type" in dag_def["required"]

    def test_flow_def_exposes_new_fields(self) -> None:
        """The schema reflects current Pydantic state — new fields show up."""
        schema = flow_schema_json()
        flow_def = schema["$defs"]["Flow"]
        # Issue #152 — context_schema_ref
        assert "context_schema_ref" in flow_def["properties"]
        # Issue #172 lives on FlowStep, which Pydantic surfaces via $defs.
        step_def = schema["$defs"]["FlowStep"]
        assert "input_contract" in step_def["properties"]
        assert "output_contract" in step_def["properties"]

    def test_file_match_patterns_cover_flow_extensions(self) -> None:
        assert "**/*.flow.json" in FILE_MATCH_PATTERNS
        assert "**/*.flow.yaml" in FILE_MATCH_PATTERNS
        assert "**/*.flow.yml" in FILE_MATCH_PATTERNS


class TestSchemaValidatesRoundTrip:
    """The emitted schema must validate the same payload ``flow_to_dict`` writes."""

    def test_flow_payload_matches_emitted_schema(self) -> None:
        # The strongest "this schema is correct" guarantee available
        # without a third-party validator: every key in the Pydantic-emit
        # payload appears as either a property or an allowed extra.
        flow = Flow(
            name="rt",
            version="0.1.0",
            description="Round-trip flow.",
            steps=[FlowStep(tool_name="double", input_mapping={"number": "number"})],
        )
        payload = flow_to_dict(flow)
        flow_def = flow_schema_json()["$defs"]["Flow"]
        for key in payload:
            assert key in flow_def["properties"], (
                f"Key '{key}' produced by flow_to_dict has no matching "
                f"property in the JSON Schema."
            )

    def test_dag_payload_matches_emitted_schema(self) -> None:
        dag = DAGFlow(
            name="d",
            version="0.1.0",
            description="DAG.",
            steps=[DAGFlowStep(tool_name="a", step_id="A", depends_on=[])],
        )
        payload = flow_to_dict(dag)
        dag_def = flow_schema_json()["$defs"]["DAGFlow"]
        for key in payload:
            assert key in dag_def["properties"], (
                f"Key '{key}' produced by flow_to_dict has no matching "
                f"property in the DAGFlow JSON Schema."
            )


class TestSchemaDeterminism:
    def test_emission_is_byte_identical_across_calls(self) -> None:
        """The schema must hash byte-identically across calls — CI's
        ``dump-schema --check`` depends on this.
        """
        a = json.dumps(flow_schema_json(), indent=2, sort_keys=True)
        b = json.dumps(flow_schema_json(), indent=2, sort_keys=True)
        assert a == b


class TestPublicExport:
    def test_flow_schema_json_is_exported(self) -> None:
        from chainweaver import flow_schema_json as exported

        assert exported is flow_schema_json


def test_schema_artifact_in_repo_is_up_to_date() -> None:
    """The checked-in artifact must match what ``flow_schema_json`` emits.

    This is the local mirror of the CI ``dump-schema --check`` guard.
    """
    from pathlib import Path

    artifact = Path(__file__).resolve().parents[1] / "schemas" / "flow.schema.json"
    if not artifact.exists():
        pytest.skip("schemas/flow.schema.json not present in this checkout")
    rendered = json.dumps(flow_schema_json(), indent=2, sort_keys=True) + "\n"
    on_disk = artifact.read_text(encoding="utf-8")
    assert on_disk == rendered, (
        "schemas/flow.schema.json is out of date. "
        "Run `chainweaver dump-schema --output schemas/flow.schema.json`."
    )
