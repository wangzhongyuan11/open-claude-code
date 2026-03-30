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
  providers/   anthropic / volcengine
  session/     session store, manager, processor, prompt, compaction, summary
  tools/       registry and builtin tools
```

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
- `/yolo`
- `/yolo on`
- `/yolo off`
- `/compact`
- `/revert`
- `/retry`
- `/todos`
- `/todo add <text>`
- `/todo done <index>`
- `/todo clear`
- `/agent <name>`
- `/agent show <name>`
- `/agent create <desc>`
- `/end`
- `/cancel`
- `/exit`

Interactive input mode:

- REPL now buffers multiline input by default
- only `/end` submits the current message
- `/cancel` discards the current buffered message
- slash commands such as `/status` or `/inspect` must be entered on an empty buffer

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
- `/end`
  - submits the current multiline input buffer as one user message
- `/exit`
  - exits the REPL

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
- `session/llm.py` emits stream events
- `session/processor.py` incrementally appends message parts
- final assistant/tool messages are persisted after stream completion
- `openagent --stream` renders assistant text deltas live in the terminal

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
- only accepts the turn once the final file states and required closing summary are satisfied

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
  - provides AST-based Python fallback navigation plus a hook for an external LSP handler
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
