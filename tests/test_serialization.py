"""Tests for the flow serialization API (issue #14)."""

from __future__ import annotations

import pytest
from helpers import NumberInput, ValueOutput

from chainweaver.exceptions import FlowSerializationError
from chainweaver.flow import (
    DAGFlow,
    DAGFlowStep,
    Flow,
    FlowGovernance,
    FlowLifecycle,
    FlowStatus,
    FlowStep,
    RetryPolicy,
)
from chainweaver.serialization import (
    flow_from_dict,
    flow_from_json,
    flow_from_yaml,
    flow_to_dict,
    flow_to_yaml,
)

# ---------------------------------------------------------------------------
# Reusable fixtures
# ---------------------------------------------------------------------------


def _make_linear() -> Flow:
    return Flow(
        name="lin",
        version="1.2.3",
        description="Linear flow.",
        steps=[
            FlowStep(tool_name="double", input_mapping={"number": "number"}),
            FlowStep(tool_name="add_ten", input_mapping={"value": "value"}),
        ],
    )


def _make_dag() -> DAGFlow:
    return DAGFlow(
        name="diamond",
        version="0.9.0",
        description="A -> (B, C) -> D",
        steps=[
            DAGFlowStep(tool_name="a", step_id="A", depends_on=[]),
            DAGFlowStep(tool_name="b", step_id="B", depends_on=["A"]),
            DAGFlowStep(tool_name="c", step_id="C", depends_on=["A"]),
            DAGFlowStep(tool_name="d", step_id="D", depends_on=["B", "C"]),
        ],
    )


# ---------------------------------------------------------------------------
# JSON round-trip
# ---------------------------------------------------------------------------


class TestJsonRoundTrip:
    def test_linear_round_trips(self) -> None:
        flow = _make_linear()
        restored = Flow.from_json(flow.to_json())
        assert restored == flow

    def test_dag_round_trips(self) -> None:
        flow = _make_dag()
        restored = DAGFlow.from_json(flow.to_json())
        assert restored == flow

    def test_dispatch_via_flow_from_dict(self) -> None:
        flow = _make_dag()
        restored = flow_from_dict(flow_to_dict(flow))
        assert isinstance(restored, DAGFlow)
        assert restored.name == "diamond"

    def test_indent_none_produces_compact_json(self) -> None:
        flow = _make_linear()
        compact = flow.to_json(indent=None)
        assert "\n" not in compact

    def test_indent_default_pretty_prints(self) -> None:
        flow = _make_linear()
        pretty = flow.to_json()
        assert "\n" in pretty


# ---------------------------------------------------------------------------
# YAML round-trip
# ---------------------------------------------------------------------------


class TestYamlRoundTrip:
    def test_linear_round_trips(self) -> None:
        flow = _make_linear()
        restored = Flow.from_yaml(flow.to_yaml())
        assert restored == flow

    def test_dag_round_trips(self) -> None:
        flow = _make_dag()
        restored = DAGFlow.from_yaml(flow.to_yaml())
        assert restored == flow

    def test_yaml_is_block_style(self) -> None:
        # block style YAML uses key: value on its own line, never flow-style {a: b}
        yaml_text = _make_linear().to_yaml()
        assert "{" not in yaml_text
        assert "\nname: lin" in yaml_text


# ---------------------------------------------------------------------------
# Schema ref round-trip
# ---------------------------------------------------------------------------


