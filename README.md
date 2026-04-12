# ChainWeaver

**Compile deterministic MCP tool chains into LLM-free executable flows.**

[![PyPI](https://img.shields.io/pypi/v/chainweaver)](https://pypi.org/project/chainweaver/)
[![CI](https://github.com/dgenio/ChainWeaver/actions/workflows/ci.yml/badge.svg)](https://github.com/dgenio/ChainWeaver/actions/workflows/ci.yml)
[![Python](https://img.shields.io/pypi/pyversions/chainweaver)](https://pypi.org/project/chainweaver/)
[![License](https://img.shields.io/github/license/dgenio/ChainWeaver)](LICENSE)

```mermaid
flowchart LR
    subgraph before ["❌ Naive Agent Chaining · N LLM calls"]
        R1([Request]) --> L1[LLM] --> T1[Tool A] --> L2[LLM] --> T2[Tool B] --> L3[LLM] --> T3[Tool C]
    end
    subgraph after ["✅ ChainWeaver · 0 LLM calls"]
        R2([Request]) --> E[FlowExecutor] --> U1[Tool A] --> U2[Tool B] --> U3[Tool C]
    end
```

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

**[Installation](#installation) · [Why ChainWeaver?](#why-chainweaver) · [Quick Start](#quick-start) · [Architecture](#architecture) · [Roadmap](#roadmap)**

---

## Why ChainWeaver?

When an LLM-powered agent chains tools together — `fetch_data → transform → store` — a
common pattern is to insert an LLM call between *every* step so the model can "decide"
what to do next.

```
User request
    │
    ▼
LLM call ──► Tool A
    │
    ▼
LLM call ──► Tool B
    │
    ▼
LLM call ──► Tool C
    │
    ▼
Response
```

For chains that are **fully deterministic** (the next step is always the same given the
previous output) these intermediate LLM calls add:

- **Latency** — each round-trip costs hundreds of milliseconds.
- **Cost** — every call consumes tokens and credits.
- **Unpredictability** — a language model might route differently on each invocation.

ChainWeaver compiles deterministic multi-tool chains into **executable flows** that run
without any LLM involvement between steps:

```
User request
    │
    ▼
FlowExecutor ──► Tool A ──► Tool B ──► Tool C
    │
    ▼
Response
```

Think of it as the difference between an **interpreter** and a **compiler**:

| Criterion | Naive LLM chaining | ChainWeaver |
|---|---|---|
| LLM calls per step | 1 per step | 0 |
| Latency | O(n × LLM RTT) | O(n × tool RTT) |
| Cost | O(n × token cost) | Fixed infra cost |
| Reproducibility | Non-deterministic | Deterministic |
| Schema validation | Ad-hoc / none | Pydantic enforced |
| Observability | Prompt logs only | Structured step logs |
| Reusability | Prompt templates | Registered, versioned flows |

---

## Installation

```bash
pip install chainweaver
```

---

## Quick Start

### Define tools, build a flow, and execute it

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
python examples/simple_linear_flow.py   # simple arithmetic chain
python examples/data_pipeline_flow.py   # ETL pipeline: fetch → validate → normalize → enrich → store
python examples/mcp_search_flow.py      # MCP-style search → extract → format
python examples/naive_vs_compiled.py    # timing comparison: naive LLM chaining vs ChainWeaver
```

### With the `@tool` decorator

The `@tool` decorator eliminates boilerplate by introspecting type hints to
auto-generate input schemas:

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
    description="Doubles a number, adds 10, and formats the result.",
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

---

## Architecture

```
chainweaver/
├── __init__.py       # Public API
├── decorators.py     # @tool decorator for zero-boilerplate tool definition
├── tools.py          # Tool — named callable with Pydantic schemas
├── flow.py           # FlowStep + Flow — ordered step definitions
├── registry.py       # FlowRegistry — in-memory flow catalogue
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
    input_mapping={"key_for_tool": "key_from_context"},
)
```

Maps keys from the accumulated execution context into the tool's input schema.
String values are looked up in the context; non-string values are treated as
literal constants.

#### `Flow`

```python
Flow(
    name="my_flow",
    description="...",
    steps=[step_a, step_b, step_c],
    deterministic=True,          # enforced by design
    trigger_conditions={"intent": "process data"},  # optional metadata
)
```

An ordered sequence of steps.

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
```

Runs a flow step-by-step with full schema validation and structured logging.
**No LLM calls are made at any point.**

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

ChainWeaver is designed to sit **between** an MCP server and your agent loop:

```
MCP Agent
   │  (observes tool call sequence at runtime)
   ▼
ChainWeaver FlowRegistry
   │  (matches pattern → retrieves compiled flow)
   ▼
FlowExecutor
   │  (runs deterministic steps without LLM involvement)
   ▼
MCP Tool Results
```

In practice:

1. An agent calls `tool_a`, then `tool_b`, then `tool_c` several times with
   the same routing logic.
2. A higher-level observer detects the pattern and registers a named `Flow`.
3. On subsequent invocations the executor runs the entire chain in a single
   call — no intermediate LLM calls required.

---

## Error Handling

All errors are typed and traceable:

| Exception | When it is raised |
|---|---|
| `ToolNotFoundError` | A step references an unregistered tool |
| `FlowNotFoundError` | The requested flow is not registered |
| `FlowAlreadyExistsError` | Registering a flow that already exists (without `overwrite=True`) |
| `SchemaValidationError` | Input or output fails Pydantic validation |
| `InputMappingError` | A mapping key is not present in the context |
| `FlowExecutionError` | The tool callable raises an unexpected exception |
| `ToolDefinitionError` | The `@tool` decorator cannot build a tool from a function |

All exceptions inherit from `ChainWeaverError`.

---

## Roadmap

### v0.1 — MVP (current)

- [x] `Tool` with Pydantic input/output schemas
- [x] `Flow` as an ordered list of `FlowStep` objects
- [x] `FlowRegistry` (in-memory)
- [x] `FlowExecutor` (sequential, LLM-free)
- [x] Structured per-step logging
- [x] Typed exceptions
- [x] Full test suite

### v0.2 — DAG & Branching

- [ ] DAG-based execution with dependency edges
- [ ] Parallel step groups
- [ ] Conditional branching inside flows

### v0.3 — Persistence & Learning

- [ ] JSON/YAML flow storage and reload
- [ ] Runtime chain observation (record ad-hoc tool sequences)
- [ ] Automatic flow suggestion from observed patterns

### v0.4 — Scoring & Observability

- [ ] Determinism scoring for partial flows
- [ ] OpenTelemetry trace export
- [ ] Async execution mode

---

## Development

```bash
# Install with dev dependencies
pip install -e ".[dev]"

# Run tests
pytest

# Run the examples
python examples/simple_linear_flow.py   # simple arithmetic chain
python examples/data_pipeline_flow.py   # ETL pipeline
python examples/mcp_search_flow.py      # MCP-style search & summarize
python examples/naive_vs_compiled.py    # naive vs compiled timing comparison
```

---

## License

This project is licensed under the Apache License 2.0 - see the [LICENSE](LICENSE) file for details.
