"""SQLModel persistence implementation for chapter text chunks."""

from collections.abc import Collection, Sequence
from dataclasses import asdict, fields
from typing import Any, override

from sqlalchemy import delete
from sqlalchemy.dialects.sqlite import insert
from sqlmodel import col, func, select
from sqlmodel.ext.asyncio.session import AsyncSession

from codex_query.application.ports.library import IChunkRepository
from codex_query.domain.models.document import TextChunk as DomainTextChunk
from codex_query.domain.models.document import TextChunkMetadata
from codex_query.infrastructure.database.sqlmodel.models import Chapter, TextChunk
from codex_query.infrastructure.logging.factory import create_logger

_META_FIELDS = {f.name for f in fields(TextChunkMetadata)}

# SQLite < 3.32 allows only 999 bound variables per statement.
_COLUMNS_PER_ROW = 5
_MAX_ROWS_PER_STMT = 900 // _COLUMNS_PER_ROW  # 180
_IN_BATCH = 500

logger = create_logger(__name__)


class SqlModelChunkRepository(IChunkRepository):
    """SQLModel-backed text chunk repository.

    Performs session flushes and statement executions only; transaction commits
    are managed by the `UnitOfWork`.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize the repository with an asynchronous SQLModel session.

        Args:
            session: Active session bound to the current unit of work.
        """
        self._session = session

    @override
    async def get_all_for_book(
        self, book_id: int, after_id: int | None = None, limit: int = 100
    ) -> Sequence[DomainTextChunk]:
        """Fetch text chunks for a book using keyset pagination on chunk ID.

        Args:
            book_id: Primary key of the target book.
            after_id: Exclusive lower bound on chunk ID for pagination.
            limit: Maximum number of text chunks to return.

        Returns:
            Text chunks ordered by chunk ID.
        """
        logger.debug(
            "Fetching text chunks for book ID %d (after_id=%s, limit=%d)",
            book_id,
            after_id,
            limit,
        )
        stmt = (
            select(TextChunk)
            .join(Chapter, col(TextChunk.chapter_id) == col(Chapter.id))
            .where(col(Chapter.book_id) == book_id)
        )
        if after_id is not None:
            stmt = stmt.where(col(TextChunk.id) > after_id)
        stmt = stmt.order_by(col(TextChunk.id)).limit(limit)

        result = await self._session.exec(stmt)
        chunks = result.all()
        logger.debug("Retrieved %d text chunk(s) for book ID %d", len(chunks), book_id)
        return [_to_domain(c) for c in chunks]

    @override
    async def get_ids_for_chapter(self, chapter_id: int) -> Sequence[int]:
        """Fetch primary key IDs for all text chunks in a chapter.

        Args:
            chapter_id: Primary key of the target chapter.

        Returns:
            Non-null chunk primary keys belonging to the chapter.
        """
        logger.debug("Fetching chunk IDs for chapter ID %d", chapter_id)
        stmt = select(col(TextChunk.id)).where(col(TextChunk.chapter_id) == chapter_id)
        result = await self._session.exec(stmt)
        ids = [i for i in result.all() if i is not None]
        logger.debug("Retrieved %d chunk ID(s) for chapter ID %d", len(ids), chapter_id)
        return ids

    @override
    async def get_chunks_for_chapter(
        self, chapter_id: int
    ) -> Sequence[DomainTextChunk]:
        """Fetch all text chunks for a chapter ordered by chunk index.

        Args:
            chapter_id: Primary key of the target chapter.

        Returns:
            Domain text chunks ordered by `chunk_index`.
        """
        logger.debug("Fetching all text chunks for chapter ID %d", chapter_id)
        stmt = (
            select(TextChunk)
            .where(col(TextChunk.chapter_id) == chapter_id)
            .order_by(col(TextChunk.chunk_index))
        )
        result = await self._session.exec(stmt)
        chunks = result.all()
        logger.debug("Retrieved %d chunk(s) for chapter ID %d", len(chunks), chapter_id)
        return [_to_domain(c) for c in chunks]

    @override
    async def upsert_for_chapter(
        self, chapter_id: int, chunks: Sequence[DomainTextChunk]
    ) -> Sequence[int]:
        """Upsert text chunks on `(chapter_id, chunk_index)` in capped batches.

        Updates `text` and `meta` on conflict. Does not remove trailing chunks if
        a chapter is re-chunked into fewer pieces; call `delete_for_chapter`
        first when full replacement is required.

        Args:
            chapter_id: Primary key of the parent chapter.
            chunks: Domain text chunks to insert or update.

        Returns:
            Chunk primary keys aligned with the input `chunks` sequence.
        """
        if not chunks:
            logger.debug(
                "No chunks provided for upsert on chapter ID %d; returning empty list",
                chapter_id,
            )
            return []

        logger.info(
            "Starting upsert of %d chunk(s) for chapter ID %d",
            len(chunks),
            chapter_id,
        )
        rows = [_to_row(chapter_id, c) for c in chunks]
        ids_by_index: dict[int, int] = {}

        for i in range(0, len(rows), _MAX_ROWS_PER_STMT):
            batch_rows = rows[i : i + _MAX_ROWS_PER_STMT]
            logger.debug(
                "Executing chunk upsert batch %d-%d of %d for chapter ID %d",
                i + 1,
                i + len(batch_rows),
                len(rows),
                chapter_id,
            )
            stmt = insert(TextChunk).values(batch_rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=["chapter_id", "chunk_index"],
                set_={
                    "text": stmt.excluded.text,
                    "meta": stmt.excluded.meta,
                },
            ).returning(col(TextChunk.chunk_index), col(TextChunk.id))

            result = await self._session.exec(stmt)
            ids_by_index.update(result.tuples().all())

        logger.info(
            "Successfully upserted %d chunk(s) for chapter ID %d",
            len(chunks),
            chapter_id,
        )
        return [ids_by_index[c.chunk_index] for c in chunks]

    @override
    async def delete_for_chapter(self, chapter_id: int) -> int:
        """Delete all text chunks belonging to a chapter.

        Args:
            chapter_id: Primary key of the chapter whose chunks are deleted.

        Returns:
            Number of deleted chunk rows.
        """
        logger.info("Deleting all text chunks for chapter ID %d", chapter_id)
        result = await self._session.exec(
            delete(TextChunk).where(col(TextChunk.chapter_id) == chapter_id)
        )
        deleted_count = result.rowcount or 0
        logger.info(
            "Deleted %d text chunk(s) for chapter ID %d", deleted_count, chapter_id
        )
        return deleted_count

    @override
    async def get_ids_for_orders(
        self, book_id: int, orders: Collection[int]
    ) -> Sequence[int]:
        """Fetch chunk IDs for chapters matching the given order numbers in a book.

        Args:
            book_id: Primary key of the parent book.
            orders: Collection of chapter order numbers to match.

        Returns:
            Matching non-null chunk primary keys across all queried batches.
        """
        ordered = list(orders)
        if not ordered:
            logger.debug(
                "No chapter orders provided for chunk ID lookup on book ID %d",
                book_id,
            )
            return []

        logger.debug(
            "Fetching chunk IDs across %d chapter order(s) for book ID %d",
            len(ordered),
            book_id,
        )
        ids: list[int] = []
        for i in range(0, len(ordered), _IN_BATCH):
            batch_orders = ordered[i : i + _IN_BATCH]
            result = await self._session.exec(
                select(col(TextChunk.id))
                .join(Chapter, col(TextChunk.chapter_id) == col(Chapter.id))
                .where(
                    col(Chapter.book_id) == book_id,
                    col(Chapter.chapter_order).in_(batch_orders),
                )
            )
            ids.extend(chunk_id for chunk_id in result.all() if chunk_id is not None)

        logger.debug(
            "Retrieved %d chunk ID(s) across %d chapter order(s) for book ID %d",
            len(ids),
            len(ordered),
            book_id,
        )
        return ids

    @override
    async def count_for_book(self, book_id: int) -> int:
        """Count total text chunks associated with a book across all chapters.

        Args:
            book_id: Primary key of the target book.

        Returns:
            Total number of text chunks for the book.
        """
        logger.debug("Counting text chunks for book ID %d", book_id)
        statement = (
            select(func.count(col(TextChunk.id)))
            .join(Chapter, col(TextChunk.chapter_id) == Chapter.id)
            .where(Chapter.book_id == book_id)
        )
        result = await self._session.exec(statement)
        count = result.one()
        logger.debug("Found %d text chunk(s) for book ID %d", count, book_id)
        return count


