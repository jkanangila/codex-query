"""update fields job table

Revision ID: a018030de05f
Revises: 99f707b162fe
Create Date: 2026-10-21 10:51:09.247931
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a018030de05f"
down_revision: str | Sequence[str] | None = "99f707b162fe"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
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


def downgrade() -> None:
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
