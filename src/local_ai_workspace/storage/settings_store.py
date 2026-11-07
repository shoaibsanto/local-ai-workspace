"""Global app settings persistence (non-secret), following the same
pattern as provider_store.py / mcp_store.py.

Holds things that aren't tied to a single provider or MCP server:
- the global ApprovalPolicy (core/approval.py), overridable per MCP server
- context-compaction tuning (core/compaction.py): threshold + retained
  recent-message count

Stored as one JSON document at storage/paths.py's settings_path().
"""
from __future__ import annotations

from pydantic import BaseModel, Field

from local_ai_workspace.core.approval import ApprovalPolicy
from local_ai_workspace.storage.json_store import read_json, write_json_atomic
from local_ai_workspace.storage.paths import settings_path

DEFAULT_COMPACTION_THRESHOLD = 0.75
DEFAULT_COMPACTION_RECENT_MESSAGES = 10


class AppSettings(BaseModel):
    approval_policy: ApprovalPolicy = Field(default_factory=ApprovalPolicy)
    # Per-MCP-server approval policy overrides, keyed by server id. A server
    # with no entry here uses the global approval_policy.
    mcp_server_approval_overrides: dict[str, ApprovalPolicy] = Field(default_factory=dict)
    compaction_threshold: float = DEFAULT_COMPACTION_THRESHOLD
    compaction_recent_messages: int = DEFAULT_COMPACTION_RECENT_MESSAGES


def get_settings() -> AppSettings:
    data = read_json(settings_path(), default=None)
    if data is None:
        return AppSettings()
    try:
        return AppSettings(**data)
    except (TypeError, ValueError):
        return AppSettings()


def save_settings(settings: AppSettings) -> AppSettings:
    write_json_atomic(settings_path(), settings.model_dump())
    return settings


def get_approval_policy() -> ApprovalPolicy:
    return get_settings().approval_policy


def save_approval_policy(policy: ApprovalPolicy) -> ApprovalPolicy:
    settings = get_settings()
    settings = settings.model_copy(update={"approval_policy": policy})
    save_settings(settings)
    return policy


def get_effective_policy_for_server(server_id: str | None) -> ApprovalPolicy:
    """The policy that applies to a given MCP server: its per-server
    override if one exists, else the global policy."""
    settings = get_settings()
    if server_id and server_id in settings.mcp_server_approval_overrides:
        return settings.mcp_server_approval_overrides[server_id]
    return settings.approval_policy
