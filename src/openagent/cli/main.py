from __future__ import annotations

import argparse
import codecs
import json
import os
import shlex
import sys
import termios
from dataclasses import dataclass
from pathlib import Path
import tty
from typing import Any

from openagent.agent.runtime import build_default_runtime, build_session_manager
from openagent.config.env import load_dotenv
from openagent.session.todo import render_todos

try:
    from prompt_toolkit import PromptSession
    from prompt_toolkit.completion import Completer, Completion
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.key_binding import KeyBindings
except ImportError:  # pragma: no cover - exercised by fallback path
    PromptSession = None
    Completer = None
    Completion = None
    FileHistory = None
    KeyBindings = None


@dataclass(frozen=True, slots=True)
class CommandSpec:
    command: str
    usage: str
    description: str
    category: str

    @property
    def accepts_args(self) -> bool:
        return " " in self.usage or "<" in self.usage or "[" in self.usage or "..." in self.usage


COMMAND_SPECS = [
    CommandSpec("/help", "/help [command]", "Show command help.", "General"),
    CommandSpec("/session", "/session", "Print the current session id.", "Session"),
    CommandSpec("/history", "/history", "Print persisted message history.", "Session"),
    CommandSpec("/status", "/status", "Print structured session/runtime status.", "Session"),
    CommandSpec("/summary", "/summary", "Print a PR-style conversation summary.", "Session"),
    CommandSpec("/inspect", "/inspect", "Print a structured JSON inspect view.", "Session"),
    CommandSpec("/replay", "/replay", "Print a turn-by-turn replay view.", "Session"),
    CommandSpec("/compact", "/compact", "Force a compaction pass if needed.", "Session"),
    CommandSpec("/revert", "/revert", "Remove the last user turn and its assistant/tool results.", "Session"),
    CommandSpec("/retry", "/retry", "Re-run the last user turn.", "Session"),
    CommandSpec("/agents", "/agents", "List visible agents and show the active one.", "Agent / Model"),
    CommandSpec("/agent", "/agent <name>", "Switch the active primary agent.", "Agent / Model"),
    CommandSpec("/agent", "/agent show <name>", "Show a stored agent definition.", "Agent / Model"),
    CommandSpec("/agent", "/agent create <description>", "Generate and persist a custom agent.", "Agent / Model"),
    CommandSpec("/model", "/model", "Show the active provider and model.", "Agent / Model"),
    CommandSpec("/model", "/model <model>", "Switch the active model for this runtime.", "Agent / Model"),
    CommandSpec("/model", "/model <provider>/<model>", "Switch provider and model together.", "Agent / Model"),
    CommandSpec("/model", "/model set <model>", "Switch the active model for this runtime.", "Agent / Model"),
    CommandSpec("/skills", "/skills", "List discovered and permission-visible skills.", "Skills"),
    CommandSpec("/skill", "/skill <name>", "Load one skill through the unified skill tool.", "Skills"),
    CommandSpec("/mcp", "/mcp", "List configured MCP servers and status.", "MCP"),
    CommandSpec("/mcp", "/mcp tools", "List MCP tools exposed through the tool registry.", "MCP"),
    CommandSpec("/mcp", "/mcp resources", "List MCP resources by server.", "MCP"),
    CommandSpec("/mcp", "/mcp prompts", "List MCP prompts by server.", "MCP"),
    CommandSpec("/mcp", "/mcp inspect <server>", "Show one MCP server's config, auth state, and discovery details.", "MCP"),
    CommandSpec("/mcp", "/mcp reconnect <server>", "Reconnect an MCP server and refresh tool injection.", "MCP"),
    CommandSpec("/mcp", "/mcp ping <server>", "Probe one MCP server and print connection status.", "MCP"),
    CommandSpec("/mcp", "/mcp auth <server> [json]", "Store auth for one MCP server and reconnect it.", "MCP"),
    CommandSpec("/mcp", "/mcp trace", "Print MCP transport attempts and recent errors.", "MCP"),
    CommandSpec("/mcp", "/mcp call <server> <tool> [json]", "Call an MCP tool manually.", "MCP"),
    CommandSpec("/mcp", "/mcp resource <server> <uri>", "Read an MCP resource manually.", "MCP"),
    CommandSpec("/mcp", "/mcp prompt <server> <name> [json]", "Get an MCP prompt manually.", "MCP"),
    CommandSpec("/snapshots", "/snapshots", "List persisted file snapshots for the current session.", "Safety"),
    CommandSpec("/rollback", "/rollback last [file]", "Revert files from the latest tracked snapshot.", "Safety"),
    CommandSpec("/rollback", "/rollback snapshot <id> [file]", "Revert files from a snapshot.", "Safety"),
    CommandSpec("/rollback", "/rollback tool <tool_call_id> [file]", "Revert files from a tool snapshot.", "Safety"),
    CommandSpec("/rollback", "/rollback task <task_id> [file]", "Revert files from a background task snapshot.", "Safety"),
    CommandSpec("/rollback", "/rollback file <path>", "Revert one file from the latest matching snapshot.", "Safety"),
    CommandSpec("/yolo", "/yolo", "Print YOLO mode status.", "Safety"),
    CommandSpec("/yolo", "/yolo on", "Enable YOLO mode for ask permissions.", "Safety"),
    CommandSpec("/yolo", "/yolo off", "Disable YOLO mode.", "Safety"),
    CommandSpec("/todos", "/todos", "List current persisted todos.", "Todo"),
    CommandSpec("/todo", "/todo add <text>", "Add a todo item.", "Todo"),
    CommandSpec("/todo", "/todo done <index>", "Mark a todo as completed.", "Todo"),
    CommandSpec("/todo", "/todo clear", "Remove all todo items.", "Todo"),
    CommandSpec("/cancel", "/cancel", "Discard the current input buffer.", "General"),
    CommandSpec("/exit", "/exit", "Exit the REPL.", "General"),
]

