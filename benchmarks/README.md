# ChainWeaver Benchmarks

Quantitative evidence for the "compiled, not interpreted" claim
(issue #29).  Each benchmark contrasts a deterministic ChainWeaver flow
against a baseline that simulates an LLM call between every tool — the
naive-chaining approach we expect ChainWeaver to displace.

## Running

```bash
# Default sweep (4 cases × 5 repeats, ~25 seconds wall-clock)
python benchmarks/bench_naive_vs_compiled.py

# Single ad-hoc case
python benchmarks/bench_naive_vs_compiled.py --steps 10 --llm-ms 500

# Emit the CI-shape JSON report alongside the human table
python benchmarks/bench_naive_vs_compiled.py --output results/bench.json

# Also emit the rich, full-shape JSON for debugging
python benchmarks/bench_naive_vs_compiled.py \
    --output results/bench.json \
    --full-output results/bench-full.json

# Sequential vs concurrent DAG-level execution (#344)
python benchmarks/bench_dag_concurrency.py --leaves 6 --io-ms 50
```

`time.sleep` is used to simulate the LLM round-trip — no real LLM is
invoked, so the benchmark is reproducible and dependency-free.  All
durations are measured with `time.perf_counter`.

Each case runs `--repeats` times (default `5`); the script reports the
median, min, and max for every measured metric so reviewers can eyeball
the variance. Median-of-5 is enough to swallow per-run jitter on shared
CI runners without inflating wall-clock time.

## Metrics captured

| Metric | Meaning |
|--------|---------|
| `total_duration_ms` | Wall-clock time for the full flow. |
| `tool_execution_ms` | Cumulative time spent inside tool functions. |
| `overhead_ms` | `total_duration_ms - tool_execution_ms` (orchestration cost). |
| `llm_calls_count` | Number of simulated LLM calls (naive only). |
| `llm_calls_avoided` | `naive.llm_calls_count - compiled.llm_calls_count`. |
| `speedup_factor` | `naive.total_duration_ms / compiled.total_duration_ms`. |
| `final_value` | Sanity field — the two approaches must agree. |

## Interpreting the results

- The `compiled` row should consistently report `llm_calls_count = 0`.
- The `speedup_factor` grows linearly with chain length and with the
  per-step LLM latency.  At default settings (5 steps, 200ms LLM delay,
  near-instant tools) the speedup is typically 20× or more.
- `overhead_ms` for the compiled approach reflects pure ChainWeaver
  orchestration (schema validation + context merge); it should remain in
  the sub-millisecond range regardless of chain length.
- The `final_value` field is identical between the two approaches when
  `--no-verify` is not set; this is the correctness gate that lives
  alongside the latency comparison.

## What the benchmark does **not** measure

- Real LLM API costs (tokens, dollars).  The simulated delay is a proxy
  for latency only.
- Memory or GC pressure.
- Concurrency or parallel execution (DAG-level parallelism is tracked
  separately in issue #80).
- Cross-language comparisons.

## JSON report shapes

### `--output` (CI shape)

When `--output` is supplied the script writes the
[`benchmark-action/github-action-benchmark`](https://github.com/benchmark-action/github-action-benchmark)
`customSmallerIsBetter` shape — a flat list of `{name, unit, value, extra}`
entries:

```json
[
  {
    "name": "compiled_total_ms_n5_llm200_tool0",
    "unit": "ms",
    "value": 0.211,
    "extra": "min=0.19ms max=0.22ms repeats=5"
  },
  {
    "name": "compiled_overhead_ms_n5_llm200_tool0",
    "unit": "ms",
    "value": 0.145,
    "extra": "min=0.13ms max=0.15ms repeats=5"
  }
]
```

Two metrics per case:

| Metric | Why it matters |
|---|---|
| `compiled_total_ms_<suffix>` | Headline regression metric. Includes simulated tool delays. |
| `compiled_overhead_ms_<suffix>` | Pure orchestration cost (`total - tool_time`). Sub-millisecond at every flow length; this is the metric that actually catches a new validation pass or `model_copy`. |

The suffix encodes the case parameters (`n{steps}_llm{ms}_tool{ms}`) so
metric names are stable and unique across the default sweep.

### `--full-output` (rich shape)

`--full-output` writes the same data shown in the stdout table — useful
for debugging or for generating a local diff against `baseline.json`.

## CI bench guard (`.github/workflows/bench.yml`)

The bench workflow runs the default sweep on every PR and push to `main`,
uploads the result via `benchmark-action/github-action-benchmark`, and stores
the history on the repo's `gh-pages` branch. Every PR still gets the benchmark
check, including release PRs, but alerts are enabled only when the diff touches
execution-sensitive modules or benchmark configuration.

| Setting | Value |
|---|---|
| Runner | `ubuntu-22.04` (pinned to avoid glibc-driven variance) |
| Python | 3.10 |
| Repeats | 5 (median reporting) |
| Tool | `customSmallerIsBetter` |
| Alert threshold | `200 %` — flag a compiled metric only when it exceeds 2x its baseline |
| Alert scope | Executor-path and benchmark changes only |
| Enforcement | Advisory comment on matching PRs; failure on the matching `main` push |

The broader threshold is intentional. Compiled overhead is normally below one
millisecond, where a 50-170 microsecond shared-runner swing can exceed a 25%
ratio without a meaningful code regression. A 2x gate still catches major
executor regressions while version-only and documentation releases cannot emit
alerts.

### `gh-pages` branch

The workflow self-bootstraps the `gh-pages` branch on its first run
(see the "Ensure gh-pages branch exists" step in
`.github/workflows/bench.yml`), so no manual init is required. To
publish the historical chart, enable GitHub Pages from the `gh-pages`
branch (Settings → Pages) after the workflow's first push to it.

### Refreshing `benchmarks/baseline.json`

`benchmarks/baseline.json` is the human-eyeball reference for local
runs. It is **not** consumed by the CI workflow (which uses the
gh-pages history instead). Regenerate it whenever an intentional
performance change lands and commit the new file in the same PR:

```bash
python benchmarks/bench_naive_vs_compiled.py --repeats 5 --output benchmarks/baseline.json
```

Absolute numbers vary across machines; the baseline is a relative
reference, not a CI gate.

---

## Correctness benchmark (`bench_correctness.py`, issue #103)

Where the latency benchmark argues compiled flows are *faster*, this one
argues they are *safer*. When an LLM mediates the data handed between
tools it introduces structural corruption that schema-validated compiled
execution eliminates by construction:

| Corruption type | What the naive simulation does |
|-----------------|--------------------------------|
| Field hallucination | Adds a fabricated field the source never produced |
| Data loss | Drops a required field |
| Type corruption | Changes a field's type (`int` → `str`) |
| Schema drift | Renames a field (`value` → `Value`, snake → camel) |
| Routing inconsistency | Picks a different next tool on some runs |

```bash
# Default: 3 scenarios (numeric, data-enrichment, long-chain) × 100 runs
python benchmarks/bench_correctness.py

# Reproducible with an explicit seed; write the machine-readable JSON
python benchmarks/bench_correctness.py --runs 500 --seed 7 \
    --output results/correctness.json
```

The corruption model is **fully seeded** (`LLMCorruptionProfile.seed`) so
runs are reproducible; no real LLM is called. Per-event rates are
configurable and documented as estimates, not measurements. The compiled
path runs the identical chain through `FlowExecutor` and reports **zero**
corruption across every run. The report also includes a
"corruption compounds" table showing how the naive corruption rate grows
with chain length.

---

## Aggregate report (`report.py`, issue #207)

Packages the latency, decisions-avoided, cost-avoided, and correctness
numbers into versioned artifacts so README/docs claims cite generated
output instead of hand-written figures:

```bash
python benchmarks/report.py                       # writes benchmarks/results/
python benchmarks/report.py --output-dir docs/_bench --correctness-runs 200
```

Outputs:

| Artifact | Purpose |
|----------|---------|
| `results/latest.json` | Machine-readable aggregate (latency + cost + correctness + environment metadata + caveats). |
| `results/latest.md` | Human-readable report for docs/README inclusion. |

Cost-avoided dollars are priced against the maintained
`chainweaver.cost.PROVIDER_PRICES` table (issue #156); the report records
the snapshot's `as_of` date. Every report embeds environment metadata
(Python version, ChainWeaver version, OS, commit SHA) and an explicit
caveats list — reproducibility matters more than impressive numbers, and
no benchmark requires network access, API keys, or paid LLM calls.

`results/latest.{json,md}` record the commit they were generated against;
regenerate them whenever the numbers should be refreshed and commit the
result. The report format is guarded by
`tests/test_benchmark_artifacts.py`, so a shape change that breaks
`latest.json` fails CI.
