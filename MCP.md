# MCP Runtime

This document defines the MCP rules implemented by OpenAgent. The goal is to match OpenCode's core model: MCP servers are managed runtime entities, and their capabilities are exposed through the existing agent/tool/permission/session pipeline.

## Server Definition Rules

MCP config is discovered from:

- `openagent.mcp.json`
- `.opencode/mcp.json`
- paths in `OPENAGENT_MCP_CONFIG`, separated by the platform path separator

Supported config shape:

```json
{
  "mcpServers": {
    "filesystem": {
      "type": "stdio",
      "command": "mcp-server-filesystem",
      "args": ["{workspace}/work"],
      "env": {},
      "enabled": true,
      "timeout": 30
    },
    "remote-memory": {
      "type": "remote",
      "url": "http://127.0.0.1:8811/mcp",
      "headers": {
        "X-API-Key": "remote-demo"
      },
      "oauth": false,
      "enabled": true,
      "timeout": 30
    }
  }
}
```

Rules:

- `name` comes from the `mcpServers` key and is normalized to alphanumeric, `_`, or `-`.
- Later config files override earlier servers with the same normalized name.
- `type` defaults to `stdio` when `command` is present.
- `stdio` requires `command`; `args`, `env`, `enabled`, and `timeout` are optional.
- `remote` requires `url`; `headers`, `oauth`, `enabled`, and `timeout` are optional.
- `{workspace}` in `command` and `args` expands to the active workspace path.
- `oauth` accepts:
  - `false`
  - `{}`
  - `{"clientId":"...","clientSecret":"...","scope":"..."}`
- auth records are stored under `.openagent/mcp_auth.json` and are keyed by `server_name + server_url` so moving a server URL does not silently reuse old credentials.
- `OPENAGENT_MCP=false` disables MCP without affecting normal tools.

## Capability Rules

MCP exposes three capability groups:

- `tools`
  - executable remote capabilities
  - adapted into normal OpenAgent tools with ids like `mcp__<server>__<tool>`
- `resources`
  - addressable context data from a server
  - exposed through the generic `mcp_read_resource` tool
- `prompts`
  - server-provided prompt templates
  - exposed through the generic `mcp_get_prompt` tool

MCP tool schema handling:

- MCP `inputSchema` is preserved when it is an object.
- Invalid or missing schemas degrade to an empty object schema.
- Tool output is normalized into `ToolExecutionResult`.
- MCP `isError` results become structured tool failures.

Conflict handling:

- MCP tool names are namespaced by server, so `echo` from `everything` becomes `mcp__everything__echo`.
- Namespacing avoids collisions with built-in tools and with tools from other MCP servers.

## Lifecycle Rules

Lifecycle is managed by `McpManager`:

- servers start when the runtime builds the tool registry
- disconnected servers reconnect on demand when a tool/resource/prompt is requested
- each server has an independent client, status, capability cache, and error state
- startup failures mark only that server as `failed`; other servers still run
- calls use per-server request timeouts
- shutdown closes each managed stdio process and remote HTTP/SSE client session
- remote servers try `StreamableHTTP` first and automatically fall back to `SSE`
- every remote connection attempt is recorded with transport name, success/failure, and error summary
- after connection, the manager immediately validates `initialize + tools/resources/prompts discovery` so "connected but unusable" servers are downgraded into an error state

Current states:

- `stopped`
- `connected`
- `disabled`
- `failed`
- `needs_auth`
- `needs_client_registration`

## Invocation And Injection Rules

MCP is not a separate execution system. The flow is:

`provider tool call -> SessionProcessor -> ToolRegistry -> McpTool -> McpManager -> StdioMcpClient/RemoteMcpClient -> MCP server`

This means MCP calls share:

- tool lifecycle events
- permission checks
- truncation and structured results
- session replay/inspect output
- per-agent visible tool filtering

The model sees MCP tools through the normal tool list. It can choose an MCP tool when the tool id and description match the task.

## Permission And Safety Rules

MCP tools use the existing permission system.

Examples:

- tool id: `mcp__everything__echo`
- permission name: `tool.mcp__everything__echo`
- ask/once/always/reject/deny semantics are unchanged

YOLO mode auto-approves ask-class MCP calls, but explicit deny rules still block them.

Server isolation:

- each server runs in its own process for stdio transport
- each remote server keeps its own transport state, session headers, auth state, and capability cache
- each tool id is namespaced by server
- failed servers do not block unrelated servers
- filesystem server access is constrained by that server's own configuration, for example `{workspace}/work`

## Error Handling Rules

Errors are surfaced instead of hidden:

