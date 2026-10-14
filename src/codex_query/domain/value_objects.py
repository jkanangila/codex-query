from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from codex_query.application.use_cases.settings.check_embedding_compatibility import (
    StaleBook,
)
from codex_query.domain.models.settings import Settings


@dataclass(frozen=True, slots=True)
class Source:
    """A passage retrieved from a book to ground an answer (a RAG "citation")."""

    chapter: str
    page: int | None
    score: float  # similarity score reported by the retriever (higher = closer)
    text: str

    @property
    def label(self) -> str:
        """Short human label, e.g. ``"Ch. 9 · p.118"`` (page omitted if unknown)."""
        return f"{self.chapter} · p.{self.page}" if self.page else self.chapter
