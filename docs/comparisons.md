# vs LangChain / Prefect / Dagster / Temporal / LangGraph

ChainWeaver overlaps with several adjacent libraries. The honest comparison is that
**no two of them solve the same problem**. This page lays out where they differ so you
can pick the right tool — not just the one you've heard of.

## Compact comparison

| | ChainWeaver | LangChain LCEL | Prefect 3 | Dagster | Temporal | LangGraph |
|---|---|---|---|---|---|---|
| LLM-free between steps (by design) | **Yes (hard invariant)** | No | N/A | N/A | N/A | No |
| Pydantic-validated I/O at every step | **Yes** | Partial | No | Partial | No | No |
| Single-dep install | **Yes (pydantic + 4 small libs)** | No | No | No | No | No |
| File-serializable flow definitions | **Yes (JSON / YAML)** | No | Python | Python | Python | No |
| Standalone (no scheduler / server) | **Yes** | Yes | No (server) | No (daemon) | No (server) | Yes |
| Built for MCP tool composition | Planned (#150) | No | No | No | No | No |
| Stateful long-running workflows | No | No | Yes | Yes | Yes | Partial |
| Graph branching on LLM output | No (by design) | Limited | N/A | N/A | N/A | **Yes** |
| Durable retries / scheduling | No | No | Yes | Yes | Yes | No |

> Versions evaluated: LangChain 0.3, LangGraph 0.3, Prefect 3, Dagster 1.9, Temporal 1.24
> (Python SDK), ChainWeaver 0.7. Re-evaluate on each minor release of any of these.

## One paragraph each

### LangChain LCEL

LangChain Expression Language is the closest neighbour. Both LCEL and ChainWeaver
express "run tool A, then B, then C". LCEL is more flexible (anything that satisfies
`Runnable` composes), more opinionated about LLM-centric primitives (prompts, retrievers,
output parsers), and does not promise zero LLM calls between steps — `RunnableLambda |
RunnableLambda` runs synchronously without a model, but the broader ecosystem assumes
models are in the loop. ChainWeaver picks "deterministic-by-construction" as a hard
invariant and trades flexibility for that guarantee. **Pick LangChain LCEL when** your
flow mixes LLM and non-LLM steps and you want one DSL covering both.
**Pick ChainWeaver when** the flow is fully deterministic and you want a runner that
can prove it.

### Prefect 3

Prefect is a general-purpose workflow engine: durable execution, scheduling, retries,
fan-out across workers, observability dashboards. It runs Python functions decorated
with `@flow` and `@task` against a Prefect server (cloud or self-hosted). The mission
shape is "data jobs that have to run on a schedule across time". ChainWeaver, by
contrast, runs **inside a single agent turn**: no scheduler, no server, no calendar.
**Pick Prefect when** your work shape is recurring data jobs.
**Pick ChainWeaver when** your work shape is "agent decides → run this deterministic
flow → return result".

### Dagster

Dagster is also a workflow engine, with a stronger emphasis on data-asset modelling:
software-defined assets, lineage, materialisations, partitioned schedules. It's the
"build a warehouse of curated datasets" tool. ChainWeaver doesn't model assets, doesn't
track lineage across runs, and doesn't carry state between calls — it's stateless,
ephemeral, embedded.
**Pick Dagster when** you need asset lineage and partitioned data jobs.
**Pick ChainWeaver when** you need a single agent turn to dispatch a known flow.

### Temporal

Temporal is a durable execution engine: workflows survive worker crashes, sleep for days
without holding RAM, and resume from any point. The cost is operational complexity
(Temporal cluster, worker processes, SDK constraints on which Python you can use inside
activities). ChainWeaver has no durability layer — a process restart kills an
in-flight flow — but offers checkpoint-based crash resume via `Checkpointer` for the
common case of "I want to retry from the last successful step".
**Pick Temporal when** you need true durable execution across hours / days / crashes.
**Pick ChainWeaver when** the flow finishes inside a single process and you only need
crash resume across operator-driven retries.

### LangGraph

LangGraph builds a graph where **nodes can decide which edge to follow next, based on
LLM output**. That's the polar opposite of ChainWeaver's design: ChainWeaver flows are
compiled with the graph fixed at definition time. LangGraph is the right tool when you
genuinely don't know the next node until a model has spoken; ChainWeaver is the right
tool when you do know.
**Pick LangGraph when** the next step depends on an LLM's decision.
**Pick ChainWeaver when** the flow is fixed and you want the cheapest, most repeatable
way to run it.

## Combining them

These libraries are not mutually exclusive. The realistic deployment uses several:

- An **agent framework** (LangGraph, Anthropic SDK tool-use, OpenAI Assistants, …) owns
  the conversation and decides "what to do next".
- ChainWeaver gets called **from inside** that agent's tool-call loop whenever the
  next few tool calls are deterministic.
- A **workflow engine** (Prefect, Dagster, Temporal) orchestrates the *outer* job —
  scheduling, recurring runs, durability — and treats the agent as one step in a larger
  workflow.

The result: the LLM thinks once, ChainWeaver dispatches deterministically, and the
workflow engine handles retries and scheduling. Each layer does what it's best at.

## Updating this page

This document is a **living comparison**. We re-evaluate on each minor release of any of
the projects listed above. If you spot a comparison that's gone stale, open an issue —
this page is a maintained dependency, not a marketing artefact.

References:

- [LangChain Expression Language docs](https://python.langchain.com/docs/concepts/lcel/)
- [Prefect 3 documentation](https://docs.prefect.io/v3/)
- [Dagster documentation](https://docs.dagster.io/)
- [Temporal Python SDK](https://docs.temporal.io/develop/python)
- [LangGraph documentation](https://langchain-ai.github.io/langgraph/)
