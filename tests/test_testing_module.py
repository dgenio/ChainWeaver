"""Tests for ``chainweaver.testing`` (issue #132).

Covers :class:`FlowTestRunner`, :func:`fake_tool`, :func:`capture_steps`,
and :func:`assert_result_matches`.  Each test isolates one
acceptance-criterion bullet from the issue body.
"""

from __future__ import annotations

import pytest
from helpers import (
    NumberInput,
    ValueInput,
    ValueOutput,
    _add_ten_fn,
    _double_fn,
)

from chainweaver.executor import FlowExecutor
from chainweaver.flow import Flow, FlowStep
from chainweaver.registry import FlowRegistry
from chainweaver.testing import (
    DEFAULT_IGNORE_FIELDS,
    FlowTestRunner,
    assert_result_matches,
    capture_steps,
    fake_tool,
)
from chainweaver.tools import Tool


def _two_step_flow() -> Flow:
    return Flow(
        name="testing_two_step",
        version="0.1.0",
        description="Two-step flow used for testing-module tests.",
        steps=[
            FlowStep(tool_name="double", input_mapping={"number": "number"}),
            FlowStep(tool_name="add_ten", input_mapping={"value": "value"}),
        ],
    )


# ---------------------------------------------------------------------------
# fake_tool
# ---------------------------------------------------------------------------


def test_fake_tool_static_output_returns_snapshot_unchanged() -> None:
    snapshot = {"value": 99, "label": "static"}
    tool = fake_tool("static", snapshot)

    result = tool.run({"anything": "goes"})

    assert result == snapshot


def test_fake_tool_static_output_is_isolated_from_caller_mutation() -> None:
    snapshot = {"value": 1}
    tool = fake_tool("static", snapshot)
    snapshot["value"] = 999  # caller mutates after construction

    assert tool.run({}) == {"value": 1}


def test_fake_tool_dynamic_callable_receives_input_as_dict() -> None:
    seen_inputs: list[dict[str, object]] = []

    def _double(inp: dict[str, object]) -> dict[str, object]:
        seen_inputs.append(inp)
        number = inp["number"]
        assert isinstance(number, int)
        return {"value": number * 2}

    tool = fake_tool("double", _double)

    assert tool.run({"number": 7}) == {"value": 14}
    assert seen_inputs == [{"number": 7}]


def test_fake_tool_default_cacheable_is_false() -> None:
    assert fake_tool("x", {"a": 1}).cacheable is False


def test_fake_tool_cacheable_override_is_respected() -> None:
    assert fake_tool("x", {"a": 1}, cacheable=True).cacheable is True


def test_fake_tool_accepts_arbitrary_input_dicts() -> None:
    tool = fake_tool("anything", lambda inp: {"echo": inp})
    # Schema is permissive: any dict structure round-trips through validation.
    result = tool.run({"nested": {"deep": [1, 2, 3]}, "scalar": True})

    assert result == {"echo": {"nested": {"deep": [1, 2, 3]}, "scalar": True}}


# ---------------------------------------------------------------------------
# FlowTestRunner — basic execution
# ---------------------------------------------------------------------------


def test_runner_pre_registered_flow_runs_with_fake_tools() -> None:
    runner = FlowTestRunner(_two_step_flow())
    runner.fake_tool("double", lambda inp: {"value": int(inp["number"]) * 2})
    runner.fake_tool("add_ten", lambda inp: {"value": int(inp["value"]) + 10})

    result = runner.execute("testing_two_step", {"number": 3})

    assert result.success is True
    assert result.final_output is not None
    assert result.final_output["value"] == 16


def test_runner_register_overwrites_existing_flow() -> None:
    runner = FlowTestRunner()
    runner.register(_two_step_flow())
    runner.register(_two_step_flow())  # second call must not raise

    runner.fake_tool("double", lambda inp: {"value": 0})
    runner.fake_tool("add_ten", lambda inp: {"value": 0})
    result = runner.execute("testing_two_step", {"number": 1})

    assert result.success is True


def test_runner_passthrough_tool_preserves_real_schemas() -> None:
    real_tool = Tool(
        name="double",
        description="real double",
        input_schema=NumberInput,
        output_schema=ValueOutput,
        fn=_double_fn,
    )
    runner = FlowTestRunner(_two_step_flow())
    runner.passthrough_tool(real_tool)
    runner.fake_tool("add_ten", lambda inp: {"value": int(inp["value"]) + 10})

    result = runner.execute("testing_two_step", {"number": 4})

    assert result.success is True
    assert result.final_output is not None
    assert result.final_output["value"] == 18  # (4*2) + 10


