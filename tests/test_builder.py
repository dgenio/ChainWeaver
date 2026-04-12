"""Unit tests for chainweaver.builder.FlowBuilder."""

from __future__ import annotations

import pytest
from helpers import FormattedOutput, NumberInput, ValueOutput

from chainweaver.builder import FlowBuilder, FlowBuilderError
from chainweaver.flow import Flow, FlowStep


class TestBasicBuild:
    def test_build_returns_flow(self) -> None:
        flow = FlowBuilder("my_flow", "Does something.").step("tool_a").build()
        assert isinstance(flow, Flow)

    def test_name_and_description_preserved(self) -> None:
        flow = FlowBuilder("my_flow", "My description.").step("tool_a").build()
        assert flow.name == "my_flow"
        assert flow.description == "My description."

    def test_steps_order_preserved(self) -> None:
        flow = (
            FlowBuilder("ordered", "Step order test.")
            .step("tool_a")
            .step("tool_b")
            .step("tool_c")
            .build()
        )
        assert [s.tool_name for s in flow.steps] == ["tool_a", "tool_b", "tool_c"]

    def test_equivalent_to_manual_construction(self) -> None:
        """FlowBuilder produces a Flow identical to direct construction."""
        builder_flow = (
            FlowBuilder("double_add_format", "Doubles a number, adds 10, and formats.")
            .step("double", number="number")
            .step("add_ten", value="value")
            .step("format_result", value="value")
            .build()
        )
        manual_flow = Flow(
            name="double_add_format",
            description="Doubles a number, adds 10, and formats.",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "number"}),
                FlowStep(tool_name="add_ten", input_mapping={"value": "value"}),
                FlowStep(tool_name="format_result", input_mapping={"value": "value"}),
            ],
        )
        assert builder_flow.name == manual_flow.name
        assert builder_flow.description == manual_flow.description
        assert len(builder_flow.steps) == len(manual_flow.steps)
        for b_step, m_step in zip(builder_flow.steps, manual_flow.steps, strict=True):
            assert b_step.tool_name == m_step.tool_name
            assert b_step.input_mapping == m_step.input_mapping


class TestStepMapping:
    def test_keyword_args_become_input_mapping(self) -> None:
        flow = FlowBuilder("f", "d.").step("tool_a", x="context_x", y="context_y").build()
        assert flow.steps[0].input_mapping == {"x": "context_x", "y": "context_y"}

    def test_no_kwargs_produces_empty_mapping(self) -> None:
        flow = FlowBuilder("f", "d.").step("tool_a").build()
        assert flow.steps[0].input_mapping == {}

    def test_literal_non_string_value_in_mapping(self) -> None:
        flow = FlowBuilder("f", "d.").step("scale", number="value", factor=3).build()
        step = flow.steps[0]
        assert step.input_mapping["number"] == "value"
        assert step.input_mapping["factor"] == 3

    def test_mixed_string_and_literal_values(self) -> None:
        flow = FlowBuilder("f", "d.").step("tool_a", a="ctx_a", b=True, c=1.5, d=0).build()
        mapping = flow.steps[0].input_mapping
        assert mapping["a"] == "ctx_a"
        assert mapping["b"] is True
        assert mapping["c"] == 1.5
        assert mapping["d"] == 0


class TestStepFrom:
    def test_step_from_accepts_prebuilt_step(self) -> None:
        pre = FlowStep(tool_name="tool_x", input_mapping={"k": "v"})
        flow = FlowBuilder("f", "d.").step_from(pre).build()
        assert flow.steps[0].tool_name == "tool_x"
        assert flow.steps[0].input_mapping == {"k": "v"}

    def test_step_from_and_step_can_be_mixed(self) -> None:
        pre = FlowStep(tool_name="tool_x", input_mapping={"k": "v"})
        flow = FlowBuilder("f", "d.").step("tool_a", x="x").step_from(pre).step("tool_b").build()
        assert [s.tool_name for s in flow.steps] == ["tool_a", "tool_x", "tool_b"]


