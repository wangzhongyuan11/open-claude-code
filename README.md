# openagent

A minimal Python coding agent runtime inspired by opencode-style architecture.

## What It Has

- Agent loop
- Tool registry / dispatch
- Session persistence
- Session processor, prompt builder, compaction, and summary
- Basic streaming session processor
- Subagent delegation
- CLI with session commands
- Settings, logging, and JSONL events
- Extension hooks for permission / MCP / LSP / GitHub

## Project Layout

```text
src/openagent/
  agent/       runtime, loop, subagent
  cli/         command-line entry
  config/      settings loading
  domain/      core models
  events/      event bus and logger
  extensions/  permission and future integration hooks
  mcp/         Model Context Protocol server manager, stdio client, and tool adapters
  providers/   anthropic / volcengine
  session/     session store, manager, processor, prompt, compaction, summary
  skill/       OpenCode-style SKILL.md discovery, validation, and loading
  tools/       registry and builtin tools
```

## Core Architecture

`openagent` is organized around a session-centric runtime:

- `cli/main.py`
  - parses CLI flags, launches the runtime, handles interactive slash commands, permission prompts, and multiline input
- `agent/runtime.py`
  - top-level orchestrator
  - owns the active agent profile, current session, tool registry, provider, subagent manager, and runtime policy
- `session/manager.py`
  - creates / loads / saves sessions
  - builds prompt windows
  - synchronizes compaction, todos, retry/revert, and long-checklist state
- `session/processor.py`
  - the main think-act loop
  - consumes model output, executes tool calls, appends tool results, and decides when a turn should stop
- `tools/registry.py`
  - single entry point for tool execution
  - applies permission checks, lifecycle events, truncation, and structured result wrapping
- `permission/policy.py`
  - session-scoped ask-before-act policy
  - merges builtin agent rules, persisted `always` approvals, and YOLO behavior
- `session/store.py`
  - atomic session persistence on disk
  - the durable source for messages, todos, permission state, summaries, and runtime metadata

At runtime the main control flow is:

1. CLI receives user input and loads the active session.
2. `AgentRuntime.run_turn()` appends the user message, may auto-route / auto-delegate, and builds a prompt window.
3. `SessionProcessor.process()` calls the provider, receives assistant text/tool calls, executes tools via `ToolRegistry`, and appends structured tool messages.
4. `AgentRuntime` validates long checklist tasks, updates runtime metadata, persists the final turn, and emits JSONL events.
5. Subsequent turns rebuild context from persisted session state rather than transient memory.

The main persisted state flows are:

- messages / parts
  - `domain/messages.py`
  - `session/message_v2.py`
- session / status / todos / permission
  - `domain/session.py`
  - `session/store.py`
- event stream
  - `events/bus.py`
  - `.openagent/logs/<session_id>.jsonl`

The main runtime state flows are:

- active agent
  - `agent/registry.py`
  - `agent/routing.py`
  - `agent/runtime.py`
- prompt / compaction / summary
  - `session/prompt.py`
  - `session/compaction.py`
  - `session/summary.py`
- tool execution / permission / truncation
  - `tools/registry.py`
  - `permission/policy.py`
  - `tools/truncation.py`
- skill discovery / lazy injection
  - `skill/manager.py`
  - `tools/builtin/integration.py`
  - `agent/runtime.py`
- MCP server lifecycle / dynamic tool injection
  - `mcp/manager.py`
  - `mcp/client.py`
  - `mcp/tool.py`
  - `agent/runtime.py`

## Run

```bash
pip install -e ".[dev,anthropic]"
export ANTHROPIC_API_KEY=your_key
openagent
```

## Run With Volcengine Ark

Based on Volcengine's official OpenAI-compatible API docs, the provider uses:

- `OPENAGENT_PROVIDER=volcengine`
- `ARK_API_KEY` for auth
- `OPENAGENT_MODEL` for model or endpoint id
- optional `ARK_BASE_URL` or `OPENAGENT_BASE_URL`

