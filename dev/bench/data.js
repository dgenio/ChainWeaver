window.BENCHMARK_DATA = {
  "lastUpdate": 1781755228841,
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
          "id": "0c0ffed3113535e2b9639610333aa8dfd40f02d5",
          "message": "Merge pull request #239 from dgenio/claude/github-issue-triage-q2WOB\n\nfeat: offline LLM-assisted flow compiler and description optimizer (#28, #100)",
          "timestamp": "2026-06-02T13:13:42+01:00",
          "tree_id": "31e17ea043eeced906a2527d6ab766ecc0b6343d",
          "url": "https://github.com/dgenio/ChainWeaver/commit/0c0ffed3113535e2b9639610333aa8dfd40f02d5"
        },
        "date": 1780402499168,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "compiled_total_ms_n2_llm100_tool0",
            "value": 0.21140499995908613,
            "unit": "ms",
            "extra": "min=0.20ms max=0.26ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n2_llm100_tool0",
            "value": 0.13604300011138548,
            "unit": "ms",
            "extra": "min=0.13ms max=0.18ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm200_tool0",
            "value": 0.3127360000689805,
            "unit": "ms",
            "extra": "min=0.29ms max=0.49ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm200_tool0",
            "value": 0.17081999999390973,
            "unit": "ms",
            "extra": "min=0.17ms max=0.38ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n10_llm200_tool10",
            "value": 101.7731009999352,
            "unit": "ms",
            "extra": "min=101.46ms max=102.21ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n10_llm200_tool10",
            "value": 0.38435999977082247,
            "unit": "ms",
            "extra": "min=0.29ms max=0.41ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm500_tool50",
            "value": 251.45028200006436,
            "unit": "ms",
            "extra": "min=251.34ms max=251.52ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm500_tool50",
            "value": 0.3444349998744656,
            "unit": "ms",
            "extra": "min=0.30ms max=0.39ms repeats=5"
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
          "id": "589a6c28bfdb83224399d8456f735c32e42cc118",
          "message": "Merge pull request #240 from dgenio/claude/github-issue-triage-BoJ2y\n\nfeat: runtime flow learning — ChainObserver, `chainweaver record`, ChainWeaverService (#78, #226, #101)",
          "timestamp": "2026-06-02T16:49:25+01:00",
          "tree_id": "d03cecb646f899e0f3e23d5aeb0a2866c614c630",
          "url": "https://github.com/dgenio/ChainWeaver/commit/589a6c28bfdb83224399d8456f735c32e42cc118"
        },
        "date": 1780415445541,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "compiled_total_ms_n2_llm100_tool0",
            "value": 0.2103439999245893,
            "unit": "ms",
            "extra": "min=0.18ms max=0.43ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n2_llm100_tool0",
            "value": 0.1277330002267263,
            "unit": "ms",
            "extra": "min=0.12ms max=0.36ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm200_tool0",
            "value": 0.2728019999267417,
            "unit": "ms",
            "extra": "min=0.24ms max=0.31ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm200_tool0",
            "value": 0.15226400000756257,
            "unit": "ms",
            "extra": "min=0.14ms max=0.17ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n10_llm200_tool10",
            "value": 102.51669100000527,
            "unit": "ms",
            "extra": "min=102.28ms max=102.69ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n10_llm200_tool10",
            "value": 0.4891649998626235,
            "unit": "ms",
            "extra": "min=0.40ms max=0.58ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm500_tool50",
            "value": 251.63396499999635,
            "unit": "ms",
            "extra": "min=251.52ms max=252.05ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm500_tool50",
            "value": 0.35809400003472547,
            "unit": "ms",
            "extra": "min=0.33ms max=0.58ms repeats=5"
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
          "id": "d4c53beffba010b96f4b3710e8fc0fd419686c5e",
          "message": "Merge pull request #241 from dgenio/claude/github-issue-triage-qFVUO\n\nfeat: real Weaver Stack interop via weaver-contracts (#233, #234)",
          "timestamp": "2026-06-02T20:27:58+01:00",
          "tree_id": "196fae30c3f175936a4b7ef5ab4a77de32a4a893",
          "url": "https://github.com/dgenio/ChainWeaver/commit/d4c53beffba010b96f4b3710e8fc0fd419686c5e"
        },
        "date": 1780428564795,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "compiled_total_ms_n2_llm100_tool0",
            "value": 0.1859970000168687,
            "unit": "ms",
            "extra": "min=0.14ms max=0.38ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n2_llm100_tool0",
            "value": 0.11821900000086316,
            "unit": "ms",
            "extra": "min=0.08ms max=0.31ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm200_tool0",
            "value": 0.31591900000194073,
            "unit": "ms",
            "extra": "min=0.29ms max=0.38ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm200_tool0",
            "value": 0.1699659999871983,
            "unit": "ms",
            "extra": "min=0.15ms max=0.20ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n10_llm200_tool10",
            "value": 102.08414600000992,
            "unit": "ms",
            "extra": "min=102.05ms max=102.12ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n10_llm200_tool10",
            "value": 0.4007700000272507,
            "unit": "ms",
            "extra": "min=0.38ms max=0.44ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm500_tool50",
            "value": 251.1283250000247,
            "unit": "ms",
            "extra": "min=251.03ms max=251.21ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm500_tool50",
            "value": 0.2480660000401258,
            "unit": "ms",
            "extra": "min=0.24ms max=0.44ms repeats=5"
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
          "id": "caa301e63436c4657c99a6494e03660bdee23ea5",
          "message": "Merge pull request #242 from dgenio/claude/github-issue-triage-PQvr5\n\nfeat: chainweaver serve MCP server + integrations distribution (#230, #231)",
          "timestamp": "2026-06-03T06:42:07+01:00",
          "tree_id": "e9f2f94e8787a37bb2209e2f4cba9eac1f0554e1",
          "url": "https://github.com/dgenio/ChainWeaver/commit/caa301e63436c4657c99a6494e03660bdee23ea5"
        },
        "date": 1780465401735,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "compiled_total_ms_n2_llm100_tool0",
            "value": 0.20276499998317377,
            "unit": "ms",
            "extra": "min=0.18ms max=0.42ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n2_llm100_tool0",
            "value": 0.14518799991947162,
            "unit": "ms",
            "extra": "min=0.12ms max=0.37ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm200_tool0",
            "value": 0.29809800003022247,
            "unit": "ms",
            "extra": "min=0.28ms max=0.31ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm200_tool0",
            "value": 0.18536900006438373,
            "unit": "ms",
            "extra": "min=0.15ms max=0.20ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n10_llm200_tool10",
            "value": 102.01519399998915,
            "unit": "ms",
            "extra": "min=101.95ms max=102.03ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n10_llm200_tool10",
            "value": 0.40508899991209546,
            "unit": "ms",
            "extra": "min=0.39ms max=0.41ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm500_tool50",
            "value": 251.42439800004013,
            "unit": "ms",
            "extra": "min=251.32ms max=251.52ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm500_tool50",
            "value": 0.31569500015393714,
            "unit": "ms",
            "extra": "min=0.29ms max=0.49ms repeats=5"
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
          "id": "d266f6fd1ea44658105ab0046a28cb1a76a05556",
          "message": "Merge pull request #245 from dgenio/claude/github-issue-triage-qSsEf\n\nfeat: chainweaver-action emits PR annotations + CI flow validation (#149)",
          "timestamp": "2026-06-03T08:03:42+01:00",
          "tree_id": "102bfadd041d4a67275f735bd3653f65c1056632",
          "url": "https://github.com/dgenio/ChainWeaver/commit/d266f6fd1ea44658105ab0046a28cb1a76a05556"
        },
        "date": 1780470296435,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "compiled_total_ms_n2_llm100_tool0",
            "value": 0.22465800003601544,
            "unit": "ms",
            "extra": "min=0.18ms max=0.41ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n2_llm100_tool0",
            "value": 0.16226400009600184,
            "unit": "ms",
            "extra": "min=0.12ms max=0.35ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm200_tool0",
            "value": 0.27425199999697725,
            "unit": "ms",
            "extra": "min=0.25ms max=0.31ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm200_tool0",
            "value": 0.1696840000136035,
            "unit": "ms",
            "extra": "min=0.15ms max=0.19ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n10_llm200_tool10",
            "value": 102.00203499999816,
            "unit": "ms",
            "extra": "min=101.97ms max=102.07ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n10_llm200_tool10",
            "value": 0.3857400000697453,
            "unit": "ms",
            "extra": "min=0.38ms max=0.41ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm500_tool50",
            "value": 251.39923799997632,
            "unit": "ms",
            "extra": "min=251.32ms max=251.59ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm500_tool50",
            "value": 0.3162339999107644,
            "unit": "ms",
            "extra": "min=0.31ms max=0.54ms repeats=5"
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
          "id": "838428daf20e615ff2f946c5b32fdadd300f9058",
          "message": "Merge pull request #246 from dgenio/claude/github-issue-triage-GGNsn\n\nfeat(mcp): migrate FlowServer to standalone fastmcp 3.x (#243)",
          "timestamp": "2026-06-03T21:38:01+01:00",
          "tree_id": "0581c9749df16863911ef52f312a8061745d0d81",
          "url": "https://github.com/dgenio/ChainWeaver/commit/838428daf20e615ff2f946c5b32fdadd300f9058"
        },
        "date": 1780519174420,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "compiled_total_ms_n2_llm100_tool0",
            "value": 0.22244900000600865,
            "unit": "ms",
            "extra": "min=0.16ms max=0.39ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n2_llm100_tool0",
            "value": 0.14621500002931498,
            "unit": "ms",
            "extra": "min=0.10ms max=0.33ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm200_tool0",
            "value": 0.31264899999428053,
            "unit": "ms",
            "extra": "min=0.26ms max=0.40ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm200_tool0",
            "value": 0.166764000027797,
            "unit": "ms",
            "extra": "min=0.15ms max=0.21ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n10_llm200_tool10",
            "value": 101.96924300001342,
            "unit": "ms",
            "extra": "min=101.39ms max=102.23ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n10_llm200_tool10",
            "value": 0.3707699999324632,
            "unit": "ms",
            "extra": "min=0.28ms max=0.43ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm500_tool50",
            "value": 251.67125400000145,
            "unit": "ms",
            "extra": "min=251.35ms max=251.84ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm500_tool50",
            "value": 0.3540989999351041,
            "unit": "ms",
            "extra": "min=0.31ms max=0.52ms repeats=5"
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
          "id": "e0931210704b757f2325a9ac7c3ea4c34c28306d",
          "message": "Merge pull request #249 from dgenio/claude/github-issues-triage-SaFUt\n\nfeat: lesson candidates from traces (#210) + ecosystem-validation research (#17)",
          "timestamp": "2026-06-04T12:25:08+01:00",
          "tree_id": "0271cf6647671356baab82163c1f299de960c506",
          "url": "https://github.com/dgenio/ChainWeaver/commit/e0931210704b757f2325a9ac7c3ea4c34c28306d"
        },
        "date": 1780572391132,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "compiled_total_ms_n2_llm100_tool0",
            "value": 0.17709999997350678,
            "unit": "ms",
            "extra": "min=0.16ms max=0.24ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n2_llm100_tool0",
            "value": 0.1050040000336594,
            "unit": "ms",
            "extra": "min=0.09ms max=0.16ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm200_tool0",
            "value": 0.3499929999861706,
            "unit": "ms",
            "extra": "min=0.26ms max=0.46ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm200_tool0",
            "value": 0.17393499990703276,
            "unit": "ms",
            "extra": "min=0.14ms max=0.22ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n10_llm200_tool10",
            "value": 102.10039499997947,
            "unit": "ms",
            "extra": "min=102.03ms max=102.17ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n10_llm200_tool10",
            "value": 0.3848980001066593,
            "unit": "ms",
            "extra": "min=0.37ms max=0.42ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm500_tool50",
            "value": 251.24619900009293,
            "unit": "ms",
            "extra": "min=251.10ms max=251.39ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm500_tool50",
            "value": 0.28684400001566246,
            "unit": "ms",
            "extra": "min=0.25ms max=0.34ms repeats=5"
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
          "id": "6c70d73ba64c1b733e551d3271fade19d229a09c",
          "message": "Merge pull request #247 from dgenio/dependabot/github_actions/main/peter-evans/create-pull-request-8\n\nbuild(deps): bump peter-evans/create-pull-request from 7 to 8",
          "timestamp": "2026-06-04T22:44:50+01:00",
          "tree_id": "09f5dc1de8d94288bd3cc87797076b9077a320a8",
          "url": "https://github.com/dgenio/ChainWeaver/commit/6c70d73ba64c1b733e551d3271fade19d229a09c"
        },
        "date": 1780609586677,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "compiled_total_ms_n2_llm100_tool0",
            "value": 0.2116670000305021,
            "unit": "ms",
            "extra": "min=0.17ms max=0.31ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n2_llm100_tool0",
            "value": 0.13141599981736363,
            "unit": "ms",
            "extra": "min=0.11ms max=0.22ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm200_tool0",
            "value": 0.33671199992113543,
            "unit": "ms",
            "extra": "min=0.26ms max=0.45ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm200_tool0",
            "value": 0.1548410000395961,
            "unit": "ms",
            "extra": "min=0.15ms max=0.20ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n10_llm200_tool10",
            "value": 102.0381460000408,
            "unit": "ms",
            "extra": "min=101.99ms max=102.33ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n10_llm200_tool10",
            "value": 0.38837800025248725,
            "unit": "ms",
            "extra": "min=0.37ms max=0.41ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm500_tool50",
            "value": 251.50012000005972,
            "unit": "ms",
            "extra": "min=251.46ms max=251.70ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm500_tool50",
            "value": 0.33037000002877903,
            "unit": "ms",
            "extra": "min=0.32ms max=0.35ms repeats=5"
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
          "id": "950a008fa4159be1d199052232ee1d0cea9b9e07",
          "message": "Merge pull request #248 from dgenio/dependabot/github_actions/main/actions/upload-artifact-7\n\nbuild(deps): bump actions/upload-artifact from 4 to 7",
          "timestamp": "2026-06-04T22:45:06+01:00",
          "tree_id": "a8a49b700f42b0f30212c69a94a83814c0f2a280",
          "url": "https://github.com/dgenio/ChainWeaver/commit/950a008fa4159be1d199052232ee1d0cea9b9e07"
        },
        "date": 1780609693936,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "compiled_total_ms_n2_llm100_tool0",
            "value": 0.0708970000005138,
            "unit": "ms",
            "extra": "min=0.07ms max=0.12ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n2_llm100_tool0",
            "value": 0.04382500000588152,
            "unit": "ms",
            "extra": "min=0.04ms max=0.09ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm200_tool0",
            "value": 0.15171900000154892,
            "unit": "ms",
            "extra": "min=0.12ms max=0.24ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm200_tool0",
            "value": 0.08364699999674485,
            "unit": "ms",
            "extra": "min=0.07ms max=0.09ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n10_llm200_tool10",
            "value": 101.18006300000104,
            "unit": "ms",
            "extra": "min=100.98ms max=101.26ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n10_llm200_tool10",
            "value": 0.21370200002479578,
            "unit": "ms",
            "extra": "min=0.19ms max=0.23ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm500_tool50",
            "value": 250.67291799999225,
            "unit": "ms",
            "extra": "min=250.66ms max=250.69ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm500_tool50",
            "value": 0.16209500002162258,
            "unit": "ms",
            "extra": "min=0.16ms max=0.17ms repeats=5"
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
          "id": "7b5d48f7d483b0fe6d825269fb6c2abb525355aa",
          "message": "Merge pull request #251 from dgenio/claude/github-issues-triage-j0u0X\n\nfix(mcp): resolve [mcp] extra in registry manifest fresh-client launch (#250)",
          "timestamp": "2026-06-05T05:54:25+01:00",
          "tree_id": "77fa6d598890d529971d08e32a325546eab478af",
          "url": "https://github.com/dgenio/ChainWeaver/commit/7b5d48f7d483b0fe6d825269fb6c2abb525355aa"
        },
        "date": 1780635350176,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "compiled_total_ms_n2_llm100_tool0",
            "value": 0.21616500021082174,
            "unit": "ms",
            "extra": "min=0.19ms max=0.24ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n2_llm100_tool0",
            "value": 0.12905299968224426,
            "unit": "ms",
            "extra": "min=0.11ms max=0.15ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm200_tool0",
            "value": 0.3173340001012548,
            "unit": "ms",
            "extra": "min=0.29ms max=0.50ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm200_tool0",
            "value": 0.1688569998350431,
            "unit": "ms",
            "extra": "min=0.16ms max=0.19ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n10_llm200_tool10",
            "value": 102.10054899994248,
            "unit": "ms",
            "extra": "min=102.04ms max=102.36ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n10_llm200_tool10",
            "value": 0.39104400002543116,
            "unit": "ms",
            "extra": "min=0.38ms max=0.41ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm500_tool50",
            "value": 251.11256900004264,
            "unit": "ms",
            "extra": "min=251.09ms max=251.20ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm500_tool50",
            "value": 0.2437579998968431,
            "unit": "ms",
            "extra": "min=0.22ms max=0.26ms repeats=5"
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
          "id": "dc100b5c19d79eee88c27ab37bf102c5668c7284",
          "message": "Merge pull request #252 from dgenio/claude/copilot-agent-setup-dF6Jg\n\nfeat(playground): interactive zero-install Streamlit playground (#81)",
          "timestamp": "2026-06-05T06:56:21+01:00",
          "tree_id": "1990add65cbc74420d1d21c289aec48494fe97b3",
          "url": "https://github.com/dgenio/ChainWeaver/commit/dc100b5c19d79eee88c27ab37bf102c5668c7284"
        },
        "date": 1780639057065,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "compiled_total_ms_n2_llm100_tool0",
            "value": 0.20607899999447454,
            "unit": "ms",
            "extra": "min=0.18ms max=0.26ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n2_llm100_tool0",
            "value": 0.14376599999366135,
            "unit": "ms",
            "extra": "min=0.13ms max=0.19ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm200_tool0",
            "value": 0.2675019999998085,
            "unit": "ms",
            "extra": "min=0.25ms max=0.40ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm200_tool0",
            "value": 0.15821699999207794,
            "unit": "ms",
            "extra": "min=0.15ms max=0.18ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n10_llm200_tool10",
            "value": 102.05291399999794,
            "unit": "ms",
            "extra": "min=101.99ms max=102.19ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n10_llm200_tool10",
            "value": 0.3792290000177445,
            "unit": "ms",
            "extra": "min=0.38ms max=0.40ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm500_tool50",
            "value": 251.4313540000046,
            "unit": "ms",
            "extra": "min=251.10ms max=251.52ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm500_tool50",
            "value": 0.3067319999843221,
            "unit": "ms",
            "extra": "min=0.28ms max=0.33ms repeats=5"
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
          "id": "013b71530fdee64ad8419f283b2d153afd2a6825",
          "message": "release: bump version to 0.12.0\n\n- pyproject.toml: 0.11.0 -> 0.12.0\n\n- chainweaver/__init__.py: __version__ 0.11.0 -> 0.12.0\n\n- server.json: MCP manifest version 0.11.0 -> 0.12.0\n\n- CHANGELOG.md: promote [Unreleased] to [0.12.0] - 2026-06-08\n\n- .github/actions/chainweaver: action.yml default + README examples 0.11.0 -> 0.12.0\n\n- docs/github-action.md: version references 0.11.0 -> 0.12.0\n\n- docs/SPEC_COMPAT.md: weaver-contracts version 0.6.0 -> 0.7.0",
          "timestamp": "2026-06-08T06:37:02+01:00",
          "tree_id": "c59f26f6fdd544a8857150e24c653fa56165dc7b",
          "url": "https://github.com/dgenio/ChainWeaver/commit/013b71530fdee64ad8419f283b2d153afd2a6825"
        },
        "date": 1780897162263,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "compiled_total_ms_n2_llm100_tool0",
            "value": 0.2192729999705989,
            "unit": "ms",
            "extra": "min=0.20ms max=0.27ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n2_llm100_tool0",
            "value": 0.15416799999456998,
            "unit": "ms",
            "extra": "min=0.14ms max=0.20ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm200_tool0",
            "value": 0.27218200000334036,
            "unit": "ms",
            "extra": "min=0.26ms max=0.43ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm200_tool0",
            "value": 0.16338999978415814,
            "unit": "ms",
            "extra": "min=0.16ms max=0.18ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n10_llm200_tool10",
            "value": 102.63831800000389,
            "unit": "ms",
            "extra": "min=102.11ms max=102.88ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n10_llm200_tool10",
            "value": 0.5018199998403361,
            "unit": "ms",
            "extra": "min=0.44ms max=0.57ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm500_tool50",
            "value": 251.8403630000421,
            "unit": "ms",
            "extra": "min=251.71ms max=251.87ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm500_tool50",
            "value": 0.39028499986670795,
            "unit": "ms",
            "extra": "min=0.38ms max=0.39ms repeats=5"
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
          "id": "c14116f6893977c5705d4f5234537b464fd3698c",
          "message": "Merge pull request #310 from dgenio/codex/fix-230-mcp-registry-publish\n\n[codex] Fix MCP registry publication prerequisites",
          "timestamp": "2026-06-08T09:13:02+01:00",
          "tree_id": "59f9e56879f2c686924f640c4ddc4cdc8b04b1ee",
          "url": "https://github.com/dgenio/ChainWeaver/commit/c14116f6893977c5705d4f5234537b464fd3698c"
        },
        "date": 1780906466555,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "compiled_total_ms_n2_llm100_tool0",
            "value": 0.1814630000467332,
            "unit": "ms",
            "extra": "min=0.16ms max=0.21ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n2_llm100_tool0",
            "value": 0.12728100006142995,
            "unit": "ms",
            "extra": "min=0.11ms max=0.16ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm200_tool0",
            "value": 0.2138919999765676,
            "unit": "ms",
            "extra": "min=0.21ms max=0.35ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm200_tool0",
            "value": 0.13201700005538441,
            "unit": "ms",
            "extra": "min=0.13ms max=0.15ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n10_llm200_tool10",
            "value": 101.75989900000104,
            "unit": "ms",
            "extra": "min=101.74ms max=102.08ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n10_llm200_tool10",
            "value": 0.33712700002297424,
            "unit": "ms",
            "extra": "min=0.33ms max=0.39ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm500_tool50",
            "value": 251.27373599997327,
            "unit": "ms",
            "extra": "min=251.24ms max=251.33ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm500_tool50",
            "value": 0.2698960000770967,
            "unit": "ms",
            "extra": "min=0.27ms max=0.29ms repeats=5"
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
          "id": "444e1fcf151e3e2ae90bc4324c34f99d435f02e5",
          "message": "Merge pull request #303 from dgenio/feat/259-governed-mcp-flows\n\nAdd governed macro-flow safety and MCP exposure",
          "timestamp": "2026-06-08T12:11:48+01:00",
          "tree_id": "dcb323c1c2a099541a150190bb97cfd78706d768",
          "url": "https://github.com/dgenio/ChainWeaver/commit/444e1fcf151e3e2ae90bc4324c34f99d435f02e5"
        },
        "date": 1780917197170,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "compiled_total_ms_n2_llm100_tool0",
            "value": 0.17048000017894083,
            "unit": "ms",
            "extra": "min=0.16ms max=0.24ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n2_llm100_tool0",
            "value": 0.1029019999805314,
            "unit": "ms",
            "extra": "min=0.09ms max=0.16ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm200_tool0",
            "value": 0.3396170000087295,
            "unit": "ms",
            "extra": "min=0.32ms max=0.55ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm200_tool0",
            "value": 0.16709200008335756,
            "unit": "ms",
            "extra": "min=0.16ms max=0.18ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n10_llm200_tool10",
            "value": 101.99853800031633,
            "unit": "ms",
            "extra": "min=101.98ms max=102.11ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n10_llm200_tool10",
            "value": 0.37983099991834024,
            "unit": "ms",
            "extra": "min=0.37ms max=0.38ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm500_tool50",
            "value": 251.10225699972943,
            "unit": "ms",
            "extra": "min=251.04ms max=251.19ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm500_tool50",
            "value": 0.24296499987030984,
            "unit": "ms",
            "extra": "min=0.23ms max=0.27ms repeats=5"
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
          "id": "edf1b6bd2c0ac40c35b3655d1dfaf8eca292b334",
          "message": "Merge pull request #327 from dgenio/feat/304-release-automation\n\nAutomate release and distribution workflows",
          "timestamp": "2026-06-09T10:23:45+01:00",
          "tree_id": "cdf918c34b1ad13f005e69462aafcbefdf8cf59f",
          "url": "https://github.com/dgenio/ChainWeaver/commit/edf1b6bd2c0ac40c35b3655d1dfaf8eca292b334"
        },
        "date": 1780997118768,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "compiled_total_ms_n2_llm100_tool0",
            "value": 0.1959170000418453,
            "unit": "ms",
            "extra": "min=0.18ms max=0.26ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n2_llm100_tool0",
            "value": 0.12434800009941682,
            "unit": "ms",
            "extra": "min=0.12ms max=0.20ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm200_tool0",
            "value": 0.27186099998743884,
            "unit": "ms",
            "extra": "min=0.25ms max=0.46ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm200_tool0",
            "value": 0.15528400001585396,
            "unit": "ms",
            "extra": "min=0.15ms max=0.19ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n10_llm200_tool10",
            "value": 102.00526400001309,
            "unit": "ms",
            "extra": "min=101.97ms max=102.04ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n10_llm200_tool10",
            "value": 0.38001800021447707,
            "unit": "ms",
            "extra": "min=0.37ms max=0.41ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm500_tool50",
            "value": 251.39099900002293,
            "unit": "ms",
            "extra": "min=251.29ms max=251.45ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm500_tool50",
            "value": 0.328768999793283,
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
          "id": "81d5841b6ccf2ae4f44c98967a31baa6521587b6",
          "message": "Merge pull request #329 from dgenio/claude/github-issues-triage-w8jkez\n\nfeat: coding-agent macro-flow compilation pipeline (#253 cluster)",
          "timestamp": "2026-06-09T17:39:10+01:00",
          "tree_id": "5fa1f7d0e86f1ae1118e15462aac87e81e035904",
          "url": "https://github.com/dgenio/ChainWeaver/commit/81d5841b6ccf2ae4f44c98967a31baa6521587b6"
        },
        "date": 1781023233674,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "compiled_total_ms_n2_llm100_tool0",
            "value": 0.227745000017876,
            "unit": "ms",
            "extra": "min=0.19ms max=0.43ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n2_llm100_tool0",
            "value": 0.13786400000981303,
            "unit": "ms",
            "extra": "min=0.13ms max=0.19ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm200_tool0",
            "value": 0.2795219999711662,
            "unit": "ms",
            "extra": "min=0.27ms max=0.33ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm200_tool0",
            "value": 0.16352099993355296,
            "unit": "ms",
            "extra": "min=0.16ms max=0.20ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n10_llm200_tool10",
            "value": 101.98433700003307,
            "unit": "ms",
            "extra": "min=101.94ms max=103.35ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n10_llm200_tool10",
            "value": 0.40553600001658197,
            "unit": "ms",
            "extra": "min=0.38ms max=0.41ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm500_tool50",
            "value": 251.39925600001334,
            "unit": "ms",
            "extra": "min=251.30ms max=251.72ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm500_tool50",
            "value": 0.32537900000306763,
            "unit": "ms",
            "extra": "min=0.31ms max=0.37ms repeats=5"
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
          "id": "9d07a03bacd6ea23641162b9412a741d978a8f4c",
          "message": "Merge pull request #383 from leno23/fix/source-context-errors-343\n\nInclude source context in loader errors",
          "timestamp": "2026-06-13T12:25:29+01:00",
          "tree_id": "4dfb705e73a9be331c1a95c84ba6a1283091e335",
          "url": "https://github.com/dgenio/ChainWeaver/commit/9d07a03bacd6ea23641162b9412a741d978a8f4c"
        },
        "date": 1781350013618,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "compiled_total_ms_n2_llm100_tool0",
            "value": 0.22597499997800696,
            "unit": "ms",
            "extra": "min=0.18ms max=0.44ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n2_llm100_tool0",
            "value": 0.1511939998977141,
            "unit": "ms",
            "extra": "min=0.12ms max=0.18ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm200_tool0",
            "value": 0.27255400004833064,
            "unit": "ms",
            "extra": "min=0.26ms max=0.28ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm200_tool0",
            "value": 0.15802500007566778,
            "unit": "ms",
            "extra": "min=0.15ms max=0.17ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n10_llm200_tool10",
            "value": 102.18653399999766,
            "unit": "ms",
            "extra": "min=102.00ms max=103.37ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n10_llm200_tool10",
            "value": 0.44611200002009355,
            "unit": "ms",
            "extra": "min=0.41ms max=0.47ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm500_tool50",
            "value": 251.64270999999871,
            "unit": "ms",
            "extra": "min=251.60ms max=251.77ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm500_tool50",
            "value": 0.36453100000244376,
            "unit": "ms",
            "extra": "min=0.35ms max=0.38ms repeats=5"
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
          "id": "aeffe8529c76a5d2fbcfb2af46ef2d85e5f81017",
          "message": "Merge pull request #384 from dgenio/claude/github-issues-triage-i4ov52\n\nHarden the FlowExecutor execution core (#330, #331, #332, #335, #336, #337, #344, #354)",
          "timestamp": "2026-06-13T17:26:32+01:00",
          "tree_id": "8d35348d550cb84f7f692077f238d792fb10f531",
          "url": "https://github.com/dgenio/ChainWeaver/commit/aeffe8529c76a5d2fbcfb2af46ef2d85e5f81017"
        },
        "date": 1781368079485,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "compiled_total_ms_n2_llm100_tool0",
            "value": 0.32039500001701526,
            "unit": "ms",
            "extra": "min=0.27ms max=1.56ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n2_llm100_tool0",
            "value": 0.2432609999232227,
            "unit": "ms",
            "extra": "min=0.20ms max=1.50ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm200_tool0",
            "value": 0.44021299999030816,
            "unit": "ms",
            "extra": "min=0.41ms max=0.46ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm200_tool0",
            "value": 0.29677099996661127,
            "unit": "ms",
            "extra": "min=0.28ms max=0.32ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n10_llm200_tool10",
            "value": 102.449149999984,
            "unit": "ms",
            "extra": "min=102.27ms max=102.56ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n10_llm200_tool10",
            "value": 0.8357680001154222,
            "unit": "ms",
            "extra": "min=0.80ms max=0.97ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm500_tool50",
            "value": 251.754668999979,
            "unit": "ms",
            "extra": "min=251.69ms max=251.81ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm500_tool50",
            "value": 0.6803399999171234,
            "unit": "ms",
            "extra": "min=0.66ms max=0.76ms repeats=5"
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
          "id": "ca1353531c2ff6bbfbe36c8d4e9aebe982000493",
          "message": "Merge pull request #385 from dgenio/claude/github-issues-triage-vo7u14\n\nfeat: MCP/ToolSafetyContract security hardening (#356, #357, #358, #359, #371)",
          "timestamp": "2026-06-13T21:37:46+01:00",
          "tree_id": "e289c8dcbdbd3bd0fe87526ede87c2348ca26be9",
          "url": "https://github.com/dgenio/ChainWeaver/commit/ca1353531c2ff6bbfbe36c8d4e9aebe982000493"
        },
        "date": 1781383152983,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "compiled_total_ms_n2_llm100_tool0",
            "value": 0.31895400002213137,
            "unit": "ms",
            "extra": "min=0.28ms max=0.45ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n2_llm100_tool0",
            "value": 0.23812300003100972,
            "unit": "ms",
            "extra": "min=0.19ms max=0.30ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm200_tool0",
            "value": 0.5030580000493501,
            "unit": "ms",
            "extra": "min=0.42ms max=0.58ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm200_tool0",
            "value": 0.3382789999477609,
            "unit": "ms",
            "extra": "min=0.28ms max=0.40ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n10_llm200_tool10",
            "value": 102.59715500001221,
            "unit": "ms",
            "extra": "min=102.54ms max=104.09ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n10_llm200_tool10",
            "value": 0.8540709999351748,
            "unit": "ms",
            "extra": "min=0.82ms max=1.44ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm500_tool50",
            "value": 251.98868299992228,
            "unit": "ms",
            "extra": "min=251.55ms max=252.03ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm500_tool50",
            "value": 0.7458810000571248,
            "unit": "ms",
            "extra": "min=0.54ms max=0.76ms repeats=5"
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
          "id": "4fef6e5c5acab63fc81909c6166cb84ae211306d",
          "message": "Merge pull request #451 from dgenio/claude/github-issues-triage-fnw055\n\nfeat: version serialized artifacts and add stable error codes (#390, #393, #394, #395)",
          "timestamp": "2026-06-14T17:18:41+01:00",
          "tree_id": "a1cd83bd9d981255e40203aa4981bf7d2e666105",
          "url": "https://github.com/dgenio/ChainWeaver/commit/4fef6e5c5acab63fc81909c6166cb84ae211306d"
        },
        "date": 1781453998722,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "compiled_total_ms_n2_llm100_tool0",
            "value": 0.3183469999612498,
            "unit": "ms",
            "extra": "min=0.29ms max=1.69ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n2_llm100_tool0",
            "value": 0.23258799990344414,
            "unit": "ms",
            "extra": "min=0.22ms max=1.62ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm200_tool0",
            "value": 0.41553299990937376,
            "unit": "ms",
            "extra": "min=0.41ms max=0.59ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm200_tool0",
            "value": 0.29247799989207124,
            "unit": "ms",
            "extra": "min=0.29ms max=0.47ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n10_llm200_tool10",
            "value": 102.7179210000213,
            "unit": "ms",
            "extra": "min=102.59ms max=103.38ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n10_llm200_tool10",
            "value": 0.9373059999688849,
            "unit": "ms",
            "extra": "min=0.87ms max=1.24ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm500_tool50",
            "value": 252.05795600004421,
            "unit": "ms",
            "extra": "min=251.88ms max=252.22ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm500_tool50",
            "value": 0.8029629999555254,
            "unit": "ms",
            "extra": "min=0.72ms max=0.87ms repeats=5"
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
          "id": "ec096157cb62774c80f808e7b78e9663031119ac",
          "message": "Merge pull request #455 from dgenio/fix/338-fallback-input-validation\n\nfix: validate fallback inputs against fallback schema",
          "timestamp": "2026-06-15T17:27:48+01:00",
          "tree_id": "991fff903a54ca1a9353339e5e81e0e79a345cbb",
          "url": "https://github.com/dgenio/ChainWeaver/commit/ec096157cb62774c80f808e7b78e9663031119ac"
        },
        "date": 1781540961323,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "compiled_total_ms_n2_llm100_tool0",
            "value": 0.3249459999778992,
            "unit": "ms",
            "extra": "min=0.29ms max=0.44ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n2_llm100_tool0",
            "value": 0.23057000009885087,
            "unit": "ms",
            "extra": "min=0.21ms max=0.35ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm200_tool0",
            "value": 0.5045399999517031,
            "unit": "ms",
            "extra": "min=0.45ms max=1.95ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm200_tool0",
            "value": 0.3377179999688451,
            "unit": "ms",
            "extra": "min=0.31ms max=0.34ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n10_llm200_tool10",
            "value": 102.89078900007098,
            "unit": "ms",
            "extra": "min=102.25ms max=103.32ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n10_llm200_tool10",
            "value": 0.9770330000264948,
            "unit": "ms",
            "extra": "min=0.78ms max=1.20ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm500_tool50",
            "value": 252.03842500002338,
            "unit": "ms",
            "extra": "min=251.93ms max=252.20ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm500_tool50",
            "value": 0.7809570001882093,
            "unit": "ms",
            "extra": "min=0.72ms max=0.86ms repeats=5"
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
          "id": "6714de4a68adb2188da9f7a90973199c9479469e",
          "message": "Merge pull request #454 from dgenio/claude/github-issues-triage-l0z4mx\n\nfeat(flow): FlowStep output_mapping, JSON-pointer input_mapping, dynamic params",
          "timestamp": "2026-06-15T20:50:35+01:00",
          "tree_id": "80506945e251de6e9bef19a0a238ff09488e1fe5",
          "url": "https://github.com/dgenio/ChainWeaver/commit/6714de4a68adb2188da9f7a90973199c9479469e"
        },
        "date": 1781553127062,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "compiled_total_ms_n2_llm100_tool0",
            "value": 0.25616800002126183,
            "unit": "ms",
            "extra": "min=0.20ms max=0.30ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n2_llm100_tool0",
            "value": 0.21025800000984418,
            "unit": "ms",
            "extra": "min=0.16ms max=0.25ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm200_tool0",
            "value": 0.3285280000113744,
            "unit": "ms",
            "extra": "min=0.31ms max=0.49ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm200_tool0",
            "value": 0.24608500001477296,
            "unit": "ms",
            "extra": "min=0.23ms max=0.41ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n10_llm200_tool10",
            "value": 101.52657999998382,
            "unit": "ms",
            "extra": "min=101.28ms max=103.28ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n10_llm200_tool10",
            "value": 0.5003180000358043,
            "unit": "ms",
            "extra": "min=0.41ms max=1.21ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm500_tool50",
            "value": 251.5022540000018,
            "unit": "ms",
            "extra": "min=251.21ms max=251.82ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm500_tool50",
            "value": 0.6243249999897671,
            "unit": "ms",
            "extra": "min=0.51ms max=0.68ms repeats=5"
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
          "id": "dea89d8ec7b9d09f5e65f88a0f12dd08ca721c4e",
          "message": "Merge pull request #461 from dgenio/docs/352-reconcile-v1-criteria\n\nReconcile v1 release criteria with shipped capabilities",
          "timestamp": "2026-06-16T06:52:24+01:00",
          "tree_id": "ea982394ce5f2b80ef27a035bc4018cb170fc6db",
          "url": "https://github.com/dgenio/ChainWeaver/commit/dea89d8ec7b9d09f5e65f88a0f12dd08ca721c4e"
        },
        "date": 1781589236344,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "compiled_total_ms_n2_llm100_tool0",
            "value": 0.36610600000130944,
            "unit": "ms",
            "extra": "min=0.31ms max=0.52ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n2_llm100_tool0",
            "value": 0.27407200002471654,
            "unit": "ms",
            "extra": "min=0.24ms max=0.42ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm200_tool0",
            "value": 0.6347079999500238,
            "unit": "ms",
            "extra": "min=0.50ms max=0.75ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm200_tool0",
            "value": 0.4051880000588426,
            "unit": "ms",
            "extra": "min=0.35ms max=0.58ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n10_llm200_tool10",
            "value": 103.89756699998998,
            "unit": "ms",
            "extra": "min=103.75ms max=104.46ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n10_llm200_tool10",
            "value": 1.541493999980048,
            "unit": "ms",
            "extra": "min=1.39ms max=1.60ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm500_tool50",
            "value": 252.4075619999735,
            "unit": "ms",
            "extra": "min=252.26ms max=252.56ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm500_tool50",
            "value": 0.9588920000851431,
            "unit": "ms",
            "extra": "min=0.88ms max=1.10ms repeats=5"
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
          "id": "ac1d4e72e184542e52313b27d7d8e426e4bebbf6",
          "message": "Merge pull request #382 from leno23/refactor/step-index-sentinels-339\n\nReplace flow validation step-index sentinels with named API",
          "timestamp": "2026-06-18T04:59:07+01:00",
          "tree_id": "150c5cd29c4f7d908c7a3f67c91114ce1751c6c3",
          "url": "https://github.com/dgenio/ChainWeaver/commit/ac1d4e72e184542e52313b27d7d8e426e4bebbf6"
        },
        "date": 1781755228556,
        "tool": "customSmallerIsBetter",
        "benches": [
          {
            "name": "compiled_total_ms_n2_llm100_tool0",
            "value": 0.3223249999990685,
            "unit": "ms",
            "extra": "min=0.31ms max=0.44ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n2_llm100_tool0",
            "value": 0.2512979999949039,
            "unit": "ms",
            "extra": "min=0.24ms max=0.37ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm200_tool0",
            "value": 0.46863400000063393,
            "unit": "ms",
            "extra": "min=0.46ms max=0.53ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm200_tool0",
            "value": 0.3324190000029148,
            "unit": "ms",
            "extra": "min=0.33ms max=0.40ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n10_llm200_tool10",
            "value": 102.46582300000284,
            "unit": "ms",
            "extra": "min=102.22ms max=102.58ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n10_llm200_tool10",
            "value": 0.8976379999836581,
            "unit": "ms",
            "extra": "min=0.83ms max=0.91ms repeats=5"
          },
          {
            "name": "compiled_total_ms_n5_llm500_tool50",
            "value": 251.90747599999952,
            "unit": "ms",
            "extra": "min=251.84ms max=252.08ms repeats=5"
          },
          {
            "name": "compiled_overhead_ms_n5_llm500_tool50",
            "value": 0.7927310000184207,
            "unit": "ms",
            "extra": "min=0.72ms max=0.81ms repeats=5"
          }
        ]
      }
    ]
  }
}