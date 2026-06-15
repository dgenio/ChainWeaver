"""Tests for FlowStep input/output wiring (issues #386, #387, #316).

Covers three related step-I/O features that share the executor's input-binding
and output-merge machinery:

* ``output_mapping`` — rename/prune a tool's outputs before the context merge.
* dotted-path / RFC-6901 ``input_mapping`` — pull nested values from context.
* ``dynamic_params`` — inject runtime params hidden from ``input_schema``.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pydantic import BaseModel

from chainweaver.builder import FlowBuilder
from chainweaver.compiler import compile_flow
from chainweaver.exceptions import OutputMappingError
from chainweaver.executor import FlowExecutor
from chainweaver.flow import DAGFlow, DAGFlowStep, Flow, FlowStep
from chainweaver.registry import FlowRegistry
from chainweaver.serialization import flow_from_json, flow_to_json
from chainweaver.tools import Tool

# ---------------------------------------------------------------------------
# Module-level schemas and tool functions (importable for ref resolution).
# ---------------------------------------------------------------------------


class _Seed(BaseModel):
    seed: int = 0


class _Profile(BaseModel):
    user: dict[str, Any]
    items: list[dict[str, Any]]
    status: str


class _CityIn(BaseModel):
    city: str


class _CityOut(BaseModel):
    city_out: str


class _QueryIn(BaseModel):
    query: str
    account: str


class _AccountOut(BaseModel):
    answer: str


class _VisibleInput(BaseModel):
    """LLM-visible flow input — deliberately omits the injected ``account``."""

    query: str


def _profile_fn(_: _Seed) -> dict[str, Any]:
    return {
        "user": {"address": {"city": "Lisbon"}},
        "items": [{"id": 10}, {"id": 20}],
        "status": "ok",
    }


def _city_fn(inp: _CityIn) -> dict[str, Any]:
    return {"city_out": inp.city.upper()}


def _account_fn(inp: _QueryIn) -> dict[str, Any]:
    return {"answer": f"{inp.query} for account {inp.account}"}


def _profile_tool() -> Tool:
    return Tool(
        name="make_profile",
        description="Produces a nested, multi-key profile payload.",
        input_schema=_Seed,
        output_schema=_Profile,
        fn=_profile_fn,
    )


def _city_tool() -> Tool:
    return Tool(
        name="echo_city",
        description="Upper-cases a city name.",
        input_schema=_CityIn,
        output_schema=_CityOut,
        fn=_city_fn,
    )


def _account_tool() -> Tool:
    return Tool(
        name="account_overview",
        description="Answers a query against an account.",
        input_schema=_QueryIn,
        output_schema=_AccountOut,
        fn=_account_fn,
    )


def _make_executor(flow: Flow | DAGFlow, *tools: Tool) -> FlowExecutor:
    registry = FlowRegistry()
    registry.register_flow(flow)
    ex = FlowExecutor(registry=registry)
    for tool in tools:
        ex.register_tool(tool)
    return ex


# ---------------------------------------------------------------------------
# #387 — dotted-path / RFC-6901 input_mapping
# ---------------------------------------------------------------------------


class TestPointerInputMapping:
    def _flow(self, pointer: str) -> Flow:
        return Flow(
            name="nested",
            description="Resolve a nested value by pointer.",
            steps=[
                FlowStep(tool_name="make_profile", input_mapping={"seed": 0}),
                FlowStep(tool_name="echo_city", input_mapping={"city": pointer}),
            ],
        )

    def test_nested_dict_pointer(self) -> None:
        ex = _make_executor(self._flow("/user/address/city"), _profile_tool(), _city_tool())
        result = ex.execute_flow("nested", {})
        assert result.success is True
        assert result.final_output is not None
        assert result.final_output["city_out"] == "LISBON"

    def test_list_index_pointer(self) -> None:
        flow = Flow(
            name="nested",
            description="Resolve a list element by pointer.",
            steps=[
                FlowStep(tool_name="make_profile", input_mapping={"seed": 0}),
                FlowStep(tool_name="echo_city", input_mapping={"city": "/items/1/id"}),
            ],
        )
        ex = _make_executor(flow, _profile_tool(), _city_tool())
        # The id is an int; _city_fn upper-cases its str() — exercises resolution
        # not type coercion, so assert on the resolved value reaching the tool.
        result = ex.execute_flow("nested", {})
        assert result.execution_log[1].inputs == {"city": 20}

    def test_escaped_tilde_and_slash_tokens(self) -> None:
        # Context holds a key literally containing "~" and "/": "a/b~c".
        passthrough = Tool(
            name="passthrough",
            description="Returns a context-shaped payload verbatim.",
            input_schema=_Seed,
            output_schema=_WeirdKeys,
            fn=lambda _: {"weird": {"a/b~c": "hit"}},
        )
        flow = Flow(
            name="escapes",
            description="Resolve an escaped pointer token.",
            steps=[
                FlowStep(tool_name="passthrough", input_mapping={"seed": 0}),
                FlowStep(tool_name="echo_city", input_mapping={"city": "/weird/a~1b~0c"}),
            ],
        )
        ex = _make_executor(flow, passthrough, _city_tool())
        result = ex.execute_flow("escapes", {})
        assert result.final_output is not None
        assert result.final_output["city_out"] == "HIT"

    def test_missing_pointer_raises_input_mapping_error(self) -> None:
        ex = _make_executor(self._flow("/user/address/zipcode"), _profile_tool(), _city_tool())
        result = ex.execute_flow("nested", {})
        assert result.success is False
        failed = result.execution_log[-1]
        assert failed.error_type == "InputMappingError"
        assert "/user/address/zipcode" in (failed.error_message or "")

    def test_pointer_into_scalar_raises(self) -> None:
        # "status" is a scalar string; descending into it is a resolution error.
        ex = _make_executor(self._flow("/status/deeper"), _profile_tool(), _city_tool())
        result = ex.execute_flow("nested", {})
        assert result.success is False
        assert result.execution_log[-1].error_type == "InputMappingError"

    def test_plain_keys_unchanged(self) -> None:
        # A plain (non-pointer) key resolves as a flat top-level lookup, as before.
        flow = Flow(
            name="flat",
            description="Flat lookup regression.",
            steps=[FlowStep(tool_name="echo_city", input_mapping={"city": "city"})],
        )
        ex = _make_executor(flow, _city_tool())
        result = ex.execute_flow("flat", {"city": "porto"})
        assert result.final_output is not None
        assert result.final_output["city_out"] == "PORTO"

    def test_async_pointer_parity(self) -> None:
        ex = _make_executor(self._flow("/user/address/city"), _profile_tool(), _city_tool())
        result = asyncio.run(ex.execute_flow_async("nested", {}))
        assert result.final_output is not None
        assert result.final_output["city_out"] == "LISBON"

    def test_compiler_accepts_valid_pointer_root(self) -> None:
        flow = self._flow("/user/address/city")
        ex = _make_executor(flow, _profile_tool(), _city_tool())
        compiled = compile_flow(flow, ex.registered_tools)
        assert compiled.success, compiled.errors

    def test_compiler_flags_unknown_pointer_root(self) -> None:
        flow = self._flow("/missing/address/city")
        ex = _make_executor(flow, _profile_tool(), _city_tool())
        compiled = compile_flow(flow, ex.registered_tools)
        assert not compiled.success
        assert any(e.issue_type == "missing_mapping_key" for e in compiled.errors)


class _WeirdKeys(BaseModel):
    weird: dict[str, Any]


# ---------------------------------------------------------------------------
# #386 — output_mapping
# ---------------------------------------------------------------------------


class TestOutputMapping:
    def test_rename_merges_renamed_key(self) -> None:
        flow = Flow(
            name="rename",
            description="Rename status -> state.",
            steps=[
                FlowStep(
                    tool_name="make_profile",
                    input_mapping={"seed": 0},
                    output_mapping={"state": "status"},
                ),
            ],
        )
        ex = _make_executor(flow, _profile_tool())
        result = ex.execute_flow("rename", {})
        assert result.final_output is not None
        # Only the renamed key merges; the original output keys are pruned.
        assert result.final_output["state"] == "ok"
        assert "status" not in result.final_output
        assert "user" not in result.final_output

    def test_raw_outputs_preserved_on_record(self) -> None:
        flow = Flow(
            name="rename",
            description="Raw outputs unchanged on the StepRecord.",
            steps=[
                FlowStep(
                    tool_name="make_profile",
                    input_mapping={"seed": 0},
                    output_mapping={"state": "status"},
                ),
            ],
        )
        ex = _make_executor(flow, _profile_tool())
        result = ex.execute_flow("rename", {})
        # The mapping affects only the context merge — the record keeps raw outputs.
        assert result.execution_log[0].outputs == {
            "user": {"address": {"city": "Lisbon"}},
            "items": [{"id": 10}, {"id": 20}],
            "status": "ok",
        }

    def test_missing_output_key_raises(self) -> None:
        flow = Flow(
            name="bad",
            description="Maps an output key the tool never produced.",
            steps=[
                FlowStep(
                    tool_name="make_profile",
                    input_mapping={"seed": 0},
                    output_mapping={"x": "nonexistent"},
                ),
            ],
        )
        ex = _make_executor(flow, _profile_tool())
        with pytest.raises(OutputMappingError) as exc_info:
            ex.execute_flow("bad", {})
        assert exc_info.value.output_key == "nonexistent"

    def test_no_mapping_is_byte_for_byte_unchanged(self) -> None:
        step = FlowStep(tool_name="make_profile", input_mapping={"seed": 0})
        assert step.output_mapping is None
        assert "output_mapping" in step.model_dump()
        assert step.model_dump()["output_mapping"] is None

    def test_async_output_mapping_parity(self) -> None:
        flow = Flow(
            name="rename",
            description="Rename in the async lane.",
            steps=[
                FlowStep(
                    tool_name="make_profile",
                    input_mapping={"seed": 0},
                    output_mapping={"state": "status"},
                ),
            ],
        )
        ex = _make_executor(flow, _profile_tool())
        result = asyncio.run(ex.execute_flow_async("rename", {}))
        assert result.final_output is not None
        assert result.final_output["state"] == "ok"

    def test_dag_fan_in_with_remapped_keys(self) -> None:
        # Two siblings both emit "status"; remapping each to a distinct context
        # key lets the level merge succeed where it would otherwise collide.
        dag = DAGFlow(
            name="diamond",
            version="0.1.0",
            description="Two profile siblings remapped to distinct keys.",
            steps=[
                DAGFlowStep(
                    tool_name="make_profile",
                    step_id="a",
                    input_mapping={"seed": 0},
                    output_mapping={"status_a": "status"},
                ),
                DAGFlowStep(
                    tool_name="make_profile",
                    step_id="b",
                    input_mapping={"seed": 0},
                    output_mapping={"status_b": "status"},
                ),
            ],
        )
        ex = _make_executor(dag, _profile_tool())
        result = ex.execute_flow("diamond", {})
        assert result.success is True, [r.error_message for r in result.execution_log]
        assert result.final_output is not None
        assert result.final_output["status_a"] == "ok"
        assert result.final_output["status_b"] == "ok"

    def test_serialization_round_trip(self) -> None:
        flow = Flow(
            name="rename",
            description="Round-trip output_mapping.",
            steps=[
                FlowStep(
                    tool_name="make_profile",
                    input_mapping={"seed": 0},
                    output_mapping={"state": "status"},
                ),
            ],
        )
        restored = flow_from_json(flow_to_json(flow))
        assert isinstance(restored, Flow)
        assert restored.steps[0].output_mapping == {"state": "status"}

    def test_builder_supports_output_mapping(self) -> None:
        flow = (
            FlowBuilder("b", "builder output_mapping")
            .step("make_profile", seed=0, output_mapping={"state": "status"})
            .build()
        )
        assert flow.steps[0].output_mapping == {"state": "status"}

    def test_explain_flow_projects_remapped_key(self) -> None:
        # The static plan must reflect the renamed context key, not the raw one,
        # so a downstream reference to it is not falsely flagged unresolved.
        flow = Flow(
            name="rename",
            description="explain_flow honours output_mapping.",
            steps=[
                FlowStep(
                    tool_name="make_profile",
                    input_mapping={"seed": 0},
                    output_mapping={"state": "status"},
                ),
            ],
        )
        ex = _make_executor(flow, _profile_tool())
        plan = ex.explain_flow("rename", {})
        assert "state" in plan.final_context_shape
        assert "status" not in plan.final_context_shape

    def test_compiler_flags_unknown_output_key(self) -> None:
        flow = Flow(
            name="bad",
            description="Static detection of an unmapped output key.",
            steps=[
                FlowStep(
                    tool_name="make_profile",
                    input_mapping={"seed": 0},
                    output_mapping={"x": "nonexistent"},
                ),
            ],
        )
        ex = _make_executor(flow, _profile_tool())
        compiled = compile_flow(flow, ex.registered_tools)
        assert not compiled.success
        assert any(e.issue_type == "unknown_output_key" for e in compiled.errors)


# ---------------------------------------------------------------------------
# #316 — dynamic_params
# ---------------------------------------------------------------------------


class TestDynamicParams:
    def _flow(self) -> Flow:
        return Flow(
            name="account",
            description="Answer a query against an injected account.",
            dynamic_params=("account",),
            steps=[
                FlowStep(
                    tool_name="account_overview",
                    input_mapping={"query": "query", "account": "account"},
                ),
            ],
        )

    def test_async_injection_reaches_output(self) -> None:
        ex = _make_executor(self._flow(), _account_tool())
        result = asyncio.run(
            ex.execute_flow_async(
                "account", {"query": "balance"}, dynamic_params={"account": "1.60007029"}
            )
        )
        assert result.success is True, [r.error_message for r in result.execution_log]
        assert result.final_output is not None
        assert result.final_output["answer"] == "balance for account 1.60007029"
        assert result.final_output["account"] == "1.60007029"

    def test_sync_injection_parity(self) -> None:
        ex = _make_executor(self._flow(), _account_tool())
        result = ex.execute_flow(
            "account", {"query": "balance"}, dynamic_params={"account": "ACC-1"}
        )
        assert result.final_output is not None
        assert result.final_output["answer"] == "balance for account ACC-1"

    def test_dynamic_param_not_in_input_schema(self) -> None:
        # Declared dynamic params are deliberately absent from the LLM-visible
        # input_schema; the flow author models only the visible inputs there.
        flow = Flow(
            name="account",
            description="Only the query is LLM-visible.",
            dynamic_params=("account",),
            input_schema_ref=Flow.schema_ref_from(_VisibleInput),
            steps=[
                FlowStep(
                    tool_name="account_overview",
                    input_mapping={"query": "query", "account": "account"},
                ),
            ],
        )
        assert flow.input_schema is not None
        assert "account" not in flow.input_schema.model_fields
        # _VisibleInput is permissive-by-default Pydantic, so initial_input that
        # omits `account` still validates — the param arrives out-of-band.
        ex = _make_executor(flow, _account_tool())
        result = ex.execute_flow(
            "account", {"query": "balance"}, dynamic_params={"account": "ACC-9"}
        )
        assert result.success is True, [r.error_message for r in result.execution_log]

    def test_dynamic_params_round_trip(self) -> None:
        restored = flow_from_json(flow_to_json(self._flow()))
        assert isinstance(restored, Flow)
        assert restored.dynamic_params == ("account",)
