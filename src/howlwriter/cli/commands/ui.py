"""`howlwriter ui` -- starts the local HowlWriter web application."""

from __future__ import annotations

import argparse
import sys
import threading
import time
import webbrowser

from howlwriter.web.app import create_app


def add_subparser(
    subparsers: argparse._SubParsersAction,
) -> argparse.ArgumentParser:
    parser = subparsers.add_parser(
        "ui",
        help="Start the local HowlWriter web application interface.",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Local network interface to bind to (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8765,
        help="Port to listen on (default: 8765).",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open browser automatically on launch.",
    )
    parser.add_argument(
        "--config",
        dest="project_config_path",
        default=None,
        help="Path to project configuration YAML/TOML.",
    )
    parser.set_defaults(handler=run)
    return parser


def run(args: argparse.Namespace) -> int:
    try:
        import uvicorn
    except ImportError:
        print(
            "error: uvicorn is required to run the local web UI. "
            "Please install it with: pip install 'uvicorn[standard]' or 'fastapi[standard]'",
            file=sys.stderr,
        )
        return 1

    host = args.host
    port = args.port
    url = f"http://{host}:{port}"

    print("Starting HowlWriter local web application...")
    print(f"URL: {url}")
    print("Press Ctrl+C to stop.")

    if not args.no_browser:
        def _open():
            time.sleep(0.8)
            try:
                webbrowser.open(url)
            except Exception:
                pass

        t = threading.Thread(target=_open, daemon=True)
        t.start()

    fastapi_app = create_app()
    uvicorn.run(
        fastapi_app,
        host=host,
        port=port,
        log_level="info",
    )
    return 0
