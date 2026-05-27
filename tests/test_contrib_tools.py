"""Tests for the contrib stdlib tools (issue #145)."""

from __future__ import annotations

from typing import Any

import pytest
from helpers import NumberInput, ValueOutput, _double_fn
from pydantic import BaseModel

from chainweaver.contrib.tools import (
    assert_equal,
    filter_list,
    json_pluck,
    json_set,
    map_list,
    passthrough,
)
from chainweaver.exceptions import ContribError
from chainweaver.executor import FlowExecutor
from chainweaver.flow import Flow, FlowStep
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool

# ---------------------------------------------------------------------------
# passthrough
# ---------------------------------------------------------------------------


class TestPassthrough:
    def test_returns_input_unchanged(self) -> None:
        payload = {"a": 1, "b": [2, 3], "c": {"d": 4}}
        assert passthrough.run({"data": payload}) == {"data": payload}

    def test_empty_dict(self) -> None:
        assert passthrough.run({"data": {}}) == {"data": {}}


# ---------------------------------------------------------------------------
# json_pluck
# ---------------------------------------------------------------------------


class TestJsonPluck:
    def test_extracts_top_level_key(self) -> None:
        out = json_pluck.run({"data": {"name": "alice", "age": 30}, "pointer": "/name"})
        assert out == {"value": "alice"}

    def test_extracts_nested_key(self) -> None:
        data = {"user": {"address": {"city": "Lisbon"}}}
        out = json_pluck.run({"data": data, "pointer": "/user/address/city"})
        assert out == {"value": "Lisbon"}

    def test_extracts_list_index(self) -> None:
        out = json_pluck.run({"data": {"items": [10, 20, 30]}, "pointer": "/items/1"})
        assert out == {"value": 20}

    def test_empty_pointer_returns_whole_document(self) -> None:
        data = {"a": 1}
        assert json_pluck.run({"data": data, "pointer": ""}) == {"value": data}

    def test_escape_sequence_tilde_one(self) -> None:
        out = json_pluck.run({"data": {"a/b": 42}, "pointer": "/a~1b"})
        assert out == {"value": 42}

    def test_escape_sequence_tilde_zero(self) -> None:
        out = json_pluck.run({"data": {"a~b": 42}, "pointer": "/a~0b"})
        assert out == {"value": 42}

    def test_missing_key_raises(self) -> None:
        with pytest.raises(ContribError) as exc:
            json_pluck.run({"data": {"a": 1}, "pointer": "/b"})
        assert "not found" in str(exc.value)

    def test_invalid_pointer_raises(self) -> None:
        with pytest.raises(ContribError) as exc:
            json_pluck.run({"data": {"a": 1}, "pointer": "no-leading-slash"})
        assert "must start with '/'" in str(exc.value)

    def test_list_with_non_integer_token_raises(self) -> None:
        with pytest.raises(ContribError) as exc:
            json_pluck.run({"data": {"items": [1, 2]}, "pointer": "/items/foo"})
        assert "not an integer" in str(exc.value)

    def test_list_out_of_range_raises(self) -> None:
        with pytest.raises(ContribError) as exc:
            json_pluck.run({"data": {"items": [1, 2]}, "pointer": "/items/5"})
        assert "out of range" in str(exc.value)


# ---------------------------------------------------------------------------
# json_set
# ---------------------------------------------------------------------------


class TestJsonSet:
    def test_sets_top_level_key(self) -> None:
        out = json_set.run({"data": {}, "pointer": "/name", "value": "alice"})
        assert out == {"data": {"name": "alice"}}

    def test_creates_intermediate_dicts(self) -> None:
        out = json_set.run({"data": {}, "pointer": "/a/b/c", "value": 1})
        assert out == {"data": {"a": {"b": {"c": 1}}}}

    def test_does_not_mutate_input(self) -> None:
        original = {"a": {"b": 1}}
        json_set.run({"data": original, "pointer": "/a/b", "value": 2})
        assert original == {"a": {"b": 1}}

    def test_overwrites_existing_value(self) -> None:
        out = json_set.run({"data": {"a": 1}, "pointer": "/a", "value": 99})
        assert out == {"data": {"a": 99}}

    def test_setting_root_raises(self) -> None:
        with pytest.raises(ContribError) as exc:
            json_set.run({"data": {}, "pointer": "", "value": 1})
        assert "root" in str(exc.value)

    def test_set_list_index_in_range(self) -> None:
        out = json_set.run({"data": {"items": [1, 2, 3]}, "pointer": "/items/1", "value": 99})
        assert out == {"data": {"items": [1, 99, 3]}}

    def test_set_list_index_out_of_range_raises(self) -> None:
        with pytest.raises(ContribError):
            json_set.run({"data": {"items": [1]}, "pointer": "/items/5", "value": 9})


