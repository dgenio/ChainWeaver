# MCP Integration

Canonical reference for the `chainweaver.mcp` package (issues #70, #72,
#150) and the async executor lane it builds on (issue #80).

---

## Surfaces

| Symbol | Purpose |
|--------|---------|
| `chainweaver.mcp.MCPToolAdapter` | Wraps tools advertised by an MCP server as ChainWeaver `Tool` objects. Inbound: MCP → ChainWeaver. |
| `chainweaver.mcp.FlowServer` | Mounts registered ChainWeaver flows on a `FastMCP` server so MCP-aware agents see each compiled flow as a single tool. Outbound: ChainWeaver → MCP. |
| `chainweaver.mcp.jsonschema_to_pydantic` | Bridge: JSON Schema (the MCP wire shape) → Pydantic `BaseModel`. |
| `chainweaver.mcp.pydantic_to_jsonschema` | Thin wrapper over `model.model_json_schema()`. |
| `FlowExecutor.execute_flow_async` | Async-native executor lane required by both MCP surfaces. |
| `Tool.run_async` | Async-native tool invocation; respects `timeout_seconds` via `asyncio.wait_for`. |
| `Tool.is_async` | Cached `True` when the tool's `fn` is a coroutine function. |
| `MCPError` / `MCPSchemaConversionError` / `MCPToolInvocationError` | Exception family for the MCP package; all inherit `ChainWeaverError`. |

## Optional extra

The MCP integration depends on the official `mcp` Python SDK:

```bash
pip install 'chainweaver[mcp]'
```

`chainweaver.mcp.adapter` and `chainweaver.mcp.server` guard the
import and raise a clear `ImportError` when the extra is missing.

## Inbound adapter (#70 + #150)

`MCPToolAdapter` discovers an MCP server's tool catalogue via
`session.list_tools()` and projects each entry into a ChainWeaver
`Tool`:

```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from chainweaver import FlowExecutor
from chainweaver.mcp import MCPToolAdapter

params = StdioServerParameters(command="my-mcp-server")
async with stdio_client(params) as (read, write):
    async with ClientSession(read, write) as session:
        await session.initialize()
        adapter = MCPToolAdapter(session)
        for tool in await adapter.discover_tools(server_prefix="search"):
            executor.register_tool(tool)
```

Policy choices baked in (issue #150):

- **Server-prefixed tool names**: `discover_tools(server_prefix="foo")`
  registers `foo__<remote_name>` so multiple MCP servers can coexist
  without collisions. Default is no prefix.
- **Official SDK only**: the adapter accepts the SDK's
  `mcp.ClientSession` — custom transports must produce one.
- **`cacheable=False` by default**: MCP calls may touch remote state,
  so wrapped tools opt out of the step cache. Mutate
  `tool.cacheable = True` after discovery for tools known to be pure.

### Output projection

| MCP tool's `outputSchema` | Adapter behaviour |
|---|---|
| Present | Routed through `_project_structured_output`. The ChainWeaver `Tool` has an `output_schema` derived from the JSON Schema; the call's `structuredContent` is returned as-is (or, missing that, the call's text content is JSON-parsed). `isError=True` raises `MCPToolInvocationError`. |
| Absent | Routed through `_project_unstructured_output`. The `output_schema` is the permissive `_MCPToolOutput` model with fields `content` (text), `structured` (dict or None), and `is_error` (always `False` — true errors raise). |

## Outbound server (#72)

`FlowServer` mounts a set of registered flows on a FastMCP server:

```python
from chainweaver import FlowRegistry, FlowExecutor
from chainweaver.mcp import FlowServer

server = FlowServer(executor, name="my-flows")  # all ACTIVE flows
# or:
server = FlowServer(executor, flow_names=["flow_a"], server_prefix="cw")
server.serve()  # blocks; stdio transport by default
# or, inside an async context:
await server.serve_async(transport="streamable-http")
```

Schema resolution (mirrors `Tool.from_flow`):

- **inputSchema**: `flow.input_schema` → first-step tool's input
  schema → permissive empty model.
- **outputSchema**: `flow.output_schema` → linear flow's last-step
  tool output schema → DAG sole-sink output schema → omitted (the
  resulting MCP tool returns text-only content).

The MCP-side tool exposes the input model's **top-level fields**
directly (e.g. `client.call_tool("my_flow", {"n": 5})`), not nested
under a `payload` parameter. This is achieved by synthesising the
dispatcher function's signature from `input_schema.model_fields`.

Flow failures surface as raised `FlowExecutionError` instances, which
FastMCP wraps as `CallToolResult(isError=True)` for the client.

## Async lane (#80)

`FlowExecutor.execute_flow_async` is a coroutine that mirrors
`execute_flow` and is the entry point both MCP surfaces use:

- **Tools** are dispatched via `Tool.run_async` — async tools (e.g.
  MCP-wrapped) are awaited natively; sync tools are offloaded to a
  worker thread via `asyncio.to_thread`.
- **Retries** use `asyncio.sleep` for backoff, not `time.sleep`.
- **on_error fallbacks** dispatch via `run_async` so an MCP tool can
  be a fallback target.
- **Middleware hooks** fire on the same threading boundary as the
  sync path — observability is unchanged.
- **Linear and DAG flows** are both supported. Intra-level
  concurrency is a follow-up; today DAG levels execute steps
  sequentially.

### Out of scope (v0.1)

- **Step cache** (#127) on the async lane — uses sync helpers; will
  be re-enabled in a follow-up.
- **Crash-resume checkpoint** (#128) on the async lane — same.
- **Conditional branching** (`branches` / `default_next`, #9) and
  **decision callbacks** (`decision_candidates`, #102) — the sync
  `execute_flow` honours these, but the async lane does not yet.
  Rather than drop the directives silently (which would diverge from
  the sync result), `execute_flow_async` raises `FlowExecutionError`
  up front when a flow declares them; route such flows through the
  synchronous `execute_flow` until the async lane reaches parity.
- **Parallel DAG execution within a level** — async lane preserves
  the sync executor's level-sequential semantics for now.
- **`stream_flow`** async counterpart — sync stream still works
  alongside the async lane.

## Executor invariants

The new code holds the three executor invariants:

1. **No LLM calls** in `executor.py` — unchanged.
2. **No network I/O** in `executor.py` — all MCP I/O lives in
   `chainweaver/mcp/`, never in the executor itself.
3. **No randomness** — unchanged.

`Tool.fn` may now be a coroutine function; the type annotation is
`Callable[[Any], dict[str, Any] | Awaitable[dict[str, Any]]]`.

## Naming policy

| Convention | Where it applies |
|---|---|
| `server_prefix__tool_name` (double underscore) | Both inbound (`MCPToolAdapter.discover_tools`) and outbound (`FlowServer(server_prefix=…)`) — keeps the resulting identifier a valid Python attribute and visually distinct from the tool's own name. |
| Default = no prefix | Appropriate only when consuming or exposing a single trusted server. |
