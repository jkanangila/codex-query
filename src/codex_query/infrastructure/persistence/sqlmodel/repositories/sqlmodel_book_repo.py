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
from codex_query.infrastructure.logging.factory import create_logger
from codex_query.infrastructure.persistence.sqlmodel.models import Book

_META_FIELDS = {f.name for f in fields(BookMetaData)}

logger = create_logger(__name__)


class SqlModelBookRepository(IBookRepository):
    """SQLModel-backed repository for book persistence.

    Performs session flushes to update the persistence context without
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
    async def register_book(self, book: DomainBook) -> int | None:
        """Register a new domain book in database storage.

        Args:
            book: Domain book model instance to register.

        Returns:
            int | None: Generated database primary key for the new book.

        Raises:
            BookAlreadyExistsError: If a database integrity constraint (such as a
                duplicate file path or hash) is violated.
        """
        logger.info("Registering new book at path '%s'", book.path)
        db_book = _from_domain(book)
        db_book.id = None  # let the DB assign the PK
        self._session.add(db_book)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            logger.exception(
                "Failed to register book at '%s': integrity constraint violated",
                book.path,
            )
            raise BookAlreadyExistsError(book.path) from exc

        logger.info(
            "Successfully registered book '%s' with ID %d", book.title, db_book.id
        )
        return db_book.id

    @override
    async def update(self, book_id: int, payload: BookUpdate) -> bool | None:
        """Apply non-null updates from a payload to an existing book record.

        Args:
            book_id: Database ID of the book to update.
            payload: Update payload containing field updates.

        Returns:
            bool | None: True if update succeeded, None if book was not found.
        """
        logger.debug("Attempting to update book ID %d", book_id)
        db_book = await self._session.get(Book, book_id)
        if db_book is None:
            logger.warning("Cannot update book ID %d: record not found", book_id)
            return None

        # NOTE: still can't clear a field to None; see issue 1
        changes = {k: v for k, v in asdict(payload).items() if v is not None}
        if "path" in changes:
            changes["path"] = str(changes["path"])

        if not changes:
            logger.debug(
                "No non-null changes supplied for book ID %d; skipping flush", book_id
            )
            return True

        for key, value in changes.items():
            setattr(db_book, key, value)

        await self._session.flush()
        logger.info(
            "Updated %d field(s) on book ID %d (%s)",
            len(changes),
            book_id,
            ", ".join(sorted(changes.keys())),
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

        await self._session.delete(book)
        await self._session.flush()
        logger.info("Successfully deleted book ID %d ('%s')", book_id, book.title)
        return True


def _from_domain(book: DomainBook) -> Book:
    """Convert a domain Book instance into a SQLModel database record.

    Args:
        book: Source domain Book instance.

    Returns:
        Book: Persistent SQLModel database entity.
    """
    logger.debug("Mapping domain Book to database model (title='%s')", book.title)
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
    """Convert a SQLModel database record into a domain Book instance.

    Filters metadata attributes against valid BookMetaData dataclass fields.

    Args:
        book: Source SQLModel database entity.

    Returns:
        DomainBook: Domain Book model instance.
    """
    logger.debug("Mapping database model to domain Book (ID=%s)", book.id)
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
