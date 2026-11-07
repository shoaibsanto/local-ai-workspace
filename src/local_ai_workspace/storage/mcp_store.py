"""MCP server configuration persistence (non-secret fields only)."""
from __future__ import annotations

from local_ai_workspace.core.models import MCPServerConfig
from local_ai_workspace.storage.json_store import read_json, write_json_atomic
from local_ai_workspace.storage.paths import mcp_servers_path


def list_mcp_servers() -> list[MCPServerConfig]:
    data = read_json(mcp_servers_path(), default=[])
    return [MCPServerConfig(**s) for s in data]


def get_mcp_server(server_id: str) -> MCPServerConfig | None:
    for s in list_mcp_servers():
        if s.id == server_id:
            return s
    return None


def save_mcp_server(server: MCPServerConfig) -> MCPServerConfig:
    servers = list_mcp_servers()
    servers = [s for s in servers if s.id != server.id]
    servers.append(server)
    write_json_atomic(mcp_servers_path(), [s.model_dump() for s in servers])
    return server


def delete_mcp_server(server_id: str) -> bool:
    servers = list_mcp_servers()
    remaining = [s for s in servers if s.id != server_id]
    if len(remaining) == len(servers):
        return False
    write_json_atomic(mcp_servers_path(), [s.model_dump() for s in remaining])
    return True
