"""Tests for the provider system: CRUD with extended fields, capability
gating behavior in the chat orchestrator, Gemini message-format conversion,
and the no-raw-key-leak guarantee across every provider-returning endpoint.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_AI_WORKSPACE_HOME", str(tmp_path))
    from local_ai_workspace.api.app import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c


# ---------- Provider CRUD with new fields ----------


def test_create_provider_with_extended_fields(client):
    resp = client.post(
        "/api/providers",
        json={
            "name": "My Gemini",
            "base_url": "https://generativelanguage.googleapis.com/v1beta",
            "kind": "gemini",
            "default_model": "gemini-1.5-pro",
            "models": ["gemini-1.5-pro", "gemini-1.5-flash"],
            "organization_id": "org-123",
            "custom_headers": {"X-Trace": "abc"},
            "timeout_seconds": 30.0,
            "context_window": 1000000,
            "allow_local": False,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "gemini"
    assert body["organization_id"] == "org-123"
    assert body["custom_headers"] == {"X-Trace": "abc"}
    assert body["timeout_seconds"] == 30.0
    assert body["context_window"] == 1000000
    assert body["allow_local"] is False
    # capabilities defaults to all-False until detected
    assert body["capabilities"] == {
        "streaming": False,
        "tool_calling": False,
        "vision": False,
        "structured_output": False,
    }


def test_default_capabilities_shape_on_seeded_providers(client):
    providers = client.get("/api/providers").json()
    for p in providers:
        assert set(p["capabilities"].keys()) == {
            "streaming",
            "tool_calling",
            "vision",
            "structured_output",
        }


def test_gemini_provider_round_trips_through_list(client):
    created = client.post(
        "/api/providers",
        json={
            "name": "Gemini",
            "base_url": "https://generativelanguage.googleapis.com/v1beta",
            "kind": "gemini",
        },
    ).json()
    providers = client.get("/api/providers").json()
    assert any(p["id"] == created["id"] and p["kind"] == "gemini" for p in providers)


# ---------- Capability detection endpoint ----------


def test_detect_capabilities_endpoint_updates_provider(client):
    created = client.post(
        "/api/providers",
        json={
            "name": "Claude Sonnet",
            "base_url": "https://api.anthropic.com/v1",
            "kind": "anthropic",
            "default_model": "claude-sonnet-4-5",
        },
    ).json()
    resp = client.post(f"/api/providers/{created['id']}/detect_capabilities")
    assert resp.status_code == 200
    body = resp.json()
    assert body["capabilities"]["tool_calling"] is True
    assert body["capabilities"]["vision"] is True

    # persisted
    providers = client.get("/api/providers").json()
    saved = next(p for p in providers if p["id"] == created["id"])
    assert saved["capabilities"]["tool_calling"] is True


def test_detect_capabilities_unknown_provider_404(client):
    resp = client.post("/api/providers/does-not-exist/detect_capabilities")
    assert resp.status_code == 404


# ---------- Test connection endpoint ----------


def test_test_connection_unknown_provider_404(client):
    resp = client.post("/api/providers/does-not-exist/test_connection")
    assert resp.status_code == 404


def test_test_connection_network_failure_reported_cleanly(client):
    # A provider pointed at an unroutable address: should fail fast(ish)
    # with ok=False and a populated error, never raise an unhandled exception.
    created = client.post(
        "/api/providers",
        json={
            "name": "Broken",
            "base_url": "http://127.0.0.1:1/v1",  # nothing listens here
            "kind": "openai_compatible",
            "default_model": "nonexistent-model",
        },
    ).json()
    resp = client.post(f"/api/providers/{created['id']}/test_connection")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"]


def test_test_connection_no_model_configured(client):
    created = client.post(
        "/api/providers",
        json={
            "name": "NoModel",
            "base_url": "https://example.invalid/v1",
            "kind": "openai_compatible",
        },
    ).json()
    resp = client.post(f"/api/providers/{created['id']}/test_connection")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "model" in body["error"].lower()


# ---------- Capability-gated tool passing in ChatOrchestrator ----------


@pytest.mark.asyncio
async def test_chat_orchestrator_withholds_tools_when_tool_calling_false(monkeypatch, tmp_path):
    """When a provider's capabilities explicitly say tool_calling=False, the
    orchestrator must not pass tool definitions to the client's stream call,
    even if MCP tools are registered."""
    monkeypatch.setenv("LOCAL_AI_WORKSPACE_HOME", str(tmp_path))

    from local_ai_workspace.core.chat import ChatOrchestrator
    from local_ai_workspace.core.models import ProviderConfig
    from local_ai_workspace.providers.client import StreamEvent
    from local_ai_workspace.storage import conversation_store
    from local_ai_workspace.storage import provider_store

    provider = ProviderConfig(
        name="NoTools",
        base_url="https://example.invalid/v1",
        kind="openai_compatible",
        default_model="some-model",
        enabled=True,
        capabilities={
            "streaming": True,
            "tool_calling": False,
            "vision": False,
            "structured_output": False,
        },
    )
    provider_store.save_provider(provider)

    meta = conversation_store.create_conversation(
        title="t", model=provider.default_model, provider=provider.id
    )

    captured = {}

    class FakeClient:
        async def stream(self, messages, model, tools=None, temperature=1.0):
            captured["tools"] = tools
            yield StreamEvent(type="text_delta", text="hi")
            yield StreamEvent(type="done", finish_reason="stop")

    def fake_make_client(kind, base_url, api_key, allow_local=False):
        return FakeClient()

    class FakeMCPManager:
        def get_tools_openai_format(self):
            return [
                {
                    "type": "function",
                    "function": {"name": "search", "description": "x", "parameters": {}},
                }
            ]

        async def call_tool(self, name, args):
            return "unused"

    monkeypatch.setattr("local_ai_workspace.core.chat.make_client", fake_make_client)

    orchestrator = ChatOrchestrator(FakeMCPManager())
    events = [e async for e in orchestrator.run_turn(meta.id, "hello")]

    assert captured["tools"] is None
    assert any(e["type"] == "assistant_message" for e in events)


@pytest.mark.asyncio
async def test_chat_orchestrator_permissive_when_capability_unset(monkeypatch, tmp_path):
    """tool_calling key simply absent (unknown) should still allow tools
    through -- permissive-by-default per the documented policy."""
    monkeypatch.setenv("LOCAL_AI_WORKSPACE_HOME", str(tmp_path))

    from local_ai_workspace.core.chat import ChatOrchestrator
    from local_ai_workspace.core.models import ProviderConfig
    from local_ai_workspace.providers.client import StreamEvent
    from local_ai_workspace.storage import conversation_store
    from local_ai_workspace.storage import provider_store

    provider = ProviderConfig(
        name="UnknownCaps",
        base_url="https://example.invalid/v1",
        kind="openai_compatible",
        default_model="some-model",
        enabled=True,
        capabilities={},  # nothing known
    )
    provider_store.save_provider(provider)

    meta = conversation_store.create_conversation(
        title="t", model=provider.default_model, provider=provider.id
    )

    captured = {}

    class FakeClient:
        async def stream(self, messages, model, tools=None, temperature=1.0):
            captured["tools"] = tools
            yield StreamEvent(type="done", finish_reason="stop")

    class FakeMCPManager:
        def get_tools_openai_format(self):
            return [{"type": "function", "function": {"name": "search", "parameters": {}}}]

        async def call_tool(self, name, args):
            return "unused"

    monkeypatch.setattr(
        "local_ai_workspace.core.chat.make_client",
        lambda kind, base_url, api_key, allow_local=False: FakeClient(),
    )

    orchestrator = ChatOrchestrator(FakeMCPManager())
    _ = [e async for e in orchestrator.run_turn(meta.id, "hello")]

    assert captured["tools"] is not None


# ---------- Gemini message conversion (no live network) ----------


def test_gemini_message_conversion_roles_and_system():
    from local_ai_workspace.providers.gemini import _messages_to_gemini

    messages = [
        {"role": "system", "content": "Be terse."},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    contents, system_instruction = _messages_to_gemini(messages)
    assert system_instruction == "Be terse."
    assert [c["role"] for c in contents] == ["user", "model"]
    assert contents[0]["parts"][0]["text"] == "hi"
    assert contents[1]["parts"][0]["text"] == "hello"


def test_gemini_message_conversion_tool_calls_and_results():
    from local_ai_workspace.providers.gemini import _messages_to_gemini

    messages = [
        {"role": "user", "content": "weather?"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "get_weather", "arguments": json.dumps({"city": "NYC"})},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": "72F sunny"},
    ]
    contents, _ = _messages_to_gemini(messages)
    assert contents[1]["role"] == "model"
    assert contents[1]["parts"][0]["functionCall"]["name"] == "get_weather"
    assert contents[1]["parts"][0]["functionCall"]["args"] == {"city": "NYC"}
    assert contents[2]["role"] == "user"
    assert "functionResponse" in contents[2]["parts"][0]


@pytest.mark.asyncio
async def test_gemini_client_stream_parses_sse_without_network(monkeypatch):
    """Verify GeminiClient.stream converts a mocked SSE response into our
    StreamEvent shape, without any real HTTP call."""
    import httpx

    from local_ai_workspace.providers.gemini import GeminiClient

    sse_body = (
        'data: {"candidates":[{"content":{"parts":[{"text":"Hello"}]},'
        '"finishReason":null}]}\n\n'
        'data: {"candidates":[{"content":{"parts":[{"text":" world"}]},'
        '"finishReason":"STOP"}],"usageMetadata":{"promptTokenCount":5,'
        '"candidatesTokenCount":2,"totalTokenCount":7}}\n\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=sse_body.encode(), headers={"content-type": "text/event-stream"})

    transport = httpx.MockTransport(handler)

    class PatchedAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("local_ai_workspace.providers.gemini.httpx.AsyncClient", PatchedAsyncClient)

    gemini_client = GeminiClient(base_url=None, api_key="fake-key")
    events = []
    async for event in gemini_client.stream([{"role": "user", "content": "hi"}], "gemini-1.5-pro"):
        events.append(event)

    text_events = [e for e in events if e.type == "text_delta"]
    done_events = [e for e in events if e.type == "done"]
    assert "".join(e.text for e in text_events) == "Hello world"
    assert len(done_events) == 1
    assert done_events[0].finish_reason == "STOP"
    assert done_events[0].usage == {
        "prompt_tokens": 5,
        "completion_tokens": 2,
        "total_tokens": 7,
    }


@pytest.mark.asyncio
async def test_gemini_client_list_models_without_network(monkeypatch):
    import httpx

    from local_ai_workspace.providers.gemini import GeminiClient

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "models": [
                    {"name": "models/gemini-1.5-pro"},
                    {"name": "models/gemini-1.5-flash"},
                ]
            },
        )

    transport = httpx.MockTransport(handler)

    class PatchedAsyncClient(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    monkeypatch.setattr("local_ai_workspace.providers.gemini.httpx.AsyncClient", PatchedAsyncClient)

    gemini_client = GeminiClient(base_url=None, api_key="fake-key")
    models = await gemini_client.list_models()
    assert models == ["gemini-1.5-pro", "gemini-1.5-flash"]


def test_make_client_dispatches_gemini():
    from local_ai_workspace.providers.client import make_client
    from local_ai_workspace.providers.gemini import GeminiClient

    c = make_client("gemini", "https://generativelanguage.googleapis.com/v1beta", "key")
    assert isinstance(c, GeminiClient)


# ---------- Never expose raw api_key ----------


RAW_KEY = "sk-super-secret-raw-key-should-never-leak"


def _assert_no_raw_key_anywhere(payload) -> None:
    serialized = json.dumps(payload)
    assert RAW_KEY not in serialized
    assert "api_key" not in serialized or '"api_key_ref"' in serialized


def test_no_provider_endpoint_ever_returns_raw_api_key(client):
    # Set a real-looking key on a seeded provider.
    providers = client.get("/api/providers").json()
    provider_id = providers[0]["id"]
    set_resp = client.put(f"/api/providers/{provider_id}/api_key", json={"api_key": RAW_KEY})
    assert set_resp.status_code == 200
    _assert_no_raw_key_anywhere(set_resp.json())
    assert "api_key" not in set_resp.json()

    # GET /api/providers (list)
    list_resp = client.get("/api/providers")
    _assert_no_raw_key_anywhere(list_resp.json())
    for p in list_resp.json():
        assert "api_key" not in p

    # POST /api/providers (create) echoes the created object back
    create_resp = client.post(
        "/api/providers",
        json={"name": "X", "base_url": "https://example.invalid", "kind": "openai_compatible"},
    )
    _assert_no_raw_key_anywhere(create_resp.json())
    assert "api_key" not in create_resp.json()

    # POST detect_capabilities also returns the provider object
    caps_resp = client.post(f"/api/providers/{provider_id}/detect_capabilities")
    _assert_no_raw_key_anywhere(caps_resp.json())
    assert "api_key" not in caps_resp.json()
