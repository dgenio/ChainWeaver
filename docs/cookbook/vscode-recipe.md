# VS Code / Copilot: observe → suggest → compile → expose

VS Code with GitHub Copilot supports **MCP servers**, so ChainWeaver can expose
reviewed macro-flows back to the editor as high-level MCP tools. Unlike Claude
Code and OpenCode, VS Code / Copilot has **no `PostToolUse`-style hook**, so
passive observation works a little differently — but the observe → suggest →
compile → expose loop is otherwise the same.

This recipe uses only local files; no live external services are required.

> **What ChainWeaver is vs. isn't here.** ChainWeaver removes *repeated,
> model-mediated decisions* between predictable tool steps — not model judgement
> itself. Only deterministic, read-mostly paths should be compiled.

The FlowServer commands are reversible and default to a **dry run**; nothing is
written until you pass `--write`, and every write backs the original up to
`<file>.bak`. The observe step writes **nothing** — it prints a snippet you opt
into.

---

## 0. Doctor — inspect what's configured

```bash
chainweaver doctor vscode --workspace .
```

Read-only. It reports `.vscode/mcp.json` servers, whether a ChainWeaver
FlowServer is exposed, the trace directory, and discoverable macro-flows.

## 1. Set up observe mode

VS Code / Copilot exposes no writable hook for ChainWeaver, so observe mode has
two portable pieces.

**(a) Route Copilot's telemetry to a sink (manual, opt-in).** GitHub Copilot
Chat can export its telemetry — including tool calls — to a JSONL file via its
OpenTelemetry file exporter. Because those keys are a product-level setting on
an evolving surface, ChainWeaver **prints** the snippet rather than writing it:

```bash
chainweaver vscode setup --observe --workspace .
```

Copy the printed keys into `.vscode/settings.json` (or your user settings):

```json
{
  "github.copilot.chat.otel.exporterType": "file",
  "github.copilot.chat.otel.outfile": ".chainweaver/traces/vscode.jsonl"
}
```

> These are workspace-local, personal settings. `.chainweaver/traces/` and your
> `.vscode/settings.json` OTel keys are things you generally do **not** commit.

**(b) Capture into a normalized trace.** Feed the exported JSONL (or any MCP
tool-call trace records) through `capture`, which **normalizes and redacts**
each tool call into the ChainWeaver trace sink:

```bash
# From the Copilot OTel export file:
chainweaver vscode capture --from copilot-otel.jsonl \
  --sink .chainweaver/traces/vscode.jsonl

# …or from stdin:
echo '{"tool":"github_get_pr","sessionId":"s1","args":{"repo":"acme/api"},
       "result":{"title":"Fix"}}' \
  | chainweaver vscode capture --sink .chainweaver/traces/vscode.jsonl
```

Capture is tolerant of shape: a flat tool-call record, or an
OpenTelemetry-style span whose tool name lives in a nested `attributes` map.
Redaction is on by default — secrets in arguments are masked and raw tool
outputs are not stored. Non-tool records are skipped; malformed input is
reported on stderr and never corrupts the sink.

## 2. Suggest candidate flows from the trace

```bash
chainweaver traces mine .chainweaver/traces/vscode.jsonl
```

Mined sequences are **suggestions, not trusted flows** — they carry support,
success rate, and savings estimates for review.

## 3. Draft, backtest, review, promote

```bash
chainweaver traces draft-flows .chainweaver/traces/vscode.jsonl --out .chainweaver/flows
chainweaver traces backtest .chainweaver/flows/<draft>.flow.yaml .chainweaver/traces/vscode.jsonl
chainweaver flows promote <flow-name>     # move draft → reviewed → active
```

Only **active** or **reviewed** flows are exposable next; drafts are withheld.

## 4. Expose active flows back to VS Code (MCP FlowServer)

```bash
chainweaver vscode setup --flows --dry-run --workspace . \
  --flows-dir .chainweaver/flows --tools your.tools.module
chainweaver vscode setup --flows --write   --workspace . \
  --flows-dir .chainweaver/flows --tools your.tools.module
```

This adds (or replaces) a single `chainweaver` entry under `servers` in
`.vscode/mcp.json` that runs `chainweaver serve` over the flows directory.
By default only **ACTIVE** flows are exposed (reviewed candidates are withheld
unless you pass `--include-reviewed`, which warns). Existing MCP servers are
preserved. Generated tool names are namespaced (`cw__<flow.name>`);
`setup --flows` refuses colliding names unless you pass `--allow-collisions`.

## 5. Revert

```bash
chainweaver vscode revert --flows --write --workspace .   # remove the MCP entry
chainweaver vscode revert --observe --workspace .         # prints how to undo (a)
```

`revert --flows` removes **only** the ChainWeaver `.vscode/mcp.json` entry,
preserving unrelated servers. Because ChainWeaver never wrote the Copilot OTel
keys, `revert --observe` only prints which keys to delete from
`.vscode/settings.json`.

---

## Safe vs. unsafe examples

- **Safe to compile:** read-only context gathering — e.g.
  `github.get_pr → github.list_files → github.get_file → summarize`.
- **Unsafe to compile:** edit/fix/refactor loops or anything whose next step
  depends on model judgement.

See also: [`chainweaver vscode`](https://github.com/dgenio/ChainWeaver/blob/main/chainweaver/cli/vscode.py),
[`chainweaver.vscode`](https://github.com/dgenio/ChainWeaver/blob/main/chainweaver/vscode.py),
and the [Claude Code recipe](claude-code-recipe.md).
