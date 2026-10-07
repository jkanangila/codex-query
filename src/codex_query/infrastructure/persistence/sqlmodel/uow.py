from types import TracebackType
from typing import Self, override

from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from codex_query.application.ports.unit_of_work import UnitOfWork
from codex_query.infrastructure.persistence.sqlmodel.repositories.sqlmodel_book_repo import (
    SqlModelBookRepository,
)
from codex_query.infrastructure.persistence.sqlmodel.repositories.sqlmodel_chapter_repo import (
    SqlModelChapterRepository,
)
from codex_query.infrastructure.persistence.sqlmodel.repositories.sqlmodel_chunk_repo import (
    SqlModelChunkRepository,
)
from codex_query.infrastructure.persistence.sqlmodel.repositories.sqlmodel_job_repo import (
    SqlModelIndexingJobRepository,
)


class SqlUnitOfWork(UnitOfWork):
    def __init__(self, factory: async_sessionmaker[AsyncSession]) -> None:
        self._factory = factory
        self._session: AsyncSession | None = None

    @property
    def session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError("UnitOfWork used outside 'async with'")
        return self._session

    @override
    async def __aenter__(self) -> Self:
        self._session = self._factory()
        self.books = SqlModelBookRepository(self._session)
        self.chapters = SqlModelChapterRepository(self._session)
        self.chunks = SqlModelChunkRepository(self._session)
        self.jobs = SqlModelIndexingJobRepository(self._session)
        return self

    @override
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        try:
            if exc_type is not None:
                await self.session.rollback()
        finally:
            await self.session.close()  # also discards any uncommitted work
            self._session = None

    @override
    async def commit(self) -> None:
        await self.session.commit()

    @override
    async def rollback(self) -> None:
        await self.session.rollback()
