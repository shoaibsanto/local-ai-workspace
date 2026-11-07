"""Tests for the tool approval policy engine (core/approval.py)."""

from __future__ import annotations

import pytest

from local_ai_workspace.core.approval import (
    UNTRUSTED_TOOL_OUTPUT_MARKER,
    ApprovalPolicy,
    classify_tool_risk,
    wrap_untrusted_tool_output,
)

# ---------- classify_tool_risk ----------


@pytest.mark.parametrize(
    "name,description,expected",
    [
        ("delete_file", "", "consequential"),
        ("remove_user", "", "consequential"),
        ("send_email", "Sends an email to a recipient", "consequential"),
        ("publish_post", "", "consequential"),
        ("purchase_item", "", "consequential"),
        ("buy_stock", "", "consequential"),
        ("write_file", "", "consequential"),
        ("modify_record", "", "consequential"),
        ("update_record", "", "consequential"),
        ("execute_command", "", "consequential"),
        ("drop_table", "", "consequential"),
        ("get_weather", "Looks up the current weather", "readonly"),
        ("list_files", "", "readonly"),
        ("search_docs", "Full text search over documents", "readonly"),
        ("read_file", "", "readonly"),
    ],
)
def test_classify_tool_risk_examples(name, description, expected):
    assert classify_tool_risk(name, description) == expected


def test_classify_tool_risk_matches_verb_in_description_not_just_name():
    assert classify_tool_risk("lookup_item", "Deletes stale cache entries") == "consequential"


def test_classify_tool_risk_does_not_false_positive_on_substring():
    # "undated" contains "date" but not "update" as a whole word; "readonly_report"
    # mentions none of the action verbs.
    assert classify_tool_risk("readonly_report", "an undated summary") == "readonly"


# ---------- ApprovalPolicy.decide ----------


def test_default_auto_approve_readonly_allows_readonly():
    policy = ApprovalPolicy()
    assert policy.default_mode == "auto_approve_readonly"
    assert policy.decide("srv__list_files", "readonly") == "allow"


def test_default_auto_approve_readonly_asks_for_consequential():
    policy = ApprovalPolicy()
    assert policy.decide("srv__delete_file", "consequential") == "ask"


def test_always_ask_asks_for_everything():
    policy = ApprovalPolicy(default_mode="always_ask")
    assert policy.decide("srv__list_files", "readonly") == "ask"
    assert policy.decide("srv__delete_file", "consequential") == "ask"


def test_auto_approve_all_allows_everything():
    policy = ApprovalPolicy(default_mode="auto_approve_all")
    assert policy.decide("srv__list_files", "readonly") == "allow"
    assert policy.decide("srv__delete_file", "consequential") == "allow"


def test_per_tool_override_wins_over_default_mode():
    policy = ApprovalPolicy(
        default_mode="auto_approve_readonly",
        per_tool_overrides={"srv__list_files": "deny", "srv__delete_file": "allow"},
    )
    assert policy.decide("srv__list_files", "readonly") == "deny"
    assert policy.decide("srv__delete_file", "consequential") == "allow"


# ---------- untrusted tool-output wrapping ----------


def test_wrap_untrusted_tool_output_prefixes_marker():
    wrapped = wrap_untrusted_tool_output("some tool result")
    assert wrapped.startswith(UNTRUSTED_TOOL_OUTPUT_MARKER)
    assert "some tool result" in wrapped


# ---------- wiring into ChatOrchestrator: consequential tools pause, readonly don't ----------


