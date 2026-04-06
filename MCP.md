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
    }
  }
}
```

Rules:

- `name` comes from the `mcpServers` key and is normalized to alphanumeric, `_`, or `-`.
- Later config files override earlier servers with the same normalized name.
- `type` defaults to `stdio` when `command` is present.
- `stdio` requires `command`; `args`, `env`, `enabled`, and `timeout` are optional.
- `{workspace}` in `command` and `args` expands to the active workspace path.
- HTTP/SSE style servers are intentionally not implemented yet; they are reported as `error` with an unsupported transport message.
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
- startup failures mark only that server as `error`; other servers still run
- calls use per-server request timeouts
- shutdown closes each managed stdio process

Current states:

- `stopped`
- `running`
- `disabled`
- `error`

## Invocation And Injection Rules

MCP is not a separate execution system. The flow is:

`provider tool call -> SessionProcessor -> ToolRegistry -> McpTool -> McpManager -> StdioMcpClient -> MCP server`

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
- each tool id is namespaced by server
- failed servers do not block unrelated servers
- filesystem server access is constrained by that server's own configuration, for example `{workspace}/work`

## Error Handling Rules

Errors are surfaced instead of hidden:

- invalid config object: raises a config parse error during discovery
- unsupported transport: server status becomes `error`
- missing command or startup failure: server status becomes `error`
- request timeout: tool result is a structured failure
- MCP `isError`: tool result is a structured failure
- unknown MCP tool/server: returns a clear failure through the CLI/tool path

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

Install them with:

```bash
npm install -g @modelcontextprotocol/server-filesystem @modelcontextprotocol/server-everything mcp-git @modelcontextprotocol/server-memory @modelcontextprotocol/server-sequential-thinking
```

## CLI Validation

List servers:

```bash
openagent --mcp
```

List tools/resources/prompts:

```bash
openagent --mcp-tools
openagent --mcp-resources
openagent --mcp-prompts
```

Call real tools:

```bash
openagent --yolo --mcp-call git git_status '{"repo_path":"/root/open-claude-code"}'
openagent --yolo --mcp-call filesystem list_directory '{"path":"/root/open-claude-code/work"}'
openagent --yolo --mcp-call memory create_entities '{"entities":[{"name":"openagent-mcp-demo","entityType":"project_fact","observations":["MCP memory stores validation facts."]}]}'
openagent --yolo --mcp-call memory search_nodes '{"query":"openagent-mcp-demo"}'
openagent --yolo --mcp-call sequential-thinking sequentialthinking '{"thought":"Plan the MCP validation in one step.","nextThoughtNeeded":false,"thoughtNumber":1,"totalThoughts":1}'
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

## Current Limits

- Implemented: stdio transport, multi-server lifecycle, tool/resource/prompt discovery, dynamic tool registry injection, permission integration, CLI management, agent-loop invocation.
- Partial: resources and prompts are exposed through generic tools; advanced subscriptions/events are not implemented.
- Not implemented: HTTP/SSE/OAuth MCP transports, streaming MCP events, remote registry installation.
