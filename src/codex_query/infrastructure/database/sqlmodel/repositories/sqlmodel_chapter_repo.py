"""SQLModel persistence implementation for book chapters."""

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
from codex_query.infrastructure.database.sqlmodel.models import Chapter
from codex_query.infrastructure.logging.factory import create_logger

# SQLite < 3.32 allows only 999 bound variables per statement.
_COLUMNS_PER_ROW = 6
_MAX_ROWS_PER_STMT = 900 // _COLUMNS_PER_ROW  # 150
_IN_BATCH = 500

logger = create_logger(__name__)


class SqlModelChapterRepository(IChapterRepository):
    """SQLModel-backed chapter repository.

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
    async def get_by_id(self, chapter_id: int) -> DomainChapter | None:
        """Fetch a single chapter by its primary key.

        Args:
            chapter_id: Primary key of the chapter.

        Returns:
            Mapped domain chapter when found, otherwise `None`.
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
        """Fetch chapters for a book using keyset pagination on `chapter_order`.

        Args:
            book_id: Primary key of the parent book.
            after_order: Exclusive lower bound on `chapter_order` for pagination.
            limit: Maximum number of chapters to return.

        Returns:
            Chapters ordered by `chapter_order`, with `content` set to `None`.
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
    async def get_hashes_for_book(self, book_id: int) -> dict[int, str]:
        """Fetch content hashes keyed by chapter order for a book.

        Args:
            book_id: Primary key of the parent book.

        Returns:
            Mapping of `chapter_order` to `content_hash`.
        """
        logger.debug("Fetching content hashes for book ID %d", book_id)
        stmt = select(Chapter.chapter_order, Chapter.content_hash).where(
            col(Chapter.book_id) == book_id
        )
        result = await self._session.exec(stmt)
        return {
            chapter_order: content_hash for chapter_order, content_hash in result.all()
        }

    @override
    async def register(self, book_id: int, chapter: DomainChapter) -> int:
        """Persist a new chapter under a book and flush the session.

        Args:
            book_id: Primary key of the parent book.
            chapter: Domain chapter to insert; any existing `id` is ignored so the
                database assigns a new primary key.

        Returns:
            Database primary key assigned to the newly inserted chapter.

        Raises:
            ChapterAlreadyExistsError: If `(book_id, chapter_order)` already exists.
            RuntimeError: If flushing does not populate a primary key.
        """
        logger.info(
            "Registering chapter order %d ('%s') for book ID %d",
            chapter.order,
            chapter.title,
            book_id,
        )
        db_chapter = _to_orm(chapter, book_id)
        db_chapter.id = None
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
        """Bulk upsert chapters on `(book_id, chapter_order)` in bounded batches.

        Updates `title`, `href`, and `content_hash` on conflict. Does not delete
        chapters omitted from `chapters` or clean up orphaned chunks; callers
        handle lifecycle removal.

        Args:
            book_id: Primary key of the target parent book.
            chapters: Domain chapters to insert or update.
            batch_size: Desired rows per statement, capped at `_MAX_ROWS_PER_STMT`
                to stay within SQLite bound-parameter limits.

        Returns:
            Chapter primary keys aligned with the input `chapters` sequence.
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
        """Delete chapters matching the given order numbers for a book.

        Cascades to dependent chunks and embeddings when foreign keys are enabled
        (`PRAGMA foreign_keys = ON`).

        Args:
            book_id: Primary key of the parent book.
            orders: Collection of `chapter_order` values to delete.

        Returns:
            Total number of deleted chapter rows.
        """
        ordered = list(orders)
        if not ordered:
            logger.debug(
                "No chapter orders provided for deletion on book ID %d", book_id
            )
            return 0

        logger.info(
            "Deleting up to %d chapter(s) by order for book ID %d",
            len(ordered),
            book_id,
        )
        deleted = 0
        for i in range(0, len(ordered), _IN_BATCH):
            batch_orders = ordered[i : i + _IN_BATCH]
            result = await self._session.exec(
                delete(Chapter).where(
                    col(Chapter.book_id) == book_id,
                    col(Chapter.chapter_order).in_(batch_orders),
                )
            )
            deleted += result.rowcount or 0

        logger.info("Deleted %d chapter(s) for book ID %d", deleted, book_id)
        return deleted


def _to_row(chapter: DomainChapter, book_id: int) -> dict[str, Any]:
    """Build a column dictionary for insert or upsert statements.

    Args:
        chapter: Source domain chapter.
        book_id: Primary key of the parent book.

    Returns:
        Dictionary mapping database column names to chapter values.
    """
    return {
        "book_id": book_id,
        "href": chapter.href,
        "title": chapter.title,
        "chapter_order": chapter.order,
        "content_hash": chapter.content_hash,
    }


def _to_orm(chapter: DomainChapter, book_id: int) -> Chapter:
    """Convert a domain chapter into a SQLModel `Chapter` entity.

    Args:
        chapter: Source domain chapter.
        book_id: Primary key of the parent book.

    Returns:
        SQLModel `Chapter` instance preserving `chapter.id`.
    """
    return Chapter(id=chapter.id, **_to_row(chapter, book_id))


def _to_domain(chapter: Chapter) -> DomainChapter:
    """Convert a SQLModel `Chapter` entity into a domain `Chapter`.

    Args:
        chapter: Source ORM chapter entity.

    Returns:
        Domain `Chapter` instance with `content` left unpopulated (`None`).
    """
    return DomainChapter(
        id=chapter.id,
        book_id=chapter.book_id,
        href=chapter.href,
        title=chapter.title,
        order=chapter.chapter_order,
        content=None,
        content_hash=chapter.content_hash,
    )
