"""CLI entry point: `local-ai serve`, `local-ai open`, etc.

Kept deliberately small (argparse, no extra CLI framework dependency) since
the whole point of this app is to minimize what gets installed.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import webbrowser

import uvicorn

from local_ai_workspace.core.logging_setup import configure_logging
from local_ai_workspace.storage.paths import get_configured_data_root, get_data_root, set_configured_data_root


def cmd_serve(args: argparse.Namespace) -> None:
    configure_logging(level=args.log_level)

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


def cmd_config(args: argparse.Namespace) -> None:
    if args.config_action == "get":
        if args.key != "data_root":
            print(f"Unknown config key: {args.key}", file=sys.stderr)
            sys.exit(1)
        value = get_configured_data_root()
        print(value if value is not None else "(not set, using platform default)")
    elif args.config_action == "set":
        if args.key != "data_root":
            print(f"Unknown config key: {args.key}", file=sys.stderr)
            sys.exit(1)
        set_configured_data_root(args.value)
        print(f"Set data_root = {args.value}")
    elif args.config_action == "unset":
        if args.key != "data_root":
            print(f"Unknown config key: {args.key}", file=sys.stderr)
            sys.exit(1)
        set_configured_data_root(None)
        print("Cleared data_root override (back to platform default / env var)")
    else:
        print("Usage: local-ai config <get|set|unset> data_root [value]", file=sys.stderr)
        sys.exit(1)


def cmd_backup(args: argparse.Namespace) -> None:
    from local_ai_workspace.storage.backup import create_backup

    path = create_backup()
    print(f"Backup created: {path}")


def cmd_restore(args: argparse.Namespace) -> None:
    from local_ai_workspace.storage.backup import restore_backup

    try:
        restored = restore_backup(args.path)
    except (FileNotFoundError, ValueError) as e:
        print(f"Restore failed: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Restored {restored} files from {args.path}")


def cmd_export(args: argparse.Namespace) -> None:
    from local_ai_workspace.storage.conversation_store import export_conversation

    data = export_conversation(args.conversation_id)
    if data is None:
        print(f"Conversation not found: {args.conversation_id}", file=sys.stderr)
        sys.exit(1)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"Exported conversation {args.conversation_id} -> {args.output}")


def cmd_wipe(args: argparse.Namespace) -> None:
    if not args.confirm:
        print(
            "Refusing to wipe all data without --confirm. "
            "Re-run as: local-ai wipe --confirm",
            file=sys.stderr,
        )
        sys.exit(1)

    import shutil

    from local_ai_workspace.storage import keyring_backend
    from local_ai_workspace.storage.paths import (
        conversations_dir,
        mcp_servers_path,
        projects_dir,
        providers_path,
        secret_key_path,
        secrets_path,
    )

    if conversations_dir().exists():
        shutil.rmtree(conversations_dir())
        conversations_dir()
    if projects_dir().exists():
        shutil.rmtree(projects_dir())
        projects_dir()
    if providers_path().exists():
        providers_path().unlink()
    if mcp_servers_path().exists():
        mcp_servers_path().unlink()
    if secrets_path().exists():
        secrets_path().unlink()
    if secret_key_path().exists():
        secret_key_path().unlink()
    try:
        keyring_backend.delete_key()
    except Exception:  # noqa: BLE001 - best-effort cleanup only
        pass

    print("All data wiped: conversations, projects, providers, MCP servers, secrets.")


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

    config_p = sub.add_parser("config", help="Get/set persistent app configuration")
    config_p.add_argument("config_action", choices=["get", "set", "unset"])
    config_p.add_argument("key", help="Config key, e.g. 'data_root'")
    config_p.add_argument("value", nargs="?", help="New value (for 'set')")
    config_p.set_defaults(func=cmd_config)

    backup_p = sub.add_parser("backup", help="Create a full backup of the data directory")
    backup_p.set_defaults(func=cmd_backup)

    restore_p = sub.add_parser("restore", help="Restore the data directory from a backup zip")
    restore_p.add_argument("path", help="Path to the backup zip file")
    restore_p.set_defaults(func=cmd_restore)

    export_p = sub.add_parser("export", help="Export a conversation to a JSON file")
    export_p.add_argument("conversation_id", help="Conversation id to export")
    export_p.add_argument("output", help="Output JSON file path")
    export_p.set_defaults(func=cmd_export)

    wipe_p = sub.add_parser("wipe", help="Delete ALL app data (conversations, providers, MCP servers, secrets)")
    wipe_p.add_argument(
        "--confirm", action="store_true", help="Required flag to actually perform the wipe"
    )
    wipe_p.set_defaults(func=cmd_wipe)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    app()
