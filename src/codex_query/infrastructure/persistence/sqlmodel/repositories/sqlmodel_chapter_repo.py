from collections.abc import Sequence
from dataclasses import replace
from typing import Any, override

from sqlalchemy.dialects.sqlite import insert
from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from codex_query.application.ports.library import IChapterRepository
from codex_query.domain.errors import ChapterAlreadyExistsError
from codex_query.domain.models.document import Chapter as DomainChapter
from codex_query.infrastructure.persistence.sqlmodel.models import Chapter

# SQLite < 3.32 allows only 999 bound variables per statement.
_COLUMNS_PER_ROW = 6
_MAX_ROWS_PER_STMT = 900 // _COLUMNS_PER_ROW  # 150


class SQLModelChapterRepository(IChapterRepository):
    """SQLModel-backed chapter repository. Flushes only; the UnitOfWork commits."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def get_by_id(self, chapter_id: int) -> DomainChapter | None:
        chapter = await self._session.get(Chapter, chapter_id)
        return _to_domain(chapter) if chapter else None

    @override
    async def get_all_for_book(
        self, book_id: int, after_order: int | None = None, limit: int = 100
    ) -> Sequence[DomainChapter]:
        """Keyset pagination on chapter_order (same column as the sort)."""
        stmt = select(Chapter).where(col(Chapter.book_id) == book_id)
        if after_order is not None:
            stmt = stmt.where(col(Chapter.chapter_order) > after_order)
        stmt = stmt.order_by(col(Chapter.chapter_order)).limit(limit)

        result = await self._session.exec(stmt)
        return [_to_domain(c) for c in result.all()]

    @override
    async def register(self, book_id: int, chapter: DomainChapter) -> DomainChapter:
        db_chapter = _to_orm(chapter, book_id)
        db_chapter.id = None  # let the DB assign the PK
        self._session.add(db_chapter)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise ChapterAlreadyExistsError(book_id, chapter.order) from exc
        return _to_domain(db_chapter)

    @override
    async def upsert_bulk(
        self,
        book_id: int,
        chapters: Sequence[DomainChapter],
        batch_size: int = _MAX_ROWS_PER_STMT,
    ) -> Sequence[DomainChapter]:
        """Upsert on (book_id, chapter_order). Does NOT commit.

        Does not delete chapters missing from `chapters`, nor chunks of
        chapters whose content changed; the use case owns that.
        """
        if not chapters:
            return []

        size = min(batch_size, _MAX_ROWS_PER_STMT)
        rows = [_to_row(ch, book_id) for ch in chapters]
        ids_by_order: dict[int, int] = {}

        for i in range(0, len(rows), size):
            stmt = insert(Chapter).values(rows[i : i + size])
            stmt = stmt.on_conflict_do_update(
                index_elements=["book_id", "chapter_order"],
                set_={
                    "title": stmt.excluded.title,
                    "href": stmt.excluded.href,
                    "content": stmt.excluded.content,
                    "content_hash": stmt.excluded.content_hash,
                },
            ).returning(col(Chapter.chapter_order), col(Chapter.id))  # not the content

            result = await self._session.execute(stmt)
            ids_by_order.update(result.tuples().all())

        # Assumes DomainChapter is a dataclass; use model_copy for pydantic.
        return [
            replace(ch, id=ids_by_order[ch.order], book_id=book_id) for ch in chapters
        ]


def _to_row(chapter: DomainChapter, book_id: int) -> dict[str, Any]:
    return {
        "book_id": book_id,
        "href": chapter.href,
        "title": chapter.title,
        "chapter_order": chapter.order,
        "content": chapter.content,
        "content_hash": chapter.content_hash,
    }


def _to_orm(chapter: DomainChapter, book_id: int) -> Chapter:
    return Chapter(id=chapter.id, **_to_row(chapter, book_id))


def _to_domain(chapter: Chapter) -> DomainChapter:
    return DomainChapter(
        id=chapter.id,
        book_id=chapter.book_id,
        href=chapter.href,
        title=chapter.title,
        order=chapter.chapter_order,
        content=chapter.content,
        content_hash=chapter.content_hash,
    )
