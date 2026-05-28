# Recipe — Expose a ChainWeaver flow as an OpenAI Agents SDK tool

**You have:** an agent built on the OpenAI Agents SDK.
**You want:** to expose a compiled ChainWeaver flow to it as **one** callable
tool, so the agent picks *when* to run the flow and ChainWeaver runs the internals
deterministically.

Paired script: `examples/integrations/openai_agents_tool.py`. It runs in a
**dry-run** mode — no API key, no network.

## Install

The Agents SDK is an optional extra:

```bash
pip install 'chainweaver[openai-agents]'
```

## The shape

ChainWeaver already ships the two pieces you need:

- `flow_to_openai_function(flow, executor)` → the OpenAI function schema
  (`{"type": "function", "function": {...}}`);
- `flow_to_callable(flow, executor)` → a plain `dict -> dict` callable that runs
  the flow.

Wrap them into an `agents.FunctionTool`:

```python
from agents import FunctionTool

flow = executor.registry.get_flow("price_with_tax")
run_flow = flow_to_callable(flow, executor, input_schema=FlowInput)
fn_spec = flow_to_openai_function(flow, executor, input_schema=FlowInput)["function"]

async def on_invoke_tool(_ctx, arguments_json: str) -> str:
    args = FlowInput.model_validate_json(arguments_json)
    return json.dumps(run_flow(args.model_dump()))

tool = FunctionTool(
    name=fn_spec["name"],
    description=fn_spec["description"],
    params_json_schema=fn_spec["parameters"],
    on_invoke_tool=on_invoke_tool,
    strict_json_schema=False,
)

agent = Agent(name="pricing-agent", instructions="Price items with tax.", tools=[tool])
```

## Dry-run validation

You can exercise the wrapper end-to-end without any API key by invoking
`on_invoke_tool` directly — exactly what the agent runtime does, minus the model
call:

```python
raw = asyncio.run(tool.on_invoke_tool(None, json.dumps({"amount": "$100", "rate": 0.23})))
# {"...": ..., "total": 123.0}
```

Registering the tool on an `Agent` needs no key; only *running* the agent
(`Runner.run`) does. Stop at the dry-run in CI.

## The boundary

The agent decides whether to call the flow; ChainWeaver validates the input,
runs the deterministic internals, and validates the output. No model sits
between the flow's steps.

## What next

- [LangGraph recipe](langgraph-node.md) — the same idea for LangGraph.
- The generic export adapters (OpenAI, Anthropic, plain callables) are in
  `chainweaver.export`; issue #25 tracks the broader adapter surface.