COMMANDS_BY_NAME = {spec.command: spec for spec in reversed(COMMAND_SPECS)}
COMMAND_NAMES = sorted(COMMANDS_BY_NAME)
SHELL_COMMANDS = {spec.command for spec in COMMAND_SPECS if not spec.accepts_args}
COMMAND_PREFIXES = tuple(sorted({f"{spec.command} " for spec in COMMAND_SPECS if spec.accepts_args}))


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
    parser.add_argument("--mcp", action="store_true", help="List configured MCP servers and exit")
    parser.add_argument("--mcp-tools", action="store_true", help="List MCP tools and exit")
    parser.add_argument("--mcp-resources", action="store_true", help="List MCP resources and exit")
    parser.add_argument("--mcp-prompts", action="store_true", help="List MCP prompts and exit")
    parser.add_argument("--mcp-inspect", default=None, help="Inspect one MCP server and exit")
    parser.add_argument("--mcp-reconnect", default=None, help="Reconnect one MCP server and exit")
    parser.add_argument("--mcp-ping", default=None, help="Ping one MCP server and exit")
    parser.add_argument("--mcp-auth", nargs="+", metavar=("SERVER", "JSON"), help="Store auth for one MCP server and reconnect it")
    parser.add_argument("--mcp-trace", action="store_true", help="Print MCP transport attempts and exit")
    parser.add_argument("--mcp-call", nargs=3, metavar=("SERVER", "TOOL", "JSON"), help="Call an MCP tool and exit")
    parser.add_argument("--mcp-resource", nargs=2, metavar=("SERVER", "URI"), help="Read an MCP resource and exit")
    parser.add_argument("--mcp-prompt", nargs=3, metavar=("SERVER", "NAME", "JSON"), help="Get an MCP prompt and exit")
    parser.add_argument("--prompt", default=None, help="Run one prompt and exit")
    parser.add_argument("--stream", action="store_true", help="Render assistant text deltas while the model is responding")
    parser.add_argument("--yolo", action="store_true", default=None, help="Enable YOLO mode for this runtime")
    return parser


def _print_session_summary(runtime) -> None:
    print(f"session: {runtime.session_id}")


def _format_command_help(command: str | None = None) -> str:
    if command:
        normalized = command if command.startswith("/") else f"/{command}"
        matches = [spec for spec in COMMAND_SPECS if spec.command == normalized]
        if not matches:
            return f"Unknown command `{command}`. Try /help."
        width = max(len(spec.usage) for spec in matches)
        lines = [f"{normalized}"]
        lines.extend(f"  {spec.usage.ljust(width)}  {spec.description}" for spec in matches)
        return "\n".join(lines)

    categories: dict[str, list[CommandSpec]] = {}
    for spec in COMMAND_SPECS:
        categories.setdefault(spec.category, []).append(spec)
    lines = ["Available interactive commands:"]
    for category, specs in categories.items():
        lines.append("")
        lines.append(f"{category}:")
        width = max(len(spec.usage) for spec in specs)
        seen: set[tuple[str, str]] = set()
        for spec in specs:
            key = (spec.usage, spec.description)
            if key in seen:
                continue
            seen.add(key)
            lines.append(f"  {spec.usage.ljust(width)}  {spec.description}")
    lines.append("")
    lines.append("Use /help <command> for command-specific help.")
    return "\n".join(lines)


HELP_TEXT = _format_command_help()


def _runtime_model_label(runtime) -> str:
    info = runtime.model_info()
    provider = info.get("provider") or "unknown"
    model = info.get("model") or "unknown"
    source = info.get("source")
    if source and source != "settings":
        return f"{provider}/{model} ({source})"
    return f"{provider}/{model}"


