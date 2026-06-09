# Distribution & ecosystem listings

ChainWeaver's discovery strategy is **passive reach**: be listed where its exact
audience already looks — the MCP ecosystem and the major agent-framework
integration directories. This page records what CI verifies and which external
submissions remain maintainer-owned.

The in-repo artifacts (the [`serve` command](cli.md#serve), the
[MCP server guide](mcp-server.md), the [`server.json`](#mcp-registry) manifest,
and the verified recipes below) are maintained here. Release metadata is
prepared by `scripts/release.py` and verified after publication by
`.github/workflows/distribution-check.yml`.

## Automated via CI

| Check | Automation | Failure behavior |
|---|---|---|
| Version consistency | `python scripts/release.py check` | Release preparation and publication stop on drift. |
| PyPI publication | `publish.yml` with trusted publishing | Publication must succeed before distribution verification starts. |
| PyPI propagation | `release.py verify-pypi` with bounded retries | Distribution check fails if the exact version never resolves. |
| MCP manifest | Official `mcp-publisher validate server.json` | Live registry-schema or semantic validation failures are reported. |
| GitHub Action default | Release consistency check | The default must match the package and manifest version. |
| Released Action smoke | Local action at the release SHA with the exact published version | Invalid installation or flow validation fails the distribution check. |

The pre-publish `action-smoke.yml` workflow deliberately passes an empty
`chainweaver-version`, so it tests action changes against the latest package
already available on PyPI. The exact new pin is tested only after publication.

## Manual / asynchronous

External repositories and marketplaces require maintainer identity, review, or
interactive publication. CI reports these items but does not impersonate a
maintainer.

| Item | Status | Tracker |
|---|---|---|
| Publish the MCP Registry entry and submit awesome-list PRs | Manual | [#325](https://github.com/dgenio/ChainWeaver/issues/325) |
| Submit LangGraph/LangChain, OpenAI Agents SDK, and LlamaIndex listings | Manual | [#231](https://github.com/dgenio/ChainWeaver/issues/231) |
| Publish the validation Action in GitHub Marketplace | Manual | [#325](https://github.com/dgenio/ChainWeaver/issues/325) |

## Post-release status

Generate the status block included in release PRs and workflow summaries:

```bash
python scripts/release.py status
```

The output records the current version, governed-reference consistency,
configured automation, and tracker links for every manual item. The
post-publish workflow appends live PyPI, manifest, and Action results to the
GitHub Actions job summary.

## Verified integration matrix

Recipes and the MCP server are verified runnable against these versions
(`python examples/...` + `pytest tests/test_integrations_*.py tests/test_mcp_server.py`):

| Integration | Entry point | Verified against |
|---|---|---|
| MCP server (outbound) | `chainweaver serve` / `chainweaver.mcp.FlowServer` | `fastmcp` 3.4.0 (+ `mcp` 1.27.2 for the inbound adapter) |
| LangGraph node | `examples/integrations/langgraph_node.py`, [recipe](cookbook/langgraph-node.md) | `langgraph` 1.2.4 |
| OpenAI Agents SDK tool | `examples/integrations/openai_agents_tool.py`, [recipe](cookbook/openai-agents-tool.md) | `openai-agents` 0.17.4 |
| LangChain bridge | `chainweaver.integrations.langchain` | `langchain-core` 1.4.0 |
| LlamaIndex bridge | `chainweaver.integrations.llamaindex` | `llama-index-core` 0.14.22 |

Re-run the verification before each submission and update this table with the
versions tested.

## MCP registry

A draft manifest ships at the repo root as
[`server.json`](https://github.com/dgenio/ChainWeaver/blob/main/server.json),
conforming to the
[`2025-12-11` server schema](https://static.modelcontextprotocol.io/schemas/2025-12-11/server.schema.json).

`server.json` carries a `--from 'chainweaver[mcp]'` `uvx` runtime argument plus
a required `flow_file` positional. `tests/test_server_manifest.py` guards the
launch contract, and `README.md` carries the required PyPI ownership marker.
The post-release workflow confirms the exact package is live on
[PyPI](https://pypi.org/project/chainweaver/) and validates the manifest with
the official [`mcp-publisher`](https://github.com/modelcontextprotocol/registry)
tool before a maintainer performs the tracked registry submission.

Fresh-client verification command:

```bash
uvx --from 'chainweaver[mcp]==<VERSION>' chainweaver serve \
  examples/double_add_format.flow.yaml --tools examples.simple_linear_flow
```

## awesome-* lists

Open a PR adding ChainWeaver to each list. Suggested entry:

> **[ChainWeaver](https://github.com/dgenio/ChainWeaver)** — Deterministic
> orchestration layer for MCP agents. Compiles tool sequences into schema-validated
> flows and exposes each flow as a single MCP tool — no LLM at build or run time.

Targets:

- [`punkpeye/awesome-mcp-servers`](https://github.com/punkpeye/awesome-mcp-servers)
- `awesome-ai-agents`
- `awesome-llm-apps`

Submission status is tracked in [#325](https://github.com/dgenio/ChainWeaver/issues/325).

## Framework ecosystem directories

For each framework, verify the recipe against the current version (table above),
then submit to its community/integration surface:

- **LangGraph / LangChain** — community/ecosystem integration listing, linking
  [the LangGraph node recipe](cookbook/langgraph-node.md).
- **OpenAI Agents SDK** — community/showcase resources, linking
  [the OpenAI Agents tool recipe](cookbook/openai-agents-tool.md).
- **LlamaIndex** — integrations/community listing, linking the LlamaIndex
  bridge.

Progress is tracked in [#231](https://github.com/dgenio/ChainWeaver/issues/231).
Once a listing is accepted, link it from the README **Integrations** section.

## GitHub Marketplace (validation Action)

The repo ships a reusable composite Action at
[`.github/actions/chainweaver`](https://github.com/dgenio/ChainWeaver/tree/main/.github/actions/chainweaver)
that runs `chainweaver check` against a downstream repo's flow files and emits
inline PR annotations (see the [GitHub Action guide](github-action.md)). It is a
distribution surface in its own right: a single `uses:` line lets other repos
adopt flow validation.

CI confirms the action's default matches the published version and that the
release tag resolves to the tested merge commit. Marketplace publication is a
manual maintainer action tracked in [#325](https://github.com/dgenio/ChainWeaver/issues/325);
publish from the tagged release through
[GitHub Marketplace](https://docs.github.com/actions/creating-actions/publishing-actions-in-github-marketplace).