class TestSchemaAndTrigger:
    def test_with_input_schema(self) -> None:
        flow = FlowBuilder("f", "d.").step("tool_a").with_input_schema(NumberInput).build()
        assert flow.input_schema is NumberInput

    def test_with_output_schema(self) -> None:
        flow = FlowBuilder("f", "d.").step("tool_a").with_output_schema(FormattedOutput).build()
        assert flow.output_schema is FormattedOutput

    def test_both_schemas(self) -> None:
        flow = (
            FlowBuilder("f", "d.")
            .step("tool_a")
            .with_input_schema(NumberInput)
            .with_output_schema(FormattedOutput)
            .build()
        )
        assert flow.input_schema is NumberInput
        assert flow.output_schema is FormattedOutput

    def test_with_trigger(self) -> None:
        conditions = {"event": "on_demand", "priority": 1}
        flow = FlowBuilder("f", "d.").step("tool_a").with_trigger(conditions).build()
        assert flow.trigger_conditions == conditions

    def test_no_schemas_defaults_to_none(self) -> None:
        flow = FlowBuilder("f", "d.").step("tool_a").build()
        assert flow.input_schema is None
        assert flow.output_schema is None
        assert flow.trigger_conditions is None


class TestMethodChaining:
    def test_step_returns_self(self) -> None:
        builder = FlowBuilder("f", "d.")
        result = builder.step("tool_a")
        assert result is builder

    def test_step_from_returns_self(self) -> None:
        builder = FlowBuilder("f", "d.")
        pre = FlowStep(tool_name="tool_x")
        result = builder.step_from(pre)
        assert result is builder

    def test_with_input_schema_returns_self(self) -> None:
        builder = FlowBuilder("f", "d.").step("tool_a")
        result = builder.with_input_schema(NumberInput)
        assert result is builder

    def test_with_output_schema_returns_self(self) -> None:
        builder = FlowBuilder("f", "d.").step("tool_a")
        result = builder.with_output_schema(ValueOutput)
        assert result is builder

    def test_with_trigger_returns_self(self) -> None:
        builder = FlowBuilder("f", "d.").step("tool_a")
        result = builder.with_trigger({"k": "v"})
        assert result is builder


class TestBuildErrors:
    def test_missing_name_raises_error(self) -> None:
        with pytest.raises(FlowBuilderError, match="'name'"):
            FlowBuilder("", "Some description.").step("tool_a").build()

    def test_missing_description_raises_error(self) -> None:
        with pytest.raises(FlowBuilderError, match="'description'"):
            FlowBuilder("my_flow", "").step("tool_a").build()

    def test_error_inherits_from_chainweaver_error(self) -> None:
        from chainweaver.exceptions import ChainWeaverError

        with pytest.raises(ChainWeaverError):
            FlowBuilder("", "d.").step("tool_a").build()

    def test_build_can_be_called_multiple_times(self) -> None:
        """build() is non-destructive — calling it twice returns equal flows."""
        builder = FlowBuilder("f", "d.").step("tool_a", x="x")
        flow1 = builder.build()
        flow2 = builder.build()
        assert flow1.name == flow2.name
        assert flow1.steps[0].input_mapping == flow2.steps[0].input_mapping


class TestIntegrationWithExecutor:
    """Verify that a FlowBuilder-produced flow executes correctly end-to-end."""

    def test_builder_flow_executes_successfully(
        self,
        double_tool,  # type: ignore[no-untyped-def]
        add_ten_tool,  # type: ignore[no-untyped-def]
        format_tool,  # type: ignore[no-untyped-def]
    ) -> None:
        from chainweaver.executor import FlowExecutor
        from chainweaver.registry import FlowRegistry

        flow = (
            FlowBuilder("double_add_format", "Doubles a number, adds 10, and formats.")
            .step("double", number="number")
            .step("add_ten", value="value")
            .step("format_result", value="value")
            .with_input_schema(NumberInput)
            .with_output_schema(FormattedOutput)
            .build()
        )

        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(double_tool)
        ex.register_tool(add_ten_tool)
        ex.register_tool(format_tool)

        result = ex.execute_flow("double_add_format", {"number": 5})
        assert result.success is True
        assert result.final_output is not None
        assert result.final_output["result"] == "Final value: 20"
