"""SQLModel and NumPy vector store for L2-normalized chunk embeddings."""

import asyncio
from collections import OrderedDict
from collections.abc import Sequence
from dataclasses import dataclass
from time import time_ns
from typing import Any, override

import numpy as np
import numpy.typing as npt
from sqlalchemy import delete
from sqlalchemy.dialects.sqlite import insert
from sqlmodel import col, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from codex_query.application.ports.vector_store import VectorStorePort
from codex_query.domain.errors import EmbeddingMismatchError
from codex_query.domain.models.chat import SearchHit
from codex_query.domain.models.document import TextChunk as DomainTextChunk
from codex_query.infrastructure.database.sqlmodel.models import ChunkEmbedding
from codex_query.infrastructure.database.sqlmodel.repositories.sqlmodel_hits import (
    load_hits,
)
from codex_query.infrastructure.logging.factory import create_logger

type Matrix = npt.NDArray[np.float32]

logger = create_logger(__name__)

# SQLite < 3.32 allows only 999 bound variables per statement.
_COLUMNS_PER_ROW = 6
_MAX_ROWS_PER_STMT = 900 // _COLUMNS_PER_ROW  # 150
_DELETE_BATCH = 500


@dataclass(frozen=True, slots=True)
class _Stamp:
    """Cheap fingerprint of a book's stored embeddings used to validate the cache.

    Any upsert bumps `max_stored_ns`, and any delete changes `count`, `min_id`,
    or `max_id`. Validating directly against the database keeps the cache
    accurate across sessions, uncommitted writes, and concurrent readers.
    """

    count: int
    min_id: int
    max_id: int
    max_stored_ns: int


@dataclass(frozen=True, slots=True)
class _BookIndex:
    """In-memory similarity search index for a single book's embeddings."""

    stamp: _Stamp
    model: str
    dim: int
    ids: npt.NDArray[np.int64]
    matrix: Matrix  # shape (n, dim), unit-length rows


class EmbeddingCache:
    """Bounded LRU cache of per-book embedding matrices.

    Shared across unit-of-work instances by default and validated against
    database stamps rather than in-process invalidation hooks.
    """

    def __init__(self, max_books: int = 3) -> None:
        """Initialize the LRU cache with a maximum number of cached books.

        Args:
            max_books: Maximum number of per-book indices retained in memory.
        """
        self._items: OrderedDict[int, _BookIndex] = OrderedDict()
        self._max_books = max_books

    def get(self, book_id: int, stamp: _Stamp) -> _BookIndex | None:
        """Return a cached book index if present and matching `stamp`.

        Args:
            book_id: Primary key of the target book.
            stamp: Expected embedding state fingerprint for `book_id`.

        Returns:
            Cached book index when `stamp` matches, otherwise `None`.
        """
        item = self._items.get(book_id)
        if item is None or item.stamp != stamp:
            return None
        self._items.move_to_end(book_id)
        return item

    def put(self, book_id: int, index: _BookIndex) -> None:
        """Insert or update a book index and evict oldest entries past capacity.

        Args:
            book_id: Primary key of the target book.
            index: Built similarity search index for `book_id`.
        """
        self._items[book_id] = index
        self._items.move_to_end(book_id)
        while len(self._items) > self._max_books:
            evicted_book_id, _ = self._items.popitem(last=False)
            logger.debug(
                "Evicted book ID %d from embedding cache (max_books=%d)",
                evicted_book_id,
                self._max_books,
            )

    def drop(self, book_id: int) -> None:
        """Remove any cached index for `book_id` if present.

        Args:
            book_id: Primary key of the target book.
        """
        if self._items.pop(book_id, None) is not None:
            logger.debug("Dropped book ID %d from embedding cache", book_id)


DEFAULT_CACHE = EmbeddingCache()


