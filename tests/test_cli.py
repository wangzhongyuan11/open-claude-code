from argparse import Namespace

from openagent.cli.main import _build_stream_handler, _classify_repl_text, _read_repl_input, build_parser


def test_cli_parser_accepts_prompt_and_print_session():
    parser = build_parser()

    args: Namespace = parser.parse_args(
        [
            "--workspace",
            ".",
            "--print-session",
            "--status",
            "--prompt",
            "hello",
            "--stream",
            "--agent",
            "plan",
            "--skills",
            "--skill",
            "openai-docs",
        ]
    )

    assert args.workspace == "."
    assert args.print_session is True
    assert args.status is True
    assert args.prompt == "hello"
    assert args.stream is True
    assert args.agent == "plan"
    assert args.skills is True
    assert args.skill == "openai-docs"


def test_cli_parser_accepts_agent_create_and_show():
    parser = build_parser()

    args: Namespace = parser.parse_args(["--agent-create", "TypeScript reviewer", "--agent-show", "build"])

    assert args.agent_create == "TypeScript reviewer"
    assert args.agent_show == "build"


def test_classify_repl_text_preserves_multiline_message():
    item = _classify_repl_text("第一行\n第二行\n")

    assert item == ("message", "第一行\n第二行\n")


def test_classify_repl_text_does_not_treat_multiline_paste_as_command():
    item = _classify_repl_text("/status\n这是我粘贴的正文\n")

    assert item == ("message", "/status\n这是我粘贴的正文\n")


def test_repl_reader_fallback_collects_multiline_until_end(monkeypatch):
    inputs = iter(["第一行", "第二行", "/end"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

    item = _read_repl_input()

    assert item == ("message", "第一行\n第二行")


def test_repl_reader_executes_command_only_when_buffer_empty(monkeypatch):
    item = _classify_repl_text("/help")

    assert item == ("command", "/help")


def test_repl_reader_cancel_discards_buffer(monkeypatch):
    inputs = iter(["第一行", "/cancel", "/status"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(inputs))

    item = _read_repl_input()

    assert item == ("command", "/status")


def test_repl_reader_treats_yolo_toggle_as_command(monkeypatch):
    item = _classify_repl_text("/yolo on")

    assert item == ("command", "/yolo on")


def test_repl_reader_treats_snapshot_commands_as_commands():
    assert _classify_repl_text("/snapshots") == ("command", "/snapshots")
    assert _classify_repl_text("/rollback last") == ("command", "/rollback last")


def test_repl_reader_treats_skill_commands_as_commands():
    assert _classify_repl_text("/skills") == ("command", "/skills")
    assert _classify_repl_text("/skill openai-docs") == ("command", "/skill openai-docs")


def test_classify_repl_text_treats_cancel_as_noop(capsys):
    item = _classify_repl_text("/cancel")

    assert item is None
    assert "[cancelled]" in capsys.readouterr().out


def test_stream_handler_renders_reasoning_then_text(capsys):
    handler, _state = _build_stream_handler()

    handler({"type": "reasoning-start", "id": "r1"})
    handler({"type": "reasoning-delta", "id": "r1", "text": "思考"})
    handler({"type": "reasoning-end", "id": "r1"})
    handler({"type": "text-start", "id": "t1"})
    handler({"type": "text-delta", "id": "t1", "text": "回答"})

    assert capsys.readouterr().out == "[thinking] 思考\n回答"