# ---------------------------------------------------------------------------
# FlowTestRunner — call tracking
# ---------------------------------------------------------------------------


def test_runner_calls_to_counts_invocations() -> None:
    runner = FlowTestRunner(_two_step_flow())
    runner.fake_tool("double", lambda inp: {"value": int(inp["number"]) * 2})
    runner.fake_tool("add_ten", lambda inp: {"value": int(inp["value"]) + 10})

    runner.execute("testing_two_step", {"number": 1})
    runner.execute("testing_two_step", {"number": 2})

    assert runner.calls_to("double") == 2
    assert runner.calls_to("add_ten") == 2


def test_runner_calls_to_unknown_tool_is_zero() -> None:
    runner = FlowTestRunner()
    assert runner.calls_to("never_called") == 0


def test_runner_inputs_to_returns_ordered_inputs() -> None:
    runner = FlowTestRunner(_two_step_flow())
    runner.fake_tool("double", lambda inp: {"value": int(inp["number"]) * 2})
    runner.fake_tool("add_ten", lambda inp: {"value": int(inp["value"]) + 10})

    runner.execute("testing_two_step", {"number": 5})
    runner.execute("testing_two_step", {"number": 7})

    assert runner.inputs_to("double") == [{"number": 5}, {"number": 7}]


def test_runner_inputs_to_returns_defensive_copies() -> None:
    runner = FlowTestRunner(_two_step_flow())
    runner.fake_tool("double", lambda inp: {"value": 0})
    runner.fake_tool("add_ten", lambda inp: {"value": 0})

    runner.execute("testing_two_step", {"number": 9})
    seen = runner.inputs_to("double")
    seen[0]["number"] = 999  # mutate

    assert runner.inputs_to("double") == [{"number": 9}]


# ---------------------------------------------------------------------------
# FlowTestRunner — accessor properties and middleware
# ---------------------------------------------------------------------------


def test_runner_exposes_executor_and_registry() -> None:
    runner = FlowTestRunner()
    # Properties surface the underlying objects so advanced tests can
    # reach features the runner does not wrap directly.
    assert runner.executor is runner.executor
    assert runner.registry is runner.registry


def test_runner_add_middleware_chains_into_executor() -> None:
    from chainweaver.middleware import BaseMiddleware, StepEndContext

    class _Counter(BaseMiddleware):
        def __init__(self) -> None:
            self.steps = 0

        def on_step_end(self, ctx: StepEndContext) -> None:
            del ctx  # unused — middleware only counts hook invocations
            self.steps += 1

    mw = _Counter()
    runner = FlowTestRunner(_two_step_flow())
    runner.add_middleware(mw)
    runner.fake_tool("double", lambda inp: {"value": 0})
    runner.fake_tool("add_ten", lambda inp: {"value": 0})

    runner.execute("testing_two_step", {"number": 1})

    assert mw.steps == 2


# ---------------------------------------------------------------------------
# FlowTestRunner — error path
# ---------------------------------------------------------------------------


def test_runner_surface_step_failure_in_result() -> None:
    def _failing(_inp: dict[str, object]) -> dict[str, object]:
        raise RuntimeError("boom")

    runner = FlowTestRunner(_two_step_flow())
    runner.fake_tool("double", _failing)
    runner.fake_tool("add_ten", {"value": 0})

    result = runner.execute("testing_two_step", {"number": 1})

    assert result.success is False
    failed_records = [r for r in result.execution_log if not r.success]
    assert len(failed_records) == 1
    assert failed_records[0].tool_name == "double"


# ---------------------------------------------------------------------------
# capture_steps
# ---------------------------------------------------------------------------


def test_capture_steps_records_one_entry_per_step() -> None:
    runner = FlowTestRunner(_two_step_flow())
    runner.fake_tool("double", lambda inp: {"value": int(inp["number"]) * 2})
    runner.fake_tool("add_ten", lambda inp: {"value": int(inp["value"]) + 10})

    with capture_steps(runner.executor) as steps:
        runner.execute("testing_two_step", {"number": 4})

    assert [s.tool_name for s in steps] == ["double", "add_ten"]
    assert all(s.success for s in steps)