Example:

```bash
export OPENAGENT_PROVIDER=volcengine
export ARK_API_KEY=your_ark_key
export OPENAGENT_MODEL=doubao-seed-code-preview-latest
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
OPENAGENT_MODEL=doubao-seed-code-preview-latest
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

# Python Review

Load this skill only for Python code review tasks. Read referenced files from this skill directory only when needed.
```

Skill rules and constraints:

- `name` is required and must match `^[a-z0-9][a-z0-9._-]{0,63}$`.
- Valid names: `python-review`, `openai-docs`, `skill_creator`, `docs.v1`.
- Invalid names: `PythonReview`, `bad skill`, `-leading-dash`, empty names, names longer than 64 characters.
- `description` is required and should state when to use the skill. It is the main matching signal exposed to the agent before loading the body.
- `compatibility`, `license`, and `metadata` are optional. `metadata` is preserved as structured data; unsupported fields are ignored rather than treated as runtime instructions.
- The Markdown body is required. Keep it focused on procedures, constraints, and references. Put large reference material in `references/`, scripts in `scripts/`, and templates/assets in `assets/`; the `skill` tool reports bundled files so the agent can load only what it needs.
- Duplicate skill names are allowed but reported as discovery errors; the later discovered skill replaces the earlier one.
- Invalid frontmatter, missing `name`/`description`, invalid names, empty bodies, path errors, and permission denials are reported in CLI/tool output instead of being silently ignored.

Permission behavior:

- Skills use a first-class `permission.skill` namespace.
- The permission pattern is the skill name, so `openai-*` or `skill-*` style wildcard rules can be represented by the existing permission rule engine.
- Denied skills are hidden from `/skills`, omitted from prompt skill summaries, and blocked by the `skill` tool.
- YOLO mode auto-approves ask-class permissions, but explicit `deny` rules still apply.
- The design leaves space for future per-agent skill filtering because skill visibility is evaluated against the active agent profile at prompt/tool time.

CLI checks:

```bash
openagent --skills
openagent --skill openai-docs
OPENAGENT_SKILL_PATHS=/tmp/my-skills openagent --skills
```

The current repository has been validated against existing global skills:

- `ljg-travel`
  - general workflow skill for cultural travel research
- `openai-docs`
  - OpenAI/OpenCode-related documentation workflow skill
- `skill-creator`
  - skill authoring and rules example
- `skill-installer`
  - installation workflow example

Model-driven skill usage:

- The runtime exposes only visible skill names and descriptions in the system prompt.
- The model decides whether a skill matches the task. If it does, it must call the unified `skill` tool to load that skill body before following the workflow.
- Full skill bodies remain lazy and are never auto-injected by deterministic runtime scoring.
- If no listed skill clearly matches, the model should continue without calling `skill`.

Bundled project-level validation skills:

- `playwright`
  - copied from the official `openai/skills` curated collection for browser automation workflow validation
- `security-threat-model`
  - copied from the official `openai/skills` curated collection for security analysis workflow validation
- `doc`
  - copied from the official `openai/skills` curated collection for document workflow validation

## Minimal Demo

```bash
PYTHONPATH=src python examples/minimal_demo.py
```

The demo uses a fake provider and exercises a real runtime, session store, and file-writing tool.

## Testing

```bash
PYTHONPATH=src pytest -q
```

Real streaming smoke check:

```bash
./openagent.sh --stream --prompt "请只回复 stream-live-ok。"
```

Expected behavior:

- terminal prints assistant text deltas directly
- `.openagent/logs/<session_id>.jsonl` contains `model.stream.event`
- `.openagent/logs/<session_id>.jsonl` contains `processor.part.appended`
- the persisted assistant message still contains a merged `text` part and a normal final `finish`

## Validation Recipes

Recommended CLI validation order:

1. Single-step lookup
```text
请定位 `src/openagent/tools/registry.py` 中负责工具权限检查的函数，只返回函数名和一句用途说明。
```

