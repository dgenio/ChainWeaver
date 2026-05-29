"""Tests for the property-based fuzzing harness (issues #220, #221)."""

from __future__ import annotations

from typing import Any

import pytest
from helpers import NumberInput, ValueOutput, _double_fn

from chainweaver import (
    BUILTIN_PROPERTIES,
    ExecutionResult,
    FaultConfig,
    Flow,
    FlowExecutor,
    FlowFuzzer,
    FlowProperty,
    FlowRegistry,
    FlowStep,
    FuzzConfigError,
    Tool,
    minimize_failure,
)
from chainweaver import attest as attest_module
from chainweaver.middleware import (
    FlowEndContext,
    FlowStartContext,
    StepEndContext,
    StepStartContext,
)


class _RecordingMiddleware:
    """Records every middleware hook invocation, mirroring test_middleware.py."""

    def __init__(self) -> None:
        self.events: list[tuple[str, Any]] = []

    def on_flow_start(self, ctx: FlowStartContext) -> None:
        self.events.append(("flow_start", ctx))

    def on_step_start(self, ctx: StepStartContext) -> None:
        self.events.append(("step_start", ctx))

    def on_step_end(self, ctx: StepEndContext) -> None:
        self.events.append(("step_end", ctx))

    def on_flow_end(self, ctx: FlowEndContext) -> None:
        self.events.append(("flow_end", ctx))


def _build() -> tuple[FlowExecutor, Flow]:
    """A single-step doubling flow with an input_schema, plus its executor."""
    flow = Flow(
        name="fuzz_double",
        version="0.1.0",
        description="Doubles a number.",
        steps=[FlowStep(tool_name="double", input_mapping={"number": "number"})],
        input_schema_ref=Flow.schema_ref_from(NumberInput),
    )
    registry = FlowRegistry()
    registry.register_flow(flow)
    executor = FlowExecutor(registry=registry)
    executor.register_tool(
        Tool(
            name="double",
            description="Doubles.",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=_double_fn,
        )
    )
    return executor, flow


_ALWAYS_FALSE = FlowProperty("always_false", lambda _r: False, "Never holds.")


