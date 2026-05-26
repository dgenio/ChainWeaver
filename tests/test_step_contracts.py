"""Tests for typed step contracts and ``Flow.context_schema_ref``.

Covers issues #172 (step input/output contracts) and #152
(``Flow.context_schema_ref``).
"""

from __future__ import annotations

import pytest
from helpers import (
    FormattedOutput,
    LinearContextSchema,
    NumberInput,
    ValueInput,
    ValueOutput,
    _add_ten_fn,
    _double_fn,
    _format_fn,
)
from pydantic import BaseModel

from chainweaver.cache import InMemoryStepCache
from chainweaver.exceptions import FlowSerializationError
from chainweaver.executor import FlowExecutor
from chainweaver.flow import (
    DAGFlow,
    DAGFlowStep,
    Flow,
    FlowStep,
    RetryPolicy,
)
from chainweaver.registry import FlowRegistry
from chainweaver.serialization import flow_from_json
from chainweaver.tools import Tool

# ---------------------------------------------------------------------------
# Local fixtures (kept here so contract tests stay self-contained)
# ---------------------------------------------------------------------------


@pytest.fixture()
def double_tool() -> Tool:
    return Tool(
        name="double",
        description="Doubles a number.",
        input_schema=NumberInput,
        output_schema=ValueOutput,
        fn=_double_fn,
    )


@pytest.fixture()
def add_ten_tool() -> Tool:
    return Tool(
        name="add_ten",
        description="Adds 10 to a value.",
        input_schema=ValueInput,
        output_schema=ValueOutput,
        fn=_add_ten_fn,
    )


@pytest.fixture()
def format_tool() -> Tool:
    return Tool(
        name="format_result",
        description="Formats a value.",
        input_schema=ValueInput,
        output_schema=FormattedOutput,
        fn=_format_fn,
    )


# ---------------------------------------------------------------------------
# Step-level input_contract (issue #172)
# ---------------------------------------------------------------------------


class _StrictDoubleInput(BaseModel):
    number: int


class _StrictAddTenInput(BaseModel):
    value: int


class _MismatchedInput(BaseModel):
    not_a_number: str


class _StrictDoubleOutput(BaseModel):
    value: int


class _MismatchedOutput(BaseModel):
    other_field: str


