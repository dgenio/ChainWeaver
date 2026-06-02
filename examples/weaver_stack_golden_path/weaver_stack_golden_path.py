"""Weaver Stack golden path: route -> execute -> gate (issue #234).

A single runnable example showing the three Weaver Stack layers cooperating
on one task, using the *real* published ``weaver-contracts`` types (issue
#233):

1. **contextweaver (routing)** — a routing decision picks *which* capability
   handles the request out of a bounded candidate set.
2. **ChainWeaver (execution)** — the selected capability resolves to a
   registered deterministic flow, which ChainWeaver runs with strict schemas
   and no LLM between steps.
3. **agent-kernel (gating)** — the flow's ``capability``-typed step is
   dispatched through a kernel that *gates* the call against a
   ``CapabilityToken`` scope before executing it.

The run prints a ``weaver_contracts.TraceEvent`` audit trail so the whole
route -> execute -> gate path is visible end-to-end.

Run it::

    pip install 'chainweaver[weaver-stack]'
    python examples/weaver_stack_golden_path/weaver_stack_golden_path.py

The example degrades gracefully: without the ``weaver-stack`` extra it prints
a skip notice and exits 0 instead of failing, so it is safe to run from a
base install.
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime, timezone

from pydantic import BaseModel

try:  # The Weaver Stack contract is an optional extra.
    from chainweaver.integrations.weaver_spec import (
        CapabilityToken,
        TraceEvent,
        flow_to_selectable_item,
        make_routing_decision,
        resolve_flow_from_routing_decision,
        selected_capability_id,
    )
except ImportError:
    print(
        "[weaver-stack] skipped: install the extra with "
        "`pip install 'chainweaver[weaver-stack]'` to run the golden path."
    )
    sys.exit(0)

from chainweaver.flow import DAGFlow, DAGFlowStep
from chainweaver.integrations.agent_kernel import InMemoryKernel, KernelBackedExecutor
from chainweaver.registry import FlowRegistry
from chainweaver.tools import Tool

# ---------------------------------------------------------------------------
# A tiny deterministic tool + capability the flow will use.
# ---------------------------------------------------------------------------


class TextInput(BaseModel):
    text: str


class CountOutput(BaseModel):
    word_count: int


def _count_words(payload: TextInput) -> CountOutput:
    return CountOutput(word_count=len(payload.text.split()))


def _render_report(inputs: dict[str, object], token: CapabilityToken) -> dict[str, object]:
    """An agent-kernel capability: render a report from the word count.

    Receives the :class:`CapabilityToken` the kernel authorized the call with,
    so the rendered artifact can record *who* produced it.
    """
    word_count = inputs["word_count"]
    return {
        "report": f"Document analysed: {word_count} words.",
        "rendered_by": token.principal,
    }


def _build_registry() -> FlowRegistry:
    """Register the ``report.generate`` capability as a deterministic flow."""
    flow = DAGFlow(
        name="generate_report",
        version="1.0.0",
        description="Count a document's words, then render a report.",
        capability_id="report.generate",
        steps=[
            DAGFlowStep(
                tool_name="count_words",
                step_id="count",
                input_mapping={"text": "text"},
            ),
            DAGFlowStep(
                tool_name="render_report_proxy",
                step_id="render",
                step_type="capability",
                capability_id="report.render",
                input_mapping={"word_count": "word_count"},
                depends_on=["count"],
            ),
        ],
    )
    registry = FlowRegistry()
    registry.register_flow(flow)
    return registry


def _trace_event(event_type: str, **fields: object) -> TraceEvent:
    return TraceEvent(
        event_id=uuid.uuid4().hex,
        event_type=event_type,
        timestamp=datetime.now(timezone.utc),
        **fields,  # type: ignore[arg-type]
    )


def main() -> None:
    registry = _build_registry()
    audit: list[TraceEvent] = []

    # --- Layer 1: contextweaver routes among advertised capabilities. --------
    # The catalog is what a router would ingest (issue #107); here we advertise
    # the one flow and route to it out of a small candidate set.
    catalog = [flow_to_selectable_item(registry.get_flow("generate_report"))]
    candidates = (*(item.capability_id for item in catalog), "report.summary")
    decision = make_routing_decision(
        decision_id="route-1",
        selected_capability_id="report.generate",
        candidates=candidates,
        context_summary="Full document analysis requested.",
    )
    chosen = selected_capability_id(decision)
    print(f"1. contextweaver routed -> {chosen!r} (from {list(candidates)})")

    # --- Layer 2: ChainWeaver resolves the decision to a flow. ---------------
    flow = resolve_flow_from_routing_decision(decision, registry)
    print(f"2. ChainWeaver resolved capability -> flow {flow.name!r} v{flow.version}")
    audit.append(_trace_event("flow_started", capability_id=chosen))

    # --- Layer 3: agent-kernel gates the capability step. --------------------
    # The kernel grants a scoped token; it refuses any capability the token's
    # scope does not authorize (see InMemoryKernel.invoke).
    grant = CapabilityToken(
        token_id="grant-1",
        principal="golden-path-demo",
        scope=["report.render"],
        issued_at=datetime.now(timezone.utc),
        single_use=True,
    )
    audit.append(_trace_event("token_issued", capability_id="report.render"))
    audit.append(
        _trace_event(
            "capability_authorized", capability_id="report.render", principal=grant.principal
        )
    )

    kernel = InMemoryKernel({"report.render": _render_report})
    executor = KernelBackedExecutor(registry=registry, kernel=kernel, default_token=grant)
    executor.register_tool(
        Tool(
            name="count_words",
            description="Count the words in a document.",
            input_schema=TextInput,
            output_schema=CountOutput,
            fn=_count_words,
        )
    )

    result = executor.execute_flow(flow.name, {"text": "the quick brown fox jumps"})
    for record in result.execution_log:
        event_type = "flow_step_completed" if record.success else "flow_failed"
        audit.append(
            _trace_event(
                event_type,
                capability_id=chosen,
                outcome="success" if record.success else "failure",
            )
        )
    audit.append(
        _trace_event(
            "flow_completed",
            capability_id=chosen,
            outcome="success" if result.success else "failure",
        )
    )

    print(f"3. agent-kernel gated + executed -> {result.final_output}")
    print("\nAudit trace (weaver_contracts.TraceEvent):")
    for event in audit:
        print(f"  - {event.event_type:<20} outcome={event.outcome or '-'}")

    # Inline assertions keep this script honest as a smoke test.
    assert result.success, "golden path flow did not succeed"
    assert result.final_output is not None
    assert result.final_output["word_count"] == 5
    assert result.final_output["report"] == "Document analysed: 5 words."
    assert result.final_output["rendered_by"] == "golden-path-demo"
    assert audit[-1].event_type == "flow_completed"
    assert audit[-1].outcome == "success"

    print("\n[weaver-stack] golden path OK")


if __name__ == "__main__":
    main()
