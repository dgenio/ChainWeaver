window.BENCHMARK_DATA = {
  "lastUpdate": 1780377116297,
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
          "id": "b2cb5b9218a5cf7756ab80e0f3597a27c420f9b0",
          "message": "chore(release): cut 0.9.0",
          "timestamp": "2026-05-27T18:09:51+01:00",
          "tree_id": "72972affb6a19884c7b22314c42941b02533cccd",
          "url": "https://github.com/dgenio/ChainWeaver/commit/b2cb5b9218a5cf7756ab80e0f3597a27c420f9b0"
        },
        "date": 1779901890805,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "compiled_total_ms_n2_llm100_tool0",
            "value": 0.21130100003574626,
            "unit": "ms",
            "extra": "min=0.20ms max=0.26ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n2_llm100_tool0",
            "value": 0.1451680000172928,
            "unit": "ms",
            "extra": "min=0.13ms max=0.18ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm200_tool0",
            "value": 0.2772640000330284,
            "unit": "ms",
            "extra": "min=0.25ms max=0.31ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm200_tool0",
            "value": 0.15603799988639366,
            "unit": "ms",
            "extra": "min=0.14ms max=0.16ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n10_llm200_tool10",
            "value": 102.28101100005915,
            "unit": "ms",
            "extra": "min=102.09ms max=103.03ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n10_llm200_tool10",
            "value": 0.42858399979195383,
            "unit": "ms",
            "extra": "min=0.39ms max=0.65ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm500_tool50",
            "value": 251.30597599991233,
            "unit": "ms",
            "extra": "min=251.00ms max=251.51ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm500_tool50",
            "value": 0.2796560002025217,
            "unit": "ms",
            "extra": "min=0.22ms max=0.35ms repeats=5"
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
          "id": "8023de026bf2ee534ebad6a20d2b27ca6771ddc0",
          "message": "Merge pull request #185 from dgenio/claude/triage-issues-6cBPH\n\nfeat: ecosystem & adapter surface — plugins, contrib, export, integrations (#25, #82, #130, #145)",
          "timestamp": "2026-05-27T20:15:02+01:00",
          "tree_id": "7e8bfbca6129614c05d0f8108ff0bef3cbf1f337",
          "url": "https://github.com/dgenio/ChainWeaver/commit/8023de026bf2ee534ebad6a20d2b27ca6771ddc0"
        },
        "date": 1779909376119,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "compiled_total_ms_n2_llm100_tool0",
            "value": 0.18792399998801557,
            "unit": "ms",
            "extra": "min=0.16ms max=0.21ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n2_llm100_tool0",
            "value": 0.11234999999487627,
            "unit": "ms",
            "extra": "min=0.11ms max=0.15ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm200_tool0",
            "value": 0.2934039999900051,
            "unit": "ms",
            "extra": "min=0.28ms max=0.31ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm200_tool0",
            "value": 0.1794010001958668,
            "unit": "ms",
            "extra": "min=0.15ms max=0.20ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n10_llm200_tool10",
            "value": 101.93117599999368,
            "unit": "ms",
            "extra": "min=101.91ms max=101.98ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n10_llm200_tool10",
            "value": 0.35974399975202687,
            "unit": "ms",
            "extra": "min=0.35ms max=0.38ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm500_tool50",
            "value": 251.32536499995695,
            "unit": "ms",
            "extra": "min=251.24ms max=251.38ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm500_tool50",
            "value": 0.28674299994690955,
            "unit": "ms",
            "extra": "min=0.28ms max=0.31ms repeats=5"
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
          "id": "0be80ad7b28e187e2e809dbb9736df494b40836f",
          "message": "Merge pull request #186 from dgenio/claude/github-issues-triage-2PNQe\n\nfeat: add chainweaver.testing + record_then_replay + pytest plugin (#132, #153)",
          "timestamp": "2026-05-27T22:53:28+01:00",
          "tree_id": "4db95d8c295030170d26c4e8e4025ec79dd5fb64",
          "url": "https://github.com/dgenio/ChainWeaver/commit/0be80ad7b28e187e2e809dbb9736df494b40836f"
        },
        "date": 1779918876847,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "compiled_total_ms_n2_llm100_tool0",
            "value": 0.19376199998077936,
            "unit": "ms",
            "extra": "min=0.19ms max=0.25ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n2_llm100_tool0",
            "value": 0.12318099999220067,
            "unit": "ms",
            "extra": "min=0.12ms max=0.17ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm200_tool0",
            "value": 0.2890119999960916,
            "unit": "ms",
            "extra": "min=0.23ms max=0.47ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm200_tool0",
            "value": 0.15677199996844138,
            "unit": "ms",
            "extra": "min=0.13ms max=0.19ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n10_llm200_tool10",
            "value": 102.00553199999263,
            "unit": "ms",
            "extra": "min=101.91ms max=102.06ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n10_llm200_tool10",
            "value": 0.364972999989277,
            "unit": "ms",
            "extra": "min=0.35ms max=0.38ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm500_tool50",
            "value": 251.34445499998037,
            "unit": "ms",
            "extra": "min=251.28ms max=251.45ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm500_tool50",
            "value": 0.28987199999619406,
            "unit": "ms",
            "extra": "min=0.28ms max=0.30ms repeats=5"
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
          "id": "23472ffef66897a4dd4ac76771e6634143c75b63",
          "message": "Merge pull request #214 from dgenio/claude/github-issues-triage-dJX0Y\n\ndocs: sync onboarding docs with shipped v0.9.0 CLI and Flow schema",
          "timestamp": "2026-05-28T06:22:23+01:00",
          "tree_id": "89178b875fd8219eb7a8bac782eb28f2176122a8",
          "url": "https://github.com/dgenio/ChainWeaver/commit/23472ffef66897a4dd4ac76771e6634143c75b63"
        },
        "date": 1779945828956,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "compiled_total_ms_n2_llm100_tool0",
            "value": 0.1879320000170992,
            "unit": "ms",
            "extra": "min=0.17ms max=0.29ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n2_llm100_tool0",
            "value": 0.11984600007508561,
            "unit": "ms",
            "extra": "min=0.11ms max=0.20ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm200_tool0",
            "value": 0.28676700003416045,
            "unit": "ms",
            "extra": "min=0.24ms max=0.55ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm200_tool0",
            "value": 0.15782599996327917,
            "unit": "ms",
            "extra": "min=0.14ms max=0.17ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n10_llm200_tool10",
            "value": 103.00721900000553,
            "unit": "ms",
            "extra": "min=102.17ms max=103.27ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n10_llm200_tool10",
            "value": 0.5713900003456729,
            "unit": "ms",
            "extra": "min=0.42ms max=0.60ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm500_tool50",
            "value": 251.64747999997417,
            "unit": "ms",
            "extra": "min=251.55ms max=251.74ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm500_tool50",
            "value": 0.34332099994571763,
            "unit": "ms",
            "extra": "min=0.33ms max=0.38ms repeats=5"
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
          "id": "530174a76a631b1e4c03194b64852abb92ad45fb",
          "message": "chore: release 0.10.0",
          "timestamp": "2026-05-28T06:38:24+01:00",
          "tree_id": "e2bebd9c2f5fea42706857583b250487f60859cd",
          "url": "https://github.com/dgenio/ChainWeaver/commit/530174a76a631b1e4c03194b64852abb92ad45fb"
        },
        "date": 1779946785402,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "compiled_total_ms_n2_llm100_tool0",
            "value": 0.14817599998195874,
            "unit": "ms",
            "extra": "min=0.13ms max=0.19ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n2_llm100_tool0",
            "value": 0.08674199997926735,
            "unit": "ms",
            "extra": "min=0.08ms max=0.12ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm200_tool0",
            "value": 0.2548250000131702,
            "unit": "ms",
            "extra": "min=0.21ms max=0.49ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm200_tool0",
            "value": 0.13143499998591324,
            "unit": "ms",
            "extra": "min=0.12ms max=0.18ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n10_llm200_tool10",
            "value": 101.91945100001476,
            "unit": "ms",
            "extra": "min=101.89ms max=101.98ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n10_llm200_tool10",
            "value": 0.3374699999199038,
            "unit": "ms",
            "extra": "min=0.33ms max=0.35ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm500_tool50",
            "value": 251.02264800000285,
            "unit": "ms",
            "extra": "min=251.01ms max=251.08ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm500_tool50",
            "value": 0.21608299999797964,
            "unit": "ms",
            "extra": "min=0.21ms max=0.22ms repeats=5"
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
          "id": "b517c6c0859090c71f6e112bdd400c8745e73ae6",
          "message": "Merge pull request #216 from dgenio/claude/github-issues-triage-NUpLq\n\ndocs, test: harden newcomer onboarding (#194, #202, #203, #208, #209, #212)",
          "timestamp": "2026-05-28T18:10:01+01:00",
          "tree_id": "847909b25c66d274e153227471bd38115ae6100c",
          "url": "https://github.com/dgenio/ChainWeaver/commit/b517c6c0859090c71f6e112bdd400c8745e73ae6"
        },
        "date": 1779988274577,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "compiled_total_ms_n2_llm100_tool0",
            "value": 0.16752100000871906,
            "unit": "ms",
            "extra": "min=0.15ms max=0.18ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n2_llm100_tool0",
            "value": 0.10068199998158889,
            "unit": "ms",
            "extra": "min=0.10ms max=0.13ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm200_tool0",
            "value": 0.2307679999944412,
            "unit": "ms",
            "extra": "min=0.21ms max=0.42ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm200_tool0",
            "value": 0.1374039999859633,
            "unit": "ms",
            "extra": "min=0.12ms max=0.16ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n10_llm200_tool10",
            "value": 102.02460799999358,
            "unit": "ms",
            "extra": "min=101.74ms max=102.32ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n10_llm200_tool10",
            "value": 0.38003700001354446,
            "unit": "ms",
            "extra": "min=0.31ms max=0.44ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm500_tool50",
            "value": 251.56921399999987,
            "unit": "ms",
            "extra": "min=251.40ms max=251.81ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm500_tool50",
            "value": 0.3007109999941804,
            "unit": "ms",
            "extra": "min=0.30ms max=0.32ms repeats=5"
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
          "id": "d054f6182b5916b8e6ffe6c6e6c108affa95ea51",
          "message": "Merge pull request #219 from dgenio/claude/github-issues-triage-JofdQ\n\nfeat: add framework recipes and workflow-template examples (#204, #205, #206, #211, #213)",
          "timestamp": "2026-05-28T23:29:01+01:00",
          "tree_id": "99343bb1773733a794795a1c8b6265c6f0e08b1b",
          "url": "https://github.com/dgenio/ChainWeaver/commit/d054f6182b5916b8e6ffe6c6e6c108affa95ea51"
        },
        "date": 1780007416407,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "compiled_total_ms_n2_llm100_tool0",
            "value": 0.21874700001944802,
            "unit": "ms",
            "extra": "min=0.18ms max=0.24ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n2_llm100_tool0",
            "value": 0.15130100001670144,
            "unit": "ms",
            "extra": "min=0.11ms max=0.18ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm200_tool0",
            "value": 0.27791700000534547,
            "unit": "ms",
            "extra": "min=0.24ms max=0.43ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm200_tool0",
            "value": 0.15043799999148177,
            "unit": "ms",
            "extra": "min=0.14ms max=0.16ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n10_llm200_tool10",
            "value": 101.97960400000738,
            "unit": "ms",
            "extra": "min=101.95ms max=102.01ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n10_llm200_tool10",
            "value": 0.3545420000534705,
            "unit": "ms",
            "extra": "min=0.35ms max=0.36ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm500_tool50",
            "value": 251.5432249999776,
            "unit": "ms",
            "extra": "min=251.33ms max=251.82ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm500_tool50",
            "value": 0.32328000003190027,
            "unit": "ms",
            "extra": "min=0.28ms max=0.40ms repeats=5"
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
          "id": "6fd70ffe4e5994bd5b5cda193ad3fb6267d508ad",
          "message": "Release 0.11.0: framework recipes and workflow examples\n\n- Add framework recipes and workflow-template examples (#204-#213)\n- LangGraph and OpenAI Agents integration examples\n- Release readiness and policy evaluation DAG flows\n- Enhanced cookbook with smoke tests\n- Version bump: 0.10.0 -> 0.11.0",
          "timestamp": "2026-05-29T06:34:43+01:00",
          "tree_id": "5595de7757a7cea191107af4e4aa63fa2974c4dd",
          "url": "https://github.com/dgenio/ChainWeaver/commit/6fd70ffe4e5994bd5b5cda193ad3fb6267d508ad"
        },
        "date": 1780032963097,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "compiled_total_ms_n2_llm100_tool0",
            "value": 0.17184000000725064,
            "unit": "ms",
            "extra": "min=0.14ms max=0.23ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n2_llm100_tool0",
            "value": 0.10865300009754719,
            "unit": "ms",
            "extra": "min=0.09ms max=0.16ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm200_tool0",
            "value": 0.21816100002070016,
            "unit": "ms",
            "extra": "min=0.21ms max=0.38ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm200_tool0",
            "value": 0.12229499998284155,
            "unit": "ms",
            "extra": "min=0.12ms max=0.16ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n10_llm200_tool10",
            "value": 101.30087599998205,
            "unit": "ms",
            "extra": "min=101.25ms max=102.31ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n10_llm200_tool10",
            "value": 0.2736400000458161,
            "unit": "ms",
            "extra": "min=0.25ms max=0.61ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm500_tool50",
            "value": 251.02954100009356,
            "unit": "ms",
            "extra": "min=250.94ms max=251.32ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm500_tool50",
            "value": 0.2412840000260985,
            "unit": "ms",
            "extra": "min=0.23ms max=0.31ms repeats=5"
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
          "id": "3e3ac00af8637f60e3b40172012174b6250872b7",
          "message": "Merge pull request #223 from dgenio/claude/github-issues-triage-YrEz0\n\nfeat: add property-based fuzzing harness, trace minimization, and CLI (#220, #221, #222, #217)",
          "timestamp": "2026-05-29T22:06:37+01:00",
          "tree_id": "212ed202f18af50309e95731e4c7e9df0c7c852e",
          "url": "https://github.com/dgenio/ChainWeaver/commit/3e3ac00af8637f60e3b40172012174b6250872b7"
        },
        "date": 1780088866969,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "compiled_total_ms_n2_llm100_tool0",
            "value": 0.14003100000081758,
            "unit": "ms",
            "extra": "min=0.12ms max=0.25ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n2_llm100_tool0",
            "value": 0.08146199999714554,
            "unit": "ms",
            "extra": "min=0.07ms max=0.18ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm200_tool0",
            "value": 0.2745909999930518,
            "unit": "ms",
            "extra": "min=0.26ms max=0.45ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm200_tool0",
            "value": 0.14781499999116932,
            "unit": "ms",
            "extra": "min=0.14ms max=0.17ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n10_llm200_tool10",
            "value": 101.94664000000841,
            "unit": "ms",
            "extra": "min=101.83ms max=101.98ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n10_llm200_tool10",
            "value": 0.35057200004473543,
            "unit": "ms",
            "extra": "min=0.32ms max=0.36ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm500_tool50",
            "value": 251.03791199998682,
            "unit": "ms",
            "extra": "min=250.96ms max=251.11ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm500_tool50",
            "value": 0.2267619999827275,
            "unit": "ms",
            "extra": "min=0.22ms max=0.24ms repeats=5"
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
          "id": "741a4b4143c32ad5113912f7764db5c9b2fdd041",
          "message": "Merge pull request #224 from dgenio/claude/github-issues-triage-SnIJB\n\nfeat: benchmark evidence + maintained provider price table (#103, #156, #207)",
          "timestamp": "2026-05-30T23:08:06+01:00",
          "tree_id": "3e7a3796c4377bbccf75228d43f1af9c1a787472",
          "url": "https://github.com/dgenio/ChainWeaver/commit/741a4b4143c32ad5113912f7764db5c9b2fdd041"
        },
        "date": 1780178958615,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "compiled_total_ms_n2_llm100_tool0",
            "value": 0.20181799999363648,
            "unit": "ms",
            "extra": "min=0.18ms max=0.22ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n2_llm100_tool0",
            "value": 0.12808899998617562,
            "unit": "ms",
            "extra": "min=0.12ms max=0.16ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm200_tool0",
            "value": 0.26506200003950653,
            "unit": "ms",
            "extra": "min=0.25ms max=0.47ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm200_tool0",
            "value": 0.1505549999478717,
            "unit": "ms",
            "extra": "min=0.15ms max=0.18ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n10_llm200_tool10",
            "value": 101.98876800001244,
            "unit": "ms",
            "extra": "min=101.67ms max=102.19ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n10_llm200_tool10",
            "value": 0.3757260000156748,
            "unit": "ms",
            "extra": "min=0.37ms max=0.42ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm500_tool50",
            "value": 251.34508600001482,
            "unit": "ms",
            "extra": "min=251.32ms max=251.61ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm500_tool50",
            "value": 0.31881099999964135,
            "unit": "ms",
            "extra": "min=0.29ms max=0.38ms repeats=5"
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
          "id": "fbeb500f059e30e7e97f3b85319044a6fb0667c6",
          "message": "Merge pull request #235 from dgenio/claude/github-issues-triage-yqaJj\n\nfeat: README/landing-page conversion overhaul (#225, #227, #228, #229, #232)",
          "timestamp": "2026-05-31T21:39:06+01:00",
          "tree_id": "50e59bd62504089cb5215d22f9d7835d1c4e455f",
          "url": "https://github.com/dgenio/ChainWeaver/commit/fbeb500f059e30e7e97f3b85319044a6fb0667c6"
        },
        "date": 1780260045489,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "compiled_total_ms_n2_llm100_tool0",
            "value": 0.14522099999680904,
            "unit": "ms",
            "extra": "min=0.13ms max=0.20ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n2_llm100_tool0",
            "value": 0.08283600004688196,
            "unit": "ms",
            "extra": "min=0.07ms max=0.14ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm200_tool0",
            "value": 0.3035569999951804,
            "unit": "ms",
            "extra": "min=0.28ms max=0.35ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm200_tool0",
            "value": 0.16020900002899907,
            "unit": "ms",
            "extra": "min=0.15ms max=0.21ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n10_llm200_tool10",
            "value": 102.01200200003768,
            "unit": "ms",
            "extra": "min=101.72ms max=102.06ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n10_llm200_tool10",
            "value": 0.36058400007732416,
            "unit": "ms",
            "extra": "min=0.31ms max=0.37ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm500_tool50",
            "value": 251.10891600002105,
            "unit": "ms",
            "extra": "min=251.08ms max=251.13ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm500_tool50",
            "value": 0.2460480001218457,
            "unit": "ms",
            "extra": "min=0.23ms max=0.28ms repeats=5"
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
          "id": "ab521f0a58a4be0ae1ac028afd470b6d17ceaa05",
          "message": "Merge pull request #237 from dgenio/claude/github-issues-triage-Hz5C3\n\nbuild: Python 3.14 support + library-grade dependency floors (#215, #236)",
          "timestamp": "2026-06-01T20:59:33+01:00",
          "tree_id": "a4fc631f4fd1af9b675bbb7a366c337810ca6fe1",
          "url": "https://github.com/dgenio/ChainWeaver/commit/ab521f0a58a4be0ae1ac028afd470b6d17ceaa05"
        },
        "date": 1780344052134,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "compiled_total_ms_n2_llm100_tool0",
            "value": 0.19826000001899047,
            "unit": "ms",
            "extra": "min=0.17ms max=0.24ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n2_llm100_tool0",
            "value": 0.12666500001046188,
            "unit": "ms",
            "extra": "min=0.11ms max=0.17ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm200_tool0",
            "value": 0.27984299998706774,
            "unit": "ms",
            "extra": "min=0.25ms max=0.33ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm200_tool0",
            "value": 0.15351799999052673,
            "unit": "ms",
            "extra": "min=0.15ms max=0.19ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n10_llm200_tool10",
            "value": 101.97518399999694,
            "unit": "ms",
            "extra": "min=101.88ms max=102.18ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n10_llm200_tool10",
            "value": 0.36572499996623264,
            "unit": "ms",
            "extra": "min=0.34ms max=0.40ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm500_tool50",
            "value": 251.06438100002038,
            "unit": "ms",
            "extra": "min=251.02ms max=251.63ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm500_tool50",
            "value": 0.22340700002132508,
            "unit": "ms",
            "extra": "min=0.21ms max=0.38ms repeats=5"
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
          "id": "507024a355a3297972be6092b01f49ddb7ab98a0",
          "message": "Merge pull request #238 from dgenio/claude/github-issue-triage-i4Iv1\n\nfeat(executor): version-targeted execution, flow cancellation, and flow composition (#201, #142, #75)",
          "timestamp": "2026-06-02T06:10:40+01:00",
          "tree_id": "b58250fb8d5a0aa80f890afdc511cb54e41b4277",
          "url": "https://github.com/dgenio/ChainWeaver/commit/507024a355a3297972be6092b01f49ddb7ab98a0"
        },
        "date": 1780377115774,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "compiled_total_ms_n2_llm100_tool0",
            "value": 0.17335500001536275,
            "unit": "ms",
            "extra": "min=0.15ms max=0.29ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n2_llm100_tool0",
            "value": 0.10530800000196905,
            "unit": "ms",
            "extra": "min=0.08ms max=0.21ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm200_tool0",
            "value": 0.3343769999446522,
            "unit": "ms",
            "extra": "min=0.31ms max=0.46ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm200_tool0",
            "value": 0.17889499963530398,
            "unit": "ms",
            "extra": "min=0.17ms max=0.22ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n10_llm200_tool10",
            "value": 102.10679300007541,
            "unit": "ms",
            "extra": "min=101.94ms max=102.16ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n10_llm200_tool10",
            "value": 0.43194199975005176,
            "unit": "ms",
            "extra": "min=0.38ms max=0.47ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm500_tool50",
            "value": 251.16021400003774,
            "unit": "ms",
            "extra": "min=251.08ms max=251.31ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm500_tool50",
            "value": 0.26724099984676286,
            "unit": "ms",
            "extra": "min=0.27ms max=0.30ms repeats=5"
          }
        ]
      }
    ]
  }
}