def test_capture_steps_removes_middleware_on_exit() -> None:
    registry = FlowRegistry()
    registry.register_flow(_two_step_flow())
    ex = FlowExecutor(registry=registry)
    ex.register_tool(
        Tool(
            name="double",
            description="",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=_double_fn,
        )
    )
    ex.register_tool(
        Tool(
            name="add_ten",
            description="",
            input_schema=ValueInput,
            output_schema=ValueOutput,
            fn=_add_ten_fn,
        )
    )
    before = len(ex._middleware)

    with capture_steps(ex):
        ex.execute_flow("testing_two_step", {"number": 1})

    assert len(ex._middleware) == before


def test_capture_steps_list_is_empty_before_first_step() -> None:
    runner = FlowTestRunner(_two_step_flow())
    runner.fake_tool("double", lambda inp: {"value": 0})
    runner.fake_tool("add_ten", lambda inp: {"value": 0})

    with capture_steps(runner.executor) as steps:
        # No execute call yet — list must be empty.
        assert steps == []
        runner.execute("testing_two_step", {"number": 1})
        assert len(steps) == 2


# ---------------------------------------------------------------------------
# assert_result_matches
# ---------------------------------------------------------------------------


def test_assert_result_matches_ignores_volatile_fields_by_default() -> None:
    actual = {
        "flow_name": "f",
        "success": True,
        "trace_id": "abc-123",
        "started_at": "2026-05-21T00:00:00Z",
        "ended_at": "2026-05-21T00:00:01Z",
        "total_duration_ms": 42.0,
        "final_output": {"value": 16},
    }
    expected = {
        "flow_name": "f",
        "success": True,
        "trace_id": "ignored",
        "started_at": "different",
        "ended_at": "also-different",
        "total_duration_ms": 9999.9,
        "final_output": {"value": 16},
    }
    # Must not raise.
    assert_result_matches(actual, expected)


def test_assert_result_matches_raises_on_meaningful_diff() -> None:
    actual = {"final_output": {"value": 16}}
    expected = {"final_output": {"value": 17}}

    with pytest.raises(AssertionError) as exc:
        assert_result_matches(actual, expected)

    message = str(exc.value)
    assert "final_output" in message
    assert "16" in message
    assert "17" in message


def test_assert_result_matches_compares_step_records_through_pydantic_model() -> None:
    runner = FlowTestRunner(_two_step_flow())
    runner.fake_tool("double", lambda inp: {"value": 6})
    runner.fake_tool("add_ten", lambda inp: {"value": 16})
    result = runner.execute("testing_two_step", {"number": 3})

    # Comparing the model against the model itself must always pass
    # — volatile fields cancel out symmetrically.
    assert_result_matches(result, result.model_dump())


def test_assert_result_matches_custom_ignore_list_replaces_default() -> None:
    actual = {"trace_id": "a", "x": 1}
    expected = {"trace_id": "b", "x": 1}

    with pytest.raises(AssertionError):
        # Custom ignore list does NOT include trace_id — so this diff surfaces.
        assert_result_matches(actual, expected, ignore=("only_this",))


def test_default_ignore_fields_includes_known_volatile_fields() -> None:
    # Documented invariant: DEFAULT_IGNORE_FIELDS covers every field
    # ``ExecutionResult`` adds at runtime that varies between runs.
    assert "trace_id" in DEFAULT_IGNORE_FIELDS
    assert "started_at" in DEFAULT_IGNORE_FIELDS
    assert "ended_at" in DEFAULT_IGNORE_FIELDS
    assert "duration_ms" in DEFAULT_IGNORE_FIELDS
    assert "total_duration_ms" in DEFAULT_IGNORE_FIELDS


def test_assert_result_matches_handles_nested_lists() -> None:
    actual = {"items": [{"trace_id": "a", "n": 1}, {"trace_id": "b", "n": 2}]}
    expected = {"items": [{"trace_id": "x", "n": 1}, {"trace_id": "y", "n": 2}]}

    assert_result_matches(actual, expected)


def test_assert_result_matches_detects_missing_key() -> None:
    actual = {"a": 1}
    expected = {"a": 1, "b": 2}

    with pytest.raises(AssertionError, match=r"\$\.b"):
        assert_result_matches(actual, expected)


def test_assert_result_matches_detects_extra_key() -> None:
    actual = {"a": 1, "extra": 99}
    expected = {"a": 1}

    with pytest.raises(AssertionError, match=r"\$\.extra"):
        assert_result_matches(actual, expected)
