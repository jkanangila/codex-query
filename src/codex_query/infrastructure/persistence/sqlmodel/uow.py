from types import TracebackType
from typing import Self, override

from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlmodel.ext.asyncio.session import AsyncSession

from codex_query.application.ports.unit_of_work import UnitOfWork
from codex_query.infrastructure.persistence.sqlmodel.repositories.sqlmodel_book_repo import (  # noqa: E501
    SqlModelBookRepository,
)
from codex_query.infrastructure.persistence.sqlmodel.repositories.sqlmodel_chapter_repo import (  # noqa: E501
    SqlModelChapterRepository,
)
from codex_query.infrastructure.persistence.sqlmodel.repositories.sqlmodel_chunk_repo import (  # noqa: E501
    SqlModelChunkRepository,
)
from codex_query.infrastructure.persistence.sqlmodel.repositories.sqlmodel_job_repo import (  # noqa: E501
    SqlModelIndexingJobRepository,
)
from codex_query.infrastructure.persistence.sqlmodel.repositories.sqlmodel_vector_store import (  # noqa: E501
    SqlModelVectorStore,
)
from codex_query.infrastructure.persistence.vector_store_factory import (
    VectorStoreFactory,
)


class SqlUnitOfWork(UnitOfWork):
    def __init__(
        self,
        factory: async_sessionmaker[AsyncSession],
        vector_store_factory: VectorStoreFactory | None = None,
    ) -> None:
        self._factory = factory
        self._session: AsyncSession | None = None
        # Default: SQLite + numpy in the same transaction. Pass a factory to swap
        # in another backend (e.g. Chroma on desktop).
        self._vector_store_factory = vector_store_factory or SqlModelVectorStore

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
        self.vectors = self._vector_store_factory(self._session)
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


class SqlReadOnlyUnitOfWork(SqlUnitOfWork):
    """Unit of work on the read-only engine (see SQLModelDatabase).

    Build it with `db.read_session_factory`. Use it for queries such as vector
    search, listing the library or reading settings: it never waits for a writer
    holding the write lock, and sees only committed data. Writes fail at the
    database (`query_only`), and `commit()` is rejected so misuse is loud.
    Use `SqlUnitOfWork` for anything that writes.
    """

    @override
    async def commit(self) -> None:
        raise RuntimeError(
            "SqlReadOnlyUnitOfWork cannot commit; use SqlUnitOfWork for writes"
        )
