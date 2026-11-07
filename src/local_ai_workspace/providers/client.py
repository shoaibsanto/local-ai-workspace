"""LLM provider client abstraction.

Two concrete clients today:
  - OpenAICompatibleClient: works for OpenRouter, Ollama, LM Studio, vLLM,
    any server speaking the OpenAI chat-completions wire format (the vast
    majority of "custom endpoint" providers in practice).
  - AnthropicClient: native Anthropic Messages API (different wire format,
    different streaming event shape).

Both expose the same async generator interface: stream(messages, model,
tools) -> yields StreamEvent. The chat orchestrator in core/chat.py only
talks to this interface, never to httpx directly, so adding a third
provider kind later means writing one new class.
"""
from __future__ import annotations

import json
from typing import Any, AsyncIterator, Literal

import httpx
from pydantic import BaseModel

from local_ai_workspace.core.models import ToolCall
from local_ai_workspace.core.ssrf_guard import validate_outbound_url


class StreamEvent(BaseModel):
    type: Literal["text_delta", "tool_call", "done", "error", "usage"]
    text: str | None = None
    tool_call: ToolCall | None = None
    error: str | None = None
    usage: dict[str, int] | None = None
    finish_reason: str | None = None


class ProviderError(Exception):
    pass


class OpenAICompatibleClient:
    def __init__(self, base_url: str, api_key: str | None, allow_local: bool = False):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.allow_local = allow_local

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    async def list_models(self) -> list[str]:
        validate_outbound_url(self.base_url, allow_loopback=self.allow_local)
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{self.base_url}/models", headers=self._headers())
            resp.raise_for_status()
            data = resp.json()
            return [m["id"] for m in data.get("data", [])]

    async def stream(
        self,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 1.0,
    ) -> AsyncIterator[StreamEvent]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "temperature": temperature,
        }
        if tools:
            payload["tools"] = tools

        pending_tool_calls: dict[int, dict[str, Any]] = {}

        try:
            validate_outbound_url(self.base_url, allow_loopback=self.allow_local)
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/chat/completions",
                    headers=self._headers(),
                    json=payload,
                ) as resp:
                    if resp.status_code >= 400:
                        body = await resp.aread()
                        raise ProviderError(
                            f"HTTP {resp.status_code}: {body.decode(errors='replace')[:500]}"
                        )
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data_str = line[len("data:") :].strip()
                        if data_str == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        choices = chunk.get("choices") or []
                        if not choices:
                            continue
                        choice = choices[0]
                        delta = choice.get("delta", {})

                        if "content" in delta and delta["content"]:
                            yield StreamEvent(type="text_delta", text=delta["content"])

                        for tc_delta in delta.get("tool_calls") or []:
                            idx = tc_delta.get("index", 0)
                            if idx not in pending_tool_calls:
                                pending_tool_calls[idx] = {
                                    "id": tc_delta.get("id", f"call_{idx}"),
                                    "name": "",
                                    "arguments": "",
                                }
                            fn = tc_delta.get("function", {})
                            if fn.get("name"):
                                pending_tool_calls[idx]["name"] += fn["name"]
                            if fn.get("arguments"):
                                pending_tool_calls[idx]["arguments"] += fn["arguments"]

                        finish_reason = choice.get("finish_reason")
                        if finish_reason:
                            for tc in pending_tool_calls.values():
                                try:
                                    args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                                except json.JSONDecodeError:
                                    args = {}
                                yield StreamEvent(
                                    type="tool_call",
                                    tool_call=ToolCall(
                                        id=tc["id"], name=tc["name"], arguments=args
                                    ),
                                )
                            usage = chunk.get("usage")
                            yield StreamEvent(
                                type="done",
                                finish_reason=finish_reason,
                                usage=usage,
                            )
        except httpx.HTTPError as e:
            yield StreamEvent(type="error", error=str(e))
        except ProviderError as e:
            yield StreamEvent(type="error", error=str(e))


