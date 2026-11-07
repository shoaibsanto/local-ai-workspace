"""Native MCP OAuth token storage, bridging the MCP SDK's TokenStorage
protocol to our encrypted-on-disk secrets store.

The official MCP Python SDK (`mcp.client.auth`) implements the full OAuth
2.1 + Dynamic Client Registration flow for remote (SSE / streamable-http)
servers — PKCE, authorization redirect, token exchange, refresh. All we
need to supply is a `TokenStorage` implementation and a callback that opens
the browser / captures the redirect. This module is that storage adapter;
the redirect-capture lives in mcp/oauth_flow.py.
"""
from __future__ import annotations

import json

from mcp.client.auth import TokenStorage
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from local_ai_workspace.storage.secrets import get_secret, set_secret


class EncryptedFileTokenStorage(TokenStorage):
    """One instance per MCP server. Keys are namespaced by server_id so
    multiple OAuth-protected MCP servers don't collide in the secrets
    store."""

    def __init__(self, server_id: str):
        self.server_id = server_id

    def _token_key(self) -> str:
        return f"mcp_oauth_token::{self.server_id}"

    def _client_info_key(self) -> str:
        return f"mcp_oauth_client::{self.server_id}"

    async def get_tokens(self) -> OAuthToken | None:
        raw = get_secret(self._token_key())
        if not raw:
            return None
        try:
            return OAuthToken(**json.loads(raw))
        except (json.JSONDecodeError, ValueError):
            return None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        set_secret(self._token_key(), tokens.model_dump_json())

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        raw = get_secret(self._client_info_key())
        if not raw:
            return None
        try:
            return OAuthClientInformationFull(**json.loads(raw))
        except (json.JSONDecodeError, ValueError):
            return None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        set_secret(self._client_info_key(), client_info.model_dump_json())
