from abc import ABC, abstractmethod
from collections.abc import Sequence
from pathlib import Path

from codex_query.domain.models import Answer, Book, Chapter, SearchHit, TextChunk


class BookReader(ABC):
    @abstractmethod
    def read(self, path: Path) -> Book: ...


class IndexLedger(ABC):
    @abstractmethod
    def register_book(self, book: Book, series: str) -> None: ...

    @abstractmethod
    def chapters_to_index(
        self, book_id: str, chapters: Sequence[Chapter]
    ) -> list[Chapter]: ...

    @abstractmethod
    def mark_chapter_indexed(
        self, book_id: str, href: str, content_hash: str
    ) -> None: ...

    @abstractmethod
    def mark_chapter_failed(self, book_id: str, href: str, error: str) -> None: ...

    @abstractmethod
    def remove_stale_chapters(
        self, book_id: str, active_hrefs: set[str]
    ) -> list[str]: ...

    @abstractmethod
    def indexed_count(self, series: str) -> int: ...

    @abstractmethod
    def close(self) -> None: ...


class VectorStore(ABC):
    @abstractmethod
    def upsert(
        self,
        series: str,
        chunks: Sequence[TextChunk],
        embeddings: Sequence[Sequence[float]],
    ) -> None: ...

    @abstractmethod
    def delete_chapter(self, series: str, book_id: str, chapter_href: str) -> None: ...

    @abstractmethod
    def search(
        self, series: str, embedding: Sequence[float], limit: int
    ) -> list[SearchHit]: ...


class EmbeddingModel(ABC):
    @abstractmethod
    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class Generator(ABC):
    @abstractmethod
    def answer(self, question: str, context: Sequence[SearchHit]) -> str: ...


class QueryService(ABC):
    @abstractmethod
    def ask(self, series: str, question: str, limit: int = 6) -> Answer: ...
