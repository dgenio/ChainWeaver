# When ChainWeaver fits

ChainWeaver is built for one specific shape of problem. This page explains when that
shape matches your problem — and when it doesn't.

## Use ChainWeaver when

- **The flow is predictable.** You can describe the next tool given the previous
  output, without asking a model to decide.
- **Determinism matters.** You need the same input to produce the same output, the same
  execution path, and the same trace — every time.
- **You want strict schemas.** Tool inputs and outputs are Pydantic-validated at every
  step boundary. Type mismatches fail fast and loudly.
- **You need audit-grade traces.** Every step record is JSON-serializable, replayable,
  and stable across releases.
- **You're paying a tax on intermediate LLM calls.** ChainWeaver's headline savings come
  from eliminating "let me think about what to do next" calls between deterministic
  steps.
- **You compose flows.** Flows can be wrapped as tools (`Tool.from_flow`) and used as
  steps in other flows. This is the tool-space reduction story.

## Don't use ChainWeaver when

- **Every step requires open-ended reasoning.** If the next tool genuinely cannot be
  known until the previous step's output is interpreted by a model, ChainWeaver is the
  wrong layer. Use an agent framework (LangGraph, the OpenAI/Anthropic SDK tool-use
  loops, your own dispatcher).
- **The plan changes dynamically based on user intent.** ChainWeaver flows are compiled
  ahead of time. They don't branch on free-form text.
- **You need a general workflow engine.** Long-running scheduled jobs, durable timers,
  fan-out to thousands of workers — that's Prefect, Dagster, or Temporal territory. See
  [vs LangChain / Prefect / Dagster / Temporal / LangGraph](comparisons.md).
- **You expect the executor to call an LLM.** It deliberately doesn't. Reasoning is the
  caller's job; ChainWeaver only runs what you've already decided.
- **You need streaming token-by-token output from a model.** ChainWeaver streams
  `FlowEvent` lifecycle events, not LLM tokens.

## How ChainWeaver relates to neighbours

This is a deliberately narrow tool. It sits next to — not on top of — agent frameworks
and workflow engines:

- **Agent frameworks** (LangChain agents, LangGraph, Anthropic / OpenAI tool-use loops):
  ChainWeaver can be **invoked from** them. When an agent recognises that the next few
  tool calls are deterministic, it dispatches a compiled flow instead of asking the LLM
  to think between each one.
- **MCP servers**: the planned MCP adapter (#150) will let ChainWeaver consume tools
  from MCP servers and expose compiled flows back as MCP-callable tools. Until then,
  use the MCP-shaped flow pattern in the cookbook.
- **Workflow engines** (Prefect, Dagster, Temporal): different mission. They schedule
  *jobs* across time; ChainWeaver compiles *tool flows* within a single agent turn.
- **LCEL / LangChain Expression Language**: closest sibling. Both express "call tool A,
  then B, then C". ChainWeaver adds Pydantic-validated schemas at every boundary,
  zero-LLM-between-steps as a hard invariant, and file-serializable flow definitions.

## A small concrete contrast

The same three-step task, expressed two ways:

```python
# Naive agent loop — three LLM round-trips between three tool calls
plan = llm("How do I fetch, transform, and store this URL?")
intermediate1 = call_tool("fetch", parse_plan(plan).step_1)
plan2 = llm(f"Next step given {intermediate1}?")
intermediate2 = call_tool("transform", parse_plan(plan2).step_2)
plan3 = llm(f"Next step given {intermediate2}?")
final = call_tool("store", parse_plan(plan3).step_3)
```

```python
# Compiled flow — zero LLM calls between steps
flow = Flow(
    name="fetch_transform_store",
    description="Standard ETL.",
    steps=[
        FlowStep(tool_name="fetch", input_mapping={"url": "url"}),
        FlowStep(tool_name="transform", input_mapping={"data": "data"}),
        FlowStep(tool_name="store", input_mapping={"records": "records"}),
    ],
)
result = executor.execute_flow("fetch_transform_store", {"url": url})
```

Running `examples/naive_vs_compiled.py` from a fresh checkout shows the timing
difference for a five-step ETL flow.

## Reaching a verdict

If most of the flows your agent runs look like the second snippet above, ChainWeaver
will pay for itself in latency and reproducibility. If most of them look like the first,
keep your agent loop — and consider ChainWeaver only for the deterministic sub-flows
inside it.
