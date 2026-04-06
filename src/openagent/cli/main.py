from __future__ import annotations

import argparse
import codecs
import os
import shlex
import sys
import termios
from pathlib import Path
import tty
from typing import Any

from openagent.agent.runtime import build_default_runtime, build_session_manager
from openagent.config.env import load_dotenv
from openagent.session.todo import render_todos

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.key_binding import KeyBindings
except ImportError:  # pragma: no cover - exercised by fallback path
    PromptSession = None
    FileHistory = None
    KeyBindings = None

SHELL_COMMANDS = {
    "/help",
    "/session",
    "/agents",
    "/history",
    "/status",
    "/summary",
    "/inspect",
    "/replay",
    "/skills",
    "/snapshots",
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
/skills                   List discovered and permission-visible skills
/skill <name>             Load one skill through the unified skill tool
/snapshots                List persisted file snapshots for the current session
/yolo                     Print YOLO mode status
/yolo on                  Enable YOLO mode (auto-approve ask permissions, deny still applies)
/yolo off                 Disable YOLO mode
/compact                  Force a compaction pass if needed
/revert                   Remove the last user turn and its assistant/tool results
/rollback ...             Revert files from tracked snapshots (last/snapshot/tool/task/file)
/retry                    Re-run the last user turn
/todos                    List current persisted todos
/todo add <text>          Add a todo item (priority defaults to medium)
/todo done <index>        Mark a todo as completed (1-based index)
/todo clear               Remove all todo items
/agent <name>             Switch the active primary agent
/agent show <name>        Show a stored agent definition
/agent create <desc>      Generate and persist a custom agent
/cancel                   Discard the current input buffer
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
    parser.add_argument("--skills", action="store_true", help="List discovered and permission-visible skills and exit")
    parser.add_argument("--skill", default=None, help="Load one skill by name and exit")
    parser.add_argument("--prompt", default=None, help="Run one prompt and exit")
    parser.add_argument("--stream", action="store_true", help="Render assistant text deltas while the model is responding")
    parser.add_argument("--yolo", action="store_true", default=None, help="Enable YOLO mode for this runtime")
    return parser


def _print_session_summary(runtime) -> None:
    print(f"session: {runtime.session_id}")


def _build_stream_handler():
    state = {"printed": False, "in_reasoning": False, "printed_reasoning": False}

    def handle(event: dict[str, Any]) -> None:
        if event["type"] == "reasoning-start":
            if state["printed"]:
                print()
            print("[thinking] ", end="", flush=True)
            state["printed"] = True
            state["in_reasoning"] = True
            state["printed_reasoning"] = False
            return
        if event["type"] == "reasoning-delta":
            print(event["text"], end="", flush=True)
            state["printed"] = True
            state["printed_reasoning"] = True
            return
        if event["type"] == "reasoning-end":
            if state["in_reasoning"] and state["printed_reasoning"]:
                print()
            state["in_reasoning"] = False
            return
        if event["type"] == "text-start":
            return
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


def _classify_repl_text(text: str) -> tuple[str, str] | None:
    stripped = text.strip()
    if not stripped:
        return None
    if stripped == "/cancel":
        print("[cancelled]")
        return None
    if stripped in {"/exit", "exit", "quit"}:
        return ("command", "/exit")
    if "\n" not in text and (
        stripped in SHELL_COMMANDS
        or stripped.startswith("/todo ")
        or stripped.startswith("/agent ")
        or stripped.startswith("/skill ")
        or stripped.startswith("/yolo ")
        or stripped.startswith("/rollback ")
    ):
        return ("command", stripped)
    return ("message", text)


def _build_repl_session(workspace: str) -> PromptSession | None:
    if PromptSession is None or FileHistory is None or KeyBindings is None:
        return None
    history_dir = Path(workspace) / ".openagent"
    history_dir.mkdir(parents=True, exist_ok=True)
    bindings = KeyBindings()

    @bindings.add("enter")
    def _submit(event) -> None:
        event.app.exit(result=event.current_buffer.text)

    @bindings.add("c-j")
    def _newline(event) -> None:
        event.current_buffer.insert_text("\n")

    return PromptSession(
        multiline=True,
        key_bindings=bindings,
        prompt_continuation=lambda width, line_number, is_soft_wrap: "... ",
        bottom_toolbar=(
            "Enter 发送 | Ctrl+J 换行 | 右键粘贴可用 | /cancel 取消 | /help 帮助"
        ),
        history=FileHistory(str(history_dir / "repl_history")),
        mouse_support=False,
    )


def _move_cursor(text: str, cursor: int) -> tuple[int, int]:
    before = text[:cursor]
    row = before.count("\n")
    col = len(before.rsplit("\n", 1)[-1])
    return row, col


def _render_raw_buffer(text: str, cursor: int, previous_lines: int) -> int:
    lines = text.split("\n") if text else [""]
    total_lines = max(1, len(lines))
    if previous_lines:
        sys.stdout.write("\r")
        if previous_lines > 1:
            sys.stdout.write(f"\x1b[{previous_lines - 1}A")
        sys.stdout.write("\x1b[J")
    for index, line in enumerate(lines):
        prefix = "openagent> " if index == 0 else "... "
        if index:
            sys.stdout.write("\n")
        sys.stdout.write(prefix + line)
    row, col = _move_cursor(text, cursor)
    sys.stdout.write("\r")
    if total_lines > 1:
        sys.stdout.write(f"\x1b[{total_lines - 1}A")
    if row:
        sys.stdout.write(f"\x1b[{row}B")
    prefix_len = len("openagent> " if row == 0 else "... ")
    if prefix_len + col:
        sys.stdout.write(f"\x1b[{prefix_len + col}C")
    sys.stdout.flush()
    return total_lines


def _read_repl_input_raw() -> tuple[str, str] | None:
    if not sys.stdin.isatty():
        return None
    fd = sys.stdin.fileno()
    original = termios.tcgetattr(fd)
    text = ""
    cursor = 0
    rendered_lines = 0
    decoder = codecs.getincrementaldecoder("utf-8")()
    try:
        tty.setraw(fd)
        rendered_lines = _render_raw_buffer(text, cursor, rendered_lines)
        while True:
            chunk = os.read(fd, 1)
            if not chunk:
                sys.stdout.write("\n")
                return None
            if chunk in {b"\x03", b"\x04", b"\x1b", b"\r", b"\n", b"\x7f", b"\x08"}:
                decoder.reset()
                ch = chunk.decode("utf-8", errors="ignore")
            else:
                ch = decoder.decode(chunk, final=False)
                if not ch:
                    continue
            if ch == "\x03":
                sys.stdout.write("\n")
                return None
            if ch == "\x04":
                if not text:
                    sys.stdout.write("\n")
                    return None
                continue
            if ch == "\x1b":
                seq = os.read(fd, 2).decode("utf-8", errors="ignore")
                if seq == "[D" and cursor > 0:
                    cursor -= 1
                elif seq == "[C" and cursor < len(text):
                    cursor += 1
                elif seq == "[A":
                    row, col = _move_cursor(text, cursor)
                    if row > 0:
                        lines = text.split("\n")
                        prev_len = len(lines[row - 1])
                        target = min(prev_len, col)
                        cursor -= col + 1
                        cursor -= prev_len - target
                elif seq == "[B":
                    row, col = _move_cursor(text, cursor)
                    lines = text.split("\n")
                    if row < len(lines) - 1:
                        next_len = len(lines[row + 1])
                        cursor += (len(lines[row]) - col) + 1
                        cursor += min(next_len, col)
                rendered_lines = _render_raw_buffer(text, cursor, rendered_lines)
                continue
            elif ch in {"\r"}:
                sys.stdout.write("\n")
                item = _classify_repl_text(text)
                if item is not None:
                    return item
                text = ""
                cursor = 0
            elif ch == "\n":
                text = text[:cursor] + "\n" + text[cursor:]
                cursor += 1
            elif ch in {"\x7f", "\b"}:
                if cursor > 0:
                    text = text[: cursor - 1] + text[cursor:]
                    cursor -= 1
            elif ch and ch >= " ":
                text = text[:cursor] + ch + text[cursor:]
                cursor += 1
            rendered_lines = _render_raw_buffer(text, cursor, rendered_lines)
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, original)