def _to_row(chapter_id: int, chunk: DomainTextChunk) -> dict[str, Any]:
    """Build a column dictionary for bulk text chunk insert or upsert statements.

    Args:
        chapter_id: Primary key of the parent chapter.
        chunk: Source domain text chunk.

    Returns:
        Dictionary mapping database column names to serialized values.
    """
    return {
        "chapter_id": chapter_id,
        "chunk_index": chunk.chunk_index,
        "text": chunk.text,
        "meta": asdict(chunk.meta),
    }


def _to_domain(chunk: TextChunk) -> DomainTextChunk:
    """Convert a SQLModel `TextChunk` entity into a domain `TextChunk`.

    Ignores unrecognized keys in `chunk.meta` when constructing
    `TextChunkMetadata`.

    Args:
        chunk: Source ORM text chunk entity.

    Returns:
        Domain `TextChunk` populated with parsed metadata fields.
    """
    metadata = TextChunkMetadata(
        **{k: v for k, v in chunk.meta.items() if k in _META_FIELDS}
    )
    return DomainTextChunk(
        id=chunk.id,
        series=metadata.series,
        chapter_id=chunk.chapter_id,
        chapter_title=metadata.chapter_title,
        book_title=metadata.book_title,
        chunk_index=chunk.chunk_index,
        text=chunk.text,
        meta=metadata,
    )