2. Single-task multi-step fix
```text
请在 `work/audit_demo` 下完成一个完整的单任务多步骤流程：
1. 创建 `math_utils.py`，内容是 `def add(a, b): return a - b`
2. 创建 `test_math_utils.py`，断言 `add(2, 3) == 5`
3. 运行这个目录下的 pytest，只先告诉我失败原因，不要修复
```

3. Same-session follow-up repair
```text
请直接修复这个 bug，并重新运行 `work/audit_demo` 下的 pytest；最后只告诉我是否通过。
```

4. Long checklist execution
```text
请完成下面这个多步任务，严格按顺序执行，并在最后只给我一个简短总结：

1. 创建目录 `work/checklist_demo/docs`、`work/checklist_demo/config`、`work/checklist_demo/output`。
2. 创建文件 `work/checklist_demo/docs/README.md`，内容为：
# Checklist Demo

- alpha
- beta
- delegate subtask
3. 创建文件 `work/checklist_demo/config/app.json`，内容为：
{
  "mode": "test",
  "name": "checklist_demo"
}
4. 将 `work/checklist_demo/config/app.json` 中的 `"mode": "test"` 修改为 `"mode": "production"`。
5. 请把下面任务委托给子代理完成：创建文件 `work/checklist_demo/output/subtask.txt`，内容为 `delegated-ok`。
6. 最后读取这三个文件并只告诉我三件事：
   - README 是否含 delegate subtask
   - mode 是否为 production
   - 子代理是否成功
```

5. Failure recovery
```text
再做一个失败恢复测试：
1. 先读取 `work/audit_demo/recover_target.txt`
2. 如果失败，解释原因
3. 然后创建这个文件，内容为 `recovered`
4. 再次读取并只回复最终内容
```

After long checklist runs, use `/todos`, `/status`, `/inspect`, and `/replay` to verify persisted progress and runtime history.

## Current Limits

- Routing is heuristic rather than model-native planning; it works for common plan/build/explore prompts but is not yet a full workflow engine.
- Checklist extraction is optimized for numbered file/dir/edit tasks; highly implicit natural-language workflows may still need another continuation round.
- Hidden agents (`title`, `summary`, `compaction`, `generate`) are functional but simpler than OpenCode’s richer internal service stack.
- `lsp` now uses a real stdio language-server client when a matching server is installed, with Python AST fallback preserved as a compatibility path.
- Tool permissions are session-scoped and consistent across delegated agents, but the UX is still CLI-centric rather than a richer approval UI.

## Session Runtime

The session layer is now the runtime center rather than a plain message store.

- `session/store.py`: persistence and schema migration
- `session/manager.py`: session orchestration and prompt preparation
- `session/processor.py`: message processing loop for LLM/tool interactions
- `session/message_builder.py`: incremental part builders for assistant/tool messages
- `session/llm.py`: provider invocation wrapper with event emission
- `session/prompt.py`: prompt/context assembly
- `session/compaction.py`: prompt-window planning and historical compaction
- `session/summary.py`: session summary generation
- `session/system.py`: session-aware system prompt construction
- `session/inspect.py`: inspect/replay views over persisted session state

The processor now runs through a basic streaming pipeline:

- `provider.stream_generate(...)`
- `session/llm.py` normalizes `reasoning-start/reasoning-delta/reasoning-end/text-start/text-delta/text-end`
- `session/processor.py` incrementally appends `reasoning` and `text` parts in stream order
- final assistant/tool messages are persisted after stream completion
- `openagent --stream` renders assistant thinking blocks live in the terminal, then naturally switches into normal answer text

The processor also contains session-level completion heuristics for common tool-driven tasks:

- exact file reads can stop on the trusted `read_file` result
- partial file reads such as “前 2 行” are not treated as whole-file exact reads
- write/create tasks can stop once the written content already matches the request
- edit tasks can stop once the requested replacement is already satisfied
- delegate tasks can stop directly on an authoritative subagent report when the user explicitly asks for the result