def _render_startup_banner(runtime, workspace: str, stream: bool) -> str:
    yolo = runtime.session.metadata.get("yolo_mode", "true" if runtime.settings.yolo_mode else "false")
    lines = [
        "OpenAgent",
        f"  session: {runtime.session_id}",
        f"  cwd:     {Path(workspace).resolve()}",
        f"  agent:   {runtime.agent_profile.name}",
        f"  model:   {_runtime_model_label(runtime)}",
        f"  stream:  {'on' if stream else 'off'}",
        f"  yolo:    {yolo}",
        "  tips:    /help  /model  /agents  /status",
    ]
    return "\n".join(lines)


def _build_bottom_toolbar(runtime, stream: bool):
    def toolbar() -> str:
        cwd = runtime.workspace.name or str(runtime.workspace)
        model = _runtime_model_label(runtime)
        yolo = runtime.session.metadata.get("yolo_mode", "true" if runtime.settings.yolo_mode else "false")
        return (
            f"cwd {cwd} | model {model} | agent {runtime.agent_profile.name} | "
            f"session {runtime.session_id[:8]} | stream {'on' if stream else 'off'} | "
            f"yolo {yolo} | Enter send | Ctrl+J newline | /help"
        )

    return toolbar


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
        or stripped in COMMANDS_BY_NAME
        or stripped.startswith(COMMAND_PREFIXES)
    ):
        return ("command", stripped)
    return ("message", text)


class _SlashCommandCompleter(Completer if Completer is not None else object):
    def __init__(self, runtime) -> None:
        self.runtime = runtime

    def get_completions(self, document, complete_event):  # pragma: no cover - prompt_toolkit integration
        text = document.text_before_cursor
        stripped = text.lstrip()
        if not stripped.startswith("/") or "\n" in text:
            return
        word = document.get_word_before_cursor(WORD=True)
        start_position = -len(word) if word else 0
        if stripped.startswith("/mcp "):
            yield from self._complete_words(
                ["tools", "resources", "prompts", "inspect", "reconnect", "ping", "auth", "trace", "call", "resource", "prompt"],
                word,
                start_position,
            )
            return
        if stripped.startswith("/agent "):
            yield from self._complete_agent(word, start_position)
            return
        if stripped.startswith("/skill "):
            yield from self._complete_skill(word, start_position)
            return
        if stripped.startswith("/model "):
            for candidate in self._model_candidates():
                if candidate.startswith(word):
                    yield Completion(candidate, start_position=start_position, display_meta="model")
            return
        fragment = stripped
        start_position = -len(fragment)
        for name in COMMAND_NAMES:
            if name.startswith(fragment):
                spec = COMMANDS_BY_NAME[name]
                yield Completion(name, start_position=start_position, display_meta=spec.description)

    def _complete_words(self, words: list[str], word: str, start_position: int):
        for candidate in words:
            if candidate.startswith(word):
                yield Completion(candidate, start_position=start_position, display_meta="subcommand")

    def _complete_agent(self, word: str, start_position: int):
        for profile in self.runtime.agent_registry.list(include_hidden=False):
            if profile.name.startswith(word):
                yield Completion(profile.name, start_position=start_position, display_meta=profile.description)

    def _complete_skill(self, word: str, start_position: int):
        try:
            result = self.runtime.skill_manager.discover()
        except Exception:
            return
        for skill in result.skills:
            if skill.name.startswith(word):
                yield Completion(skill.name, start_position=start_position, display_meta=skill.description)

    def _model_candidates(self) -> list[str]:
        info = self.runtime.model_info()
        current = str(info.get("model") or "")
        provider = str(info.get("provider") or "")
        candidates = [current]
        if provider and current:
            candidates.append(f"{provider}/{current}")
        candidates.extend(item.strip() for item in os.getenv("OPENAGENT_MODELS", "").split(",") if item.strip())
        return sorted({item for item in candidates if item})


