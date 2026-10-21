from collections.abc import Collection, Sequence
from typing import Any, override

from sqlalchemy import delete
from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from codex_query.application.ports.library import IChapterRepository
from codex_query.domain.errors import ChapterAlreadyExistsError
from codex_query.domain.models.document import Chapter as DomainChapter
from codex_query.infrastructure.logging.factory import create_logger
from codex_query.infrastructure.persistence.sqlmodel.models import Chapter

# SQLite < 3.32 allows only 999 bound variables per statement.
_COLUMNS_PER_ROW = 6
_MAX_ROWS_PER_STMT = 900 // _COLUMNS_PER_ROW  # 150
_IN_BATCH = 500

logger = create_logger(__name__)


class SqlModelChapterRepository(IChapterRepository):
    """SQLModel-backed chapter repository.

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
    async def get_by_id(self, chapter_id: int) -> DomainChapter | None:
        """Fetch a single chapter by its database primary key.

        Args:
            chapter_id: Unique database identifier of the chapter.

        Returns:
            DomainChapter | None: Mapped domain chapter if found, None otherwise.
        """
        logger.debug("Querying chapter by ID: %d", chapter_id)
        chapter = await self._session.get(Chapter, chapter_id)
        if chapter is None:
            logger.debug("No chapter found matching ID: %d", chapter_id)
            return None
        logger.debug("Found chapter ID %d ('%s')", chapter_id, chapter.title)
        return _to_domain(chapter)

    @override
    async def get_all_for_book(
        self, book_id: int, after_order: int | None = None, limit: int = 100
    ) -> Sequence[DomainChapter]:
        """Fetch chapters for a given book using keyset pagination.

        Paginates using `chapter_order` as the keyset cursor column.

        Args:
            book_id: Database ID of the associated book.
            after_order: Optional cursor for fetching chapters ordered after this value.
            limit: Maximum number of chapters to retrieve.

        Returns:
            Sequence[DomainChapter]: Sequence of mapped domain chapter models.
        """
        logger.debug(
            "Fetching chapters for book ID %d (after_order=%s, limit=%d)",
            book_id,
            after_order,
            limit,
        )
        stmt = select(Chapter).where(col(Chapter.book_id) == book_id)
        if after_order is not None:
            stmt = stmt.where(col(Chapter.chapter_order) > after_order)
        stmt = stmt.order_by(col(Chapter.chapter_order)).limit(limit)

        result = await self._session.exec(stmt)
        chapters = result.all()
        logger.debug("Retrieved %d chapter(s) for book ID %d", len(chapters), book_id)
        return [_to_domain(c) for c in chapters]

    @override
    async def register(self, book_id: int, chapter: DomainChapter) -> int:
        """Register a single new chapter under a given book ID.

        Args:
            book_id: Database ID of the parent book.
            chapter: Domain chapter instance to persist.

        Returns:
            int | None: Database primary key assigned to the new chapter.

        Raises:
            ChapterAlreadyExistsError: If a duplicate chapter order constraint is
                violated for the given book.
        """
        logger.info(
            "Registering chapter order %d ('%s') for book ID %d",
            chapter.order,
            chapter.title,
            book_id,
        )
        db_chapter = _to_orm(chapter, book_id)
        db_chapter.id = None  # let the DB assign the PK
        self._session.add(db_chapter)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            logger.exception(
                "Failed to register chapter order %d for book ID %d: already exists",
                chapter.order,
                book_id,
            )
            raise ChapterAlreadyExistsError(book_id, chapter.order) from exc

        if db_chapter.id is None:  # pragma: no cover - flush always assigns it
            raise RuntimeError("Database did not assign a primary key")
        logger.info(
            "Successfully registered chapter ID %d for book ID %d",
            db_chapter.id,
            book_id,
        )
        return db_chapter.id

    @override
    async def upsert_bulk(
        self,
        book_id: int,
        chapters: Sequence[DomainChapter],
        batch_size: int = _MAX_ROWS_PER_STMT,
    ) -> Sequence[int]:
        """Perform a bulk upsert on (book_id, chapter_order) in capped batches.

        Does NOT handle deletion of chapters omitted from `chapters` or orphaned
        chunks; the calling use case is responsible for lifecycle cleanups.

        Args:
            book_id: Database ID of the target parent book.
            chapters: Sequence of domain chapter objects to upsert.
            batch_size: Requested batch size limit (capped by SQLite variable limits).

        Returns:
            Sequence[int]: Database IDs corresponding to the input chapters in order.
        """
        if not chapters:
            logger.debug("No chapters provided for bulk upsert; returning empty list")
            return []

        effective_batch_size = min(batch_size, _MAX_ROWS_PER_STMT)
        logger.info(
            "Starting bulk upsert of %d chapter(s) for book ID %d (batch_size=%d)",
            len(chapters),
            book_id,
            effective_batch_size,
        )

        rows = [_to_row(ch, book_id) for ch in chapters]
        ids_by_order: dict[int, int] = {}

        for i in range(0, len(rows), effective_batch_size):
            batch_rows = rows[i : i + effective_batch_size]
            logger.debug(
                "Executing upsert batch %d-%d of %d for book ID %d",
                i + 1,
                i + len(batch_rows),
                len(rows),
                book_id,
            )
            stmt = insert(Chapter).values(batch_rows)
            stmt = stmt.on_conflict_do_update(
                index_elements=["book_id", "chapter_order"],
                set_={
                    "title": stmt.excluded.title,
                    "href": stmt.excluded.href,
                    "content_hash": stmt.excluded.content_hash,
                },
            ).returning(col(Chapter.chapter_order), col(Chapter.id))

            result = await self._session.exec(stmt)
            ids_by_order.update(result.tuples().all())

        logger.info(
            "Completed bulk upsert for %d chapter(s) across book ID %d",
            len(chapters),
            book_id,
        )
        return [ids_by_order[ch.order] for ch in chapters]

    @override
    async def delete_by_order(self, book_id: int, orders: Collection[int]) -> int:
        """Delete chapters by order. Chunks and embeddings go with them through
        ON DELETE CASCADE (PRAGMA foreign_keys = ON)."""
        ordered = list(orders)
        deleted = 0
        for i in range(0, len(ordered), _IN_BATCH):
            result = await self._session.exec(
                delete(Chapter).where(
                    col(Chapter.book_id) == book_id,
                    col(Chapter.chapter_order).in_(ordered[i : i + _IN_BATCH]),
                )
            )
            deleted += result.rowcount
        return deleted


def _to_row(chapter: DomainChapter, book_id: int) -> dict[str, Any]:
    """Convert a domain chapter to a raw database row dictionary representation.

    Args:
        chapter: Source domain chapter instance.
        book_id: ID of the parent book.

    Returns:
        dict[str, Any]: Dictionary mapping DB column names to values.
    """
    logger.debug(
        "Mapping domain chapter order %d to row dict for book ID %d",
        chapter.order,
        book_id,
    )
    return {
        "book_id": book_id,
        "href": chapter.href,
        "title": chapter.title,
        "chapter_order": chapter.order,
        "content_hash": chapter.content_hash,
    }


def _to_orm(chapter: DomainChapter, book_id: int) -> Chapter:
    """Convert a domain chapter into a SQLModel Chapter ORM entity.

    Args:
        chapter: Source domain chapter instance.
        book_id: ID of the parent book.

    Returns:
        Chapter: SQLModel Chapter database entity.
    """
    logger.debug("Mapping domain chapter order %d to ORM model", chapter.order)
    return Chapter(id=chapter.id, **_to_row(chapter, book_id))


def _to_domain(chapter: Chapter) -> DomainChapter:
    """Convert a SQLModel Chapter ORM entity into a DomainChapter instance.

    Args:
        chapter: Source SQLModel database entity.

    Returns:
        DomainChapter: Mapped domain chapter model with unpopulated content.
    """
    logger.debug("Mapping chapter ORM entity ID %d to domain model", chapter.id)
    return DomainChapter(
        id=chapter.id,
        book_id=chapter.book_id,
        href=chapter.href,
        title=chapter.title,
        order=chapter.chapter_order,
        content=None,
        content_hash=chapter.content_hash,
    )
