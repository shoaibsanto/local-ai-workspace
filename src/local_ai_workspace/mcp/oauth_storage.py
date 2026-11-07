"""Native MCP OAuth token storage, bridging the MCP SDK's TokenStorage
protocol to our encrypted-on-disk secrets store.

The official MCP Python SDK (`mcp.client.auth`) implements the full OAuth
2.1 + Dynamic Client Registration flow for remote (SSE / streamable-http)
servers — PKCE, authorization redirect, token exchange, refresh. All we
need to supply is a `TokenStorage` implementation and a callback that opens
the browser / captures the redirect. This module is that storage adapter;
the redirect-capture lives in mcp/oauth_flow.py.

Isolation guarantee: every key written to the shared encrypted secrets blob
is namespaced with the MCP server's own `server_id` (`mcp_oauth_token::<id>`
/ `mcp_oauth_client::<id>`). There is no key derived from server name, URL,
or anything else that could collide across two different server configs,
and nothing here ever reads a key for a server_id other than the one this
instance was constructed with. See tests/test_mcp_oauth.py for a test that
proves tokens cannot leak across servers.

Expiry round-trip: `OAuthToken` (from the SDK) only carries a *relative*
`expires_in` (seconds), not an absolute timestamp -- so on its own it can't
tell us "is this expired *now*" after being read back from disk. We store a
thin wrapper around the token that also records `obtained_at` (wall-clock
time of the most recent `set_tokens` call), and use that to compute an
absolute expiry timestamp when needed. Older/foreign data written as a bare
OAuthToken JSON object (no wrapper) is handled as a legacy shape with an
unknown expiry (treated as "not expired" since we have no information to
say otherwise, and connect() will simply discover 401s the normal way).
"""

from __future__ import annotations

import json
import time
from typing import Any

from mcp.client.auth import TokenStorage
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from local_ai_workspace.storage.secrets import delete_secret, get_secret, set_secret


def compute_expiry(token: OAuthToken, obtained_at: float) -> float | None:
    """Absolute expiry timestamp for `token`, or None if it never expires
    (no `expires_in` on the token) or we can't compute one."""
    if token.expires_in is None:
        return None
    try:
        return obtained_at + float(token.expires_in)
    except (TypeError, ValueError):
        return None


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
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if isinstance(data, dict) and "token" in data and "obtained_at" in data:
            try:
                return OAuthToken(**data["token"])
            except (ValueError, TypeError):
                return None
        # Legacy shape: a bare OAuthToken dict with no obtained_at wrapper.
        try:
            return OAuthToken(**data)
        except (ValueError, TypeError):
            return None

    async def get_obtained_at(self) -> float | None:
        raw = get_secret(self._token_key())
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if isinstance(data, dict) and "obtained_at" in data:
            try:
                return float(data["obtained_at"])
            except (TypeError, ValueError):
                return None
        return None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        wrapper: dict[str, Any] = {
            "token": json.loads(tokens.model_dump_json()),
            "obtained_at": time.time(),
        }
        set_secret(self._token_key(), json.dumps(wrapper))

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

    async def is_expired(self) -> bool:
        """True if a stored token exists and has a known, past expiry.

        A token with no stored expiry info (legacy shape, or a provider
        that issued a token with no `expires_in`) is treated as *not*
        expired -- we have no evidence it's bad, and the normal HTTP 401
        path will catch a genuinely-expired token on the next request.
        """
        token = await self.get_tokens()
        if token is None:
            return False
        obtained_at = await self.get_obtained_at()
        if obtained_at is None:
            return False
        expiry = compute_expiry(token, obtained_at)
        if expiry is None:
            return False
        return time.time() >= expiry

    def clear(self) -> None:
        """Delete both the token and client-registration secrets for this
        server from the encrypted store. Used by revoke/reauthorize --
        actually removes the secret via storage/secrets.py's delete_secret,
        not just a status flag."""
        delete_secret(self._token_key())
        delete_secret(self._client_info_key())
