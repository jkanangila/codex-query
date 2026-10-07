from enum import StrEnum
from typing import TypedDict


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


class EndpointsConfig(TypedDict):
    chat: str
    embeddings: str


class AuthConfig(TypedDict):
    type: AuthType
    header_name: str | None


class ProviderConfig(TypedDict):
    name: str
    base_url: str
    auth: AuthConfig
    endpoints: EndpointsConfig
    default_models: dict[str, str]


PROVIDER_CONFIGS: dict[LLMProvider, ProviderConfig] = {
    LLMProvider.OLLAMA: {
        "name": "Ollama (Local)",
        "base_url": "http://127.0.0.1:11434/v1",
        "auth": {
            "type": AuthType.BEARER_TOKEN,
            "header_name": None,
        },
        "endpoints": {
            "chat": "/chat/completions",
            "embeddings": "/embeddings",
        },
        "default_models": {
            "chat": "llama3.2:3b",
            "embeddings": "bge-m3",
        },
    },
    LLMProvider.OPENAI: {
        "name": "OpenAI",
        "base_url": "https://api.openai.com/v1",
        "auth": {
            "type": AuthType.BEARER_TOKEN,
            "header_name": "Authorization",
        },
        "endpoints": {
            "chat": "/chat/completions",
            "embeddings": "/embeddings",
        },
        "default_models": {
            "chat": "gpt-4o-mini",
            "embeddings": "text-embedding-3-small",
        },
    },
    LLMProvider.ANTHROPIC: {
        "name": "Anthropic",
        "base_url": "https://api.anthropic.com/v1",
        "auth": {
            "type": AuthType.CUSTOM_HEADER,
            "header_name": "x-api-key",
        },
        "endpoints": {
            "chat": "/messages",
            "embeddings": "",  # Requires external embedding provider
        },
        "default_models": {
            "chat": "claude-3-5-sonnet-20241022",
            "embeddings": "none",
        },
    },
    LLMProvider.GOOGLE_GEMINI: {
        "name": "Google Gemini",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "auth": {
            "type": AuthType.BEARER_TOKEN,
            "header_name": "Authorization",
        },
        "endpoints": {
            "chat": "/chat/completions",
            "embeddings": "/embeddings",
        },
        "default_models": {
            "chat": "gemini-1.5-flash",
            "embeddings": "text-embedding-004",
        },
    },
    LLMProvider.MISTRAL: {
        "name": "Mistral AI",
        "base_url": "https://api.mistral.ai/v1",
        "auth": {
            "type": AuthType.BEARER_TOKEN,
            "header_name": "Authorization",
        },
        "endpoints": {
            "chat": "/chat/completions",
            "embeddings": "/embeddings",
        },
        "default_models": {
            "chat": "mistral-small-latest",
            "embeddings": "mistral-embed",
        },
    },
    LLMProvider.COHERE: {
        "name": "Cohere",
        "base_url": "https://api.cohere.com/v2",
        "auth": {
            "type": AuthType.BEARER_TOKEN,
            "header_name": "Authorization",
        },
        "endpoints": {
            "chat": "/chat",
            "embeddings": "/embed",
        },
        "default_models": {
            "chat": "command-r-plus",
            "embeddings": "embed-english-v3.0",
        },
    },
}