For numbered multi-step checklist requests, the runtime now performs a final-state validation pass before accepting an assistant `stop`:

- parses required directories, files, replacements, and final summary conditions from the user checklist
- validates the actual workspace state instead of trusting a premature textual success claim
- re-enters the loop with a continuation prompt when unfinished requirements remain
- stops cleanly after the final verification reads instead of drifting into extra tool loops
- treats `batch` verification reads the same as individual `read_file` checks when deciding whether the checklist is truly complete
- nudges the build agent to treat large numbered prompts as checklists and use `todowrite` / `task` deliberately when that helps preserve progress
- for long numbered requests, the runtime now mirrors the parsed checklist into session todos so the active turn sees an explicit pending-step list instead of relying only on the raw prompt text
- only accepts the turn once the final file states and required closing summary are satisfied
- supports delegated inline file-creation steps such as “创建文件 ...，内容为 `delegated-ok`” without accidentally rebinding the content to the previous file in the checklist
- dedents uniformly indented multi-line file blocks captured from REPL paste input so checklist validation does not confuse prompt indentation with intended file content
- compares JSON final files semantically instead of byte-for-byte so equivalent formatting does not trigger unnecessary continuation loops
- treats Python workflow setup files under `src/` and `tests/` as mutable when the checklist later says to run pytest and repair a bug, so the runtime does not keep insisting on the initial broken implementation after the fix is already verified
- can build deterministic four-point completion summaries for mixed verification batches such as `read_file + bash(pytest) + read_file + read_file`, instead of handing the final answer back to the model and risking another repair loop

Todo notes:

- manual todos created with `/todo` or `todowrite` are still just persisted task tracking; they do not auto-execute in the background
- `todowrite` is treated as internal session-state maintenance for writable agents, so it does not trigger an extra approval prompt; readonly agents still deny it
- long multi-step user messages can now populate `auto-checklist` todos to reduce forgetting within the same session and across resumed sessions
- if the model also writes a parallel todo checklist, the runtime preserves the existing `auto-checklist` entries and merges matching status updates into them instead of replacing them
- delegated subagent aliases are normalized defensively (`generic`, `python`, `simple`, `basic`, `default`, etc.) so long workflows do not stall just because the model picked a nearby but unsupported subagent label

The runtime prompt is assembled from:

- base system prompt
- session identity / degraded recovery context
- historical summary synthetic message
- working-set context synthetic message
- recent real messages

Session metadata also tracks recent runtime state, including:

- auto-generated session title from the first user turn
- `last_finish_reason`
- `last_loop_unstable`
- `last_loop_steps`
- `last_loop_tool_calls`
- `last_prompt_notes`
- `prompt_token_estimate`
- `compacted_token_estimate`
- `compaction_mode`

Persisted message parts now cover more operational and artifact cases:

## Agent System

The runtime now has an explicit opencode-inspired agent layer rather than a single hard-coded main prompt.

- `agent/profile.py`
  - defines `AgentProfile`, including `mode`, `hidden`, `steps`, model overrides, and tool visibility
- `agent/registry.py`
  - registers built-in agents and selects the default visible primary agent
- `agent/prompts.py`
  - stores the base coding prompt and agent-specific prompt overlays
- `agent/runtime.py`
  - binds the active agent profile to provider selection, system prompt construction, and visible tools
- `agent/subagent.py`
  - runs delegated work under a chosen subagent profile instead of one fixed subagent prompt

Built-in agents:

- `build`
  - default primary coding agent with the full toolset
- `plan`
  - primary planning agent that can inspect the repository and manage todos but must not edit files
- `general`
  - focused subagent for delegated implementation or investigation work
- `explore`
  - read-only exploration subagent optimized for codebase search
- `title`
  - hidden agent used to generate a session title
- `summary`
  - hidden agent used to generate a PR-style conversation summary
