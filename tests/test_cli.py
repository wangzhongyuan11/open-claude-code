from argparse import Namespace

from openagent.cli.main import build_parser


def test_cli_parser_accepts_prompt_and_print_session():
    parser = build_parser()

    args: Namespace = parser.parse_args(["--workspace", ".", "--print-session", "--prompt", "hello"])

    assert args.workspace == "."
    assert args.print_session is True
    assert args.prompt == "hello"
