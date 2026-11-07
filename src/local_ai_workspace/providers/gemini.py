"""Gemini provider adapter (Google generativelanguage.googleapis.com).

Implements the same async interface as OpenAICompatibleClient/AnthropicClient
in providers/client.py: an async `stream(messages, model, tools)` generator
yielding StreamEvent, plus `list_models()`. The chat orchestrator never needs
to know this is a different wire format.

Gemini differences handled here:
  - Message roles: Gemini only knows "user" and "model" (no "assistant",
    no "system" message in the contents array). We map assistant -> model
    and pull all "system" messages out into a top-level `system_instruction`
    field instead.
  - Tool-call wire format: OpenAI-style `tool_calls` with JSON-string
    arguments become Gemini `functionCall` parts with native JSON objects;
    tool results (role "tool" in our internal format) become
    `functionResponse` parts on a "user"-turn content block (Gemini has no
    separate tool role).
  - Streaming: Gemini's streamGenerateContent (with ?alt=sse) sends whole
    GenerateContentResponse JSON objects per SSE `data:` line (not deltas to
    merge token-by-token) -- each chunk's candidate parts are emitted
    directly as our StreamEvent text/tool_call events as they arrive.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from local_ai_workspace.core.models import ToolCall
from local_ai_workspace.core.ssrf_guard import validate_outbound_url
from local_ai_workspace.providers.client import ProviderError, StreamEvent

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"


def _messages_to_gemini(
    messages: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str | None]:
    """Convert internal OpenAI-style message list into Gemini's `contents`
    list plus an optional system instruction string."""
    system_parts: list[str] = []
    contents: list[dict[str, Any]] = []

    for m in messages:
        role = m.get("role")
        if role == "system":
            if m.get("content"):
                system_parts.append(m["content"])
            continue

        if role == "tool":
            # Gemini represents tool results as a functionResponse part,
            # conventionally on a "user" turn.
            contents.append(
                {
                    "role": "user",
                    "parts": [
                        {
                            "functionResponse": {
                                "name": m.get("name") or "tool_result",
                                "response": {"result": m.get("content", "")},
                            }
                        }
                    ],
                }
            )
            continue

        gemini_role = "model" if role == "assistant" else "user"
        parts: list[dict[str, Any]] = []
        if m.get("content"):
            parts.append({"text": m["content"]})
        for tc in m.get("tool_calls") or []:
            fn = tc.get("function", {})
            args = fn.get("arguments")
            if isinstance(args, str):
                try:
                    args = json.loads(args) if args else {}
                except json.JSONDecodeError:
                    args = {}
            parts.append({"functionCall": {"name": fn.get("name", ""), "args": args or {}}})
        if not parts:
            # Gemini requires at least one part per content entry.
            parts.append({"text": ""})
        contents.append({"role": gemini_role, "parts": parts})

    system_instruction = "\n".join(system_parts).strip() or None
    return contents, system_instruction


def _tools_to_gemini(tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    if not tools:
        return None
    declarations = []
    for t in tools:
        fn = t.get("function", t)
        declarations.append(
            {
                "name": fn.get("name"),
                "description": fn.get("description", ""),
                "parameters": fn.get("parameters", {"type": "object", "properties": {}}),
            }
        )
    return [{"functionDeclarations": declarations}]


class GeminiClient:
    def __init__(
        self,
        base_url: str | None,
        api_key: str | None,
        custom_headers: dict[str, str] | None = None,
        timeout_seconds: float = 60.0,
        allow_local: bool = False,
    ):
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.api_key = api_key
        self.custom_headers = custom_headers or {}
        self.timeout_seconds = timeout_seconds
        self.allow_local = allow_local

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json", **self.custom_headers}
        return headers

    def _params(self) -> dict[str, str]:
        params = {}
        if self.api_key:
            params["key"] = self.api_key
        return params

    async def list_models(self) -> list[str]:
        validate_outbound_url(self.base_url, allow_loopback=self.allow_local)
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(f"{self.base_url}/models", headers=self._headers(), params=self._params())
            resp.raise_for_status()
            data = resp.json()
            names = []
            for m in data.get("models", []):
                name = m.get("name", "")
                # Gemini returns "models/gemini-1.5-pro" -- strip the prefix
                # to match the bare model-id convention used elsewhere.
                names.append(name.split("/", 1)[-1] if "/" in name else name)
            return names

    async def stream(
        self,
        messages: list[dict[str, Any]],
        model: str,
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 1.0,
    ) -> AsyncIterator[StreamEvent]:
        contents, system_instruction = _messages_to_gemini(messages)
        payload: dict[str, Any] = {
            "contents": contents,
            "generationConfig": {"temperature": temperature},
        }
        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}
        gemini_tools = _tools_to_gemini(tools)
        if gemini_tools:
            payload["tools"] = gemini_tools

        url = f"{self.base_url}/models/{model}:streamGenerateContent"
        params = {**self._params(), "alt": "sse"}

        try:
            validate_outbound_url(self.base_url, allow_loopback=self.allow_local)
            async with (
                httpx.AsyncClient(timeout=self.timeout_seconds) as client,
                client.stream(
                    "POST",
                    url,
                    headers=self._headers(),
                    params=params,
                    json=payload,
                ) as resp,
            ):
                if resp.status_code >= 400:
                    body = await resp.aread()
                    raise ProviderError(f"HTTP {resp.status_code}: {body.decode(errors='replace')[:500]}")
                usage: dict[str, int] | None = None
                finish_reason: str | None = None
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data_str = line[len("data:") :].strip()
                    if not data_str:
                        continue
                    try:
                        chunk = json.loads(data_str)
                    except json.JSONDecodeError:
                        continue

                    for candidate in chunk.get("candidates", []):
                        content = candidate.get("content", {})
                        for part in content.get("parts", []):
                            if "text" in part and part["text"]:
                                yield StreamEvent(type="text_delta", text=part["text"])
                            if "functionCall" in part:
                                fc = part["functionCall"]
                                yield StreamEvent(
                                    type="tool_call",
                                    tool_call=ToolCall(
                                        id=f"call_{fc.get('name', 'fn')}",
                                        name=fc.get("name", ""),
                                        arguments=fc.get("args", {}) or {},
                                    ),
                                )
                        if candidate.get("finishReason"):
                            finish_reason = candidate["finishReason"]

                    if chunk.get("usageMetadata"):
                        um = chunk["usageMetadata"]
                        usage = {
                            "prompt_tokens": um.get("promptTokenCount", 0),
                            "completion_tokens": um.get("candidatesTokenCount", 0),
                            "total_tokens": um.get("totalTokenCount", 0),
                        }

                yield StreamEvent(type="done", finish_reason=finish_reason, usage=usage)
        except httpx.HTTPError as e:
            yield StreamEvent(type="error", error=str(e))
        except ProviderError as e:
            yield StreamEvent(type="error", error=str(e))
