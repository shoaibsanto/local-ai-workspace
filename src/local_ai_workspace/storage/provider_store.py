"""Provider configuration persistence (non-secret fields only)."""

from __future__ import annotations

from local_ai_workspace.core.models import ProviderConfig
from local_ai_workspace.storage.json_store import read_json, write_json_atomic
from local_ai_workspace.storage.paths import providers_path


def list_providers() -> list[ProviderConfig]:
    data = read_json(providers_path(), default=[])
    return [ProviderConfig(**p) for p in data]


def get_provider(provider_id: str) -> ProviderConfig | None:
    for p in list_providers():
        if p.id == provider_id:
            return p
    return None


def save_provider(provider: ProviderConfig) -> ProviderConfig:
    providers = list_providers()
    providers = [p for p in providers if p.id != provider.id]
    providers.append(provider)
    write_json_atomic(providers_path(), [p.model_dump() for p in providers])
    return provider


def delete_provider(provider_id: str) -> bool:
    providers = list_providers()
    remaining = [p for p in providers if p.id != provider_id]
    if len(remaining) == len(providers):
        return False
    write_json_atomic(providers_path(), [p.model_dump() for p in remaining])
    return True


def seed_default_providers() -> None:
    """Called once on first run so the app isn't an empty shell."""
    if list_providers():
        return
    defaults = [
        ProviderConfig(
            name="OpenRouter",
            base_url="https://openrouter.ai/api/v1",
            kind="openai_compatible",
            default_model="anthropic/claude-sonnet-4.5",
            models=[
                "anthropic/claude-sonnet-4.5",
                "anthropic/claude-opus-4.1",
                "openai/gpt-5",
                "deepseek/deepseek-chat",
            ],
            enabled=False,  # enabled once user supplies an API key
        ),
        ProviderConfig(
            name="Anthropic",
            base_url="https://api.anthropic.com/v1",
            kind="anthropic",
            default_model="claude-sonnet-4-5",
            models=["claude-sonnet-4-5", "claude-opus-4-1", "claude-haiku-4-5"],
            enabled=False,
        ),
        ProviderConfig(
            name="Local (Ollama)",
            base_url="http://localhost:11434/v1",
            kind="openai_compatible",
            default_model="llama3.1",
            models=["llama3.1", "qwen2.5"],
            enabled=False,
        ),
    ]
    for p in defaults:
        save_provider(p)
