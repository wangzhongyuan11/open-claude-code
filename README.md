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
openagent --workspace . --print-session
openagent --workspace . --session-id <session_id> --status
openagent --workspace . --session-id <session_id> --inspect
openagent --workspace . --session-id <session_id> --replay
openagent --workspace . --prompt "创建一个 demo.txt"
openagent --workspace . --stream --prompt "请只回复 stream-ok。"
```

Interactive commands:

- `/help`
- `/session`
- `/history`
- `/status`
- `/inspect`
- `/replay`
- `/compact`
- `/revert`
- `/retry`
- `/todos`
- `/todo add <text>`
- `/todo done <index>`
- `/todo clear`
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
- `/history`
  - prints the persisted message history in stored order
- `/status`
  - prints the structured session/runtime status JSON
- `/inspect`
  - prints a structured JSON view of recent messages, parts, and metadata
- `/replay`
  - prints a human-readable turn-by-turn replay
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

## Work Log

Ongoing engineering changes are recorded in [`work_log.jsonl`](./work_log.jsonl).
