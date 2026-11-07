"""FastAPI application: REST + SSE API, plus serving the built frontend.

Binds to 127.0.0.1 only by default (see cli/main.py) — this is a local
desktop app, not a service meant to be exposed on the network.
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from local_ai_workspace.core.approval import ApprovalPolicy
from local_ai_workspace.core.chat import ChatOrchestrator
from local_ai_workspace.core.compaction import get_summary
from local_ai_workspace.core.models import MCPServerConfig, ProjectMeta, ProviderConfig
from local_ai_workspace.mcp.manager import MCPManager
from local_ai_workspace.providers.capabilities import detect_capabilities
from local_ai_workspace.providers.client import make_client
from local_ai_workspace.storage import conversation_store
from local_ai_workspace.storage.backup import create_backup, restore_backup
from local_ai_workspace.storage.mcp_store import (
    delete_mcp_server,
    get_mcp_server,
    list_mcp_servers,
    save_mcp_server,
)
from local_ai_workspace.storage.paths import (
    conversations_dir,
    mcp_servers_path,
    projects_dir,
    providers_path,
    secret_key_path,
    secrets_path,
)
from local_ai_workspace.storage.provider_store import (
    delete_provider,
    get_provider,
    list_providers,
    save_provider,
    seed_default_providers,
)
from local_ai_workspace.storage.secrets import delete_secret, get_secret, set_secret
from local_ai_workspace.storage.settings_store import (
    get_approval_policy,
    save_approval_policy,
)

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


class TestConnectionResult(BaseModel):
    ok: bool
    latency_ms: float | None = None
    error: str | None = None
    model: str | None = None


class ChatBody(BaseModel):
    content: str


class RestoreBackupBody(BaseModel):
    path: str


class ImportConversationBody(BaseModel):
    meta: dict
    messages: list[dict] = []


class WipeBody(BaseModel):
    confirm: bool = False


class QuickAddMCPServerBody(BaseModel):
    name: str
    url: str
    description: str | None = None


class ToggleToolBody(BaseModel):
    tool_name: str
    enabled: bool


class ResumeToolApprovalBody(BaseModel):
    approved: bool


ALLOWED_ORIGINS = {
    "http://127.0.0.1",
    "http://localhost",
    "https://127.0.0.1",
    "https://localhost",
}


def _origin_is_allowed(origin: str) -> bool:
    """True if `origin` is an http(s) origin on 127.0.0.1 or localhost
    (any port). Used both by the CSRF-style origin check middleware and to
    build the CORS allow-list."""
    try:
        from urllib.parse import urlparse

        parsed = urlparse(origin)
    except Exception:  # noqa: BLE001
        return False
    if parsed.scheme not in ("http", "https"):
        return False
    return parsed.hostname in ("127.0.0.1", "localhost")


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

    # ---------- Origin / CSRF protection ----------
    # Reject any non-GET request whose Origin header (when present) isn't an
    # http(s) origin on 127.0.0.1/localhost. Prevents a malicious website
    # from using the user's browser (with its ambient trust / cookies) to
    # make state-changing requests against this local API.
    @app.middleware("http")
    async def reject_cross_origin_mutations(request: Request, call_next):
        if request.method != "GET":
            origin = request.headers.get("origin")
            if origin and not _origin_is_allowed(origin):
                return JSONResponse(
                    status_code=403,
                    content={"detail": f"Cross-origin request blocked (Origin: {origin})"},
                )
        return await call_next(request)

    # Explicit CORS allow-list -- no wildcard. Only the local UI (served from
    # 127.0.0.1/localhost at any port) is allowed to make cross-origin calls.
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https?://(127\.0\.0\.1|localhost)(:\d+)?$",
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["*"],
    )

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

    @app.get("/api/conversations/{conversation_id}/export")
    def api_export_conversation(conversation_id: str):
        data = conversation_store.export_conversation(conversation_id)
        if data is None:
            raise HTTPException(404, "Conversation not found")
        return data

    @app.post("/api/conversations/import")
    def api_import_conversation(body: ImportConversationBody):
        new_meta = conversation_store.import_conversation(body.model_dump())
        return new_meta.model_dump()

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

    @app.post("/api/conversations/{conversation_id}/tool_calls/{tool_call_id}/resume")
    async def api_resume_tool_approval(conversation_id: str, tool_call_id: str, body: ResumeToolApprovalBody):
        """Resume an agent loop that paused on an approval_required event
        for `tool_call_id`: execute it (approved=true) or skip it
        (approved=false), then continue the loop. Streams the same SSE
        event shapes as /chat."""
        orchestrator: ChatOrchestrator = app.state.orchestrator

        async def event_stream():
            async for event in orchestrator.resume_turn(conversation_id, tool_call_id, body.approved):
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

    @app.post("/api/providers/{provider_id}/detect_capabilities")
    def api_detect_provider_capabilities(provider_id: str):
        provider = get_provider(provider_id)
        if provider is None:
            raise HTTPException(404, "Provider not found")
        capabilities = detect_capabilities(provider)
        updated = provider.model_copy(update={"capabilities": capabilities})
        saved = save_provider(updated)
        return saved.model_dump()

    @app.post("/api/providers/{provider_id}/test_connection")
    async def api_test_provider_connection(provider_id: str) -> TestConnectionResult:
        """Send a minimal, cheap completion request through the provider's
        configured client and report whether it actually works. Distinguishes
        invalid-auth, network, timeout, and unsupported-model failures so the
        UI can show something more useful than a generic "failed"."""
        import time as _time

        import httpx as _httpx

        provider = get_provider(provider_id)
        if provider is None:
            raise HTTPException(404, "Provider not found")

        model = provider.default_model or (provider.models[0] if provider.models else None)
        if not model:
            return TestConnectionResult(ok=False, error="No model configured for this provider")

        api_key = get_secret(provider.api_key_ref) if provider.api_key_ref else None
        client = make_client(provider.kind, provider.base_url, api_key, allow_local=provider.allow_local)

        probe_messages = [{"role": "user", "content": "ping"}]
        start = _time.monotonic()
        try:
            async for event in client.stream(probe_messages, model, tools=None):
                if event.type == "error":
                    err = event.error or ""
                    latency_ms = (_time.monotonic() - start) * 1000
                    if "401" in err or "403" in err:
                        return TestConnectionResult(ok=False, latency_ms=latency_ms, error=f"Invalid API key: {err}")
                    if "404" in err or "400" in err:
                        return TestConnectionResult(
                            ok=False,
                            latency_ms=latency_ms,
                            error=f"Unsupported model or bad request: {err}",
                            model=model,
                        )
                    return TestConnectionResult(ok=False, latency_ms=latency_ms, error=err)
                if event.type in ("text_delta", "done"):
                    latency_ms = (_time.monotonic() - start) * 1000
                    return TestConnectionResult(ok=True, latency_ms=latency_ms, model=model)
            latency_ms = (_time.monotonic() - start) * 1000
            return TestConnectionResult(ok=True, latency_ms=latency_ms, model=model)
        except _httpx.TimeoutException as e:
            latency_ms = (_time.monotonic() - start) * 1000
            return TestConnectionResult(ok=False, latency_ms=latency_ms, error=f"Timeout: {e}")
        except _httpx.HTTPError as e:
            latency_ms = (_time.monotonic() - start) * 1000
            return TestConnectionResult(ok=False, latency_ms=latency_ms, error=f"Network error: {e}")
        except Exception as e:  # pragma: no cover - defensive catch-all
            latency_ms = (_time.monotonic() - start) * 1000
            return TestConnectionResult(ok=False, latency_ms=latency_ms, error=str(e))

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

    @app.post("/api/mcp/servers/quick_add")
    async def api_quick_add_mcp_server(body: QuickAddMCPServerBody):
        """Quick-add flow: caller supplies only name/url/description. We
        auto-detect transport (streamable_http first, sse fallback) and
        auto-detect whether OAuth is required via well-known metadata
        discovery -- no manual checkbox needed. oauth_autodetect_failed is
        true only when discovery genuinely failed, signaling the client UI
        to fall back to asking the user to specify OAuth manually."""
        try:
            updated, oauth_detection_failed = await app.state.mcp_manager.quick_add(
                body.name, body.url, body.description
            )
        except RuntimeError as e:
            raise HTTPException(502, str(e)) from e
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return {
            "server": updated.model_dump(),
            "oauth_autodetect_failed": oauth_detection_failed,
        }

    @app.post("/api/mcp/servers/{server_id}/reauthorize")
    async def api_reauthorize_mcp_server(server_id: str):
        """Clear the stored OAuth token and re-run the OAuth flow from
        scratch (drives a fresh browser-based authorization on connect)."""
        try:
            updated = await app.state.mcp_manager.reauthorize(server_id)
        except ValueError as e:
            raise HTTPException(404, str(e)) from e
        return updated.model_dump()

    @app.post("/api/mcp/servers/{server_id}/revoke_token")
    async def api_revoke_mcp_token(server_id: str):
        """Delete the stored OAuth token (and any client registration) for
        this server without removing the server config itself."""
        updated = await app.state.mcp_manager.revoke_oauth_token(server_id)
        if updated is None:
            raise HTTPException(404, "MCP server not found")
        return updated.model_dump()

    @app.put("/api/mcp/servers/{server_id}/tools/toggle")
    async def api_toggle_mcp_tool(server_id: str, body: ToggleToolBody):
        """Enable/disable a single tool (server-local name, not qualified)
        on this server. Disabled tools are skipped by
        MCPManager.get_tools_openai_format and refused by call_tool."""
        try:
            updated = app.state.mcp_manager.set_tool_enabled(server_id, body.tool_name, body.enabled)
        except ValueError as e:
            raise HTTPException(404, str(e)) from e
        return updated.model_dump()

    @app.get("/api/mcp/tools")
    def api_list_mcp_tools():
        return app.state.mcp_manager.get_tools_openai_format()

    @app.get("/api/health")
    def api_health():
        return {"status": "ok"}

    # ---------- Approval policy (Feature B) ----------

    @app.get("/api/settings/approval_policy")
    def api_get_approval_policy():
        return get_approval_policy().model_dump()

    @app.put("/api/settings/approval_policy")
    def api_put_approval_policy(body: ApprovalPolicy):
        return save_approval_policy(body).model_dump()

    # ---------- Context compaction (Feature C) ----------

    @app.post("/api/conversations/{conversation_id}/compact")
    async def api_trigger_compaction(conversation_id: str):
        """Manually trigger compaction for a conversation. Uses the
        conversation's configured provider/model to generate the summary."""
        from local_ai_workspace.core.compaction import compact

        meta = conversation_store.get_conversation_meta(conversation_id)
        if meta is None:
            raise HTTPException(404, "Conversation not found")
        if not meta.provider or not meta.model:
            raise HTTPException(400, "Conversation has no provider/model configured")
        provider_cfg = get_provider(meta.provider)
        if provider_cfg is None:
            raise HTTPException(400, "Provider not configured")
        api_key = get_secret(provider_cfg.api_key_ref) if provider_cfg.api_key_ref else None
        client = make_client(provider_cfg.kind, provider_cfg.base_url, api_key, allow_local=provider_cfg.allow_local)
        summary = await compact(conversation_id, client, meta.model)
        return summary.model_dump()

    @app.get("/api/conversations/{conversation_id}/summary")
    def api_get_conversation_summary(conversation_id: str):
        """View the current persisted structured summary for a
        conversation, if compaction has ever run for it."""
        summary = get_summary(conversation_id)
        if summary is None:
            raise HTTPException(404, "No summary exists for this conversation yet")
        return summary.model_dump()

    @app.get("/api/conversations/{conversation_id}/raw_messages")
    def api_get_raw_messages(conversation_id: str):
        """The full original message list for this conversation, straight
        from messages.jsonl -- proof that compaction never destructively
        drops anything from disk, regardless of what's been summarized."""
        meta = conversation_store.get_conversation_meta(conversation_id)
        if meta is None:
            raise HTTPException(404, "Conversation not found")
        messages = conversation_store.get_messages(conversation_id)
        return [m.model_dump() for m in messages]

    # ---------- Backup / restore ----------

    @app.post("/api/admin/backup")
    def api_create_backup():
        path = create_backup()
        return {"path": str(path)}

    @app.post("/api/admin/restore")
    async def api_restore_backup(
        path: str | None = None,
        file: UploadFile | None = File(None),  # noqa: B008 - FastAPI's own idiom: File()/Depends() must live in the signature default to be recognized as a dependency
    ):
        """Restore from a backup. Either pass `path` (a path to an existing
        backup archive on disk) as a query/form param, or upload the backup
        zip as `file`."""
        if file is not None:
            import tempfile

            with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
                tmp.write(await file.read())
                tmp_path = tmp.name
            try:
                restored = restore_backup(tmp_path)
            except (FileNotFoundError, ValueError) as e:
                raise HTTPException(400, str(e)) from e
            finally:
                import os as _os

                _os.unlink(tmp_path)
            return {"ok": True, "files_restored": restored}

        if path is None:
            raise HTTPException(400, "Either 'path' or an uploaded 'file' is required")
        try:
            restored = restore_backup(path)
        except FileNotFoundError as e:
            raise HTTPException(404, str(e)) from e
        except ValueError as e:
            raise HTTPException(400, str(e)) from e
        return {"ok": True, "files_restored": restored}

    # ---------- Admin: clear all data ----------

    @app.post("/api/admin/wipe")
    def api_wipe_all_data(body: WipeBody):
        """Delete all conversations, projects, providers, MCP server configs,
        and secrets. Requires explicit confirm=true in the request body --
        never deletes without it."""
        if not body.confirm:
            raise HTTPException(400, "Refusing to wipe data without confirm=true")

        import shutil as _shutil

        if conversations_dir().exists():
            _shutil.rmtree(conversations_dir())
            conversations_dir()  # recreate empty
        if projects_dir().exists():
            _shutil.rmtree(projects_dir())
            projects_dir()
        if providers_path().exists():
            providers_path().unlink()
        if mcp_servers_path().exists():
            mcp_servers_path().unlink()
        if secrets_path().exists():
            secrets_path().unlink()
        if secret_key_path().exists():
            secret_key_path().unlink()
        try:
            from local_ai_workspace.storage import keyring_backend as _keyring_backend

            _keyring_backend.delete_key()
        except Exception:  # noqa: BLE001 - best-effort cleanup only
            pass

        return {"ok": True}

    # ---------- Frontend static files (production) ----------

    static_dir = Path(__file__).resolve().parent.parent / "static"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="frontend")

    return app
