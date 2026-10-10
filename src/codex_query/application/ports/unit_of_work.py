from collections.abc import Callable
from types import TracebackType
from typing import Protocol, Self

from codex_query.application.ports.api_keys import ApiKeyRepositoryPort
from codex_query.application.ports.indexing import IndexingJobPort
from codex_query.application.ports.library import (
    IBookRepository,
    IChapterRepository,
    IChunkRepository,
)


class UnitOfWork(Protocol):
    books: IBookRepository
    chapters: IChapterRepository
    chunks: IChunkRepository
    jobs: IndexingJobPort

    async def __aenter__(self) -> Self: ...
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None: ...
    async def commit(self) -> None:
        """Commit the current transaction."""
        ...

    async def rollback(self) -> None:
        """Roll back the current transaction."""
        ...


UnitOfWorkFactory = Callable[[], UnitOfWork]
