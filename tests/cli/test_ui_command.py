"""Tests for howlwriter ui CLI command parsing."""

import builtins

from howlwriter.cli.commands import ui as ui_module
from howlwriter.cli.main import build_parser, main


def test_ui_without_fastapi_extra_reports_actionable_error_not_a_traceback(capsys, monkeypatch):
    """fastapi/uvicorn are the optional "web" extra: every other subcommand
    (including --version, exercised elsewhere) must keep working without
    it, and `ui` itself must degrade to a clean message, not crash."""
    real_import = builtins.__import__

    def blocked(name, *args, **kwargs):
        if name in ("uvicorn", "howlwriter.web.app"):
            raise ImportError(f"no {name}")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)

    exit_code = main(["ui", "--no-browser"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "error:" in captured.err
    assert "howlwriter[web]" in captured.err or "uvicorn" in captured.err
    assert "Traceback" not in captured.err


def test_ui_command_module_has_no_top_level_fastapi_import():
    """The module itself must not eagerly import howlwriter.web.app --
    that would require fastapi just to import the CLI's command tree,
    breaking --version and every other subcommand on a core-only install.
    A module-level `from howlwriter.web.app import create_app` would bind
    create_app as an attribute of this module; a deferred, in-function
    import does not."""
    assert not hasattr(ui_module, "create_app")


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
