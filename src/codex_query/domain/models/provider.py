from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Final


class LLMProvider(StrEnum):
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    GOOGLE_GEMINI = "google_gemini"
    MISTRAL = "mistral"
    COHERE = "cohere"
    OLLAMA = "ollama"


class AuthType(StrEnum):
    BEARER_TOKEN = "bearer_token"
    CUSTOM_HEADER = "custom_header"


class WireFormat(StrEnum):
    """Request/response dialect an endpoint speaks.

    Gemini, Mistral and OpenAI all speak the OpenAI dialect, so they share
    one adapter and differ only by configuration.
    """

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    COHERE = "cohere"
    OLLAMA = "ollama"


@dataclass(frozen=True, slots=True)
class AuthConfig:
    type: AuthType
    header_name: str = "Authorization"
    api_key_required: bool = True


@dataclass(frozen=True, slots=True)
class EndpointConfig:
    name: str
    base_url: str
    path: str
    auth: AuthConfig
    wire_format: WireFormat
    default_model: str
    extra_headers: Mapping[str, str] = field(default_factory=dict[str, str])


@dataclass(frozen=True, slots=True)
class ChatProviderConfig(EndpointConfig):
    # OpenAI's newer models reject "max_tokens"; most compatible APIs want it.
    max_tokens_param: str = "max_tokens"


@dataclass(frozen=True, slots=True)
class EmbeddingProviderConfig(EndpointConfig):
    # Largest number of texts sent per request; the adapter batches for you.
    max_batch_size: int = 64


_BEARER: Final = AuthConfig(AuthType.BEARER_TOKEN)

CHAT_PROVIDER_CONFIGS: Final[Mapping[LLMProvider, ChatProviderConfig]] = {
    LLMProvider.OLLAMA: ChatProviderConfig(
        name="Ollama (Local)",
        base_url="http://127.0.0.1:11434",
        path="/api/chat",
        auth=AuthConfig(AuthType.BEARER_TOKEN, api_key_required=False),
        wire_format=WireFormat.OLLAMA,
        default_model="llama3.2:3b",
    ),
    LLMProvider.OPENAI: ChatProviderConfig(
        name="OpenAI",
        base_url="https://api.openai.com/v1",
        path="/chat/completions",
        auth=_BEARER,
        wire_format=WireFormat.OPENAI,
        default_model="gpt-4o-mini",
        max_tokens_param="max_completion_tokens",
    ),
    LLMProvider.ANTHROPIC: ChatProviderConfig(
        name="Anthropic",
        base_url="https://api.anthropic.com/v1",
        path="/messages",
        auth=AuthConfig(AuthType.CUSTOM_HEADER, header_name="x-api-key"),
        wire_format=WireFormat.ANTHROPIC,
        default_model="claude-haiku-5-5",
        extra_headers={"anthropic-version": "2023-06-01"},
    ),
    LLMProvider.GOOGLE_GEMINI: ChatProviderConfig(
        name="Google Gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        path="/chat/completions",
        auth=_BEARER,
        wire_format=WireFormat.OPENAI,
        default_model="gemini-2.5-flash-lite",
    ),
    LLMProvider.MISTRAL: ChatProviderConfig(
        name="Mistral AI",
        base_url="https://api.mistral.ai/v1",
        path="/chat/completions",
        auth=_BEARER,
        wire_format=WireFormat.OPENAI,
        default_model="mistral-small-latest",
    ),
    LLMProvider.COHERE: ChatProviderConfig(
        name="Cohere",
        base_url="https://api.cohere.com/v2",
        path="/chat",
        auth=_BEARER,
        wire_format=WireFormat.COHERE,
        default_model="command-r-plus",
    ),
}

# Anthropic is intentionally absent: it has no embeddings API.
EMBEDDING_PROVIDER_CONFIGS: Final[Mapping[LLMProvider, EmbeddingProviderConfig]] = {
    LLMProvider.OLLAMA: EmbeddingProviderConfig(
        name="Ollama (Local)",
        base_url="http://127.0.0.1:11434",
        path="/api/embed",
        auth=AuthConfig(AuthType.BEARER_TOKEN, api_key_required=False),
        wire_format=WireFormat.OLLAMA,
        default_model="bge-m3",
        max_batch_size=32,
    ),
    LLMProvider.OPENAI: EmbeddingProviderConfig(
        name="OpenAI",
        base_url="https://api.openai.com/v1",
        path="/embeddings",
        auth=_BEARER,
        wire_format=WireFormat.OPENAI,
        default_model="text-embedding-3-small",
        max_batch_size=256,
    ),
    LLMProvider.GOOGLE_GEMINI: EmbeddingProviderConfig(
        name="Google Gemini",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        path="/embeddings",
        auth=_BEARER,
        wire_format=WireFormat.OPENAI,
        default_model="gemini-embedding-001",
        max_batch_size=100,
    ),
    LLMProvider.MISTRAL: EmbeddingProviderConfig(
        name="Mistral AI",
        base_url="https://api.mistral.ai/v1",
        path="/embeddings",
        auth=_BEARER,
        wire_format=WireFormat.OPENAI,
        default_model="mistral-embed",
        max_batch_size=32,
    ),
    LLMProvider.COHERE: EmbeddingProviderConfig(
        name="Cohere",
        base_url="https://api.cohere.com/v2",
        path="/embed",
        auth=_BEARER,
        wire_format=WireFormat.COHERE,
        default_model="embed-english-v3.0",
        max_batch_size=96,
    ),
}
