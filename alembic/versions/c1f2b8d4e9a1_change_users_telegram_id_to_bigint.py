"""change_users_telegram_id_to_bigint

Revision ID: c1f2b8d4e9a1
Revises: a3f9e7f2d1c1
Create Date: 2026-04-22 13:10:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "c1f2b8d4e9a1"
down_revision: Union[str, Sequence[str], None] = "a3f9e7f2d1c1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.alter_column(
        "users",
        "telegram_id",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=True,
        postgresql_using="telegram_id::bigint",
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.alter_column(
        "users",
        "telegram_id",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=True,
        postgresql_using="telegram_id::integer",
    )