class SqlModelVectorStore(VectorStorePort):
    """SQLite and NumPy vector store sharing the chunk database and transaction.

    Embeddings are stored L2-normalized so cosine similarity reduces to a dot
    product. Session flushes and statement executions run within the current
    session; transaction commits are managed by `UnitOfWork`.
    """

    def __init__(
        self, session: AsyncSession, cache: EmbeddingCache | None = None
    ) -> None:
        """Initialize the vector store with an async session and optional cache.

        Args:
            session: Active session bound to the current unit of work.
            cache: Shared `EmbeddingCache` instance; defaults to `DEFAULT_CACHE`.
        """
        self._session = session
        self._cache = cache if cache is not None else DEFAULT_CACHE

    @override
    async def upsert(
        self,
        chunks: Sequence[DomainTextChunk],
        embeddings: Sequence[Sequence[float]],
        model: str,
    ) -> None:
        """Normalize and upsert chunk embeddings on `chunk_id` in capped batches.

        Args:
            chunks: Persisted domain text chunks corresponding to `embeddings`.
            embeddings: Vector representations aligned one-to-one with `chunks`.
            model: Identifier of the embedding model that produced the vectors.

        Raises:
            ValueError: If `chunks` and `embeddings` have different lengths,
                `embeddings` is not a 2D array, or any chunk lacks an `id`.
            EmbeddingMismatchError: If a book already stores embeddings with a
                different model or dimension.
        """
        if len(chunks) != len(embeddings):
            raise ValueError("chunks and embeddings must have the same length")
        if not chunks:
            return
        raw = np.asarray(embeddings, dtype=np.float32)
        if raw.ndim != 2:
            raise ValueError("embeddings must be equal-length vectors")
        matrix = _normalize_rows(raw)
        dim = int(matrix.shape[1])
        stored_ns = time_ns()

        rows_by_book: dict[int, list[dict[str, Any]]] = {}
        for chunk, vec in zip(chunks, matrix, strict=True):
            if chunk.id is None:
                raise ValueError("chunks must be persisted (id set) before embedding")
            book_id = chunk.meta.book_id
            rows_by_book.setdefault(book_id, []).append(
                {
                    "chunk_id": chunk.id,
                    "book_id": book_id,
                    "model": model,
                    "dim": dim,
                    "vector": vec.tobytes(),
                    "stored_at_ns": stored_ns,
                }
            )

        for book_id, rows in rows_by_book.items():
            await self._ensure_compatible(book_id, model, dim)
            for i in range(0, len(rows), _MAX_ROWS_PER_STMT):
                stmt = insert(ChunkEmbedding).values(rows[i : i + _MAX_ROWS_PER_STMT])
                stmt = stmt.on_conflict_do_update(
                    index_elements=["chunk_id"],
                    set_={
                        "model": stmt.excluded.model,
                        "dim": stmt.excluded.dim,
                        "vector": stmt.excluded.vector,
                        "stored_at_ns": stmt.excluded.stored_at_ns,
                    },
                )
                await self._session.exec(stmt)
            logger.info("Upserted %d embedding(s) for book ID %d", len(rows), book_id)

    @override
    async def search(
        self,
        book_id: int,
        query: Sequence[float],
        top_k: int,
        model: str,
    ) -> list[SearchHit]:
        """Rank stored chunk embeddings for a book by cosine similarity to `query`.

        Args:
            book_id: Primary key of the book to search.
            query: Query embedding vector.
            top_k: Maximum number of search hits to return.
            model: Expected embedding model identifier for the book.

        Returns:
            Top matching `SearchHit` results ordered by descending similarity.

        Raises:
            EmbeddingMismatchError: If the book's stored model or dimension does
                not match `model` or `query`.
        """
        if top_k <= 0:
            return []
        stamp = await self._stamp(book_id)
        if stamp is None:
            logger.debug("No embeddings found for book ID %d during search", book_id)
            return []
        index = self._cache.get(book_id, stamp)
        if index is None:
            logger.debug("Embedding cache miss for book ID %d; loading index", book_id)
            index = await self._load_index(book_id, stamp)
        else:
            logger.debug("Embedding cache hit for book ID %d", book_id)
        if index.model != model:
            logger.warning(
                "Embedding model mismatch for book ID %d: expected %r, got %r",
                book_id,
                model,
                index.model,
            )
            raise EmbeddingMismatchError(
                f"Book {book_id} was indexed with {index.model!r}, not {model!r}. "
                "Re-index it after changing the embedding model."
            )
        q = np.asarray(query, dtype=np.float32)
        if q.shape != (index.dim,):
            logger.warning(
                "Query dimension mismatch for book ID %d: expected %d, got %d",
                book_id,
                index.dim,
                q.size,
            )
            raise EmbeddingMismatchError(
                f"Query has {q.size} dimensions; book {book_id} uses {index.dim}."
            )

        positions, scores = await asyncio.to_thread(_rank, index.matrix, q, top_k)
        ordered_ids = [int(index.ids[p]) for p in positions]

        return await load_hits(self._session, ordered_ids, [1.0 - x for x in scores])

    @override
    async def count(self, book_id: int) -> int:
        """Count stored embeddings for a book.

        Args:
            book_id: Primary key of the target book.

        Returns:
            Number of stored chunk embeddings for `book_id`.
        """
        result = await self._session.exec(
            select(func.count())
            .select_from(ChunkEmbedding)
            .where(col(ChunkEmbedding.book_id) == book_id)
        )
        return result.one()

    @override
    async def delete_book(self, book_id: int) -> None:
        """Delete all stored embeddings and invalidate cache for a book.

        Args:
            book_id: Primary key of the target book.
        """
        logger.info("Deleting embeddings for book ID %d", book_id)
        await self._session.exec(
            delete(ChunkEmbedding).where(col(ChunkEmbedding.book_id) == book_id)
        )
        self._cache.drop(book_id)

    @override
    async def embedded_chunk_ids(self, book_id: int) -> frozenset[int]:
        """Return chunk IDs that currently have stored embeddings for a book.

        Args:
            book_id: Primary key of the target book.

        Returns:
            Set of embedded chunk primary keys for `book_id`.
        """
        result = await self._session.exec(
            select(col(ChunkEmbedding.chunk_id)).where(
                col(ChunkEmbedding.book_id) == book_id
            )
        )
        return frozenset(result.all())

    @override
    async def delete_chunks(self, book_id: int, chunk_ids: Sequence[int]) -> None:
        """Delete embeddings for specific chunk IDs and invalidate cache for `book_id`.

        Args:
            book_id: Primary key of the parent book whose cache entry is dropped.
            chunk_ids: Chunk primary keys whose embeddings should be deleted.
        """
        ids = list(chunk_ids)
        if not ids:
            return
        logger.info(
            "Deleting embeddings for %d chunk(s) in book ID %d", len(ids), book_id
        )
        for i in range(0, len(ids), _DELETE_BATCH):
            await self._session.exec(
                delete(ChunkEmbedding).where(
                    col(ChunkEmbedding.chunk_id).in_(ids[i : i + _DELETE_BATCH])
                )
            )
        self._cache.drop(book_id)

    # -- internals ------------------------------------------------------

    async def _ensure_compatible(self, book_id: int, model: str, dim: int) -> None:
        """Verify incoming `model` and `dim` match existing embeddings for `book_id`.

        Args:
            book_id: Primary key of the target book.
            model: Incoming embedding model identifier.
            dim: Incoming embedding vector dimension.

        Raises:
            EmbeddingMismatchError: If existing rows use another model or dimension.
        """
        result = await self._session.exec(
            select(col(ChunkEmbedding.model), col(ChunkEmbedding.dim))
            .where(col(ChunkEmbedding.book_id) == book_id)
            .limit(1)
        )
        existing = result.first()
        if existing is not None and tuple(existing) != (model, dim):
            raise EmbeddingMismatchError(
                f"Book {book_id} is indexed with {existing[0]!r} ({existing[1]}-dim); "
                f"got {model!r} ({dim}-dim). Delete its embeddings and re-index."
            )

    async def _stamp(self, book_id: int) -> _Stamp | None:
        """Fetch an aggregate fingerprint of stored embeddings for `book_id`.

        Args:
            book_id: Primary key of the target book.

        Returns:
            Current `_Stamp` for `book_id`, or `None` if no embeddings exist.
        """
        result = await self._session.exec(
            select(
                func.count(),
                func.min(col(ChunkEmbedding.chunk_id)),
                func.max(col(ChunkEmbedding.chunk_id)),
                func.max(col(ChunkEmbedding.stored_at_ns)),
            ).where(col(ChunkEmbedding.book_id) == book_id)
        )
        count, lo, hi, newest = result.one()
        if count == 0:
            return None
        return _Stamp(count, lo, hi, newest)

    async def _load_index(self, book_id: int, stamp: _Stamp) -> _BookIndex:
        """Load a book's embeddings from the database into the cache.

        Args:
            book_id: Primary key of the target book.
            stamp: Cache validation stamp associated with this snapshot.

        Returns:
            Newly built and cached `_BookIndex`.

        Raises:
            EmbeddingMismatchError: If `book_id` contains mixed models or dimensions.
        """
        variants = (
            await self._session.exec(
                select(col(ChunkEmbedding.model), col(ChunkEmbedding.dim))
                .where(col(ChunkEmbedding.book_id) == book_id)
                .distinct()
                .limit(2)
            )
        ).all()
        if len(variants) != 1:
            raise EmbeddingMismatchError(
                f"Book {book_id} has mixed embedding models/dimensions; re-index it."
            )
        model, dim = variants[0]

        result = await self._session.exec(
            select(col(ChunkEmbedding.chunk_id), col(ChunkEmbedding.vector))
            .where(col(ChunkEmbedding.book_id) == book_id)
            .order_by(col(ChunkEmbedding.chunk_id))
        )
        rows = [(int(r[0]), bytes(r[1])) for r in result.all()]
        index = await asyncio.to_thread(_build_index, stamp, model, dim, rows)
        self._cache.put(book_id, index)
        logger.debug(
            "Loaded %d embedding vector(s) for book ID %d (model=%r, dim=%d)",
            len(rows),
            book_id,
            model,
            dim,
        )
        return index


