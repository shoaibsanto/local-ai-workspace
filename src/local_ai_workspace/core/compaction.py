"""Context compaction: when a conversation's raw history approaches the
provider's context window, replace (for *prompt-building purposes only*)
the full raw history with a persisted structured summary plus the most
recent N raw messages.

Nothing on disk is ever destroyed by this module: messages.jsonl (the
original history) is never deleted, truncated, or rewritten here. Summaries
are purely additive artifacts living alongside it in the same conversation
directory:

    conversations/<id>/messages.jsonl   untouched, always the full history
    conversations/<id>/summary.md       human-readable summary (latest)
    conversations/<id>/context.json     structured ConversationSummary

This is a *prompt-construction* optimization layered on top of
core/chat.py's existing cheap char-count truncation safety net
(`_compact_messages`), not a replacement for it: even after summarizing,
the summary + recent messages combination still goes through that same
truncation as a final safety net in case it's still too large (e.g. a
single huge recent message, or a summary that grew larger than expected).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from local_ai_workspace.storage.paths import conversation_dir

logger = logging.getLogger(__name__)

DEFAULT_COMPACT_TIMEOUT_SECONDS = 45.0


class ConversationSummary(BaseModel):
    user_instructions: str = ""
    important_facts: list[str] = Field(default_factory=list)
    decisions_made: list[str] = Field(default_factory=list)
    project_state: str = ""
    completed_work: list[str] = Field(default_factory=list)
    pending_tasks: list[str] = Field(default_factory=list)
    tool_results_of_note: list[str] = Field(default_factory=list)
    updated_at: float = Field(default_factory=time.time)
    # id of the last original message (from messages.jsonl) folded into
    # this summary -- lets a future compaction run know where to resume
    # summarizing from, rather than re-summarizing from scratch every time.
    covers_through_message_id: str = ""

    def to_markdown(self) -> str:
        def _bullets(items: list[str]) -> str:
            return "\n".join(f"- {i}" for i in items) if items else "- (none)"

        return (
            "# Conversation Summary\n\n"
            f"_Updated: {self.updated_at}_  \n"
            f"_Covers through message: {self.covers_through_message_id}_\n\n"
            "## User Instructions\n"
            f"{self.user_instructions or '(none recorded)'}\n\n"
            "## Important Facts\n"
            f"{_bullets(self.important_facts)}\n\n"
            "## Decisions Made\n"
            f"{_bullets(self.decisions_made)}\n\n"
            "## Project State\n"
            f"{self.project_state or '(none recorded)'}\n\n"
            "## Completed Work\n"
            f"{_bullets(self.completed_work)}\n\n"
            "## Pending Tasks\n"
            f"{_bullets(self.pending_tasks)}\n\n"
            "## Tool Results Of Note\n"
            f"{_bullets(self.tool_results_of_note)}\n"
        )


def _summary_md_path(conversation_id: str) -> Path:
    return conversation_dir(conversation_id) / "summary.md"


def _context_json_path(conversation_id: str) -> Path:
    return conversation_dir(conversation_id) / "context.json"


def get_summary(conversation_id: str) -> ConversationSummary | None:
    """Read the persisted structured summary, if one exists."""
    path = _context_json_path(conversation_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return ConversationSummary(**data)
    except (json.JSONDecodeError, ValueError, OSError) as e:
        logger.warning("Failed to read existing summary for %s: %s", conversation_id, e)
        return None


def _write_summary(conversation_id: str, summary: ConversationSummary) -> None:
    d = conversation_dir(conversation_id)
    d.mkdir(parents=True, exist_ok=True)
    _context_json_path(conversation_id).write_text(
        json.dumps(summary.model_dump(), indent=2, ensure_ascii=False), encoding="utf-8"
    )
    _summary_md_path(conversation_id).write_text(summary.to_markdown(), encoding="utf-8")


def estimate_tokens(messages: list[dict[str, Any]]) -> int:
    """Token estimate for a wire-format message list, reusing the same
    4-chars-per-token heuristic already used in core/chat.py's cheap
    truncation safety net (CHARS_PER_TOKEN / `_estimate_chars`) rather than
    inventing a second, possibly-inconsistent estimator."""
    from local_ai_workspace.core.chat import CHARS_PER_TOKEN, _estimate_chars

    return _estimate_chars(messages) // CHARS_PER_TOKEN


def should_compact(messages: list[dict[str, Any]], context_window: int, threshold: float = 0.75) -> bool:
    """True if `messages` are estimated to use >= `threshold` fraction of
    `context_window` tokens."""
    if context_window <= 0:
        return False
    return estimate_tokens(messages) >= context_window * threshold


_SUMMARY_PROMPT_TEMPLATE = """\
You are maintaining a running structured summary of a long conversation so \
older turns can be dropped from the live prompt without losing what matters.

{existing_block}