class TestSchemaRefs:
    def test_input_schema_ref_round_trips(self) -> None:
        flow = Flow(
            name="ref",
            version="1.0.0",
            description="With schema refs.",
            steps=[FlowStep(tool_name="double")],
            input_schema_ref=Flow.schema_ref_from(NumberInput),
            output_schema_ref=Flow.schema_ref_from(ValueOutput),
        )
        restored = Flow.from_json(flow.to_json())
        assert restored.input_schema_ref == "helpers:NumberInput"
        assert restored.input_schema is NumberInput
        assert restored.output_schema is ValueOutput

    def test_unresolvable_module_raises(self) -> None:
        flow = Flow(
            name="bad",
            version="1.0.0",
            description="Broken ref.",
            steps=[FlowStep(tool_name="x")],
            input_schema_ref="no_such_module:Foo",
        )
        with pytest.raises(FlowSerializationError, match="Cannot import module"):
            _ = flow.input_schema

    def test_unresolvable_attribute_raises(self) -> None:
        flow = Flow(
            name="bad",
            version="1.0.0",
            description="Broken ref.",
            steps=[FlowStep(tool_name="x")],
            input_schema_ref="helpers:DoesNotExist",
        )
        with pytest.raises(FlowSerializationError, match="not found"):
            _ = flow.input_schema

    def test_ref_resolving_to_non_basemodel_raises(self) -> None:
        flow = Flow(
            name="bad",
            version="1.0.0",
            description="Resolves to a function, not a class.",
            steps=[FlowStep(tool_name="x")],
            input_schema_ref="helpers:_double_fn",
        )
        with pytest.raises(FlowSerializationError, match="expected a class"):
            _ = flow.input_schema

    def test_ref_resolving_to_wrong_base_raises(self) -> None:
        flow = Flow(
            name="bad",
            version="1.0.0",
            description="Resolves to int, not BaseModel.",
            steps=[FlowStep(tool_name="x")],
            input_schema_ref="builtins:int",
        )
        with pytest.raises(FlowSerializationError, match="not a subclass"):
            _ = flow.input_schema

    def test_missing_colon_raises(self) -> None:
        flow = Flow(
            name="bad",
            version="1.0.0",
            description="Malformed ref.",
            steps=[FlowStep(tool_name="x")],
            input_schema_ref="helpers.NumberInput",  # dot instead of colon
        )
        with pytest.raises(FlowSerializationError, match="'module:qualname' form"):
            _ = flow.input_schema

    def test_no_schema_ref_returns_none(self) -> None:
        flow = Flow(
            name="bare",
            version="1.0.0",
            description="No schemas.",
            steps=[FlowStep(tool_name="x")],
        )
        assert flow.input_schema is None
        assert flow.output_schema is None


# ---------------------------------------------------------------------------
# RetryPolicy refs
# ---------------------------------------------------------------------------


class TestRetryPolicyRefs:
    def test_default_resolves_to_exception(self) -> None:
        policy = RetryPolicy()
        assert policy.retryable_errors == ("builtins:Exception",)
        assert policy.resolved_retryable_errors() == (Exception,)

    def test_custom_resolves(self) -> None:
        policy = RetryPolicy(retryable_errors=("builtins:KeyError", "builtins:ValueError"))
        assert policy.resolved_retryable_errors() == (KeyError, ValueError)

    def test_missing_colon_rejected_at_validation(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="'module:qualname' form"):
            RetryPolicy(retryable_errors=("builtins.KeyError",))

    def test_empty_tuple_rejected(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError, match="at least one"):
            RetryPolicy(retryable_errors=())

    def test_unresolvable_raises_on_resolve(self) -> None:
        policy = RetryPolicy(retryable_errors=("no_such_module:NoSuchError",))
        with pytest.raises(FlowSerializationError):
            policy.resolved_retryable_errors()

    def test_non_exception_class_rejected_on_resolve(self) -> None:
        policy = RetryPolicy(retryable_errors=("builtins:int",))
        with pytest.raises(FlowSerializationError, match="not a subclass"):
            policy.resolved_retryable_errors()

    def test_retry_policy_round_trips_through_flow_json(self) -> None:
        flow = Flow(
            name="ret",
            version="1.0.0",
            description="With retry.",
            steps=[
                FlowStep(
                    tool_name="x",
                    retry=RetryPolicy(retryable_errors=("builtins:KeyError",)),
                )
            ],
        )
        restored = Flow.from_json(flow.to_json())
        assert restored.steps[0].retry is not None
        assert restored.steps[0].retry.retryable_errors == ("builtins:KeyError",)


# ---------------------------------------------------------------------------
# Other Flow fields round-trip
# ---------------------------------------------------------------------------


