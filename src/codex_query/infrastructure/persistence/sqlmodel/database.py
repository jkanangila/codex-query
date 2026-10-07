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


class SQLModelDatabase:
    def __init__(self, config: DatabaseConfig) -> None:
        self.db_conf = config
        self.db_url = self.db_conf.async_url

        self.engine: AsyncEngine = create_async_engine(
            self.db_url,
            echo=self.db_conf.db_engine_echo,
            connect_args={"timeout": self.db_conf.timeout},
        )

        # Configure SQLite PRAGMAs for foreign keys, WAL mode, and busy timeout
        # Stop the driver from emitting its own deferred BEGIN.
        @event.listens_for(self.engine.sync_engine, "connect")
        def set_sqlite_pragma(
            dbapi_connection: DBAPIConnection, connection_record: ConnectionPoolEntry
        ) -> None:
            dbapi_connection.isolation_level = None

            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode = WAL")
            cursor.execute("PRAGMA synchronous = NORMAL")
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.execute(f"PRAGMA busy_timeout = {self.db_conf.timeout * 1000}")
            cursor.close()

        # Emit our own BEGIN IMMEDIATE at the start of every transaction.
        @event.listens_for(self.engine.sync_engine, "begin")
        def do_begin(conn: SAConnection) -> None:
            conn.exec_driver_sql("BEGIN IMMEDIATE")

        self.session_factory = async_sessionmaker(
            bind=self.engine,
            class_=AsyncSession,
            expire_on_commit=self.db_conf.session_expire_on_commit,
        )

    async def startup(self) -> None:
        configure_mappers()
        await asyncio.to_thread(run_migrations)

    async def shutdown(self) -> None:
        await self.engine.dispose()
