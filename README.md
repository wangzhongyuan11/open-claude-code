# openagent

A minimal Python coding agent runtime inspired by opencode-style architecture.

## What It Has

- Agent loop
- Tool registry / dispatch
- Session persistence
- Session processor, prompt builder, compaction, and summary
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
openagent --workspace . --prompt "创建一个 demo.txt"
```

Interactive commands:

- `/session`
- `/history`
- `/exit`

## Minimal Demo

```bash
PYTHONPATH=src python examples/minimal_demo.py
```

The demo uses a fake provider and exercises a real runtime, session store, and file-writing tool.

## Testing

```bash
PYTHONPATH=src pytest -q
```

## Session Runtime

The session layer is now the runtime center rather than a plain message store.

- `session/store.py`: persistence and schema migration
- `session/manager.py`: session orchestration and prompt preparation
- `session/processor.py`: message processing loop for LLM/tool interactions
- `session/llm.py`: provider invocation wrapper with event emission
- `session/prompt.py`: prompt/context assembly
- `session/compaction.py`: prompt-window planning and historical compaction
- `session/summary.py`: session summary generation
- `session/system.py`: session-aware system prompt construction

The runtime prompt is assembled from:

- base system prompt
- session identity / degraded recovery context
- historical summary synthetic message
- working-set context synthetic message
- recent real messages

## Manual Validation Tasks

See [`SESSION_TEST_TASKS.md`](./SESSION_TEST_TASKS.md) for a concrete prompt-by-prompt validation checklist, including:

- plain text roundtrip
- tool-use protocol
- session resume
- compaction / summary
- subagent
- bash error path
- processor / part persistence checks

## Work Log

Ongoing engineering changes are recorded in [`work_log.jsonl`](./work_log.jsonl).
