from collections.abc import Sequence
from typing import Protocol

from codex_query.domain.models.chat import SearchHit
from codex_query.domain.models.document import TextChunk


class VectorStorePort(Protocol):
    """Per-book embedding storage and cosine-similarity search.

    `SearchHit.distance` is cosine distance (0 = identical, 2 = opposite).
    """

    async def upsert(
        self,
        chunks: Sequence[TextChunk],
        embeddings: Sequence[Sequence[float]],
        model: str,
    ) -> None:
        """Store embeddings for already-persisted chunks (chunk.id must be set).

        Idempotent per chunk id, so a resumed indexing job can safely re-send.
        Raises EmbeddingMismatchError if the book was indexed with another
        model or dimension.
        """

    async def search(
        self,
        book_id: int,
        query: Sequence[float],
        top_k: int,
        model: str,
    ) -> list[SearchHit]:
        """Return up to top_k hits for one book, best match first."""
        ...

    async def count(self, book_id: int) -> int: ...

    async def delete_book(self, book_id: int) -> None: ...
