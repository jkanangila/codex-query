"""update fields job table

Revision ID: a018030de05f
Revises: 99f707b162fe
Create Date: 2026-10-21 10:51:09.247931

Alembic migration replacing ``book.author`` with a JSON ``authors`` column and
updating ``indexing_job`` with an ``eta`` column and UUID primary key column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from codex_query.infrastructure.logging.factory import create_logger

revision: str = "a018030de05f"
down_revision: str | Sequence[str] | None = "99f707b162fe"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

logger = create_logger(__name__)


def upgrade() -> None:
    """Apply schema updates to the ``book`` and ``indexing_job`` tables.

    Replaces ``book.author`` with a non-nullable JSON ``authors`` column, adds a
    non-nullable float ``eta`` column to ``indexing_job``, and alters
    ``indexing_job.id`` from integer to UUID using batch table operations.
    """
    logger.debug("Applying schema upgrade (revision %s)", revision)

    # Update book table
    with op.batch_alter_table("book") as batch_op:
        batch_op.add_column(sa.Column("authors", sa.JSON(), nullable=False))
        batch_op.drop_column("author")

    # Update indexing_job table
    with op.batch_alter_table("indexing_job") as batch_op:
        batch_op.add_column(sa.Column("eta", sa.Float(), nullable=False))
        batch_op.alter_column(
            "id",
            existing_type=sa.Integer(),
            type_=sa.Uuid(),
            existing_nullable=False,
        )

    logger.debug("Completed schema upgrade (revision %s)", revision)


def downgrade() -> None:
    """Revert ``indexing_job`` and ``book`` schema changes from this revision.

    Reverts ``indexing_job.id`` from UUID back to integer, drops ``indexing_job.eta``,
    and restores ``book.author`` while dropping ``book.authors``.
    """
    logger.debug("Reverting schema upgrade (revision %s)", revision)

    # Revert indexing_job changes
    with op.batch_alter_table("indexing_job") as batch_op:
        batch_op.alter_column(
            "id",
            existing_type=sa.Uuid(),
            type_=sa.Integer(),
            existing_nullable=False,
        )
        batch_op.drop_column("eta")

    # Revert book changes
    with op.batch_alter_table("book") as batch_op:
        batch_op.add_column(sa.Column("author", sa.String(), nullable=False))
        batch_op.drop_column("authors")

    logger.debug("Completed schema downgrade (revision %s)", revision)
