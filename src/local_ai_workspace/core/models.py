"""Pydantic data models shared across the app."""
from __future__ import annotations

import time
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field


def new_id(prefix: str = "") -> str:
    return f"{prefix}{uuid.uuid4().hex[:20]}"


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    tool_call_id: str
    name: str
    content: str
    is_error: bool = False


class Message(BaseModel):
    id: str = Field(default_factory=lambda: new_id("msg_"))
    role: Literal["user", "assistant", "system", "tool"]
    content: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)
    created_at: float = Field(default_factory=time.time)
    model: str | None = None
    provider: str | None = None
    error: str | None = None


class ConversationMeta(BaseModel):
    id: str = Field(default_factory=lambda: new_id("conv_"))
    title: str = "New Conversation"
    project_id: str | None = None
    model: str | None = None
    provider: str | None = None
    created_at: float = Field(default_factory=time.time)
    updated_at: float = Field(default_factory=time.time)
    pinned: bool = False
    message_count: int = 0


class ProjectMeta(BaseModel):
    id: str = Field(default_factory=lambda: new_id("proj_"))
    name: str = "New Project"
    description: str = ""
    created_at: float = Field(default_factory=time.time)
    system_prompt: str | None = None


class ProviderConfig(BaseModel):
    """A configured LLM provider. api_key_ref points into the secrets store,
    never the raw key itself (so this model is safe to serialize to disk
    unencrypted and to return from the API)."""

    id: str = Field(default_factory=lambda: new_id("prov_"))
    name: str
    base_url: str
    api_key_ref: str | None = None  # key name in the encrypted secrets store
    default_model: str | None = None
    models: list[str] = Field(default_factory=list)
    kind: Literal["openai_compatible", "anthropic", "gemini"] = "openai_compatible"
    enabled: bool = True

    # --- extended provider metadata ---
    organization_id: str | None = None  # e.g. OpenAI org/project header
    custom_headers: dict[str, str] = Field(default_factory=dict)
    timeout_seconds: float = 60.0
    # Known/detected feature support for this provider+model combo. Keys left
    # unset mean "unknown", not "false" -- see providers/capabilities.py and
    # core/chat.py for how callers are expected to treat that distinction.
    capabilities: dict[str, bool] = Field(
        default_factory=lambda: {
            "streaming": False,
            "tool_calling": False,
            "vision": False,
            "structured_output": False,
        }
    )
    context_window: int | None = None
    # Whether this provider is allowed to target localhost/private network
    # addresses (SSRF guard). Defaults to False; local providers like Ollama
    # must opt in explicitly. Shared with the SSRF-hardening work elsewhere
    # in the codebase -- reused here, not redefined.
    allow_local: bool = False


class MCPServerConfig(BaseModel):
    id: str = Field(default_factory=lambda: new_id("mcp_"))
    name: str
    transport: Literal["stdio", "sse", "streamable_http"] = "stdio"
    command: str | None = None  # for stdio
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    url: str | None = None  # for sse / streamable_http
    requires_oauth: bool = False
    oauth_token_ref: str | None = None  # key name in secrets store
    enabled: bool = True
    status: Literal["disconnected", "connecting", "connected", "error", "needs_auth"] = (
        "disconnected"
    )
    last_error: str | None = None
    tool_count: int = 0
    allow_local: bool = False  # opt-in: skip SSRF guard for local MCP endpoints
    # Server-local tool names (NOT qualified with "servername__") that the
    # user has disabled. MCPManager.get_tools_openai_format skips these.
    disabled_tools: list[str] = Field(default_factory=list)
