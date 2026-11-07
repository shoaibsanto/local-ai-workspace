"""Filesystem layout and path helpers.

Everything the app persists lives under a single root directory. Resolution
order for the data root is:

    1. LOCAL_AI_WORKSPACE_HOME env var (highest priority; tests, portable
       installs, multiple profiles).
    2. A user-overridable pointer stored in a small fixed-location config
       file (`global_config_path()`, outside the data root itself — it has
       to live somewhere stable since it's what tells us *where* the data
       root is). Set/read via `get_configured_data_root()` /
       `set_configured_data_root()`, exposed through `local-ai config`.
    3. The platformdirs default user data directory.

No database — conversations, settings, and MCP config are plain JSON /
JSONL / Markdown files on disk.

Layout (under the data root):
    settings.json              global app settings (non-secret)
    secrets.enc                encrypted blob: API keys, OAuth tokens
    providers.json             configured LLM providers (non-secret fields)
    mcp_servers.json           configured MCP servers (non-secret fields)
    conversations/
        <conversation_id>/
            meta.json           title, model, created_at, updated_at, pinned
            messages.jsonl      one JSON object per line, append-only
    projects/
        <project_id>/
            meta.json
            conversations/      conversation ids belonging to this project
    backups/
        <timestamp>.zip         full data-dir snapshots created by `local-ai backup`
    logs/
        application.log         rotating application log
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from platformdirs import user_config_dir, user_data_dir

APP_NAME = "local-ai-workspace"


def global_config_path() -> Path:
    """Fixed-location config file (independent of the data root) that may
    point at a user-chosen data root. Lives in the OS user-config directory
    so it's discoverable even before we know where the data root is."""
    d = Path(user_config_dir(APP_NAME, appauthor=False))
    d.mkdir(parents=True, exist_ok=True)
    return d / "settings.json"


def get_configured_data_root() -> str | None:
    """Read the user-configured data root override, if any, from the fixed
    global config file. Returns None if not set or unreadable."""
    path = global_config_path()
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        value = data.get("data_root")
        return str(value) if value else None
    except (json.JSONDecodeError, OSError):
        return None


def set_configured_data_root(path: str | None) -> None:
    """Persist (or clear, if path is None) the user-configured data root
    override in the fixed global config file."""
    config_path = global_config_path()
    data: dict = {}
    if config_path.exists():
        try:
            with open(config_path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            data = {}
    if path is None:
        data.pop("data_root", None)
    else:
        data["data_root"] = str(path)
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_data_root() -> Path:
    """Return the root data directory, creating it if needed.

    Resolution order: LOCAL_AI_WORKSPACE_HOME env var, then the
    user-configured override (`local-ai config set data_root ...`), then the
    platformdirs default.
    """
    override = os.environ.get("LOCAL_AI_WORKSPACE_HOME")
    if not override:
        override = get_configured_data_root()
    root = Path(override) if override else Path(user_data_dir(APP_NAME, appauthor=False))
    root.mkdir(parents=True, exist_ok=True)
    return root


def conversations_dir() -> Path:
    d = get_data_root() / "conversations"
    d.mkdir(parents=True, exist_ok=True)
    return d


def projects_dir() -> Path:
    d = get_data_root() / "projects"
    d.mkdir(parents=True, exist_ok=True)
    return d


def conversation_dir(conversation_id: str) -> Path:
    d = conversations_dir() / conversation_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def settings_path() -> Path:
    return get_data_root() / "settings.json"


def secrets_path() -> Path:
    return get_data_root() / "secrets.enc"


def secret_key_path() -> Path:
    return get_data_root() / ".secret_key"


def providers_path() -> Path:
    return get_data_root() / "providers.json"


def mcp_servers_path() -> Path:
    return get_data_root() / "mcp_servers.json"


def backups_dir() -> Path:
    d = get_data_root() / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def logs_dir() -> Path:
    d = get_data_root() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d
