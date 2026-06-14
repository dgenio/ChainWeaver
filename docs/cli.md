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

## Machine-readable output (`--format json`)

The result-producing commands — `inspect`, `validate`, `check`, `profile`,
`diff`, `attest`, and `flows list` — wrap their `--format json` payload in a
stable, versioned envelope so automation and CI can branch on `status` / error
codes instead of scraping human-readable text:

```json
{
  "schema_version": "1",
  "status": "ok",
  "data": { "...": "command-specific payload" },
  "errors": [{ "code": "CW-E017", "message": "…" }]
}
```

- `schema_version` versions the **envelope itself** — distinct from a flow's
  SemVer `version` and from the `trace_schema_version` of a trace. A MAJOR bump
  signals an incompatible envelope-shape change.
- `status` is `"ok"` or `"error"`; on failure, `errors` carries
  `{code, message}` entries using the stable
  [error codes](reference/error-table.md).
- Trace-bearing commands (`profile`, `diff`) include the source
  `trace_schema_version` in `data`.

`run` and `dump-schema` keep their existing (un-enveloped) JSON output.

---

## Shell completion

The CLI ships tab-completion for bash, zsh, and fish (provided by typer). It
covers every command and option. Install it once per shell:

```bash
chainweaver --install-completion          # auto-detect the current shell
chainweaver --show-completion bash        # print the script without installing
```

Restart your shell (or re-source its rc file) after installing.

---

## Flow file format

The file-oriented commands (`run`, `validate`, `check`, `doctor`, `attest`,
`suggest`) load a flow definition from disk. Accepted extensions are
`.flow.yaml`, `.flow.yml`, and `.flow.json`.

**Reading `.flow.yaml` / `.flow.yml` requires the YAML extra:**

```bash
pip install 'chainweaver[yaml]'
```

`.flow.json` works with no extra. Without `pyyaml`, the YAML commands fail
with `FlowSerializationError: YAML support requires 'pyyaml' to be installed`.

### The `type:` discriminator

Every flow file **must** declare a top-level `type:` key — either `Flow`
(linear) or `DAGFlow` (directed-acyclic). It tells the loader which model to
build; without it you get:

```
chainweaver: Missing or invalid 'type' discriminator (got None); expected 'Flow' or 'DAGFlow'
```

A minimal hand-authored linear flow (`examples/double_add_format.flow.yaml`,
shipped in the repo) looks like this:

```yaml
type: Flow
name: double_add_format
version: "0.1.0"
description: Doubles a number, adds 10, and formats the result.
steps:
  - tool_name: double
    input_mapping:
      number: number
  - tool_name: add_ten
    input_mapping:
      value: value
  - tool_name: format_result
    input_mapping:
      value: value
```