def _read_repl_input(session: PromptSession | None = None) -> tuple[str, str] | None:
    if session is not None:
        while True:
            try:
                text = session.prompt("openagent> ")
            except (EOFError, KeyboardInterrupt):
                print()
                return None
            item = _classify_repl_text(text)
            if item is not None:
                return item
        return None

    raw_item = _read_repl_input_raw()
    if raw_item is not None:
        return raw_item

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
            if (
                stripped in SHELL_COMMANDS
                or stripped.startswith("/todo ")
                or stripped.startswith("/agent ")
                or stripped.startswith("/skill ")
                or stripped.startswith("/yolo ")
                or stripped.startswith("/rollback ")
            ):
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

    if args.skills:
        print(runtime.list_skills())
        return

    if args.skill:
        print(runtime.load_skill(args.skill))
        return

    if args.prompt is not None:
        _print_session_summary(runtime)
        _run_once(runtime, args.prompt, stream=args.stream)
        return

    _print_session_summary(runtime)
    repl_session = _build_repl_session(args.workspace)
    if repl_session is None:
        if sys.stdin.isatty():
            print("当前环境未安装 prompt_toolkit，使用内置多行编辑器：Enter 发送，Ctrl+J 换行，支持方向键编辑。")
        else:
            print("当前环境未安装 prompt_toolkit，回退到兼容输入模式：多行输入后仍需用 /end 提交。")
    else:
        print("已启用 prompt_toolkit 多行编辑器：Enter 发送，Ctrl+J 换行，支持方向键；已关闭鼠标捕获以兼容右键粘贴。")

    while True:
        item = _read_repl_input(repl_session)
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
        if item_type == "command" and user_input == "/skills":
            print(runtime.list_skills())
            continue
        if item_type == "command" and user_input.startswith("/skill "):
            parts = shlex.split(user_input)
            if len(parts) == 2:
                print(runtime.load_skill(parts[1]))
                continue
            print("Usage: /skill <name>")
            continue
        if item_type == "command" and user_input == "/snapshots":
            print(runtime.list_snapshots())
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
        if item_type == "command" and user_input.startswith("/rollback "):
            parts = shlex.split(user_input)
            if len(parts) == 2 and parts[1] == "last":
                print(runtime.rollback("last"))
                continue
            if len(parts) == 3 and parts[1] == "file":
                print(runtime.rollback("file", parts[2]))
                continue
            if len(parts) in {3, 4} and parts[1] in {"snapshot", "tool", "task"}:
                file_path = parts[3] if len(parts) == 4 else None
                print(runtime.rollback(parts[1], parts[2], file_path))
                continue
            if len(parts) == 3 and parts[1] == "last":
                print(runtime.rollback("last", file_path=parts[2]))
                continue
            print("Usage: /rollback last [file] | /rollback snapshot <id> [file] | /rollback tool <tool_call_id> [file] | /rollback task <task_id> [file] | /rollback file <path>")
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
