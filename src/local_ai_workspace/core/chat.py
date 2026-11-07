"""Chat orchestration: turns a conversation + user message into a streamed
assistant response, running any MCP tool calls the model requests in a loop
(classic agent loop) and persisting everything via the conversation store.

Context management: two layers, not a replacement of one by the other.

1. (Pre-existing, kept as the safety net) A simple, honest char-count
   token-budget truncation (`_compact_messages` / `MAX_CONTEXT_CHARS`): we
   estimate tokens with a 4-chars-per-token heuristic and drop the oldest
   non-system messages when a conversation would exceed the configured
   budget, always keeping the system prompt and the most recent exchange
   intact. Intentionally simple over clever.
2. (New, core/compaction.py) When the conversation is large enough that
   `should_compact` trips (default: raw history >= 75% of the configured
   context window), we build the prompt from a persisted structured summary
   plus only the most recent N raw messages, instead of the full raw
   history. The cheap truncation above still runs on *that* result as a
   final safety net (e.g. if the summary itself ballooned, or one recent
   message is huge) -- it's layered on top, not replaced.

Tool approval: before executing any MCP tool call, core/approval.py's
ApprovalPolicy is consulted. "ask" decisions pause the agent loop entirely
and persist state to pending_approvals.json in the conversation directory
(core/approval.py's save_pending_approvals) so a page refresh doesn't lose
track of what's awaiting a decision; `resume_turn` continues from there.

Tool results fed back to the model are wrapped with a fixed boundary marker
(core/approval.py's wrap_untrusted_tool_output) since MCP tool output is
untrusted, model-influenceable content, not a privileged instruction
source. This is a mitigation, not a guarantee -- see that module's
docstring.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from local_ai_workspace.core.approval import (
    PendingApprovalState,
    PendingToolCall,
    classify_tool_risk,
    clear_pending_approvals,
    load_pending_approvals,
    save_pending_approvals,
    wrap_untrusted_tool_output,
)
from local_ai_workspace.core.models import Message, ToolCall, ToolResult
from local_ai_workspace.mcp.manager import MCPManager
from local_ai_workspace.providers.client import make_client
from local_ai_workspace.storage import conversation_store
from local_ai_workspace.storage.mcp_store import list_mcp_servers
from local_ai_workspace.storage.provider_store import get_provider
from local_ai_workspace.storage.secrets import get_secret
from local_ai_workspace.storage.settings_store import get_effective_policy_for_server, get_settings

logger = logging.getLogger(__name__)

MAX_CONTEXT_CHARS = 100_000  # ~25k tokens at the 4 chars/token heuristic
MAX_TOOL_ITERATIONS = 8
CHARS_PER_TOKEN = 4  # shared heuristic -- see core/compaction.py's estimate_tokens
DEFAULT_CONTEXT_WINDOW_TOKENS = 25_000  # ~ MAX_CONTEXT_CHARS / CHARS_PER_TOKEN
DEFAULT_COMPACTION_RECENT_MESSAGES = 10  # N most recent raw messages kept verbatim


def _estimate_chars(messages: list[dict[str, Any]]) -> int:
    return sum(len(m.get("content") or "") for m in messages)


def _compact_messages(messages: list[dict[str, Any]], budget_chars: int = MAX_CONTEXT_CHARS) -> list[dict[str, Any]]:
    if _estimate_chars(messages) <= budget_chars:
        return messages

    system = [m for m in messages if m["role"] == "system"]
    rest = [m for m in messages if m["role"] != "system"]

    # Keep dropping from the front of `rest` (oldest first) until it fits,
    # always preserving the last 2 messages (the live exchange).
    while len(rest) > 2 and _estimate_chars(system + rest) > budget_chars:
        rest.pop(0)

    if system:
        notice = {
            "role": "system",
            "content": (
                system[0]["content"] + "\n\n[Note: earlier conversation history was truncated to fit the "
                "context window.]"
            ),
        }
        system = [notice] + system[1:]

    return system + rest


def _messages_to_wire_format(messages: list[Message]) -> list[dict[str, Any]]:
    wire: list[dict[str, Any]] = []
    for m in messages:
        if m.role == "tool":
            for tr in m.tool_results:
                wire.append(
                    {
                        "role": "tool",
                        "tool_call_id": tr.tool_call_id,
                        "content": tr.content,
                    }
                )
        elif m.tool_calls:
            wire.append(
                {
                    "role": "assistant",
                    "content": m.content or None,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": json.dumps(tc.arguments),
                            },
                        }
                        for tc in m.tool_calls
                    ],
                }
            )
        else:
            wire.append({"role": m.role, "content": m.content})
    return wire


def _tool_calls_to_wire(tool_calls: list[ToolCall]) -> list[dict[str, Any]]:
    return [
        {
            "id": tc.id,
            "type": "function",
            "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)},
        }
        for tc in tool_calls
    ]


class ChatOrchestrator:
    def __init__(self, mcp_manager: MCPManager):
        self.mcp_manager = mcp_manager

    # ---------- shared helpers ----------

    def _server_name_to_id(self) -> dict[str, str]:
        return {s.name: s.id for s in list_mcp_servers()}

    def _tool_description_map(self, tools: list[dict[str, Any]]) -> dict[str, str]:
        return {t["function"]["name"]: t["function"].get("description", "") for t in tools}

    def _build_wire_messages(self, conversation_id: str, provider_cfg) -> list[dict[str, Any]]:
        """Build the wire-format prompt messages, applying compaction (if
        the conversation is large enough to warrant it) and then the cheap
        char-count safety net on top either way."""
        from local_ai_workspace.core.compaction import build_prompt_with_summary, should_compact

        history = conversation_store.get_messages(conversation_id)
        wire_full = _messages_to_wire_format(history)

        settings = get_settings()
        context_window = provider_cfg.context_window or DEFAULT_CONTEXT_WINDOW_TOKENS
        threshold = settings.compaction_threshold
        recent_n = settings.compaction_recent_messages

        if should_compact(wire_full, context_window, threshold):
            wire_messages = build_prompt_with_summary(conversation_id, recent_n)
        else:
            wire_messages = wire_full

        return _compact_messages(wire_messages)

    async def trigger_compaction(self, conversation_id: str, llm_client, model_name: str):
        """Manually trigger compaction (also used by the API endpoint)."""
        from local_ai_workspace.core.compaction import compact

        return await compact(conversation_id, llm_client, model_name)

    # ---------- main entry points ----------

    async def run_turn(self, conversation_id: str, user_content: str) -> AsyncIterator[dict[str, Any]]:
        """Yields SSE-ready dict events: {type, ...}. Persists the user
        message immediately and the assistant message(s) as they complete."""
        meta = conversation_store.get_conversation_meta(conversation_id)
        if meta is None:
            yield {"type": "error", "error": "Conversation not found"}
            return
        if not meta.provider or not meta.model:
            yield {"type": "error", "error": "Conversation has no provider/model configured"}
            return

        provider_cfg = get_provider(meta.provider)
        if provider_cfg is None or not provider_cfg.enabled:
            yield {"type": "error", "error": "Provider not configured or disabled"}
            return

        api_key = get_secret(provider_cfg.api_key_ref) if provider_cfg.api_key_ref else None
        client = make_client(provider_cfg.kind, provider_cfg.base_url, api_key, allow_local=provider_cfg.allow_local)

        user_msg = Message(role="user", content=user_content)
        conversation_store.add_message(conversation_id, user_msg)
        yield {"type": "user_message", "message": user_msg.model_dump()}

        wire_messages = self._build_wire_messages(conversation_id, provider_cfg)

        tool_calling_supported = provider_cfg.capabilities.get("tool_calling", True) is not False

        async for event in self._agent_loop(
            conversation_id,
            meta,
            provider_cfg,
            client,
            wire_messages,
            tool_calling_supported,
            MAX_TOOL_ITERATIONS,
        ):
            yield event

    async def resume_turn(
        self, conversation_id: str, tool_call_id: str, approved: bool
    ) -> AsyncIterator[dict[str, Any]]:
        """Resume an agent loop paused on an approval_required event for
        `tool_call_id`. If approved, executes that specific tool call; if
        not, skips it with a clear "denied by user" result. Either way,
        continues processing the rest of the paused queue (which may itself
        pause again on another "ask" decision) and then continues the
        model-call loop exactly as if the pause never happened."""
        state = load_pending_approvals(conversation_id)
        if state is None:
            yield {"type": "error", "error": "No pending approval for this conversation"}
            return
        if not state.queue or state.queue[0].tool_call.get("id") != tool_call_id:
            yield {
                "type": "error",
                "error": f"tool_call_id {tool_call_id!r} does not match the pending approval",
            }
            return

        meta = conversation_store.get_conversation_meta(conversation_id)
        if meta is None:
            yield {"type": "error", "error": "Conversation not found"}
            return
        if meta.provider is None:
            yield {"type": "error", "error": "Conversation has no provider configured"}
            return
        provider_cfg = get_provider(meta.provider)
        if provider_cfg is None:
            yield {"type": "error", "error": "Provider not configured or disabled"}
            return
        api_key = get_secret(provider_cfg.api_key_ref) if provider_cfg.api_key_ref else None
        client = make_client(provider_cfg.kind, provider_cfg.base_url, api_key, allow_local=provider_cfg.allow_local)

        pending = state.queue[0]
        tc = ToolCall(**pending.tool_call)

        tool_results: list[ToolResult] = [ToolResult(**r) for r in state.results_so_far]
        wire_messages = self._build_wire_messages(conversation_id, provider_cfg)
        # Re-append the assistant turn that requested these tool calls, plus
        # any already-resolved tool results from this batch, mirroring what
        # the original (paused) loop had already appended before pausing.
        all_tool_calls = [ToolCall(**q.tool_call) for q in state.queue]
        wire_messages.append(
            {
                "role": "assistant",
                "content": state.assistant_text or None,
                "tool_calls": _tool_calls_to_wire(all_tool_calls),
            }
        )
        for tr in tool_results:
            wire_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tr.tool_call_id,
                    "content": wrap_untrusted_tool_output(tr.content),
                }
            )

        if approved:
            yield {"type": "tool_executing", "tool_call": tc.model_dump()}
            result_text = await self.mcp_manager.call_tool(tc.name, tc.arguments)
        else:
            result_text = f"Tool call '{tc.name}' was not approved by the user and was skipped."
        tr = ToolResult(tool_call_id=tc.id, name=tc.name, content=result_text)
        tool_results.append(tr)
        wire_messages.append(
            {"role": "tool", "tool_call_id": tc.id, "content": wrap_untrusted_tool_output(result_text)}
        )
        yield {"type": "tool_result", "tool_result": tr.model_dump()}

        remaining_queue = state.queue[1:]
        tool_calling_supported = provider_cfg.capabilities.get("tool_calling", True) is not False

        paused = False
        if remaining_queue:
            async for event in self._process_queue(
                conversation_id,
                remaining_queue,
                tool_results,
                wire_messages,
                state.assistant_text,
                state.iterations_remaining,
            ):
                if event.get("type") == "__paused__":
                    paused = True
                else:
                    yield event

        if paused:
            return

        clear_pending_approvals(conversation_id)
        tool_msg = Message(role="tool", content="", tool_results=tool_results)
        conversation_store.add_message(conversation_id, tool_msg)

        async for event in self._agent_loop(
            conversation_id,
            meta,
            provider_cfg,
            client,
            wire_messages,
            tool_calling_supported,
            state.iterations_remaining,
        ):
            yield event

    # ---------- internals ----------

    async def _process_queue(
        self,
        conversation_id: str,
        queue: list[PendingToolCall],
        tool_results: list[ToolResult],
        wire_messages: list[dict[str, Any]],
        assistant_text: str,
        iterations_remaining: int,
    ) -> AsyncIterator[dict[str, Any]]:
        """Resolve a queue of not-yet-executed tool calls against the
        approval policy, executing/skipping/pausing as directed. Mutates
        `tool_results` and `wire_messages` in place. Yields a final
        {"type": "__paused__"} sentinel (never sent over SSE -- callers
        filter it) if it had to pause partway through."""
        tools = self.mcp_manager.get_tools_openai_format()
        descriptions = self._tool_description_map(tools)
        server_ids = self._server_name_to_id()

        for i, pending in enumerate(queue):
            tc = ToolCall(**pending.tool_call)
            server_name = tc.name.split("__", 1)[0] if "__" in tc.name else None
            server_id = server_ids.get(server_name) if server_name else None
            risk = classify_tool_risk(tc.name, descriptions.get(tc.name, ""))
            policy = get_effective_policy_for_server(server_id)
            decision = policy.decide(tc.name, risk)

            if decision == "deny":
                result_text = f"Tool call denied by approval policy: {tc.name}"
                tr = ToolResult(tool_call_id=tc.id, name=tc.name, content=result_text)
                tool_results.append(tr)
                wire_messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": wrap_untrusted_tool_output(result_text),
                    }
                )
                yield {"type": "tool_result", "tool_result": tr.model_dump()}
                continue

            if decision == "ask":
                state = PendingApprovalState(
                    conversation_id=conversation_id,
                    assistant_text=assistant_text,
                    queue=queue[i:],
                    results_so_far=[tr.model_dump() for tr in tool_results],
                    iterations_remaining=iterations_remaining,
                )
                save_pending_approvals(state)
                yield {
                    "type": "approval_required",
                    "tool_call": tc.model_dump(),
                    "server_name": server_name,
                    "risk": risk,
                }
                yield {"type": "__paused__"}
                return

            # allow
            yield {"type": "tool_executing", "tool_call": tc.model_dump()}
            result_text = await self.mcp_manager.call_tool(tc.name, tc.arguments)
            tr = ToolResult(tool_call_id=tc.id, name=tc.name, content=result_text)
            tool_results.append(tr)
            wire_messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": wrap_untrusted_tool_output(result_text),
                }
            )
            yield {"type": "tool_result", "tool_result": tr.model_dump()}

    async def _agent_loop(
        self,
        conversation_id: str,
        meta,
        provider_cfg,
        client,
        wire_messages: list[dict[str, Any]],
        tool_calling_supported: bool,
        iterations: int,
    ) -> AsyncIterator[dict[str, Any]]:
        tools = self.mcp_manager.get_tools_openai_format()
        effective_tools = tools if (tools and tool_calling_supported) else None

        for iteration in range(iterations):
            assistant_text = ""
            tool_calls: list[ToolCall] = []
            error: str | None = None

            async for event in client.stream(wire_messages, meta.model, tools=effective_tools):
                if event.type == "text_delta":
                    assistant_text += event.text or ""
                    yield {"type": "text_delta", "text": event.text}
                elif event.type == "tool_call" and event.tool_call:
                    tool_calls.append(event.tool_call)
                    yield {
                        "type": "tool_call_requested",
                        "tool_call": event.tool_call.model_dump(),
                    }
                elif event.type == "error":
                    error = event.error
                    yield {"type": "error", "error": event.error}
                elif event.type == "done":
                    pass

            if error:
                err_msg = Message(role="assistant", content=assistant_text, error=error)
                conversation_store.add_message(conversation_id, err_msg)
                yield {"type": "assistant_message", "message": err_msg.model_dump()}
                return

            assistant_msg = Message(
                role="assistant",
                content=assistant_text,
                tool_calls=tool_calls,
                model=meta.model,
                provider=meta.provider,
            )
            conversation_store.add_message(conversation_id, assistant_msg)
            yield {"type": "assistant_message", "message": assistant_msg.model_dump()}
            wire_messages.append(
                {
                    "role": "assistant",
                    "content": assistant_text or None,
                    "tool_calls": _tool_calls_to_wire(tool_calls) if tool_calls else None,
                }
            )

            if not tool_calls:
                break  # model is done, no more tools requested

            tool_results: list[ToolResult] = []
            queue = [PendingToolCall(tool_call=tc.model_dump(), server_name=None, risk="readonly") for tc in tool_calls]
            iterations_remaining = iterations - iteration - 1

            paused = False
            async for event in self._process_queue(
                conversation_id,
                queue,
                tool_results,
                wire_messages,
                assistant_text,
                iterations_remaining,
            ):
                if event.get("type") == "__paused__":
                    paused = True
                else:
                    yield event

            if paused:
                return  # agent loop pauses here; resume_turn picks it up later

            tool_msg = Message(role="tool", content="", tool_results=tool_results)
            conversation_store.add_message(conversation_id, tool_msg)
            # loop again so the model can see tool results and respond

        yield {"type": "turn_complete"}
