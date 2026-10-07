from dataclasses import dataclass
from enum import StrEnum
from typing import Final, Protocol

from codex_query.domain.models.provider import PROVIDER_CONFIGS, LLMProvider

# Explicit constants for token estimation
ESTIMATED_CHARS_PER_TOKEN: Final[int] = 4
PROMPT_OVERHEAD_TOKENS: Final[int] = 200


class PresetMode(StrEnum):
    QUALITY = "QUALITY"
    BALANCED = "BALANCED"
    LOW = "LOW"
    CUSTOM = "CUSTOM"


@dataclass(frozen=True, slots=True)
class Preset:
    temperature: float
    max_tokens: int
    top_k: int
    num_ctx: int
    chunk_size: int


PRESETS: dict[PresetMode, Preset] = {
    PresetMode.QUALITY: Preset(0.3, 1000, 8, 8192, 1000),
    PresetMode.BALANCED: Preset(0.2, 600, 6, 6144, 800),
    PresetMode.LOW: Preset(0.2, 400, 4, 4096, 600),
}


class ProviderUrlResolver(Protocol):
    def get_default_url(self, provider: LLMProvider) -> str: ...


@dataclass(slots=True)
class Settings:
    provider: LLMProvider = LLMProvider.OLLAMA
    base_url: str = ""
    api_key: str = ""
    chat_model: str = "llama3.2:3b"
    embed_model: str = "bge-m3"
    preset_mode: PresetMode = PresetMode.LOW
    temperature: float = 0.2
    max_tokens: int = 400
    top_k: int = 4
    num_ctx: int = 4096
    chunk_size: int = 600

    def select_preset(self, name: PresetMode) -> None:
        if name in PRESETS:
            p = PRESETS[name]
            self.preset_mode = name
            self.temperature = p.temperature
            self.max_tokens = p.max_tokens
            self.top_k = p.top_k
            self.num_ctx = p.num_ctx
            self.chunk_size = p.chunk_size
        else:
            self.preset_mode = PresetMode.CUSTOM

    def select_provider(
        self, new_provider: LLMProvider, resolver: ProviderUrlResolver
    ) -> bool:
        url_changed = False
        default_for_new_provider = resolver.get_default_url(new_provider)
        current_default_url = resolver.get_default_url(self.provider)

        # Update base URL if empty or currently pointing to previous provider's default
        if not self.base_url or self.base_url == current_default_url:
            url_changed = self.base_url != default_for_new_provider
            self.base_url = default_for_new_provider

        # Update model defaults for the new provider
        if new_provider in PROVIDER_CONFIGS:
            prev_defaults = PROVIDER_CONFIGS.get(self.provider, {}).get(
                "default_models", {}
            )
            new_defaults = PROVIDER_CONFIGS[new_provider]["default_models"]

            # Replace chat model if it matched previous provider's default or was empty
            if not self.chat_model or self.chat_model == prev_defaults.get("chat"):
                self.chat_model = new_defaults["chat"]

            # Replace embedding model accordingly
            if not self.embed_model or self.embed_model == prev_defaults.get(
                "embeddings"
            ):
                self.embed_model = (
                    new_defaults["embeddings"]
                    if new_defaults["embeddings"] != "none"
                    else ""
                )

        self.provider = new_provider
        return url_changed

    def est_tokens(self) -> int:
        """Estimates context window token usage based on chunk size and model params."""
        retrieval_tokens = (self.top_k * self.chunk_size) // ESTIMATED_CHARS_PER_TOKEN
        return retrieval_tokens + PROMPT_OVERHEAD_TOKENS + self.max_tokens