Here is the conversation content to incorporate (if an existing summary was \
given above, only incorporate what's NEW since it; otherwise summarize \
everything below):

{history_block}

Respond with ONLY a single JSON object (no markdown fences, no commentary) \
with exactly these keys:
{{
  "user_instructions": "<string: the user's standing instructions/goals>",
  "important_facts": ["<string>", ...],
  "decisions_made": ["<string>", ...],
  "project_state": "<string: current state of whatever is being worked on>",
  "completed_work": ["<string>", ...],
  "pending_tasks": ["<string>", ...],
  "tool_results_of_note": ["<string>", ...]
}}
"""


def _build_summary_prompt(existing: ConversationSummary | None, history_text: str) -> str:
    existing_block = (
        f"Existing summary (update/extend this, don't discard still-relevant information):\n{existing.to_markdown()}"
        if existing is not None
        else "There is no existing summary yet -- this is the first compaction."
    )
    return _SUMMARY_PROMPT_TEMPLATE.format(existing_block=existing_block, history_block=history_text)


def _extract_json_object(text: str) -> dict[str, Any]:
    """Defensively pull a JSON object out of a model response that may be
    wrapped in markdown fences or have leading/trailing prose."""
    text = text.strip()
    try:
        parsed: dict[str, Any] = json.loads(text)
        return parsed
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        parsed = json.loads(match.group(0))
        return parsed
    raise ValueError("No JSON object found in model response")


async def compact(
    conversation_id: str,
    llm_client: Any,
    model_name: str,
    timeout: float = DEFAULT_COMPACT_TIMEOUT_SECONDS,
) -> ConversationSummary:
    """Build or incrementally update the structured summary for a
    conversation by asking the model to produce it, parse the response
    defensively, persist it to disk, and return it.

    Never raises: on any failure (timeout, network error, malformed model
    output), logs the error and returns the existing on-disk summary
    unchanged if one exists, or a minimal fallback summary (not persisted)
    built from the raw history otherwise. The caller (core/chat.py) can
    always fall back to the existing cheap truncation behavior using this
    return value or the raw history -- compaction failing never crashes the
    conversation.
    """
    from local_ai_workspace.core.chat import _messages_to_wire_format
    from local_ai_workspace.storage import conversation_store

    existing = get_summary(conversation_id)
    history = conversation_store.get_messages(conversation_id)

    # Only summarize messages after the existing summary's cutoff, if any,
    # so updates are incremental rather than regenerated from scratch.
    new_messages = history
    if existing is not None and existing.covers_through_message_id:
        for i, m in enumerate(history):
            if m.id == existing.covers_through_message_id:
                new_messages = history[i + 1 :]
                break

    if not new_messages and existing is not None:
        return existing  # nothing new to fold in

    wire = _messages_to_wire_format(new_messages)
    history_text = "\n".join(f"[{m.get('role')}] {m.get('content') or ''}" for m in wire)
    prompt = _build_summary_prompt(existing, history_text)

    async def _call_model() -> str:
        text = ""
        async for event in llm_client.stream([{"role": "user", "content": prompt}], model_name, tools=None):
            if event.type == "text_delta":
                text += event.text or ""
            elif event.type == "error":
                raise RuntimeError(f"LLM error during compaction: {event.error}")
        return text

    try:
        raw_text = await asyncio.wait_for(_call_model(), timeout=timeout)
        parsed = _extract_json_object(raw_text)
        summary = ConversationSummary(
            user_instructions=str(parsed.get("user_instructions", "")),
            important_facts=[str(x) for x in parsed.get("important_facts", [])],
            decisions_made=[str(x) for x in parsed.get("decisions_made", [])],
            project_state=str(parsed.get("project_state", "")),
            completed_work=[str(x) for x in parsed.get("completed_work", [])],
            pending_tasks=[str(x) for x in parsed.get("pending_tasks", [])],
            tool_results_of_note=[str(x) for x in parsed.get("tool_results_of_note", [])],
            updated_at=time.time(),
            covers_through_message_id=history[-1].id if history else "",
        )
        _write_summary(conversation_id, summary)
        return summary
    except TimeoutError:
        logger.error("Compaction timed out for conversation %s after %ss", conversation_id, timeout)
    except Exception as e:  # noqa: BLE001 - never let compaction crash the turn
        logger.error("Compaction failed for conversation %s: %s", conversation_id, e)

    if existing is not None:
        return existing
    # No prior summary and this attempt failed: minimal, not persisted,
    # fallback so callers always get a ConversationSummary back.
    return ConversationSummary(
        project_state="(compaction failed; falling back to raw/truncated history)",
        covers_through_message_id=history[-1].id if history else "",
    )


def build_prompt_with_summary(
    conversation_id: str, recent_n: int, summary: ConversationSummary | None = None
) -> list[dict[str, Any]]:
    """Build a wire-format message list: a system-role context block built
    from the persisted summary, followed by the `recent_n` most recent raw
    messages converted to wire format. Falls back to plain raw-history wire
    format (no summary block) if no summary is available -- callers should
    only call this after `should_compact` returns True and ideally after
    `compact()` has produced/refreshed a summary, but it degrades
    gracefully either way."""
    from local_ai_workspace.core.chat import _messages_to_wire_format
    from local_ai_workspace.storage import conversation_store

    history = conversation_store.get_messages(conversation_id)
    recent = history[-recent_n:] if recent_n > 0 else history
    recent_wire = _messages_to_wire_format(recent)

    summary = summary if summary is not None else get_summary(conversation_id)
    if summary is None:
        return recent_wire

    context_block = {
        "role": "system",
        "content": (
            "[Context compacted: the following is a structured summary of "
            "earlier conversation history that has been omitted from this "
            "prompt to save context. The raw history is still fully "
            "preserved on disk and was not deleted.]\n\n" + summary.to_markdown()
        ),
    }
    return [context_block] + recent_wire
