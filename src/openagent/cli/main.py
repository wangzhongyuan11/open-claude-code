from __future__ import annotations

import argparse
import shlex

from openagent.agent.runtime import build_default_runtime, build_session_manager
from openagent.config.env import load_dotenv
from openagent.session.todo import render_todos


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Minimal coding agent CLI")
    parser.add_argument("--workspace", default=".", help="Workspace root")
    parser.add_argument("--session-id", default=None, help="Resume an existing session")
    parser.add_argument("--list-sessions", action="store_true", help="List local sessions and exit")
    parser.add_argument("--print-session", action="store_true", help="Print the current session id and exit")
    parser.add_argument("--inspect", action="store_true", help="Print a structured session inspection view and exit")
    parser.add_argument("--replay", action="store_true", help="Print a turn-by-turn session replay view and exit")
    parser.add_argument("--prompt", default=None, help="Run one prompt and exit")
    return parser


def _print_session_summary(runtime) -> None:
    print(f"session: {runtime.session_id}")


def _run_once(runtime, prompt: str) -> None:
    reply = runtime.run_turn(prompt)
    print(reply)


def main() -> None:
    load_dotenv()
    parser = build_parser()
    args = parser.parse_args()

    if args.list_sessions:
        manager = build_session_manager(workspace=args.workspace)
        for session in manager.list_sessions():
            print(f"{session.id}  {session.updated_at}  {session.workspace}")
        return

    runtime = build_default_runtime(
        workspace=args.workspace,
        session_id=args.session_id,
    )

    if args.print_session:
        _print_session_summary(runtime)
        return

    if args.inspect:
        print(runtime.inspect_session())
        return

    if args.replay:
        print(runtime.replay_session())
        return

    if args.prompt is not None:
        _print_session_summary(runtime)
        _run_once(runtime, args.prompt)
        return

    _print_session_summary(runtime)

    while True:
        try:
            user_input = input("openagent> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not user_input:
            continue
        if user_input in {"/exit", "exit", "quit"}:
            break
        if user_input == "/session":
            print(runtime.session_id)
            continue
        if user_input == "/history":
            for message in runtime.session.messages:
                print(f"[{message.role}] {message.content}")
            continue
        if user_input == "/status":
            print(runtime.status_report())
            continue
        if user_input == "/inspect":
            print(runtime.inspect_session())
            continue
        if user_input == "/replay":
            print(runtime.replay_session())
            continue
        if user_input == "/compact":
            print(runtime.compact_session())
            continue
        if user_input == "/revert":
            print(runtime.revert_last_turn())
            continue
        if user_input == "/retry":
            print(runtime.retry_last_turn())
            continue
        if user_input == "/todos":
            print(render_todos(runtime.session))
            continue
        if user_input.startswith("/todo "):
            parts = shlex.split(user_input)
            if len(parts) >= 3 and parts[1] == "add":
                print(runtime.add_todo(" ".join(parts[2:])))
                continue
            if len(parts) == 3 and parts[1] == "done":
                print(runtime.complete_todo(int(parts[2]) - 1))
                continue
            if len(parts) == 2 and parts[1] == "clear":
                print(runtime.clear_todos())
                continue
            print("Usage: /todo add <text> | /todo done <index> | /todo clear")
            continue
        try:
            reply = runtime.run_turn(user_input)
            print(reply)
        except Exception as exc:
            print(f"[error] {exc}")


if __name__ == "__main__":
    main()
