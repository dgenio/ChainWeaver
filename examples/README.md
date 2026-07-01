# ChainWeaver examples

Runnable, standalone scripts that demonstrate ChainWeaver's features. Every
script in this directory runs without a test framework and without live
external services:

```bash
pip install -e ".[dev]"      # from the repo root
python examples/simple_linear_flow.py
```

Some scripts need an optional extra (noted inline) — e.g. MCP examples need
`pip install 'chainweaver[mcp]'` and YAML flows need `chainweaver[yaml]`.

> This index is enforced by `tests/test_examples_index.py`: every
> `examples/*.py` script must appear below, so the list cannot silently rot.
> Several scripts have a narrated walkthrough under
> [`docs/cookbook/`](../docs/cookbook/index.md) — linked where one exists.

## Basics

| Script | What it shows |
|--------|---------------|
| [`simple_linear_flow.py`](simple_linear_flow.py) | A simple linear flow — the smallest end-to-end example. |
| [`etl_flow.py`](etl_flow.py) | An extract/transform/load-style flow. |
| [`builder_flow.py`](builder_flow.py) | Constructing a flow programmatically with `FlowBuilder`. |
| [`decorator_tool.py`](decorator_tool.py) | Defining a tool with the decorator API. |
| [`virtual_tool.py`](virtual_tool.py) | Flow-as-Tool: composing a flow so it can be used as a tool. |
| [`naive_vs_compiled.py`](naive_vs_compiled.py) | Naive LLM-in-the-loop vs. compiled-flow timing comparison ([cookbook](../docs/cookbook/01-naive-to-compiled.md)). |

## Caching & checkpointing

| Script | What it shows |
|--------|---------------|
| [`caching.py`](caching.py) | Step-result caching to skip recomputation. |
| [`checkpoint_resume.py`](checkpoint_resume.py) | Crash-resume checkpointing of a partially executed flow. |

## Streaming

| Script | What it shows |
|--------|---------------|
| [`streaming_flow.py`](streaming_flow.py) | Streaming per-step output as a flow executes. |

## Flow discovery & analysis (offline)

| Script | What it shows |
|--------|---------------|
| [`chain_analyzer.py`](chain_analyzer.py) | Discovering schema-compatible tool combinations offline with `ChainAnalyzer`. |
| [`chain_observer.py`](chain_observer.py) | Suggesting compiled flows from runtime tool traces with `ChainObserver`. |
| [`llm_flow_proposals.py`](llm_flow_proposals.py) | Proposing flows from tool metadata with an offline LLM ([cookbook](../docs/cookbook/offline-llm-flow-proposals.md)). |
| [`description_optimizer.py`](description_optimizer.py) | Rewriting tool descriptions for discriminability with an offline LLM ([cookbook](../docs/cookbook/offline-description-optimizer.md)). |

## Contrib tools

| Script | What it shows |
|--------|---------------|
| [`contrib_map_filter.py`](contrib_map_filter.py) | The `map_list` / `filter_list` contrib tools over sub-flows. |
| [`contrib_pluck_and_set.py`](contrib_pluck_and_set.py) | The `json_pluck` / `json_set` contrib tools. |

## MCP integration

| Script | What it shows |
|--------|---------------|
| [`mcp_adapter.py`](mcp_adapter.py) | Wrapping an inbound MCP tool with `MCPToolAdapter`. |
| [`mcp_flow_server.py`](mcp_flow_server.py) | Exposing flows over MCP with `FlowServer`. |
| [`mcp_search_flow.py`](mcp_search_flow.py) | An MCP-style search-and-summarize flow. |
| [`mcp_style_before_after_demo.py`](mcp_style_before_after_demo.py) | Before/after demo of an MCP-style tool flow ([cookbook](../docs/cookbook/mcp-before-after.md)). |

## Coding-agent workflows

| Script | What it shows |
|--------|---------------|
| [`coding_agent_pr_review.py`](coding_agent_pr_review.py) | Deterministic PR-review checklist template. |
| [`coding_agent_changelog.py`](coding_agent_changelog.py) | Deterministic changelog-generation template. |
| [`coding_agent_debug_log.py`](coding_agent_debug_log.py) | Deterministic debug-log triage template. |
| [`coding_agent_macro_flows.py`](coding_agent_macro_flows.py) | Realistic coding-agent macro-flow examples. |

## Cost & observability

| Script | What it shows |
|--------|---------------|
| [`otel_export.py`](otel_export.py) | Emitting OpenTelemetry spans per step ([cookbook](../docs/cookbook/03-otel-tracing.md)). |

## Export adapters

| Script | What it shows |
|--------|---------------|
| [`export_openai_anthropic.py`](export_openai_anthropic.py) | Exporting a compiled flow to OpenAI / Anthropic / generic-callable shapes. |

## Plugins

| Script | What it shows |
|--------|---------------|
| [`plugin_discovery.py`](plugin_discovery.py) | Entry-point plugin discovery. |

## Policy evaluation

| Script | What it shows |
|--------|---------------|
| [`skdr_policy_eval_flow.py`](skdr_policy_eval_flow.py) | Offline policy-evaluation workflow using skdr-eval artifacts ([cookbook](../docs/cookbook/policy-eval-skdr.md)). |

## Testing & fuzzing

| Script | What it shows |
|--------|---------------|
| [`fuzz_properties.py`](fuzz_properties.py) | A custom `FlowProperty` (`gracefully_handles_input`) used by the scheduled fuzz workflow (`.github/workflows/fuzz.yml`) against [`fuzzable_linear.flow.yaml`](fuzzable_linear.flow.yaml). |

## Multi-file examples

These live in their own subdirectories:

| Directory | What it shows |
|-----------|---------------|
| [`cookbook/`](cookbook/) | Numbered recipe scripts mirrored by [`docs/cookbook/`](../docs/cookbook/index.md). |
| [`integrations/`](integrations/) | Framework integration recipes ([LangGraph node](../docs/cookbook/langgraph-node.md), [OpenAI Agents tool](../docs/cookbook/openai-agents-tool.md)). |
| [`release_readiness_flow/`](release_readiness_flow/) | A release-readiness flow ([cookbook](../docs/cookbook/release-readiness.md)). |
| [`weaver_stack_golden_path/`](weaver_stack_golden_path/) | End-to-end Weaver Stack interop golden path. |
