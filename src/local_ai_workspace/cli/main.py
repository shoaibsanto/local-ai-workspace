"""CLI entry point: `local-ai serve`, `local-ai open`, etc.

Kept deliberately small (argparse, no extra CLI framework dependency) since
the whole point of this app is to minimize what gets installed.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import socket
import sys
import threading
import time
import webbrowser
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

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
            "Refusing to wipe all data without --confirm. Re-run as: local-ai wipe --confirm",
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
    with contextlib.suppress(Exception):  # best-effort cleanup only
        keyring_backend.delete_key()

    print("All data wiped: conversations, projects, providers, MCP servers, secrets.")


def _get_version() -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("local-ai-workspace")
    except PackageNotFoundError:
        return "0.0.0+unknown"


class CheckStatus(Enum):
    """Severity of a single `local-ai doctor` check."""

    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"


@dataclass
class CheckResult:
    name: str
    status: CheckStatus
    detail: str


_MIN_PYTHON = (3, 11)


def _check_python_version() -> CheckResult:
    actual = sys.version_info[:2]
    if actual >= _MIN_PYTHON:
        return CheckResult(
            "Python version",
            CheckStatus.PASS,
            f"{sys.version.split()[0]} (>= {'.'.join(map(str, _MIN_PYTHON))} required)",
        )
    return CheckResult(
        "Python version",
        CheckStatus.FAIL,
        f"{sys.version.split()[0]} is below the minimum supported {'.'.join(map(str, _MIN_PYTHON))}",
    )


def _check_data_dir() -> CheckResult:
    try:
        root = get_data_root()
    except OSError as e:
        return CheckResult("Data directory", CheckStatus.FAIL, f"could not resolve/create data root: {e}")

    if not root.exists():
        return CheckResult("Data directory", CheckStatus.FAIL, f"{root} does not exist")

    probe = root / ".doctor_write_check"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as e:
        return CheckResult("Data directory", CheckStatus.FAIL, f"{root} exists but is not writable: {e}")

    return CheckResult("Data directory", CheckStatus.PASS, f"{root} exists and is writable")


def _check_frontend_static() -> CheckResult:
    static_dir = Path(__file__).resolve().parent.parent / "static"
    if not static_dir.exists():
        return CheckResult(
            "Frontend static assets",
            CheckStatus.WARN,
            f"{static_dir} is missing — this is expected for an editable/dev install "
            "before the frontend has been built (see frontend/README.md); "
            "`local-ai serve` will run API-only without a bundled UI",
        )
    if not any(static_dir.iterdir()):
        return CheckResult("Frontend static assets", CheckStatus.WARN, f"{static_dir} exists but is empty")
    return CheckResult("Frontend static assets", CheckStatus.PASS, f"{static_dir} present")


def _check_port_free(host: str, port: int) -> CheckResult:
    """Best-effort check: a bind-and-close probe. Inherently racy (TOCTOU)
    against whatever actually calls `uvicorn.run` later, so this is reported
    as a WARN rather than FAIL on conflict — it's informational, not a hard
    gate, since the real bind attempt at `serve` time is authoritative."""
    with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError as e:
            return CheckResult(
                f"Port {port} availability",
                CheckStatus.WARN,
                f"{host}:{port} appears to be in use ({e}); `local-ai serve --port <other>` to pick a different one",
            )
    return CheckResult(f"Port {port} availability", CheckStatus.PASS, f"{host}:{port} is free")


def _check_secrets_master_key() -> CheckResult:
    try:
        from local_ai_workspace.storage.secrets import _get_or_create_key

        key = _get_or_create_key()
    except Exception as e:  # noqa: BLE001 - doctor must never crash on a broken key backend
        return CheckResult("Secrets master key", CheckStatus.FAIL, f"could not load/create master key: {e}")

    if not key:
        return CheckResult("Secrets master key", CheckStatus.FAIL, "master key resolved to an empty value")

    from local_ai_workspace.storage import keyring_backend

    backend = keyring_backend.backend_description() if keyring_backend.is_keyring_available() else "file-based"
    return CheckResult("Secrets master key", CheckStatus.PASS, f"loadable via {backend}")


def cmd_doctor(args: argparse.Namespace) -> None:
    checks = [
        _check_python_version(),
        _check_data_dir(),
        _check_frontend_static(),
        _check_port_free(args.host, args.port),
        _check_secrets_master_key(),
    ]

    print("local-ai doctor")
    print("=" * 60)
    worst = CheckStatus.PASS
    for result in checks:
        print(f"[{result.status.value:4}] {result.name}: {result.detail}")
        if result.status == CheckStatus.FAIL:
            worst = CheckStatus.FAIL
        elif result.status == CheckStatus.WARN and worst != CheckStatus.FAIL:
            worst = CheckStatus.WARN
    print("=" * 60)

    if worst == CheckStatus.FAIL:
        print("Result: FAIL — one or more checks failed, see above.")
        sys.exit(1)
    elif worst == CheckStatus.WARN:
        print("Result: PASS with warnings.")
        sys.exit(0)
    else:
        print("Result: PASS — all checks OK.")
        sys.exit(0)


def app() -> None:
    parser = argparse.ArgumentParser(prog="local-ai", description="Local-first AI workspace")
    parser.add_argument(
        "--version",
        action="version",
        version=f"local-ai-workspace {_get_version()}",
    )
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
    wipe_p.add_argument("--confirm", action="store_true", help="Required flag to actually perform the wipe")
    wipe_p.set_defaults(func=cmd_wipe)

    doctor_p = sub.add_parser("doctor", help="Diagnose environment/config issues (data dir, port, secrets, frontend)")
    doctor_p.add_argument("--host", default="127.0.0.1", help="Host to probe for port availability")
    doctor_p.add_argument("--port", type=int, default=8420, help="Port to probe for availability")
    doctor_p.set_defaults(func=cmd_doctor)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    app()