class TestMiscFieldsRoundTrip:
    def test_tool_schema_hashes_round_trips(self) -> None:
        flow = Flow(
            name="hashed",
            version="1.0.0",
            description="Hashes attached.",
            steps=[FlowStep(tool_name="x")],
            tool_schema_hashes={"x": "abcdef0123456789"},
        )
        restored = Flow.from_json(flow.to_json())
        assert restored.tool_schema_hashes == {"x": "abcdef0123456789"}

    def test_trigger_conditions_round_trips(self) -> None:
        flow = Flow(
            name="trig",
            version="1.0.0",
            description="Has triggers.",
            steps=[FlowStep(tool_name="x")],
            trigger_conditions={"on_intent": "summarize", "min_words": 50},
        )
        restored = Flow.from_json(flow.to_json())
        assert restored.trigger_conditions == {"on_intent": "summarize", "min_words": 50}

    def test_status_round_trips(self) -> None:
        flow = Flow(
            name="stat",
            version="1.0.0",
            description="Disabled.",
            steps=[FlowStep(tool_name="x")],
            status=FlowStatus.DISABLED,
        )
        restored = Flow.from_json(flow.to_json())
        assert restored.status is FlowStatus.DISABLED

    def test_governance_round_trips(self) -> None:
        flow = Flow(
            name="candidate",
            version="0.0.0",
            description="Candidate.",
            steps=[FlowStep(tool_name="x")],
            governance=FlowGovernance(
                lifecycle=FlowLifecycle.REVIEWED,
                owner="platform",
                replaces_tools=("x",),
                estimated_model_calls_removed=7,
                estimated_token_savings=1200,
                reviewed_by="maintainer",
            ),
        )
        restored = Flow.from_json(flow.to_json())
        assert restored.governance == flow.governance

    def test_legacy_requires_review_is_preserved_on_yaml_load(self) -> None:
        restored = flow_from_yaml(
            """
type: Flow
name: legacy-safety
version: 1.0.0
description: Legacy safety payload.
steps:
  - tool_name: x
safety:
  requires_review: true
"""
        )
        assert restored.safety is not None
        assert restored.safety.requires_approval is True


class TestFlowLifecycle:
    def test_valid_promotion_path(self) -> None:
        governance = FlowGovernance(lifecycle=FlowLifecycle.SUGGESTED)
        governance = governance.transition_to(FlowLifecycle.DRAFT)
        governance = governance.transition_to(
            FlowLifecycle.REVIEWED,
            reviewed_by="maintainer",
        )
        governance = governance.transition_to(FlowLifecycle.ACTIVE)
        assert governance.lifecycle is FlowLifecycle.ACTIVE
        assert governance.reviewed_by == "maintainer"

    def test_invalid_transition_raises(self) -> None:
        governance = FlowGovernance(lifecycle=FlowLifecycle.DRAFT)
        with pytest.raises(ValueError, match="cannot transition"):
            governance.transition_to(FlowLifecycle.ACTIVE)

    @pytest.mark.parametrize(
        ("source", "target"),
        [
            (FlowLifecycle.OBSERVED, FlowLifecycle.SUGGESTED),
            (FlowLifecycle.OBSERVED, FlowLifecycle.IGNORED),
            (FlowLifecycle.SUGGESTED, FlowLifecycle.DRAFT),
            (FlowLifecycle.SUGGESTED, FlowLifecycle.IGNORED),
            (FlowLifecycle.DRAFT, FlowLifecycle.REVIEWED),
            (FlowLifecycle.DRAFT, FlowLifecycle.IGNORED),
            (FlowLifecycle.REVIEWED, FlowLifecycle.DRAFT),
            (FlowLifecycle.REVIEWED, FlowLifecycle.ACTIVE),
            (FlowLifecycle.REVIEWED, FlowLifecycle.ARCHIVED),
            (FlowLifecycle.ACTIVE, FlowLifecycle.ARCHIVED),
            (FlowLifecycle.IGNORED, FlowLifecycle.SUGGESTED),
            (FlowLifecycle.ARCHIVED, FlowLifecycle.REVIEWED),
        ],
    )
    def test_supported_transition(self, source: FlowLifecycle, target: FlowLifecycle) -> None:
        governance = FlowGovernance(lifecycle=source)
        assert governance.transition_to(target).lifecycle is target

    @pytest.mark.parametrize(
        ("source", "target"),
        [
            (FlowLifecycle.OBSERVED, FlowLifecycle.ACTIVE),
            (FlowLifecycle.DRAFT, FlowLifecycle.ARCHIVED),
            (FlowLifecycle.ACTIVE, FlowLifecycle.DRAFT),
            (FlowLifecycle.IGNORED, FlowLifecycle.ACTIVE),
        ],
    )
    def test_unsupported_transition_raises(
        self,
        source: FlowLifecycle,
        target: FlowLifecycle,
    ) -> None:
        with pytest.raises(ValueError, match="cannot transition"):
            FlowGovernance(lifecycle=source).transition_to(target)


