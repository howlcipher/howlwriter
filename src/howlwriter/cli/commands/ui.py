"""`howlwriter ui` -- starts the local HowlWriter web application."""

from __future__ import annotations

import argparse
import sys
import threading
import time
import webbrowser


_LOOPBACK_HOSTS = ("127.0.0.1", "localhost", "::1")


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
        help="Interface to bind to (default: 127.0.0.1). Non-loopback hosts need --allow-network-access.",
    )
    parser.add_argument(
        "--allow-network-access",
        action="store_true",
        help="Allow binding a non-loopback host. The API has no login: anyone who can reach it can "
        "read and write the owner's text files and use their model access.",
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
    from howlwriter.integration import provider_choice

    # The server never waits on its terminal: the page asks which model to use.
    provider_choice.PROCESS_DEFAULTS["interactive"] = False
    # fastapi/uvicorn are the "web" extra, not a core dependency -- every
    # other howlwriter subcommand (including --version/--help) must keep
    # working with just the core install, so these imports stay deferred
    # to here rather than at module load time.
    try:
        import uvicorn
    except ImportError:
        print(
            "error: uvicorn is required to run the local web UI. "
            "Please install it with: pip install 'uvicorn[standard]' or 'fastapi[standard]'",
            file=sys.stderr,
        )
        return 1
    try:
        from howlwriter.web.app import create_app
    except ImportError:
        print(
            "error: fastapi is required to run the local web UI. "
            "Please install it with: pip install 'howlwriter[web]'",
            file=sys.stderr,
        )
        return 1

    host = args.host
    port = args.port
    network = host not in _LOOPBACK_HOSTS
    if network and not args.allow_network_access:
        print(
            f"error: refusing to bind {host!r}: the web UI has no login, so anything that can reach it "
            "could read and write your files. Use 127.0.0.1, or pass --allow-network-access if you "
            "understand that.",
            file=sys.stderr,
        )
        return 1
    if network:
        print(
            f"WARNING: --allow-network-access: the web API is unauthenticated, and Host header checks are "
            f"relaxed in this mode. Every machine that can reach {host} can read and write your text "
            "files and use your model access.",
            file=sys.stderr,
        )
    shown = f"[{host}]" if ":" in host and not host.startswith("[") else host
    url = f"http://{shown}:{port}"

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

    # Off loopback the Host header is whatever address the visitor typed, so the host check cannot
    # name it; the owner has accepted that with --allow-network-access.
    fastapi_app = create_app(
        port=port, host=host, allowed_hosts=("*",) if network else ("127.0.0.1", "localhost")
    )
    uvicorn.run(
        fastapi_app,
        host=host,
        port=port,
        log_level="info",
    )
    return 0
