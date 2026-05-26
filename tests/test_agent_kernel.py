"""Tests for the agent-kernel execution backend (issue #89)."""

from __future__ import annotations

from typing import Any

import pytest
from helpers import NumberInput, ValueOutput, _double_fn

from chainweaver.exceptions import KernelInvocationError
from chainweaver.flow import DAGFlow, DAGFlowStep
from chainweaver.integrations.agent_kernel import (
    InMemoryKernel,
    KernelBackedExecutor,
    KernelProtocol,
)
from chainweaver.integrations.weaver_spec import CapabilityToken
from chainweaver.middleware import StepEndContext, StepStartContext
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool


class _RecordingMiddleware:
    """Records lifecycle hook invocations in order for assertions."""

    def __init__(self) -> None:
        self.events: list[tuple[str, Any]] = []

    def on_step_start(self, ctx: StepStartContext) -> None:
        self.events.append(("step_start", ctx))

    def on_step_end(self, ctx: StepEndContext) -> None:
        self.events.append(("step_end", ctx))


def _ingest_capability(inputs: dict[str, Any], token: CapabilityToken) -> dict[str, Any]:
    return {"rows": len(inputs.get("records", [])), "via": token.capability_id}


def _build_capability_dag() -> DAGFlow:
    return DAGFlow(
        name="cap_dag",
        version="0.1.0",
        description="Single capability step.",
        steps=[
            DAGFlowStep(
                tool_name="ingest_capability_proxy",
                step_id="ingest",
                step_type="capability",
                capability_id="data.ingest",
            ),
        ],
    )


def test_in_memory_kernel_satisfies_protocol() -> None:
    kernel = InMemoryKernel({"data.ingest": _ingest_capability})
    assert isinstance(kernel, KernelProtocol)


def test_in_memory_kernel_raises_for_unknown_capability() -> None:
    kernel = InMemoryKernel({})
    with pytest.raises(LookupError, match=r"data\.ingest"):
        kernel.invoke(CapabilityToken(capability_id="data.ingest", token=""), {})


def test_kernel_backed_executor_rejects_non_protocol_kernel() -> None:
    reg = FlowRegistry()
    with pytest.raises(TypeError, match="KernelProtocol"):
        KernelBackedExecutor(registry=reg, kernel="not a kernel")  # type: ignore[arg-type]


def test_kernel_backed_executor_runs_capability_step() -> None:
    dag = _build_capability_dag()
    reg = FlowRegistry()
    reg.register_flow(dag)
    kernel = InMemoryKernel({"data.ingest": _ingest_capability})
    ex = KernelBackedExecutor(registry=reg, kernel=kernel)
    result = ex.execute_flow("cap_dag", {"records": [1, 2, 3]})
    assert result.success is True
    assert result.execution_log[0].outputs == {"rows": 3, "via": "data.ingest"}


def test_capability_step_emits_lifecycle_events() -> None:
    """Capability steps fire on_step_start/on_step_end like tool steps (issue #89)."""
    dag = _build_capability_dag()
    reg = FlowRegistry()
    reg.register_flow(dag)
    kernel = InMemoryKernel({"data.ingest": _ingest_capability})
    recorder = _RecordingMiddleware()
    ex = KernelBackedExecutor(registry=reg, kernel=kernel, middleware=[recorder])
    result = ex.execute_flow("cap_dag", {"records": [1, 2, 3]})
    assert result.success is True
    kinds = [kind for kind, _ in recorder.events]
    assert "step_start" in kinds
    assert "step_end" in kinds
    assert kinds.index("step_start") < kinds.index("step_end")
    start_ctx = next(ctx for kind, ctx in recorder.events if kind == "step_start")
    end_ctx = next(ctx for kind, ctx in recorder.events if kind == "step_end")
    assert start_ctx.tool_name == "ingest_capability_proxy"
    assert end_ctx.step_record.success is True
    assert end_ctx.step_record.outputs == {"rows": 3, "via": "data.ingest"}