The required fields are `type`, `name`, `description`, and `steps`; `version`
defaults to `"0.1.0"` on `Flow` but is required on `DAGFlow`. See
[`AGENTS.md` §5](https://github.com/dgenio/ChainWeaver/blob/main/AGENTS.md#5-executor-and-flow-semantics)
for the full field table. The `--tools` modules supply the actual `Tool`
implementations referenced by `tool_name`.

---

## Commands

### `inspect`

Print the structure of a flow.

```
chainweaver inspect <flow_name> [--format table|json] [discovery flags]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--format` / `-f` | `table` | Output format: human-readable table or machine-readable JSON |
| `--file` | — | Load the flow directly from a `.flow.yaml` / `.flow.json` file |
| `--discover-dir` | — | Discover flows by scanning a directory for `.flow.*` files |
| `--discover-entry-points` | `false` | Discover flows from installed packages via the `chainweaver.flows` entry points |

Without a discovery flag, the flow is resolved from the registry installed via
`set_default_registry` (see [Programmatic registration](#programmatic-registration-inspect-viz)).
Discovery precedence is `--file` → `--discover-dir` → `--discover-entry-points`
→ the default registry; a no-match error names the source consulted and the
flows it found. Use `chainweaver flows list` to preview what is discoverable.

**Exit codes**: `0` = success, `1` = flow not found or no registry configured,
`2` = a supplied file/directory does not exist.

**Example**:

```bash
chainweaver inspect my_etl_flow                          # from the default registry
chainweaver inspect my_etl_flow --discover-dir flows/    # no Python setup needed
chainweaver inspect my_etl_flow --file flows/etl.flow.yaml --format json
chainweaver flows list --discover-dir flows/             # see what is discoverable
```

---

### `viz`

Render a flow as ASCII art, DOT (Graphviz), or Mermaid text.

```
chainweaver viz <flow_name> [--format ascii|dot|mermaid] [discovery flags]
chainweaver viz --result <trace.json> --format mermaid
```

| Flag | Default | Description |
|------|---------|-------------|
| `--format` / `-f` | `ascii` | Visualization format: terminal-friendly ASCII, Graphviz DOT, or Mermaid |
| `--result` | — | Render an `ExecutionResult` JSON file as a Mermaid status/timing overlay (file-only; no registry or flow name needed). Requires `--format mermaid` |
| `--file` | — | Load the flow directly from a `.flow.yaml` / `.flow.json` file |
| `--discover-dir` | — | Discover flows by scanning a directory for `.flow.*` files |
| `--discover-entry-points` | `false` | Discover flows from installed packages via the `chainweaver.flows` entry points |

Flow resolution works exactly like [`inspect`](#inspect). Mermaid renders
natively on GitHub and MkDocs Material, so it is the lowest-friction format for
PR descriptions and docs.

**Exit codes**: `0` = success, `1` = flow not found or no registry configured,
`2` = usage error (no flow and no `--result`, or `--result` without
`--format mermaid`) or a supplied file/directory does not exist.

**Example**:

```bash
chainweaver viz my_etl_flow --discover-dir flows/
chainweaver viz my_etl_flow --format dot | dot -Tpng -o my_etl_flow.png
chainweaver viz my_etl_flow --discover-dir flows/ --format mermaid
chainweaver viz --result trace.json --format mermaid    # overlay a real run
```

---

### `explain`

Render a deterministic, **LLM-free** explanation of a flow — steps, input/output
mappings, branching conditions, governance/safety attributes, and an embedded
Mermaid diagram — suitable for pasting into a pull-request description or a
review. Output is stable across runs (diff-friendly).

```
chainweaver explain <flow_name> [--format md|text] [--result trace.json] [discovery flags]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--format` / `-f` | `md` | `md` (Markdown for PRs) or `text` |
| `--result` | — | Overlay actual step outcomes from an `ExecutionResult` JSON file |
| `--file` / `--discover-dir` / `--discover-entry-points` | — | Flow resolution, exactly like [`inspect`](#inspect) |

**Exit codes**: `0` = success, `1` = flow not found or no registry configured,
`2` = a supplied file/directory does not exist.

**Example**:

```bash
chainweaver explain my_etl_flow --discover-dir flows/ > flow-review.md
chainweaver explain my_etl_flow --file flows/etl.flow.yaml --result trace.json
```

---

### `init`

Scaffold a runnable first flow project — tool definitions, a flow file, and a
run script — in one command.

```
chainweaver init [directory] [--template linear|dag|mcp] [--with-tests] [--force]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--template` / `-t` | `linear` | Project template: linear flow, fan-in DAG, or MCP-ready starter |
| `--with-tests` | `false` | Also scaffold a passing `pytest` module (`test_flow.py`) |
| `--force` | `false` | Overwrite existing files instead of aborting on a collision |

The command prints the exact next commands after generating the files.

**Exit codes**: `0` = success, `1` = a target file already exists and `--force`
was not given, `2` = *directory* exists but is not a directory.

**Example**:

```bash
chainweaver init my-first-flow --template linear --with-tests
cd my-first-flow && python run.py
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
# Runnable from the repository root — the flow file and tools both ship in examples/:
chainweaver run examples/double_add_format.flow.yaml --tools examples.simple_linear_flow --input '{"number": 5}'

chainweaver run flows/etl.flow.yaml --tools my_package.tools --input input.json --format json
```

---

### `serve`

Expose a flow as **MCP tools** over a chosen transport. Loads a flow file and its tool modules (exactly like `run`), mounts the flow on a [`FlowServer`](mcp-server.md), and serves it so MCP-aware agents call the whole compiled flow as a single deterministic tool. Requires the `mcp` extra (`pip install 'chainweaver[mcp]'`).

```
chainweaver serve <flow_file> [--tools module] [--transport stdio|sse|streamable-http] [--name NAME] [--prefix PREFIX]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--tools` / `-t` | (none) | Python module path to import tools from (repeatable) |
| `--transport` | `stdio` | MCP transport: `stdio`, `sse`, or `streamable-http` |
| `--name` | `chainweaver` | Server name advertised to MCP clients |
| `--prefix` | (none) | Prefix for exposed tool names (e.g. `cw` → `cw__my_flow`) |

The startup banner is written to **stderr**, keeping stdout a clean MCP wire channel under `stdio`. The process blocks serving the transport until interrupted (Ctrl-C).

**Exit codes**: `0` = clean shutdown, `1` = malformed flow file or missing `mcp` extra, `2` = flow file not found or tools module not importable.

**Example**:

```bash
# Runnable from the repository root — flow file and tools both ship in examples/:
chainweaver serve examples/double_add_format.flow.yaml --tools examples.simple_linear_flow
```

See [Use ChainWeaver as an MCP server](mcp-server.md) for the full guide.

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

Diagnose ChainWeaver flows against the currently registered tools. With `--check-drift`, walks every flow file under *path* (single file or recursive directory), imports tools from the modules passed via `--tools`, and reports per-flow `missing_tool` / `schema_mismatch` issues. With `--preflight`, runs structural validation (tool existence and resolvable input mappings). With `--profile first-run`, skips flow analysis and checks **environment readiness** instead — Python version, optional-extra availability (with the exact install command), writable paths, and core import health — for a "is my install ready?" first check (no *path* required).

```
chainweaver doctor <path> --check-drift [--tools MODULE...] [--format table|json]
chainweaver doctor --profile first-run [--format table|json]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--check-drift` | — | Compare each step's tool reference and schema fingerprint to the current registry. |
| `--preflight` | — | Validate flow structure: tool existence and resolvable input mappings. |
| `--profile` | — | Named diagnostic profile. `first-run` checks environment readiness (no *path* needed). |
| `--tools` / `-t` | (empty) | Python module path that exposes `Tool` instances at top level. Repeatable. |
| `--format` / `-f` | `table` | Output format: human-readable table or structured JSON. |

One of `--check-drift`, `--preflight`, or `--profile` is required.

**First-run JSON shape** (when `--profile first-run --format json`): a top-level
`ok` flag plus `python`, `writable_paths`, `import_health`, and an `extras`
array where each entry carries `extra`, `available`, `missing_modules`, and a
copy-paste `install` command.

**Exit codes**: `0` = no drift / ready, `1` = drift detected, malformed flow file, or not ready, `2` = path or `--tools` module missing.

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

### `attest`

Run an observed-determinism attestation against a flow: generate `--runs` distinct inputs (or read them from `--seed-input`), run the flow `--repeats` times per input, and emit a JSON attestation report. When all repeats agree the attestation passes; any divergence fails it.

This produces *observed-deterministic* evidence, not a formal proof — re-running with the same `--seed` and ChainWeaver version yields a byte-identical `aggregate_fingerprint`.

```
chainweaver attest <flow_file> [--tools module] [--runs N] [--repeats N] [--seed N] [--seed-input file] [--format json|table]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--tools` / `-t` | (none) | Python module path exposing `Tool` instances at top level. Repeatable. |
| `--runs` | `100` | Number of distinct inputs to generate (ignored when `--seed-input` is set). |
| `--repeats` | `3` | Executions per input. Must be ≥ 2. |
| `--seed` | `0` | Integer seed for the input generator. Same seed → same inputs. |
| `--seed-input` | (none) | JSON file containing a list of input objects to use directly (bypasses the generator). |
| `--format` / `-f` | `json` | Output format: `json` (the attestation artifact) or `table`. |

**Exit codes**: `0` = observed-deterministic across all inputs, `1` = divergence detected / execution / argument error, `2` = flow file or tools module not found.

**Example**:

```bash
chainweaver attest examples/double_add_format.flow.yaml --tools examples.simple_linear_flow --runs 50 --repeats 3
```

---

### `suggest`

Emit advisory static optimization suggestions for a flow file. A successful run always exits `0` (the suggester is advisory); machine consumers should gate on the `suggestions` array length in `--format json`.

Suggestion families (stable codes):

- `CW001` — wasteful-passthrough (empty `input_mapping`).
- `CW002` — parallelizable-pair (adjacent steps reading disjoint context keys). Requires `--tools`.
- `CW003` — dead-step (step outputs are not read downstream). Requires `--tools`.
- `CW004` — cacheable-step (identical outputs across observed traces). Requires two or more `--trace` files.

```
chainweaver suggest <flow_file> [--tools module] [--trace file] [--format table|json]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--tools` / `-t` | (none) | Python module path exposing `Tool` instances at top level. Required for CW003 (dead-step). Repeatable. |
| `--trace` | (none) | Path to a recorded `ExecutionResult` JSON file. Two or more required for CW004 (cacheable-step). Repeatable. |
| `--format` / `-f` | `table` | Output format: human-readable table or machine-readable JSON. |

**Exit codes**: `0` = ran successfully (regardless of suggestion count), `1` = malformed input, `2` = file not found.

**Example**:

```bash
chainweaver suggest examples/double_add_format.flow.yaml --tools examples.simple_linear_flow
chainweaver suggest flows/etl.flow.yaml --tools my_pkg.tools --trace run_a.json --trace run_b.json --format json
```

---

### `record`

Mine candidate flows from a recorded JSONL tool trace (issue #226). Replays the trace through `ChainObserver`, detects repeated tool sequences **offline (no LLM)**, and emits candidate `.flow.yaml` files ranked by projected LLM calls avoided (`len(tools) * occurrences`). Without `--output-dir` the command is a dry run that only reports candidates.

Each non-blank line of the trace file is a JSON object describing one tool call. Calls are grouped into traces by `trace_id` (file order preserved); lines without a `trace_id` join a single default trace:

```json
{"trace_id": "req-1", "tool": "fetch", "inputs": {"url": "..."}, "outputs": {"body": "..."}}
```

`tool` (or its alias `tool_name`) is required; `inputs` defaults to `{}` and `outputs` to `null`.

```
chainweaver record <trace.jsonl> [--output-dir DIR] [--min-occurrences N] [--min-length N] [--max-length N] [--include-ignored] [--format table|json]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--output-dir` / `-o` | (none) | Directory to write candidate `.flow.yaml` files into. Omit for a dry run. |
| `--min-occurrences` | `3` | Minimum contiguous appearances for a pattern to be suggested. |
| `--min-length` | `2` | Minimum pattern length (number of tools). |
| `--max-length` | (none) | Maximum pattern length. Omit for no upper bound. |
| `--include-ignored` | `False` | Report persisted ignored candidates instead of suppressing them. Ignored files are never overwritten. |
| `--format` / `-f` | `table` | Output format: human-readable table or machine-readable JSON. |

**Exit codes**: `0` = ran successfully (regardless of candidate count), `1` = malformed trace or serialization error, `2` = file not found.

**Example**:

```bash
chainweaver record examples/agent_tool_trace.jsonl
chainweaver record examples/agent_tool_trace.jsonl --output-dir candidates/ --format json
```

New files are persisted with lifecycle `draft`; repeated runs preserve an
existing candidate's governance state. Promote a candidate deterministically:

```bash
chainweaver flows promote candidates/suggested__fetch__validate.flow.yaml --to reviewed --reviewed-by alice
chainweaver flows promote candidates/suggested__fetch__validate.flow.yaml --to active
chainweaver flows ignore candidates/suggested__noisy.flow.yaml --reason "Not useful for this workspace"
```

The lifecycle is `observed → suggested → draft → reviewed → active`.
`ignored` candidates are suppressed by later `record` runs, and `archived`
flows remain auditable but are not exposed by default.

---

### `traces`

Import coding-agent tool-use traces and run the **observe → mine → score →
draft → backtest** loop for the coding-agent token-reduction use case
(issues #254, #256, #257, #266, #267). The richer JSONL format carries both
`tool_call` and `model_call` events plus token/latency/status metadata; all
analysis is **offline (no LLM)**. See the [Daily Driver guide](daily-driver.md).

```
chainweaver traces mine <trace.jsonl> [--min-occurrences N] [--min-length N] [--max-length N] [--limit N] [--format table|json]
chainweaver traces draft-flows <trace.jsonl> [--output-dir DIR] [--min-occurrences N] [--min-length N] [--max-length N] [--format table|json]
chainweaver traces backtest <flow.yaml> --trace <trace.jsonl> [--format table|json]
```

- **`mine`** — mine repeated tool sequences and score each by support,
  success rate, schema stability, determinism, and safety; prints a ranked,
  human-friendly report (or JSON).
- **`draft-flows`** — generate `draft`-lifecycle `.flow.yaml` files (with a
  `.json` metadata/warnings sidecar) from the scored candidates. Without
  `--output-dir` it is a dry run.
- **`backtest`** — replay past traces against a draft flow (shape + sequence
  only, no tool execution); exits non-zero if any window fails to reproduce.

**Exit codes**: `0` = ran successfully (for `backtest`, all examples
reproduced), `1` = malformed trace / mismatches found, `2` = file not found.

**Example**:

```bash
chainweaver traces mine coding-agent.jsonl --limit 5
chainweaver traces draft-flows coding-agent.jsonl --output-dir flows/drafts/
chainweaver traces backtest flows/drafts/draft__fs_search__fs_read.flow.yaml --trace coding-agent.jsonl
```

---

### `dump-schema`

Emit the JSON Schema for `.flow.json` / `.flow.yaml` files, derived from the Pydantic models in `chainweaver.flow`. Editors that consume JSON Schema (VS Code via `redhat.vscode-yaml`, JetBrains, …) get autocomplete, hover docs, and inline validation once they point `yaml.schemas` at the published schema.

```
chainweaver dump-schema [--output PATH] [--check]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--output` / `-o` | stdout | Write the JSON Schema to this path. Recommended in-repo path: `schemas/flow.schema.json`. |
| `--check` | `False` | Write nothing; exit `0` if the file at `--output` already matches the current schema, `1` if it would change. Useful as a CI guard. |

**Exit codes**: `0` = written / printed successfully (or `--check` match), `1` = `--check` mismatch or `--output` unwritable, `2` = `--check` used without `--output`.

**Example**:

```bash
chainweaver dump-schema --output schemas/flow.schema.json
chainweaver dump-schema --check --output schemas/flow.schema.json   # CI: fails if the checked-in schema is stale
```

---

### `fuzz`

Property-based fuzzing for a flow file (issues #220, #221, #222). Generates `--runs` cases — either from the flow's `input_schema` or by mutating a `--input` base — executes the flow, and checks each `--property` (a generic invariant over the `ExecutionResult`) against the result. Optionally injects malformed tool outputs (`--output-fault-prob`), shrinks failing inputs to a minimal reproducer (`--minimize`, issue #221), and saves failing traces as replayable JSON, redacted by default (`--save-failures` / `--redact`, issue #217). With `--redact` (the default) the failing and minimized inputs printed in the summary/table are redacted too, so secrets do not leak into CI logs; pass `--no-redact` for raw values. Each `--property` must resolve to a unique name.

A run is **reproducible**: re-running with the same `--seed`, `--runs`, flow, and tools yields the same cases and failures.

```
chainweaver fuzz <file> [--tools MODULE...] [--property NAME|module:attr ...] [--runs N] [--seed S] \
                        [--input JSON | --input-file PATH] [--output-fault-prob P] \
                        [--minimize] [--save-failures DIR] [--redact/--no-redact] [--format table|json]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--tools` / `-t` | (empty) | Python module path that exposes `Tool` instances at top level. Repeatable. |
| `--property` / `-p` | `flow_succeeds` | A built-in property name (`flow_succeeds`, `final_output_present`) or a `module:attr` path to a `FlowProperty` or a `Callable[[ExecutionResult], bool]`. Repeatable. |
| `--runs` / `-n` | `100` | Number of cases to generate (`>= 1`). |
| `--seed` | `0` | Deterministic RNG seed. |
| `--input` / `-i` | (off) | JSON object used as the base input to mutate instead of generating from the schema. |
| `--input-file` | (off) | Path to a JSON object used as the base input. |
| `--output-fault-prob` | `0.0` | Probability in `[0,1]` of corrupting a tool's output per call (`0` disables). |
| `--minimize` / `--no-minimize` | `--no-minimize` | Shrink each failing input to a minimal reproducer. |
| `--save-failures` | (off) | Directory to write failing `ExecutionResult` traces to (created if absent). |
| `--redact` / `--no-redact` | `--redact` | Redact saved traces **and emitted failing/minimized inputs** with the default `RedactionPolicy`. Use `--no-redact` for raw values. |
| `--format` / `-f` | `table` | Output format: human-readable table or structured JSON. |

**Exit codes**: `0` = no property violated, `1` = one or more violations found or a CLI-level error (bad arguments, malformed flow/input, unknown property), `2` = flow file, tools module, or property module not found / not importable.

**JSON output shape** (when `--format json`):

```json
{
  "flow": "my_flow",
  "runs": 1000,
  "seed": 42,
  "properties": ["flow_succeeds"],
  "failures": 1,
  "failure_cases": [
    {
      "property": "flow_succeeds",
      "case_index": 17,
      "initial_input": {"number": 5, "junk": "x"},
      "check_error": null,
      "minimized_input": {"junk": "x"},
      "saved": "failures/my_flow.flow_succeeds.case17.json"
    }
  ]
}
```

`minimized_input` is present only with `--minimize`; `saved` only with `--save-failures`. `check_error` is set when a property check itself raised (treated as a violation).

**Example (CI integration)**:

```bash
chainweaver fuzz flows/my_flow.flow.yaml \
  --tools my_pkg.tools \
  --property my_pkg.props:no_unauthorized_action \
  --runs 1000 --seed 42 \
  --minimize --save-failures failures/
# exits non-zero when a property is violated, failing the CI job;
# minimized, redacted reproducers land in failures/ as build artifacts.
```

---

### `service`

Run one `ChainWeaverService` analysis pass and report the proposals it would queue (issue #101). The service ties together the static schema analyzer (`--tools`) and the runtime observer (`--trace`), surfaces candidate flows as **pending proposals**, and prints service metrics. Proposals are reported, never auto-registered — promotion stays a governed, in-process action.

A long-running daemon with cross-invocation `approve` / `reject` requires proposal persistence (#16) and is intentionally out of scope for the CLI; drive that loop via the `ChainWeaverService` Python API instead.

```
chainweaver service [--tools module...] [--trace trace.jsonl] [--min-occurrences N] [--min-length N] [--format table|json]
```

| Flag | Default | Description |
|------|---------|-------------|
| `--tools` / `-t` | (none) | Python module path exposing `Tool` instances at top level. Enables the static-analysis pass. Repeatable. |
| `--trace` | (none) | JSONL tool-trace file (same format as `chainweaver record`) feeding the runtime-observation pass. |
| `--min-occurrences` | `3` | Minimum runtime occurrences before an observed pattern is proposed. |
| `--min-length` | `2` | Minimum pattern / flow length (number of tools). |
| `--format` / `-f` | `table` | Output format: human-readable table or machine-readable JSON. |

**Exit codes**: `0` = ran successfully, `1` = malformed trace / input, `2` = trace file not found.

**Example**:

```bash
chainweaver service --tools examples.simple_linear_flow
chainweaver service --trace examples/agent_tool_trace.jsonl --min-occurrences 2 --format json
```

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

`validate`, `check`, `run`, `profile`, `diff`, `attest`, `suggest`, `doctor`, and `fuzz` read directly from disk and do not consult the default registry. `dump-schema` takes no flow input.
