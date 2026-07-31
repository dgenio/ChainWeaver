# Claude Code: observe → suggest → compile → expose

Claude Code is arguably the cleanest first developer experience for ChainWeaver
macro-flow compilation: it supports **MCP servers** and **hooks**, so ChainWeaver
can *passively observe* the tool paths you already run through a `PostToolUse`
hook, mine the repeated ones into deterministic macro-flows, and expose the
reviewed flows back to Claude Code as high-level MCP tools.

This recipe walks the full loop using only local files — no live external
services are required.

> **What ChainWeaver is vs. isn't here.** ChainWeaver removes *repeated,
> model-mediated decisions* between predictable tool steps. It is not a
> reasoning engine — only deterministic, read-mostly paths should be compiled.
> Edit/fix/refactor loops that need model judgement should stay as agent loops.
>
> **How this differs from Claude Code tool search.** Claude Code's tool search
> reduces *schema loading* (which tools the model sees); ChainWeaver reduces
> *repeated model-mediated decisions* between predictable steps. They compose:
> tool search narrows the menu, ChainWeaver compiles the recurring order.

The commands below are all reversible and default to a **dry run**; nothing is
written until you pass `--write`, and every write backs the original up to
`<file>.bak`.

## Local vs project vs user scope

Claude Code reads config from several scopes. This recipe uses two:

- **Local** (`.claude/settings.local.json`) — personal, git-ignored. The
  **default** for observe hooks: a hook runs a shell command, so it should be
  *your* choice, not silently committed for the whole team.
- **Project** (`.mcp.json`, `.claude/settings.json`) — shared and committed.
  FlowServer exposure of reviewed flows lives here (in `.mcp.json`) so the team
  shares the same macro-tools; pass `--scope project` to write the observe hook
  to shared settings only when you deliberately want that.

ChainWeaver never writes to user-global config.

---

## 0. Doctor — inspect what's configured

```bash
chainweaver doctor claude --workspace .
```

Read-only. It reports `.mcp.json` servers, whether a ChainWeaver FlowServer is
exposed, which config scopes exist, whether a `PostToolUse` observe hook is
present, and the trace directory.

## 1. Set up observe mode (a PostToolUse hook)

Install a small, auditable `PostToolUse` hook into your **personal**
`.claude/settings.local.json`. Preview first:

```bash
chainweaver claude setup --observe --dry-run --workspace .
chainweaver claude setup --observe --write   --workspace .
```

The hook is one line: on each tool execution Claude Code pipes the hook payload
to `chainweaver claude capture`, which **normalizes and redacts** it into a
workspace-local JSONL sink (default `.chainweaver/traces/claude-code.jsonl`).
Redaction is on by default — secrets in arguments are masked and raw tool
outputs are not stored (only result field names and status are kept).

By default the hook fires for **all** tools; pass `--matcher 'mcp__.*'` to
capture only MCP tools.

Capture can also be driven directly (this is exactly what the hook does):

```bash
echo '{"hook_event_name":"PostToolUse","tool_name":"mcp__github__get_pr",
       "session_id":"s1","tool_input":{"repo":"acme/api"},
       "tool_output":{"title":"Fix"}}' \
  | chainweaver claude capture --sink .chainweaver/traces/claude-code.jsonl
```

What capture records per event: tool name, tool source (built-in vs MCP, with
`mcp__<server>__<tool>` split into provenance), redacted argument shape, result
status, result field names, and session/turn ids. Non-tool hook events are
skipped; malformed input is reported on stderr and never corrupts the sink.

## 2. Suggest candidate flows from the trace

Mine repeated, successful tool paths and score them:

```bash
chainweaver traces mine .chainweaver/traces/claude-code.jsonl
```

Mined sequences are **suggestions, not trusted flows** — they carry support,
success rate, latency, and token/call-savings estimates for review.

## 3. Draft, backtest, review, promote

```bash
chainweaver traces draft-flows .chainweaver/traces/claude-code.jsonl --out .chainweaver/flows
chainweaver traces backtest .chainweaver/flows/<draft>.flow.yaml .chainweaver/traces/claude-code.jsonl
chainweaver flows promote <flow-name>     # move draft → reviewed → active
```

Draft flows are **not** exposed automatically — only flows whose governance
lifecycle is **active** or **reviewed** are exposable in the next step. Draft,
suggested, ignored, and archived flows are withheld by default.

## 4. Expose active flows back to Claude Code (MCP FlowServer)

```bash
chainweaver claude setup --flows --dry-run --workspace . \
  --flows-dir .chainweaver/flows --tools your.tools.module
chainweaver claude setup --flows --write   --workspace . \
  --flows-dir .chainweaver/flows --tools your.tools.module
```

This adds (or replaces) a single `chainweaver` entry under `mcpServers` in your
project `.mcp.json` that runs `chainweaver serve` over the flows **directory**.
By default only **ACTIVE** flows are exposed — a reviewed-but-not-yet-approved
candidate is *not* surfaced as a live tool. For local development you can pass
`--include-reviewed` to also expose REVIEWED flows (it prints a warning).
Existing MCP servers are preserved.

### Safe naming and collisions

`FlowServer` exposes each flow as `<prefix>__<flow.name>` — with the default
prefix, the flow `ship_it` becomes the tool `cw__ship_it`. The `cw__` namespace
keeps generated macro-tools from shadowing other tools. `claude setup --flows`
predicts these exact names and **refuses to expose colliding ones**; rename the
flow, change `--prefix`, or pass `--allow-collisions` to override. The mapping
is stable — the same flow name and prefix always yield the same tool name.

## 5. Revert

```bash
chainweaver claude revert --observe --write --workspace .   # remove the hook
chainweaver claude revert --flows   --write --workspace .   # remove the MCP entry
```

Revert removes **only** ChainWeaver-managed entries (matched by the capture
command in the hook, and by the `chainweaver` `mcpServers` key). Unrelated
hooks, MCP servers, your captured traces, and your flow files are left
untouched.

---

## What hook observation can and cannot capture

- **Can:** tool name, tool source (built-in / MCP), redacted argument shape,
  result status/field names, and session/turn ids.
- **Cannot (reliably):** full tool outputs (intentionally not stored), latency
  (`PostToolUse` carries no timing), and any decision the model made between
  tool calls — which is exactly the model-mediated cost a compiled flow removes.

## Safe vs. unsafe examples

- **Safe to compile:** read-only context gathering — e.g.
  `github.get_pr → github.list_files → github.get_file → summarize`.
- **Unsafe to compile:** edit/fix/refactor loops, anything whose next step
  depends on model judgement, or side-effecting paths that need approval.

See also: [`chainweaver claude`](https://github.com/dgenio/ChainWeaver/blob/main/chainweaver/cli/claude.py),
[`chainweaver.claude`](https://github.com/dgenio/ChainWeaver/blob/main/chainweaver/claude.py),
the [OpenCode recipe](opencode-recipe.md), and the
[trace pipeline](https://github.com/dgenio/ChainWeaver/blob/main/chainweaver/traces.py).
