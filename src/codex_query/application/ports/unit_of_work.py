"""Application port definitions for transactional unit-of-work boundaries."""

from collections.abc import Callable
from types import TracebackType
from typing import Protocol, Self

from codex_query.application.ports.indexing import IndexingJobPort
from codex_query.application.ports.library import (
    IBookRepository,
    IChapterRepository,
    IChunkRepository,
)
from codex_query.application.ports.vector_store import VectorStorePort


class UnitOfWork(Protocol):
    """Protocol for an async transactional unit of work across repositories and stores.

    Implementations coordinate persistence operations across book, chapter, chunk,
    indexing job, and vector store ports within an ``async with`` context.

    Attributes:
        books: Repository port for book records.
        chapters: Repository port for chapter records.
        chunks: Repository port for text chunk records.
        jobs: Port for indexing job state persistence.
        vectors: Port for storing and querying vector embeddings.

    Example:
        ```python
        async with uow_factory() as uow:
            await uow.books.add(book)
            await uow.commit()
        ```
    """

    books: IBookRepository
    chapters: IChapterRepository
    chunks: IChunkRepository
    jobs: IndexingJobPort
    vectors: VectorStorePort

    async def __aenter__(self) -> Self:
        """Enter the async context and prepare transactional resources.

        Returns:
            The active ``UnitOfWork`` instance.
        """
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Exit the async context, rolling back on unhandled errors and releasing state.

        Args:
            exc_type: Exception class if an exception occurred inside the block,
                otherwise ``None``.
            exc: Exception instance if an exception occurred, otherwise ``None``.
            tb: Traceback if an exception occurred, otherwise ``None``.
        """
        ...

    async def commit(self) -> None:
        """Commit all changes in the current transaction."""
        ...

    async def rollback(self) -> None:
        """Roll back all uncommitted changes in the current transaction."""
        ...


UnitOfWorkFactory = Callable[[], UnitOfWork]
"""Factory callable that constructs a new ``UnitOfWork`` instance."""
