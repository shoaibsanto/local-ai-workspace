"""FastAPI application: REST + SSE API, plus serving the built frontend.

Binds to 127.0.0.1 only by default (see cli/main.py) — this is a local
desktop app, not a service meant to be exposed on the network.
"""
from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from local_ai_workspace.core.chat import ChatOrchestrator
from local_ai_workspace.core.models import MCPServerConfig, ProjectMeta, ProviderConfig
from local_ai_workspace.mcp.manager import MCPManager
from local_ai_workspace.storage import conversation_store
from local_ai_workspace.storage.mcp_store import (
    delete_mcp_server,
    get_mcp_server,
    list_mcp_servers,
    save_mcp_server,
)
from local_ai_workspace.storage.provider_store import (
    delete_provider,
    list_providers,
    save_provider,
    seed_default_providers,
)
from local_ai_workspace.storage.secrets import delete_secret, set_secret

logger = logging.getLogger(__name__)


class CreateConversationBody(BaseModel):
    title: str = "New Conversation"
    project_id: str | None = None
    model: str | None = None
    provider: str | None = None


class UpdateConversationBody(BaseModel):
    title: str | None = None
    pinned: bool | None = None
    model: str | None = None
    provider: str | None = None


class EditResendBody(BaseModel):
    message_index: int
    new_content: str


class SetProviderKeyBody(BaseModel):
    api_key: str


class ChatBody(BaseModel):
    content: str


@asynccontextmanager
async def lifespan(app: FastAPI):
    seed_default_providers()
    app.state.mcp_manager = MCPManager()
    app.state.orchestrator = ChatOrchestrator(app.state.mcp_manager)
    await app.state.mcp_manager.connect_all_enabled()
    yield
    await app.state.mcp_manager.disconnect_all()