- invalid config object: raises a config parse error during discovery
- unsupported transport: server status becomes `failed`
- missing command or startup failure: server status becomes `failed`
- request timeout: tool result is a structured failure
- MCP `isError`: tool result is a structured failure
- unknown MCP tool/server: returns a clear failure through the CLI/tool path
- HTTP 401/403 from a remote server: server state becomes `needs_auth`
- HTTP 428 from a remote server: server state becomes `needs_client_registration`
- broken StreamableHTTP endpoint with a valid SSE fallback: attempt is recorded and the server continues in `connected` state over `sse`

## Verified Servers

The repository-level `openagent.mcp.json` is validated against:

- `filesystem`
  - package: `@modelcontextprotocol/server-filesystem`
  - purpose: file/system capability validation, scoped to `{workspace}/work`
- `git`
  - package: `mcp-git`
  - purpose: development tooling validation
- `everything`
  - package: `@modelcontextprotocol/server-everything`
  - purpose: general MCP tools/resources/prompts validation
- `memory`
  - package: `@modelcontextprotocol/server-memory`
  - purpose: knowledge graph memory validation for complete cross-step tasks
- `sequential-thinking`
  - package: `@modelcontextprotocol/server-sequential-thinking`
  - purpose: structured planning validation for multi-step workflows

The repository also includes [`openagent.mcp.remote.json`](openagent.mcp.remote.json) for remote validation through local `mcp-proxy` instances:

- `remote-memory`
  - remote StreamableHTTP
  - authenticated with `X-API-Key: remote-demo`
  - purpose: remote knowledge graph validation
- `remote-sequential`
  - remote StreamableHTTP
  - purpose: remote planning validation
- `remote-filesystem-sse`
  - remote server intentionally exposed through SSE only
  - purpose: verify HTTP-first then SSE fallback
- `remote-memory-oauth`
  - remote auth-required server
  - purpose: validate `needs_auth`, stored credentials, and reconnect flow

An optional local GitHub MCP server can also be attached through an ignored file such as `.openagent/mcp.github.json`:

```json
{
  "mcpServers": {
    "github": {
      "type": "stdio",
      "command": "mcp-server-github",
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": "${YOUR_TOKEN}"
      },
      "enabled": true,
      "timeout": 60
    }
  }
}
```

Install them with:

```bash
npm install -g @modelcontextprotocol/server-filesystem @modelcontextprotocol/server-everything mcp-git @modelcontextprotocol/server-memory @modelcontextprotocol/server-sequential-thinking
npm install -g mcp-proxy
npm install -g @modelcontextprotocol/server-github
```

Start local remote validation proxies:

```bash
mcp-proxy --host 127.0.0.1 --port 8811 --apiKey remote-demo -- mcp-server-memory
mcp-proxy --host 127.0.0.1 --port 8812 -- mcp-server-sequential-thinking
mcp-proxy --host 127.0.0.1 --port 8813 --server sse -- mcp-server-filesystem /root/open-claude-code/work
mcp-proxy --host 127.0.0.1 --port 8814 --apiKey oauth-demo -- mcp-server-memory
```

## CLI Validation

List servers:

```bash
openagent --mcp
OPENAGENT_MCP_CONFIG=openagent.mcp.remote.json openagent --mcp
```

List tools/resources/prompts:

```bash
openagent --mcp-tools
openagent --mcp-resources
openagent --mcp-prompts
OPENAGENT_MCP_CONFIG=openagent.mcp.remote.json openagent --mcp-tools
OPENAGENT_MCP_CONFIG=openagent.mcp.remote.json openagent --mcp-inspect remote-filesystem-sse
OPENAGENT_MCP_CONFIG=openagent.mcp.remote.json openagent --mcp-trace
```

Call real tools:

```bash
openagent --yolo --mcp-call git git_status '{"repo_path":"/root/open-claude-code"}'
openagent --yolo --mcp-call filesystem list_directory '{"path":"/root/open-claude-code/work"}'
openagent --yolo --mcp-call memory create_entities '{"entities":[{"name":"openagent-mcp-demo","entityType":"project_fact","observations":["MCP memory stores validation facts."]}]}'
openagent --yolo --mcp-call memory search_nodes '{"query":"openagent-mcp-demo"}'
openagent --yolo --mcp-call sequential-thinking sequentialthinking '{"thought":"Plan the MCP validation in one step.","nextThoughtNeeded":false,"thoughtNumber":1,"totalThoughts":1}'
OPENAGENT_MCP_CONFIG=openagent.mcp.remote.json openagent --yolo --mcp-call remote-memory create_entities '{"entities":[{"name":"openagent-remote-demo","entityType":"project_fact","observations":["Created through remote MCP."]}]}'
OPENAGENT_MCP_CONFIG=openagent.mcp.remote.json openagent --yolo --mcp-call remote-memory search_nodes '{"query":"openagent-remote-demo"}'
OPENAGENT_MCP_CONFIG=openagent.mcp.remote.json openagent --yolo --mcp-call remote-sequential sequentialthinking '{"thought":"Plan the remote MCP validation in one step.","nextThoughtNeeded":false,"thoughtNumber":1,"totalThoughts":1}'
OPENAGENT_MCP_CONFIG=openagent.mcp.remote.json openagent --yolo --mcp-call remote-filesystem-sse list_directory '{"path":"/root/open-claude-code/work"}'
```