# ---------------------------------------------------------------------------
# assert_equal
# ---------------------------------------------------------------------------


class TestAssertEqual:
    def test_equal_values_pass(self) -> None:
        assert assert_equal.run({"left": 42, "right": 42}) == {"equal": True}

    def test_equal_nested_dicts_pass(self) -> None:
        assert assert_equal.run({"left": {"a": [1, 2]}, "right": {"a": [1, 2]}}) == {"equal": True}

    def test_unequal_raises(self) -> None:
        with pytest.raises(ContribError) as exc:
            assert_equal.run({"left": 1, "right": 2})
        assert "values differ" in str(exc.value)

    def test_long_values_truncated_in_error(self) -> None:
        long_str = "x" * 200
        with pytest.raises(ContribError) as exc:
            assert_equal.run({"left": long_str, "right": "different"})
        # Truncated form ends with ``...``
        assert "..." in str(exc.value)


# ---------------------------------------------------------------------------
# map_list — needs a sub-flow + executor
# ---------------------------------------------------------------------------


class _NumberInputMap(BaseModel):
    """Input schema for a one-step sub-flow that doubles ``item``."""

    item: int


class _DoubleSubInput(BaseModel):
    item: int


class _DoubleSubOutput(BaseModel):
    value: int


def _double_sub_fn(inp: _DoubleSubInput) -> dict[str, Any]:
    return {"value": inp.item * 2}


@pytest.fixture()
def map_list_setup() -> tuple[FlowExecutor, Tool]:
    """Register a sub-flow that doubles each item, return the executor + map_list tool."""
    sub_flow = Flow(
        name="double_item",
        version="0.1.0",
        description="Double the input item.",
        steps=[FlowStep(tool_name="double_sub", input_mapping={"item": "item"})],
    )
    registry = FlowRegistry()
    registry.register_flow(sub_flow)
    executor = FlowExecutor(registry=registry)
    executor.register_tool(
        Tool(
            name="double_sub",
            description="Doubles a number.",
            input_schema=_DoubleSubInput,
            output_schema=_DoubleSubOutput,
            fn=_double_sub_fn,
        )
    )
    return executor, map_list(subflow_name="double_item", executor=executor)


class TestMapList:
    def test_applies_subflow_to_each_element(
        self, map_list_setup: tuple[FlowExecutor, Tool]
    ) -> None:
        _, tool = map_list_setup
        out = tool.run({"items": [1, 2, 3]})
        # ``ExecutionResult.final_output`` is the merged context (input +
        # step outputs).  The sub-flow's input was ``{"item": N}`` and
        # the doubling step produced ``{"value": 2N}``; both keys appear
        # in each per-item dict.
        assert out == {
            "items": [
                {"item": 1, "value": 2},
                {"item": 2, "value": 4},
                {"item": 3, "value": 6},
            ]
        }

    def test_empty_list(self, map_list_setup: tuple[FlowExecutor, Tool]) -> None:
        _, tool = map_list_setup
        assert tool.run({"items": []}) == {"items": []}

    def test_subflow_failure_raises_contrib_error(self) -> None:
        # Sub-flow that always fails (its single tool raises).
        class _Inp(BaseModel):
            item: int

        class _Out(BaseModel):
            value: int

        def _fail(inp: _Inp) -> dict[str, Any]:
            raise RuntimeError("boom")

        sub_flow = Flow(
            name="failing_sub",
            version="0.1.0",
            description="Always fails.",
            steps=[FlowStep(tool_name="boom", input_mapping={"item": "item"})],
        )
        registry = FlowRegistry()
        registry.register_flow(sub_flow)
        executor = FlowExecutor(registry=registry)
        executor.register_tool(
            Tool(
                name="boom",
                description="Always raises.",
                input_schema=_Inp,
                output_schema=_Out,
                fn=_fail,
            )
        )
        tool = map_list(subflow_name="failing_sub", executor=executor)
        with pytest.raises(ContribError) as exc:
            tool.run({"items": [1]})
        assert "failed on item index 0" in str(exc.value)