# ---------------------------------------------------------------------------
# Error paths
# ---------------------------------------------------------------------------


class TestErrorPaths:
    def test_invalid_json_raises_serialization_error(self) -> None:
        with pytest.raises(FlowSerializationError, match="Invalid JSON"):
            flow_from_json("{not valid json")

    def test_invalid_json_records_source_context(self) -> None:
        with pytest.raises(FlowSerializationError, match=r"bad\.flow\.json") as exc_info:
            flow_from_json("{not valid json", source="flows/bad.flow.json")
        assert exc_info.value.source == "flows/bad.flow.json"
        assert "Invalid JSON" in exc_info.value.detail

    def test_invalid_yaml_raises_serialization_error(self) -> None:
        with pytest.raises(FlowSerializationError, match="Invalid YAML"):
            flow_from_yaml("key: [unbalanced")

    def test_invalid_yaml_records_source_context(self) -> None:
        with pytest.raises(FlowSerializationError, match=r"bad\.flow\.yaml") as exc_info:
            flow_from_yaml("key: [unbalanced", source="flows/bad.flow.yaml")
        assert exc_info.value.source == "flows/bad.flow.yaml"
        assert "Invalid YAML" in exc_info.value.detail

    def test_empty_yaml_raises_serialization_error(self) -> None:
        with pytest.raises(FlowSerializationError, match="empty"):
            flow_from_yaml("")

    def test_missing_type_discriminator_raises(self) -> None:
        with pytest.raises(FlowSerializationError, match="discriminator"):
            flow_from_dict({"name": "x", "version": "1.0.0", "description": "y", "steps": []})

    def test_unknown_type_discriminator_raises(self) -> None:
        with pytest.raises(FlowSerializationError, match="discriminator"):
            flow_from_dict(
                {
                    "type": "PickleFlow",
                    "name": "x",
                    "version": "1.0.0",
                    "description": "y",
                    "steps": [],
                }
            )

    def test_non_dict_payload_raises(self) -> None:
        with pytest.raises(FlowSerializationError, match="mapping"):
            flow_from_dict(["not", "a", "dict"])  # type: ignore[arg-type]

    def test_missing_required_field_raises(self) -> None:
        with pytest.raises(FlowSerializationError, match="Validation failed"):
            flow_from_dict({"type": "Flow", "name": "x"})  # missing version/description/steps

    def test_from_json_flow_payload_to_dag_class_fails(self) -> None:
        flow = _make_linear()
        with pytest.raises(FlowSerializationError, match="DAGFlow"):
            DAGFlow.from_json(flow.to_json())

    def test_from_json_classmethod_preserves_source_on_type_mismatch(self) -> None:
        flow = _make_linear()
        with pytest.raises(FlowSerializationError, match=r"flow\.json") as exc_info:
            DAGFlow.from_json(flow.to_json(), source="flows/flow.json")
        assert exc_info.value.source == "flows/flow.json"

    def test_from_json_dag_payload_to_flow_class_fails(self) -> None:
        flow = _make_dag()
        with pytest.raises(FlowSerializationError, match="Flow"):
            Flow.from_json(flow.to_json())


# ---------------------------------------------------------------------------
# Missing pyyaml fallback (simulated)
# ---------------------------------------------------------------------------


class TestYamlNotAvailable:
    def test_clear_error_when_yaml_missing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When pyyaml is not importable, both encode and decode error cleanly."""
        import builtins

        real_import = builtins.__import__

        def fake_import(name: str, *args: object, **kwargs: object) -> object:
            if name == "yaml":
                raise ImportError("simulated missing pyyaml")
            return real_import(name, *args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(builtins, "__import__", fake_import)

        with pytest.raises(FlowSerializationError, match="pyyaml"):
            flow_to_yaml(_make_linear())
        with pytest.raises(FlowSerializationError, match="pyyaml"):
            flow_from_yaml("type: Flow\nname: x\nversion: 1.0.0\ndescription: y\nsteps: []\n")
