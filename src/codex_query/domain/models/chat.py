from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum


class Role(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


@dataclass(frozen=True, slots=True)
class ChatMessage:
    role: Role
    content: str


@dataclass(frozen=True, slots=True)
class GenerationParams:
    temperature: float
    max_tokens: int
    # Only honoured by providers that let the caller size the context window
    # (currently Ollama's native API). Ignored by hosted providers.
    num_ctx: int | None = None


@dataclass(frozen=True, slots=True)
class TokenUsage:
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True, slots=True)
class SearchHit:
    text: str
    distance: float
    metadata: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class Answer:
    question: str
    answer: str
    sources: tuple[SearchHit, ...]
    usage: TokenUsage | None = None
    finish_reason: str | None = None


@dataclass(frozen=True, slots=True)
class ChatResult:
    text: str
    usage: TokenUsage | None = None
    finish_reason: str | None = None