def create_app() -> FastAPI:
    app = FastAPI(title="Local AI Workspace", lifespan=lifespan)

    # ---------- Conversations ----------

    @app.get("/api/conversations")
    def api_list_conversations(project_id: str | None = None):
        return [m.model_dump() for m in conversation_store.list_conversations(project_id)]

    @app.post("/api/conversations")
    def api_create_conversation(body: CreateConversationBody):
        meta = conversation_store.create_conversation(
            title=body.title, project_id=body.project_id, model=body.model, provider=body.provider
        )
        return meta.model_dump()

    @app.get("/api/conversations/search")
    def api_search_conversations(q: str):
        return [m.model_dump() for m in conversation_store.search_conversations(q)]

    @app.get("/api/conversations/{conversation_id}")
    def api_get_conversation(conversation_id: str):
        meta = conversation_store.get_conversation_meta(conversation_id)
        if meta is None:
            raise HTTPException(404, "Conversation not found")
        messages = conversation_store.get_messages(conversation_id)
        return {"meta": meta.model_dump(), "messages": [m.model_dump() for m in messages]}

    @app.patch("/api/conversations/{conversation_id}")
    def api_update_conversation(conversation_id: str, body: UpdateConversationBody):
        updates = {k: v for k, v in body.model_dump().items() if v is not None}
        meta = conversation_store.update_conversation_meta(conversation_id, **updates)
        if meta is None:
            raise HTTPException(404, "Conversation not found")
        return meta.model_dump()

    @app.delete("/api/conversations/{conversation_id}")
    def api_delete_conversation(conversation_id: str):
        if not conversation_store.delete_conversation(conversation_id):
            raise HTTPException(404, "Conversation not found")
        return {"ok": True}

    @app.post("/api/conversations/{conversation_id}/edit_resend")
    def api_edit_resend(conversation_id: str, body: EditResendBody):
        """Truncate history at message_index and replace it with new_content,
        ready for a fresh /chat call to regenerate from there."""
        messages = conversation_store.get_messages(conversation_id)
        if body.message_index < 0 or body.message_index >= len(messages):
            raise HTTPException(400, "Invalid message index")
        truncated = messages[: body.message_index]
        conversation_store.replace_messages(conversation_id, truncated)
        return {"ok": True, "remaining_messages": len(truncated)}

    @app.post("/api/conversations/{conversation_id}/regenerate")
    def api_regenerate(conversation_id: str):
        """Drop the last assistant turn (and any tool messages after the
        last user message) so the next /chat call regenerates it."""
        messages = conversation_store.get_messages(conversation_id)
        last_user_idx = None
        for i in range(len(messages) - 1, -1, -1):
            if messages[i].role == "user":
                last_user_idx = i
                break
        if last_user_idx is None:
            raise HTTPException(400, "No user message to regenerate from")
        truncated = messages[:last_user_idx]
        last_user_content = messages[last_user_idx].content
        conversation_store.replace_messages(conversation_id, truncated)
        return {"ok": True, "resend_content": last_user_content}

    # ---------- Chat streaming (SSE) ----------

    @app.post("/api/conversations/{conversation_id}/chat")
    async def api_chat(conversation_id: str, body: ChatBody):
        content = body.content
        orchestrator: ChatOrchestrator = app.state.orchestrator

        async def event_stream():
            async for event in orchestrator.run_turn(conversation_id, content):
                yield f"data: {json.dumps(event)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(event_stream(), media_type="text/event-stream")

    # ---------- Providers ----------

    @app.get("/api/providers")
    def api_list_providers():
        return [p.model_dump() for p in list_providers()]

    @app.post("/api/providers")
    def api_create_provider(body: ProviderConfig):
        return save_provider(body).model_dump()

    @app.put("/api/providers/{provider_id}/api_key")
    def api_set_provider_key(provider_id: str, body: SetProviderKeyBody):
        providers = {p.id: p for p in list_providers()}
        provider = providers.get(provider_id)
        if provider is None:
            raise HTTPException(404, "Provider not found")
        secret_ref = f"provider_api_key::{provider_id}"
        set_secret(secret_ref, body.api_key)
        updated = provider.model_copy(update={"api_key_ref": secret_ref, "enabled": True})
        return save_provider(updated).model_dump()

    @app.delete("/api/providers/{provider_id}")
    def api_delete_provider(provider_id: str):
        provider = next((p for p in list_providers() if p.id == provider_id), None)
        if provider and provider.api_key_ref:
            delete_secret(provider.api_key_ref)
        if not delete_provider(provider_id):
            raise HTTPException(404, "Provider not found")
        return {"ok": True}

    # ---------- Projects ----------

    @app.get("/api/projects")
    def api_list_projects():
        from local_ai_workspace.storage.json_store import read_json
        from local_ai_workspace.storage.paths import projects_dir

        results = []
        for d in projects_dir().iterdir():
            if d.is_dir():
                data = read_json(d / "meta.json")
                if data:
                    results.append(data)
        return results

    @app.post("/api/projects")
    def api_create_project(body: ProjectMeta):
        from local_ai_workspace.storage.json_store import write_json_atomic
        from local_ai_workspace.storage.paths import projects_dir

        d = projects_dir() / body.id
        d.mkdir(parents=True, exist_ok=True)
        write_json_atomic(d / "meta.json", body.model_dump())
        return body.model_dump()

    # ---------- MCP servers ----------

    @app.get("/api/mcp/servers")
    def api_list_mcp_servers():
        return [s.model_dump() for s in list_mcp_servers()]

    @app.post("/api/mcp/servers")
    async def api_create_mcp_server(body: MCPServerConfig):
        save_mcp_server(body)
        if body.enabled:
            updated = await app.state.mcp_manager.connect(body)
            return updated.model_dump()
        return body.model_dump()

    @app.post("/api/mcp/servers/{server_id}/connect")
    async def api_connect_mcp_server(server_id: str):
        config = get_mcp_server(server_id)
        if config is None:
            raise HTTPException(404, "MCP server not found")
        updated = await app.state.mcp_manager.connect(config)
        return updated.model_dump()

    @app.post("/api/mcp/servers/{server_id}/disconnect")
    async def api_disconnect_mcp_server(server_id: str):
        await app.state.mcp_manager.disconnect(server_id)
        config = get_mcp_server(server_id)
        if config:
            updated = config.model_copy(update={"status": "disconnected"})
            save_mcp_server(updated)
            return updated.model_dump()
        return {"ok": True}

    @app.delete("/api/mcp/servers/{server_id}")
    async def api_delete_mcp_server(server_id: str):
        await app.state.mcp_manager.disconnect(server_id)
        if not delete_mcp_server(server_id):
            raise HTTPException(404, "MCP server not found")
        return {"ok": True}

    @app.get("/api/mcp/tools")
    def api_list_mcp_tools():
        return app.state.mcp_manager.get_tools_openai_format()

    @app.get("/api/health")
    def api_health():
        return {"status": "ok"}

    # ---------- Frontend static files (production) ----------

    static_dir = Path(__file__).resolve().parent.parent / "static"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="frontend")

    return app
