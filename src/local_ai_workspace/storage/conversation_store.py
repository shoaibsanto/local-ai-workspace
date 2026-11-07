"""Conversation persistence: filesystem-backed, no database.

Each conversation is a directory:
    conversations/<id>/meta.json       ConversationMeta
    conversations/<id>/messages.jsonl  append-only Message log

Reading a conversation's messages means reading the JSONL file top to
bottom. Editing/deleting a message rewrites the file atomically (rare
operation, conversations are small enough this is fine without an index).
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path

from local_ai_workspace.core.models import ConversationMeta, Message
from local_ai_workspace.storage.json_store import (
    append_jsonl,
    read_json,
    read_jsonl,
    rewrite_jsonl_atomic,
    write_json_atomic,
)
from local_ai_workspace.storage.paths import conversation_dir, conversations_dir


def _meta_path(conversation_id: str) -> Path:
    return conversation_dir(conversation_id) / "meta.json"


def _messages_path(conversation_id: str) -> Path:
    return conversation_dir(conversation_id) / "messages.jsonl"


def create_conversation(
    title: str = "New Conversation",
    project_id: str | None = None,
    model: str | None = None,
    provider: str | None = None,
) -> ConversationMeta:
    meta = ConversationMeta(title=title, project_id=project_id, model=model, provider=provider)
    write_json_atomic(_meta_path(meta.id), meta.model_dump())
    return meta


def get_conversation_meta(conversation_id: str) -> ConversationMeta | None:
    data = read_json(_meta_path(conversation_id))
    if data is None:
        return None
    return ConversationMeta(**data)


def update_conversation_meta(conversation_id: str, **updates) -> ConversationMeta | None:
    meta = get_conversation_meta(conversation_id)
    if meta is None:
        return None
    updated = meta.model_copy(update={**updates, "updated_at": time.time()})
    write_json_atomic(_meta_path(conversation_id), updated.model_dump())
    return updated


def list_conversations(project_id: str | None = None) -> list[ConversationMeta]:
    results = []
    for d in conversations_dir().iterdir():
        if not d.is_dir():
            continue
        data = read_json(d / "meta.json")
        if data is None:
            continue
        meta = ConversationMeta(**data)
        if project_id is not None and meta.project_id != project_id:
            continue
        results.append(meta)
    results.sort(key=lambda m: m.updated_at, reverse=True)
    return results


def delete_conversation(conversation_id: str) -> bool:
    d = conversation_dir(conversation_id)
    if not d.exists():
        return False
    shutil.rmtree(d)
    return True


def add_message(conversation_id: str, message: Message) -> Message:
    append_jsonl(_messages_path(conversation_id), message.model_dump())
    meta = get_conversation_meta(conversation_id)
    if meta is not None:
        update_conversation_meta(conversation_id, message_count=meta.message_count + 1)
    return message


def get_messages(conversation_id: str) -> list[Message]:
    records = read_jsonl(_messages_path(conversation_id))
    return [Message(**r) for r in records]


def replace_messages(conversation_id: str, messages: list[Message]) -> None:
    """Used for edit-and-resend (truncate history) and regenerate."""
    rewrite_jsonl_atomic(_messages_path(conversation_id), [m.model_dump() for m in messages])
    update_conversation_meta(conversation_id, message_count=len(messages))


def search_conversations(query: str) -> list[ConversationMeta]:
    query_lower = query.lower()
    matches = []
    for meta in list_conversations():
        if query_lower in meta.title.lower():
            matches.append(meta)
            continue
        messages = get_messages(meta.id)
        if any(query_lower in m.content.lower() for m in messages):
            matches.append(meta)
    return matches


def export_conversation(conversation_id: str) -> dict | None:
    """Return a single JSON-serializable document containing a conversation's
    meta and full message history, or None if it doesn't exist. Suitable for
    writing straight to a file or returning from an API endpoint."""
    meta = get_conversation_meta(conversation_id)
    if meta is None:
        return None
    messages = get_messages(conversation_id)
    return {
        "meta": meta.model_dump(),
        "messages": [m.model_dump() for m in messages],
    }


def import_conversation(data: dict) -> ConversationMeta:
    """Create a brand-new conversation from a previously exported document.

    Always allocates a new conversation id (and new message ids) -- an
    import NEVER overwrites an existing conversation, even if the source
    document's id happens to collide with one already on disk.
    """
    meta_data = dict(data.get("meta") or {})
    # Drop the original id/timestamps so defaults mint fresh ones.
    meta_data.pop("id", None)
    meta_data.pop("created_at", None)
    meta_data.pop("updated_at", None)
    meta_data.pop("message_count", None)

    new_meta = ConversationMeta(
        title=meta_data.get("title", "Imported Conversation"),
        project_id=meta_data.get("project_id"),
        model=meta_data.get("model"),
        provider=meta_data.get("provider"),
    )
    if meta_data.get("pinned"):
        new_meta = new_meta.model_copy(update={"pinned": True})

    write_json_atomic(_meta_path(new_meta.id), new_meta.model_dump())

    raw_messages = data.get("messages") or []
    imported_messages: list[Message] = []
    for raw in raw_messages:
        raw = dict(raw)
        raw.pop("id", None)  # mint a fresh message id too
        imported_messages.append(Message(**raw))

    if imported_messages:
        rewrite_jsonl_atomic(_messages_path(new_meta.id), [m.model_dump() for m in imported_messages])
        updated = update_conversation_meta(new_meta.id, message_count=len(imported_messages))
        if updated is not None:
            new_meta = updated

    return new_meta