- `compaction`
  - hidden agent used to generate compaction summaries for long sessions
- `generate`
  - hidden agent used to generate custom agent definitions from natural language descriptions

How agent selection works:

- the active primary agent is stored in `session.metadata["active_agent"]`
- `--agent <name>` starts a runtime with that primary agent
- `/agent <name>` switches the active primary agent inside the current session
- `--agent-create <description>` and `/agent create <description>` generate and persist a custom agent
- `--agent-show <name>` and `/agent show <name>` inspect a built-in or persisted custom agent
- the runtime can auto-route between `build` and `plan` based on the user turn:
  - planning / read-only requests auto-switch `build -> plan`
  - implementation requests auto-switch `plan -> build`
- exploration-style requests from `build` or other read-only agents can auto-delegate to the `explore` subagent
- every automatic switch or delegation is persisted as an `agent` part in session history so `/inspect` and `/replay` can show the handoff chain
- hidden agents are not user-selectable and are invoked internally by the runtime

How hidden agents are used:

- the first user turn can trigger the hidden `title` agent to create a better session title
- compaction can call the hidden `compaction` agent before falling back to deterministic summarization
- `/summary` invokes the hidden `summary` agent before falling back to the local summary implementation
- agent creation invokes the hidden `generate` agent and persists the generated profile as markdown

Custom agent persistence:

- generated agents are stored under `.openagent/agents/<name>.md`
- each file uses front matter plus a prompt body
- startup merges built-in agents with all persisted custom agents
- custom agents can then be selected with `--agent <name>` or `/agent <name>`
- generated agents are sanitized before persistence:
  - reserved names are avoided automatically
  - duplicate identifiers are renamed safely
  - read-only reviewer / analysis agents get restricted tool visibility instead of inheriting the full build toolset

Real validation chain for the current agent system:

- listed visible agents with `/agents`
- created and persisted a custom `ts-reviewer` agent through the live CLI
- switched to `ts-reviewer` in the same session and verified it responded under the custom review prompt
- ran a `build` turn and confirmed normal tool-capable behavior
- switched to `plan` and confirmed the agent refused a requested file creation instead of editing the workspace
- switched back to `build`
- used `task` with `subagent_type=explore` to locate `active_agent` references in [`runtime.py`](/root/open-claude-code/src/openagent/agent/runtime.py)
- confirmed `--status` reflects the persisted `active_agent` for the session
- verified a single live session can:
  - auto-switch from `build` to `plan` for a read-only architecture analysis request
  - auto-switch back from `plan` to `build` for a file-creation request
  - auto-delegate an exploration request to `explore`
  - persist all handoffs as `agent` parts in the session log
- externally verified that the refused `plan` turn did not create `work/should_not_exist.txt`

- `text`: normal assistant text
- `reasoning`: internal reasoning notes when present
- `tool`: tool request / tool result state
- `file`: file content or file mutation record
- `patch`: unified diff for file mutations
- `snapshot`: lightweight content snapshot refs for rollback/debug
- `step-start` / `step-finish`: per-step boundaries and usage
- `compaction`: compaction event records
- `subtask`: delegate/subagent results
- `retry`: retry scheduling metadata

## Tool Runtime

The tool layer is now a proper execution subsystem instead of a loose handler map.

- `tools/base.py`
  - defines the shared tool protocol
  - every tool exposes a stable id/name, description, input schema, optional init hook, and output limits
- `tools/registry.py`
  - owns registration, lookup, filtered tool discovery, permission checks, argument validation, execution, output truncation, lifecycle events, and error wrapping
- `tools/truncation.py`
  - provides a central truncation layer for oversized tool output
  - writes full output to `.openagent/tool_outputs/` and returns a preview plus metadata when needed
- `session/snapshot.py`
  - tracks file state before mutating tool calls
  - computes changed files and diffs after the write completes
  - restores files by snapshot id, tool call id, task id, or file path
