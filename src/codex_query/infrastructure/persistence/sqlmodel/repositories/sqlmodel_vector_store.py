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
from codex_query.infrastructure.logging.factory import create_logger
from codex_query.infrastructure.persistence.sqlmodel.models import ChunkEmbedding
from codex_query.infrastructure.persistence.sqlmodel.repositories.sqlmodel_hits import (
    load_hits,
)

type Matrix = npt.NDArray[np.float32]

logger = create_logger(__name__)

# SQLite < 3.32 allows only 999 bound variables per statement.
_COLUMNS_PER_ROW = 6
_MAX_ROWS_PER_STMT = 900 // _COLUMNS_PER_ROW  # 150
_DELETE_BATCH = 500


@dataclass(frozen=True, slots=True)
class _Stamp:
    """Cheap fingerprint of a book's stored embeddings, used to validate the cache.

    Any upsert bumps `max_stored_ns`; any delete changes `count`/`min_id`/`max_id`.
    Validating against the database (not in-process invalidation) keeps the cache
    correct across sessions, uncommitted writes, and concurrent readers.
    """

    count: int
    min_id: int
    max_id: int
    max_stored_ns: int


@dataclass(frozen=True, slots=True)
class _BookIndex:
    stamp: _Stamp
    model: str
    dim: int
    ids: npt.NDArray[np.int64]
    matrix: Matrix  # shape (n, dim), unit-length rows


class EmbeddingCache:
    """Small LRU of per-book matrices, shared across unit-of-work instances."""

    def __init__(self, max_books: int = 3) -> None:
        self._items: OrderedDict[int, _BookIndex] = OrderedDict()
        self._max_books = max_books

    def get(self, book_id: int, stamp: _Stamp) -> _BookIndex | None:
        item = self._items.get(book_id)
        if item is None or item.stamp != stamp:
            return None
        self._items.move_to_end(book_id)
        return item

    def put(self, book_id: int, index: _BookIndex) -> None:
        self._items[book_id] = index
        self._items.move_to_end(book_id)
        while len(self._items) > self._max_books:
            self._items.popitem(last=False)

    def drop(self, book_id: int) -> None:
        self._items.pop(book_id, None)


DEFAULT_CACHE = EmbeddingCache()


class SqlModelVectorStore(VectorStorePort):
    """SQLite + numpy vector store living in the same database and transaction as
    the chunks. Embeddings are stored L2-normalized, so cosine similarity is a dot
    product. Transaction commits are managed by the UnitOfWork.
    """

    def __init__(
        self, session: AsyncSession, cache: EmbeddingCache | None = None
    ) -> None:
        self._session = session
        self._cache = cache if cache is not None else DEFAULT_CACHE

    @override
    async def upsert(
        self,
        chunks: Sequence[DomainTextChunk],
        embeddings: Sequence[Sequence[float]],
        model: str,
    ) -> None:
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
        if top_k <= 0:
            return []
        stamp = await self._stamp(book_id)
        if stamp is None:
            return []
        index = self._cache.get(book_id, stamp)
        if index is None:
            index = await self._load_index(book_id, stamp)
        if index.model != model:
            raise EmbeddingMismatchError(
                f"Book {book_id} was indexed with {index.model!r}, not {model!r}. "
                "Re-index it after changing the embedding model."
            )
        q = np.asarray(query, dtype=np.float32)
        if q.shape != (index.dim,):
            raise EmbeddingMismatchError(
                f"Query has {q.size} dimensions; book {book_id} uses {index.dim}."
            )

        positions, scores = await asyncio.to_thread(_rank, index.matrix, q, top_k)
        ordered_ids = [int(index.ids[p]) for p in positions]

        return await load_hits(self._session, ordered_ids, [1.0 - x for x in scores])

    @override
    async def count(self, book_id: int) -> int:
        result = await self._session.exec(
            select(func.count())
            .select_from(ChunkEmbedding)
            .where(col(ChunkEmbedding.book_id) == book_id)
        )
        return result.one()

    @override
    async def delete_book(self, book_id: int) -> None:
        logger.info("Deleting embeddings for book ID %d", book_id)
        await self._session.exec(
            delete(ChunkEmbedding).where(col(ChunkEmbedding.book_id) == book_id)
        )
        self._cache.drop(book_id)

    @override
    async def embedded_chunk_ids(self, book_id: int) -> frozenset[int]:
        result = await self._session.exec(
            select(col(ChunkEmbedding.chunk_id)).where(
                col(ChunkEmbedding.book_id) == book_id
            )
        )
        return frozenset(result.all())

    @override
    async def delete_chunks(self, book_id: int, chunk_ids: Sequence[int]) -> None:
        ids = list(chunk_ids)
        for i in range(0, len(ids), _DELETE_BATCH):
            await self._session.exec(
                delete(ChunkEmbedding).where(
                    col(ChunkEmbedding.chunk_id).in_(ids[i : i + _DELETE_BATCH])
                )
            )
        self._cache.drop(book_id)

    # -- internals ------------------------------------------------------

    async def _ensure_compatible(self, book_id: int, model: str, dim: int) -> None:
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
        """One cheap query (index-only on book_id) used to validate the cache."""
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
        """Cache miss: read model/dim, then the whole book's matrix."""
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
        return index


def _normalize_rows(m: Matrix) -> Matrix:
    norms = np.linalg.norm(m, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    return (m / norms).astype(np.float32)


def _build_index(
    stamp: _Stamp, model: str, dim: int, rows: Sequence[tuple[int, bytes]]
) -> _BookIndex:
    ids = np.fromiter((r[0] for r in rows), dtype=np.int64, count=len(rows))
    matrix = np.stack([np.frombuffer(r[1], dtype=np.float32) for r in rows])
    return _BookIndex(stamp=stamp, model=model, dim=dim, ids=ids, matrix=matrix)


def _rank(matrix: Matrix, query: Matrix, top_k: int) -> tuple[list[int], list[float]]:
    norm = float(np.linalg.norm(query))
    unit = query / norm if norm > 0 else query
    scores = matrix @ unit
    k = min(top_k, int(scores.shape[0]))
    top = np.argpartition(-scores, k - 1)[:k]
    top = top[np.argsort(-scores[top])]
    return [int(i) for i in top], [float(scores[i]) for i in top]
