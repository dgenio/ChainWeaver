# Distribution & ecosystem listings

ChainWeaver's discovery strategy is **passive reach**: be listed where its exact
audience already looks — the MCP ecosystem and the major agent-framework
integration directories. This page is the operational checklist for those
submissions, plus the prepared copy to paste into each one.

The in-repo artifacts (the [`serve` command](cli.md#serve), the
[MCP server guide](mcp-server.md), the [`server.json`](#mcp-registry) manifest, and
the verified recipes below) are maintained here. The external submissions are
maintainer actions in *other* projects' repos and are tracked by
[#230](https://github.com/dgenio/ChainWeaver/issues/230) and
[#231](https://github.com/dgenio/ChainWeaver/issues/231).

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

**Before submitting:**

- [x] Finalize the package launch in the manifest so a fresh client can start a
      working server: `server.json` now carries a `--from 'chainweaver[mcp]'`
      `uvx` runtime argument (resolving the `mcp` extra) plus a required
      `flow_file` positional. `tests/test_server_manifest.py` guards this.
- [ ] Publish the manifest's `version` (including the `mcp` extra) to PyPI so it
      resolves to an installable release. Confirm the version is live on
      [PyPI](https://pypi.org/project/chainweaver/) before publishing the
      manifest; see [#250](https://github.com/dgenio/ChainWeaver/issues/250).
- [ ] Validate and publish with the official
      [`mcp-publisher`](https://github.com/modelcontextprotocol/registry) tool —
      it validates `server.json` against the live schema on publish. Confirm the
      `version` field matches the published PyPI release first.

## awesome-* lists

Open a PR adding ChainWeaver to each list. Suggested entry:

> **[ChainWeaver](https://github.com/dgenio/ChainWeaver)** — Deterministic
> orchestration layer for MCP agents. Compiles tool sequences into schema-validated
> flows and exposes each flow as a single MCP tool — no LLM at build or run time.

- [ ] [`punkpeye/awesome-mcp-servers`](https://github.com/punkpeye/awesome-mcp-servers)
- [ ] `awesome-ai-agents`
- [ ] `awesome-llm-apps`

## Framework ecosystem directories

For each framework, verify the recipe against the current version (table above),
then submit to its community/integration surface:

- [ ] **LangGraph / LangChain** — community/ecosystem integration listing, linking
      [the LangGraph node recipe](cookbook/langgraph-node.md).
- [ ] **OpenAI Agents SDK** — community/showcase resources, linking
      [the OpenAI Agents tool recipe](cookbook/openai-agents-tool.md).
- [ ] **LlamaIndex** — integrations/community listing, linking the LlamaIndex
      bridge.

Once a listing is accepted, link it from the README **Integrations** section.

## GitHub Marketplace (validation Action)

The repo ships a reusable composite Action at
[`.github/actions/chainweaver`](https://github.com/dgenio/ChainWeaver/tree/main/.github/actions/chainweaver)
that runs `chainweaver check` against a downstream repo's flow files and emits
inline PR annotations (see the [GitHub Action guide](github-action.md)). It is a
distribution surface in its own right: a single `uses:` line lets other repos
adopt flow validation.

**Before submitting:**

- [ ] Confirm the action's `chainweaver-version` default matches the published
      PyPI release.
- [ ] Tag the release so `uses: dgenio/ChainWeaver/.github/actions/chainweaver@<tag>`
      resolves.
- [ ] Publish the Action to the
      [GitHub Marketplace](https://docs.github.com/actions/creating-actions/publishing-actions-in-github-marketplace)
      from the tagged release.
