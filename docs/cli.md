# ChainWeaver CLI Reference

ChainWeaver ships a `chainweaver` console script built on [typer](https://typer.tiangolo.com/).

```
chainweaver <command> [options]
```

---

## Exit codes

All commands share the same top-level exit-code contract:

| Code | Meaning |
|------|---------|
| `0` | Success / all flows valid |
| `1` | Logic error: flow not found, validation failure, execution error, or malformed input |
| `2` | Input file or directory not found |

---

## Commands

### `inspect`

Print the structure of a registered flow.

```
chainweaver inspect <flow_name> [--format table|json]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--format` / `-f` | `table` | Output format: human-readable table or machine-readable JSON |

**Exit codes**: `0` = success, `1` = flow not registered or no registry configured.

**Example**:

```bash
chainweaver inspect my_etl_flow
chainweaver inspect my_etl_flow --format json
```

---

### `viz`

Render a registered flow as ASCII art or DOT (Graphviz) text.

```
chainweaver viz <flow_name> [--format ascii|dot]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--format` / `-f` | `ascii` | Visualization format: terminal-friendly ASCII or Graphviz DOT |

**Exit codes**: `0` = success, `1` = flow not found or no registry configured.

**Example**:

```bash
chainweaver viz my_etl_flow
chainweaver viz my_etl_flow --format dot | dot -Tpng -o my_etl_flow.png
```

---

### `validate`

Validate a single flow definition file (`.flow.yaml`, `.flow.yml`, or `.flow.json`).

```
chainweaver validate <file> [--format table|json]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--format` / `-f` | `table` | Output format: human-readable line or machine-readable JSON |

**Exit codes**: `0` = valid, `1` = validation error, `2` = file not found.

**Example**:

```bash
chainweaver validate flows/etl.flow.yaml
chainweaver validate flows/etl.flow.json --format json
```

---

### `check`

Validate every flow file in a directory (recursive).

```
chainweaver check <directory> [--format table|json] [--quiet]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--format` / `-f` | `table` | Output format |
| `--quiet` / `-q` | `False` | Suppress per-file output; only exit code is meaningful |

**Exit codes**: `0` = all valid, `1` = at least one invalid file, `2` = directory not found.

**Example**:

```bash
chainweaver check flows/
chainweaver check flows/ --quiet  # CI-friendly: exit code only
```

---

### `run`

Load a flow definition file from disk, register tools from one or more Python modules, and execute the flow with optional JSON input.

```
chainweaver run <flow_file> [--tools module] [--input file] [--format table|json]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--tools` / `-t` | (none) | Python module path to import tools from (repeatable) |
| `--input` / `-i` | (none) | JSON file containing the initial input dict |
| `--format` / `-f` | `table` | Output format |

**Exit codes**: `0` = success, `1` = execution error or tool not found, `2` = file not found.

**Example**:

```bash
chainweaver run flows/etl.flow.yaml --tools my_package.tools
chainweaver run flows/etl.flow.yaml --tools my_package.tools --input input.json --format json
```

---

### `profile`

Analyze one or more `ExecutionResult` JSON files. For a single file, surfaces per-step duration and bottlenecks. For multiple files, adds p50/p95/p99 statistics across runs. Every output (single or multi) also carries per-step and per-tool **reliability aggregates** — retries, skips, fallbacks, failures, and cache hits — so you can see at a glance which step or tool is responsible for instability.

```
chainweaver profile <traces...> [--top N] [--format table|json]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--top` / `-n` | `5` | Number of slowest steps to surface |
| `--format` / `-f` | `table` | Output format |

**Exit codes**: `0` = success, `1` = malformed trace input, `2` = file not found.

**Reliability fields** (issue #176, stable JSON contract):

Every entry in `steps[]` carries these in addition to `step_index`, `tool_name`, `duration_ms`, `success`:

| Field | Type | Meaning |
|---|---|---|
| `retry_count` | int | Retries beyond the initial invocation. In multi-trace mode this is the **sum** across the N traces at the same step index. |
| `skipped` | bool (single) / `skip_count` int (multi) | Step was `on_error="skip"`-ed. |
| `fallback_used` | bool (single) / `fallback_count` int (multi) | Step's `on_error="fallback:<tool_name>"` policy invoked a fallback tool — set regardless of whether the fallback itself succeeded. |
| `cached` | bool (single) / `cached_count` int (multi) | Outputs served from the executor's `step_cache`. |
| `error_type` | str \| null (single only) | Exception class name when the step failed. |

The top-level `aggregates` object rolls these up:

```json
{
  "aggregates": {
    "retry_count":    3,
    "skip_count":     0,
    "fallback_count": 1,
    "failure_count":  0,
    "cached_count":   0,
    "by_tool": {
      "fetch": {
        "invocation_count": 2,
        "retry_count": 3,
        "skip_count": 0,
        "fallback_count": 0,
        "failure_count": 0,
        "cached_count": 0
      },
      "store": { "...": "same shape" }
    }
  }
}
```

The table view appends a `Reliability:` footer with the same data, plus a per-tool table sorted by failures → fallbacks → retries. The footer is suppressed for clean runs (every count zero) so happy-path output stays compact.

**Example**:

```bash
chainweaver profile trace.json
chainweaver profile trace_a.json trace_b.json trace_c.json --top 10
chainweaver profile trace.json --format json
```

---

### `doctor`

Diagnose ChainWeaver flows against the currently registered tools. With `--check-drift`, walks every flow file under *path* (single file or recursive directory), imports tools from the modules passed via `--tools`, and reports per-flow `missing_tool` / `schema_mismatch` issues.

```
chainweaver doctor <path> --check-drift [--tools MODULE...] [--format table|json]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--check-drift` | — | Required. Currently the only `doctor` mode. |
| `--tools` / `-t` | (empty) | Python module path that exposes `Tool` instances at top level. Repeatable. |
| `--format` / `-f` | `table` | Output format: human-readable table or structured JSON. |

**Exit codes**: `0` = no drift, `1` = drift detected or malformed flow file, `2` = path or `--tools` module missing.

**JSON output shape** (when `--format json`):

```json
{
  "path": "flows/",
  "flow_count": 2,
  "drift_count": 1,
  "load_errors": [],
  "results": [
    {
      "path": "flows/ok.flow.yaml",
      "flow_name": "etl",
      "flow_version": "0.1.0",
      "fingerprints_present": true,
      "ok": true,
      "missing_count": 0,
      "drift_count": 0,
      "issues": []
    },
    {
      "path": "flows/legacy.flow.yaml",
      "flow_name": "legacy_etl",
      "flow_version": "0.1.0",
      "fingerprints_present": true,
      "ok": false,
      "missing_count": 0,
      "drift_count": 1,
      "issues": [
        {
          "step_index": 0,
          "tool_name": "fetch",
          "issue_type": "schema_mismatch",
          "detail": "Tool 'fetch' schema hash changed: expected 'abc123…', got 'def456…'."
        }
      ]
    }
  ]
}
```

`fingerprints_present: false` means the flow file was saved without a `tool_schema_hashes` snapshot — only `missing_tool` issues are detectable for those flows.

**Example**:

```bash
chainweaver doctor flows/etl.flow.yaml --check-drift --tools my_pkg.tools
chainweaver doctor flows/ --check-drift --tools my_pkg.tools --format json
```

---

### `diff`

Compare two `ExecutionResult` JSON files step-by-step.

Aligns step records by position and checks `outputs`, `error_type`, `error_message`, and `success` for each paired step. Non-deterministic fields (`trace_id`, `started_at`, `ended_at`, `total_duration_ms`, per-step `duration_ms`) are ignored unless `--perf-tolerance` is set.

```
chainweaver diff <a.json> <b.json> [--perf-tolerance N] [--format table|json]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--perf-tolerance` | (off) | Flag steps whose `duration_ms` changed by more than N %. Integer, e.g. `25` = 25%. |
| `--format` / `-f` | `table` | Output format: human-readable table or structured JSON diff |

**Exit codes**:

| Code | Meaning |
|------|---------|
| `0` | Traces are identical (modulo ignored fields) |
| `1` | Traces differ, or malformed trace input |
| `2` | File not found |

**JSON output shape** (when `--format json`):

```json
{
  "identical": false,
  "flow_name": null,
  "step_count": null,
  "success": null,
  "final_output": {
    "values_changed": {
      "root['key']": { "old_value": 42, "new_value": 99 }
    }
  },
  "steps": [
    {
      "step_index": 1,
      "tool_name": "store",
      "outputs": {
        "values_changed": {
          "root['key']": { "old_value": 42, "new_value": 99 }
        }
      }
    }
  ]
}
```

Fields `flow_name`, `step_count`, `success`, and `final_output` are `null` / `{}` when that dimension is identical between the two traces. The `steps` list contains only steps where at least one field differed.

**Example**:

```bash
chainweaver diff baseline.json current.json
chainweaver diff baseline.json current.json --perf-tolerance 25
chainweaver diff baseline.json current.json --format json
```

**Use cases**:

- A flow misbehaves in production — compare a known-good trace with today's failing trace to isolate the diverging step.
- A replay run (#21) finishes — was `final_output` byte-identical to the original?
- A schema drift event (#50) occurred — what was the functional impact on recorded traces?

---

## Programmatic registration (`inspect`, `viz`)

`inspect` and `viz` read from a process-scoped registry installed via `cli.set_default_registry`:

```python
from chainweaver import FlowRegistry, cli

registry = FlowRegistry()
registry.register_flow(my_flow)
cli.set_default_registry(registry)
cli.main(["inspect", "my_flow"])
```

`validate`, `check`, `run`, `profile`, and `diff` read directly from disk and do not consult the default registry.