class TestStepInputContract:
    def test_valid_input_contract_passes(
        self, double_tool: Tool, add_ten_tool: Tool, format_tool: Tool
    ) -> None:
        flow = Flow(
            name="contract_flow",
            version="0.1.0",
            description="Flow with input contracts on every step.",
            steps=[
                FlowStep(
                    tool_name="double",
                    input_mapping={"number": "number"},
                    input_contract=FlowStep.contract_ref_from(_StrictDoubleInput),
                ),
                FlowStep(
                    tool_name="add_ten",
                    input_mapping={"value": "value"},
                    input_contract=FlowStep.contract_ref_from(_StrictAddTenInput),
                ),
                FlowStep(tool_name="format_result", input_mapping={"value": "value"}),
            ],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(double_tool)
        ex.register_tool(add_ten_tool)
        ex.register_tool(format_tool)

        result = ex.execute_flow("contract_flow", {"number": 5})
        assert result.success is True
        assert result.final_output is not None
        assert result.final_output["result"] == "Final value: 20"

    def test_invalid_input_contract_fails_step(self, double_tool: Tool) -> None:
        """A mismatched input contract aborts the step before the tool runs."""
        flow = Flow(
            name="bad_contract",
            version="0.1.0",
            description="Step contract rejects the wired inputs.",
            steps=[
                FlowStep(
                    tool_name="double",
                    input_mapping={"number": "number"},
                    input_contract=FlowStep.contract_ref_from(_MismatchedInput),
                ),
            ],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(double_tool)

        result = ex.execute_flow("bad_contract", {"number": 5})
        assert result.success is False
        assert result.final_output is None
        assert len(result.execution_log) == 1
        record = result.execution_log[0]
        assert record.success is False
        assert record.error_type == "SchemaValidationError"
        assert "step_input_contract" in (record.error_message or "")

    def test_resolved_input_contract_property(self) -> None:
        step = FlowStep(
            tool_name="double",
            input_contract=FlowStep.contract_ref_from(_StrictDoubleInput),
        )
        assert step.resolved_input_contract is _StrictDoubleInput

    def test_resolved_input_contract_none_when_unset(self) -> None:
        step = FlowStep(tool_name="double")
        assert step.resolved_input_contract is None


# ---------------------------------------------------------------------------
# Step-level output_contract (issue #172)
# ---------------------------------------------------------------------------


class TestStepOutputContract:
    def test_valid_output_contract_passes(self, double_tool: Tool) -> None:
        flow = Flow(
            name="out_contract",
            version="0.1.0",
            description="Flow with an output contract.",
            steps=[
                FlowStep(
                    tool_name="double",
                    input_mapping={"number": "number"},
                    output_contract=FlowStep.contract_ref_from(_StrictDoubleOutput),
                ),
            ],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(double_tool)

        result = ex.execute_flow("out_contract", {"number": 7})
        assert result.success is True
        assert result.final_output == {"number": 7, "value": 14}

    def test_invalid_output_contract_fails_step(self, double_tool: Tool) -> None:
        """A tool whose outputs don't satisfy the step's output contract fails."""
        flow = Flow(
            name="bad_out_contract",
            version="0.1.0",
            description="Output contract demands a field the tool never produces.",
            steps=[
                FlowStep(
                    tool_name="double",
                    input_mapping={"number": "number"},
                    output_contract=FlowStep.contract_ref_from(_MismatchedOutput),
                ),
            ],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(double_tool)

        result = ex.execute_flow("bad_out_contract", {"number": 5})
        assert result.success is False
        assert len(result.execution_log) == 1
        record = result.execution_log[0]
        assert record.error_type == "SchemaValidationError"
        assert "step_output_contract" in (record.error_message or "")
        # outputs are nulled out on contract failure — the wiring is the
        # caller's problem to fix.
        assert record.outputs is None

    def test_unresolvable_output_contract_ref_raises(self, double_tool: Tool) -> None:
        flow = Flow(
            name="bad_ref",
            version="0.1.0",
            description="Output contract ref doesn't resolve.",
            steps=[
                FlowStep(
                    tool_name="double",
                    input_mapping={"number": "number"},
                    output_contract="no_such_module:NoClass",
                ),
            ],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(double_tool)

        with pytest.raises(FlowSerializationError, match="Cannot import module"):
            ex.execute_flow("bad_ref", {"number": 5})


# ---------------------------------------------------------------------------
# Serialization round-trip for contract fields (issue #172)
# ---------------------------------------------------------------------------


class TestContractFieldsRoundTrip:
    def test_contract_refs_round_trip_via_json(self) -> None:
        flow = Flow(
            name="rt",
            version="0.1.0",
            description="Round-trip flow with contracts.",
            steps=[
                FlowStep(
                    tool_name="double",
                    input_mapping={"number": "number"},
                    input_contract=FlowStep.contract_ref_from(_StrictDoubleInput),
                    output_contract=FlowStep.contract_ref_from(_StrictDoubleOutput),
                ),
            ],
        )
        restored = flow_from_json(flow.to_json())
        assert isinstance(restored, Flow)
        assert restored.steps[0].input_contract == flow.steps[0].input_contract
        assert restored.steps[0].output_contract == flow.steps[0].output_contract


# ---------------------------------------------------------------------------
# Flow.context_schema_ref (issue #152)
# ---------------------------------------------------------------------------


class _PartialContextSchema(BaseModel):
    # Demands a field no tool produces — the context-schema gate must fail.
    missing_field: str


class TestFlowContextSchema:
    def test_context_schema_resolves_to_class(self) -> None:
        flow = Flow(
            name="ctx",
            version="0.1.0",
            description="Flow with a context schema.",
            steps=[],
            context_schema_ref=Flow.schema_ref_from(LinearContextSchema),
        )
        assert flow.context_schema is LinearContextSchema

    def test_context_schema_none_when_unset(self) -> None:
        flow = Flow(
            name="ctx_none",
            version="0.1.0",
            description="No context schema.",
            steps=[],
        )
        assert flow.context_schema is None

    def test_context_schema_validates_at_flow_end(
        self, double_tool: Tool, add_ten_tool: Tool, format_tool: Tool
    ) -> None:
        flow = Flow(
            name="ctx_happy",
            version="0.1.0",
            description="Context schema is satisfied by the accumulated context.",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "number"}),
                FlowStep(tool_name="add_ten", input_mapping={"value": "value"}),
                FlowStep(tool_name="format_result", input_mapping={"value": "value"}),
            ],
            context_schema_ref=Flow.schema_ref_from(LinearContextSchema),
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(double_tool)
        ex.register_tool(add_ten_tool)
        ex.register_tool(format_tool)

        result = ex.execute_flow("ctx_happy", {"number": 5})
        assert result.success is True
        assert result.final_output is not None
        assert result.final_output["result"] == "Final value: 20"

    def test_context_schema_failure_aborts_flow_after_steps(self, double_tool: Tool) -> None:
        """An accumulated context missing required fields fails at the gate."""
        flow = Flow(
            name="ctx_bad",
            version="0.1.0",
            description="Context schema demands a field no tool produces.",
            steps=[
                FlowStep(tool_name="double", input_mapping={"number": "number"}),
            ],
            context_schema_ref=Flow.schema_ref_from(_PartialContextSchema),
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(double_tool)

        result = ex.execute_flow("ctx_bad", {"number": 5})
        assert result.success is False
        assert result.final_output is None
        # One success record for the step + one failure record for the
        # context-schema gate.
        assert len(result.execution_log) == 2
        gate = result.execution_log[-1]
        assert gate.step_index == len(flow.steps)
        assert gate.error_type == "SchemaValidationError"
        assert "flow_context" in (gate.error_message or "")

    def test_context_schema_round_trips_via_json(self) -> None:
        flow = Flow(
            name="ctx_rt",
            version="0.1.0",
            description="Context schema round-trip.",
            steps=[],
            context_schema_ref=Flow.schema_ref_from(LinearContextSchema),
        )
        restored = flow_from_json(flow.to_json())
        assert isinstance(restored, Flow)
        assert restored.context_schema_ref == flow.context_schema_ref
        assert restored.context_schema is LinearContextSchema


# ---------------------------------------------------------------------------
# DAGFlow.context_schema_ref + contract fields (issue #152 + #172)
# ---------------------------------------------------------------------------


def _passthrough_fn(inp: BaseModel) -> dict[str, object]:
    return inp.model_dump()


class _PassthroughIn(BaseModel):
    number: int


class _PassthroughOut(BaseModel):
    number: int


class TestDAGContextSchema:
    def test_dag_context_schema_resolves(self) -> None:
        dag = DAGFlow(
            name="dag_ctx",
            version="0.1.0",
            description="DAG with a context schema.",
            steps=[
                DAGFlowStep(tool_name="a", step_id="A", depends_on=[]),
            ],
            context_schema_ref=DAGFlow.schema_ref_from(LinearContextSchema),
        )
        assert dag.context_schema is LinearContextSchema

    def test_dag_step_forwards_contract_to_executor(self) -> None:
        """DAGFlowStep input/output_contract are honoured during execution."""
        tool_a = Tool(
            name="a",
            description="Identity passthrough.",
            input_schema=_PassthroughIn,
            output_schema=_PassthroughOut,
            fn=_passthrough_fn,
        )
        dag = DAGFlow(
            name="dag_contracts",
            version="0.1.0",
            description="Single-step DAG that fails its output contract.",
            steps=[
                DAGFlowStep(
                    tool_name="a",
                    step_id="A",
                    depends_on=[],
                    input_mapping={"number": "number"},
                    output_contract=FlowStep.contract_ref_from(_MismatchedOutput),
                ),
            ],
        )
        registry = FlowRegistry()
        registry.register_flow(dag)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(tool_a)

        result = ex.execute_flow("dag_contracts", {"number": 5})
        assert result.success is False
        assert any(
            r.error_type == "SchemaValidationError"
            and "step_output_contract" in (r.error_message or "")
            for r in result.execution_log
        )


# ---------------------------------------------------------------------------
# DAG step retry / on_error parity (regression guard)
#
# ``DAGFlowStep`` inherits ``retry`` and ``on_error`` from ``FlowStep``.  The
# DAG executor builds a lightweight ``FlowStep`` proxy before delegating to
# ``_execute_step``; if those fields are not forwarded, DAG steps silently
# diverge from linear steps and always run with the defaults (no retries,
# ``on_error="fail"``).  These tests assert end-to-end parity.
# ---------------------------------------------------------------------------


class _FlakyTool:
    """Callable that fails *fail_until_attempt* times before succeeding."""

    def __init__(self, fail_until_attempt: int) -> None:
        self.fail_until_attempt = fail_until_attempt
        self.attempts = 0

    def __call__(self, inp: NumberInput) -> dict[str, object]:
        self.attempts += 1
        if self.attempts <= self.fail_until_attempt:
            raise RuntimeError(f"intermittent failure on attempt {self.attempts}.")
        return {"value": inp.number * 2}


def _flaky_tool(fail_until_attempt: int) -> tuple[Tool, _FlakyTool]:
    counter = _FlakyTool(fail_until_attempt=fail_until_attempt)
    tool = Tool(
        name="flaky_dag",
        description="Fails N times before succeeding.",
        input_schema=NumberInput,
        output_schema=ValueOutput,
        fn=counter,
    )
    return tool, counter


def _build_dag_executor(*tools: Tool, step: DAGFlowStep) -> FlowExecutor:
    dag = DAGFlow(
        name="dag_retry_flow",
        version="0.1.0",
        description="Single-step DAG used to assert retry / on_error parity.",
        steps=[step],
    )
    registry = FlowRegistry()
    registry.register_flow(dag)
    ex = FlowExecutor(registry=registry)
    for tool in tools:
        ex.register_tool(tool)
    return ex


class TestDAGStepRetryParity:
    def test_dag_step_honors_retry_policy(self) -> None:
        """A DAGFlowStep with retry= must retry the same way a linear step does."""
        tool, counter = _flaky_tool(fail_until_attempt=2)
        step = DAGFlowStep(
            tool_name="flaky_dag",
            step_id="F",
            depends_on=[],
            input_mapping={"number": "number"},
            retry=RetryPolicy(max_retries=3, backoff_seconds=0.0, backoff_multiplier=1.0),
        )
        ex = _build_dag_executor(tool, step=step)
        result = ex.execute_flow("dag_retry_flow", {"number": 4})
        assert result.success is True
        assert counter.attempts == 3  # initial + 2 retries
        record = result.execution_log[0]
        assert record.success is True
        assert record.outputs == {"value": 8}
        assert record.retry_count == 2

    def test_dag_step_without_retry_makes_single_attempt(self) -> None:
        """Default behaviour must match linear flows: no retries when policy is absent."""
        tool, counter = _flaky_tool(fail_until_attempt=10)
        step = DAGFlowStep(
            tool_name="flaky_dag",
            step_id="F",
            depends_on=[],
            input_mapping={"number": "number"},
        )
        ex = _build_dag_executor(tool, step=step)
        result = ex.execute_flow("dag_retry_flow", {"number": 1})
        assert result.success is False
        assert counter.attempts == 1


class TestDAGStepOnErrorParity:
    def test_dag_step_on_error_skip_continues(self) -> None:
        """``on_error="skip"`` on a DAG step must succeed the flow and skip outputs."""
        tool, _ = _flaky_tool(fail_until_attempt=10)
        step = DAGFlowStep(
            tool_name="flaky_dag",
            step_id="F",
            depends_on=[],
            input_mapping={"number": "number"},
            on_error="skip",
        )
        ex = _build_dag_executor(tool, step=step)
        result = ex.execute_flow("dag_retry_flow", {"number": 1})
        assert result.success is True
        record = result.execution_log[0]
        assert record.success is True
        assert record.skipped is True
        assert record.outputs == {}

    def test_dag_step_on_error_fallback_invokes_alt(self) -> None:
        """``on_error="fallback:<tool>"`` on a DAG step must invoke the fallback tool."""
        primary, _ = _flaky_tool(fail_until_attempt=10)
        alt_fn = lambda inp: {"value": inp.number + 100}  # noqa: E731
        alt = Tool(
            name="alt_dag",
            description="Fallback tool for the DAG retry parity tests.",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=alt_fn,
        )
        step = DAGFlowStep(
            tool_name="flaky_dag",
            step_id="F",
            depends_on=[],
            input_mapping={"number": "number"},
            on_error="fallback:alt_dag",
        )
        ex = _build_dag_executor(primary, alt, step=step)
        result = ex.execute_flow("dag_retry_flow", {"number": 7})
        assert result.success is True
        record = result.execution_log[0]
        assert record.success is True
        assert record.outputs == {"value": 107}


# ---------------------------------------------------------------------------
# Step cache + output_contract interaction (regression guard for #181)
#
# Two steps that use the same tool with identical resolved inputs share a
# cache entry keyed by ``(tool_name, schema_hash, input_value_hash)``.  If
# the second step declares a stricter ``output_contract`` than the first,
# the cache-hit path must re-validate the cached output against the new
# contract — otherwise the contract-bearing step silently accepts whatever
# was written by the contract-less step.
# ---------------------------------------------------------------------------


class TestStepCacheOutputContractValidation:
    """``output_contract`` must be enforced on cache-hit, not just cache-miss."""

    def test_cache_hit_with_stricter_output_contract_rejects(self, double_tool: Tool) -> None:
        """Cached output that violates a later step's output_contract must fail."""
        flow = Flow(
            name="cache_contract_flow",
            version="0.1.0",
            description=(
                "Two identical doubling steps; the second one carries a strict "
                "output_contract that the cached output would violate."
            ),
            steps=[
                # First step has no output_contract; it warms the cache with
                # the tool's natural output shape (which uses ``value``).
                FlowStep(tool_name="double", input_mapping={"number": "number"}),
                # Second step shares the cache slot — same tool, same inputs —
                # but declares an output_contract whose required key does NOT
                # exist in the cached output, so validation must reject.
                FlowStep(
                    tool_name="double",
                    input_mapping={"number": "number"},
                    output_contract=FlowStep.contract_ref_from(_MismatchedOutput),
                ),
            ],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry, step_cache=InMemoryStepCache())
        ex.register_tool(double_tool)

        result = ex.execute_flow("cache_contract_flow", {"number": 5})
        assert result.success is False
        # The second step's record must surface the contract failure on a
        # cache hit (not on tool re-execution).
        failing = result.execution_log[-1]
        assert failing.success is False
        assert failing.error_type == "SchemaValidationError"
        assert "step_output_contract" in (failing.error_message or "")

    def test_cache_hit_with_matching_output_contract_passes(self, double_tool: Tool) -> None:
        """A cache hit whose payload satisfies the contract must succeed cached."""
        flow = Flow(
            name="cache_contract_pass",
            version="0.1.0",
            description="Cache write + cache hit, both honour an output_contract.",
            steps=[
                FlowStep(
                    tool_name="double",
                    input_mapping={"number": "number"},
                    output_contract=FlowStep.contract_ref_from(_StrictDoubleOutput),
                ),
                FlowStep(
                    tool_name="double",
                    input_mapping={"number": "number"},
                    output_contract=FlowStep.contract_ref_from(_StrictDoubleOutput),
                ),
            ],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry, step_cache=InMemoryStepCache())
        ex.register_tool(double_tool)

        result = ex.execute_flow("cache_contract_pass", {"number": 5})
        assert result.success is True
        assert len(result.execution_log) == 2
        # The second invocation must have come from the cache.
        assert result.execution_log[0].cached is False
        assert result.execution_log[1].cached is True


# ---------------------------------------------------------------------------
# Step contracts vs on_error policy (regression guard for #181)
#
# ``on_error`` (``skip`` / ``fallback:<tool>``) covers tool-execution
# failures.  Contract failures are wiring bugs, not transient errors, so
# they must abort the step regardless of ``on_error``.  These tests pin
# that semantics so future refactors don't accidentally relax it.
# ---------------------------------------------------------------------------


class TestContractsBypassOnErrorPolicy:
    def test_input_contract_failure_ignores_on_error_skip(self, double_tool: Tool) -> None:
        """``on_error="skip"`` must NOT skip an input_contract violation."""
        flow = Flow(
            name="contract_vs_skip",
            version="0.1.0",
            description="Step with on_error=skip and an input_contract mismatch.",
            steps=[
                FlowStep(
                    tool_name="double",
                    input_mapping={"number": "number"},
                    input_contract=FlowStep.contract_ref_from(_MismatchedInput),
                    on_error="skip",
                ),
            ],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(double_tool)

        result = ex.execute_flow("contract_vs_skip", {"number": 5})
        assert result.success is False
        record = result.execution_log[-1]
        assert record.success is False
        assert record.skipped is False
        assert record.error_type == "SchemaValidationError"
        assert "step_input_contract" in (record.error_message or "")

    def test_output_contract_failure_ignores_on_error_skip(self, double_tool: Tool) -> None:
        """``on_error="skip"`` must NOT skip an output_contract violation."""
        flow = Flow(
            name="output_contract_vs_skip",
            version="0.1.0",
            description="Step with on_error=skip and an output_contract mismatch.",
            steps=[
                FlowStep(
                    tool_name="double",
                    input_mapping={"number": "number"},
                    output_contract=FlowStep.contract_ref_from(_MismatchedOutput),
                    on_error="skip",
                ),
            ],
        )
        registry = FlowRegistry()
        registry.register_flow(flow)
        ex = FlowExecutor(registry=registry)
        ex.register_tool(double_tool)

        result = ex.execute_flow("output_contract_vs_skip", {"number": 5})
        assert result.success is False
        record = result.execution_log[-1]
        assert record.success is False
        assert record.skipped is False
        assert record.error_type == "SchemaValidationError"
        assert "step_output_contract" in (record.error_message or "")
