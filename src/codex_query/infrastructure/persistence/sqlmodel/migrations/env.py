from alembic import context
from sqlalchemy import create_engine
from sqlmodel import SQLModel

from codex_query.infrastructure.persistence.sqlmodel import (
    models,  # noqa: F401  # pyright: ignore[reportUnusedImport]
)
from codex_query.infrastructure.persistence.sqlmodel.config import db_config

target_metadata = SQLModel.metadata

with create_engine(db_config.sync_url).connect() as conn:
    context.configure(
        connection=conn,
        target_metadata=target_metadata,
        render_as_batch=False,
    )
    with context.begin_transaction():
        context.run_migrations()
