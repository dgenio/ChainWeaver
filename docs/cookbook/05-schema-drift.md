# Recipe 5 — Detect schema drift in CI

**You have:** a registered flow that's been working for months. A teammate releases a
new version of one of its tools with a slightly different input schema.
**You want:** CI to fail before that change reaches production.

Paired script: `examples/cookbook/recipe_05_schema_drift.py`.

## The mechanism

Every `Tool` carries a `schema_hash` derived from its input + output schemas. Every
registered flow records the hashes its tools had **at registration time**. When the
runtime hashes diverge from the registered hashes, the executor surfaces a `DriftInfo`
entry.

Two complementary surfaces cover the case:

| Surface | When it runs | What it tells you |
|---|---|---|
| `check_flow_compatibility(flow, tools)` | Pure-static, no executor | "Can this flow run against these tools right now?" |
| `FlowExecutor.get_drift_report()` | After `register_tool` | "Has any registered flow's tool surface changed since registration?" |
| `chainweaver validate flow.yaml` | CLI | Wraps `check_flow_compatibility` for CI. |

## CI snippet

```yaml
# .github/workflows/flow-validation.yml
- name: Validate registered flows
  run: |
    chainweaver validate flows/*.flow.yaml --tools my_pkg.tools
    chainweaver check flows/ --tools my_pkg.tools
```

`chainweaver validate` exits with status 1 if any flow has unresolved tools, schema
mismatches between consecutive steps, or unresolved `input_mapping` references.

## Programmatic detection

```python
from chainweaver import check_flow_compatibility

issues = check_flow_compatibility(flow, {"fetch": fetch, "transform": transform})
if issues:
    for issue in issues:
        print(f"{issue.issue_type}: step={issue.step_index} {issue.detail}")
    raise SystemExit(1)
```

## Runtime detection

```python
executor.register_tool(updated_tool)   # same name, drifted schema
drift = executor.get_drift_report()
if drift:
    for entry in drift:
        log.warning(
            "flow=%s tool=%s expected=%s actual=%s",
            entry.flow_name,
            entry.tool_name,
            entry.expected_hash,
            entry.actual_hash,
        )
    raise RuntimeError("Schema drift detected — refusing to serve")
```

A flow only carries `tool_schema_hashes` once `executor.accept_drift(flow_name)` has
been called against the current tool registry. The first time round, treat this as
"baseline the schema fingerprints"; later, treat the same call as "accept this drift,
the change is intentional, restore the flow to `ACTIVE`".

```python
executor.accept_drift("my_flow")   # snapshot now-current hashes
```

For a freshly-registered flow with no baseline, `get_drift_report()` returns `[]` — it
has nothing to compare against.

## What next

- [Concepts → Schema validation](../concepts/schema-validation.md) — the precise
  mechanics of schema fingerprinting.
- [Data integrity guarantees](../data-integrity.md) — the formal properties drift
  detection preserves.
