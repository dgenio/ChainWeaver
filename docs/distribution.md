# Distribution & ecosystem listings

ChainWeaver's immediate distribution strategy is **validation before amplification**.
The repository already has the technical artifacts needed for PyPI, MCP, framework
recipes, and a reusable GitHub Action. Broad ecosystem submission work remains useful,
but it must not outrun the product evidence in
[#553](https://github.com/dgenio/ChainWeaver/issues/553) or the final naming decision in
[#556](https://github.com/dgenio/ChainWeaver/issues/556).

During the validation phase, prioritize **qualified reach**:

- existing/inbound relationships with teams that operate real tool-using agents;
- integrations needed by a validation participant;
- reproducible technical artifacts that make evaluation easier;
- honest case studies, including negative/no-benefit outcomes.

Do not optimize directory count, stars, or a broad launch while the product category is
still falsifiable.

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

## Broad external submissions are gated

External repositories and marketplaces require maintainer identity, review, or
interactive publication. Those tasks remain tracked, but their priority is lower than
independent product/security validation.

Before a broad submission push, require:

1. enough #553 evidence to know which product job should be promoted;
2. the final keep/qualify/rename decision from #556;
3. README/docs claims that match the validated job;
4. at least one case study or independent integration that demonstrates real value;
5. no known release/security blocker that would turn discovery into a poor first
   experience.

| Item | Current posture | Tracker |
|---|---|---|
| Publish the MCP Registry entry and submit awesome-list PRs | Prepared, but broad push gated by #553/#556 | [#325](https://github.com/dgenio/ChainWeaver/issues/325) |
| Submit LangGraph/LangChain, OpenAI Agents SDK, and LlamaIndex listings | Recipes exist; broad push gated by #553/#556 | [#231](https://github.com/dgenio/ChainWeaver/issues/231) |
| Publish the validation Action in GitHub Marketplace | Technical artifact exists; publish when the validated story is stable | [#325](https://github.com/dgenio/ChainWeaver/issues/325) |

This does **not** prohibit a focused submission when it directly helps a validation
participant or produces credible external evidence. The distinction is between solving
a real adoption dependency and broadcasting an unvalidated category claim.

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

Recipes and the MCP server are verified runnable against the versions recorded by the
repository's integration tests and maintenance process. Re-run verification before an
external submission; do not use an old version table as a substitute for current CI.

| Integration | Entry point |
|---|---|
| MCP server (outbound) | `chainweaver serve` / `chainweaver.mcp.FlowServer` |
| LangGraph node | `examples/integrations/langgraph_node.py`, [recipe](cookbook/langgraph-node.md) |
| OpenAI Agents SDK tool | `examples/integrations/openai_agents_tool.py`, [recipe](cookbook/openai-agents-tool.md) |
| LangChain bridge | `chainweaver.integrations.langchain` |
| LlamaIndex bridge | `chainweaver.integrations.llamaindex` |

The product-validation work deliberately prefers **depth on the integrations used by
real participants** over increasing the adapter count.

## MCP Registry

A draft manifest ships at the repo root as
[`server.json`](https://github.com/dgenio/ChainWeaver/blob/main/server.json),
conforming to the registry schema version recorded in that artifact/test suite.

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

MCP is an important **interoperability surface**, not the whole product category. Most
valuable compiled capabilities may be private organization-specific tools that will
never belong in a public registry. Registry publication therefore cannot substitute for
real adoption evidence.

## awesome-* lists

Once the validation/name gates are satisfied, use an entry that reflects the **validated
product job** rather than the old generic workflow-engine framing.

Do not freeze suggested marketing copy here before #553: the project explicitly allows
the result to favor analyzer/compiler, combined lifecycle + runtime, or a narrower
runtime product.

Potential targets remain:

- [`punkpeye/awesome-mcp-servers`](https://github.com/punkpeye/awesome-mcp-servers)
- relevant AI-agent/application lists with real editorial relevance.

Submission status is tracked in [#325](https://github.com/dgenio/ChainWeaver/issues/325).
Do not mass-submit to low-signal catalogs solely to manufacture backlinks.

## Framework ecosystem directories

The existing recipes make framework-native evaluation possible. When #553 clarifies the
product story, submit only where the framework actually has a suitable community or
integration surface and the recipe has been reverified against the current release.

- **LangGraph / LangChain** — show ChainWeaver as an evidence/governance layer that can
  produce a deterministic capability callable from the existing graph, not as a claim
  that LangGraph cannot execute fixed workflows.
- **OpenAI Agents SDK** — show the same relationship to code orchestration/function
  tools.
- **LlamaIndex** — submit only if the bridge remains part of the validated adoption
  story.

Progress is tracked in [#231](https://github.com/dgenio/ChainWeaver/issues/231).
Once a listing is accepted, link it from the README **Integrations** section.

## GitHub Marketplace (validation Action)

The repo ships a reusable composite Action at
[`.github/actions/chainweaver`](https://github.com/dgenio/ChainWeaver/tree/main/.github/actions/chainweaver)
that runs `chainweaver check` against a downstream repo's flow files and emits
inline PR annotations (see the [GitHub Action guide](github-action.md)).

This can become a low-friction acquisition surface if downstream teams actually value
flow/artifact validation. Publish it when the surrounding product contract is stable
enough that the Action does not become an early compatibility promise by accident.
Marketplace publication remains a manual maintainer action tracked in
[#325](https://github.com/dgenio/ChainWeaver/issues/325).

## What success looks like

Distribution is working when it creates **qualified downstream behavior**:

- an independent team evaluates ChainWeaver on real traces;
- a project integrates a supported contract without maintainer implementation;
- an adopter returns for repeated use;
- a contributor adds a real scenario, integration, bug fix, or security review;
- a case study documents both value and limitations.

Stars and directory counts are lagging signals, not the operating target.
