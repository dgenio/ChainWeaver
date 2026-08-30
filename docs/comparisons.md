# ChainWeaver vs agent and workflow frameworks

ChainWeaver overlaps with several mature libraries. The important comparison is
**not** "which one can run deterministic code?" They all can, in different
forms.

The decision is whether you already know the workflow you want to run, or
whether you need evidence for **which regions of observed agent behavior should
stop being model-mediated in the first place**.

> **If you already know the path is fixed, start with the simplest thing that
> works: a Python function or the workflow primitive in the framework you
> already use.** ChainWeaver should earn another dependency through discovery,
> evidence, useful rejection, review/governance, security-boundary preservation,
> or drift handling—not through the claim that deterministic orchestration is
> otherwise unavailable.

The product thesis is under independent validation in
[#553](https://github.com/dgenio/ChainWeaver/issues/553). See
[Product validation & adoption gates](product-validation.md).

## Compact decision guide

| Starting problem | Usually start with | Where ChainWeaver may add value |
| --- | --- | --- |
| "I already know A → B → C and it is ordinary Python" | Plain Python | Only if you need ChainWeaver's contracts, evidence/audit, drift, or promotion lifecycle |
| "I need a stateful agent/workflow graph with fixed and conditional paths" | LangGraph | Analyze observed tool-use regions and propose/reject deterministic promotion candidates; optionally expose accepted capabilities back to the graph |
| "I use the OpenAI Agents SDK and want deterministic orchestration" | Agents SDK + normal code | Evidence-driven discovery/review of repeated tool paths and governed capability artifacts |
| "I need LLM-centric composable chains/retrievers/tools" | LangChain | Deterministic capability behind the agent/chain when the evidence says a region no longer needs model mediation |
| "I need scheduled data/workflow orchestration" | Prefect / Dagster | A bounded deterministic agent capability inside the larger job, if useful |
| "I need long-running durable business workflows" | Temporal (or LangGraph where its runtime fits) | Only for the agent/tool subproblem; ChainWeaver is not a replacement durable platform |
| "I have real agent traces and don't know which repeated paths are safe/worth compiling" | **ChainWeaver is testing this as its primary job** | Candidate discovery, evidence, rejection, review, governed promotion, drift |

## The baseline ChainWeaver must beat: plain Python

A repeated path can always be written directly:

```python
def collect_pr_context(repo, pr):
    files = list_changed_files(repo, pr)
    ci = read_ci(repo, pr)
    metadata = read_pr_metadata(repo, pr)
    return build_context(files, ci, metadata)
```

If that is all you need, it is probably the right answer.

ChainWeaver becomes interesting only if it contributes material value around the
*lifecycle*:

- identifying a useful candidate from real traces;
- proving the path recurs across independent sessions;
- distinguishing actual model-mediated transitions from assumed ones;
- validating cumulative dataflow/schema compatibility;
- showing counterexamples and rejected candidates;
- preserving authorization/approval boundaries during promotion;
- producing reproducible review evidence and durable artifact identity;
- detecting schema/safety/policy drift later;
- making the accepted capability portable or easy to expose through the host.

The validation program explicitly implements the manual baseline for accepted
candidates instead of comparing only against an intentionally inefficient agent
loop.

## LangGraph

LangGraph is a low-level orchestration/runtime system for agent workflows. Its
current documentation explicitly distinguishes **workflows with predetermined
code paths** from dynamic agents, and its Graph API supports both fixed and
conditional edges. Its custom-workflow guidance also supports mixing
deterministic logic with agentic behavior. The Functional API lets users write
ordinary Python control flow while retaining runtime features such as
checkpointing.

So this is **not** the differentiator:

> "ChainWeaver can run a fixed path; LangGraph cannot."

That would be false.

Use LangGraph when you want to author and operate the workflow/agent topology
itself, especially when state, durable execution, streaming, human-in-the-loop,
or mixed deterministic/agentic control flow are central.

ChainWeaver's narrower hypothesis is useful when the starting point is
**observed agent/tool traces** and the problem is determining which
model-mediated regions have earned deterministic promotion. If a candidate is
accepted, the resulting capability can be called from a LangGraph node; see the
[LangGraph recipe](cookbook/langgraph-node.md).

Official references:

- [LangGraph: workflows and agents](https://docs.langchain.com/oss/python/langgraph/workflows-agents)
- [LangGraph Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)
- [LangChain custom workflow](https://docs.langchain.com/oss/python/langchain/multi-agent/custom-workflow)
- [LangGraph Functional API](https://docs.langchain.com/oss/python/langgraph/functional-api)

## OpenAI Agents SDK

The OpenAI Agents SDK also explicitly supports **orchestration via code** and
describes it as a way to make behavior more deterministic and predictable in
speed, cost, and performance. Its examples include deterministic workflows.

Therefore ChainWeaver should not be adopted merely to prove that an OpenAI
agent can call deterministic Python.

Use normal Agents SDK orchestration when the sequence is already known and your
application can own it directly.

The possible ChainWeaver value is upstream of that execution decision:

```text
observed tool use
→ repeated candidate
→ evidence + counterexamples
→ safety/dataflow review
→ accepted deterministic capability
→ expose as an Agents SDK tool / callable
```

See the [OpenAI Agents SDK recipe](cookbook/openai-agents-tool.md).

Official references:

- [OpenAI Agents SDK: agent orchestration](https://openai.github.io/openai-agents-python/multi_agent/)
- [OpenAI Agents SDK examples](https://openai.github.io/openai-agents-python/examples/)

## LangChain

LangChain provides model/tool abstractions, agent loops, retrievers,
middleware, and composition primitives. It is a broader LLM application
framework, and modern LangChain agents run on LangGraph.

Use LangChain when the main problem is composing model-centric application
components or building an agent with its ecosystem.

If a region of the resulting tool behavior proves repetitive and no longer
needs model judgment, ChainWeaver can be evaluated as an analysis/governance
layer and deterministic capability behind that agent. It does not need to own
the outer loop.

Official reference:

- [LangChain agents](https://docs.langchain.com/oss/python/langchain/agents)

## Prefect and Dagster

Prefect and Dagster solve general workflow/data-orchestration jobs rather than
the same product problem ChainWeaver is testing.

Use them when you need things such as scheduling, operational orchestration,
worker infrastructure, data assets/lineage, recurring pipelines, or
organization-level workflow observability.

A ChainWeaver capability, if useful, belongs **inside** that larger job rather
than replacing the orchestrator.

References:

- [Prefect documentation](https://docs.prefect.io/)
- [Dagster documentation](https://docs.dagster.io/)

## Temporal

Temporal is a durable execution platform for workflows that must survive
process/worker failures and continue across long periods. That is a different
operational contract from ChainWeaver's embedded deterministic capability
runtime.

Use Temporal when durable business-workflow execution is the requirement. Do
not choose ChainWeaver as a smaller substitute for a requirement that actually
needs Temporal's execution model.

Reference:

- [Temporal documentation](https://docs.temporal.io/)

## MCP is not the comparison category

ChainWeaver can expose an accepted deterministic flow as an MCP tool and consume
MCP tools as execution steps. MCP is therefore an important interoperability
surface.

But "MCP workflow engine" is too broad a category claim. A company's most useful
compiled capability is often private and organization-specific. The value must
survive even when the outer host is LangGraph, the OpenAI Agents SDK, a custom
agent, or plain Python.

## Security is part of the comparison

A macro capability can be *less* safe than the original agent path if its
convenience silently aggregates child privileges or removes approval boundaries.

Current ChainWeaver has child safety/approval contracts and a macro-level
FlowServer authorization seam, but generic caller-specific child authorization
is still a v1 blocker. See
[Macro-capability security boundary](macro-capability-security.md) and
[#554](https://github.com/dgenio/ChainWeaver/issues/554).

Do not count "one tool call instead of several" as an advantage if the resulting
capability weakens the host's authorization model.

## A fair adoption rule

Choose ChainWeaver only if, on your workload, it demonstrates enough value over
the simplest existing alternative.

The project deliberately records these possible outcomes:

- **analysis + runtime are valuable** → continue the current combined product;
- **analysis is valuable, runtime is not** → lean toward analyzer/compiler +
  portable governed artifacts (#555);
- **runtime is valuable, trace discovery is not** → simplify toward a focused
  deterministic-flow library;
- **plain Python / current framework wins** → do not force ChainWeaver into the
  architecture;
- **security boundaries cannot be preserved** → reject the candidate.

Those are product results, not failures to be hidden.

## Updating this page

This document is a living comparison. Framework capabilities change quickly;
prefer their official documentation and update this page when a claim drifts.
Avoid feature-table claims whose truth depends on an old minor version when the
actual adoption decision is about product responsibility and lifecycle.
