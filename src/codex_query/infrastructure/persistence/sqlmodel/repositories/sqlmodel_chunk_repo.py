from collections.abc import Sequence
from dataclasses import asdict, fields
from typing import Any, override

from sqlalchemy import delete
from sqlalchemy.dialects.sqlite import insert
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from codex_query.application.ports.library import IChunkRepository
from codex_query.domain.models.document import TextChunk as DomainTextChunk
from codex_query.domain.models.document import TextChunkMetadata
from codex_query.infrastructure.logging.factory import create_logger
from codex_query.infrastructure.persistence.sqlmodel.models import Chapter, TextChunk

_META_FIELDS = {f.name for f in fields(TextChunkMetadata)}

# SQLite < 3.32 allows only 999 bound variables per statement.
_COLUMNS_PER_ROW = 5
_MAX_ROWS_PER_STMT = 900 // _COLUMNS_PER_ROW  # 180

logger = create_logger(__name__)


class SqlModelChunkRepository(IChunkRepository):
    """SQLModel-backed text chunk repository.

    Performs session flushes and executions only; transaction commits are managed
    by the UnitOfWork.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with an active asynchronous SQLModel session.

        Args:
            session: Active AsyncSession bound to the current unit of work.
        """
        self._session = session

    @override
    async def get_all_for_book(
        self, book_id: int, after_id: int | None = None, limit: int = 100
    ) -> Sequence[DomainTextChunk]:
        """Fetch text chunks associated with a book using keyset pagination on ID.

        Args:
            book_id: Database ID of the target book.
            after_id: Optional ID cursor for fetching chunks ordered after this value.
            limit: Maximum number of text chunks to retrieve.

        Returns:
            Sequence[DomainTextChunk]: Sequence of mapped domain text chunk models.
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
        """Fetch primary key IDs for all text chunks belonging to a chapter.

        Args:
            chapter_id: Database ID of the target chapter.

        Returns:
            Sequence[int]: Sequence of non-null chunk database primary keys.
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
            chapter_id: Database ID of the target chapter.

        Returns:
            Sequence[DomainTextChunk]: Sequence of mapped domain text chunks.
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
        """Upsert text chunks on conflict of (chapter_id, chunk_index) in capped batches

        Does NOT handle removal of extraneous trailing chunks if a chapter was
        re-chunked into fewer pieces. Call `delete_for_chapter` first if needed.

        Args:
            chapter_id: Database ID of the parent chapter.
            chunks: Sequence of domain text chunks to upsert.

        Returns:
            Sequence[int]: Database IDs corresponding to the input chunks in order.
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
        # Assumes DomainTextChunk is a dataclass; use model_copy for pydantic.
        return [ids_by_index[c.chunk_index] for c in chunks]

    @override
    async def delete_for_chapter(self, chapter_id: int) -> int:
        """Delete all text chunks associated with a specific chapter ID.

        Args:
            chapter_id: Database ID of the chapter whose chunks should be deleted.

        Returns:
            int: Number of deleted chunk rows.
        """
        logger.info("Deleting all text chunks for chapter ID %d", chapter_id)
        result = await self._session.exec(
            delete(TextChunk).where(col(TextChunk.chapter_id) == chapter_id)
        )
        deleted_count = result.rowcount
        logger.info(
            "Deleted %d text chunk(s) for chapter ID %d", deleted_count, chapter_id
        )
        return deleted_count


def _to_row(chapter_id: int, chunk: DomainTextChunk) -> dict[str, Any]:
    """Convert a domain text chunk into a raw dictionary for bulk insertion.

    Args:
        chapter_id: Database ID of the parent chapter.
        chunk: Source domain text chunk instance.

    Returns:
        dict[str, Any]: Dictionary mapping DB column names to values.
    """
    logger.debug(
        "Mapping chunk index %d to row dict for chapter ID %d",
        chunk.chunk_index,
        chapter_id,
    )
    return {
        "chapter_id": chapter_id,
        "chunk_index": chunk.chunk_index,
        "text": chunk.text,
        "meta": asdict(chunk.meta),
    }


def _to_domain(chunk: TextChunk) -> DomainTextChunk:
    """Convert a SQLModel TextChunk ORM entity into a DomainTextChunk instance.

    Filters metadata key-value pairs against valid TextChunkMetadata fields.

    Args:
        chunk: Source SQLModel database entity.

    Returns:
        DomainTextChunk: Mapped domain text chunk model.
    """
    logger.debug("Mapping TextChunk ORM entity ID %d to domain model", chunk.id)
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
