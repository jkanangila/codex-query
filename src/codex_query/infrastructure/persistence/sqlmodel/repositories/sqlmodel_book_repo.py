from dataclasses import fields
from pathlib import Path
from typing import Any, override

from sqlalchemy.exc import IntegrityError
from sqlmodel import col, select
from sqlmodel.ext.asyncio.session import AsyncSession

from codex_query.application.ports.library import IBookRepository
from codex_query.domain.errors import BookAlreadyExistsError
from codex_query.domain.models.document import (
    UNSET,
    BookMetadata,
    BookUpdate,
    DocumentType,
)
from codex_query.domain.models.document import Book as DomainBook
from codex_query.infrastructure.logging.factory import create_logger
from codex_query.infrastructure.persistence.sqlmodel.models import Book

logger = create_logger(__name__)


class SqlModelBookRepository(IBookRepository):
    """SQLModel-backed repository for book persistence.

    Perform session flushes to update the persistence context without
    committing transactions.
    Transaction management and final commits are handled by the UnitOfWork.
    """

    def __init__(self, session: AsyncSession) -> None:
        """Initialize repository with an active asynchronous SQLModel session.

        Args:
            session: Active AsyncSession bound to the current unit of work.
        """
        self._session = session

    @override
    async def get_all(self) -> list[DomainBook]:
        """Fetch all books ordered by series presence, series name, and title.

        Returns:
            list[DomainBook]: Ordered collection of all books mapped to domain models.
        """
        logger.debug("Fetching all books ordered by series and title")
        stmt = select(Book).order_by(
            col(Book.series).is_(None), col(Book.series), col(Book.title)
        )
        result = await self._session.exec(stmt)
        books = result.all()
        logger.debug("Retrieved %d book(s) from storage", len(books))
        return [_to_domain(b) for b in books]

    @override
    async def get_by_id(self, book_id: int) -> DomainBook | None:
        """Fetch a single book by its primary database ID.

        Args:
            book_id: Unique database identifier of the book.

        Returns:
            DomainBook | None: Domain book instance if found, None otherwise.
        """
        logger.debug("Querying book by ID: %d", book_id)
        book = await self._session.get(Book, book_id)
        if book is None:
            logger.debug("No book found matching ID: %d", book_id)
            return None
        logger.debug("Found book ID %d ('%s')", book_id, book.title)
        return _to_domain(book)

    @override
    async def register_book(self, book: DomainBook) -> int:
        """Register a new domain book in database storage.

        Args:
            book: Domain book model instance to register.

        Returns:
            int: Generated database primary key for the new book.

        Raises:
            BookAlreadyExistsError: If a database integrity constraint (such as a
                duplicate file path) is violated.
        """
        logger.info("Registering new book at path '%s'", book.path)
        db_book = _from_domain(book)
        db_book.id = None  # let the DB assign the PK
        self._session.add(db_book)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            # Expected condition (duplicate import), not a crash: no traceback.
            logger.warning(
                "Failed to register book at '%s': integrity constraint violated",
                book.path,
            )
            raise BookAlreadyExistsError(book.path) from exc

        if db_book.id is None:  # pragma: no cover - flush always assigns it
            raise RuntimeError("Database did not assign a primary key")

        logger.info(
            "Successfully registered book '%s' with ID %d", book.title, db_book.id
        )
        return db_book.id

    @override
    async def update(self, book_id: int, payload: BookUpdate) -> bool | None:
        """Apply the fields set on a payload to an existing book record.

        Fields left as ``UNSET`` are untouched; ``None`` is a real value, so
        nullable fields such as ``series`` can now be cleared.

        Args:
            book_id: Database ID of the book to update.
            payload: Partial update; only non-``UNSET`` fields are applied.

        Returns:
            bool | None: True if update succeeded, None if book was not found.
        """
        logger.debug("Attempting to update book ID %d", book_id)
        db_book = await self._session.get(Book, book_id)
        if db_book is None:
            logger.warning("Cannot update book ID %d: record not found", book_id)
            return None

        changes = _changes(payload)
        if not changes:
            logger.debug("No fields supplied for book ID %d; skipping flush", book_id)
            return True

        for key, value in changes.items():
            setattr(db_book, key, value)

        await self._session.flush()
        logger.info(
            "Updated %d field(s) on book ID %d (%s)",
            len(changes),
            book_id,
            ", ".join(sorted(changes)),
        )
        return True

    @override
    async def delete(self, book_id: int) -> bool:
        """Delete a book from storage by its database ID.

        Args:
            book_id: Unique database identifier of the target book.

        Returns:
            bool: True if the book was found and deleted, False otherwise.
        """
        logger.debug("Attempting to delete book ID %d", book_id)
        book = await self._session.get(Book, book_id)
        if book is None:
            logger.warning("Cannot delete book ID %d: record not found", book_id)
            return False

        title = book.title
        await self._session.delete(book)
        await self._session.flush()
        logger.info("Successfully deleted book ID %d ('%s')", book_id, title)
        return True


