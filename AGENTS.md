# OpenAgent Project Instructions

Project-specific coding and verification rules for `open-claude-code` / `openagent`.
Merge these with global instructions and any narrower instructions in subdirectories.

## Project Purpose

`openagent` is a lightweight Python 3.11+ coding-agent runtime inspired by OpenCode-style architecture. The goal is to implement the behavior ourselves while using `/root/opencode/packages/opencode/` as a reference implementation, not as a source to copy blindly.

Core areas:
- `src/openagent/agent/`: top-level runtime, loop, subagents, routing, agent profiles.
- `src/openagent/cli/`: CLI entrypoint, REPL, slash commands, streaming UI.
- `src/openagent/session/`: session persistence, prompt construction, processing loop, compaction, summary, rollback/revert, todos.
- `src/openagent/tools/`: built-in tool registry, truncation, tool lifecycle.
- `src/openagent/mcp/`: MCP stdio/remote clients, manager, tool adapter, auth/config behavior.
- `src/openagent/providers/`: LLM provider integrations, especially Anthropic and Volcengine Ark.
- `src/openagent/skill/`: OpenCode-compatible `SKILL.md` discovery and loading.
- `tests/`: pytest coverage for runtime, CLI, sessions, tools, MCP, skills, providers, permissions.

## Reference Policy

- Treat `/root/opencode/packages/opencode/` as the complete OpenCode reference.
- Before implementing OpenCode-like behavior, inspect the relevant OpenCode module and summarize the behavior being ported or adapted.
- Do not copy large chunks mechanically. Reimplement in this Python codebase's style and architecture.
- If OpenCode behavior conflicts with this project's existing design, state the tradeoff and keep the smallest compatible implementation.

## Think Before Coding

- State assumptions before implementation when the request is ambiguous.
- If multiple interpretations exist, present them instead of silently choosing.
- Prefer the simplest implementation that satisfies the request.
- Push back on speculative features, broad rewrites, or abstractions that are not needed.
- Stop and ask when the success criteria cannot be inferred safely.

## Simplicity First

- No features beyond what was asked.
- No abstractions for single-use code.
- No configurability unless the user requested it or existing project patterns require it.
- No defensive error handling for scenarios that cannot happen in the current design.
- If an implementation gets large, re-check whether a smaller change would solve the same problem.

## Surgical Changes

- Touch only files directly related to the task.
- Match existing style, naming, data models, and test patterns.
- Do not refactor adjacent code, comments, or formatting unless required by the task.
- Remove only imports, variables, functions, or files made unused by your own change.
- Mention unrelated dead code or issues instead of deleting them.
- Preserve user changes in the worktree. Do not revert unrelated modified or untracked files.

## Verification Is Mandatory

Every code change needs verification. Prefer a tight loop:
1. Reproduce or define the target behavior.
2. Add or update focused tests when practical.
3. Run the narrowest relevant pytest target.
4. Run broader tests when shared runtime behavior changed.
5. Validate with a real `openagent` conversation when behavior affects the agent loop, tools, sessions, MCP, providers, CLI, skills, or subagents.

Common commands:
```bash
pip install -e ".[dev,anthropic]"
pytest
pytest tests/test_session_core.py
pytest tests/test_runtime_tasks.py
pytest tests/test_mcp_system.py
pytest tests/test_cli.py
./openagent.sh --workspace .
```

For Volcengine Ark work:
```bash
OPENAGENT_PROVIDER=volcengine \
ARK_API_KEY=<key> \
OPENAGENT_MODEL=<model> \
ARK_BASE_URL=https://ark.cn-beijing.volces.com/api/coding/v3 \
./openagent.sh --workspace .
```

## Real OpenAgent Validation

When validating agent behavior, use `openagent` itself. Do not fake, simulate, or hand-wave the result.

Required approach:
- Start the real CLI with `./openagent.sh --workspace .` or the relevant command under test.
- Conduct a complete multi-turn task like a real user would.
- Observe tool calls, files written/read, session state, stdout/stderr, and final assistant output.
- Judge correctness from the actual `openagent` result, not from expected text alone.
- If `openagent` behaves incorrectly, keep debugging and editing until the real conversation succeeds.
- Do not stop midway for user confirmation unless credentials, destructive actions, or external access make progress impossible.

Good smoke tasks are documented in `SESSION_TEST_TASKS.md`, including:
- minimal text round trip,
- file read through tool use,
- file write,
- multi-turn session resume,
- compaction/summary,
- subagent delegation,
- nonzero shell exit handling,
- inspect/replay output.

## Git Workflow

After each code modification:
- Run the relevant verification first.
- Review `git status --short` and stage only files changed for the current task.
- Commit with a concise message describing the completed change.
- Push the current branch to its configured remote.
- If there are pre-existing unrelated changes, leave them unstaged and mention that they were intentionally not included.
- If push is impossible because no remote/upstream exists or credentials fail, report the blocker and leave the local commit intact.

## Documentation And Config Changes

- Keep Markdown concise and operational.
- Prefer root-level `AGENTS.md` for project-wide agent behavior.
- Keep command examples executable from the repository root.
- Do not commit secrets from `.env`, local logs, `.openagent/`, or generated session artifacts.
