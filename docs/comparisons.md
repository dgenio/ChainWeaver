# How ChainWeaver compares to other orchestration libraries

> **Last reviewed:** 2026-05-16 · **ChainWeaver version:** 0.4.0
>
> This is a living document. Versions of the alternatives drift quickly;
> the matrix below pins each comparison to a specific release and cites
> the alternative's own docs. If you spot something stale, please open an
> issue — accuracy beats convenience.
>
> Tone goal: factual, not boastful. ChainWeaver makes a specific
> tradeoff (smaller surface area, narrower scope) that is right for some
> use cases and wrong for others. The sections below try to make the
> tradeoffs clear so you can pick the tool that fits.

---

## Matrix

| Property | **ChainWeaver 0.4** | LangChain LCEL ([0.3.x](https://python.langchain.com/docs/concepts/lcel/)) | LangGraph ([0.6.x](https://langchain-ai.github.io/langgraph/)) | Prefect ([3.x](https://docs.prefect.io/)) | Dagster ([1.10.x](https://docs.dagster.io/)) | Temporal Python SDK ([1.x](https://docs.temporal.io/develop/python)) |
|---|---|---|---|---|---|---|
| **No LLM calls between steps**[¹](#footnotes) | ✅ Hard invariant | ⚠️ Possible, not enforced | ⚠️ Possible, not enforced | ✅ N/A (not LLM-aware) | ✅ N/A (not LLM-aware) | ✅ N/A (not LLM-aware) |
| **Pydantic-validated tool I/O** | ✅ Required | ⚠️ Optional via `RunnableLambda` typing | ✅ Pydantic state schemas supported | ✅ Pydantic 2 native | ⚠️ Dagster `Config` (own type system, Pydantic-compatible) | ⚠️ Pydantic optional via `dataclass` / activity I/O |
| **Runtime dependencies** | 4 (pydantic, tenacity, typer, packaging) | Heavy: `langchain-core` + langsmith + provider SDKs | Heavy: `langgraph` + `langchain-core` | Heavy: SQLAlchemy, anyio, httpx, prefect-client, … | Very heavy: graphql-core, alembic, pendulum, … | Heavy: gRPC, protobuf, Temporal server |
| **File-serializable flows (YAML/JSON round-trip)** | ✅ `.flow.yaml` / `.flow.json` | ⚠️ Via LangChain Hub for some Runnables; not a first-class format | ❌ Code-defined graphs | ❌ Code-defined flows | ❌ Code-defined assets | ❌ Code-defined workflows |
| **Standalone / no server required** | ✅ Pure in-process Python | ✅ In-process | ✅ In-process | ⚠️ Ephemeral mode in-process; production needs server | ⚠️ Requires Dagster daemon + webserver for production | ❌ Requires Temporal server |
| **Built-in checkpoint / resume**[²](#footnotes) | 🚧 [#128](https://github.com/dgenio/ChainWeaver/issues/128) | ❌ | ✅ via `Checkpointer` | ✅ Task results, retries | ✅ Asset materializations | ✅ First-class (the whole point) |
| **Distributed execution** | ❌ In-process only | ❌ | ⚠️ Via LangGraph Platform | ✅ Workers / agents | ✅ Run launchers | ✅ Built around it |
| **Static schema-compatibility analysis** | 🚧 [#77](https://github.com/dgenio/ChainWeaver/issues/77) | ❌ | ❌ | ❌ | ⚠️ Asset graph validation | ❌ |

Legend: ✅ supported · ⚠️ partial / configurable · ❌ not supported · 🚧 in development.

[¹]: "No LLM calls between steps" means the orchestrator itself does not invoke an LLM between user-defined steps. Several frameworks support LLM-free graphs but don't enforce the property at the framework level.

[²]: ChainWeaver's `Checkpointer` is being delivered in [PR #136](https://github.com/dgenio/ChainWeaver/pull/136); once merged the column flips to ✅.

---

## Notes per alternative

### LangChain (LCEL — LangChain Expression Language)

LangChain is the dominant LLM orchestration library; LCEL is its
declarative composition layer where Runnables are piped together. LCEL
graphs can run without LLM calls between steps if every step is a pure
function — but the framework is built around LLM integration and
doesn't enforce LLM-freedom.

**Pick LangChain when:** your flow's primary purpose is to chain LLM
calls, you want the broad provider/tool integration surface, and you
accept the dependency footprint.

**Pick ChainWeaver when:** the *value* of compilation is removing
LLM calls between tool steps — and you want that guaranteed at the
framework level, not as a convention.

Docs: <https://python.langchain.com/docs/concepts/lcel/>

### LangGraph

LangGraph is LangChain's graph-execution layer with state, branching,
and checkpointing. It supports Pydantic state schemas and conditional
edges, and the LangGraph Platform offers managed durable execution.

**Pick LangGraph when:** you need agentic graphs with stateful
branching, LLM-aware checkpointers, and the broader LangChain
ecosystem.

**Pick ChainWeaver when:** you want the *opposite* — a strictly
deterministic, LLM-free graph runner with file-serializable definitions
and a small dependency footprint.

Docs: <https://langchain-ai.github.io/langgraph/>

### Prefect 3

Prefect is a general-purpose workflow orchestrator. Flows and tasks
are Python functions with `@flow` / `@task` decorators. Prefect 3
natively supports Pydantic 2 inputs and can run "ephemeral" without a
server, but production deployments expect a Prefect server (self-hosted
or Prefect Cloud).

**Pick Prefect when:** you need a mature workflow scheduler with retries,
caching, distributed workers, and observability — and you accept the
operational footprint of running a server.

**Pick ChainWeaver when:** you specifically want LLM-tool-chain
orchestration without a separate orchestration runtime — flows are
in-process Python data structures, no server, no scheduler.

Docs: <https://docs.prefect.io/>

### Dagster

Dagster is an asset-oriented orchestrator. The unit of composition is an
"asset" with explicit dependencies; the framework tracks materializations
and lineage. Dagster has its own config system (Pydantic-compatible) and
expects a daemon + webserver for production.

**Pick Dagster when:** your work is data-asset-shaped (tables, files,
ML artifacts) and you want lineage + scheduling + a UI.

**Pick ChainWeaver when:** your work is tool-call-shaped (function I/O
chains, not asset materializations) and you don't want a separate
orchestration runtime.

Docs: <https://docs.dagster.io/>

### Temporal (Python SDK)

Temporal is a distributed, durable execution platform — workflows can
run for days or years across process restarts, with strong guarantees
around exactly-once activity execution. It requires a Temporal server
(self-hosted, Temporal Cloud, or local dev server) and a worker process
per activity queue.

**Pick Temporal when:** workflows are long-running, distributed, or
need cross-service durability guarantees that survive process death.

**Pick ChainWeaver when:** flows are short, in-process, deterministic
compositions — and the framework overhead of running a server isn't
justified by the workload.

Docs: <https://docs.temporal.io/develop/python>

---

## Why "compiled, not interpreted"?

The phrase ChainWeaver uses for itself — "compiled, not interpreted" —
is meant to signal one specific design choice: the path through a flow
is fixed at definition time, not chosen at runtime by a language model.
The five alternatives above each make a different design choice that's
right for their own audience:

- LangChain / LangGraph treat LLM intermediation as a feature.
- Prefect / Dagster treat orchestration as infrastructure (workers,
  schedulers, UIs).
- Temporal treats durability as the primary contract.

ChainWeaver treats "no LLM call between steps" as a hard invariant in
`executor.py` and aligns the rest of the design around it
(schema-validated I/O, file-serializable flows, no server). If that
trade-off matches your workload, ChainWeaver fits. If not, one of the
alternatives above probably fits better.

---

## Refresh schedule

This document is reviewed on each ChainWeaver minor release. If any
alternative ships a major change that invalidates a row in the matrix,
open an issue tagged `type:docs` and reference this file.
