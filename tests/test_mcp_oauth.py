"""Tests for MCP OAuth token isolation and per-tool enable/disable."""
from __future__ import annotations

from contextlib import AsyncExitStack

import pytest

from local_ai_workspace.core.models import MCPServerConfig
from local_ai_workspace.mcp.manager import ConnectedServer, MCPManager
from local_ai_workspace.mcp.oauth_storage import EncryptedFileTokenStorage


# ---------- token isolation between two servers ----------


@pytest.mark.asyncio
async def test_tokens_are_keyed_strictly_by_server_id(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_AI_WORKSPACE_HOME", str(tmp_path))

    from mcp.shared.auth import OAuthToken

    storage_a = EncryptedFileTokenStorage("server-a")
    storage_b = EncryptedFileTokenStorage("server-b")

    token_a = OAuthToken(access_token="secret-for-a", token_type="Bearer", expires_in=3600)
    token_b = OAuthToken(access_token="secret-for-b", token_type="Bearer", expires_in=3600)

    await storage_a.set_tokens(token_a)
    await storage_b.set_tokens(token_b)

    got_a = await storage_a.get_tokens()
    got_b = await storage_b.get_tokens()

    assert got_a is not None and got_a.access_token == "secret-for-a"
    assert got_b is not None and got_b.access_token == "secret-for-b"

    # Cross-reads must never see the other server's secret.
    assert got_a.access_token != got_b.access_token


@pytest.mark.asyncio
async def test_deleting_one_server_token_does_not_touch_the_other(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_AI_WORKSPACE_HOME", str(tmp_path))

    from mcp.shared.auth import OAuthToken

    storage_a = EncryptedFileTokenStorage("server-a")
    storage_b = EncryptedFileTokenStorage("server-b")

    await storage_a.set_tokens(OAuthToken(access_token="a-token", token_type="Bearer"))
    await storage_b.set_tokens(OAuthToken(access_token="b-token", token_type="Bearer"))

    storage_a.clear()

    assert await storage_a.get_tokens() is None
    remaining = await storage_b.get_tokens()
    assert remaining is not None
    assert remaining.access_token == "b-token"


@pytest.mark.asyncio
async def test_raw_secrets_store_has_no_cross_server_keys(monkeypatch, tmp_path):
    """Directly inspect the encrypted blob's key namespace -- every key must
    carry its own server_id and never a shared/global token key."""
    monkeypatch.setenv("LOCAL_AI_WORKSPACE_HOME", str(tmp_path))

    from mcp.shared.auth import OAuthToken
    from local_ai_workspace.storage.secrets import load_secrets

    storage_a = EncryptedFileTokenStorage("server-a")
    storage_b = EncryptedFileTokenStorage("server-b")
    await storage_a.set_tokens(OAuthToken(access_token="a-token", token_type="Bearer"))
    await storage_b.set_tokens(OAuthToken(access_token="b-token", token_type="Bearer"))

    all_secrets = load_secrets()
    assert "mcp_oauth_token::server-a" in all_secrets
    assert "mcp_oauth_token::server-b" in all_secrets
    assert all_secrets["mcp_oauth_token::server-a"] != all_secrets["mcp_oauth_token::server-b"]
    # no generic/shared key that both servers might read from
    assert "mcp_oauth_token" not in all_secrets


@pytest.mark.asyncio
async def test_new_server_with_same_name_different_id_gets_no_token(monkeypatch, tmp_path):
    """Even if a server is re-added with the same *name*, a different
    server id must not inherit a previously stored token."""
    monkeypatch.setenv("LOCAL_AI_WORKSPACE_HOME", str(tmp_path))

    from mcp.shared.auth import OAuthToken

    first = EncryptedFileTokenStorage("srv_123")
    await first.set_tokens(OAuthToken(access_token="first-token", token_type="Bearer"))

    recreated_same_name_new_id = EncryptedFileTokenStorage("srv_456")
    assert await recreated_same_name_new_id.get_tokens() is None


# ---------- disabled_tools filtering in get_tools_openai_format ----------


def _make_connection(server_id: str, name: str, tool_names: list[str], disabled: list[str]) -> ConnectedServer:
    config = MCPServerConfig(id=server_id, name=name, transport="stdio", disabled_tools=disabled)
    conn = ConnectedServer(config=config, session=object(), stack=AsyncExitStack())
    conn.tools = [{"name": t, "description": f"{t} description", "input_schema": {}} for t in tool_names]
    return conn


def test_get_tools_openai_format_skips_disabled_tools():
    manager = MCPManager()
    conn = _make_connection(
        "srv_1", "myserver", ["list_files", "delete_file"], disabled=["delete_file"]
    )
    manager._connections["srv_1"] = conn

    tools = manager.get_tools_openai_format()
    names = [t["function"]["name"] for t in tools]

    assert "myserver__list_files" in names
    assert "myserver__delete_file" not in names
    assert len(names) == 1


def test_get_tools_openai_format_includes_all_when_nothing_disabled():
    manager = MCPManager()
    conn = _make_connection("srv_1", "myserver", ["a", "b"], disabled=[])
    manager._connections["srv_1"] = conn

    tools = manager.get_tools_openai_format()
    names = {t["function"]["name"] for t in tools}
    assert names == {"myserver__a", "myserver__b"}


def test_disabled_tools_is_server_local_not_shared_across_servers():
    manager = MCPManager()
    conn_a = _make_connection("srv_a", "alpha", ["shared_name"], disabled=["shared_name"])
    conn_b = _make_connection("srv_b", "beta", ["shared_name"], disabled=[])
    manager._connections["srv_a"] = conn_a
    manager._connections["srv_b"] = conn_b

    tools = manager.get_tools_openai_format()
    names = {t["function"]["name"] for t in tools}

    assert "alpha__shared_name" not in names
    assert "beta__shared_name" in names


def test_set_tool_enabled_toggles_disabled_tools_list(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_AI_WORKSPACE_HOME", str(tmp_path))

    from local_ai_workspace.storage.mcp_store import save_mcp_server

    manager = MCPManager()
    config = MCPServerConfig(id="srv_1", name="myserver", transport="stdio")
    save_mcp_server(config)
    conn = _make_connection("srv_1", "myserver", ["a", "b"], disabled=[])
    manager._connections["srv_1"] = conn

    updated = manager.set_tool_enabled("srv_1", "a", enabled=False)
    assert "a" in updated.disabled_tools

    tools = manager.get_tools_openai_format()
    names = {t["function"]["name"] for t in tools}
    assert "myserver__a" not in names
    assert "myserver__b" in names

    reenabled = manager.set_tool_enabled("srv_1", "a", enabled=True)
    assert "a" not in reenabled.disabled_tools
