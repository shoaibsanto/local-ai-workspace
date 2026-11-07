"""Chat orchestration: turns a conversation + user message into a streamed
assistant response, running any MCP tool calls the model requests in a loop
(classic agent loop) and persisting everything via the conversation store.

Context management: a simple, honest token-budget truncation. We estimate
tokens with a 4-chars-per-token heuristic (good enough without pulling in a
model-specific tokenizer per provider) and drop the oldest non-system
messages when a conversation would exceed the configured budget, always
keeping the system prompt and the most recent exchange intact. This is
intentionally simple over clever — a wrong compaction silently corrupting
context is worse than a slightly early truncation.
"""
from __future__ import annotations

import logging
from typing import Any, AsyncIterator

from local_ai_workspace.core.models import Message, ToolCall, ToolResult
from local_ai_workspace.mcp.manager import MCPManager
from local_ai_workspace.providers.client import StreamEvent, make_client
from local_ai_workspace.storage import conversation_store
from local_ai_workspace.storage.provider_store import get_provider
from local_ai_workspace.storage.secrets import get_secret

logger = logging.getLogger(__name__)

MAX_CONTEXT_CHARS = 100_000  # ~25k tokens at the 4 chars/token heuristic
MAX_TOOL_ITERATIONS = 8


def _estimate_chars(messages: list[dict[str, Any]]) -> int:
    return sum(len(m.get("content") or "") for m in messages)


def _compact_messages(
    messages: list[dict[str, Any]], budget_chars: int = MAX_CONTEXT_CHARS
) -> list[dict[str, Any]]:
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
                system[0]["content"]
                + "\n\n[Note: earlier conversation history was truncated to fit the "
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
                                "arguments": __import__("json").dumps(tc.arguments),
                            },
                        }
                        for tc in m.tool_calls
                    ],
                }
            )
        else:
            wire.append({"role": m.role, "content": m.content})
    return wire


class ChatOrchestrator:
    def __init__(self, mcp_manager: MCPManager):
        self.mcp_manager = mcp_manager

    async def run_turn(
        self, conversation_id: str, user_content: str
    ) -> AsyncIterator[dict[str, Any]]:
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
        client = make_client(provider_cfg.kind, provider_cfg.base_url, api_key)

        user_msg = Message(role="user", content=user_content)
        conversation_store.add_message(conversation_id, user_msg)
        yield {"type": "user_message", "message": user_msg.model_dump()}

        history = conversation_store.get_messages(conversation_id)
        wire_messages = _messages_to_wire_format(history)
        wire_messages = _compact_messages(wire_messages)

        tools = self.mcp_manager.get_tools_openai_format()

        for _ in range(MAX_TOOL_ITERATIONS):
            assistant_text = ""
            tool_calls: list[ToolCall] = []
            error: str | None = None

            async for event in client.stream(wire_messages, meta.model, tools=tools or None):
                event = event  # type: StreamEvent
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
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.name,
                                "arguments": __import__("json").dumps(tc.arguments),
                            },
                        }
                        for tc in tool_calls
                    ]
                    if tool_calls
                    else None,
                }
            )

            if not tool_calls:
                break  # model is done, no more tools requested

            tool_results: list[ToolResult] = []
            for tc in tool_calls:
                yield {"type": "tool_executing", "tool_call": tc.model_dump()}
                result_text = await self.mcp_manager.call_tool(tc.name, tc.arguments)
                tr = ToolResult(tool_call_id=tc.id, name=tc.name, content=result_text)
                tool_results.append(tr)
                wire_messages.append(
                    {"role": "tool", "tool_call_id": tc.id, "content": result_text}
                )
                yield {"type": "tool_result", "tool_result": tr.model_dump()}

            tool_msg = Message(role="tool", content="", tool_results=tool_results)
            conversation_store.add_message(conversation_id, tool_msg)
            # loop again so the model can see tool results and respond

        yield {"type": "turn_complete"}