- `domain/tools.py`
  - defines `ToolSpec`, `ToolContext`, `ToolExecutionResult`, `ToolError`, `ToolArtifact`, and output limits

Current tool execution model:

- tools are registered through a single `ToolRegistry`
- the processor resolves model tool calls through the registry
- each invocation receives a context-aware `ToolContext`, including:
  - workspace
  - session id
  - current assistant message id
  - current tool call id
  - agent name
  - event bus
- mutating tools are snapshotted before execution when `OPENAGENT_SNAPSHOT` is enabled
- snapshot ids, changed files, and patch hashes are attached to mutating tool results

## Snapshot Rollback

Snapshot rollback is session-scoped and file-selective. It does not reset the whole workspace.

- snapshots are created before real mutating tool calls such as `write_file`, `append_file`, `edit_file`, `multiedit`, `replace_all`, `insert_text`, and `apply_patch`
- the snapshot backend uses an internal git repository under `.openagent/snapshot/` rather than relying on the user's main git history
- each snapshot stores:
  - a snapshot id
  - a git tree hash
  - session id
  - agent name
  - message id
  - tool call id
  - optional task id
- after the tool finishes, the runtime computes:
  - changed files
  - a patch hash
  - a diff against the stored git tree
- rollback supports:
  - latest snapshot
  - one snapshot id
  - one tool call id
  - one task id
  - one specific file
- new files are deleted on rollback, modified files are restored from the snapshot tree, and deleted files are recreated from the snapshot tree
- snapshot tracking can be disabled with `OPENAGENT_SNAPSHOT=false`
- every tool result is normalized into a shared result structure:
  - `title`
  - `content` / output
  - `metadata`
  - `error`
  - `artifacts`
  - `status`
  - `truncated`

Tool lifecycle events emitted to the JSONL event stream now include:

- `tool.pending`
- `tool.running`
- `tool.succeeded`
- `tool.failed`
- `tool.timed_out`
- `tool.cancelled`

The existing `tool.called` / `tool.completed` events are still emitted for compatibility.

Current tool sources supported by the registry:

- built-in tools registered directly from runtime
- custom tools registered programmatically via `register()`
- factory-based tools registered via `register_factory()`

This is the compatibility layer that future MCP/plugin/provider-specific tools should plug into.

Current built-in local tools:

- `ls`
- `glob`
- `grep`
- `codesearch`
- `read_file`
- `read_file_range`
- `read`
- `ensure_dir`
- `write_file`
- `write`
- `append_file`
- `edit_file`
- `edit`
- `multiedit`
- `replace_all`
- `insert_text`
- `apply_patch`
- `patch`
- `list_files`
- `bash`
- `background_task`
- `delegate`
- `task`
- `todowrite`
- `todoread`
- `question`
- `skill`
- `lsp`
- `read_symbol`
- `batch`
- `webfetch`
- `websearch`

The local coding toolchain now covers the common repository workflow:

- inspect directory structure
- find files by pattern
- search code/text
- read exact files or line ranges
- read a named Python symbol directly
- ensure a directory exists without shelling out to `mkdir -p`
- write/append/edit files
- replace all exact occurrences
- insert text around an anchor
- apply a unified diff patch
- run shell commands when a shell-native action is really needed
- run long-lived shell commands in the background without blocking the main dialogue loop

Additional opencode-style integrations now available:

- `task`
  - delegates a focused subtask to a subagent and returns a structured `<task_result>` block
- `todowrite` / `todoread`
  - read and replace the persisted session todo list through the tool runtime
- `question`
  - asks clarifying questions through the interactive CLI question handler
- `skill`
  - loads a `SKILL.md` from configured skill roots and injects it as structured context
- `lsp`
  - uses a real stdio LSP client for `workspaceSymbol`, `definition`, `references`, `documentSymbol`, and `hover` when a matching server is available
  - currently ships built-in server mappings for Python (`pyright-langserver`) and TypeScript/JavaScript (`typescript-language-server`)
  - falls back to local Python AST navigation if no matching LSP server is available
