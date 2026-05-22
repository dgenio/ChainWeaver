window.BENCHMARK_DATA = {
  "lastUpdate": 1779444210206,
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
      },
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
          "id": "838bc5b4fffc1a68ebf49dcb7dc12bc8ece6b07d",
          "message": "Merge pull request #165 from dgenio/claude/triage-issues-7JgBE\n\nchore: add pre-commit hooks, property tests, API snapshot guard, and bench CI (#137)",
          "timestamp": "2026-05-22T10:49:56+01:00",
          "tree_id": "eab35543053f3950e6ddb5e8e16ef10048055c8a",
          "url": "https://github.com/dgenio/ChainWeaver/commit/838bc5b4fffc1a68ebf49dcb7dc12bc8ece6b07d"
        },
        "date": 1779443447887,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "compiled_total_ms_n2_llm100_tool0",
            "value": 0.20514200002708094,
            "unit": "ms",
            "extra": "min=0.18ms max=0.23ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n2_llm100_tool0",
            "value": 0.1416540000036548,
            "unit": "ms",
            "extra": "min=0.12ms max=0.17ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm200_tool0",
            "value": 0.27779800001326294,
            "unit": "ms",
            "extra": "min=0.26ms max=0.32ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm200_tool0",
            "value": 0.1638469999534209,
            "unit": "ms",
            "extra": "min=0.15ms max=0.20ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n10_llm200_tool10",
            "value": 101.99445500001048,
            "unit": "ms",
            "extra": "min=101.92ms max=102.12ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n10_llm200_tool10",
            "value": 0.37135200000193436,
            "unit": "ms",
            "extra": "min=0.37ms max=0.43ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm500_tool50",
            "value": 251.27372999997988,
            "unit": "ms",
            "extra": "min=251.19ms max=251.42ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm500_tool50",
            "value": 0.2916330000175549,
            "unit": "ms",
            "extra": "min=0.27ms max=0.31ms repeats=5"
          }
        ]
      },
      {
        "commit": {
          "author": {
            "email": "diogo.ansantos@nos.pt",
            "name": "Diogo Andre Santos",
            "username": "dgenio"
          },
          "committer": {
            "email": "diogo.ansantos@nos.pt",
            "name": "Diogo Andre Santos",
            "username": "dgenio"
          },
          "distinct": true,
          "id": "ceaf0250cf3cf7cfa2019f7dacfacc7664fb40d1",
          "message": "chore: release v0.8.0",
          "timestamp": "2026-05-22T11:01:57+01:00",
          "tree_id": "e8d74c83b979e1c69d7b683abb8209f9901d92aa",
          "url": "https://github.com/dgenio/ChainWeaver/commit/ceaf0250cf3cf7cfa2019f7dacfacc7664fb40d1"
        },
        "date": 1779444209842,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "compiled_total_ms_n2_llm100_tool0",
            "value": 0.1867049999759729,
            "unit": "ms",
            "extra": "min=0.17ms max=0.23ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n2_llm100_tool0",
            "value": 0.13073100001292914,
            "unit": "ms",
            "extra": "min=0.12ms max=0.17ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm200_tool0",
            "value": 0.24472000001196648,
            "unit": "ms",
            "extra": "min=0.24ms max=0.28ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm200_tool0",
            "value": 0.15700999998102816,
            "unit": "ms",
            "extra": "min=0.15ms max=0.18ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n10_llm200_tool10",
            "value": 101.99501600001781,
            "unit": "ms",
            "extra": "min=101.92ms max=102.36ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n10_llm200_tool10",
            "value": 0.3795590000379434,
            "unit": "ms",
            "extra": "min=0.37ms max=0.46ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm500_tool50",
            "value": 251.62768199999164,
            "unit": "ms",
            "extra": "min=251.62ms max=251.66ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm500_tool50",
            "value": 0.36685000003444657,
            "unit": "ms",
            "extra": "min=0.36ms max=0.39ms repeats=5"
          }
        ]
      }
    ]
  }
}