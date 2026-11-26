"""Alembic migration environment configuration for SQLModel schemas."""

from alembic import context
from sqlalchemy import create_engine
from sqlmodel import SQLModel

# Register all SQLModel tables.
from codex_query.infrastructure.database.sqlmodel import (
    models,  # noqa: F401  # pyright: ignore[reportUnusedImport]
)
from codex_query.infrastructure.database.sqlmodel.config import db_config
from codex_query.infrastructure.logging.factory import create_logger

logger = create_logger(__name__)

target_metadata = SQLModel.metadata


def run_migrations_online() -> None:
    """Run migrations using a synchronous database connection."""
    logger.info("Starting database migrations.")

    engine = create_engine(db_config.sync_url)

    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=True,
            )

            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()

    logger.info("Database migrations completed.")


run_migrations_online()
