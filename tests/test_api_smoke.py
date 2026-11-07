"""Smoke tests for the FastAPI app: no network calls to real LLM providers,
just verifying the app wires up and the filesystem persistence layer works.
Run with: pytest
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_AI_WORKSPACE_HOME", str(tmp_path))
    from local_ai_workspace.api.app import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_default_providers_seeded(client):
    resp = client.get("/api/providers")
    assert resp.status_code == 200
    data = resp.json()
    names = {p["name"] for p in data}
    assert "OpenRouter" in names
    assert "Anthropic" in names


def test_create_and_fetch_conversation(client):
    resp = client.post("/api/conversations", json={"title": "Test", "model": "x", "provider": "y"})
    assert resp.status_code == 200
    conv = resp.json()
    assert conv["title"] == "Test"

    resp2 = client.get(f"/api/conversations/{conv['id']}")
    assert resp2.status_code == 200
    body = resp2.json()
    assert body["meta"]["id"] == conv["id"]
    assert body["messages"] == []


def test_update_and_delete_conversation(client):
    conv = client.post("/api/conversations", json={"title": "A"}).json()
    resp = client.patch(f"/api/conversations/{conv['id']}", json={"pinned": True})
    assert resp.status_code == 200
    assert resp.json()["pinned"] is True

    resp = client.delete(f"/api/conversations/{conv['id']}")
    assert resp.status_code == 200
    assert client.get(f"/api/conversations/{conv['id']}").status_code == 404


def test_set_provider_key_enables_provider(client):
    providers = client.get("/api/providers").json()
    provider_id = providers[0]["id"]
    resp = client.put(f"/api/providers/{provider_id}/api_key", json={"api_key": "sk-test-123"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["enabled"] is True
    assert body["api_key_ref"] is not None
    # raw key must never be echoed back
    assert "sk-test-123" not in str(body)


def test_secrets_are_encrypted_on_disk(client, tmp_path):
    providers = client.get("/api/providers").json()
    provider_id = providers[0]["id"]
    client.put(f"/api/providers/{provider_id}/api_key", json={"api_key": "sk-super-secret-value"})
    secrets_file = tmp_path / "secrets.enc"
    assert secrets_file.exists()
    raw = secrets_file.read_bytes()
    assert b"sk-super-secret-value" not in raw


def test_mcp_server_crud(client):
    resp = client.post(
        "/api/mcp/servers",
        json={"name": "test-echo", "transport": "stdio", "command": "nonexistent-binary", "args": [], "enabled": False},
    )
    assert resp.status_code == 200
    server = resp.json()
    assert server["name"] == "test-echo"

    resp = client.get("/api/mcp/servers")
    assert any(s["id"] == server["id"] for s in resp.json())

    resp = client.delete(f"/api/mcp/servers/{server['id']}")
    assert resp.status_code == 200
