from dataclasses import dataclass
from enum import StrEnum
from typing import TypedDict


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


class SearchHitMeta(TypedDict):
    # book info
    book_id: int
    book_title: str
    series: str | None
    # chapter info
    chapter_id: int
    chapter_href: str
    chapter_title: str
    chapter_order: int
    # chunk info
    chunk_id: int
    chunk_index: int


# RetrievedChunk (VectorStore Search)
@dataclass(frozen=True, slots=True)
class SearchHit:
    text: str
    distance: float
    metadata: SearchHitMeta


# @dataclass(frozen=True, slots=True)
# class Answer:
#     question: str
#     answer: str
#     sources: tuple[SearchHit, ...]
#     usage: TokenUsage | None = None
#     finish_reason: str | None = None


@dataclass(frozen=True, slots=True)
class ChatResult:
    text: str
    usage: TokenUsage | None = None
    finish_reason: str | None = None
