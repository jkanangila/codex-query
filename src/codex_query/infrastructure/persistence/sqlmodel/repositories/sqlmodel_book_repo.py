from dataclasses import asdict, fields
from pathlib import Path
from typing import override

from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from codex_query.application.ports.library import IBookRepository
from codex_query.domain.errors import BookAlreadyExistsError
from codex_query.domain.models.document import Book as DomainBook
from codex_query.domain.models.document import BookMetaData, BookUpdate
from codex_query.infrastructure.persistence.sqlmodel.models import Book

_META_FIELDS = {f.name for f in fields(BookMetaData)}


class SQLModelBookRepository(IBookRepository):
    """SQLModel-backed book repository. Flushes only; the UnitOfWork commits."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @override
    async def get_all(self) -> list[DomainBook]:
        stmt = select(Book).order_by(
            col(Book.series).is_(None), col(Book.series), col(Book.title)
        )
        result = await self._session.exec(stmt)
        return [_to_domain(b) for b in result.all()]

    @override
    async def get_by_id(self, book_id: int) -> DomainBook | None:
        book = await self._session.get(Book, book_id)
        return _to_domain(book) if book else None

    @override
    async def register_book(self, book: DomainBook) -> DomainBook:
        db_book = _from_domain(book)
        db_book.id = None  # let the DB assign the PK
        self._session.add(db_book)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            raise BookAlreadyExistsError(book.path) from exc
        return _to_domain(db_book)

    @override
    async def update(self, book_id: int, payload: BookUpdate) -> DomainBook | None:
        db_book = await self._session.get(Book, book_id)
        if db_book is None:
            return None

        # NOTE: still can't clear a field to None; see issue 1
        changes = {k: v for k, v in asdict(payload).items() if v is not None}
        if "path" in changes:
            changes["path"] = str(changes["path"])

        for key, value in changes.items():
            setattr(db_book, key, value)

        if changes:
            await self._session.flush()
        return _to_domain(db_book)

    @override
    async def delete(self, book_id: int) -> bool:
        book = await self._session.get(Book, book_id)
        if book is None:
            return False
        await self._session.delete(book)
        await self._session.flush()
        return True


def _from_domain(book: DomainBook) -> Book:
    return Book(
        id=book.id,
        series=book.series,
        path=str(book.path),
        title=book.title,
        author=book.author,
        file_hash=book.file_hash,
        size=book.size,
        modified_ns=book.modified_ns,
        meta=asdict(book.meta),
    )


def _to_domain(book: Book) -> DomainBook:
    return DomainBook(
        id=book.id,
        path=Path(book.path),
        title=book.title,
        series=book.series,
        author=book.author,
        file_hash=book.file_hash,
        size=book.size,
        modified_ns=book.modified_ns,
        meta=BookMetaData(**{k: v for k, v in book.meta.items() if k in _META_FIELDS}),
    )
