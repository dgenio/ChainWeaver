# Use ChainWeaver as an MCP server

ChainWeaver is MCP-native in **both directions**:

- **Inbound** — `chainweaver.mcp.MCPToolAdapter` wraps tools advertised by an
  MCP server as ChainWeaver `Tool` objects so you can compose them into a flow.
- **Outbound** — `FlowServer` exposes your **registered flows as MCP tools**, so an
  MCP-aware agent (Claude Desktop, an IDE, another runtime) calls a whole compiled
  flow as a *single deterministic tool*. An N-step flow collapses into one MCP wire
  call — the headline "compiled, not interpreted" benefit.

This page covers the **outbound** direction: turning ChainWeaver into an MCP server.

!!! note "Requires the `mcp` extra"
    The MCP server builds on the standalone
    [`fastmcp`](https://github.com/jlowin/fastmcp) package; the official
    [`mcp`](https://pypi.org/project/mcp/) SDK is pulled in by the same extra
    for the inbound adapter:

    ```bash
    pip install 'chainweaver[mcp]'
    ```

## One command

`chainweaver serve` loads a flow file and its tool modules (exactly like
[`chainweaver run`](cli.md#run)) and serves the flow over MCP:

```bash
# Flow file and tools both ship in examples/ — runnable from the repo root.
chainweaver serve examples/double_add_format.flow.yaml --tools examples.simple_linear_flow
```

This starts a `stdio` MCP server advertising one tool per registered flow. The
startup banner goes to **stderr**, so under `stdio` your stdout stays a clean MCP
channel. Use `--transport sse` or `--transport streamable-http` for network
transports, `--name` to set the advertised server name, and `--prefix` to namespace
the exposed tool names. Press Ctrl-C to stop.

See the [`serve` CLI reference](cli.md#serve) for every flag and the exit-code
contract.

## Minimal client config

Point any MCP client at the command. For a stdio client (e.g. a
`claude_desktop_config.json`-style config):

```json
{
  "mcpServers": {
    "chainweaver": {
      "command": "chainweaver",
      "args": [
        "serve",
        "/abs/path/to/your.flow.yaml",
        "--tools", "your_package.tools"
      ]
    }
  }
}
```

The client then sees each registered flow as a callable MCP tool, with an
`inputSchema` (and, when determinable, an `outputSchema`) derived from the flow's
own schemas.

The same policy applies across MCP hosts:

| Host | Recommended exposure |
|------|----------------------|
| Claude Code / Claude Desktop | Default safe discovery for active read-only flows; explicit names only for trusted write flows. |
| OpenCode | Namespace with `server_prefix` when raw tools and macro-flows share a session. |
| VS Code / GitHub Copilot | Keep draft/reviewed candidate files in the workspace; promote to `active` before discovery. |
| Platform gateway | Set lifecycle, owner, and side-effect allow-lists and enforce authentication at the gateway boundary. |

## Programmatic use

When you already build a `FlowExecutor` in Python, mount it directly:

```python
from chainweaver.mcp import FlowServer

server = FlowServer(executor, name="my-flows")
print(server.registered_tool_names)  # one entry per exposed flow
server.serve(transport="stdio")      # or "sse" / "streamable-http"
```

Default discovery is intentionally strict: a flow must have lifecycle
`active`, known safety metadata, read-only side effects (`none` or `read`),
and no approval requirement. Missing metadata and excluded flows are logged.
Explicit `flow_names` is the advanced operator override:

```python
from chainweaver import FlowLifecycle, SideEffectLevel

# Include reviewed flows owned by the platform team, still read-only.
server = FlowServer(
    executor,
    allowed_lifecycles={FlowLifecycle.REVIEWED, FlowLifecycle.ACTIVE},
    allowed_side_effects={SideEffectLevel.NONE, SideEffectLevel.READ},
    owners={"platform"},
)

# Deliberately expose one named flow even when it is write-capable.
server = FlowServer(executor, flow_names=["deploy_release"])
```

Each advertised MCP tool receives accurate `readOnlyHint`,
`destructiveHint`, `idempotentHint`, and `openWorldHint` values. Its
description and `_meta.chainweaver` payload include lifecycle, owner, version,
replaced raw tools, model-call savings, token savings, and the effective
safety contract. A coding agent therefore sees one reviewed macro-tool such
as `repo_context_pack` instead of separately planning several raw filesystem
calls.

`FlowServer.fastmcp` exposes the underlying `FastMCP` instance if you want to add
extra MCP capabilities (resources, prompts, raw tools) on the same transport. A
full end-to-end demo that talks to the server with a real MCP client lives in
`examples/mcp_flow_server.py`.

## Publishing to the MCP ecosystem

A ready-to-submit MCP registry manifest ships at
[`server.json`](https://github.com/dgenio/ChainWeaver/blob/main/server.json). It
launches the server with a fresh-client command that resolves the `mcp` extra:

```bash
uvx --from 'chainweaver[mcp]' chainweaver serve /abs/path/to/your.flow.yaml \
  --tools your_package.tools
```

See [Distribution & ecosystem listings](distribution.md) for the registry and
awesome-list submission checklist.
