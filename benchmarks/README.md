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
| `compiled_overhead_ms_<suffix>` | Pure orchestration cost (`total - tool_time`). Sub-millisecond at every chain length; this is the metric that actually catches a new validation pass or `model_copy`. |

The suffix encodes the case parameters (`n{steps}_llm{ms}_tool{ms}`) so
metric names are stable and unique across the default sweep.

### `--full-output` (rich shape)

`--full-output` writes the same data shown in the stdout table — useful
for debugging or for generating a local diff against `baseline.json`.

## CI bench guard (`.github/workflows/bench.yml`)

The bench workflow runs the default sweep on every PR and push to
`main`, uploads the result via `benchmark-action/github-action-benchmark`,
and stores the history on the repo's `gh-pages` branch.

| Setting | Value |
|---|---|
| Runner | `ubuntu-22.04` (pinned to avoid glibc-driven variance) |
| Python | 3.10 |
| Repeats | 5 (median reporting) |
| Tool | `customSmallerIsBetter` |
| Alert threshold | `125 %` — fail the PR if any compiled metric regresses > 25 % |
| Comment | Posted on PR when the threshold trips |

### One-time setup: `gh-pages` branch

The first time this workflow runs, it needs a `gh-pages` branch to push
its history to. Initialize it once with:

```bash
git checkout --orphan gh-pages
git rm -rf .
echo 'ChainWeaver benchmark history' > README.md
git add README.md
git commit -m "chore: initialize gh-pages branch for benchmark history"
git push -u origin gh-pages
git checkout main
```

Enable GitHub Pages from the `gh-pages` branch (Settings → Pages) so the
historical chart renders publicly at the project's GitHub Pages URL.

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
