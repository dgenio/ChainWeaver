# OpenCode: observe → suggest → compile → expose

OpenCode is a strong first integration target for ChainWeaver: it supports MCP
servers, plugins, custom tools, and — crucially — **plugin hooks around tool
execution**. That lets ChainWeaver *passively observe* the tool paths you
already run, mine the repeated ones into deterministic macro-flows, and expose
the reviewed flows back to OpenCode as high-level MCP tools.

This recipe walks the full loop using only local files — no live external
services are required.

> **Why OpenCode.** Unlike an MCP-only gateway, an OpenCode plugin can observe
> both MCP tools and OpenCode-native tools (when the event payload includes
> them), so the trace you mine reflects how the agent actually works.
>
> **What ChainWeaver is vs. isn't here.** ChainWeaver removes *repeated,
> model-mediated decisions* between predictable tool steps. It is not a
> reasoning engine — only deterministic, read-mostly paths should be compiled.
> Edit/fix/refactor loops that need model judgement should stay as agent loops.

The commands below are all reversible and default to a **dry run**; nothing is
written until you pass `--write`, and every write backs the original up to
`<file>.bak`.

---

## 0. Doctor — inspect what's configured

```bash
chainweaver doctor opencode --workspace .
```

Read-only. It reports the OpenCode config, whether a ChainWeaver FlowServer is
exposed, whether the observe plugin is installed, discoverable macro-flows, and
the trace directory.

## 1. Set up observe mode

Install the ChainWeaver observe plugin under `.opencode/plugin/`. Preview first:

```bash
chainweaver opencode setup --observe --dry-run --workspace .
chainweaver opencode setup --observe --write   --workspace .
```

The plugin is tiny and auditable: on each `tool.execute` event it pipes the
event to `chainweaver opencode capture`, which **normalizes and redacts** it
into a workspace-local JSONL sink (default
`.chainweaver/traces/opencode.jsonl`). Redaction is on by default — secrets in
arguments are masked and raw tool outputs are not stored.

Capture can also be driven directly (this is exactly what the plugin does):

```bash
echo '{"type":"tool.execute.after","tool":"github_get_pr","sessionID":"s1",
       "args":{"repo":"acme/api"},"result":{"title":"Fix"}}' \
  | chainweaver opencode capture --sink .chainweaver/traces/opencode.jsonl
```

What capture records per event: tool name, tool source (built-in / custom /
MCP, when available), redacted argument shape, result status, result field
names, latency, and session/turn ids. Non-tool events are skipped; malformed
input is reported on stderr and never corrupts the sink.

## 2. Suggest candidate flows from the trace

Mine repeated, successful tool paths and score them:

```bash
chainweaver traces mine .chainweaver/traces/opencode.jsonl
```

Mined sequences are **suggestions, not trusted flows** — they carry support,
success rate, latency, and token/call-savings estimates for review.

## 3. Draft, backtest, review, promote

```bash
chainweaver traces draft-flows .chainweaver/traces/opencode.jsonl --out .chainweaver/flows
chainweaver traces backtest .chainweaver/flows/<draft>.flow.yaml .chainweaver/traces/opencode.jsonl
chainweaver flows promote <flow-name>     # move draft → reviewed → active
```

Only flows whose governance lifecycle is **active** or **reviewed** are
exposable in the next step. Draft, suggested, ignored, and archived flows are
withheld by default.

## 4. Expose reviewed flows back to OpenCode (MCP FlowServer)

```bash
chainweaver opencode setup --flows --dry-run --workspace . \
  --flows-dir .chainweaver/flows --tools your.tools.module
chainweaver opencode setup --flows --write   --workspace . \
  --flows-dir .chainweaver/flows --tools your.tools.module
```

This adds (or replaces) a single `chainweaver` entry under `mcp` in your
OpenCode config that runs `chainweaver serve` over the flows **directory**
(`chainweaver serve` accepts a file or a directory; a directory exposes its
active/reviewed flows and withholds drafts). Existing MCP servers are preserved.

### Safe naming and collisions

`FlowServer` exposes each flow as `<prefix>__<flow.name>` — with the default
prefix, the flow `ship_it` becomes the tool `cw__ship_it`. The `cw__` namespace
keeps generated macro-tools from shadowing OpenCode built-ins such as `read`,
`bash`, `edit`, or `write` (a high-level macro-flow can hide several actions
behind one call, so a generic name would be misleading). `opencode setup`
predicts these exact names and **refuses to expose colliding ones** (reserved
built-ins, names already configured, or two flows mapping to the same tool
name); rename the flow, change `--prefix`, or pass `--allow-collisions` to
override.

The mapping is stable — the same flow name and prefix always yield the same
tool name across runs.

## 5. Revert

```bash
chainweaver opencode revert --observe --write --workspace .   # remove the plugin
chainweaver opencode revert --flows   --write --workspace .   # remove the MCP entry
```

Revert removes **only** ChainWeaver-managed entries. Unrelated OpenCode
config, your captured traces, and your flow files are left untouched.

---

## What plugin observation can and cannot capture

- **Can:** tool name, redacted argument shape, result status/field names,
  latency, session/turn ids, and tool source when the event includes it.
- **Cannot (reliably):** full tool outputs (intentionally not stored), and any
  decision the model made between tool calls — which is exactly the
  model-mediated cost a compiled flow removes.

## Safe vs. unsafe examples

- **Safe to compile:** read-only context gathering — e.g.
  `github.get_pr → github.list_files → github.get_file → summarize`.
- **Unsafe to compile:** edit/fix/refactor loops, anything whose next step
  depends on model judgement, or side-effecting paths that need approval.

See also: [`chainweaver opencode`](https://github.com/dgenio/ChainWeaver/blob/main/chainweaver/cli/opencode.py),
[`chainweaver.opencode`](https://github.com/dgenio/ChainWeaver/blob/main/chainweaver/opencode.py),
and the [trace pipeline](https://github.com/dgenio/ChainWeaver/blob/main/chainweaver/traces.py).