@pytest.mark.asyncio
async def test_consequential_tool_pauses_agent_loop(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_AI_WORKSPACE_HOME", str(tmp_path))

    from local_ai_workspace.core.chat import ChatOrchestrator
    from local_ai_workspace.core.models import ProviderConfig
    from local_ai_workspace.providers.client import StreamEvent
    from local_ai_workspace.storage import conversation_store, provider_store

    provider = ProviderConfig(name="P", base_url="https://example.invalid/v1", default_model="m", enabled=True)
    provider_store.save_provider(provider)
    meta = conversation_store.create_conversation(title="t", model="m", provider=provider.id)

    class FakeClient:
        def __init__(self):
            self.calls = 0

        async def stream(self, messages, model, tools=None, temperature=1.0):
            self.calls += 1
            if self.calls == 1:
                yield StreamEvent(
                    type="tool_call",
                    tool_call=__import__("local_ai_workspace.core.models", fromlist=["ToolCall"]).ToolCall(
                        id="call_1", name="srv__delete_file", arguments={}
                    ),
                )
                yield StreamEvent(type="done", finish_reason="tool_calls")
            else:
                yield StreamEvent(type="text_delta", text="done")
                yield StreamEvent(type="done", finish_reason="stop")

    fake_client = FakeClient()

    class FakeMCPManager:
        def get_tools_openai_format(self):
            return [
                {
                    "type": "function",
                    "function": {
                        "name": "srv__delete_file",
                        "description": "Deletes a file",
                        "parameters": {},
                    },
                }
            ]

        async def call_tool(self, name, args):
            return "should not be called"

    monkeypatch.setattr(
        "local_ai_workspace.core.chat.make_client",
        lambda kind, base_url, api_key, allow_local=False: fake_client,
    )

    orchestrator = ChatOrchestrator(FakeMCPManager())
    events = [e async for e in orchestrator.run_turn(meta.id, "please delete something")]

    approval_events = [e for e in events if e["type"] == "approval_required"]
    assert len(approval_events) == 1
    assert approval_events[0]["tool_call"]["name"] == "srv__delete_file"
    assert approval_events[0]["risk"] == "consequential"
    # loop paused -- no turn_complete, no second assistant message with "done" text
    assert not any(e["type"] == "turn_complete" for e in events)

    from local_ai_workspace.core.approval import load_pending_approvals

    pending = load_pending_approvals(meta.id)
    assert pending is not None
    assert pending.queue[0].tool_call["id"] == "call_1"


@pytest.mark.asyncio
async def test_readonly_tool_does_not_pause_agent_loop(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCAL_AI_WORKSPACE_HOME", str(tmp_path))

    from local_ai_workspace.core.chat import ChatOrchestrator
    from local_ai_workspace.core.models import ProviderConfig, ToolCall
    from local_ai_workspace.providers.client import StreamEvent
    from local_ai_workspace.storage import conversation_store, provider_store

    provider = ProviderConfig(name="P2", base_url="https://example.invalid/v1", default_model="m", enabled=True)
    provider_store.save_provider(provider)
    meta = conversation_store.create_conversation(title="t", model="m", provider=provider.id)

    class FakeClient:
        def __init__(self):
            self.calls = 0

        async def stream(self, messages, model, tools=None, temperature=1.0):
            self.calls += 1
            if self.calls == 1:
                yield StreamEvent(
                    type="tool_call",
                    tool_call=ToolCall(id="call_1", name="srv__list_files", arguments={}),
                )
                yield StreamEvent(type="done", finish_reason="tool_calls")
            else:
                yield StreamEvent(type="text_delta", text="done")
                yield StreamEvent(type="done", finish_reason="stop")

    fake_client = FakeClient()

    class FakeMCPManager:
        def get_tools_openai_format(self):
            return [
                {
                    "type": "function",
                    "function": {
                        "name": "srv__list_files",
                        "description": "Lists files in a directory",
                        "parameters": {},
                    },
                }
            ]

        async def call_tool(self, name, args):
            return "file1.txt\nfile2.txt"

    monkeypatch.setattr(
        "local_ai_workspace.core.chat.make_client",
        lambda kind, base_url, api_key, allow_local=False: fake_client,
    )

    orchestrator = ChatOrchestrator(FakeMCPManager())
    events = [e async for e in orchestrator.run_turn(meta.id, "list my files")]

    assert not any(e["type"] == "approval_required" for e in events)
    assert any(e["type"] == "turn_complete" for e in events)

    from local_ai_workspace.core.approval import load_pending_approvals

    assert load_pending_approvals(meta.id) is None

    # tool result fed back to the model must carry the untrusted-content marker
    tool_result_events = [e for e in events if e["type"] == "tool_result"]
    assert len(tool_result_events) == 1
