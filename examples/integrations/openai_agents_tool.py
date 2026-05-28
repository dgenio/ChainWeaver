"""Framework recipe: expose a ChainWeaver flow as an OpenAI Agents SDK tool (issue #206).

The most natural shape for OpenAI Agents SDK users is to expose a compiled
ChainWeaver flow as **one** callable tool: the agent decides *whether* to call
the flow; ChainWeaver runs the flow internals deterministically, with
schema-checked I/O and no model-mediated steps in between.

This recipe:

1. defines a small ChainWeaver flow (``parse_amount -> apply_tax``);
2. derives the OpenAI function schema with ``flow_to_openai_function`` and a
   plain callable with ``flow_to_callable``;
3. wraps both into an ``agents.FunctionTool``;
4. runs a **dry-run** that invokes the tool wrapper directly — no API key, no
   network — validating input/output schemas around the flow;
5. shows (construction only) how an ``Agent`` would register the tool.

Requires the optional Agents SDK extra::

    pip install 'chainweaver[openai-agents]'

Run from the repository root (dry-run, no API key needed)::

    python examples/integrations/openai_agents_tool.py
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from agents import Agent, FunctionTool
from pydantic import BaseModel

from chainweaver import Flow, FlowExecutor, FlowRegistry, FlowStep, Tool
from chainweaver.export.callable import flow_to_callable
from chainweaver.export.openai import flow_to_openai_function

# ---------------------------------------------------------------------------
# ChainWeaver flow: parse an amount string, then apply tax
# ---------------------------------------------------------------------------


class ParseInput(BaseModel):
    amount: str


class ParseOutput(BaseModel):
    value: float


class TaxInput(BaseModel):
    value: float
    rate: float


class TaxOutput(BaseModel):
    total: float


def parse_amount_fn(inp: ParseInput) -> dict[str, Any]:
    return {"value": float(inp.amount.replace("$", "").strip())}


def apply_tax_fn(inp: TaxInput) -> dict[str, Any]:
    return {"total": round(inp.value * (1 + inp.rate), 2)}


class FlowInput(BaseModel):
    amount: str
    rate: float


def build_executor() -> FlowExecutor:
    parse = Tool(
        name="parse_amount",
        description="Parse a currency string into a float.",
        input_schema=ParseInput,
        output_schema=ParseOutput,
        fn=parse_amount_fn,
    )
    tax = Tool(
        name="apply_tax",
        description="Apply a tax rate to a value.",
        input_schema=TaxInput,
        output_schema=TaxOutput,
        fn=apply_tax_fn,
    )
    flow = Flow(
        name="price_with_tax",
        version="0.1.0",
        description="Parse an amount and apply a tax rate.",
        steps=[
            FlowStep(tool_name="parse_amount", input_mapping={"amount": "amount"}),
            FlowStep(
                tool_name="apply_tax",
                input_mapping={"value": "value", "rate": "rate"},
            ),
        ],
    )
    registry = FlowRegistry()
    registry.register_flow(flow)
    executor = FlowExecutor(registry=registry)
    executor.register_tool(parse)
    executor.register_tool(tax)
    return executor


def build_function_tool(executor: FlowExecutor) -> FunctionTool:
    """Wrap the ``price_with_tax`` flow as an Agents SDK ``FunctionTool``."""
    flow = executor.registry.get_flow("price_with_tax")
    run_flow = flow_to_callable(flow, executor, input_schema=FlowInput)
    schema = flow_to_openai_function(flow, executor, input_schema=FlowInput)
    fn_spec = schema["function"]

    async def on_invoke_tool(_ctx: Any, arguments_json: str) -> str:
        # Validate the agent-supplied arguments, run the deterministic flow,
        # and return a JSON string. No API call happens here.
        args = FlowInput.model_validate_json(arguments_json)
        output = run_flow(args.model_dump())
        return json.dumps(output)

    return FunctionTool(
        name=fn_spec["name"],
        description=fn_spec["description"],
        params_json_schema=fn_spec["parameters"],
        on_invoke_tool=on_invoke_tool,
        strict_json_schema=False,
    )


def main() -> None:
    executor = build_executor()
    tool = build_function_tool(executor)

    # Dry-run: drive the tool wrapper directly, exactly as the agent runtime
    # would, but without an API key or network call.
    arguments = json.dumps({"amount": "$100", "rate": 0.23})
    raw = asyncio.run(tool.on_invoke_tool(None, arguments))  # type: ignore[arg-type]
    result = json.loads(raw)

    # Construction only — registering the tool on an Agent needs no API key;
    # actually *running* the agent (Runner.run) would, so we stop here.
    agent = Agent(name="pricing-agent", instructions="Price items with tax.", tools=[tool])

    print("ChainWeaver flow -> OpenAI Agents SDK FunctionTool (dry-run)")
    print("=" * 60)
    print(f"tool name   : {tool.name}")
    print(f"agent tools : {[t.name for t in agent.tools]}")
    print(f"input       : {arguments}")
    print(f"flow output : {result}")

    assert tool.name == "price_with_tax"
    assert result["total"] == 123.0
    assert agent.tools[0].name == "price_with_tax"


if __name__ == "__main__":
    main()
