"""MCP server connection manager.

Owns one live `ClientSession` per connected MCP server, discovers its tools
on connect, converts MCP tool schemas to OpenAI-style function-calling
schemas (the common denominator our provider clients speak), and executes
tool calls by name. For OAuth-protected remote servers it drives the MCP
SDK's OAuth flow using the loopback callback server + encrypted token
storage from this package.

This is process-lifetime state (live connections), not disk state — if the
app restarts, servers are reconnected on startup via `connect_all_enabled`.
"""

from __future__ import annotations

import contextlib
import logging
from contextlib import AsyncExitStack
from typing import Any

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.auth import OAuthClientProvider
from mcp.client.auth.utils import (
    build_oauth_authorization_server_metadata_discovery_urls,
    build_protected_resource_metadata_discovery_urls,
)
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client as streamablehttp_client
from mcp.shared.auth import OAuthClientMetadata, OAuthMetadata, ProtectedResourceMetadata

from local_ai_workspace.core.models import MCPServerConfig
from local_ai_workspace.core.ssrf_guard import validate_outbound_url
from local_ai_workspace.mcp.oauth_flow import OAuthCallbackServer
from local_ai_workspace.mcp.oauth_storage import EncryptedFileTokenStorage
from local_ai_workspace.storage.mcp_store import get_mcp_server, list_mcp_servers, save_mcp_server

logger = logging.getLogger(__name__)


class OAuthDiscoveryError(Exception):
    """Raised when OAuth requirement discovery genuinely fails (network
    error, malformed metadata, etc.) as opposed to cleanly determining "no
    OAuth protection here" (a 404 on the protected-resource well-known
    path). Callers should fall back to asking the user to manually specify
    OAuth only when this is raised -- a clean negative result is not an
    error."""


async def discover_oauth_requirement(url: str, allow_loopback: bool = False) -> bool:
    """Per the MCP authorization spec: look for OAuth 2.0 Protected
    Resource Metadata (RFC 9728) at the server's well-known
    oauth-protected-resource path(s); if found, follow its
    `authorization_servers[0]` to that AS's OAuth 2.0 Authorization Server
    Metadata (RFC 8414) well-known path(s).

    Returns True if both documents were found and valid (the server
    requires OAuth), False if no Protected Resource Metadata document
    exists anywhere (the server does not require OAuth -- not an error).
    Raises OAuthDiscoveryError for anything else: network failures,
    malformed metadata, or a PRM that points at an AS with no discoverable
    metadata at all.
    """
    validate_outbound_url(url, allow_loopback=allow_loopback)

    prm: ProtectedResourceMetadata | None = None
    async with httpx.AsyncClient(timeout=10) as client:
        for prm_url in build_protected_resource_metadata_discovery_urls(None, url):
            try:
                resp = await client.get(prm_url)
            except httpx.HTTPError as e:
                raise OAuthDiscoveryError(
                    f"Network error discovering protected resource metadata at {prm_url}: {e}"
                ) from e
            if resp.status_code == 200:
                try:
                    prm = ProtectedResourceMetadata.model_validate_json(resp.content)
                except Exception as e:  # noqa: BLE001
                    raise OAuthDiscoveryError(f"Invalid protected resource metadata at {prm_url}: {e}") from e
                break
            if resp.status_code == 404:
                continue
            raise OAuthDiscoveryError(
                f"Unexpected status {resp.status_code} discovering protected resource metadata at {prm_url}"
            )

    if prm is None:
        return False  # no PRM anywhere -> server doesn't require OAuth

    if not prm.authorization_servers:
        raise OAuthDiscoveryError("Protected resource metadata has no authorization_servers")

    auth_server_url = str(prm.authorization_servers[0])
    async with httpx.AsyncClient(timeout=10) as client:
        for as_url in build_oauth_authorization_server_metadata_discovery_urls(auth_server_url, url):
            try:
                resp = await client.get(as_url)
            except httpx.HTTPError as e:
                raise OAuthDiscoveryError(
                    f"Network error discovering authorization server metadata at {as_url}: {e}"
                ) from e
            if resp.status_code == 200:
                try:
                    OAuthMetadata.model_validate_json(resp.content)
                except Exception as e:  # noqa: BLE001
                    raise OAuthDiscoveryError(f"Invalid authorization server metadata at {as_url}: {e}") from e
                return True
            if 300 <= resp.status_code < 500:
                continue
            raise OAuthDiscoveryError(f"Authorization server metadata request failed ({resp.status_code}) at {as_url}")

    raise OAuthDiscoveryError(
        f"Protected resource metadata referenced authorization server {auth_server_url} "
        "but no authorization server metadata was discoverable there"
    )


