# ChainWeaver Benchmarks

Quantitative evidence for the "compiled, not interpreted" claim
(issue #29).  Each benchmark contrasts a deterministic ChainWeaver flow
against a baseline that simulates an LLM call between every tool — the
naive-chaining approach we expect ChainWeaver to displace.

## Running

```bash
# Default sweep (4 cases, ~5 seconds wall-clock)
python benchmarks/bench_naive_vs_compiled.py

# Single ad-hoc case
python benchmarks/bench_naive_vs_compiled.py --steps 10 --llm-ms 500

# Median-of-N reporting (smooths runner jitter)
python benchmarks/bench_naive_vs_compiled.py --repeats 5

# Emit a machine-readable JSON report alongside the human table
python benchmarks/bench_naive_vs_compiled.py --output results/bench.json

# Emit a flat array in the benchmark-action/github-action-benchmark
# customSmallerIsBetter format (used by the CI bench guard)
python benchmarks/bench_naive_vs_compiled.py \
    --benchmark-action-output results/bench-flat.json
```

`time.sleep` is used to simulate the LLM round-trip — no real LLM is
invoked, so the benchmark is reproducible and dependency-free.  All
durations are measured with `time.perf_counter`.

## Metrics captured

| Metric | Meaning |
|--------|---------|
| `total_duration_ms` | Wall-clock time for the full chain. |
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

## JSON report shape

When `--output` is supplied the script writes a JSON document of the
shape:

```json
{
  "cases": [
    {
      "n_steps": 5,
      "llm_delay_ms": 200.0,
      "tool_delay_ms": 0.0,
      "rows": [
        { "approach": "naive",    "total_duration_ms": 803.4, "...": "..." },
        { "approach": "compiled", "total_duration_ms": 1.1,   "...": "..." }
      ],
      "speedup_factor": 730.4,
      "llm_calls_avoided": 4
    }
  ]
}
```

This format is stable enough to feed into a CI tracker if/when the
historical-tracking issue (out of scope for #29) lands.

## CI performance-budget guard (issue #144)

`.github/workflows/bench.yml` runs the benchmark on every PR and on
push to `main`, then hands the result to
[`benchmark-action/github-action-benchmark`][bench-action]. History is
stored on the repo's own `gh-pages` branch (no SaaS dependency); the
action posts a PR comment when `total_duration_ms` regresses beyond the
**125 % alert threshold** (i.e. a +25 % slowdown).

### Failure semantics

A failing bench job means **the median `total_duration_ms` for one or
more named metrics is at least 25 % worse than the `gh-pages` baseline**.
The PR comment lists every metric that tripped the threshold, with the
old and new values side-by-side.

If the regression is genuine, fix it in the same PR — do not relax the
threshold. If the regression is intentional (e.g. you traded latency
for correctness), document the trade-off in the PR description and
[refresh the baseline](#refreshing-the-baseline) on `main`.

### Variance and OS pinning

- Runner OS is pinned to `ubuntu-22.04` to avoid glibc-driven variance
  ([CodSpeed note][glibc-note]).
- macOS and Windows runners are deliberately **not** included — their
  wall-clock variance is too high for a hard gate.
- `--repeats 5` with median reporting smooths transient runner jitter.

### One-off `gh-pages` initialization

Before the first run, a maintainer must seed the `gh-pages` branch with
an initial benchmark dataset (the action will not create the branch on
its own). This is a one-time bootstrap step:

```bash
git checkout --orphan gh-pages
git rm -rf .
echo "ChainWeaver benchmark history" > index.md
git add index.md
git commit -m "chore: initialize gh-pages for benchmark history"
git push -u origin gh-pages
git checkout main
```

After this, every subsequent `main` push appends to the history
automatically.

### Refreshing the baseline

`benchmarks/baseline.json` is the **local sanity reference** — a sample
run of the default sweep, regenerated only when an intentional perf
change lands:

```bash
python benchmarks/bench_naive_vs_compiled.py --repeats 5 \
    --output benchmarks/baseline.json
git add benchmarks/baseline.json
git commit -m "perf: refresh benchmark baseline after <change>"
```

The CI gate's source of truth lives on `gh-pages`, **not** in
`baseline.json` — refresh the latter only to keep the local reference
consistent with current `main`.

[bench-action]: https://github.com/benchmark-action/github-action-benchmark
[glibc-note]: https://codspeed.io/blog/unrelated-benchmark-regression