def test_capability_step_failure_still_emits_step_end() -> None:
    """A failing capability step still emits on_step_end for observability (issue #89)."""

    def boom(inputs: dict[str, Any], token: CapabilityToken) -> dict[str, Any]:
        raise RuntimeError("kernel broke")

    dag = _build_capability_dag()
    reg = FlowRegistry()
    reg.register_flow(dag)
    kernel = InMemoryKernel({"data.ingest": boom})
    recorder = _RecordingMiddleware()
    ex = KernelBackedExecutor(registry=reg, kernel=kernel, middleware=[recorder])
    result = ex.execute_flow("cap_dag", {"records": [1]})
    assert result.success is False
    end_ctx = next(ctx for kind, ctx in recorder.events if kind == "step_end")
    assert end_ctx.step_record.success is False


def test_kernel_backed_executor_still_runs_tool_steps() -> None:
    """Tool-typed steps in the same flow keep using the standard path."""
    dag = DAGFlow(
        name="mixed",
        version="0.1.0",
        description="Tool + capability mix.",
        steps=[
            DAGFlowStep(
                tool_name="double",
                step_id="d",
                input_mapping={"number": "number"},
            ),
            DAGFlowStep(
                tool_name="ingest_capability_proxy",
                step_id="i",
                step_type="capability",
                capability_id="data.ingest",
                depends_on=["d"],
            ),
        ],
    )
    reg = FlowRegistry()
    reg.register_flow(dag)
    kernel = InMemoryKernel({"data.ingest": _ingest_capability})
    ex = KernelBackedExecutor(registry=reg, kernel=kernel)
    ex.register_tool(
        Tool(
            name="double",
            description="d",
            input_schema=NumberInput,
            output_schema=ValueOutput,
            fn=_double_fn,
        )
    )
    result = ex.execute_flow("mixed", {"number": 4, "records": [10, 20]})
    assert result.success is True
    # First step ran via tool path
    assert result.execution_log[0].tool_name == "double"
    assert result.execution_log[0].outputs == {"value": 8}
    # Second step ran via kernel path
    assert result.execution_log[1].outputs == {"rows": 2, "via": "data.ingest"}


def test_kernel_backed_executor_wraps_kernel_exceptions() -> None:
    def boom(inputs: dict[str, Any], token: CapabilityToken) -> dict[str, Any]:
        raise RuntimeError("kernel broke")

    dag = _build_capability_dag()
    reg = FlowRegistry()
    reg.register_flow(dag)
    kernel = InMemoryKernel({"data.ingest": boom})
    ex = KernelBackedExecutor(registry=reg, kernel=kernel)
    result = ex.execute_flow("cap_dag", {"records": []})
    assert result.success is False
    rec = result.execution_log[0]
    assert rec.error_type == "KernelInvocationError"
    assert "kernel broke" in (rec.error_message or "")
    assert "RuntimeError" in (rec.error_message or "")


def test_kernel_backed_executor_rejects_non_dict_kernel_output() -> None:
    def returns_string(inputs: dict[str, Any], token: CapabilityToken) -> dict[str, Any]:
        return "not a dict"  # type: ignore[return-value]

    dag = _build_capability_dag()
    reg = FlowRegistry()
    reg.register_flow(dag)
    kernel = InMemoryKernel({"data.ingest": returns_string})
    ex = KernelBackedExecutor(registry=reg, kernel=kernel)
    result = ex.execute_flow("cap_dag", {})
    assert result.success is False
    assert result.execution_log[0].error_type == "KernelInvocationError"
    assert "non-dict" in (result.execution_log[0].error_message or "")


def test_default_token_propagates_when_capability_id_matches() -> None:
    captured: list[CapabilityToken] = []

    def capture_token(inputs: dict[str, Any], token: CapabilityToken) -> dict[str, Any]:
        captured.append(token)
        return {"ok": True}

    dag = _build_capability_dag()
    reg = FlowRegistry()
    reg.register_flow(dag)
    kernel = InMemoryKernel({"data.ingest": capture_token})
    default_tok = CapabilityToken(
        capability_id="data.ingest", token="secret-token", scopes=("read",)
    )
    ex = KernelBackedExecutor(registry=reg, kernel=kernel, default_token=default_tok)
    result = ex.execute_flow("cap_dag", {})
    assert result.success is True
    assert len(captured) == 1
    assert captured[0] is default_tok


