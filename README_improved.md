# open-claude-code (OpenAgent)

![Python](https://img.shields.io/badge/python-3.11+-blue.svg)
![License](https://img.shields.io/badge/license-MIT-green.svg)
![Version](https://img.shields.io/badge/version-0.1.0-orange.svg)
![Stars](https://img.shields.io/github/stars/wangzhongyuan11/open-claude-code)

A minimal Python coding agent runtime inspired by OpenCode-style architecture with full MCP support.

## Project Goals

`openagent` (the core runtime of open-claude-code) aims to provide a **lightweight, extensible** coding agent runtime with:

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

> For complete MCP rules, server configuration, and validation examples, see **[MCP.md](MCP.md)**.

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

> Full skill rules, discovery paths, and validation are documented in **[SKILLS.md](SKILLS.md)**.

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

See full CLI documentation for complete startup options and interactive commands. Quick reference:

```bash
# Startup options
openagent --workspace .                    # Set workspace
openagent --agent plan                   # Start with specific agent
openagent --session-id <id>              # Resume session
openagent --list-sessions               # List all sessions
```

### Interactive Commands (Highlights)
| Command | Description |
|----------|-------------|
| `/help` | Show full help |
| `/status` | Session/runtime status |
| `/summary` | PR-style conversation summary |
| `/todos` | Todo list management |
| `/yolo on/off` | Auto-approve mode |
| `/exit` | Exit REPL |

> Full CLI reference is available via `/help` in the interactive REPL.

---

## Volcengine Ark Support

```bash
# Configure Volcengine Ark
export OPENAGENT_PROVIDER=volcengine
export ARK_API_KEY=your_ark_key
export OPENAGENT_MODEL=ark-code-latest
export ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/coding/v3

# Run
python -m openagent.cli.main --workspace .
```

You can also use a local `.env` file:
```bash
cp .env.example .env
# Fill in your Ark API key and model info
chmod +x openagent.sh
./openagent.sh
```

---

## Documentation

- [MCP.md](MCP.md) - Full Model Context Protocol implementation details
- [SKILLS.md](SKILLS.md) - Skill system specification and usage guide
