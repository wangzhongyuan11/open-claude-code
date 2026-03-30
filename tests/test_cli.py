from argparse import Namespace

from openagent.cli.main import _read_repl_input, build_parser


def test_cli_parser_accepts_prompt_and_print_session():
    parser = build_parser()

    args: Namespace = parser.parse_args(
        ["--workspace", ".", "--print-session", "--status", "--prompt", "hello", "--stream", "--agent", "plan"]
    )

    assert args.workspace == "."
    assert args.print_session is True
    assert args.status is True
    assert args.prompt == "hello"
    assert args.stream is True
    assert args.agent == "plan"


def test_cli_parser_accepts_agent_create_and_show():
    parser = build_parser()

    args: Namespace = parser.parse_args(["--agent-create", "TypeScript reviewer", "--agent-show", "build"])

    assert args.agent_create == "TypeScript reviewer"
    assert args.agent_show == "build"


def test_repl_reader_collects_multiline_until_end(monkeypatch):
    inputs = iter(["第一行", "第二行", "/end"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

    item = _read_repl_input()

    assert item == ("message", "第一行\n第二行")


def test_repl_reader_executes_command_only_when_buffer_empty(monkeypatch):
    inputs = iter(["/help"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

    item = _read_repl_input()

    assert item == ("command", "/help")


def test_repl_reader_cancel_discards_buffer(monkeypatch):
    inputs = iter(["第一行", "/cancel", "/status"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

    item = _read_repl_input()

    assert item == ("command", "/status")


def test_repl_reader_treats_yolo_toggle_as_command(monkeypatch):
    inputs = iter(["/yolo on"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

    item = _read_repl_input()

    assert item == ("command", "/yolo on")
