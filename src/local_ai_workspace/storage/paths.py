"""Filesystem layout and path helpers.

Everything the app persists lives under a single root directory, resolved via
platformdirs so it's correct on Windows/macOS/Linux without any hardcoded
paths. No database — conversations, settings, and MCP config are plain JSON /
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
"""
from __future__ import annotations

import os
from pathlib import Path

from platformdirs import user_data_dir

APP_NAME = "local-ai-workspace"


def get_data_root() -> Path:
    """Return the root data directory, creating it if needed.

    Honors LOCAL_AI_WORKSPACE_HOME env var for overriding (tests, portable
    installs, multiple profiles).
    """
    override = os.environ.get("LOCAL_AI_WORKSPACE_HOME")
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
