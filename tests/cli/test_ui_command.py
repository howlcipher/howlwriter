"""Tests for howlwriter ui CLI command parsing."""

from howlwriter.cli.main import build_parser


def test_ui_parser_defaults():
    parser = build_parser()
    args = parser.parse_args(["ui"])
    assert args.command == "ui"
    assert args.host == "127.0.0.1"
    assert args.port == 8765
    assert args.no_browser is False


def test_ui_parser_custom_args():
    parser = build_parser()
    args = parser.parse_args(["ui", "--host", "127.0.0.1", "--port", "9000", "--no-browser"])
    assert args.command == "ui"
    assert args.host == "127.0.0.1"
    assert args.port == 9000
    assert args.no_browser is True
