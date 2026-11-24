from collections.abc import Sequence
from typing import Protocol

from codex_query.domain.models.chat import SearchHit
from codex_query.domain.models.document import TextChunk


class VectorStorePort(Protocol):
    """Per-book embedding storage and cosine-similarity search contract.

    `SearchHit.distance` is cosine distance (`0.0` = identical, `2.0` =
    opposite).
    """

    async def upsert(
        self,
        chunks: Sequence[TextChunk],
        embeddings: Sequence[Sequence[float]],
        model: str,
    ) -> None:
        """Store embeddings for already-persisted chunks.

        Idempotent per chunk ID so a resumed indexing job can safely re-send
        existing vectors.

        Args:
            chunks: Persisted text chunks with `chunk.id` set.
            embeddings: Vector representations aligned one-to-one with `chunks`.
            model: Identifier of the embedding model that produced the vectors.

        Raises:
            EmbeddingMismatchError: If the book is already indexed with a
                different model or dimension.
            ValueError: If `chunks` and `embeddings` have mismatched lengths,
                malformed vector shapes, or unpersisted chunks without an ID.
        """
        ...

    async def search(
        self,
        book_id: int,
        query: Sequence[float],
        top_k: int,
        model: str,
    ) -> list[SearchHit]:
        """Return up to `top_k` similarity matches for a book, best first.

        Args:
            book_id: Identifier of the book to search.
            query: Query embedding vector.
            top_k: Maximum number of search hits to return.
            model: Expected embedding model identifier for the book.

        Returns:
            Matching `SearchHit` results ordered by increasing distance.

        Raises:
            EmbeddingMismatchError: If the book's stored model or dimension does
                not match `model` or `query`.
        """
        ...

    async def count(self, book_id: int) -> int:
        """Count stored embeddings for a book.

        Args:
            book_id: Identifier of the target book.

        Returns:
            Number of stored chunk embeddings for the book.
        """
        ...

    async def delete_book(self, book_id: int) -> None:
        """Delete all stored embeddings for a book.

        Args:
            book_id: Identifier of the target book.
        """
        ...

    async def embedded_chunk_ids(self, book_id: int) -> frozenset[int]:
        """Return IDs of chunks for a book that already have stored vectors.

        Args:
            book_id: Identifier of the target book.

        Returns:
            Set of chunk IDs with stored embeddings for the book.
        """
        ...

    async def delete_chunks(self, book_id: int, chunk_ids: Sequence[int]) -> None:
        """Delete stored vectors for specific chunks of a book.

        Unknown chunk IDs are ignored.

        Args:
            book_id: Identifier of the target book.
            chunk_ids: Chunk IDs whose embeddings should be removed.
        """
        ...
