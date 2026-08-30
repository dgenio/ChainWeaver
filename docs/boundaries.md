# When ChainWeaver fits

ChainWeaver is built for a narrower job than "run a deterministic workflow."
This page explains when it may earn a place in your architecture — and when the
simpler answer is a Python function or the workflow primitive you already have.

The primary product thesis is still being tested on independent workloads in
[#553](https://github.com/dgenio/ChainWeaver/issues/553). See
[Product validation & adoption gates](product-validation.md).

## Start with the simplest baseline

If you already know the exact path you want:

```python
def fetch_transform_store(url):
    data = fetch(url)
    records = transform(data)
    return store(records)
```

that may be the correct solution.

Deterministic execution is available in normal Python, LangGraph, provider SDKs,
and general workflow systems. ChainWeaver should add another dependency only
when its **discovery/evidence/governance lifecycle or execution contracts** solve
a problem you actually have.

## Evaluate ChainWeaver when

- **You have real agent/tool traces.** You suspect the agent repeatedly spends
  model turns navigating the same multi-tool plumbing, but you do not want to
  guess which regions are genuinely safe to compile.
- **You need evidence before promotion.** Recurrence, independent-session support,
  actual model-mediated boundaries, cumulative dataflow/schema compatibility,
  counterexamples, and rejection reasons matter.
- **Useful rejection matters as much as optimization.** You want the system to
  say "do not compile this path" when semantic judgment, unstable branching,
  side effects, missing evidence, or authorization/approval boundaries remain.
- **You want strict execution contracts after acceptance.** Tool inputs and
  outputs are Pydantic-validated, execution is structured and traceable, and
  schema/safety/policy drift can be detected around governed artifacts.
- **You need reviewable promotion rather than accidental automation.** A repeated
  sequence is a candidate, not authorization. Human review and explicit safety
  evidence remain part of the lifecycle.
- **You need to preserve security boundaries while reducing reasoning.** A macro
  capability must not silently aggregate child privileges or erase approval
  requirements. See [Macro-capability security boundary](macro-capability-security.md).
- **You want a capability to plug back into an existing host.** ChainWeaver can
  expose flows through MCP and framework adapters; #555 tests whether true
  runtime-independent exports become necessary based on user evidence.

## Prefer plain Python or your existing framework when

- **The workflow is already obvious and owned by humans.** If the engineering
  team already knows A → B → C and a normal function is easy to test and maintain,
  use it unless ChainWeaver's contracts/governance create a concrete benefit.
- **You do not need trace-derived discovery or evidence.** Adding a second
  abstraction solely to express a known sequence is usually unnecessary.
- **Your current framework already gives you the lifecycle you need.** LangGraph,
  the OpenAI Agents SDK, or your own application code can mix deterministic and
  model-mediated logic.

## Don't use ChainWeaver when

- **Every step requires open-ended reasoning.** If the next operation genuinely
  cannot be known until a model interprets new information, keep the model in
  the loop.
- **The plan changes dynamically based on semantic intent at every transition.**
  Do not compile away judgment just because the same tool names appear often.
- **You need a general durable/scheduled workflow platform.** Long-running jobs,
  timers, worker fleets, data assets, or organization-level workflow operations
  belong to systems such as Temporal, Prefect, Dagster, or the relevant host
  runtime.
- **You expect ChainWeaver to replace the outer agent framework.** It is designed
  to identify and execute bounded deterministic capabilities, not own every
  planning/conversation concern.
- **You cannot preserve child authorization/approval semantics.** Reject the
  candidate rather than wrapping it in a convenient macro.
- **Your trace privacy requirements cannot be represented safely.** Prefer local
  shape-only/minimized analysis; if even that is inappropriate, do not ingest
  the traces. See #527.
- **You need streaming model tokens.** ChainWeaver streams execution lifecycle
  events, not model output tokens.

## How ChainWeaver relates to neighbours

- **Agent frameworks** (LangGraph, LangChain agents, OpenAI/Anthropic tool-use
  loops): keep the outer reasoning/routing loop. ChainWeaver may analyze
  observed tool behavior and provide an accepted deterministic capability back
  to that host.
- **MCP**: supported interoperability surface. ChainWeaver can consume MCP tools
  and expose flows as MCP-callable tools; MCP is not the product category.
- **Workflow engines** (Prefect, Dagster, Temporal): different operational
  responsibility. A ChainWeaver capability, if useful, belongs inside the
  larger workflow rather than replacing it.
- **Plain Python**: the most important baseline. #553 explicitly compares accepted
  candidates against the practical manual implementation.

See [ChainWeaver vs agent and workflow frameworks](comparisons.md) for the fairer,
current comparison.

## A concrete contrast

A model-mediated path may look like:

```text
model → search → model → inspect → model → read CI → model → assemble context
```

The interesting ChainWeaver question is not simply whether this could be written
as:

```python
def collect_context(...):
    ...
```

Of course it could.

The product question is whether evidence from real executions can establish:

- the path actually recurs;
- those intermediate model turns are not contributing meaningful judgment;
- cumulative tool dataflow is stable;
- counterexamples do not invalidate the candidate;
- child side effects and approval/authorization boundaries remain safe;
- the lifecycle/audit/drift benefits justify ChainWeaver over the manual
  function.

Only then should the path become a governed deterministic capability.

## Reaching a verdict

Use the same decision rule the project applies to itself:

- if ChainWeaver changes a decision you would otherwise miss, or materially
  improves evidence/rejection/governance, that is a strong reason to adopt it;
- if the analyzer is valuable but the runtime is not, use that signal to favor
  portable outputs rather than forcing `FlowExecutor` everywhere;
- if the runtime is useful but trace discovery is not, treat ChainWeaver as a
  focused deterministic-flow library;
- if plain Python or your current framework is simpler and equally safe, use it;
- if compilation weakens security boundaries, do not compile the candidate.

Negative/no-benefit results are expected inputs to the product decision, not
failures to hide.
