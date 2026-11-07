"""Tests for the production-reliability pass: global exception handling,
request-id correlation, chat rate limiting, and concurrent-write safety on
the conversation store.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCAL_AI_WORKSPACE_HOME", str(tmp_path))
    from local_ai_workspace.api.app import create_app

    app = create_app()
    with TestClient(app) as c:
        yield c


# ---------- Global exception handling ----------


def test_unhandled_exception_returns_generic_500_with_request_id(tmp_path, monkeypatch):
    """An unhandled exception anywhere in a route handler must never leak a
    stack trace or file path into the HTTP response -- only a generic
    {"error": "internal_error", "request_id": ...} body."""
    monkeypatch.setenv("LOCAL_AI_WORKSPACE_HOME", str(tmp_path))
    from local_ai_workspace.api.app import create_app
    from local_ai_workspace.storage import conversation_store

    def boom(*args, **kwargs):
        raise RuntimeError("something exploded deep inside /root/local-ai-workspace/src/secret_path.py")

    monkeypatch.setattr(conversation_store, "list_conversations", boom)

    app = create_app()
    # raise_server_exceptions=False: TestClient normally re-raises unhandled
    # exceptions in-process for debuggability; here we specifically want to
    # observe the real HTTP response our exception handler produces.
    with TestClient(app, raise_server_exceptions=False) as c:
        resp = c.get("/api/conversations")
    assert resp.status_code == 500
    body = resp.json()
    assert body["error"] == "internal_error"
    assert "request_id" in body and body["request_id"] != "-"
    # Must never leak the exception message or any file path.
    assert "secret_path.py" not in resp.text
    assert "RuntimeError" not in resp.text
    assert "Traceback" not in resp.text


def test_http_exception_still_includes_request_id(client):
    """A deliberate HTTPException (e.g. 404) should keep its normal status
    code/detail but also carry the request id for correlation."""
    resp = client.get("/api/conversations/does-not-exist")
    assert resp.status_code == 404
    body = resp.json()
    assert "request_id" in body


# ---------- Request-id correlation ----------


def test_every_response_has_a_unique_request_id_header(client):
    resp1 = client.get("/api/health")
    resp2 = client.get("/api/health")
    assert "X-Request-Id" in resp1.headers
    assert "X-Request-Id" in resp2.headers
    assert resp1.headers["X-Request-Id"] != resp2.headers["X-Request-Id"]


# ---------- Request size limit ----------


def test_oversized_request_body_rejected_with_413(client):
    from local_ai_workspace.api.app import MAX_REQUEST_BODY_BYTES

    create = client.post("/api/conversations", json={"title": "size test"})
    conv_id = create.json()["id"]

    huge = "x" * (MAX_REQUEST_BODY_BYTES + 1)
    resp = client.post(f"/api/conversations/{conv_id}/chat", json={"content": huge})
    assert resp.status_code == 413
    assert resp.json()["error"] == "request_too_large"


# ---------- Chat rate limiting ----------


def test_chat_endpoint_rate_limited_after_configured_threshold(client, monkeypatch):
    from local_ai_workspace.core.rate_limit import chat_rate_limiter

    chat_rate_limiter.reset()

    create = client.post("/api/conversations", json={"title": "rate limit test"})
    conv_id = create.json()["id"]

    # Force a tiny limit so the test doesn't need to fire 20+ requests.
    from local_ai_workspace.storage import settings_store

    settings = settings_store.get_settings()
    monkeypatch.setattr(
        settings_store,
        "get_settings",
        lambda: settings.model_copy(update={"chat_rate_limit_per_minute": 2}),
    )
    # app.py imported get_settings by reference at module scope via
    # `from ... import get_settings`? No -- it calls get_settings() fresh
    # each time via the imported name, so patch at the app module too.
    from local_ai_workspace.api import app as app_module

    monkeypatch.setattr(
        app_module,
        "get_settings",
        lambda: settings.model_copy(update={"chat_rate_limit_per_minute": 2}),
    )

    def fake_run_turn(conversation_id, content):
        async def gen():
            yield {"type": "done"}

        return gen()

    from local_ai_workspace.core.chat import ChatOrchestrator

    monkeypatch.setattr(ChatOrchestrator, "run_turn", lambda self, cid, content: fake_run_turn(cid, content))

    ok1 = client.post(f"/api/conversations/{conv_id}/chat", json={"content": "hi"})
    ok2 = client.post(f"/api/conversations/{conv_id}/chat", json={"content": "hi"})
    blocked = client.post(f"/api/conversations/{conv_id}/chat", json={"content": "hi"})

    assert ok1.status_code == 200
    assert ok2.status_code == 200
    assert blocked.status_code == 429
    chat_rate_limiter.reset()


# ---------- Concurrency safety ----------


def test_concurrent_add_message_never_loses_a_message(tmp_path, monkeypatch):
    """Fire many concurrent add_message calls at the SAME conversation and
    assert every single one lands -- no interleaved read-modify-write on
    meta.json's message_count silently drops an increment."""
    monkeypatch.setenv("LOCAL_AI_WORKSPACE_HOME", str(tmp_path))
    from local_ai_workspace.core.models import Message
    from local_ai_workspace.storage import conversation_store

    meta = conversation_store.create_conversation(title="concurrency test")

    async def run():
        async def add(i: int):
            await asyncio.to_thread(
                conversation_store.add_message,
                meta.id,
                Message(role="user", content=f"message {i}"),
            )

        await asyncio.gather(*(add(i) for i in range(50)))

    asyncio.run(run())

    messages = conversation_store.get_messages(meta.id)
    updated_meta = conversation_store.get_conversation_meta(meta.id)

    assert len(messages) == 50
    assert updated_meta is not None
    assert updated_meta.message_count == 50
    # Every message content must be present exactly once -- no corruption,
    # truncation, or duplicate from a racy append.
    contents = {m.content for m in messages}
    assert contents == {f"message {i}" for i in range(50)}
