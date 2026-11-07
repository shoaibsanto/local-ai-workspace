"""Trivial stdio MCP test server used by the graceful-shutdown test and the
manual SIGTERM shutdown check.

Exposes a single tool, `echo`, that returns whatever string it was given.
No live network calls -- this is intentionally the smallest possible real
MCP server so we can exercise MCPManager's connect/disconnect lifecycle
against a genuine ClientSession/transport pair instead of mocking it away.

Run directly: `python tests/fixtures/echo_mcp_server.py` (speaks MCP over
stdio -- not meant to be run interactively).
"""

from __future__ import annotations

import anyio
import mcp.types as types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.server.models import InitializationOptions
from mcp.server.stdio import stdio_server

server: Server = Server("echo-test-server", version="0.1.0")


@server.list_tools()
async def _on_list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="echo",
            description="Echo back the provided text.",
            inputSchema={
                "type": "object",
                "properties": {"text": {"type": "string"}},
                "required": ["text"],
            },
        )
    ]


@server.call_tool()
async def _on_call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    text = (arguments or {}).get("text", "")
    return [types.TextContent(type="text", text=f"echo: {text}")]


async def main() -> None:
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name="echo-test-server",
                server_version="0.1.0",
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )


if __name__ == "__main__":
    anyio.run(main)
