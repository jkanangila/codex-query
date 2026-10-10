"""ChromaDB-backed VectorStorePort (desktop). Requires the `desktop` extra.

Chroma holds only vectors, keyed by chunk id. Chunk text and metadata stay in
SQLite (the source of truth) and are hydrated through the unit-of-work session,
so nothing is duplicated.

Chroma writes are NOT part of the SQLite transaction: if the transaction rolls
back after an upsert, the vectors remain but hydration skips ids with no chunk.
Deleting a book through the database does not touch Chroma, so the delete-book
use case must also call `uow.vectors.delete_book(book_id)`.
"""

import asyncio
from collections.abc import Sequence
from typing import Any, override

from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection
from sqlmodel.ext.asyncio.session import AsyncSession

from codex_query.application.ports.vector_store import VectorStorePort
from codex_query.domain.errors import EmbeddingMismatchError
from codex_query.domain.models.chat import SearchHit
from codex_query.domain.models.document import TextChunk as DomainTextChunk
from codex_query.infrastructure.logging.factory import create_logger
from codex_query.infrastructure.persistence.sqlmodel.repositories.sqlmodel_hits import (
    load_hits,
)

logger = create_logger(__name__)


def _name(book_id: int) -> str:
    """Generate the standard Chroma collection name for a given book ID.

    Args:
        book_id: Database primary key of the target book.

    Returns:
        str: Formatted collection name identifier.
    """
    return f"codex_book_{book_id}"