def test_default_token_ignored_when_capability_id_mismatches() -> None:
    """A token for a different capability id is not used — a fresh token is minted."""
    captured: list[CapabilityToken] = []

    def capture_token(inputs: dict[str, Any], token: CapabilityToken) -> dict[str, Any]:
        captured.append(token)
        return {"ok": True}

    dag = _build_capability_dag()
    reg = FlowRegistry()
    reg.register_flow(dag)
    kernel = InMemoryKernel({"data.ingest": capture_token})
    wrong_tok = CapabilityToken(capability_id="other.cap", token="x")
    ex = KernelBackedExecutor(registry=reg, kernel=kernel, default_token=wrong_tok)
    result = ex.execute_flow("cap_dag", {})
    assert result.success is True
    assert captured[0].capability_id == "data.ingest"
    assert captured[0].token == ""


def test_input_mapping_resolves_keys_for_capability_steps() -> None:
    seen_inputs: list[dict[str, Any]] = []

    def echo(inputs: dict[str, Any], token: CapabilityToken) -> dict[str, Any]:
        seen_inputs.append(dict(inputs))
        return {"echoed": True}

    dag = DAGFlow(
        name="cap_dag_mapped",
        version="0.1.0",
        description="Capability step with input_mapping.",
        steps=[
            DAGFlowStep(
                tool_name="cap_proxy",
                step_id="cap",
                step_type="capability",
                capability_id="data.echo",
                input_mapping={"payload": "raw"},
            ),
        ],
    )
    reg = FlowRegistry()
    reg.register_flow(dag)
    kernel = InMemoryKernel({"data.echo": echo})
    ex = KernelBackedExecutor(registry=reg, kernel=kernel)
    result = ex.execute_flow("cap_dag_mapped", {"raw": {"x": 1}})
    assert result.success is True
    assert seen_inputs == [{"payload": {"x": 1}}]


def test_missing_input_mapping_source_fails_capability_step() -> None:
    dag = DAGFlow(
        name="cap_dag_bad_mapping",
        version="0.1.0",
        description="Missing mapping key.",
        steps=[
            DAGFlowStep(
                tool_name="cap_proxy",
                step_id="cap",
                step_type="capability",
                capability_id="data.echo",
                input_mapping={"payload": "nonexistent_key"},
            ),
        ],
    )
    reg = FlowRegistry()
    reg.register_flow(dag)
    kernel = InMemoryKernel({"data.echo": lambda i, t: {"ok": True}})
    ex = KernelBackedExecutor(registry=reg, kernel=kernel)
    result = ex.execute_flow("cap_dag_bad_mapping", {"raw": 1})
    assert result.success is False
    assert result.execution_log[0].error_type == "KernelInvocationError"
    assert "not found in context" in (result.execution_log[0].error_message or "")


def test_kernel_invocation_error_carries_context() -> None:
    err = KernelInvocationError("data.x", 3, "broken")
    assert err.capability_id == "data.x"
    assert err.step_index == 3
    assert err.detail == "broken"
    assert "data.x" in str(err)
    assert "step 3" in str(err)


def test_base_flow_executor_still_rejects_capability_steps() -> None:
    """Sanity check: the FlowExecutor base class still fails on capability steps."""
    from chainweaver.executor import FlowExecutor

    dag = _build_capability_dag()
    reg = FlowRegistry()
    reg.register_flow(dag)
    ex = FlowExecutor(registry=reg)
    result = ex.execute_flow("cap_dag", {})
    assert result.success is False
    assert result.execution_log[0].error_type == "FlowExecutionError"
    assert "KernelBackedExecutor" in (result.execution_log[0].error_message or "")