class ConnectedServer:
    def __init__(self, config: MCPServerConfig, session: ClientSession, stack: AsyncExitStack):
        self.config = config
        self.session = session
        self.stack = stack
        self.tools: list[dict[str, Any]] = []  # raw MCP tool defs


class MCPManager:
    """Singleton-ish manager; one instance lives on the FastAPI app state."""

    def __init__(self):
        self._connections: dict[str, ConnectedServer] = {}

    def is_connected(self, server_id: str) -> bool:
        return server_id in self._connections

    def get_tools_openai_format(self) -> list[dict[str, Any]]:
        """All tools across all connected servers, as OpenAI function-calling
        schemas, prefixed with the server name so collisions across servers
        are impossible and the model can tell them apart. Tools the user has
        disabled for a given server (config.disabled_tools, server-local
        names, not qualified) are skipped entirely -- the model never even
        sees them as callable."""
        tools: list[dict[str, Any]] = []
        for _server_id, conn in self._connections.items():
            disabled = set(conn.config.disabled_tools or [])
            for tool in conn.tools:
                if tool["name"] in disabled:
                    continue
                tools.append(
                    {
                        "type": "function",
                        "function": {
                            "name": f"{conn.config.name}__{tool['name']}",
                            "description": tool.get("description", ""),
                            "parameters": tool.get("inputSchema", {"type": "object", "properties": {}}),
                        },
                    }
                )
        return tools

    def _find_tool(self, qualified_name: str) -> tuple[ConnectedServer, str] | None:
        for conn in self._connections.values():
            prefix = f"{conn.config.name}__"
            if qualified_name.startswith(prefix):
                return conn, qualified_name[len(prefix) :]
        return None

    def set_tool_enabled(self, server_id: str, tool_name: str, enabled: bool) -> MCPServerConfig:
        """Toggle membership of `tool_name` (server-local, unqualified) in
        the server's disabled_tools list. Persists immediately and updates
        the live connection (if any) so get_tools_openai_format reflects it
        without requiring a reconnect."""
        config = get_mcp_server(server_id)
        if config is None:
            raise ValueError(f"MCP server not found: {server_id}")
        disabled = set(config.disabled_tools or [])
        if enabled:
            disabled.discard(tool_name)
        else:
            disabled.add(tool_name)
        updated = config.model_copy(update={"disabled_tools": sorted(disabled)})
        save_mcp_server(updated)
        conn = self._connections.get(server_id)
        if conn is not None:
            conn.config = updated
        return updated

    async def call_tool(self, qualified_name: str, arguments: dict[str, Any]) -> str:
        found = self._find_tool(qualified_name)
        if found is None:
            return f"Error: tool '{qualified_name}' not found on any connected MCP server."
        conn, tool_name = found
        if tool_name in (conn.config.disabled_tools or []):
            return f"Error: tool '{qualified_name}' is disabled by the user."
        try:
            result = await conn.session.call_tool(tool_name, arguments)
            parts = []
            for block in result.content:
                if hasattr(block, "text"):
                    parts.append(block.text)
                else:
                    parts.append(str(block))
            text = "\n".join(parts)
            if result.isError:
                return f"Tool error: {text}"
            return text
        except Exception as e:  # noqa: BLE001 - surface any tool failure to the model
            logger.exception("MCP tool call failed: %s", qualified_name)
            return f"Error calling tool '{qualified_name}': {e}"

    def _mark_status(self, config: MCPServerConfig, status: str, last_error: str | None) -> MCPServerConfig:
        updated = config.model_copy(update={"status": status, "last_error": last_error})
        save_mcp_server(updated)
        conn = self._connections.get(config.id)
        if conn is not None:
            conn.config = updated
        return updated

    async def ensure_valid_token(self, server_id: str) -> MCPServerConfig | None:
        """Called before reusing a stored OAuth token on reconnect. If the
        stored token is expired and a refresh_token is present, drives the
        MCP SDK's OAuth provider to refresh it. If refresh fails (or there's
        no refresh token to use), marks the server needs_auth with a clear
        last_error instead of silently failing and attempting a doomed
        connection. Returns the (possibly updated) config, or None if the
        server doesn't exist."""
        config = get_mcp_server(server_id)
        if config is None or not config.requires_oauth:
            return config

        storage = EncryptedFileTokenStorage(server_id)
        if not await storage.is_expired():
            return config

        tokens = await storage.get_tokens()
        if tokens is None or not tokens.refresh_token:
            return self._mark_status(
                config,
                "needs_auth",
                "OAuth access token expired and no refresh token is available; reauthorization required.",
            )

        if not config.url:
            return self._mark_status(config, "needs_auth", "OAuth-protected server has no url configured.")
        provider = await self._build_oauth_provider(config)
        try:
            async with httpx.AsyncClient(auth=provider, timeout=15) as client:
                await client.get(config.url)
        except Exception as e:  # noqa: BLE001
            logger.warning("OAuth token refresh request failed for %s: %s", config.name, e)
            return self._mark_status(config, "needs_auth", f"OAuth token refresh failed: {e}")

        if not provider.context.is_token_valid():
            return self._mark_status(
                config,
                "needs_auth",
                "OAuth token refresh failed: the authorization server rejected the "
                "refresh token. Reauthorization required.",
            )
        return config

    async def connect(self, config: MCPServerConfig) -> MCPServerConfig:
        if config.id in self._connections:
            await self.disconnect(config.id)

        if config.requires_oauth:
            refreshed = await self.ensure_valid_token(config.id)
            if refreshed is not None and refreshed.status == "needs_auth":
                return refreshed

        stack = AsyncExitStack()
        try:
            if config.transport == "stdio":
                if not config.command:
                    raise ValueError("stdio transport requires a command")
                params = StdioServerParameters(command=config.command, args=config.args, env=config.env or None)
                read, write = await stack.enter_async_context(stdio_client(params))
            elif config.transport in ("sse", "streamable_http"):
                if not config.url:
                    raise ValueError(f"{config.transport} transport requires a url")
                validate_outbound_url(config.url, allow_loopback=config.allow_local)
                auth = None
                if config.requires_oauth:
                    auth = await self._build_oauth_provider(config)
                if config.transport == "sse":
                    read, write = await stack.enter_async_context(sse_client(config.url, auth=auth))
                else:
                    http_client = None
                    if auth is not None:
                        http_client = await stack.enter_async_context(
                            httpx.AsyncClient(auth=auth, base_url=config.url, follow_redirects=True)
                        )
                    read, write, _ = await stack.enter_async_context(
                        streamablehttp_client(config.url, http_client=http_client)
                    )
            else:
                raise ValueError(f"Unknown transport: {config.transport}")

            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()

            tools_result = await session.list_tools()
            tools = [
                {
                    "name": t.name,
                    "description": t.description or "",
                    "inputSchema": t.inputSchema,
                }
                for t in tools_result.tools
            ]

            self._connections[config.id] = ConnectedServer(config, session, stack)

            updated = config.model_copy(update={"status": "connected", "last_error": None, "tool_count": len(tools)})
            self._connections[config.id].tools = tools
            save_mcp_server(updated)
            return updated

        except Exception as e:  # noqa: BLE001
            await stack.aclose()
            logger.exception("Failed to connect MCP server: %s", config.name)
            needs_auth = "401" in str(e) or "auth" in str(e).lower()
            updated = config.model_copy(
                update={
                    "status": "needs_auth" if needs_auth else "error",
                    "last_error": str(e)[:500],
                }
            )
            save_mcp_server(updated)
            return updated

    async def auto_connect(self, config: MCPServerConfig) -> MCPServerConfig:
        """Connect a remote MCP server without an explicit, known-good
        transport choice: try streamable_http first (the spec-preferred
        transport for new servers), then fall back to sse. Raises
        RuntimeError only if neither transport works at all -- a result of
        "needs_auth" (we reached the server but it wants OAuth) still
        counts as that transport working.
        """
        if config.transport == "stdio":
            return await self.connect(config)

        attempts: list[str] = []
        for transport in ("streamable_http", "sse"):
            trial = config.model_copy(update={"transport": transport})
            updated = await self.connect(trial)
            if updated.status in ("connected", "needs_auth"):
                return updated
            attempts.append(f"{transport}: {updated.last_error}")
        raise RuntimeError("Could not connect via streamable_http or sse. " + " | ".join(attempts))

    async def quick_add(self, name: str, url: str, description: str | None = None) -> tuple[MCPServerConfig, bool]:
        """Quick-add flow: user supplies only name/url/description. We
        auto-detect transport (auto_connect) and auto-detect whether OAuth
        is required (discover_oauth_requirement) rather than asking the
        user to tick a checkbox. Returns (config, oauth_detection_failed) --
        oauth_detection_failed is True only when discovery genuinely failed
        (network/malformed metadata), signaling the caller should fall back
        to asking the user to specify OAuth manually.
        """
        validate_outbound_url(url)

        requires_oauth = False
        oauth_detection_failed = False
        try:
            requires_oauth = await discover_oauth_requirement(url)
        except OAuthDiscoveryError as e:
            logger.warning("OAuth auto-discovery failed for %s: %s", url, e)
            oauth_detection_failed = True

        config = MCPServerConfig(
            name=name,
            url=url,
            transport="streamable_http",
            requires_oauth=requires_oauth,
            enabled=True,
        )
        # MCPServerConfig has no `description` field upstream of this change;
        # store it in env as a best-effort note rather than failing the
        # whole quick-add if the caller passes one and the model doesn't
        # carry it yet.
        if description:
            config = config.model_copy(update={"env": {**config.env, "_description": description}})

        updated = await self.auto_connect(config)
        if updated.status == "error" and updated.requires_oauth is False and not oauth_detection_failed:
            # Discovery said "no OAuth needed" but the connection still
            # failed looking like an auth problem -- the heuristic in
            # connect()'s exception handler already upgrades this to
            # needs_auth when the error text looks like a 401, so nothing
            # more to do here; this branch is just documentation of intent.
            pass
        return updated, oauth_detection_failed

    async def revoke_oauth_token(self, server_id: str) -> MCPServerConfig | None:
        """Delete the stored OAuth token (and client registration) for a
        server without removing the server config. Actually deletes the
        secret from the encrypted store via storage/secrets.py's
        delete_secret -- does not just flip a flag."""
        storage = EncryptedFileTokenStorage(server_id)
        storage.clear()
        config = get_mcp_server(server_id)
        if config is None:
            return None
        await self.disconnect(server_id)
        return self._mark_status(config, "needs_auth", "OAuth token revoked by user.")

    async def reauthorize(self, server_id: str) -> MCPServerConfig:
        """Clear the stored token and re-run the OAuth flow from scratch by
        reconnecting -- with no stored token, connect() will drive a fresh
        browser-based authorization."""
        config = get_mcp_server(server_id)
        if config is None:
            raise ValueError(f"MCP server not found: {server_id}")
        storage = EncryptedFileTokenStorage(server_id)
        storage.clear()
        await self.disconnect(server_id)
        return await self.connect(config)

    async def _build_oauth_provider(self, config: MCPServerConfig) -> OAuthClientProvider:
        callback_server = OAuthCallbackServer()
        port = await callback_server.start()
        redirect_uri = f"http://127.0.0.1:{port}/callback"

        async def redirect_handler(authorization_url: str) -> None:
            import webbrowser

            webbrowser.open(authorization_url)

        async def callback_handler() -> tuple[str, str | None]:
            return await callback_server.wait_for_code()

        storage = EncryptedFileTokenStorage(config.id)
        metadata = OAuthClientMetadata(
            redirect_uris=[redirect_uri],
            client_name="Local AI Workspace",
            grant_types=["authorization_code", "refresh_token"],
            response_types=["code"],
        )
        return OAuthClientProvider(
            server_url=config.url,
            client_metadata=metadata,
            storage=storage,
            redirect_handler=redirect_handler,
            callback_handler=callback_handler,
        )

    async def disconnect(self, server_id: str) -> None:
        conn = self._connections.pop(server_id, None)
        if conn:
            with contextlib.suppress(Exception):
                await conn.stack.aclose()

    async def disconnect_all(self) -> None:
        for server_id in list(self._connections.keys()):
            await self.disconnect(server_id)

    async def connect_all_enabled(self) -> None:
        for config in list_mcp_servers():
            if config.enabled:
                await self.connect(config)
