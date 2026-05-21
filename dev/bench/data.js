window.BENCHMARK_DATA = {
  "lastUpdate": 1779400310968,
  "repoUrl": "https://github.com/dgenio/ChainWeaver",
  "entries": {
    "ChainWeaver microbenchmarks": [
      {
        "commit": {
          "author": {
            "email": "diogofcul@hotmail.com",
            "name": "Diogo Santos",
            "username": "dgenio"
          },
          "committer": {
            "email": "noreply@github.com",
            "name": "GitHub",
            "username": "web-flow"
          },
          "distinct": true,
          "id": "6f66c98dac31af71bc44b12b89bba1fcba42fa1a",
          "message": "Merge pull request #164 from dgenio/claude/triage-issues-dwP8T\n\nchore: bundle OSS health, pre-commit, comparisons, bench CI, action",
          "timestamp": "2026-05-21T22:51:01+01:00",
          "tree_id": "ebfe52c639e784fbec52ab53465788604afb92cb",
          "url": "https://github.com/dgenio/ChainWeaver/commit/6f66c98dac31af71bc44b12b89bba1fcba42fa1a"
        },
        "date": 1779400310379,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "compiled_total_ms_n2_llm100_tool0",
            "value": 0.3230599999142214,
            "unit": "ms",
            "extra": "min=0.11ms max=0.50ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n2_llm100_tool0",
            "value": 0.1921169999832273,
            "unit": "ms",
            "extra": "min=0.07ms max=0.29ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm200_tool0",
            "value": 0.33456500000283995,
            "unit": "ms",
            "extra": "min=0.19ms max=0.42ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm200_tool0",
            "value": 0.1885670000092432,
            "unit": "ms",
            "extra": "min=0.12ms max=0.28ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n10_llm200_tool10",
            "value": 102.5350070000286,
            "unit": "ms",
            "extra": "min=102.10ms max=102.86ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n10_llm200_tool10",
            "value": 0.5814849999978833,
            "unit": "ms",
            "extra": "min=0.49ms max=0.74ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm500_tool50",
            "value": 251.47830399998838,
            "unit": "ms",
            "extra": "min=251.31ms max=251.57ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm500_tool50",
            "value": 0.3553409999312862,
            "unit": "ms",
            "extra": "min=0.32ms max=0.40ms repeats=5"
          }
        ]
      }
    ]
  }
}