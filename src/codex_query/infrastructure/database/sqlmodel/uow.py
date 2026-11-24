"""Async SQLModel Unit of Work implementations for read-write and read-only access."""

from types import TracebackType
from typing import Self, override

from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from codex_query.application.ports.unit_of_work import UnitOfWork
from codex_query.infrastructure.database.sqlmodel.repositories.sqlmodel_book_repo import (  # noqa: E501
    SqlModelBookRepository,
)
from codex_query.infrastructure.database.sqlmodel.repositories.sqlmodel_chapter_repo import (  # noqa: E501
    SqlModelChapterRepository,
)
from codex_query.infrastructure.database.sqlmodel.repositories.sqlmodel_chunk_repo import (  # noqa: E501
    SqlModelChunkRepository,
)
from codex_query.infrastructure.database.sqlmodel.repositories.sqlmodel_job_repo import (  # noqa: E501
    SqlModelIndexingJobRepository,
)
from codex_query.infrastructure.database.sqlmodel.repositories.sqlmodel_vector_store import (  # noqa: E501
    SqlModelVectorStore,
)
from codex_query.infrastructure.database.vector_store_factory import VectorStoreFactory
from codex_query.infrastructure.logging.factory import create_logger

logger = create_logger(__name__)


class SqlUnitOfWork(UnitOfWork):
    """Transactional async Unit of Work backed by SQLModel and a vector store.

    Opens an ``AsyncSession`` per ``async with`` block and wires repository and
    vector-store instances to that session so operations share transactional scope.

    Attributes:
        books: Repository for book records.
        chapters: Repository for chapter records.
        chunks: Repository for text chunk records.
        jobs: Repository for indexing job records.
        vectors: Vector store instance created from ``vector_store_factory``.

    Example:
        ```python
        uow = SqlUnitOfWork(db.session_factory)
        async with uow:
            await uow.books.add(book)
            await uow.commit()
        ```
    """

    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        vector_store_factory: VectorStoreFactory | None = None,
    ) -> None:
        """Initialize the Unit of Work with a session factory and vector store factory.

        Args:
            factory: Async session maker used to create a new ``AsyncSession`` on
                context entry.
            vector_store_factory: Optional callable accepting an ``AsyncSession`` to
                construct a vector store. Defaults to ``SqlModelVectorStore`` so
                vector data shares the SQLite transaction; pass another factory to swap
                backends.
        """
        self._factory = factory
        self._session: AsyncSession | None = None
        # Default: SQLite + numpy in the same transaction. Pass a factory to swap
        # in another backend (e.g. Chroma on desktop).
        self._vector_store_factory = vector_store_factory or SqlModelVectorStore

    @property
    def session(self) -> AsyncSession:
        """Return the active ``AsyncSession`` bound to this Unit of Work.

        Returns:
            The active ``AsyncSession`` instance.

        Raises:
            RuntimeError: If accessed outside an active ``async with`` block.
        """
        if self._session is None:
            raise RuntimeError("UnitOfWork used outside 'async with'")
        return self._session

    @override
    async def __aenter__(self) -> Self:
        """Open a new session and initialize repositories and vector store.

        Returns:
            This Unit of Work instance with bound repository and vector store
            attributes.
        """
        logger.debug("Opening %s session", type(self).__name__)
        self._session = self._factory()
        self.books = SqlModelBookRepository(self._session)
        self.chapters = SqlModelChapterRepository(self._session)
        self.chunks = SqlModelChunkRepository(self._session)
        self.jobs = SqlModelIndexingJobRepository(self._session)
        self.vectors = self._vector_store_factory(self._session)
        return self

    @override
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """Roll back on unhandled exceptions, close the session, and clear state.

        Args:
            exc_type: Exception class if an exception occurred inside the block,
                otherwise ``None``.
            exc_val: Exception instance if an exception occurred, otherwise ``None``.
            exc_tb: Traceback if an exception occurred, otherwise ``None``.
        """
        try:
            if exc_type is not None:
                logger.warning(
                    "Rolling back %s due to unhandled exception (%s)",
                    type(self).__name__,
                    exc_type.__name__,
                )
                await self.session.rollback()
        except Exception:
            logger.exception("Failed to roll back %s session", type(self).__name__)
        finally:
            await self.session.close()  # also discards any uncommitted work
            self._session = None
            logger.debug("Closed %s session", type(self).__name__)

    @override
    async def commit(self) -> None:
        """Commit the active session transaction.

        Raises:
            RuntimeError: If called outside an active ``async with`` block.
        """
        await self.session.commit()
        logger.debug("Committed %s transaction", type(self).__name__)

    @override
    async def rollback(self) -> None:
        """Roll back the active session transaction.

        Raises:
            RuntimeError: If called outside an active ``async with`` block.
        """
        await self.session.rollback()
        logger.debug("Rolled back %s transaction", type(self).__name__)


class SqlReadOnlyUnitOfWork(SqlUnitOfWork):
    """Read-only Unit of Work intended for queries against a read-only engine.

    Construct with a read-only session factory (such as
    ``SqlModelDatabase.read_session_factory``) for read operations like vector
    search, listing library items, or reading settings. In SQLite WAL mode with
    ``PRAGMA query_only = ON``, readers observe committed snapshots without waiting
    for active writers, and ``commit()`` is explicitly disallowed. Use
    ``SqlUnitOfWork`` for write operations.
    """

    @override
    async def commit(self) -> None:
        """Reject commit attempts on a read-only Unit of Work.

        Raises:
            RuntimeError: Always raised because commits are not permitted on a
                read-only Unit of Work.
        """
        logger.warning("Blocked commit attempt on read-only Unit of Work")
        raise RuntimeError(
            "SqlReadOnlyUnitOfWork cannot commit; use SqlUnitOfWork for writes"
        )