class AnthropicClient:
    def __init__(self, base_url: str, api_key: str | None, allow_local: bool = False):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.allow_local = allow_local

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "x-api-key": self.api_key or "",
            "anthropic-version": "2023-06-01",
        }

    async def list_models(self) -> list[str]:
        validate_outbound_url(self.base_url, allow_loopback=self.allow_local)
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{self.base_url}/models", headers=self._headers())
            resp.raise_for_status()
            return [m["id"] for m in resp.json().get("data", [])]

    async def stream(
        self,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 1.0,
    ) -> AsyncIterator[StreamEvent]:
        system = ""
        converted = []
        for m in messages:
            if m["role"] == "system":
                system += m["content"] + "\n"
            else:
                converted.append({"role": m["role"], "content": m["content"]})

        payload: dict[str, Any] = {
            "model": model,
            "messages": converted,
            "max_tokens": 8192,
            "stream": True,
            "temperature": temperature,
        }
        if system:
            payload["system"] = system.strip()
        if tools:
            payload["tools"] = [
                {
                    "name": t["function"]["name"],
                    "description": t["function"].get("description", ""),
                    "input_schema": t["function"].get("parameters", {}),
                }
                for t in tools
            ]

        current_tool: dict[str, Any] | None = None
        try:
            validate_outbound_url(self.base_url, allow_loopback=self.allow_local)
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url}/messages",
                    headers=self._headers(),
                    json=payload,
                ) as resp:
                    if resp.status_code >= 400:
                        body = await resp.aread()
                        raise ProviderError(
                            f"HTTP {resp.status_code}: {body.decode(errors='replace')[:500]}"
                        )
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data_str = line[len("data:") :].strip()
                        if not data_str:
                            continue
                        try:
                            event = json.loads(data_str)
                        except json.JSONDecodeError:
                            continue
                        etype = event.get("type")
                        if etype == "content_block_start":
                            block = event.get("content_block", {})
                            if block.get("type") == "tool_use":
                                current_tool = {
                                    "id": block.get("id", ""),
                                    "name": block.get("name", ""),
                                    "arguments": "",
                                }
                        elif etype == "content_block_delta":
                            delta = event.get("delta", {})
                            if delta.get("type") == "text_delta":
                                yield StreamEvent(type="text_delta", text=delta.get("text", ""))
                            elif delta.get("type") == "input_json_delta" and current_tool:
                                current_tool["arguments"] += delta.get("partial_json", "")
                        elif etype == "content_block_stop" and current_tool:
                            try:
                                args = (
                                    json.loads(current_tool["arguments"])
                                    if current_tool["arguments"]
                                    else {}
                                )
                            except json.JSONDecodeError:
                                args = {}
                            yield StreamEvent(
                                type="tool_call",
                                tool_call=ToolCall(
                                    id=current_tool["id"],
                                    name=current_tool["name"],
                                    arguments=args,
                                ),
                            )
                            current_tool = None
                        elif etype == "message_delta":
                            usage = event.get("usage")
                            finish_reason = event.get("delta", {}).get("stop_reason")
                            yield StreamEvent(
                                type="done", finish_reason=finish_reason, usage=usage
                            )
        except httpx.HTTPError as e:
            yield StreamEvent(type="error", error=str(e))
        except ProviderError as e:
            yield StreamEvent(type="error", error=str(e))


def make_client(kind: str, base_url: str, api_key: str | None, allow_local: bool = False):
    if kind == "anthropic":
        return AnthropicClient(base_url, api_key, allow_local=allow_local)
    if kind == "gemini":
        # Imported lazily to avoid a hard import-time dependency cycle
        # between providers/client.py and providers/gemini.py.
        from local_ai_workspace.providers.gemini import GeminiClient

        return GeminiClient(base_url, api_key, allow_local=allow_local)
    return OpenAICompatibleClient(base_url, api_key, allow_local=allow_local)
