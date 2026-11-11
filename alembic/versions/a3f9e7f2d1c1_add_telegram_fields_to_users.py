"""add_telegram_fields_to_users

Revision ID: a3f9e7f2d1c1
Revises: 4826d7ab39a6
Create Date: 2026-04-22 11:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "a3f9e7f2d1c1"
down_revision: Union[str, Sequence[str], None] = "4826d7ab39a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("users", sa.Column("telegram_id", sa.Integer(), nullable=True))
    op.add_column(
        "users", sa.Column("telegram_username", sa.String(length=255), nullable=True)
    )
    op.create_index(op.f("ix_users_telegram_id"), "users", ["telegram_id"], unique=True)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_users_telegram_id"), table_name="users")
    op.drop_column("users", "telegram_username")
    op.drop_column("users", "telegram_id")
