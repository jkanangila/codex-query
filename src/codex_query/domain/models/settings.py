from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final

from codex_query.domain.errors import ProviderConfigurationError
from codex_query.domain.models.chat import GenerationParams
from codex_query.domain.models.provider import (
    CHAT_PROVIDER_CONFIGS,
    EMBEDDING_PROVIDER_CONFIGS,
    EndpointConfig,
    LLMProvider,
)

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


@dataclass(slots=True)
class ServiceSettings:
    """Provider, credentials and model for ONE capability (chat or embeddings)."""

    provider: LLMProvider
    base_url: str = ""
    api_key: str = ""
    model: str = ""

    @classmethod
    def for_provider(
        cls, provider: LLMProvider, configs: Mapping[LLMProvider, EndpointConfig]
    ) -> "ServiceSettings":
        config = configs.get(provider)
        if config is None:
            msg = f"{provider.value} does not offer this service"
            raise ProviderConfigurationError(msg)
        return cls(provider, base_url=config.base_url, model=config.default_model)

    def select_provider(
        self,
        new_provider: LLMProvider,
        configs: Mapping[LLMProvider, EndpointConfig],
    ) -> bool:
        """Switch provider, carrying over only values the user customized.

        Returns True when the base URL changed. Raises if `new_provider` does
        not offer this service (e.g. Anthropic has no embeddings).
        """
        new_config = configs.get(new_provider)
        if new_config is None:
            msg = f"{new_provider.value} does not offer this service"
            raise ProviderConfigurationError(msg)
        old_config = configs.get(self.provider)

        url_changed = False
        # Replace the URL if empty or still pointing at the old provider's default.
        if (
            old_config is None
            or not self.base_url
            or self.base_url == old_config.base_url
        ):
            url_changed = self.base_url != new_config.base_url
            self.base_url = new_config.base_url

        if (
            old_config is None
            or not self.model
            or self.model == old_config.default_model
        ):
            self.model = new_config.default_model

        # A key is only valid for the vendor that issued it: never send it on.
        if new_provider != self.provider:
            self.api_key = ""

        self.provider = new_provider
        return url_changed


def _default_chat() -> ServiceSettings:
    return ServiceSettings.for_provider(LLMProvider.OLLAMA, CHAT_PROVIDER_CONFIGS)


def _default_embedding() -> ServiceSettings:
    return ServiceSettings.for_provider(LLMProvider.OLLAMA, EMBEDDING_PROVIDER_CONFIGS)


@dataclass(slots=True)
class Settings:
    chat: ServiceSettings = field(default_factory=_default_chat)
    embedding: ServiceSettings = field(default_factory=_default_embedding)
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

    def select_chat_provider(self, provider: LLMProvider) -> bool:
        return self.chat.select_provider(provider, CHAT_PROVIDER_CONFIGS)

    def select_embedding_provider(self, provider: LLMProvider) -> bool:
        return self.embedding.select_provider(provider, EMBEDDING_PROVIDER_CONFIGS)

    def generation_params(self) -> GenerationParams:
        return GenerationParams(
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            num_ctx=self.num_ctx,
        )

    def est_tokens(self) -> int:
        """Estimates context window token usage based on chunk size and model params."""
        retrieval_tokens = (self.top_k * self.chunk_size) // ESTIMATED_CHARS_PER_TOKEN
        return retrieval_tokens + PROMPT_OVERHEAD_TOKENS + self.max_tokens
