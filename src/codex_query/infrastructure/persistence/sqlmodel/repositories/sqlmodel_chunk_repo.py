from collections.abc import Sequence
from dataclasses import asdict, fields, replace
from typing import Any, override

from sqlalchemy import delete
from sqlalchemy.dialects.sqlite import insert
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from codex_query.application.ports.library import IChunkRepository
from codex_query.domain.models.document import TextChunk as DomainTextChunk
from codex_query.domain.models.document import TextChunkMetadata
from codex_query.infrastructure.persistence.sqlmodel.models import Chapter, TextChunk

_META_FIELDS = {f.name for f in fields(TextChunkMetadata)}

# SQLite < 3.32 allows only 999 bound variables per statement.
_COLUMNS_PER_ROW = 5
_MAX_ROWS_PER_STMT = 900 // _COLUMNS_PER_ROW  # 180


class SQLModelChunkRepository(IChunkRepository):
    """SQLModel-backed chunk repository. Flushes only; the UnitOfWork commits."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def get_all_for_book(
        self, book_id: int, after_id: int | None = None, limit: int = 100
    ) -> Sequence[DomainTextChunk]:
        stmt = (
            select(TextChunk)
            .join(Chapter, col(TextChunk.chapter_id) == col(Chapter.id))
            .where(col(Chapter.book_id) == book_id)
        )
        if after_id is not None:
            stmt = stmt.where(col(TextChunk.id) > after_id)
        stmt = stmt.order_by(col(TextChunk.id)).limit(limit)

        result = await self._session.exec(stmt)
        return [_to_domain(c) for c in result.all()]

    @override
    async def get_ids_for_chapter(self, chapter_id: int) -> Sequence[int]:
        stmt = select(col(TextChunk.id)).where(col(TextChunk.chapter_id) == chapter_id)
        result = await self._session.exec(stmt)
        return [i for i in result.all() if i is not None]

    @override
    async def upsert_for_chapter(
        self, chapter_id: int, chunks: Sequence[DomainTextChunk]
    ) -> Sequence[DomainTextChunk]:
        """Upsert on (chapter_id, chunk_index). Does NOT commit.

        Does not remove chunks beyond the new count; call
        `delete_for_chapter` first if the chapter was re-chunked.
        """
        if not chunks:
            return []

        rows = [_to_row(chapter_id, c) for c in chunks]
        ids_by_index: dict[int, int] = {}

        for i in range(0, len(rows), _MAX_ROWS_PER_STMT):
            stmt = insert(TextChunk).values(rows[i : i + _MAX_ROWS_PER_STMT])
            stmt = stmt.on_conflict_do_update(
                index_elements=["chapter_id", "chunk_index"],
                set_={
                    "chunk_hash": stmt.excluded.chunk_hash,
                    "text": stmt.excluded.text,
                    "meta": stmt.excluded.meta,
                },
            ).returning(col(TextChunk.chunk_index), col(TextChunk.id))

            result = await self._session.exec(stmt)
            ids_by_index.update(result.tuples().all())

        # Assumes DomainTextChunk is a dataclass; use model_copy for pydantic.
        return [
            replace(c, id=ids_by_index[c.chunk_index], chapter_id=chapter_id)
            for c in chunks
        ]

    @override
    async def delete_for_chapter(self, chapter_id: int) -> int:
        result = await self._session.exec(
            delete(TextChunk).where(col(TextChunk.chapter_id) == chapter_id)
        )
        return result.rowcount


def _to_row(chapter_id: int, chunk: DomainTextChunk) -> dict[str, Any]:
    return {
        "chunk_hash": chunk.chunk_hash,
        "chapter_id": chapter_id,
        "chunk_index": chunk.chunk_index,
        "text": chunk.text,
        "meta": asdict(chunk.meta),
    }


def _to_domain(chunk: TextChunk) -> DomainTextChunk:
    metadata = TextChunkMetadata(
        **{k: v for k, v in chunk.meta.items() if k in _META_FIELDS}
    )
    return DomainTextChunk(
        id=chunk.id,
        chunk_hash=chunk.chunk_hash,
        series=metadata.series,
        chapter_id=chunk.chapter_id,
        chapter_title=metadata.chapter_title or "",
        book_title=metadata.book_title or "",
        chunk_index=chunk.chunk_index,
        text=chunk.text,
        meta=metadata,
    )