- `read_symbol`
  - reads a named Python function or class definition from a file without loading the whole file
- `batch`
  - executes multiple tool calls sequentially through the runtime and returns a structured summary
- `webfetch` / `websearch`
  - fetch public web resources and perform lightweight web search with structured metadata
- `background_task`
  - starts, inspects, or lists long-running shell tasks without blocking the main conversation loop
  - completion state, exit code, output summary, error, and output file path are persisted back into the session

Background task runtime notes:

- background work is executed by a detached worker process, not by an in-memory daemon thread
- session writes are serialized through per-session store locks and atomic file replacement
- task state is persisted in `.openagent/sessions/<session_id>/background_tasks.json`
- full command output is persisted in `.openagent/sessions/<session_id>/background_outputs/<task_id>.log`
- completion updates are appended back into session history as `session-op` messages carrying `background-task` parts
- subsequent turns refresh the session from disk before prompt construction, so the model can see newly completed background work

## Permission Runtime

The tool runtime now enforces a session-scoped permission model before each tool invocation.

- each agent can carry its own `permission_rules`
- permission decisions are evaluated centrally in [`registry.py`](/root/open-claude-code/src/openagent/tools/registry.py)
- ask-before-act replies support:
  - `once`
  - `always`
  - `reject`
- `always` writes a reusable approval rule into the current session
- YOLO mode auto-approves `ask` decisions but still preserves explicit `deny` rules
- permission asks and replies are appended into session history as `session-op` messages carrying `permission` parts
- delegated subagents reuse the same session-scoped permission state, so approvals and denies remain consistent across `task` / `delegate`

## Manual Validation Tasks

See [`SESSION_TEST_TASKS.md`](./SESSION_TEST_TASKS.md) for a concrete prompt-by-prompt validation checklist, including:

- plain text roundtrip
- tool-use protocol
- session resume
- compaction / summary
- subagent
- bash error path
- processor / part persistence checks
- native provider streaming and CLI live output
- status / retry / revert / todo helpers
- patch / snapshot / compaction / retry parts
- end-to-end numbered checklist tasks with continuation after premature assistant stop
- tool lifecycle events, structured tool results, and truncation behavior

Example continuous CLI validation chain for the tool runtime:

- inspect `src/openagent/tools` with `ls` / `glob`
- locate `tool.pending` and `tool.succeeded` with `grep`
- create a deliberately broken sample module under `work/tool_runtime_chain`
- run `pytest` with `bash` and observe failure
- repair the file with `apply_patch`
- rerun `pytest`
- delegate a note-creation subtask with `task`
- persist follow-up work with `todowrite` / `todoread`
- confirm the final file content and test result

Observed real-world recovery cases during validation:

- the CLI originally crashed because `AgentLoop` did not expose its `tool_context`; fixed by retaining `tool_context` on the loop object so runtime callbacks such as `question` can be injected safely
- `grep` originally failed when the model supplied an absolute `path_glob` inside the workspace; fixed by normalizing workspace-absolute globs before matching
- `read_file_range` originally rejected `start_line=0`; fixed by clamping the start line to 1 so the processor can recover from zero-based line guesses more gracefully

Recent tool additions for editing precision and code understanding:

- `replace_all`
  - replaces every exact occurrence of a string and returns structured mutation metadata
- `insert_text`
  - inserts text before or after an exact anchor string with full before/after snapshots
- `read_symbol`
  - extracts a Python function/class definition using AST parsing and returns just that symbol body
- `ensure_dir`
  - ensures a workspace directory exists and reports whether it had to be created

Recent background execution addition:

- `background_task`
  - `action=start` launches a long-running shell command in a detached worker process
  - `action=get` returns structured status for a specific task id
  - `action=list` returns all persisted background tasks for the current session

## Work Log

Ongoing engineering changes are recorded in [`work_log.jsonl`](./work_log.jsonl).