class TestFlowFuzzerBasics:
    def test_requires_at_least_one_property(self) -> None:
        executor, flow = _build()
        with pytest.raises(FuzzConfigError):
            FlowFuzzer(executor=executor, flow=flow, properties=[])

    def test_runs_must_be_positive(self) -> None:
        executor, flow = _build()
        fuzzer = FlowFuzzer(
            executor=executor, flow=flow, properties=[BUILTIN_PROPERTIES["flow_succeeds"]]
        )
        with pytest.raises(FuzzConfigError):
            fuzzer.run(runs=0, seed=1)

    def test_schema_generation_when_no_base_input(self) -> None:
        executor, flow = _build()
        fuzzer = FlowFuzzer(
            executor=executor, flow=flow, properties=[BUILTIN_PROPERTIES["flow_succeeds"]]
        )
        report = fuzzer.run(runs=20, seed=7)
        assert report.runs == 20
        assert report.property_names == ["flow_succeeds"]
        # Case 0 is the pristine, schema-valid generated input — it always runs
        # cleanly.  Later cases may be mutated (e.g. the required ``number`` key
        # dropped), and such adversarial inputs legitimately surface as failures.
        assert 0 not in {f.case_index for f in report.failures}

    def test_schema_generation_is_deterministic(self) -> None:
        executor, flow = _build()
        prop = [BUILTIN_PROPERTIES["flow_succeeds"]]
        a = FlowFuzzer(executor=executor, flow=flow, properties=prop).run(runs=20, seed=7)
        b = FlowFuzzer(executor=executor, flow=flow, properties=prop).run(runs=20, seed=7)
        assert [f.initial_input for f in a.failures] == [f.initial_input for f in b.failures]

    def test_missing_schema_without_base_input_errors(self) -> None:
        # A flow with no input_schema_ref cannot generate inputs.
        flow = Flow(
            name="no_schema",
            description="No schema.",
            steps=[FlowStep(tool_name="double", input_mapping={"number": "number"})],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        executor = FlowExecutor(registry=registry)
        executor.register_tool(
            Tool(
                name="double",
                description="Doubles.",
                input_schema=NumberInput,
                output_schema=ValueOutput,
                fn=_double_fn,
            )
        )
        fuzzer = FlowFuzzer(
            executor=executor, flow=flow, properties=[BUILTIN_PROPERTIES["flow_succeeds"]]
        )
        with pytest.raises(FuzzConfigError):
            fuzzer.run(runs=5, seed=1)


class TestViolationDetection:
    def test_always_false_property_fails_every_case(self) -> None:
        executor, flow = _build()
        fuzzer = FlowFuzzer(executor=executor, flow=flow, properties=[_ALWAYS_FALSE])
        report = fuzzer.run(runs=8, seed=1, base_input={"number": 3})
        assert report.num_failures == 8
        assert not report.passed
        assert all(f.property_name == "always_false" for f in report.failures)
        assert {f.case_index for f in report.failures} == set(range(8))

    def test_raising_property_is_recorded_as_violation(self) -> None:
        executor, flow = _build()

        def _boom(_r: ExecutionResult) -> bool:
            raise RuntimeError("kaboom")

        prop = FlowProperty("boom", _boom)
        fuzzer = FlowFuzzer(executor=executor, flow=flow, properties=[prop])
        report = fuzzer.run(runs=3, seed=1, base_input={"number": 1})
        assert report.num_failures == 3
        assert report.failures[0].check_error is not None
        assert "RuntimeError: kaboom" in report.failures[0].check_error

    def test_failure_carries_replayable_trace(self) -> None:
        executor, flow = _build()
        fuzzer = FlowFuzzer(executor=executor, flow=flow, properties=[_ALWAYS_FALSE])
        report = fuzzer.run(runs=1, seed=1, base_input={"number": 21})
        failure = report.failures[0]
        assert isinstance(failure.result, ExecutionResult)
        # The carried input replays to the same successful doubling result.
        replayed = executor.execute_flow(flow.name, failure.initial_input)
        assert replayed.success
        assert replayed.final_output is not None
        assert replayed.final_output["value"] == 42


class TestDeterminism:
    def test_same_seed_same_failures(self) -> None:
        executor, flow = _build()
        prop = [BUILTIN_PROPERTIES["flow_succeeds"]]
        a = FlowFuzzer(executor=executor, flow=flow, properties=prop).run(runs=40, seed=99)
        b = FlowFuzzer(executor=executor, flow=flow, properties=prop).run(runs=40, seed=99)
        assert [f.initial_input for f in a.failures] == [f.initial_input for f in b.failures]
        assert a.num_failures == b.num_failures

    def test_base_input_mutation_is_seeded(self) -> None:
        executor, flow = _build()
        fuzzer = FlowFuzzer(executor=executor, flow=flow, properties=[_ALWAYS_FALSE])
        a = fuzzer.run(runs=10, seed=5, base_input={"number": 2})
        b = fuzzer.run(runs=10, seed=5, base_input={"number": 2})
        assert [f.initial_input for f in a.failures] == [f.initial_input for f in b.failures]
        # Case 0 is the pristine base input; later cases may be mutated.
        assert a.failures[0].initial_input == {"number": 2}


class TestFaultInjection:
    def test_custom_fault_hook_breaks_every_run(self) -> None:
        executor, flow = _build()

        def _drop_all(_name: str, _outputs: dict[str, Any], _rng: Any) -> dict[str, Any]:
            return {}  # empty output -> required 'value' missing -> step fails

        fuzzer = FlowFuzzer(
            executor=executor,
            flow=flow,
            properties=[BUILTIN_PROPERTIES["flow_succeeds"]],
            fault_hook=_drop_all,
        )
        report = fuzzer.run(runs=6, seed=1, base_input={"number": 4})
        assert report.num_failures == 6

    def test_fault_injection_does_not_mutate_caller_executor(self) -> None:
        executor, flow = _build()

        def _drop_all(_name: str, _outputs: dict[str, Any], _rng: Any) -> dict[str, Any]:
            return {}

        FlowFuzzer(
            executor=executor,
            flow=flow,
            properties=[BUILTIN_PROPERTIES["flow_succeeds"]],
            fault_hook=_drop_all,
        ).run(runs=3, seed=1, base_input={"number": 4})
        # The caller's executor still runs the real (un-faulted) tool.
        clean = executor.execute_flow(flow.name, {"number": 4})
        assert clean.success
        assert clean.final_output is not None
        assert clean.final_output["value"] == 8

    def test_fault_config_probability_is_reproducible(self) -> None:
        executor, flow = _build()
        prop = [BUILTIN_PROPERTIES["flow_succeeds"]]
        config = FaultConfig(output_fault_probability=1.0)
        assert config.active
        a = FlowFuzzer(executor=executor, flow=flow, properties=prop, fault_config=config).run(
            runs=30, seed=3, base_input={"number": 4}
        )
        b = FlowFuzzer(executor=executor, flow=flow, properties=prop, fault_config=config).run(
            runs=30, seed=3, base_input={"number": 4}
        )
        assert a.num_failures == b.num_failures
        assert a.num_failures > 0

    def test_invalid_fault_probability_rejected(self) -> None:
        with pytest.raises(FuzzConfigError):
            FaultConfig(output_fault_probability=1.5)


class TestMinimize:
    def test_shrinks_to_minimal_reproducer(self) -> None:
        executor, flow = _build()
        # Violated whenever the input carries a key other than "number".
        prop = FlowProperty(
            "only_number",
            lambda r: set(r.initial_input.keys()) <= {"number"},
        )
        failing = {"number": 7, "junk": "leak", "extra": 99}
        minimized = minimize_failure(executor, flow, failing, prop)
        # Still violates, and is strictly smaller than the noisy original.
        assert set(minimized.keys()) - {"number"}
        assert len(minimized) < len(failing)
        replayed = executor.execute_flow(flow.name, minimized)
        assert set(replayed.initial_input.keys()) - {"number"}

    def test_minimize_rejects_non_violating_input(self) -> None:
        executor, flow = _build()
        prop = BUILTIN_PROPERTIES["flow_succeeds"]
        with pytest.raises(FuzzConfigError):
            # A valid input succeeds, so there is nothing to minimize.
            minimize_failure(executor, flow, {"number": 1}, prop)


class TestBuiltinProperties:
    def test_final_output_present_holds_on_success(self) -> None:
        executor, flow = _build()
        result = executor.execute_flow(flow.name, {"number": 2})
        assert BUILTIN_PROPERTIES["final_output_present"].holds(result)
        assert BUILTIN_PROPERTIES["flow_succeeds"].holds(result)


class TestExecutorConfigPreservation:
    """Fault injection must not silently drop executor configuration (#220 review)."""

    def test_middleware_preserved_under_fault_injection(self) -> None:
        executor, flow = _build()
        rec = _RecordingMiddleware()
        executor.add_middleware(rec)
        fuzzer = FlowFuzzer(
            executor=executor,
            flow=flow,
            properties=[BUILTIN_PROPERTIES["flow_succeeds"]],
            fault_config=FaultConfig(output_fault_probability=1.0),
        )
        fuzzer.run(runs=3, seed=1)
        # The per-case executor built for fault injection must reuse the
        # configured middleware, so its hooks fire.  Before the fix it built a
        # bare FlowExecutor and recorded nothing.
        kinds = {kind for kind, _ in rec.events}
        assert "flow_start" in kinds
        assert "flow_end" in kinds

    def test_with_replaced_tools_preserves_config_and_swaps_tools(self) -> None:
        executor, flow = _build()
        rec = _RecordingMiddleware()
        executor.add_middleware(rec)

        def _tripled(inp: NumberInput) -> dict[str, Any]:
            return {"value": inp.number * 3}

        replacement = Tool(
            name="double",  # same name, different behavior
            description="Actually triples.",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=_tripled,
        )
        clone = executor.with_replaced_tools([replacement])
        result = clone.execute_flow(flow.name, {"number": 4})
        assert result.final_output is not None
        assert result.final_output["value"] == 12  # swapped tool ran
        assert any(kind == "flow_end" for kind, _ in rec.events)  # config preserved


class TestSharedSchemaGenerator:
    """The schema-value generator is a supported public API (#220 review)."""

    def test_generator_helpers_are_public(self) -> None:
        from chainweaver.attest import UnsupportedAnnotation, generate_value

        assert "generate_value" in attest_module.__all__
        assert "UnsupportedAnnotation" in attest_module.__all__
        assert callable(generate_value)
        assert issubclass(UnsupportedAnnotation, Exception)
