import asyncio

from sqlalchemy import event
from sqlalchemy.engine import Connection as SAConnection
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import configure_mappers
from sqlalchemy.pool import ConnectionPoolEntry
from sqlmodel.ext.asyncio.session import AsyncSession

from codex_query.infrastructure.logging.factory import create_logger
from codex_query.infrastructure.persistence.sqlmodel.config import (
    DatabaseConfig,
)
from codex_query.infrastructure.persistence.sqlmodel.migrate import (
    run_migrations,
)

logger = create_logger(__name__)


class SqlModelDatabase:
    """Owns two engines over the same SQLite file.

    - `engine` / `session_factory`: read-write. Every transaction starts with
      BEGIN IMMEDIATE, so writers queue up front instead of failing mid-way.
    - `read_engine` / `read_session_factory`: read-only (`PRAGMA query_only`) with
      its own connection pool. Transactions start with a plain deferred BEGIN, so in
      WAL mode readers see a committed snapshot and never wait for a writer, e.g.
      a vector search while a long indexing transaction is open.
    """

    def __init__(self, config: DatabaseConfig) -> None:
        self.db_conf = config
        self.db_url = self.db_conf.async_url

        self.engine: AsyncEngine = self._create_engine(read_only=False)
        self.read_engine: AsyncEngine = self._create_engine(read_only=True)

        self.session_factory = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=self.db_conf.session_expire_on_commit,
        )
        self.read_session_factory = async_sessionmaker(
            bind=self.read_engine,
            class_=AsyncSession,
            expire_on_commit=self.db_conf.session_expire_on_commit,
        )

    def _create_engine(self, *, read_only: bool) -> AsyncEngine:
        engine = create_async_engine(
            self.db_url,
            echo=self.db_conf.db_engine_echo,
            connect_args={"timeout": self.db_conf.timeout},
        )
        busy_ms = int(self.db_conf.timeout * 1000)  # PRAGMA needs an integer

        # Configure SQLite PRAGMAs for foreign keys, WAL mode, and busy timeout
        # Stop the driver from emitting its own deferred BEGIN.
        @event.listens_for(engine.sync_engine, "connect")
        def set_sqlite_pragma(
            dbapi_connection: DBAPIConnection, connection_record: ConnectionPoolEntry
        ) -> None:
            dbapi_connection.isolation_level = None

            cursor = dbapi_connection.cursor()
            if read_only:
                # WAL is persistent in the file; only the writer engine sets it.
                cursor.execute("PRAGMA query_only = ON")
            else:
                cursor.execute("PRAGMA journal_mode = WAL")
                cursor.execute("PRAGMA synchronous = NORMAL")
                cursor.execute("PRAGMA foreign_keys = ON")
            cursor.execute(f"PRAGMA busy_timeout = {busy_ms}")
            cursor.close()

        # Emit our own BEGIN at the start of every transaction.
        @event.listens_for(engine.sync_engine, "begin")
        def do_begin(conn: SAConnection) -> None:
            conn.exec_driver_sql("BEGIN" if read_only else "BEGIN IMMEDIATE")

        return engine

    async def startup(self) -> None:
        configure_mappers()
        # Migrations first: they create the file and switch it to WAL.
        await asyncio.to_thread(run_migrations)

    async def shutdown(self) -> None:
        await self.read_engine.dispose()
        await self.engine.dispose()
