# Roadmap

## Stage 2: Runtime Stabilization

Goal:
- Make the agent reliable under repeated tool-use and multi-step confirmation flows.

Core changes:
- Add completion heuristics so the loop stops after clear success conditions instead of re-reading files.
- Strengthen per-tool postconditions for `delegate`, `read_file`, `bash`, and write/edit workflows.
- Add targeted integration smoke tests that exercise real CLI behavior, not only fake provider unit tests.
- Improve failure messages and session persistence for interrupted or degraded runs.

Exit criteria:
- `delegate` tasks complete without repetitive confirmation loops.
- Exact-output prompts remain exact under longer conversations.
- CLI never exits on loop instability; it degrades gracefully and keeps the session usable.

## Stage 3: Tooling Expansion

Goal:
- Expand the local coding workflow beyond the current MVP tools.

Core changes:
- Add dedicated `list_top_level`, `search_text`, and patch-oriented edit tools.
- Add richer file diff/edit workflows instead of exact-string replace only.
- Add safer shell execution controls and explicit output truncation metadata.

Exit criteria:
- Common repo navigation tasks do not require the model to improvise with noisy recursive listings.
- Editing tasks can handle multi-location changes more reliably.

## Stage 4: Session and Context Management

Goal:
- Make long-running sessions sustainable and restart-friendly.

Core changes:
- Add context compaction/summarization checkpoints.
- Add session metadata for last successful task, degraded state, and recovery hints.
- Add explicit transcript snapshots and resumable run markers.

Exit criteria:
- Large sessions do not degrade into unstable tool loops as quickly.
- A restarted agent can recover state without replaying full history mentally.

## Stage 5: Productization Interfaces

Goal:
- Turn current extension hooks into real integrations.

Core changes:
- Implement one real extension path first: MCP or LSP.
- Add configurable permission policy instead of allow-all default.
- Add structured provider configuration profiles.

Exit criteria:
- At least one extension hook is production-real, not placeholder protocol only.
- Permission decisions are visible and testable.

## Stage 6: UX and Observability

Goal:
- Make the agent easier to operate and debug interactively.

Core changes:
- Add `/help`, richer slash commands, and optional streaming output.
- Improve event inspection and session browsing.
- Add a reproducible smoke-test script for release verification.

Exit criteria:
- A new operator can start, inspect, resume, and debug the agent without reading source code first.