def _normalize_rows(m: Matrix) -> Matrix:
    """L2-normalize each row of `m`, leaving zero-norm rows unchanged.

    Args:
        m: 2D array of embedding vectors.

    Returns:
        Row-normalized `float32` matrix with the same shape as `m`.
    """
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (m / norms).astype(np.float32)


def _build_index(
    stamp: _Stamp, model: str, dim: int, rows: Sequence[tuple[int, bytes]]
) -> _BookIndex:
    """Assemble chunk IDs and a stacked `float32` matrix from stored rows.

    Args:
        stamp: Cache validation stamp for the loaded rows.
        model: Embedding model identifier for all rows.
        dim: Embedding vector dimension.
        rows: Ordered `(chunk_id, vector_bytes)` pairs.

    Returns:
        Constructed `_BookIndex` ready for similarity ranking.
    """
    ids = np.fromiter((r[0] for r in rows), dtype=np.int64, count=len(rows))
    matrix = np.stack([np.frombuffer(r[1], dtype=np.float32) for r in rows])
    return _BookIndex(stamp=stamp, model=model, dim=dim, ids=ids, matrix=matrix)


def _rank(matrix: Matrix, query: Matrix, top_k: int) -> tuple[list[int], list[float]]:
    """Compute top-`top_k` row indices and cosine similarity scores for `query`.

    Args:
        matrix: 2D unit-length embedding matrix of shape `(n, dim)`.
        query: 1D query vector of shape `(dim,)`.
        top_k: Maximum number of top-scoring rows to return.

    Returns:
        Tuple of `(indices, scores)` sorted by descending similarity score.
    """
    norm = float(np.linalg.norm(query))
    unit = query / norm if norm > 0 else query
    scores = matrix @ unit
    k = min(top_k, int(scores.shape[0]))
    top = np.argpartition(-scores, k - 1)[:k]
    top = top[np.argsort(-scores[top])]
    return [int(i) for i in top], [float(scores[i]) for i in top]