Auth prelude validation:

```bash
OPENAGENT_MCP_CONFIG=openagent.mcp.remote.json openagent --mcp-ping remote-memory-oauth
OPENAGENT_MCP_CONFIG=openagent.mcp.remote.json openagent --mcp-auth remote-memory-oauth '{"access_token":"oauth-demo","header_name":"X-API-Key","prefix":""}'
OPENAGENT_MCP_CONFIG=openagent.mcp.remote.json openagent --yolo --mcp-call remote-memory-oauth search_nodes '{"query":"openagent-remote-demo"}'
```

GitHub MCP validation:

```bash
OPENAGENT_MCP_CONFIG="openagent.mcp.json:.openagent/mcp.github.json" openagent --mcp-inspect github
OPENAGENT_MCP_CONFIG="openagent.mcp.json:.openagent/mcp.github.json" openagent --yolo --mcp-call github search_repositories '{"query":"openagent","perPage":3}'
OPENAGENT_MCP_CONFIG="openagent.mcp.json:.openagent/mcp.github.json" openagent --yolo --mcp-call github get_file_contents '{"owner":"modelcontextprotocol","repo":"servers","path":"README.md"}'
```

Agent-loop validation:

```text
请使用 MCP filesystem 的 list_directory 工具列出 /root/open-claude-code/work 目录，然后只回复是否看到了 yolo_ok.txt。
```

Expected `/replay` evidence:

```text
ToolRequest: mcp__filesystem__list_directory {"path": "/root/open-claude-code/work"}
ToolResult: mcp__filesystem__list_directory -> ...
```

Complete multi-MCP validation task:

```text
请完成一个 MCP 综合验证任务：1. 使用 MCP sequential-thinking 做一步简短计划，2. 使用 MCP memory 写入实体 openagent-cli-mcp-final，观察内容为 CLI loop used MCP memory and sequential-thinking，3. 再用 MCP memory 搜索该实体，最后只回复是否搜索到了该实体。
```

Expected `/replay` evidence:

```text
ToolRequest: mcp__sequential_thinking__sequentialthinking ...
ToolRequest: mcp__memory__create_entities ...
ToolRequest: mcp__memory__search_nodes ...
```

Remote multi-turn validation that was actually run in one persisted session:

```text
1. 请使用 remote-memory 创建实体 remote-loop-a，并添加 first note。
2. 再给它添加 second note。
3. 再搜索 remote-loop-a。
4. 最后只回复是否同时看到了 first note 和 second note。
```

Observed result:

```text
是的，同时看到了 first note 和 second note。
```

Replay evidence:

```text
ToolRequest: mcp__remote_memory__create_entities ...
ToolRequest: mcp__remote_memory__add_observations ...
ToolRequest: mcp__remote_memory__search_nodes ...
```

Remote fallback validation that was actually run:

```text
1. 先用 remote-filesystem-sse 列出 /root/open-claude-code/work/not-real。
2. 如果失败，用一句话说明原因。
3. 再列出 /root/open-claude-code/work。
4. 最后只回复是否看到了 yolo_ok.txt。
```

Observed result:

```text
看到了 yolo_ok.txt。
```

## Current Limits

- Implemented: stdio transport, remote StreamableHTTP transport, SSE fallback, multi-server lifecycle, tool/resource/prompt discovery, dynamic tool registry injection, permission integration, CLI management, auth record storage, and agent-loop invocation.
- Partial: auth support is real for stored token/header credentials and the runtime exposes `needs_auth` / `needs_client_registration`, but a full browser OAuth callback flow is only scaffolded structurally, not completed end to end.
- Partial: resources and prompts are exposed through generic tools; advanced subscriptions/events are not implemented.
- Not implemented: full browser OAuth dance, remote registry installation, MCP streaming subscriptions/events, HTTP transport variants beyond the currently verified StreamableHTTP/SSE paths.
