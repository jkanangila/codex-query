"""Alembic migration environment configuration for SQLModel schemas."""

from alembic import context
from sqlalchemy import create_engine
from sqlmodel import SQLModel

# Imported for side effects so SQLModel registers all table models on SQLModel.metadata.
from codex_query.infrastructure.database.sqlmodel import (
    models,  # noqa: F401  # pyright: ignore[reportUnusedImport]
)
from codex_query.infrastructure.database.sqlmodel.config import db_config
from codex_query.infrastructure.logging.factory import create_logger

logger = create_logger(__name__)

target_metadata = SQLModel.metadata

logger.info("Starting database migrations")
try:
    with create_engine(db_config.sync_url).connect() as conn:
        context.configure(
            connection=conn,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()
except Exception:
    logger.exception("Database migrations failed")
    raise
logger.info("Database migrations completed")