# ---------------------------------------------------------------------------
# filter_list — sub-flow returns a predicate boolean
# ---------------------------------------------------------------------------


class _EvenSubInput(BaseModel):
    item: int


class _EvenSubOutput(BaseModel):
    keep: bool


def _even_sub_fn(inp: _EvenSubInput) -> dict[str, Any]:
    return {"keep": inp.item % 2 == 0}


@pytest.fixture()
def filter_list_setup() -> Tool:
    sub_flow = Flow(
        name="is_even",
        version="0.1.0",
        description="True if the input item is even.",
        steps=[FlowStep(tool_name="even_sub", input_mapping={"item": "item"})],
    )
    registry = FlowRegistry()
    registry.register_flow(sub_flow)
    executor = FlowExecutor(registry=registry)
    executor.register_tool(
        Tool(
            name="even_sub",
            description="Even predicate.",
            input_schema=_EvenSubInput,
            output_schema=_EvenSubOutput,
            fn=_even_sub_fn,
        )
    )
    return filter_list(subflow_name="is_even", executor=executor)


class TestFilterList:
    def test_keeps_truthy_items(self, filter_list_setup: Tool) -> None:
        out = filter_list_setup.run({"items": [1, 2, 3, 4]})
        assert out == {"items": [2, 4]}

    def test_empty_list(self, filter_list_setup: Tool) -> None:
        assert filter_list_setup.run({"items": []}) == {"items": []}

    def test_missing_predicate_key_raises(self) -> None:
        # Sub-flow returns the wrong shape — no ``keep`` key.
        class _Inp(BaseModel):
            item: int

        class _Out(BaseModel):
            wrong: bool

        sub_flow = Flow(
            name="bad_pred",
            version="0.1.0",
            description="Wrong shape.",
            steps=[FlowStep(tool_name="bad_pred_sub", input_mapping={"item": "item"})],
        )
        registry = FlowRegistry()
        registry.register_flow(sub_flow)
        executor = FlowExecutor(registry=registry)
        executor.register_tool(
            Tool(
                name="bad_pred_sub",
                description="",
                input_schema=_Inp,
                output_schema=_Out,
                fn=lambda inp: {"wrong": True},
            )
        )
        tool = filter_list(subflow_name="bad_pred", executor=executor)
        with pytest.raises(ContribError) as exc:
            tool.run({"items": [1]})
        assert "did not produce key 'keep'" in str(exc.value)


# ---------------------------------------------------------------------------
# End-to-end: contrib tool inside a registered flow
# ---------------------------------------------------------------------------


def test_passthrough_in_a_flow() -> None:
    """Passthrough should be usable as a normal step in a registered flow."""
    flow = Flow(
        name="echo",
        version="0.1.0",
        description="Echo input through passthrough.",
        steps=[FlowStep(tool_name="passthrough", input_mapping={"data": "payload"})],
    )
    registry = FlowRegistry()
    registry.register_flow(flow)
    executor = FlowExecutor(registry=registry)
    executor.register_tool(passthrough)
    # Sanity import: the helpers fixture exists in the conftest scope.
    _ = (NumberInput, ValueOutput, _double_fn)
    result = executor.execute_flow("echo", {"payload": {"a": 1}})
    assert result.success
    # final_output is the merged context: original input + the
    # passthrough step's ``data`` output.
    assert result.final_output == {"payload": {"a": 1}, "data": {"a": 1}}
