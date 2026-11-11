"""add description translation fields

Revision ID: e1f2a3b4c5d6
Revises: d4e5f6a7b8c9
Create Date: 2026-05-13 17:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: Union[str, Sequence[str], None] = "d4e5f6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("products", sa.Column("description_raw", sa.Text(), nullable=True))
    op.add_column("products", sa.Column("description_ru", sa.Text(), nullable=True))
    op.add_column(
        "products", sa.Column("description_hash", sa.String(length=64), nullable=True)
    )
    op.execute(
        "UPDATE products SET description_raw = description "
        "WHERE description IS NOT NULL AND description_raw IS NULL"
    )
    op.drop_column("products", "description")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column("products", sa.Column("description", sa.Text(), nullable=True))
    op.execute(
        "UPDATE products SET description = COALESCE(description_ru, description_raw)"
    )
    op.drop_column("products", "description_hash")
    op.drop_column("products", "description_ru")
    op.drop_column("products", "description_raw")