def _build_repl_session(workspace: str, runtime, stream: bool) -> PromptSession | None:
    if PromptSession is None or FileHistory is None or KeyBindings is None or Completion is None:
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
        bottom_toolbar=_build_bottom_toolbar(runtime, stream),
        completer=_SlashCommandCompleter(runtime),
        complete_while_typing=True,
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
                or stripped in COMMANDS_BY_NAME
                or stripped.startswith(COMMAND_PREFIXES)
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

    if args.mcp:
        print(runtime.mcp_status_report())
        return

    if args.mcp_tools:
        print(runtime.mcp_tools_report())
        return

    if args.mcp_resources:
        print(runtime.mcp_resources_report())
        return

    if args.mcp_prompts:
        print(runtime.mcp_prompts_report())
        return

    if args.mcp_inspect:
        print(runtime.mcp_inspect(args.mcp_inspect))
        return

    if args.mcp_reconnect:
        print(runtime.mcp_reconnect(args.mcp_reconnect))
        return

    if args.mcp_ping:
        print(runtime.mcp_ping(args.mcp_ping))
        return

    if args.mcp_auth:
        server = args.mcp_auth[0]
        payload = json.loads(" ".join(args.mcp_auth[1:])) if len(args.mcp_auth) > 1 else None
        print(runtime.mcp_auth(server, payload))
        return

    if args.mcp_trace:
        print(runtime.mcp_trace_report())
        return

    if args.mcp_call:
        server, tool, raw_args = args.mcp_call
        print(runtime.mcp_call(server, tool, json.loads(raw_args)))
        return

    if args.mcp_resource:
        server, uri = args.mcp_resource
        print(runtime.mcp_read_resource(server, uri))
        return

    if args.mcp_prompt:
        server, name, raw_args = args.mcp_prompt
        print(runtime.mcp_get_prompt(server, name, json.loads(raw_args)))
        return

    if args.prompt is not None:
        _print_session_summary(runtime)
        _run_once(runtime, args.prompt, stream=args.stream)
        return

    print(_render_startup_banner(runtime, args.workspace, args.stream))
    repl_session = _build_repl_session(args.workspace, runtime, args.stream)
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
        if item_type == "command" and (user_input == "/help" or user_input.startswith("/help ")):
            parts = shlex.split(user_input)
            print(_format_command_help(parts[1] if len(parts) > 1 else None))
            continue
        if item_type == "command" and user_input == "/session":
            print(runtime.session_id)
            continue
        if item_type == "command" and user_input == "/agents":
            print(runtime.list_agents())
            continue
        if item_type == "command" and (user_input == "/model" or user_input.startswith("/model ")):
            parts = shlex.split(user_input)
            if len(parts) == 1:
                print(runtime.model_report())
                continue
            if len(parts) == 2:
                print(runtime.switch_model(parts[1]))
                continue
            if len(parts) == 3 and parts[1] == "set":
                print(runtime.switch_model(parts[2]))
                continue
            print("Usage: /model | /model <model> | /model <provider>/<model> | /model set <model>")
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
        if item_type == "command" and user_input.startswith("/mcp"):
            parts = shlex.split(user_input)
            if len(parts) == 1:
                print(runtime.mcp_status_report())
                continue
            if len(parts) == 2 and parts[1] == "tools":
                print(runtime.mcp_tools_report())
                continue
            if len(parts) == 2 and parts[1] == "resources":
                print(runtime.mcp_resources_report())
                continue
            if len(parts) == 2 and parts[1] == "prompts":
                print(runtime.mcp_prompts_report())
                continue
            if len(parts) == 3 and parts[1] == "inspect":
                print(runtime.mcp_inspect(parts[2]))
                continue
            if len(parts) == 3 and parts[1] == "reconnect":
                print(runtime.mcp_reconnect(parts[2]))
                continue
            if len(parts) == 3 and parts[1] == "ping":
                print(runtime.mcp_ping(parts[2]))
                continue
            if len(parts) >= 3 and parts[1] == "auth":
                try:
                    payload = json.loads(" ".join(parts[3:])) if len(parts) > 3 else None
                    print(runtime.mcp_auth(parts[2], payload))
                except Exception as exc:
                    print(f"MCP auth failed: {exc}")
                continue
            if len(parts) == 2 and parts[1] == "trace":
                print(runtime.mcp_trace_report())
                continue
            if len(parts) >= 4 and parts[1] == "call":
                try:
                    arguments = json.loads(" ".join(parts[4:])) if len(parts) > 4 else {}
                    print(runtime.mcp_call(parts[2], parts[3], arguments))
                except Exception as exc:
                    print(f"MCP call failed: {exc}")
                continue
            if len(parts) >= 4 and parts[1] == "resource":
                try:
                    print(runtime.mcp_read_resource(parts[2], " ".join(parts[3:])))
                except Exception as exc:
                    print(f"MCP resource failed: {exc}")
                continue
            if len(parts) >= 4 and parts[1] == "prompt":
                try:
                    arguments = json.loads(" ".join(parts[4:])) if len(parts) > 4 else {}
                    print(runtime.mcp_get_prompt(parts[2], parts[3], arguments))
                except Exception as exc:
                    print(f"MCP prompt failed: {exc}")
                continue
            print("Usage: /mcp | /mcp tools | /mcp resources | /mcp prompts | /mcp inspect <server> | /mcp reconnect <server> | /mcp ping <server> | /mcp auth <server> [json] | /mcp trace | /mcp call <server> <tool> [json] | /mcp resource <server> <uri> | /mcp prompt <server> <name> [json]")
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
