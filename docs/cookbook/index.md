# Cookbook

Six runnable recipes for the patterns that come up over and over. Each recipe is a
narrative page plus a paired script under `examples/cookbook/`. The scripts run cleanly
from a fresh checkout — `python examples/cookbook/recipe_01_naive_to_compiled.py` (for
example) executes the recipe end-to-end and asserts its own output.

| # | Recipe | What you'll build |
|---|---|---|
| 1 | [Naive LLM loop → compiled flow](01-naive-to-compiled.md) | Convert a prompt-routed agent loop into a deterministic compiled flow. |
| 2 | [MCP-style search and summarize](02-mcp-style-flow.md) | Wire two MCP-shaped tools (search and summarise) into one flow. |
| 3 | [OpenTelemetry tracing](03-otel-tracing.md) | Emit one parent flow span plus one child span per step using `chainweaver[otel]`. |
| 4 | [Testing flows](04-testing-flows.md) | Use vanilla pytest fixtures to test flow construction and execution. |
| 5 | [Schema drift in CI](05-schema-drift.md) | Detect when a tool's schema changes underneath a registered flow. |
| 6 | [Fan-out / fan-in DAG patterns](06-dag-fanout.md) | Build a `DAGFlow` that pulls from two sources in parallel and merges. |

## Conventions used in the cookbook

- All recipes follow the **standalone-script rule** for `examples/`: no pytest imports,
  no fixtures. Smoke-checking happens inline with `assert`.
- Recipes pin to `chainweaver>=0.8,<1.0` in their intro; bump the pin when the public
  API changes.
- Diagrams use Mermaid, which renders both in this site and on GitHub.
- Each recipe ends with **What next** — usually pointing into the
  [Concepts](../concepts/tools-and-flows.md) section.

## Running every recipe

```bash
for f in examples/cookbook/recipe_*.py; do
    echo "--- $f"
    python "$f" || break
done
```

A clean exit on every script means the cookbook is in sync with the current public API.
