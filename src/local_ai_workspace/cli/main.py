"""CLI entry point: `local-ai serve`, `local-ai open`, etc.

Kept deliberately small (argparse, no extra CLI framework dependency) since
the whole point of this app is to minimize what gets installed.
"""
from __future__ import annotations

import argparse
import sys
import threading
import time
import webbrowser

import uvicorn

from local_ai_workspace.storage.paths import get_data_root


def cmd_serve(args: argparse.Namespace) -> None:
    from local_ai_workspace.api.app import create_app

    app = create_app()

    if not args.no_browser:

        def _open_browser():
            time.sleep(1.2)
            webbrowser.open(f"http://{args.host}:{args.port}")

        threading.Thread(target=_open_browser, daemon=True).start()

    print(f"Local AI Workspace running at http://{args.host}:{args.port}")
    print(f"Data directory: {get_data_root()}")
    uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)


def cmd_data_dir(args: argparse.Namespace) -> None:
    print(get_data_root())


def app() -> None:
    parser = argparse.ArgumentParser(prog="local-ai", description="Local-first AI workspace")
    sub = parser.add_subparsers(dest="command", required=True)

    serve_p = sub.add_parser("serve", help="Start the local server and open the UI")
    serve_p.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1, local-only)")
    serve_p.add_argument("--port", type=int, default=8420, help="Bind port (default: 8420)")
    serve_p.add_argument("--no-browser", action="store_true", help="Don't auto-open a browser tab")
    serve_p.add_argument("--log-level", default="info")
    serve_p.set_defaults(func=cmd_serve)

    data_p = sub.add_parser("data-dir", help="Print the data directory path")
    data_p.set_defaults(func=cmd_data_dir)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    app()
