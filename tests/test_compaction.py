"""Tests for context compaction (core/compaction.py)."""

from __future__ import annotations

import json

import pytest

from local_ai_workspace.core.compaction import (
    ConversationSummary,
    compact,
    estimate_tokens,
    get_summary,
    should_compact,
)

# ---------- should_compact threshold logic ----------


def test_estimate_tokens_uses_shared_4_chars_per_token_heuristic():
    from local_ai_workspace.core.chat import CHARS_PER_TOKEN

    messages = [{"role": "user", "content": "x" * 40}]
    assert estimate_tokens(messages) == 40 // CHARS_PER_TOKEN


def test_should_compact_false_when_well_under_threshold():
    messages = [{"role": "user", "content": "short"}]
    assert should_compact(messages, context_window=10_000, threshold=0.75) is False


def test_should_compact_true_when_over_threshold():
    # 4 chars/token heuristic: 10_000 tokens * 4 chars = 40_000 chars needed
    # to hit 100%; use enough content to clear 75%.
    big_content = "x" * 35_000
    messages = [{"role": "user", "content": big_content}]
    assert should_compact(messages, context_window=10_000, threshold=0.75) is True


def test_should_compact_respects_custom_threshold():
    content = "x" * 8_000  # 2000 tokens against a 10_000 token window = 20%
    messages = [{"role": "user", "content": content}]
    assert should_compact(messages, context_window=10_000, threshold=0.75) is False
    assert should_compact(messages, context_window=10_000, threshold=0.1) is True


def test_should_compact_handles_zero_context_window():
    assert should_compact([{"role": "user", "content": "x"}], context_window=0) is False


# ---------- persistence: summary.md + context.json, messages.jsonl untouched ----------


@pytest.mark.asyncio
async def test_compact_writes_summary_files_without_touching_messages_jsonl(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_AI_WORKSPACE_HOME", str(tmp_path))

    from local_ai_workspace.core.models import Message
    from local_ai_workspace.storage import conversation_store
    from local_ai_workspace.storage.paths import conversation_dir

    meta = conversation_store.create_conversation(title="t", model="m", provider="p")
    conversation_store.add_message(meta.id, Message(role="user", content="Please remember X."))
    conversation_store.add_message(meta.id, Message(role="assistant", content="Noted: X."))

    messages_path = conversation_dir(meta.id) / "messages.jsonl"
    original_bytes = messages_path.read_bytes()

    fake_response = json.dumps(
        {
            "user_instructions": "Remember X",
            "important_facts": ["X is important"],
            "decisions_made": [],
            "project_state": "in progress",
            "completed_work": [],
            "pending_tasks": [],
            "tool_results_of_note": [],
        }
    )

    class FakeStreamEvent:
        def __init__(self, type, text=None, error=None):
            self.type = type
            self.text = text
            self.error = error

    class FakeClient:
        async def stream(self, messages, model, tools=None, temperature=1.0):
            yield FakeStreamEvent("text_delta", text=fake_response)
            yield FakeStreamEvent("done")

    summary = await compact(meta.id, FakeClient(), "fake-model")

    assert summary.user_instructions == "Remember X"
    assert "X is important" in summary.important_facts

    summary_md = conversation_dir(meta.id) / "summary.md"
    context_json = conversation_dir(meta.id) / "context.json"
    assert summary_md.exists()
    assert context_json.exists()
    assert "Remember X" in summary_md.read_text()

    # messages.jsonl must be byte-identical: nothing destructive happened.
    assert messages_path.read_bytes() == original_bytes

    # get_summary reads it back correctly
    reloaded = get_summary(meta.id)
    assert reloaded is not None
    assert reloaded.user_instructions == "Remember X"


# ---------- defensive parsing: malformed model output doesn't crash ----------


@pytest.mark.asyncio
async def test_compact_falls_back_gracefully_on_malformed_model_output(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_AI_WORKSPACE_HOME", str(tmp_path))

    from local_ai_workspace.core.models import Message
    from local_ai_workspace.storage import conversation_store
    from local_ai_workspace.storage.paths import conversation_dir

    meta = conversation_store.create_conversation(title="t", model="m", provider="p")
    conversation_store.add_message(meta.id, Message(role="user", content="hello"))
    messages_path = conversation_dir(meta.id) / "messages.jsonl"
    original_bytes = messages_path.read_bytes()

    class FakeStreamEvent:
        def __init__(self, type, text=None, error=None):
            self.type = type
            self.text = text
            self.error = error

    class FakeClient:
        async def stream(self, messages, model, tools=None, temperature=1.0):
            yield FakeStreamEvent("text_delta", text="this is not json at all, sorry")
            yield FakeStreamEvent("done")

    # Must not raise.
    summary = await compact(meta.id, FakeClient(), "fake-model")
    assert isinstance(summary, ConversationSummary)
    # No prior summary existed, so this is the fallback placeholder; no
    # context.json/summary.md should have been written for a failed parse.
    assert not (conversation_dir(meta.id) / "context.json").exists()
    assert messages_path.read_bytes() == original_bytes


@pytest.mark.asyncio
async def test_compact_keeps_old_summary_when_update_fails(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_AI_WORKSPACE_HOME", str(tmp_path))

    from local_ai_workspace.core.models import Message
    from local_ai_workspace.storage import conversation_store

    meta = conversation_store.create_conversation(title="t", model="m", provider="p")
    conversation_store.add_message(meta.id, Message(role="user", content="first"))

    class FakeStreamEvent:
        def __init__(self, type, text=None, error=None):
            self.type = type
            self.text = text
            self.error = error

    good_response = json.dumps(
        {
            "user_instructions": "keep this",
            "important_facts": [],
            "decisions_made": [],
            "project_state": "",
            "completed_work": [],
            "pending_tasks": [],
            "tool_results_of_note": [],
        }
    )

    class GoodClient:
        async def stream(self, messages, model, tools=None, temperature=1.0):
            yield FakeStreamEvent("text_delta", text=good_response)
            yield FakeStreamEvent("done")

    first_summary = await compact(meta.id, GoodClient(), "fake-model")
    assert first_summary.user_instructions == "keep this"

    conversation_store.add_message(meta.id, Message(role="user", content="second"))

    class BadClient:
        async def stream(self, messages, model, tools=None, temperature=1.0):
            yield FakeStreamEvent("error", error="simulated LLM failure")

    second_summary = await compact(meta.id, BadClient(), "fake-model")
    # Falls back to the OLD summary rather than crashing or losing data.
    assert second_summary.user_instructions == "keep this"


@pytest.mark.asyncio
async def test_compact_times_out_gracefully(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_AI_WORKSPACE_HOME", str(tmp_path))

    import asyncio

    from local_ai_workspace.core.models import Message
    from local_ai_workspace.storage import conversation_store

    meta = conversation_store.create_conversation(title="t", model="m", provider="p")
    conversation_store.add_message(meta.id, Message(role="user", content="hello"))

    class SlowClient:
        async def stream(self, messages, model, tools=None, temperature=1.0):
            await asyncio.sleep(5)
            yield None  # pragma: no cover - never reached

    summary = await compact(meta.id, SlowClient(), "fake-model", timeout=0.05)
    assert isinstance(summary, ConversationSummary)
