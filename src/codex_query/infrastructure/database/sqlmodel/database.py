"""Async SQLModel database manager configured for concurrent SQLite WAL access."""

import asyncio

from sqlalchemy import event
from sqlalchemy.engine import Connection as SAConnection
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import configure_mappers
from sqlalchemy.pool import ConnectionPoolEntry
from sqlmodel.ext.asyncio.session import AsyncSession

from codex_query.infrastructure.database.sqlmodel.config import (
    DatabaseConfig,
)
from codex_query.infrastructure.database.sqlmodel.migrate import (
    run_migrations,
)
from codex_query.infrastructure.logging.factory import create_logger

logger = create_logger(__name__)


class SqlModelDatabase:
    """Manages separate read-write and read-only async engines over SQLite.

    Maintains two engines against the same SQLite database file so read queries can
    proceed against a committed WAL snapshot without waiting on long-running write
    transactions (such as indexing while vector searches run):

    - ``engine`` and ``session_factory``: Read-write access where every transaction
      begins with ``BEGIN IMMEDIATE`` so writers serialize up front instead of
      encountering write-lock failures mid-transaction.
    - ``read_engine`` and ``read_session_factory``: Read-only access enforcing
      ``PRAGMA query_only = ON`` with its own connection pool and a standard
      deferred ``BEGIN``.

    Attributes:
        db_conf: Database configuration settings.
        db_url: Asynchronous SQLAlchemy connection URL.
        engine: Async engine configured for read-write transactions.
        read_engine: Async engine configured for read-only transactions.
        session_factory: Session maker producing read-write ``AsyncSession`` instances.
        read_session_factory: Session maker producing read-only ``AsyncSession``
            instances.

    Example:
        ```python
        db = SqlModelDatabase(config)
        await db.startup()
        try:
            async with db.session_factory() as session:
                ...
        finally:
            await db.shutdown()
        ```
    """

    def __init__(self, config: DatabaseConfig) -> None:
        """Initialize read-write and read-only engines and session factories.

        Args:
            config: Configuration object supplying the async database URL, echo flag,
                connection/busy timeout, and session expiration behavior.
        """
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
        """Create an async SQLite engine with custom connection and transaction hooks.

        Disables DBAPI autocommit/implicit transaction management (``isolation_level =
        None``), applies SQLite ``PRAGMA`` settings on each new connection, and issues
        an explicit ``BEGIN`` or ``BEGIN IMMEDIATE`` at transaction start.

        Args:
            read_only: If ``True``, enables ``PRAGMA query_only = ON`` and starts
                transactions with ``BEGIN``. If ``False``, configures WAL mode,
                ``synchronous = NORMAL``, foreign keys, and ``BEGIN IMMEDIATE``.

        Returns:
            Configured ``AsyncEngine`` instance.
        """
        mode_label = "read-only" if read_only else "read-write"
        logger.debug("Creating %s SQLite async engine", mode_label)

        engine = create_async_engine(
            self.db_url,
            echo=self.db_conf.db_engine_echo,
            connect_args={"timeout": self.db_conf.timeout},
        )
        busy_ms = int(self.db_conf.timeout * 1000)

        # Configure SQLite PRAGMAs on connect and let SQLAlchemy/our hook manage BEGIN.
        @event.listens_for(engine.sync_engine, "connect")
        def set_sqlite_pragma(
            dbapi_connection: DBAPIConnection,
            connection_record: ConnectionPoolEntry,
        ) -> None:
            dbapi_connection.isolation_level = None

            cursor = dbapi_connection.cursor()
            try:
                if read_only:
                    # WAL mode persists in the database file; only the writer sets it.
                    cursor.execute("PRAGMA query_only = ON")
                else:
                    cursor.execute("PRAGMA journal_mode = WAL")
                    cursor.execute("PRAGMA synchronous = NORMAL")
                    cursor.execute("PRAGMA foreign_keys = ON")
                cursor.execute(f"PRAGMA busy_timeout = {busy_ms}")
            finally:
                cursor.close()

            logger.debug(
                "Configured SQLite PRAGMAs for %s connection (busy_timeout=%dms)",
                mode_label,
                busy_ms,
            )

        # Emit an explicit transaction start statement so writers acquire locks early.
        @event.listens_for(engine.sync_engine, "begin")
        def do_begin(conn: SAConnection) -> None:
            conn.exec_driver_sql("BEGIN" if read_only else "BEGIN IMMEDIATE")

        return engine

    async def startup(self) -> None:
        """Configure ORM mappers and run synchronous database migrations.

        Executes ``configure_mappers()`` and runs ``run_migrations()`` in a worker
        thread so the SQLite file is created and switched to WAL mode before serving
        queries.

        Raises:
            Exception: Propagates any error raised while configuring mappers or running
                migrations.
        """
        logger.info("Starting database initialization")
        try:
            configure_mappers()
            await asyncio.to_thread(run_migrations)
        except Exception:
            logger.exception("Database startup failed during mapper or migration setup")
            raise
        logger.info("Database startup completed")

    async def shutdown(self) -> None:
        """Dispose of both read-only and read-write async engine connection pools.

        Raises:
            Exception: Propagates any error encountered while disposing the engines.
        """
        logger.info("Shutting down database engines")
        try:
            await self.read_engine.dispose()
            await self.engine.dispose()
        except Exception:
            logger.exception("Error while disposing database engines")
            raise
        logger.info("Database engines disposed")