class ChromaVectorStore(VectorStorePort):
    """ChromaDB implementation of `VectorStorePort`.

    Stores text chunk vector embeddings isolated per book within separate collections.
    """

    def __init__(self, client: ClientAPI, session: AsyncSession) -> None:
        """Initialize ChromaVectorStore with a Chroma client and active SQL session.

        Args:
            client: Chroma API client instance.
            session: Active database session for retrieving hit metadata.
        """
        self._client = client
        self._session = session

    def _collection(self, book_id: int) -> Collection:
        """Retrieve or create the Chroma collection for a specific book.

        Args:
            book_id: Database primary key of the target book.

        Returns:
            Collection: Chroma collection configured with cosine distance metric.
        """
        logger.debug("Retrieving or creating Chroma collection for book ID %d", book_id)
        return self._client.get_or_create_collection(
            name=_name(book_id),
            metadata={"hnsw:space": "cosine"},
            embedding_function=None,  # embeddings are always supplied by us
        )

    @staticmethod
    def _check_model(collection: Collection, book_id: int, model: str) -> None:
        """Verify that existing vectors in the collection match the target model.

        Args:
            collection: Target Chroma collection instance to check.
            book_id: Database primary key of the book.
            model: Expected embedding model name identifier.

        Raises:
            EmbeddingMismatchError: If vectors exist and were embedded with a
                different model.
        """
        sample = collection.get(limit=1, include=["metadatas"])
        metas: Any = sample["metadatas"] or []
        if metas and metas[0] and metas[0].get("model") != model:
            stored_model = metas[0].get("model")
            logger.error(
                "Embedding model mismatch for book ID %d: expected %r, found %r",
                book_id,
                model,
                stored_model,
            )
            raise EmbeddingMismatchError(
                f"Book {book_id} was indexed with {stored_model!r}, "
                f"not {model!r}. Delete its embeddings and re-index."
            )

    @override
    async def upsert(
        self,
        chunks: Sequence[DomainTextChunk],
        embeddings: Sequence[Sequence[float]],
        model: str,
    ) -> None:
        """Persist chunk embeddings to vector storage grouped by book.

        Args:
            chunks: Sequence of domain text chunk objects to store.
            embeddings: Parallel sequence of floating point vector embeddings.
            model: Embedding model name used to create the vectors.

        Raises:
            ValueError: If lengths of chunks and embeddings mismatch, or if any
                chunk lacks a primary key ID.
        """
        if len(chunks) != len(embeddings):
            logger.error(
                "Length mismatch in upsert: %d chunks vs %d embeddings",
                len(chunks),
                len(embeddings),
            )
            raise ValueError("chunks and embeddings must have the same length")

        by_book: dict[int, list[int]] = {}
        for i, chunk in enumerate(chunks):
            if chunk.id is None:
                logger.error("Chunk at index %d has no set database ID", i)
                raise ValueError("chunks must be persisted (id set) before embedding")
            by_book.setdefault(chunk.meta.book_id, []).append(i)

        logger.debug(
            "Upserting %d total vector(s) across %d book(s)",
            len(chunks),
            len(by_book),
        )

        for book_id, positions in by_book.items():
            await asyncio.to_thread(
                self._upsert_book, book_id, positions, chunks, embeddings, model
            )
            logger.info("Upserted %d vector(s) for book ID %d", len(positions), book_id)

    def _upsert_book(
        self,
        book_id: int,
        positions: Sequence[int],
        chunks: Sequence[DomainTextChunk],
        embeddings: Sequence[Sequence[float]],
        model: str,
    ) -> None:
        """Synchronously upsert a subset of vectors belonging to a single book.

        Args:
            book_id: Database primary key of the target book.
            positions: Sequence of indices corresponding to chunks and embeddings.
            chunks: Full sequence of domain text chunk objects.
            embeddings: Full sequence of floating point vector embeddings.
            model: Embedding model name used to create the vectors.
        """
        collection = self._collection(book_id)
        self._check_model(collection, book_id, model)
        collection.upsert(
            ids=[str(chunks[i].id) for i in positions],
            embeddings=[list(embeddings[i]) for i in positions],
            metadatas=[{"model": model} for _ in positions],
        )

    @override
    async def search(
        self,
        book_id: int,
        query: Sequence[float],
        top_k: int,
        model: str,
    ) -> list[SearchHit]:
        """Perform vector similarity search against a specific book's collection.

        Args:
            book_id: Database primary key of the target book.
            query: Query vector embedding floats.
            top_k: Maximum number of closest matches to return.
            model: Expected embedding model identifier.

        Returns:
            list[SearchHit]: Ranked collection of search hit results.
        """
        if top_k <= 0:
            logger.debug("search called with top_k <= 0 for book ID %d", book_id)
            return []

        logger.debug(
            "Searching vector store for book ID %d (top_k=%d, model=%s)",
            book_id,
            top_k,
            model,
        )
        ids, distances = await asyncio.to_thread(
            self._query, book_id, list(query), top_k, model
        )
        logger.debug(
            "Vector query returned %d hit ID(s) for book ID %d", len(ids), book_id
        )
        return await load_hits(self._session, ids, distances)

    def _query(
        self, book_id: int, query: list[float], top_k: int, model: str
    ) -> tuple[list[int], list[float]]:
        """Synchronously execute a vector similarity query against Chroma.

        Args:
            book_id: Database primary key of the target book.
            query: List of floating point query vector values.
            top_k: Maximum number of closest matches to return.
            model: Expected embedding model identifier.

        Returns:
            tuple[list[int], list[float]]: Tuple containing matched chunk database
                IDs and their corresponding cosine distances.
        """
        collection = self._collection(book_id)
        total = collection.count()
        if total == 0:
            logger.debug(
                "Collection for book ID %d is empty; returning 0 hits", book_id
            )
            return [], []

        self._check_model(collection, book_id, model)
        result = collection.query(
            query_embeddings=[query],
            n_results=min(top_k, total),
            include=["distances"],
        )
        ids = (result["ids"] or [[]])[0]
        distances = (result["distances"] or [[]])[0]
        return [int(i) for i in ids], [float(d) for d in distances]

    @override
    async def count(self, book_id: int) -> int:
        """Count total vectors stored in the collection for a specific book.

        Args:
            book_id: Database primary key of the target book.

        Returns:
            int: Number of vectors currently stored in the collection.
        """
        logger.debug("Counting vectors for book ID %d", book_id)
        total = await asyncio.to_thread(lambda: self._collection(book_id).count())
        logger.debug("Book ID %d collection count: %d", book_id, total)
        return total

    @override
    async def delete_book(self, book_id: int) -> None:
        """Delete the entire vector collection associated with a book.

        Args:
            book_id: Database primary key of the target book.
        """
        logger.info("Deleting vector collection for book ID %d", book_id)

        def _delete() -> None:
            self._collection(book_id)  # ensure it exists so delete never raises
            self._client.delete_collection(_name(book_id))

        await asyncio.to_thread(_delete)
        logger.info("Successfully deleted vector collection for book ID %d", book_id)
