window.BENCHMARK_DATA = {
  "lastUpdate": 1779900488068,
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
          "id": "797ad16d9d99415e3974852b5a4401c61556f6d8",
          "message": "Merge pull request #179 from dgenio/claude/triage-issues-W2BcC\n\nfeat: add doctor CLI, profile reliability aggregates, public registered_tools (#175, #176, #178)",
          "timestamp": "2026-05-25T11:47:24+01:00",
          "tree_id": "204164b5a0dcbf7bd22042674c5b941b8c0369a2",
          "url": "https://github.com/dgenio/ChainWeaver/commit/797ad16d9d99415e3974852b5a4401c61556f6d8"
        },
        "date": 1779706095248,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "compiled_total_ms_n2_llm100_tool0",
            "value": 0.1543189999893002,
            "unit": "ms",
            "extra": "min=0.14ms max=0.20ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n2_llm100_tool0",
            "value": 0.10092299999087118,
            "unit": "ms",
            "extra": "min=0.10ms max=0.14ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm200_tool0",
            "value": 0.21077499991406512,
            "unit": "ms",
            "extra": "min=0.19ms max=0.26ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm200_tool0",
            "value": 0.12203400001453701,
            "unit": "ms",
            "extra": "min=0.12ms max=0.14ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n10_llm200_tool10",
            "value": 101.80719899994983,
            "unit": "ms",
            "extra": "min=101.66ms max=102.04ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n10_llm200_tool10",
            "value": 0.34305700012282614,
            "unit": "ms",
            "extra": "min=0.31ms max=0.42ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm500_tool50",
            "value": 251.2905020000744,
            "unit": "ms",
            "extra": "min=251.19ms max=251.68ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm500_tool50",
            "value": 0.3076990001318336,
            "unit": "ms",
            "extra": "min=0.30ms max=0.34ms repeats=5"
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
          "id": "95afc12e031d2127af4fe4a615bcc9f4caee6f25",
          "message": "Merge pull request #181 from dgenio/claude/triage-issues-CtCU1\n\nfeat: authoring DX + typed contracts + JSON Schema for flow files",
          "timestamp": "2026-05-26T20:09:27+01:00",
          "tree_id": "8d03644181003d99ee308188566951e4c284b3fb",
          "url": "https://github.com/dgenio/ChainWeaver/commit/95afc12e031d2127af4fe4a615bcc9f4caee6f25"
        },
        "date": 1779822620983,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "compiled_total_ms_n2_llm100_tool0",
            "value": 0.17181700002311118,
            "unit": "ms",
            "extra": "min=0.14ms max=0.18ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n2_llm100_tool0",
            "value": 0.1267110000071625,
            "unit": "ms",
            "extra": "min=0.10ms max=0.14ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm200_tool0",
            "value": 0.2554530000224986,
            "unit": "ms",
            "extra": "min=0.20ms max=0.31ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm200_tool0",
            "value": 0.13683600008107533,
            "unit": "ms",
            "extra": "min=0.12ms max=0.17ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n10_llm200_tool10",
            "value": 101.5594559999613,
            "unit": "ms",
            "extra": "min=101.38ms max=102.18ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n10_llm200_tool10",
            "value": 0.3357229999210176,
            "unit": "ms",
            "extra": "min=0.28ms max=0.45ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm500_tool50",
            "value": 251.24841699999934,
            "unit": "ms",
            "extra": "min=251.15ms max=251.53ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm500_tool50",
            "value": 0.31469399999650705,
            "unit": "ms",
            "extra": "min=0.29ms max=0.36ms repeats=5"
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
          "id": "0e58f95e1213fd659ab5fe94b34986d6c030a910",
          "message": "Merge pull request #182 from dgenio/claude/triage-issues-JSgiS\n\nfeat: determinism + safety contracts, conditional branching, property tests",
          "timestamp": "2026-05-26T21:49:26+01:00",
          "tree_id": "8c1360db8d8008a97f91862d7840cafb43fe142a",
          "url": "https://github.com/dgenio/ChainWeaver/commit/0e58f95e1213fd659ab5fe94b34986d6c030a910"
        },
        "date": 1779828620394,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "compiled_total_ms_n2_llm100_tool0",
            "value": 0.14956199993321206,
            "unit": "ms",
            "extra": "min=0.14ms max=0.20ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n2_llm100_tool0",
            "value": 0.097428999879412,
            "unit": "ms",
            "extra": "min=0.10ms max=0.14ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm200_tool0",
            "value": 0.2033129999290395,
            "unit": "ms",
            "extra": "min=0.20ms max=0.23ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm200_tool0",
            "value": 0.12219399991408864,
            "unit": "ms",
            "extra": "min=0.12ms max=0.14ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n10_llm200_tool10",
            "value": 101.51409900004182,
            "unit": "ms",
            "extra": "min=101.33ms max=101.78ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n10_llm200_tool10",
            "value": 0.27615999965746596,
            "unit": "ms",
            "extra": "min=0.24ms max=0.34ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm500_tool50",
            "value": 251.47593200017582,
            "unit": "ms",
            "extra": "min=251.08ms max=251.57ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm500_tool50",
            "value": 0.2985749999879772,
            "unit": "ms",
            "extra": "min=0.26ms max=0.36ms repeats=5"
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
          "id": "1b252d59a9821eb4c76e2893c9f7b0871a8b7ab9",
          "message": "Merge pull request #183 from dgenio/claude/triage-issues-pNfax\n\nfeat: Weaver Stack boundary alignment — capability identity, decisions, kernel backend (#89, #90, #91, #102, #106, #107)",
          "timestamp": "2026-05-27T11:30:17+01:00",
          "tree_id": "c56df6c0ccccafae636fc9c17ebf2af9b5458910",
          "url": "https://github.com/dgenio/ChainWeaver/commit/1b252d59a9821eb4c76e2893c9f7b0871a8b7ab9"
        },
        "date": 1779877872005,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "compiled_total_ms_n2_llm100_tool0",
            "value": 0.1718999999980042,
            "unit": "ms",
            "extra": "min=0.17ms max=0.22ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n2_llm100_tool0",
            "value": 0.11757699999748183,
            "unit": "ms",
            "extra": "min=0.11ms max=0.16ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm200_tool0",
            "value": 0.2512410000008458,
            "unit": "ms",
            "extra": "min=0.24ms max=0.29ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm200_tool0",
            "value": 0.1587999999941303,
            "unit": "ms",
            "extra": "min=0.15ms max=0.20ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n10_llm200_tool10",
            "value": 101.93035700000053,
            "unit": "ms",
            "extra": "min=101.40ms max=102.00ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n10_llm200_tool10",
            "value": 0.37679600001183644,
            "unit": "ms",
            "extra": "min=0.33ms max=0.38ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm500_tool50",
            "value": 251.33547000000078,
            "unit": "ms",
            "extra": "min=251.31ms max=251.55ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm500_tool50",
            "value": 0.3301149999970221,
            "unit": "ms",
            "extra": "min=0.30ms max=0.36ms repeats=5"
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
          "id": "4638331b9b92edfbe4d3b50dd88d4153576cf102",
          "message": "Merge pull request #184 from dgenio/claude/triage-issues-UcGHs\n\nfeat: MCP integration + async executor lane (#70, #72, #80, #150)",
          "timestamp": "2026-05-27T17:47:09+01:00",
          "tree_id": "3e60226bc55bfa0648e858dea8397ecacccd8261",
          "url": "https://github.com/dgenio/ChainWeaver/commit/4638331b9b92edfbe4d3b50dd88d4153576cf102"
        },
        "date": 1779900487743,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "compiled_total_ms_n2_llm100_tool0",
            "value": 0.1991850000138129,
            "unit": "ms",
            "extra": "min=0.17ms max=0.24ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n2_llm100_tool0",
            "value": 0.13803400003098432,
            "unit": "ms",
            "extra": "min=0.12ms max=0.17ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm200_tool0",
            "value": 0.25550800000928575,
            "unit": "ms",
            "extra": "min=0.25ms max=0.27ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm200_tool0",
            "value": 0.14614700000947778,
            "unit": "ms",
            "extra": "min=0.14ms max=0.17ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n10_llm200_tool10",
            "value": 102.00820500000418,
            "unit": "ms",
            "extra": "min=101.70ms max=102.40ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n10_llm200_tool10",
            "value": 0.3814329999158872,
            "unit": "ms",
            "extra": "min=0.34ms max=0.48ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm500_tool50",
            "value": 251.60430700000802,
            "unit": "ms",
            "extra": "min=251.42ms max=251.69ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm500_tool50",
            "value": 0.3428069999813488,
            "unit": "ms",
            "extra": "min=0.32ms max=0.36ms repeats=5"
          }
        ]
      }
    ]
  }
}