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

import logging
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.auth import OAuthClientProvider
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client as streamablehttp_client
from mcp.shared.auth import OAuthClientMetadata

from local_ai_workspace.core.models import MCPServerConfig
from local_ai_workspace.mcp.oauth_flow import OAuthCallbackServer, make_redirect_handler
from local_ai_workspace.mcp.oauth_storage import EncryptedFileTokenStorage
from local_ai_workspace.storage.mcp_store import list_mcp_servers, save_mcp_server

logger = logging.getLogger(__name__)


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
        are impossible and the model can tell them apart."""
        tools: list[dict[str, Any]] = []
        for server_id, conn in self._connections.items():
            for tool in conn.tools:
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

    async def call_tool(self, qualified_name: str, arguments: dict[str, Any]) -> str:
        found = self._find_tool(qualified_name)
        if found is None:
            return f"Error: tool '{qualified_name}' not found on any connected MCP server."
        conn, tool_name = found
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

    async def connect(self, config: MCPServerConfig) -> MCPServerConfig:
        if config.id in self._connections:
            await self.disconnect(config.id)

        stack = AsyncExitStack()
        try:
            if config.transport == "stdio":
                if not config.command:
                    raise ValueError("stdio transport requires a command")
                params = StdioServerParameters(
                    command=config.command, args=config.args, env=config.env or None
                )
                read, write = await stack.enter_async_context(stdio_client(params))
            elif config.transport in ("sse", "streamable_http"):
                if not config.url:
                    raise ValueError(f"{config.transport} transport requires a url")
                auth = None
                if config.requires_oauth:
                    auth = await self._build_oauth_provider(config)
                if config.transport == "sse":
                    read, write = await stack.enter_async_context(
                        sse_client(config.url, auth=auth)
                    )
                else:
                    http_client = None
                    if auth is not None:
                        import httpx

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

            updated = config.model_copy(
                update={"status": "connected", "last_error": None, "tool_count": len(tools)}
            )
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
            try:
                await conn.stack.aclose()
            except Exception:  # noqa: BLE001
                pass

    async def disconnect_all(self) -> None:
        for server_id in list(self._connections.keys()):
            await self.disconnect(server_id)

    async def connect_all_enabled(self) -> None:
        for config in list_mcp_servers():
            if config.enabled:
                await self.connect(config)
