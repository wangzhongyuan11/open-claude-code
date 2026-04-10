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
export OPENAGENT_MODEL=doubao-seed-code-preview-latest
export ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/coding/v3
PYTHONPATH=src python -m openagent.cli.main --workspace .
```

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