# --------------------------------------------------------------------------- #
# Mapping                                                                     #
# --------------------------------------------------------------------------- #
def _changes(payload: BookUpdate) -> dict[str, Any]:
    """ORM-ready column values for every field that is not ``UNSET``.

    Uses ``fields()`` rather than ``asdict()`` so nested dataclasses are not
    recursively converted and tuples are not silently copied.
    """
    changes: dict[str, Any] = {}
    for f in fields(payload):
        value = getattr(payload, f.name)
        if value is UNSET:
            continue
        match f.name:
            case "path":
                changes["path"] = str(value)
            case "authors":
                changes["authors"] = list(value)
            case "meta":
                changes["meta"] = _meta_to_json(value)
            case name:
                changes[name] = value
    return changes


def _meta_to_json(meta: BookMetadata) -> dict[str, Any]:
    """Serialize metadata to JSON-safe primitives (no tuples, no enums)."""
    return {
        "file_type": meta.file_type,
        "chapter_count": meta.chapter_count,
        "language": meta.language,
        "publisher": meta.publisher,
        "description": meta.description,
        "isbn": meta.isbn,
        "published_year": meta.published_year,
        "subjects": list(meta.subjects),
        "book_number": meta.book_number,
        "document_type": meta.document_type.value,
        "embedding_model": meta.embedding_model,
        "embedding_provider": meta.embedding_provider,
        "chunks": meta.chunks,
        "chunk_size": meta.chunk_size,
        "chunk_overlap": meta.chunk_overlap,
    }


def _meta_from_json(raw: dict[str, Any]) -> BookMetadata:
    """Rebuild metadata, restoring tuples/enums and tolerating missing keys."""
    try:
        document_type = DocumentType(raw.get("document_type"))
    except ValueError:
        document_type = DocumentType.UNKNOWN

    return BookMetadata(
        file_type=raw.get("file_type") or "unknown",
        chapter_count=int(raw.get("chapter_count") or 0),
        language=raw.get("language") or None,
        publisher=raw.get("publisher") or None,
        description=raw.get("description") or None,
        isbn=raw.get("isbn") or None,
        published_year=raw.get("published_year"),
        subjects=tuple(raw.get("subjects") or ()),
        book_number=raw.get("book_number"),
        document_type=document_type,
        embedding_model=raw.get("embedding_model") or None,
        embedding_provider=raw.get("embedding_provider") or None,
        chunks=int(raw.get("chunks") or 0),
        chunk_size=int(raw.get("chunk_size") or 0),
        chunk_overlap=int(raw.get("chunk_overlap") or 0),
    )


def _from_domain(book: DomainBook) -> Book:
    """Convert a domain Book instance into a SQLModel database record."""
    logger.debug("Mapping domain Book to database model (title='%s')", book.title)
    return Book(
        id=book.id,
        series=book.series,
        path=str(book.path),
        title=book.title,
        authors=list(book.authors),
        file_hash=book.file_hash,
        size=book.size,
        modified_ns=book.modified_ns,
        meta=_meta_to_json(book.meta),
    )


def _to_domain(book: Book) -> DomainBook:
    """Convert a SQLModel database record into a domain Book instance."""
    logger.debug("Mapping database model to domain Book (ID=%s)", book.id)
    return DomainBook(
        id=book.id,
        path=Path(book.path),
        title=book.title,
        series=book.series,
        authors=tuple(book.authors),
        file_hash=book.file_hash,
        size=book.size,
        modified_ns=book.modified_ns,
        meta=_meta_from_json(book.meta),
    )
