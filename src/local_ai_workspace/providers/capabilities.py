"""Capability detection for providers.

Approach chosen: static lookup table keyed by provider kind + model-name
substring matching, NOT a live probe. Rationale:
  - A live probe (e.g. actually sending a tool-call request and seeing if the
    provider accepts it) costs a real network round-trip and, for metered
    APIs, real money/quota, every time a user opens the providers screen.
  - Capability support for the major providers is well-documented and
    changes rarely enough that a maintained table is accurate in practice
    and costs nothing to query.
  - It degrades gracefully: unknown provider kinds/models fall back to a
    conservative "we don't know" result (see core/chat.py for how callers
    are expected to treat unset vs. explicitly-False capability keys).

If a future need arises for differentiating niche self-hosted models that
don't match any known pattern, the right fix is to let the user hand-edit
a provider's `capabilities` dict in the UI -- not to add a network call
here.
"""
from __future__ import annotations

from local_ai_workspace.core.models import ProviderConfig

CapabilityDict = dict[str, bool]

_DEFAULT: CapabilityDict = {
    "streaming": True,
    "tool_calling": False,
    "vision": False,
    "structured_output": False,
}

# (kind, model substring) -> capability overrides, checked in order; later
# matches win on a per-key basis (dict.update), so put broad kind-level
# defaults first and specific model overrides after.
_RULES: list[tuple[str, str, CapabilityDict]] = [
    # --- OpenAI-compatible (OpenRouter, Ollama, LM Studio, vLLM, etc.) ---
    ("openai_compatible", "", {"streaming": True, "tool_calling": True}),
    ("openai_compatible", "gpt-4", {"tool_calling": True, "vision": True, "structured_output": True}),
    ("openai_compatible", "gpt-5", {"tool_calling": True, "vision": True, "structured_output": True}),
    ("openai_compatible", "o1", {"tool_calling": True, "structured_output": True}),
    ("openai_compatible", "o3", {"tool_calling": True, "structured_output": True}),
    ("openai_compatible", "claude", {"tool_calling": True, "vision": True}),
    ("openai_compatible", "llama", {"tool_calling": True}),
    ("openai_compatible", "qwen", {"tool_calling": True}),
    ("openai_compatible", "deepseek", {"tool_calling": True}),
    ("openai_compatible", "llava", {"vision": True}),
    # --- Anthropic native API ---
    ("anthropic", "", {"streaming": True, "tool_calling": True, "vision": True}),
    ("anthropic", "haiku", {"tool_calling": True, "vision": True}),
    ("anthropic", "opus", {"tool_calling": True, "vision": True, "structured_output": True}),
    ("anthropic", "sonnet", {"tool_calling": True, "vision": True, "structured_output": True}),
    # --- Gemini ---
    ("gemini", "", {"streaming": True, "tool_calling": True, "vision": True}),
    ("gemini", "1.5-pro", {"tool_calling": True, "vision": True, "structured_output": True}),
    ("gemini", "1.5-flash", {"tool_calling": True, "vision": True}),
    ("gemini", "2.0", {"tool_calling": True, "vision": True, "structured_output": True}),
    ("gemini", "2.5", {"tool_calling": True, "vision": True, "structured_output": True}),
]


def detect_capabilities(provider: ProviderConfig, model: str | None = None) -> CapabilityDict:
    """Return a best-guess capabilities dict for `provider` (optionally for
    a specific `model`, defaulting to the provider's default_model/first
    configured model). Pure/static -- no network calls."""
    model_name = (model or provider.default_model or (provider.models[0] if provider.models else "") or "").lower()

    result = dict(_DEFAULT)
    for kind, substring, overrides in _RULES:
        if kind != provider.kind:
            continue
        if substring and substring not in model_name:
            continue
        result.update(overrides)
    return result
