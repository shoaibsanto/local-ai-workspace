"""Fail-fast startup validation: run before the server starts accepting
traffic so a misconfigured environment produces one clear, actionable error
message instead of starting in a half-broken state (or crashing later, mid
request, with a raw stack trace).

Three checks, matching the three ways this app can be unable to actually
serve a request even though `uvicorn.run()` would happily bind and go:

1. Data directory not writable (permissions, read-only filesystem, disk
   full) -- every single request touches the filesystem (no in-memory
   fallback), so this is fatal, not degraded-mode.
2. Secrets master key not loadable -- without it, every provider API key /
   MCP OAuth token lookup fails; better to refuse to start than silently
   serve a broken "every provider looks unauthenticated" experience.
3. Configured port already in use -- uvicorn's own error for this is a raw
   OSError traceback; a one-line "port 8420 is already in use, pick
   another with --port" is much more actionable for a local desktop app
   the user is starting from a terminal.
"""

from __future__ import annotations

import socket


class StartupCheckError(Exception):
    """Raised with a human-actionable message; cli/main.py catches this and
    prints it cleanly (no traceback) before exiting non-zero."""


def check_data_dir_writable() -> None:
    from local_ai_workspace.storage.paths import get_data_root

    try:
        data_root = get_data_root()
    except OSError as e:
        raise StartupCheckError(
            f"Could not create or access the data directory: {e}\n"
            "Check LOCAL_AI_WORKSPACE_HOME (if set) or your platform's default "
            "user data directory, and that this user has permission to write there."
        ) from e

    probe = data_root / ".startup_write_check"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as e:
        raise StartupCheckError(
            f"Data directory is not writable: {data_root} ({e})\n"
            "Fix the directory's permissions, free up disk space if it's full, "
            "or point LOCAL_AI_WORKSPACE_HOME at a writable location."
        ) from e


def check_secrets_key_loadable() -> None:
    from local_ai_workspace.storage.secrets import _get_or_create_key

    try:
        key = _get_or_create_key()
    except Exception as e:  # noqa: BLE001 - any failure here is fatal and must be explained
        raise StartupCheckError(
            f"Could not load or create the secrets master key: {e}\n"
            "This usually means the OS keyring is in a broken state or the "
            "data directory's .secret_key file is corrupted/unreadable. Check "
            "file permissions, or run `local-ai wipe --confirm` to reset all "
            "stored secrets if you're OK losing saved API keys."
        ) from e
    if not key:
        raise StartupCheckError(
            "Secrets master key loaded but was empty -- refusing to start with a broken secrets store."
        )


def check_port_available(host: str, port: int) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
    except OSError as e:
        raise StartupCheckError(
            f"Port {port} on {host} is already in use ({e}).\n"
            f"Another instance may already be running, or another program is "
            f"using that port. Stop it, or start this one on a different port: "
            f"`local-ai serve --port <other-port>`."
        ) from e
    finally:
        sock.close()


def run_all_startup_checks(host: str, port: int) -> None:
    """Run every startup check, in order, raising StartupCheckError with the
    first failure's actionable message. Called by cli/main.py before
    uvicorn.run() -- never by the FastAPI app itself, since by the time
    FastAPI/uvicorn is involved the port is already claimed by us."""
    check_data_dir_writable()
    check_secrets_key_loadable()
    check_port_available(host, port)
