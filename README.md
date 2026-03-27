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

- `/session`
- `/status`
- `/history`
- `/inspect`
- `/replay`
- `/end`
- `/cancel`
- `/exit`

Interactive input mode:

- REPL now buffers multiline input by default
- only `/end` submits the current message
- `/cancel` discards the current buffered message
- slash commands such as `/status` or `/inspect` must be entered on an empty buffer

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

## Work Log

Ongoing engineering changes are recorded in [`work_log.jsonl`](./work_log.jsonl).
