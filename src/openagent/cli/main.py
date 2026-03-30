from __future__ import annotations

import argparse
import shlex
from typing import Any

from openagent.agent.runtime import build_default_runtime, build_session_manager
from openagent.config.env import load_dotenv
from openagent.session.todo import render_todos

SHELL_COMMANDS = {
    "/help",
    "/session",
    "/agents",
    "/history",
    "/status",
    "/summary",
    "/inspect",
    "/replay",
    "/yolo",
    "/compact",
    "/revert",
    "/retry",
    "/todos",
}

HELP_TEXT = """Available interactive commands:
/help                     Show this help text
/session                  Print the current session id
/agents                   List visible agents and show the active one
/history                  Print persisted message history
/status                   Print structured session/runtime status
/summary                  Print a PR-style conversation summary
/inspect                  Print a structured JSON inspect view
/replay                   Print a turn-by-turn replay view
/yolo                     Print YOLO mode status
/yolo on                  Enable YOLO mode (auto-approve ask permissions, deny still applies)
/yolo off                 Disable YOLO mode
/compact                  Force a compaction pass if needed
/revert                   Remove the last user turn and its assistant/tool results
/retry                    Re-run the last user turn
/todos                    List current persisted todos
/todo add <text>          Add a todo item (priority defaults to medium)
/todo done <index>        Mark a todo as completed (1-based index)
/todo clear               Remove all todo items
/agent <name>             Switch the active primary agent
/agent show <name>        Show a stored agent definition
/agent create <desc>      Generate and persist a custom agent
/cancel                   Discard the current multiline input buffer
/end                      Submit the current multiline input buffer
/exit                     Exit the REPL"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Minimal coding agent CLI")
    parser.add_argument("--workspace", default=".", help="Workspace root")
    parser.add_argument("--session-id", default=None, help="Resume an existing session")
    parser.add_argument("--agent", default=None, help="Select the active primary agent")
    parser.add_argument("--agents", action="store_true", help="List visible agents and exit")
    parser.add_argument("--agent-show", default=None, help="Show a specific agent definition and exit")
    parser.add_argument("--agent-create", default=None, help="Generate and persist a custom agent, then exit")
    parser.add_argument("--list-sessions", action="store_true", help="List local sessions and exit")
    parser.add_argument("--print-session", action="store_true", help="Print the current session id and exit")
    parser.add_argument("--status", action="store_true", help="Print session status and exit")
    parser.add_argument("--summary", action="store_true", help="Print a PR-style conversation summary and exit")
    parser.add_argument("--inspect", action="store_true", help="Print a structured session inspection view and exit")
    parser.add_argument("--replay", action="store_true", help="Print a turn-by-turn session replay view and exit")
    parser.add_argument("--prompt", default=None, help="Run one prompt and exit")
    parser.add_argument("--stream", action="store_true", help="Render assistant text deltas while the model is responding")
    parser.add_argument("--yolo", action="store_true", help="Enable YOLO mode for this runtime")
    return parser


def _print_session_summary(runtime) -> None:
    print(f"session: {runtime.session_id}")


def _build_stream_handler():
    state = {"printed": False}

    def handle(event: dict[str, Any]) -> None:
        if event["type"] == "text-delta":
            print(event["text"], end="", flush=True)
            state["printed"] = True

    return handle, state


def _run_once(runtime, prompt: str, stream: bool = False) -> None:
    if not stream:
        reply = runtime.run_turn(prompt)
        print(reply)
        return
    handler, state = _build_stream_handler()
    reply = runtime.run_turn(prompt, stream_handler=handler)
    if state["printed"]:
        print()
    elif reply:
        print(reply)


def _question_handler(questions: list[dict[str, Any]]) -> list[str]:
    answers: list[str] = []
    print("[question] Agent needs clarification.")
    for index, item in enumerate(questions, start=1):
        prompt = item.get("question", f"Question #{index}")
        header = item.get("header")
        if header:
            print(f"[question:{header}] {prompt}")
        else:
            print(f"[question] {prompt}")
        try:
            answer = input("answer> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            answer = ""
        answers.append(answer or "Unanswered")
    return answers


def _permission_handler(request) -> str:
    print("[permission] Tool requires approval before execution.")
    print(f"  agent: {request.agent_name}")
    print(f"  tool: {request.tool_name}")
    print(f"  permission: {request.permission}")
    print(f"  target: {request.pattern}")
    if request.metadata:
        preview = request.metadata.get("command") or request.metadata.get("target_agent") or request.metadata.get("kind")
        if preview:
            print(f"  detail: {preview}")
    while True:
        try:
            answer = input("approve [o]nce / [a]lways / [r]eject > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return "reject"
        if answer in {"o", "once"}:
            return "once"
        if answer in {"a", "always"}:
            return "always"
        if answer in {"r", "reject", "n", "no"}:
            return "reject"
        print("Please answer with once, always, or reject.")


def _read_repl_input() -> tuple[str, str] | None:
    buffer: list[str] = []
    while True:
        prompt = "openagent> " if not buffer else "... "
        try:
            raw_line = input(prompt)
        except (EOFError, KeyboardInterrupt):
            print()
            return None
        line = raw_line.rstrip("\n")
        stripped = line.strip()
        if not buffer:
            if not stripped:
                continue
            if stripped in {"/exit", "exit", "quit"}:
                return ("command", "/exit")
            if stripped in SHELL_COMMANDS or stripped.startswith("/todo ") or stripped.startswith("/agent ") or stripped.startswith("/yolo "):
                return ("command", stripped)
        if stripped == "/cancel":
            print("[cancelled]")
            buffer.clear()
            continue
        if stripped == "/end":
            message = "\n".join(buffer).strip("\n")
            if not message.strip():
                buffer.clear()
                continue
            return ("message", message)
        buffer.append(line)


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
        agent_name=args.agent,
        yolo=args.yolo,
    )
    runtime.set_question_handler(_question_handler)
    runtime.set_permission_handler(_permission_handler)

    if args.print_session:
        _print_session_summary(runtime)
        return

    if args.status:
        print(runtime.status_report())
        return

    if args.agents:
        print(runtime.list_agents())
        return

    if args.agent_show:
        print(runtime.show_agent(args.agent_show))
        return

    if args.agent_create:
        print(runtime.create_agent(args.agent_create))
        return

    if args.summary:
        print(runtime.conversation_summary())
        return

    if args.inspect:
        print(runtime.inspect_session())
        return

    if args.replay:
        print(runtime.replay_session())
        return

    if args.prompt is not None:
        _print_session_summary(runtime)
        _run_once(runtime, args.prompt, stream=args.stream)
        return

    _print_session_summary(runtime)
    print("输入多行消息后，用 /end 提交；输入 /cancel 放弃当前输入。Slash 命令需要在空输入状态下单独输入。")

    while True:
        item = _read_repl_input()
        if item is None:
            break
        item_type, user_input = item
        if user_input in {"/exit", "exit", "quit"}:
            break
        if item_type == "command" and user_input == "/help":
            print(HELP_TEXT)
            continue
        if item_type == "command" and user_input == "/session":
            print(runtime.session_id)
            continue
        if item_type == "command" and user_input == "/agents":
            print(runtime.list_agents())
            continue
        if item_type == "command" and user_input == "/history":
            for message in runtime.session.messages:
                print(f"[{message.role}] {message.content}")
            continue
        if item_type == "command" and user_input == "/status":
            print(runtime.status_report())
            continue
        if item_type == "command" and user_input == "/summary":
            print(runtime.conversation_summary())
            continue
        if item_type == "command" and user_input == "/inspect":
            print(runtime.inspect_session())
            continue
        if item_type == "command" and user_input == "/replay":
            print(runtime.replay_session())
            continue
        if item_type == "command" and user_input == "/yolo":
            print(runtime.status_report())
            continue
        if item_type == "command" and user_input in {"/yolo on", "/yolo off"}:
            print(runtime.set_yolo_mode(user_input.endswith("on")))
            continue
        if item_type == "command" and user_input == "/compact":
            print(runtime.compact_session())
            continue
        if item_type == "command" and user_input == "/revert":
            print(runtime.revert_last_turn())
            continue
        if item_type == "command" and user_input == "/retry":
            print(runtime.retry_last_turn())
            continue
        if item_type == "command" and user_input == "/todos":
            print(render_todos(runtime.session))
            continue
        if item_type == "command" and user_input.startswith("/todo "):
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
        if item_type == "command" and user_input.startswith("/agent "):
            parts = shlex.split(user_input)
            if len(parts) == 2:
                print(runtime.switch_agent(parts[1]))
                continue
            if len(parts) >= 3 and parts[1] == "show":
                print(runtime.show_agent(parts[2]))
                continue
            if len(parts) >= 3 and parts[1] == "create":
                print(runtime.create_agent(" ".join(parts[2:])))
                continue
            print("Usage: /agent <name> | /agent show <name> | /agent create <description>")
            continue
        try:
            if args.stream:
                handler, state = _build_stream_handler()
                reply = runtime.run_turn(user_input, stream_handler=handler)
                if state["printed"]:
                    print()
                elif reply:
                    print(reply)
            else:
                reply = runtime.run_turn(user_input)
                print(reply)
        except Exception as exc:
            print(f"[error] {exc}")


if __name__ == "__main__":
    main()
