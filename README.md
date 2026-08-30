# ChainWeaver

<!-- mcp-name: io.github.dgenio/chainweaver -->

**Find where your agent no longer needs to reason. Review the evidence. Turn the accepted path into a governed deterministic capability.**

[![PyPI](https://img.shields.io/pypi/v/chainweaver)](https://pypi.org/project/chainweaver/)
[![CI](https://github.com/dgenio/ChainWeaver/actions/workflows/ci.yml/badge.svg)](https://github.com/dgenio/ChainWeaver/actions/workflows/ci.yml)
[![Python](https://img.shields.io/pypi/pyversions/chainweaver)](https://pypi.org/project/chainweaver/)
[![License](https://img.shields.io/github/license/dgenio/ChainWeaver)](LICENSE)
[![Open in Colab](https://colab.research.google.com/assets/colab-badge.svg)](https://colab.research.google.com/github/dgenio/ChainWeaver/blob/main/notebooks/quickstart.ipynb)
[![Read the Weaver Stack overview on Towards AI](https://img.shields.io/badge/Read_the_overview-Towards_AI-black?logo=medium&logoColor=white)](https://pub.towardsai.net/the-weaver-stack-one-contract-layer-for-safe-llm-agents-7f733cad5eac)

<p align="center">
  <img src="docs/assets/quickstart.svg" alt="ChainWeaver quick start: pip install, run a flow, and see the LLM-free step log" width="760">
</p>

**Product thesis under validation — observe → prove → review → compile.**
ChainWeaver can inspect repeated tool behavior, surface candidates, and execute
reviewed deterministic paths with typed contracts. Deterministic execution by
itself is **not** the moat: if you already know the exact workflow, a normal
Python function, LangGraph node, or provider-native tool may be simpler. The
hypothesis being tested is that **trace-derived evidence, useful rejection,
governed promotion, security-boundary preservation, and drift detection** make
ChainWeaver worth adopting. See [Product validation & adoption
gates](docs/product-validation.md) and [#553](https://github.com/dgenio/ChainWeaver/issues/553).

**Remove reasoning boundaries, never security boundaries.** Compiling several
tool calls into one capability must not silently aggregate privileges or erase
child approval requirements. That invariant is tracked explicitly in
[#554](https://github.com/dgenio/ChainWeaver/issues/554).

**Governance for deterministic tool paths.** Typed I/O at every step,
file-serializable flows, schema-drift detection, determinism *attestation*,
property fuzzing, and structured audit traces provide a disciplined execution
substrate for paths that have actually earned deterministic promotion.

> **Benchmarks are evidence about the executor, not proof of product-market fit.**
> The repo's [benchmark report](benchmarks/results/latest.md) is reproducible —
> regenerate it yourself with `python benchmarks/report.py` — and shows the
> deterministic core avoiding model-mediated transitions in its synthetic
> comparison. It does **not** establish that every repeated path should
> be compiled, or that ChainWeaver beats the obvious plain-Python implementation.
> The independent validation program requires that manual baseline explicitly.

```python
from chainweaver import Tool, Flow, FlowStep, FlowRegistry, FlowExecutor
# (NumberInput, ValueOutput, double_fn defined in full example below)

# 1. Wrap any function as a schema-validated Tool
double = Tool(name="double", description="Doubles a number.",
              input_schema=NumberInput, output_schema=ValueOutput, fn=double_fn)
# 2. Wire tools into a Flow
flow = Flow(name="calc", description="Double a number.",
            steps=[FlowStep(tool_name="double", input_mapping={"number": "number"})])
# 3. Register and execute — zero LLM calls
registry = FlowRegistry()
registry.register_flow(flow)
executor = FlowExecutor(registry=registry)
executor.register_tool(double)
result = executor.execute_flow("calc", {"number": 5})
# result.final_output → {"number": 5, "value": 10}
```

> See the [full example](#quick-start) below or run `python examples/simple_linear_flow.py`

**[Installation](#installation) · [Why ChainWeaver?](#why-chainweaver) · [Is this for me?](#is-this-for-me) · [Product validation](docs/product-validation.md) · [Quick Start](#quick-start) · [Architecture](#architecture) · [Docs site](https://chainweaver.readthedocs.io/) · [Roadmap](#roadmap)**

---

## See it in 30 seconds

The deterministic executor solves a simple problem: once a path has been shown
to need no intermediate reasoning, stop paying a model to re-decide the same
plumbing on every run.

**Before — a model-mediated path:**

```
turn 1   ─►  LLM("plan")    ─►  search(query)         ─► 12 results
turn 2   ─►  LLM("next?")   ─►  extract(results)      ─► 8 facts
turn 3   ─►  LLM("next?")   ─►  validate(facts)       ─► 7 facts
turn 4   ─►  LLM("next?")   ─►  format(facts)         ─► answer
```

**After review — the accepted path can run deterministically:**

```
turn 1   ─►  LLM("plan")    ─►  search_summarize_flow(query)
                                  └─ search ─► extract ─► validate ─► format
```

The agent still decides *which* capability to invoke. The deterministic steps
inside it run with strict Pydantic validation and no LLM involvement.

The harder product question comes **before** this diagram: should this path be
compiled at all? A useful ChainWeaver analysis must be able to show why a
candidate is recurrent and structurally safe **and** reject paths where semantic
judgment, side effects, authorization, or approval boundaries still matter. That
claim is currently being tested on independent traces in #553.

**Copy-paste executor path:**

```bash
pip install 'chainweaver[yaml]'
python examples/simple_linear_flow.py
```

The summary below is a condensed view of the real `ExecutionResult` the script
produces:

```
flow=double_add_format success=True
final_output={'number': 5, 'value': 20, 'result': 'Final value: 20'}
step 0 double          {'value': 10}
step 1 add_ten         {'value': 20}
step 2 format_result   {'result': 'Final value: 20'}
```

---

## Why ChainWeaver?

### Why not just write a Python function?

Often, you should.

If your team already knows the workflow is fixed, a normal function or the
workflow primitives in your existing framework are usually the lowest-complexity
answer. ChainWeaver should earn another dependency only when its lifecycle adds
meaningful value—for example:

- discovering non-obvious repeated model-mediated paths from real traces;
- showing evidence for recurrence, dataflow compatibility, and counterexamples;
- rejecting tempting paths that still require semantic judgment;
- preserving approval and authorization constraints during promotion;
- producing reproducible review evidence and artifact identity;
- detecting schema/safety/policy drift after promotion;
- exporting or executing the accepted capability without pretending that fewer
  model calls automatically means greater correctness.

Whether those advantages are strong enough in real teams is a **falsifiable
product hypothesis**, not a README assumption. See
[docs/product-validation.md](docs/product-validation.md).

When an LLM-powered agent routes tools together — `fetch_data → transform → store` — a
common pattern is to insert an LLM call between steps so the model can decide
what to do next. For a path that has been **demonstrated and reviewed as fully
deterministic**, those intermediate calls can add latency, cost, and variability
without adding useful judgment.

ChainWeaver's executor can run an accepted deterministic path without any LLM
involvement between steps:

```
User request
    │
    ▼
FlowExecutor ──► Tool A ──► Tool B ──► Tool C
    │
    ▼
Response
```

| Criterion | Model-mediated path | ChainWeaver deterministic path |
|---|---|---|
| LLM calls between deterministic steps | potentially one or more | 0 |
| Reproducibility | depends on model decisions | deterministic path |
| Schema validation | framework/application dependent | Pydantic enforced |
| Observability | framework/application dependent | structured step logs |
| Reusability | application dependent | registered, versioned flows |

### How is this different from LangChain / LangGraph / Prefect / Dagster / Temporal?

Those frameworks can also execute deterministic code. ChainWeaver should **not**
be selected because deterministic execution is impossible elsewhere. Its current
product thesis is narrower: start from observed agent/tool behavior, establish
which regions no longer need reasoning, make the evidence and rejections
reviewable, then promote accepted paths into governed deterministic
capabilities.

The execution substrate remains deliberately small and LLM-free between steps,
but the project is testing whether the evidence/governance lifecycle—not the
mere existence of another workflow runtime—is the part users value.

See [docs/comparisons.md](docs/comparisons.md) for the detailed, versioned
comparison and [docs/product-validation.md](docs/product-validation.md) for the
criteria that can falsify this positioning.

---

## Is this for me?

ChainWeaver is built for one specific shape of problem. The
[full fit/non-fit page](https://chainweaver.readthedocs.io/en/latest/boundaries/) covers
the nuances; the short version:

**Use ChainWeaver when**

- You have real agent/tool traces and suspect parts of the path are repeated
  plumbing rather than useful model judgment.
- You want evidence and review around **which** paths deserve deterministic
  promotion, not only a runtime for a workflow you already know.
- Determinism, strict schemas, auditability, and drift detection matter once a
  path is promoted.
- You are prepared to keep security and approval boundaries explicit rather
  than treating a macro-tool invocation as blanket child authorization.

**Don't use ChainWeaver when**

- You already know the workflow and a normal Python function or your existing
  framework expresses it clearly enough.
- Every step requires open-ended reasoning to pick the next one (use an agent
  framework: LangGraph, the OpenAI / Anthropic SDK tool-use loops).
- You need a general workflow engine for scheduled / durable jobs across time
  (use Prefect, Dagster, or Temporal).
- You expect the executor to call an LLM. It deliberately doesn't.
- You cannot preserve the authorization/approval semantics of a side-effecting
  path during compilation.

The product thesis, validation protocol, and kill/pivot criteria are public in
[docs/product-validation.md](docs/product-validation.md).

For the correctness argument behind the deterministic execution design, see
[docs/data-integrity.md](docs/data-integrity.md).

### Part of the Weaver Stack

ChainWeaver is the **deterministic multi-step tool execution** layer of the
[Weaver Stack](https://github.com/dgenio/weaver-spec) — a family of small,
composable SDKs that share `weaver-spec`'s `SelectableItem` routing contract.
On the request path a router picks *which* capability to invoke, ChainWeaver
runs the deterministic tool path *behind* it, and downstream layers gate and
guard the call:

```mermaid
flowchart LR
    req([Request]) --> ctx[contextweaver<br/>context assembly]
    ctx --> cw[<b>ChainWeaver</b><br/>deterministic flow execution]
    cw --> ak[agent-kernel<br/>capability gating]
    ak --> af[agentfence<br/>runtime guardrails]
    subgraph adjacent [Adjacent · use any subset]
        vg[vibeguard]
        lw[lessonweaver]
        se[skdr-eval]
    end
```

**Use standalone or together.** Each layer stands on its own — ChainWeaver's
base install has **no hard dependency** on any sibling and works fully
standalone. Real interop runs through the `chainweaver[weaver-stack]` extra,
which pins the published [`weaver-contracts`](https://pypi.org/project/weaver-contracts/)
package: ChainWeaver consumes its `SelectableItem` / `RoutingDecision` /
`CapabilityToken` types directly, so a router can hand a routing decision
straight to `resolve_flow_from_routing_decision()` for deterministic
execution. See the runnable
[Weaver Stack golden path](examples/weaver_stack_golden_path/) (issue #234).

| Layer | What it owns | Sibling project |
|-------|--------------|-----------------|
| Routing / capability selection | "Which named operation handles this request?" | `weaver-spec` (#91 — `SelectableItem` contract) |
| Context assembly | "What facts and tool descriptions belong in the prompt?" | `contextweaver` (#106) |
| Agent kernel | The model-mediated tool-use loop itself | `agent-kernel` (#89) |
| **Deterministic flow execution** | "Run this exact tool sequence with strict schemas, no LLM between steps" | **ChainWeaver — this repo** |
| Lessons & evaluation | Turning traces into reviewed operational guidance ([how ChainWeaver feeds it](docs/lessons-from-traces.md)) | `lessonweaver` (#210) |

ChainWeaver does **not** replace an agent framework.  It is meant to be
called *from* one — see the [LangGraph
recipe](docs/cookbook/langgraph-node.md) (issue #205) and the [OpenAI Agents
SDK recipe](docs/cookbook/openai-agents-tool.md) (issue #206) for
the canonical integration patterns.

For host-level expectations (when to invoke, how to store traces,
side-effect tools, MCP parity), see the
[Runtime responsibilities](docs/runtime-responsibilities.md) page.

---

## Installation

```bash
pip install chainweaver                  # base install — no extras
pip install 'chainweaver[yaml]'          # most common — needed for .flow.yaml files
pip install 'chainweaver[yaml,otel,mcp]' # combine extras with commas
```

The base install pulls only five runtime dependencies (`deepdiff`,
`packaging`, `pydantic`, `tenacity`, `typer`) and has no transitive LLM
SDK pinned.  Pick extras for the integrations you actually use:

| Extra | Use when | Pulls in |
|-------|----------|----------|
| `chainweaver[yaml]` | Reading / writing `.flow.yaml` flow files (the CLI's `run`, `validate`, `check`, `doctor` commands need this) | `pyyaml` |
| `chainweaver[otel]` | Emitting OpenTelemetry spans for every flow run | `opentelemetry-api` |
| `chainweaver[mcp]` | Exposing flows over MCP via the `chainweaver.mcp` adapter | `mcp` |
| `chainweaver[contrib]` | Importing the curated standard tool library (see [Standard tool library](#standard-tool-library)) | *(no extra deps today)* |
| `chainweaver[langchain]` | Bidirectional adapters between ChainWeaver and LangChain `BaseTool` | `langchain-core` |
| `chainweaver[llamaindex]` | Bidirectional adapters between ChainWeaver and LlamaIndex `FunctionTool` | `llama-index-core` |
| `chainweaver[test]` | Hypothesis-based property tests for your own flows | `hypothesis`, `hypothesis-jsonschema` |
| `chainweaver[docs]` | Building the docs site locally with mkdocs | `mkdocs`, `mkdocs-material`, `mkdocstrings` |
| `chainweaver[weaver-stack]` | Real Weaver Stack interop — consuming the shared routing/capability contract (`weaver-spec` #91, `contextweaver` #106, `agent-kernel` #89, #233) | `weaver-contracts` |
| `chainweaver[integrations]` | Every integration extra above at once — the composition CI exercises | the union of the integration rows above |

Maintainer tooling (pytest, ruff, mypy, nbmake, ...) is **not** a published
extra: it lives in PEP 735 dependency groups, installed with
`pip install -e ".[integrations]" --group dev` (#550). The `[dev]` extra no
longer exists.

Package metadata (`pyproject.toml`) publishes URLs for the
[documentation](https://chainweaver.readthedocs.io/), the
[source](https://github.com/dgenio/ChainWeaver), the
[changelog](https://github.com/dgenio/ChainWeaver/blob/main/CHANGELOG.md),
and the
[issue tracker](https://github.com/dgenio/ChainWeaver/issues), so `pip
show chainweaver` and the PyPI sidebar point users to the right place.

---

## Quick Start

### Define tools, build a flow, and execute it

<!-- smoke-test: run -->
```python
from pydantic import BaseModel
from chainweaver import Tool, Flow, FlowStep, FlowRegistry, FlowExecutor

# --- 1. Declare schemas ---

class NumberInput(BaseModel):
    number: int

class ValueOutput(BaseModel):
    value: int

class ValueInput(BaseModel):
    value: int

class FormattedOutput(BaseModel):
    result: str

# --- 2. Implement tool functions ---

def double_fn(inp: NumberInput) -> dict:
    return {"value": inp.number * 2}

def add_ten_fn(inp: ValueInput) -> dict:
    return {"value": inp.value + 10}

def format_result_fn(inp: ValueInput) -> dict:
    return {"result": f"Final value: {inp.value}"}

# --- 3. Wrap as Tool objects ---

double_tool = Tool(
    name="double",
    description="Takes a number and returns its double.",
    input_schema=NumberInput,
    output_schema=ValueOutput,
    fn=double_fn,
)

add_ten_tool = Tool(
    name="add_ten",
    description="Takes a value and returns value + 10.",
    input_schema=ValueInput,
    output_schema=ValueOutput,
    fn=add_ten_fn,
)

format_tool = Tool(
    name="format_result",
    description="Formats a numeric value into a human-readable string.",
    input_schema=ValueInput,
    output_schema=FormattedOutput,
    fn=format_result_fn,
)

# --- 4. Define the flow ---

flow = Flow(
    name="double_add_format",
    description="Doubles a number, adds 10, and formats the result.",
    steps=[
        FlowStep(tool_name="double",        input_mapping={"number": "number"}),
        FlowStep(tool_name="add_ten",       input_mapping={"value": "value"}),
        FlowStep(tool_name="format_result", input_mapping={"value": "value"}),
    ],
)

# --- 5. Execute ---

registry = FlowRegistry()
registry.register_flow(flow)

executor = FlowExecutor(registry=registry)
executor.register_tool(double_tool)
executor.register_tool(add_ten_tool)
executor.register_tool(format_tool)

result = executor.execute_flow("double_add_format", {"number": 5})

print(result.success)       # True
print(result.final_output)  # {'number': 5, 'value': 20, 'result': 'Final value: 20'}

for record in result.execution_log:
    print(record.step_index, record.tool_name, record.outputs)
# 0 double {'value': 10}
# 1 add_ten {'value': 20}
# 2 format_result {'result': 'Final value: 20'}
```

You can also run the bundled examples directly:

```bash
python examples/simple_linear_flow.py   # simple arithmetic flow
python examples/etl_flow.py             # ETL flow: fetch → validate → normalize → enrich → store
python examples/mcp_search_flow.py      # MCP-style search → extract → format flow
python examples/naive_vs_compiled.py    # timing comparison: naive LLM calls vs ChainWeaver flow
python examples/coding_agent_pr_review.py    # deterministic PR-review checklist
python examples/coding_agent_changelog.py    # changelog generation workflow template
python examples/coding_agent_debug_log.py    # debug-log triage workflow template
python examples/mcp_style_before_after_demo.py        # before/after MCP-style flow demo
python examples/release_readiness_flow/release_readiness.py  # deterministic release-readiness gate
python examples/skdr_policy_eval_flow.py              # offline policy-evaluation workflow template
python examples/integrations/langgraph_node.py        # call a flow from a LangGraph node (needs chainweaver[langgraph])
python examples/integrations/openai_agents_tool.py    # expose a flow as an OpenAI Agents SDK tool (needs chainweaver[openai-agents])
```

The hosted docs also include a [cookbook](docs/cookbook/index.md) with paired
scripts under `examples/cookbook/`, plus framework recipes and workflow
templates (LangGraph, OpenAI Agents SDK, release-readiness, policy evaluation).

### With the `@tool` decorator

The `@tool` decorator eliminates boilerplate by introspecting type hints to
auto-generate input schemas:

<!-- smoke-test: run -->
```python
from pydantic import BaseModel
from chainweaver import tool, Flow, FlowStep, FlowRegistry, FlowExecutor

class ValueOutput(BaseModel):
    value: int

class FormattedOutput(BaseModel):
    result: str

@tool(description="Doubles a number.")
def double(number: int) -> ValueOutput:
    return {"value": number * 2}

@tool(description="Adds ten.")
def add_ten(value: int) -> ValueOutput:
    return {"value": value + 10}

@tool(description="Formats the result.")
def format_result(value: int) -> FormattedOutput:
    return {"result": f"Final value: {value}"}

flow = Flow(
    name="double_add_format",
    description="Doubles a number, adds 10, and formats.",
    steps=[
        FlowStep(tool_name="double",        input_mapping={"number": "number"}),
        FlowStep(tool_name="add_ten",       input_mapping={"value": "value"}),
        FlowStep(tool_name="format_result", input_mapping={"value": "value"}),
    ],
)

registry = FlowRegistry()
registry.register_flow(flow)

executor = FlowExecutor(registry=registry)
executor.register_tool(double)
executor.register_tool(add_ten)
executor.register_tool(format_result)

result = executor.execute_flow("double_add_format", {"number": 5})
print(result.final_output)  # {'number': 5, 'value': 20, 'result': 'Final value: 20'}
```

Decorated tools are also directly callable:

```python
print(double(number=5))  # {'value': 10}
```

See `examples/decorator_tool.py` for a runnable before/after comparison.

### With `FlowBuilder`

`FlowBuilder` provides a fluent, chainable API as a more Pythonic alternative
to constructing `Flow` objects directly.  It produces an identical `Flow` — it
is syntax sugar, not a replacement:

```python
from chainweaver import FlowBuilder

flow = (
    FlowBuilder("double_add_format", "Doubles a number, adds 10, and formats.")
    .step("double", number="number")
    .step("add_ten", value="value")
    .step("format_result", value="value")
    .build()
)
```

- **`.step(tool_name, **mapping)`** — adds a step; string values are context-key
  lookups, non-string values are literal constants, no kwargs = full-context
  passthrough.
- **`.step_from(flow_step)`** — appends a pre-built `FlowStep` for interop.
- **`.with_input_schema(Model)`** / **`.with_output_schema(Model)`** — optional
  flow-level Pydantic schema declarations.
- **`.with_trigger(conditions)`** — optional free-form trigger metadata.
- **`.build()`** — returns a validated `Flow`; raises `FlowBuilderError` if
  `name` or `description` is missing.

---

## Interactive playground

Want to try ChainWeaver without installing anything locally? The
[`playground/`](playground/) directory ships a Streamlit app that lets you pick
a pre-loaded flow, edit its JSON input, run it, and watch the step-by-step,
**LLM-free** execution trace with a Mermaid diagram — the same `FlowExecutor`
the library ships.

```bash
pip install -r playground/requirements.txt
streamlit run playground/app.py
```

It ships three example flows (arithmetic, a data flow, and an MCP-style
search), produces shareable `?share=<token>` links that round-trip a run through
the URL, and is fully stateless so it deploys to Streamlit Community Cloud with
no backend. See [`playground/README.md`](playground/README.md) for local-run and
deployment instructions.

---

## Architecture

```
chainweaver/
├── __init__.py       # Public API
├── builder.py        # FlowBuilder — fluent API for flow construction
├── compat.py         # schema_fingerprint, check_flow_compatibility
├── compiler.py       # compile_flow — static schema flow validation
├── decorators.py     # @tool decorator for zero-boilerplate tool definition
├── tools.py          # Tool — named callable with Pydantic schemas
├── flow.py           # FlowStep + Flow + FlowStatus — ordered step definitions
├── registry.py       # FlowRegistry — multi-version flow catalogue
├── executor.py       # FlowExecutor — deterministic, LLM-free runner
├── exceptions.py     # Typed exceptions with traceable context
└── log_utils.py      # Structured per-step logging
```

### Core abstractions

#### `Tool`

```python
Tool(
    name="my_tool",
    description="...",
    input_schema=MyInputModel,   # Pydantic BaseModel
    output_schema=MyOutputModel, # Pydantic BaseModel
    fn=my_callable,
)
```

A tool wraps a plain Python callable together with Pydantic models for strict
input/output validation.

#### `FlowStep`

```python
FlowStep(
    tool_name="my_tool",
    input_mapping={
        "key_for_tool": "key_from_context",   # flat top-level lookup
        "city": "/user/address/city",         # RFC-6901 pointer into nested context
        "limit": 10,                          # non-string -> literal constant
    },
    output_mapping={"renamed": "value"},      # rename/prune outputs before merge
)
```

`input_mapping` maps keys from the accumulated execution context into the
tool's input schema. String values are looked up in the context — a plain key
is a top-level lookup, and a string starting with `/` is an RFC-6901 JSON
pointer into the nested context (#387) — while non-string values are literal
constants.

`output_mapping` (#386) optionally renames and prunes a tool's outputs before
they merge into the context: `{context_key: output_key}` keeps only the listed
output keys, each renamed. Omit it to merge every output key verbatim.

To inject per-request secrets that must never appear in a model-visible schema
(auth tokens, account numbers), pass them at execute-time instead of in
`initial_input`:

```python
result = executor.execute_flow(
    "account_overview",
    {"query": "what's my balance?"},          # LLM-visible
    dynamic_params={"billingAccountNumber": "1.60007029"},  # hidden, injected (#316)
)
```

#### `Flow`

```python
Flow(
    name="my_flow",
    version="0.1.0",             # SemVer string; defaults to "0.1.0" if omitted
    description="...",
    steps=[step_a, step_b, step_c],
    deterministic=True,          # metadata annotation; executor is always LLM-free
    trigger_conditions={"intent": "process data"},  # optional metadata
)
```

An ordered sequence of steps. See [AGENTS.md](AGENTS.md) §5 for the full
field table (`status`, `tool_schema_hashes`, and the `input_schema_ref` /
`output_schema_ref` string fields with their resolved-property accessors).

A `FlowStep` runs **either** a tool (`tool_name`) **or** a registered
sub-flow (`flow_name`) — exactly one, never both. Referencing a sub-flow lets
you compose reusable flows (issue #75):

```python
fetch_validate = Flow(
    name="fetch_validate",
    description="Fetch and validate.",
    steps=[
        FlowStep(tool_name="fetch", input_mapping={"url": "url"}),
        FlowStep(tool_name="validate", input_mapping={"data": "data"}),
    ],
)
fetch_then_transform = Flow(
    name="fetch_then_transform",
    description="Reuse fetch_validate, then transform.",
    steps=[
        FlowStep(flow_name="fetch_validate", input_mapping={"url": "url"}),  # sub-flow
        FlowStep(tool_name="transform", input_mapping={"data": "data"}),
    ],
)
```

The executor runs the sub-flow with the step's resolved inputs, merges its
output back into the parent context, and attaches the sub-flow's
`ExecutionResult` to the parent `StepRecord.sub_result`. Sub-flow references
are checked for cycles and a configurable max nesting depth
(`FlowExecutor(max_composition_depth=...)`, default 10) before execution,
raising `FlowCompositionError` otherwise.

A `deadline` or `CancellationToken` passed to `execute_flow` is forwarded into
composed sub-flows, so cancellation and the wall-clock budget are observed at
the step boundaries *inside* a sub-flow — a long sub-flow stops between its own
steps rather than only at the parent boundary. The cost report's
`steps_executed` counts the tool invocations a composed step actually drove
(recursively), so `llm_calls_avoided` reflects every tool that ran across the
composition.

#### `FlowRegistry`

```python
registry = FlowRegistry()
registry.register_flow(flow)
registry.get_flow("my_flow")
registry.list_flows()
registry.match_flow_by_intent("process data")  # basic substring match
```

An in-memory catalogue of flows.

#### `FlowExecutor`

```python
executor = FlowExecutor(registry=registry)
executor.register_tool(tool_a)
result = executor.execute_flow("my_flow", {"key": "value"})

# Version-targeted execution: run an exact registered version instead of the
# latest. Omitting `version` keeps the default (latest) behaviour. The version
# that actually ran is always recorded on `result.flow_version`, so routing,
# audit, and replay can correlate a result with the precise flow definition.
result = executor.execute_flow("my_flow", {"key": "value"}, version="1.2.0")
assert result.flow_version == "1.2.0"
```

Runs a flow step-by-step with full schema validation and structured logging.
**No LLM calls are made at any point.**

#### `ChainAnalyzer`

```python
from chainweaver import ChainAnalyzer, ToolChain

analyzer = ChainAnalyzer(tools=[tool_a, tool_b, tool_c])

# All schema-compatible pairs
matrix: dict[str, list[str]] = analyzer.compatibility_matrix()

# All valid tool sequences up to length 3
chains: list[ToolChain] = analyzer.find_chains(max_depth=3)

# Filter by start or end tool
chains = analyzer.find_chains(max_depth=3, start="tool_a", end="tool_c")

# Promote chains to ready-to-register Flow objects
flows = analyzer.suggest_flows(max_depth=3, min_depth=2)
```

Discovers schema-compatible tool combinations **offline**, before any flow is
registered or executed. `compatibility_matrix()` checks that every required
input field of a consumer tool appears in the output of the producer with a
matching type. `suggest_flows()` auto-wires `input_mapping` by name-matching
and returns `Flow` objects ready for `FlowRegistry.register_flow()`.

### Data flow

```
initial_input (dict)
       │
       ▼
 ┌─────────────────────────────────────────────┐
 │  Execution context (cumulative dict)        │
 │                                             │
 │  Step 0: resolve inputs → run tool → merge  │
 │  Step 1: resolve inputs → run tool → merge  │
 │  Step N: resolve inputs → run tool → merge  │
 └─────────────────────────────────────────────┘
       │
       ▼
 ExecutionResult.final_output (merged context)
```

---

## MCP Integration Concept

ChainWeaver can sit between agent/tool observation and deterministic execution:

```
Agent / tool traces
   │  (observe repeated paths)
   ▼
Candidate analysis + human review
   │  (prove/reject; preserve security boundaries)
   ▼
Governed deterministic capability
   │  (FlowExecutor and/or supported export)
   ▼
MCP / host-framework invocation
```

MCP is an interoperability surface, not the product category. The current
runtime can expose reviewed flows as MCP tools, while #555 explores whether
portable outputs should let the same approved capability execute through other
hosts without requiring ChainWeaver to own the runtime.

ChainWeaver is **a library you embed**, not the runtime that owns your trace
store, identity system, or enterprise authorization control plane. Host authors
should read [`docs/runtime-responsibilities.md`](docs/runtime-responsibilities.md).

---

## Integrations

ChainWeaver plugs into the MCP ecosystem and major agent frameworks. Existing
integrations remain supported; new adapter breadth is deliberately lower
priority than independent product validation.

| Integration | What it does | Entry point |
|---|---|---|
| **MCP server** (outbound) | Expose your flows as MCP tools — agents call a whole compiled flow as one deterministic tool | [`chainweaver serve`](docs/cli.md) · [guide](docs/mcp-server.md) · [`FlowServer`](chainweaver/mcp/server.py) |
| **MCP adapter** (inbound) | Wrap tools advertised by an MCP server as ChainWeaver `Tool`s | `chainweaver.mcp.MCPToolAdapter` |
| **LangGraph** | Call a flow from a LangGraph node | [recipe](docs/cookbook/langgraph-node.md) · `examples/integrations/langgraph_node.py` |
| **OpenAI Agents SDK** | Expose a flow as an Agents SDK `FunctionTool` | [recipe](docs/cookbook/openai-agents-tool.md) · `examples/integrations/openai_agents_tool.py` |
| **LangChain / LlamaIndex** | Bidirectional tool bridges | `chainweaver.integrations.{langchain,llamaindex}` (see below) |
| **OpenCode** | Observe tool runs, mine macro-flows, and expose reviewed flows back as MCP tools | [recipe](docs/cookbook/opencode-recipe.md) · [`chainweaver opencode`](chainweaver/cli/opencode.py) |
| **Claude Code** | Capture `PostToolUse` hook traces, mine macro-flows, and expose reviewed flows back as MCP tools | [recipe](docs/cookbook/claude-code-recipe.md) · [`chainweaver claude`](chainweaver/cli/claude.py) |
| **VS Code / Copilot** | Capture MCP tool traces (Copilot OTel) and expose reviewed flows via `.vscode/mcp.json` | [recipe](docs/cookbook/vscode-recipe.md) · [`chainweaver vscode`](chainweaver/cli/vscode.py) |
| **GitHub Action** | Validate `.flow.yaml` / `.flow.json` files in CI with inline PR annotations | [`.github/actions/chainweaver`](.github/actions/chainweaver) · [guide](docs/github-action.md) |

Install the extra you need: `pip install 'chainweaver[mcp]'` (or `langgraph`,
`openai-agents`, `langchain`, `llamaindex`). Importing any integration without its
extra raises a clear `ImportError`.

Looking to publish or list ChainWeaver in the MCP registry / awesome-lists / framework
directories? See [`docs/distribution.md`](docs/distribution.md). Broad distribution
is intentionally gated behind the naming decision (#556) and validation evidence
(#553).

---

## Error Handling

All errors are typed and traceable:

| Exception | When it is raised |
|---|---|
| `ToolNotFoundError` | A step references an unregistered tool |
| `FlowNotFoundError` | The requested flow is not registered |
| `FlowAlreadyExistsError` | Registering a flow that already exists (without `overwrite=True`) |
| `FlowStatusError` | Executing a flow whose status is not `ACTIVE` (without `force=True`) |
| `FlowCancelledError` | A `deadline` passed or a `CancellationToken` was cancelled at a step boundary (carries the partial result) |
| `InvalidFlowVersionError` | A flow is registered with a version string that is not valid PEP 440 |
| `FlowSerializationError` | A flow file (YAML/JSON) is malformed, has an unknown discriminator, or references an unresolvable class |
| `SchemaValidationError` | Input or output fails Pydantic validation |
| `InputMappingError` | A mapping key is not present in the context |
| `FlowExecutionError` | The tool callable raises an unexpected exception |
| `ApprovalDeniedError` | An execution-time approval callback denied a step, raised, or returned an invalid value — or `strict_safety=True` and a required-approval step has no callback |
| `SafetyCeilingError` | A step's `ToolSafetyContract.side_effects` exceeds the executor's configured `max_side_effect_level` |
| `GuardrailViolationError` | A registered `guardrail_callback` blocked a step at the input stage (content-safety / injection check) |
| `ToolDefinitionError` | The `@tool` decorator cannot build a tool from a function |
| `DAGDefinitionError` | A `DAGFlow` has a cycle, duplicate `step_id`, or unknown dependency |
| `FlowCompositionError` | A composed flow has a sub-flow cycle, exceeds `max_composition_depth`, or references an unregistered sub-flow |
| `ToolTimeoutError` | A `Tool` with `timeout_seconds` set exceeds the configured wall-clock cap |
| `ToolOutputSizeError` | A `Tool` with `max_output_size` set returns an output larger than the configured cap |
| `FlowBuilderError` | `FlowBuilder.build()` is called without a name or description |
| `AttestationInputError` | The attestation input generator cannot synthesize a value for a schema field |
| `PluginDiscoveryError` | Strict-mode plugin discovery (`discover_tools(strict=True)` / `discover_flows(strict=True)`) hits a misbehaving entry-point loader |
| `ContribError` | A `chainweaver.contrib.tools` tool hits a contract violation (missing JSON-pointer key, wrong predicate shape, assertion mismatch) |
| `FixtureStaleError` | A `record_then_replay` replay invocation cannot be matched to a recording (missing/stale fixture) |
| `FuzzConfigError` | A property-based fuzzing run is misconfigured (no properties, `runs < 1`, a flow with no `input_schema` and no base input, or an unsupported input-field type) |
| `CostProfileError` | A cost estimate is requested for a `(provider, model)` pair absent from the maintained `PROVIDER_PRICES` table |
| `MCPMetadataError` | A server-provided MCP tool name fails the adapter's `MetadataPolicy` (and `on_invalid_name="error"`) |
| `MCPSchemaDriftError` | A pinned MCP tool's raw schema changed under `MCPToolAdapter(on_drift="error")` |
| `FlowAuthenticationError` | A network-exposed `FlowServer` authenticator returned `None` or raised; the call is refused before dispatch |
| `RateLimitExceededError` | A `FlowServer` rate limiter declined the call |
| `FlowAuthorizationError` | A `FlowServer` authorization callback denied the call (carries only a client-safe `reason_code`) |
| `CheckpointVersionError` | A resumed snapshot's `snapshot_version` is an incompatible MAJOR relative to the running library |

All exceptions inherit from `ChainWeaverError` and carry a stable diagnostic
`code` (e.g. `CW-E006`); the CLI prefixes it on error output and failing
`StepRecord`s expose it as `error_code`. See the full code table in
[docs/reference/error-table.md](docs/reference/error-table.md#stable-diagnostic-codes).

---

## Standard tool library

`chainweaver.contrib.tools` ships a curated set of deterministic
utility tools so that a new user can compose a meaningful flow on the
first afternoon without writing any `Tool` boilerplate.

```python
from chainweaver.contrib.tools import (
    assert_equal,
    filter_list,
    json_pluck,
    json_set,
    map_list,
    passthrough,
)
```

| Tool | Purpose |
|------|---------|
| `passthrough` | Identity — return the context unchanged. |
| `json_pluck` | Extract one value by RFC-6901 JSON pointer. |
| `json_set` | Set one value by RFC-6901 JSON pointer; returns a new dict. |
| `assert_equal` | Raise `ContribError` when two context keys differ. |
| `map_list` | Apply a registered sub-flow to each element of a list. |
| `filter_list` | Drop elements whose predicate sub-flow returns falsy. |

The library is **deterministic-only**: no HTTP, file I/O, database
access, RNG, or clocks.  Anything stateful belongs in user code.
Install with `pip install 'chainweaver[contrib]'`.

Runnable examples: [`examples/contrib_pluck_and_set.py`](examples/contrib_pluck_and_set.py),
[`examples/contrib_map_filter.py`](examples/contrib_map_filter.py).

---

## Cost-avoided reporting

Every inter-step transition a naive agent delegates to an LLM is a routing
call ChainWeaver eliminates. `CostProfile` / `CostReport` turn that into a
dollar estimate, and the maintained `PROVIDER_PRICES` table (dated snapshots,
no live HTTP lookup) lets you price it against a real model:

```python
from chainweaver.cost import compute_cost_report

# Build a profile straight from the maintained price table.
report = compute_cost_report(
    steps_executed=6,                 # a six-tool flow
    actual_execution_ms=4.2,
    provider="anthropic",
    model="claude-opus-4-7",
)
print(report)
```

```text
Cost Avoided Report (estimate)
──────────────────────────────
Steps executed:          6
LLM calls avoided:       5
Est. latency saved:      1500.0ms
Est. cost saved:         $0.1688
Actual execution time:   4.2ms
Priced against:          anthropic/claude-opus-4-7 (as of 2026-05-01)
```

Every report built from the table carries the snapshot's `as_of` date so
stale prices are visible. Unknown `(provider, model)` pairs raise
`CostProfileError` rather than guessing. Pass an explicit
`profile=CostProfile(...)` when you have better per-call numbers, or set
`cost_profile=` on `FlowExecutor` to attach a report to every
`ExecutionResult`. Prices are refreshed by a maintainer-reviewed PR
(`.github/workflows/update-prices.yml`) — never auto-merged.

These reports are **estimates** unless their inputs come from observed trace
measurements. They must not be presented as evidence that a candidate should be
compiled; #377 tracks calibration of assumed versus measured model mediation.

---

## Export adapters

Hand a compiled flow off to any external agent framework via
`chainweaver.export`:

```python
from chainweaver.export import (
    flow_to_anthropic_tool,
    flow_to_callable,
    flow_to_openai_function,
)

openai_spec = flow_to_openai_function(flow, executor)
anthropic_spec = flow_to_anthropic_tool(flow, executor)
run = flow_to_callable(flow, executor)  # plain dict → dict callable
```

`flow_to_openai_function` emits the
`{"type": "function", "function": {…}}` shape OpenAI's chat / responses
APIs expect.  `flow_to_anthropic_tool` emits Anthropic's `tool_use`
shape.  `flow_to_callable` wraps the flow as a `Callable[[dict], dict]`
suitable for any framework that accepts arbitrary Python callables.

None of these adapters imports `openai` or `anthropic` — they emit
dicts and callables only.  Runtime integration with those clients is
the caller's job.

Runnable example: [`examples/export_openai_anthropic.py`](examples/export_openai_anthropic.py).

---

## Ecosystem bridges (LangChain, LlamaIndex)

`chainweaver.integrations.langchain` and
`chainweaver.integrations.llamaindex` ship thin bidirectional adapters
so existing LangChain `BaseTool` / LlamaIndex `FunctionTool`
instances can be pulled into ChainWeaver, and ChainWeaver `Tool`
instances can be pushed back out.

```python
from chainweaver.integrations.langchain import (
    from_langchain_tool,
    to_langchain_tool,
)

cw_tool = from_langchain_tool(my_langchain_tool)
lc_tool = to_langchain_tool(my_cw_tool)
```

Install with `pip install 'chainweaver[langchain]'` /
`'chainweaver[llamaindex]'`.  Importing either module without the
relevant extra raises a clear `ImportError`.

---

## Plugin discovery

For third-party packages — `chainweaver-aws`, `chainweaver-stripe`,
… — ChainWeaver follows the same entry-point convention used by
pytest, Sphinx, MkDocs, and friends.

Publisher (`pyproject.toml`):

```toml
[project.entry-points."chainweaver.tools"]
aws = "chainweaver_aws:get_tools"

[project.entry-points."chainweaver.flows"]
aws = "chainweaver_aws:get_flows"
```

Consumer:

```python
from chainweaver import FlowExecutor, FlowRegistry

# Auto-register every tool / flow advertised by an installed plugin.
registry = FlowRegistry(discover_plugins=True)
executor = FlowExecutor(registry=registry, discover_plugins=True)
```

Discovery is **opt-in** — importing `chainweaver` does not trigger
plugin imports.  Misbehaving plugins (raise on import, return the
wrong type) are logged at `WARNING` and skipped; pass
`strict=True` to `discover_tools()` / `discover_flows()` for the loud
form.

Runnable example: [`examples/plugin_discovery.py`](examples/plugin_discovery.py).

---

## Runtime learning

ChainWeaver can watch what an agent does and **propose** deterministic-flow
candidates for repeated paths. A repeated sequence is not proof that the path
is safe or valuable to compile; proposals require review, and the product
validation program is explicitly measuring false positives, false negatives,
and useful rejections.

```python
from chainweaver import ChainObserver, FlowRegistry

observer = ChainObserver()

# Record tool calls as the agent makes them.
observer.record("fetch", {"url": "..."}, {"body": "..."})
observer.record("validate", {"body": "..."}, {"valid": True})
observer.record("transform", {"body": "..."}, {"records": [1, 2, 3]})
observer.end_trace()
# ... many traces later ...

registry = FlowRegistry()
for suggestion in observer.suggest_flows(min_occurrences=3):
    # Suggestions are proposals — review; never treat confidence as authorization.
    print(suggestion.flow.name, suggestion.confidence,
          suggestion.estimated_llm_calls_avoided)
    registry.register_flow(suggestion.flow)
```

- **`ChainObserver`** (#78) mines repeated tool sequences from runtime traces and
  emits ranked `FlowSuggestion`s — never auto-registered.
- **`chainweaver record`** (#226) mines recorded JSONL traces and writes candidate
  flow files for explicit review/promotion.
- **`ChainWeaverService`** (#101) ties observation, static analysis, and optional
  offline proposals into an *analyze → propose → govern → promote* loop.

See [Product validation & adoption gates](docs/product-validation.md) before
interpreting a suggestion as proof that a path should become deterministic.

---

## Roadmap

The current roadmap is **validation-first**, not feature-count-first. The latest
published release is `v0.14.1`; newer work on `main` remains unreleased until a
subsequent release is cut.

| Priority | Work | Why |
|---|---|---|
| **P0** | [#553 independent product falsification](https://github.com/dgenio/ChainWeaver/issues/553) | Establish whether trace-derived discovery/governance beats human inspection + a plain-function baseline. |
| **P0** | [#554 authorization/approval preservation](https://github.com/dgenio/ChainWeaver/issues/554) | Compilation may remove reasoning boundaries, never silently security boundaries. |
| **P0** | [#522 stable/supported/experimental API tiers](https://github.com/dgenio/ChainWeaver/issues/522) | Keep the compatibility promise smaller than the implementation surface. |
| **P0** | [#519 release coherence](https://github.com/dgenio/ChainWeaver/issues/519) | Source, package, tag, release, docs, and artifacts must agree. |
| **P1** | [#527 privacy profiles](https://github.com/dgenio/ChainWeaver/issues/527) | Trace analysis must work with minimized/local evidence. |
| **Gate on #553** | [#334 canonical evidence architecture](https://github.com/dgenio/ChainWeaver/issues/334) | Build the large lifecycle model only after users validate the job. |
| **Gate on #553** | [#498 production golden path](https://github.com/dgenio/ChainWeaver/issues/498) | Turn validated needs into one canonical end-to-end proof. |
| **Explore if demanded** | [#555 portable compiled capabilities](https://github.com/dgenio/ChainWeaver/issues/555) | If users value analysis but not `FlowExecutor`, make the accepted artifact portable. |
| **Before broad distribution** | [#556 naming/search decision](https://github.com/dgenio/ChainWeaver/issues/556) | Resolve discoverability/ambiguity while migration is still cheap. |

Broad directory submissions, hosted-playground investment, and additional
framework-adapter breadth are deliberately lower priority until these gates
produce evidence.

`v1.0.0` is also evidence-gated: independent workloads/adopters, a manual
baseline, an external security review, repeated use, a downstream integration,
and a 30-day RC compatibility soak are required by
[docs/v1-release-criteria.md](docs/v1-release-criteria.md).

---

## Command-line interface

ChainWeaver ships a `chainweaver` console script with the following subcommands.
Reading `.flow.yaml` files needs the YAML extra
(`pip install 'chainweaver[yaml]'` — also listed in [Installation](#installation)).
The `run` example below uses a flow shipped under `examples/`, so it should be
invoked from the repository root.

```bash
# Run a flow from disk — no Python required.
chainweaver run examples/double_add_format.flow.yaml \
    --tools examples.simple_linear_flow \
    --input '{"number": 5}'

# Serve a flow as MCP tools (needs chainweaver[mcp]) — agents call the whole
# compiled flow as one deterministic tool. See docs/mcp-server.md.
chainweaver serve examples/double_add_format.flow.yaml \
    --tools examples.simple_linear_flow

# Validate a flow file (used by CI gates and editor tooling).
chainweaver validate flows/etl.flow.yaml
chainweaver check flows/                  # whole-directory variant

# Scaffold a runnable first flow project (tools + flow file + run script).
chainweaver init my-first-flow --template linear --with-tests

# Render a flow as ASCII, Graphviz DOT, or Mermaid. Discover it from a directory
# of flow files, an installed package's entry points, or the default registry.
chainweaver viz my_flow --discover-dir flows/ --format dot | dot -Tpng -o my_flow.png
chainweaver viz my_flow --discover-dir flows/ --format mermaid
chainweaver viz --result trace.json --format mermaid   # overlay a real run

# Explain a flow deterministically (LLM-free) for review — paste into a PR.
chainweaver explain my_flow --discover-dir flows/ > flow-review.md

# Inspect a flow's structure (table or JSON). `flows list` previews what is
# discoverable so you can see what `inspect`/`viz` can target.
chainweaver inspect my_flow --discover-dir flows/ --format json
chainweaver flows list --discover-dir flows/

# Check that your environment is ready before running anything.
chainweaver doctor flow --profile first-run

# Inspect a coding-agent workspace's MCP / observe setup (read-only).
chainweaver doctor vscode --workspace .

# Install tab-completion for your shell (bash/zsh/fish).
chainweaver --install-completion

# Analyze ExecutionResult traces — bottlenecks, p50/p95/p99 across runs,
# and per-step / per-tool retry / skip / fallback / failure aggregates.
chainweaver profile trace_a.json trace_b.json --format json

# Compare two ExecutionResult JSON files step-by-step.
chainweaver diff baseline.json current.json --perf-tolerance 25

# Observed-determinism attestation: run N inputs × M repeats.
chainweaver attest flows/etl.flow.yaml --tools my_pkg.tools --runs 50 --repeats 3

# Advisory optimization suggestions for a saved flow.
chainweaver suggest flows/etl.flow.yaml --tools my_pkg.tools --trace trace_a.json

# Mine candidate flows from a recorded JSONL tool trace (offline, no LLM).
chainweaver record examples/agent_tool_trace.jsonl --output-dir candidates/
chainweaver flows promote candidates/suggested__fetch__validate.flow.yaml --to reviewed
chainweaver flows promote candidates/suggested__fetch__validate.flow.yaml --to active

# Run one continuous-analysis service pass and report flow proposals.
chainweaver service --tools my_pkg.tools --trace trace.jsonl

# Check saved flows for tool schema drift against the live registry.
chainweaver doctor flow flows/ --check-drift --tools my_pkg.tools

# Property-based fuzzing: generate cases, check invariants, save/minimize failures.
chainweaver fuzz flows/etl.flow.yaml --tools my_pkg.tools \
  --property my_pkg.props:no_unauthorized_action --runs 1000 --seed 42 \
  --minimize --save-failures failures/
```

`run` is the fastest path from a fresh install to seeing a flow execute:
point it at a `.flow.yaml`/`.flow.json` file, pass `--tools <module>` (the
import path of a Python module that exposes `Tool` instances at top
level), and supply the initial input as JSON. Hand-authored flow files must
declare a `type: Flow` (or `type: DAGFlow`) discriminator at the top — see
the [flow file format](docs/cli.md#flow-file-format) reference. Most
reporting subcommands also accept `--format json` for machine consumption
(`inspect`, `validate`, `check`, `run`, `profile`, `diff`, `attest`,
`suggest`, `doctor`); the exceptions are `viz`, which uses
`--format ascii|dot|mermaid`, `explain`, which uses `--format md|text`, and
`dump-schema`, which writes a raw JSON Schema and has no `--format` flag. The result-producing commands (`inspect`,
`validate`, `check`, `profile`, `diff`, `attest`) wrap their `--format json`
output in a stable, versioned envelope
(`{"schema_version", "status", "data", "errors"}`) so automation can branch on
`status` / error codes — see
[machine-readable output](docs/cli.md#machine-readable-output---format-json).
All subcommands share the same exit-code contract (`0` success, `1`
business-logic error, `2` file-not-found / argument error), and the CLI ships
tab-completion (`chainweaver --install-completion`).

**`inspect` and `viz` resolve flows from disk or a registry.**
Pass `--file <path>`, `--discover-dir <dir>`, or `--discover-entry-points` to
resolve a flow without writing any Python (issue #381); `chainweaver flows
list` previews what is discoverable. With no discovery flag they fall back to a
process-scoped, in-memory registry installed programmatically — running
`chainweaver inspect my_flow` with neither a flag nor a configured registry
exits `1` with `No registry configured. Call
chainweaver.cli.set_default_registry(...) before invoking the CLI.`. To wire
the default-registry path, use a small entry script:

```python
# my_cli_entry.py
from chainweaver import FlowRegistry
from chainweaver.cli import main, set_default_registry
from my_app import build_registry  # returns a populated FlowRegistry

set_default_registry(build_registry())
main()
```

See [`docs/cli.md` § Programmatic registration](docs/cli.md#programmatic-registration-inspect-viz)
for the full pattern, including why the split exists (file-oriented
commands stay zero-config, registry-oriented commands stay
introspection-friendly).

---

## Development

New contributors: see [**Your first contribution**](CONTRIBUTING.md#your-first-contribution)
in `CONTRIBUTING.md` for the `good-first-issue` / `good-first-ai-issue` onramp
and the step-by-step path to your first PR.

```bash
# Install with the integration extras and the maintainer tooling group
pip install --upgrade pip          # --group needs pip >= 25.1
pip install -e ".[integrations]" --group dev

# Run tests
python -m pytest tests/ -v

# Run the examples
python examples/simple_linear_flow.py   # simple arithmetic flow
python examples/etl_flow.py             # ETL flow
python examples/mcp_search_flow.py      # MCP-style search & summarize flow
python examples/naive_vs_compiled.py    # naive vs compiled timing comparison
python examples/coding_agent_pr_review.py
python examples/coding_agent_changelog.py
python examples/coding_agent_debug_log.py
```

---

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.
