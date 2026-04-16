# openagent

![Python](https://img.shields.io/badge/python-3.11+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Version](https://img.shields.io/badge/version-0.1.0-orange.svg)
![Stars](https://img.shields.io/github/stars/wangzhongyuan11/open-claude-code)

A minimal Python coding agent runtime inspired by OpenCode-style architecture with full MCP support.

## Project Goals

`openagent` aims to provide a **lightweight, extensible** coding agent runtime with:

- Clean session-centric architecture
- Native Model Context Protocol (MCP) integration
- OpenCode-compatible skills system
- Multiple LLM provider support (Anthropic, Volcengine)
- Rich interactive CLI with streaming support
- Session persistence and rollback capabilities

---

## Quick Start

```bash
# Install
pip install -e ".[dev,anthropic]"

# Configure API
export ANTHROPIC_API_KEY=your_key

# Run
openagent
```

> **Tip:** Auto-loads `.env` from project root. Use `cp .env.example .env` for quick setup.

---

## Project Layout

```text
src/openagent/
├── agent/       # Agent system (runtime, loop, subagent, routing)
├── cli/         # Command-line entry and REPL
├── config/      # Settings loading
├── domain/      # Core model definitions
├── events/      # Event bus and logger
├── extensions/  # Extension hooks
├── mcp/         # MCP runtime (stdio/remote clients, manager)
├── providers/   # LLM providers (anthropic, volcengine)
├── session/      # Session layer (store, processor, prompt, compaction)
├── skill/        # Skill runtime (discovery, validation, loading)
├── tools/        # Tool registry and built-in tools
├── permission/   # Permission policy
└── lsp/          # LSP client support
```

---

## Core Architecture

`openagent` is organized around a **session-centric runtime**:

```
CLI Input → AgentRuntime → SessionProcessor → ToolRegistry → Execution
              ↓                ↓                  ↓
         Session Store → Tool/Permission → LLM Provider
```

### Key Components

| Component | Description |
|-----------|-------------|
| `cli/main.py` | CLI entry, interactive REPL, slash commands |
| `agent/runtime.py` | Top-level orchestrator, active agent, tool registry |
| `session/manager.py` | Session lifecycle, prompt windows, compaction |
| `session/processor.py` | Think-act loop, tool execution, streaming |
| `tools/registry.py` | Single tool execution point, permissions, lifecycle |
| `permission/policy.py` | Session-scoped ask-before-act policy |
| `session/store.py` | Atomic persistence on disk |

---

## Model Context Protocol (MCP)

OpenAgent implements **full MCP integration** where servers are managed runtime entities with tools adapted into the normal tool registry.

### Supported Features

| Feature | Status |
|----------|--------|
| stdio transport | ✅ Implemented |
| Remote StreamableHTTP | ✅ Implemented |
| SSE fallback | ✅ Implemented |
| Multi-server management | ✅ Implemented |
| Tool namespacing (`mcp__server__tool`) | ✅ Implemented |
| Permission integration | ✅ Implemented |
| Auth persistence | ✅ Implemented |
| Streaming tool responses | ⚠️ Partial (via tool result) |
| Resource subscriptions | ⚠️ Generic tools only |
| Browser OAuth | ⚠️ Token/header auth only |

<details>
<summary>See full MCP documentation</summary>

For complete MCP rules, server configuration, and validation examples, see **[MCP.md](MCP.md)**.

### Example MCP Config

```json
{
  "mcpServers": {
    "filesystem": {
      "type": "stdio",
      "command": "mcp-server-filesystem",
      "args": ["{workspace}/work"],
      "enabled": true
    },
    "remote-memory": {
      "type": "remote",
      "url": "http://127.0.0.1:8811/mcp",
      "headers": {"X-API-Key": "your-key"},
      "enabled": true
    }
  }
}
```

### MCP CLI Commands

```bash
openagent --mcp                    # List all servers
openagent --mcp-tools               # List MCP tools
openagent --mcp-call fs list '{"path":"."}'  # Call MCP tool
OPENAGENT_MCP=false openagent       # Disable MCP
```
</details>

---

## Comparison with Other Runtimes

### vs OpenCode

| Feature | openagent | OpenCode |
|----------|-----------|----------|
| MCP transport priority | HTTP → SSE | SSE → HTTP |
| Tool integration | Namespaced adapter | Direct integration |
| Permission system | `permission.mcp__*` namespace | Native MCP |
| Streaming tools | Via tool result | Native support |
| Browser OAuth | Partial only | Full support |

**Why openagent?**
- ✅ Clean Python implementation, easy to extend
- ✅ Session-centric with full persistence
- ✅ Works with multiple LLM providers
- ✅ OpenCode-compatible skill system
- ✅ No heavy dependencies

### vs Claude Code

| Feature | openagent | Claude Code |
|----------|-----------|-------------|
| MCP support | Self-implemented | Native integration |
| Tool ecosystem | MCP + built-in | MCP + native tools |
| Security context | Basic permission | Deep security context |

**Why openagent?**
- ✅ Understand and modify the runtime
- ✅ Lightweight for local development
- ✅ Multiple provider support

---

## Skill System

OpenAgent implements **OpenCode-compatible skills** discovered from `SKILL.md` files and loaded lazily via the `skill` tool.

<details>
<summary>See complete skill documentation</summary>

Full skill rules, discovery paths, and validation are documented in **[SKILLS.md](SKILLS.md)**.

### Example Skill

```markdown
---
name: python-review
description: Use when reviewing Python code for bugs and typing issues.
---

# Python Review Reviewer

Check for common Python anti-patterns and type hints.
```

### Skill CLI

```bash
openagent --skills                # List available skills
openagent --skill python-review     # Load a skill
OPENAGENT_SKILL_PATHS=/path openagent --skills  # Add custom path
```
</details>

---

## Built-in Tools

| Category | Tools |
|----------|--------|
| **File System** | `ls`, `glob`, `read_file`, `write_file`, `edit_file`, `apply_patch` |
| **Search** | `grep`, `codesearch`, `read_symbol` |
| **Shell** | `bash`, `background_task` |
| **Agent** | `delegate`, `task`, `todowrite` |
| **Integration** | `skill`, `lsp`, `webfetch`, `websearch` |
| **Session** | `question`, `revert`, `rollback` |

---

## CLI Commands

### Startup Options

```bash
openagent --workspace .                    # Set workspace
openagent --agent plan                   # Start with specific agent
openagent --session-id <id>              # Resume session
openagent --stream                      # Enable streaming
openagent --list-sessions               # List all sessions
```

### Interactive Commands

| Command | Description |
|----------|-------------|
| `/help` | Show help |
| `/status` | Session/runtime status JSON |
| `/summary` | PR-style conversation summary |
| `/inspect` | Structured message view |
| `/replay` | Human-readable turn-by-turn replay |
| `/history` | Message history |
| `/agents` | List and switch agents |
| `/skills` | List available skills |
| `/mcp` | MCP server status |
| `/todos` | Todo list management |
| `/snapshots` | File snapshot list |
| `/yolo on/off` | Auto-approve mode |
| `/compact` | Force session compaction |
| `/revert` | Remove last turn |
| `/rollback <target>` | Rollback file changes |
| `/retry` | Rerun last turn |
| `/cancel` | Discard current input |
| `/exit` | Exit REPL |

---

## Volcengine Ark Support

```bash
export OPENAGENT_PROVIDER=volcengine
export ARK_API_KEY=your_ark_key
export OPENAGENT_MODEL=ark-code-latest
export ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/coding/v3
PYTHONPATH=src python -m openagent.cli.main --workspace .
```

You can also use a local `.env` file. The CLI auto-loads `.env` from the project root before startup.

```bash
cp .env.example .env
```

Then fill in:

```bash
ARK_API_KEY=your_ark_key
OPENAGENT_MODEL=ark-code-latest
```

Quick start:

```bash
chmod +x openagent.sh
./openagent.sh
```

## CLI

```bash
openagent --workspace .
openagent --workspace . --list-sessions
openagent --workspace . --session-id <session_id>
openagent --workspace . --agents
openagent --workspace . --agent plan
openagent --workspace . --agent-create "TypeScript 代码审查专家"
openagent --workspace . --agent-show ts-reviewer
openagent --workspace . --print-session
openagent --workspace . --session-id <session_id> --status
openagent --workspace . --session-id <session_id> --summary
openagent --workspace . --session-id <session_id> --inspect
openagent --workspace . --session-id <session_id> --replay
openagent --workspace . --skills
openagent --workspace . --skill openai-docs
openagent --workspace . --mcp
openagent --workspace . --mcp-tools
openagent --workspace . --mcp-call filesystem list_directory '{"path":"/root/open-claude-code/work"}'
openagent --workspace . --prompt "创建一个 demo.txt"
openagent --workspace . --stream --prompt "请只回复 stream-ok。"
```

Interactive commands:

- `/help`
- `/session`
- `/agents`
- `/history`
- `/status`
- `/summary`
- `/inspect`
- `/replay`
- `/skills`
- `/skill <name>`
- `/mcp`
- `/mcp tools`
- `/mcp resources`
- `/mcp prompts`
- `/mcp call <server> <tool> [json]`
- `/mcp resource <server> <uri>`
- `/mcp prompt <server> <name> [json]`
- `/snapshots`
- `/yolo`
- `/yolo on`
- `/yolo off`
- `/compact`
- `/revert`
- `/rollback last [file]`
- `/rollback snapshot <id> [file]`
- `/rollback tool <tool_call_id> [file]`
- `/rollback task <task_id> [file]`
- `/rollback file <path>`
- `/retry`
- `/todos`
- `/todo add <text>`
- `/todo done <index>`
- `/todo clear`
- `/agent <name>`
- `/agent show <name>`
- `/agent create <desc>`
- `/cancel`
- `/exit`

Interactive input mode:

- REPL now uses an editor-style multiline input
- `prompt_toolkit` is installed by default and powers the primary REPL experience
- `Enter` sends the current message immediately
- `Ctrl+J` inserts a newline inside the current message
- pasted multiline text is preserved as one message, including trailing blank lines
- arrow keys move the cursor inside the current buffer
- mouse capture is disabled so terminal right-click paste keeps working
- only single-line slash commands are treated as commands; pasted multiline text is always treated as a normal message
- `/cancel` discards the current buffered message
- slash commands such as `/status` or `/inspect` can be entered directly as single-line input

Interactive command reference:

- `/help`
  - prints the built-in REPL help text
- `/session`
  - prints the current session id
- `/agents`
  - prints the visible agent list and marks the active agent
- `/history`
  - prints the persisted message history in stored order
- `/status`
  - prints the structured session/runtime status JSON
- `/summary`
  - prints a hidden-agent PR-style summary of the current conversation
- `/inspect`
  - prints a structured JSON view of recent messages, parts, and metadata
- `/replay`
  - prints a human-readable turn-by-turn replay
- `/skills`
  - lists discovered skills that are visible to the current agent after `permission.skill` filtering
- `/skill <name>`
  - loads one skill through the unified `skill` tool and prints the injected instruction block
- `/mcp`
  - lists configured MCP servers with source, status, command, capability counts, and last error
- `/mcp tools`
  - lists MCP tools exposed into the normal tool registry; ids use `mcp__<server>__<tool>`
- `/mcp resources`
  - lists resources reported by MCP servers
- `/mcp prompts`
  - lists prompts reported by MCP servers
- `/mcp call <server> <tool> [json]`
  - manually invokes an MCP tool through the same registry and permission path as model tool calls
- `/mcp resource <server> <uri>`
  - reads an MCP resource through `mcp_read_resource`
- `/mcp prompt <server> <name> [json]`
  - gets an MCP prompt through `mcp_get_prompt`
- `/snapshots`
  - lists persisted git-backed snapshots for the current session, including snapshot tree hashes, tool call ids, and changed files
- `/yolo`
  - prints the current runtime status JSON, including whether YOLO mode is enabled
- `/yolo on`
  - enables YOLO mode for the current session/runtime; ask-class permissions are auto-approved but explicit deny rules still block execution
- `/yolo off`
  - disables YOLO mode so sensitive tool calls return to ask-before-act behavior
- `/compact`
  - forces a compaction pass if the session can be summarized further
- `/revert`
  - removes the last user turn together with its assistant/tool results
  - appends a `session-op` revert record so the change is auditable
- `/rollback last [file]`
  - reverts the most recent tracked file snapshot
  - if a file path is provided, only that file is restored from the latest snapshot
- `/rollback snapshot <id> [file]`
  - reverts a specific snapshot id, optionally scoped to one file
- `/rollback tool <tool_call_id> [file]`
  - reverts the tracked file changes produced by one tool call
- `/rollback task <task_id> [file]`
  - reverts all tracked file changes associated with a task id in reverse order
- `/rollback file <path>`
  - reverts the most recent snapshot that touched the given file
- `/retry`
  - reruns the last user turn after recording retry metadata
- `/todos`
  - lists persisted todo items for the current session
- `/todo add <text>`
  - adds a todo item; use it to track planned follow-up work inside the session
- `/todo done <index>`
  - marks a todo item as completed using a 1-based index from `/todos`
- `/todo clear`
  - removes all todo items from the current session
- `/agent <name>`
  - switches the active primary agent for the current session, for example `build` or `plan`
- `/agent show <name>`
  - prints the stored definition for a built-in or custom agent
- `/agent create <description>`
  - invokes the hidden generate agent, persists the result under `.openagent/agents/`, and reloads the registry
- `/cancel`
  - discards the current multiline input buffer before submission
- `/exit`
  - exits the REPL

## MCP Runtime

OpenAgent implements an OpenCode-style MCP integration where each MCP server is a managed runtime entity, and server tools are adapted into the existing tool registry rather than handled by a parallel path.

Full MCP rules are documented in [MCP.md](MCP.md).

Core implementation:

- `mcp/models.py`
  - structured server config, server state, and discovered tool info
- `mcp/client.py`
  - stdio JSON-RPC client plus remote StreamableHTTP/SSE client with auth prelude, fallback handling, timeout handling, and transport attempt traces
- `mcp/manager.py`
  - config discovery, auth storage, server lifecycle, capability cache, multi-server isolation, remote reconnect/ping/inspect, and reconnect-on-demand
- `mcp/tool.py`
  - adapts MCP tools/resources/prompts into normal `BaseTool` implementations
- `agent/runtime.py`
  - loads MCP config, connects enabled servers, registers dynamic MCP tools, and exposes CLI report/call helpers
- `tools/registry.py`
  - remains the single invocation point, so MCP tool calls still use lifecycle events, permission checks, truncation, and structured results

Config sources:

- `openagent.mcp.json`
- `.opencode/mcp.json`
- `OPENAGENT_MCP_CONFIG=/path/a.json:/path/b.json`
- `OPENAGENT_MCP=false` disables MCP without changing normal tool execution

Example config:

```json
{
  "mcpServers": {
    "filesystem": {
      "type": "stdio",
      "command": "mcp-server-filesystem",
      "args": ["{workspace}/work"],
      "enabled": true,
      "timeout": 30
    }
  }
}
```

Remote config is also supported:

```json
{
  "mcpServers": {
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

The repository includes `openagent.mcp.json` configured for:

- `filesystem`
  - `@modelcontextprotocol/server-filesystem`, scoped to `{workspace}/work`
- `git`
  - `mcp-git`, development/tooling validation
- `everything`
  - `@modelcontextprotocol/server-everything`, general MCP capability validation
- `memory`
  - `@modelcontextprotocol/server-memory`, knowledge graph memory for concrete cross-step state tasks
- `sequential-thinking`
  - `@modelcontextprotocol/server-sequential-thinking`, structured multi-step planning for workflow tasks

Remote validation config is provided separately in `openagent.mcp.remote.json` so local development does not fail when remote proxies are not running. It contains:

- `remote-memory`
  - StreamableHTTP with `X-API-Key: remote-demo`
- `remote-sequential`
  - StreamableHTTP planning server
- `remote-filesystem-sse`
  - SSE-only filesystem server used to prove HTTP-first fallback
- `remote-memory-oauth`
  - auth-required remote memory server used to validate `needs_auth` and reconnect after storing credentials

Optional local GitHub MCP configuration can be added in an ignored file such as `.openagent/mcp.github.json` and enabled through `OPENAGENT_MCP_CONFIG`. Example:

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

Install the validation servers when needed:

```bash
npm install -g @modelcontextprotocol/server-filesystem @modelcontextprotocol/server-everything mcp-git @modelcontextprotocol/server-memory @modelcontextprotocol/server-sequential-thinking mcp-proxy
```

Start remote validation proxies when you want to test remote MCP:

```bash
mcp-proxy --host 127.0.0.1 --port 8811 --apiKey remote-demo -- mcp-server-memory
mcp-proxy --host 127.0.0.1 --port 8812 -- mcp-server-sequential-thinking
mcp-proxy --host 127.0.0.1 --port 8813 --server sse -- mcp-server-filesystem /root/open-claude-code/work
mcp-proxy --host 127.0.0.1 --port 8814 --apiKey oauth-demo -- mcp-server-memory
```

CLI checks:

```bash
openagent --mcp
openagent --mcp-tools
openagent --mcp-resources
openagent --mcp-prompts
openagent --mcp-inspect filesystem
openagent --mcp-ping filesystem
openagent --mcp-trace
openagent --yolo --mcp-call git git_status '{"repo_path":"/root/open-claude-code"}'
openagent --yolo --mcp-call filesystem list_directory '{"path":"/root/open-claude-code/work"}'
openagent --yolo --mcp-call memory create_entities '{"entities":[{"name":"openagent-mcp-demo","entityType":"project_fact","observations":["MCP memory stores validation facts."]}]}'
openagent --yolo --mcp-call sequential-thinking sequentialthinking '{"thought":"Plan the MCP validation in one step.","nextThoughtNeeded":false,"thoughtNumber":1,"totalThoughts":1}'
```

Remote CLI checks:

```bash
OPENAGENT_MCP_CONFIG=openagent.mcp.remote.json openagent --mcp
OPENAGENT_MCP_CONFIG=openagent.mcp.remote.json openagent --mcp-inspect remote-filesystem-sse
OPENAGENT_MCP_CONFIG=openagent.mcp.remote.json openagent --mcp-trace
OPENAGENT_MCP_CONFIG=openagent.mcp.remote.json openagent --yolo --mcp-call remote-memory create_entities '{"entities":[{"name":"openagent-remote-demo","entityType":"project_fact","observations":["Created through remote MCP."]}]}'
OPENAGENT_MCP_CONFIG=openagent.mcp.remote.json openagent --yolo --mcp-call remote-filesystem-sse list_directory '{"path":"/root/open-claude-code/work"}'
OPENAGENT_MCP_CONFIG=openagent.mcp.remote.json openagent --mcp-ping remote-memory-oauth
OPENAGENT_MCP_CONFIG=openagent.mcp.remote.json openagent --mcp-auth remote-memory-oauth '{"access_token":"oauth-demo","header_name":"X-API-Key","prefix":""}'
```

GitHub MCP local checks:

```bash
npm install -g @modelcontextprotocol/server-github
OPENAGENT_MCP_CONFIG="openagent.mcp.json:.openagent/mcp.github.json" openagent --mcp-inspect github
OPENAGENT_MCP_CONFIG="openagent.mcp.json:.openagent/mcp.github.json" openagent --yolo --mcp-call github search_repositories '{"query":"openagent","perPage":3}'
OPENAGENT_MCP_CONFIG="openagent.mcp.json:.openagent/mcp.github.json" openagent --yolo --mcp-call github get_file_contents '{"owner":"modelcontextprotocol","repo":"servers","path":"README.md"}'
```

Agent-loop check:

```text
请使用 MCP filesystem 的 list_directory 工具列出 /root/open-claude-code/work 目录，然后只回复是否看到了 yolo_ok.txt。
```

Expected evidence in `/replay`:

```text
ToolRequest: mcp__filesystem__list_directory {"path": "/root/open-claude-code/work"}
ToolResult: mcp__filesystem__list_directory -> ...
```

Concrete multi-tool MCP task:

```text
请完成一个 MCP 综合验证任务：1. 使用 MCP sequential-thinking 做一步简短计划，2. 使用 MCP memory 写入实体 openagent-cli-mcp-final，观察内容为 CLI loop used MCP memory and sequential-thinking，3. 再用 MCP memory 搜索该实体，最后只回复是否搜索到了该实体。
```

Expected `/replay` evidence:

```text
ToolRequest: mcp__sequential_thinking__sequentialthinking ...
ToolRequest: mcp__memory__create_entities ...
ToolRequest: mcp__memory__search_nodes ...
```

Remote multi-server validation used in a persisted session:

```text
请完成一个远程 MCP 综合验证任务：1. 使用 remote-sequential 做一步简短计划，2. 使用 remote-memory 写入实体 remote-loop-b，观察内容为 remote multi server validation，3. 再搜索 remote-loop-b，最后只回复是否搜索到了该实体。
```

Observed `/replay` evidence:

```text
ToolRequest: mcp__remote_sequential__sequentialthinking ...
ToolRequest: mcp__remote_memory__create_entities ...
ToolRequest: mcp__remote_memory__search_nodes ...
```

Failure-recovery validation used in a persisted session:

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

Current limits:

- `stdio` MCP transport is implemented and verified.
- Remote `StreamableHTTP` transport is implemented and verified.
- Remote `SSE` fallback is implemented and verified.
- Auth is partially implemented: stored token/header credentials, `needs_auth`, and `needs_client_registration` are implemented; a full browser OAuth callback flow is not.
- resource and prompt capabilities are listed and callable through generic tools; some third-party servers may time out or return errors for specific resource URIs, and those failures are surfaced rather than hidden.
- MCP permission policy currently uses normal tool names such as `mcp__everything__echo`; dedicated `permission.mcp` namespacing can be added later if needed.

## Skill Runtime

OpenAgent implements an OpenCode-style native skill system. Skills are reusable instruction packages discovered from `SKILL.md` files, advertised to the model by name/description, and loaded lazily through one unified `skill` tool only when the task matches the description.

Full rules are documented in [SKILLS.md](SKILLS.md).

Core implementation:

- `skill/models.py`
  - `SkillInfo`, `LoadedSkill`, and structured discovery errors
- `skill/manager.py`
  - scans skill roots, parses frontmatter, validates names and required fields, resolves duplicates, and loads skill bodies plus bundled files
- `tools/builtin/integration.py`
  - exposes the unified `skill` tool with `action=list` and `name=<skill>`
- `agent/runtime.py`
  - injects available skill summaries into the system prompt and provides `--skills`, `--skill`, `/skills`, and `/skill <name>`; the model decides whether to call the unified `skill` tool for the current task
- `permission/policy.py`
  - evaluates `permission="skill"` with the skill name as the pattern, so agents can allow or deny individual skills using the same rule engine as tools

Discovery rules:

- Project-level OpenCode format:
  - `.opencode/skill/**/SKILL.md`
  - `.opencode/skills/**/SKILL.md`
- Project-level compatible formats:
  - `.claude/skills/**/SKILL.md`
  - `.agents/skills/**/SKILL.md`
- Global compatible formats:
  - `~/.config/opencode/skill/**/SKILL.md`
  - `~/.config/opencode/skills/**/SKILL.md`
  - `~/.opencode/skill/**/SKILL.md`
  - `~/.opencode/skills/**/SKILL.md`
  - `~/.claude/skills/**/SKILL.md`
  - `~/.agents/skills/**/SKILL.md`
  - `~/.codex/skills/**/SKILL.md`
- Additional roots:
  - `OPENAGENT_SKILL_PATHS=/path/a:/path/b`

Minimal `SKILL.md`:

```markdown
---
name: python-review
description: Use when reviewing Python code for bugs, tests, typing, and maintainability risks.
compatibility: [openagent]
license: MIT
metadata:
  short-description: Python review workflow
---

## Current Limits

| Area | Limitation |
|-------|------------|
| **Routing** | Heuristic-based, not model-native planning |
| **Checklists** | Optimized for explicit numbered tasks |
| **Hidden Agents** | Simpler than OpenCode's service stack |
| **Permissions** | CLI-centric UX, not rich approval UI |
| **MCP Streaming** | Tool results only, no live streaming |

---

## Development

### Running Tests

```bash
PYTHONPATH=src pytest -q
```

### Minimal Demo

```bash
PYTHONPATH=src python examples/minimal_demo.py
```

### Documentation

- [MCP.md](MCP.md) - Full Model Context Protocol documentation
- [SKILLS.md](SKILLS.md) - Skill system documentation
- [ROADMAP.md](ROADMAP.md) - Development roadmap
- [SESSION_TEST_TASKS.md](SESSION_TEST_TASKS.md) - Validation checklist

---

## License

MIT
