"""The only place that maps settings to a concrete provider adapter."""

from dataclasses import replace

import httpx

from codex_query.application.ports.chat import ChatPort
from codex_query.application.ports.embeddings import EmbeddingPort
from codex_query.domain.errors import ProviderConfigurationError
from codex_query.domain.models.provider import (
    CHAT_PROVIDER_CONFIGS,
    EMBEDDING_PROVIDER_CONFIGS,
    WireFormat,
)
from codex_query.domain.models.settings import ServiceSettings
from codex_query.infrastructure.llm.anthropic import AnthropicChatAdapter
from codex_query.infrastructure.llm.cohere import (
    CohereChatAdapter,
    CohereEmbeddingAdapter,
)
from codex_query.infrastructure.llm.ollama import (
    OllamaChatAdapter,
    OllamaEmbeddingAdapter,
)
from codex_query.infrastructure.llm.ollama_host import resolve_ollama_url
from codex_query.infrastructure.llm.openai_compat import (
    OpenAIChatAdapter,
    OpenAIEmbeddingAdapter,
)


def _ollama_settings(settings: ServiceSettings, base_url: str) -> ServiceSettings:
    return replace(settings, base_url=resolve_ollama_url(settings.base_url or base_url))


def create_chat_adapter(
    client: httpx.AsyncClient, settings: ServiceSettings
) -> ChatPort:
    config = CHAT_PROVIDER_CONFIGS.get(settings.provider)
    if config is None:
        msg = f"{settings.provider.value} does not support chat"
        raise ProviderConfigurationError(msg)
    match config.wire_format:
        case WireFormat.OPENAI:
            return OpenAIChatAdapter(client, config, settings)
        case WireFormat.ANTHROPIC:
            return AnthropicChatAdapter(client, config, settings)
        case WireFormat.COHERE:
            return CohereChatAdapter(client, config, settings)
        case WireFormat.OLLAMA:
            return OllamaChatAdapter(
                client, config, _ollama_settings(settings, config.base_url)
            )


def create_embedding_adapter(
    client: httpx.AsyncClient, settings: ServiceSettings
) -> EmbeddingPort:
    config = EMBEDDING_PROVIDER_CONFIGS.get(settings.provider)
    if config is None:
        msg = f"{settings.provider.value} does not support embeddings"
        raise ProviderConfigurationError(msg)
    match config.wire_format:
        case WireFormat.OPENAI:
            return OpenAIEmbeddingAdapter(client, config, settings)
        case WireFormat.COHERE:
            return CohereEmbeddingAdapter(client, config, settings)
        case WireFormat.OLLAMA:
            return OllamaEmbeddingAdapter(
                client, config, _ollama_settings(settings, config.base_url)
            )
        case WireFormat.ANTHROPIC:
            msg = "The Anthropic wire format has no embeddings endpoint"
            raise ProviderConfigurationError(msg)
