"""add delivery fields to orders

Revision ID: 1a2b3c4d5e6f
Revises: e8c4a9b1d2f3
Create Date: 2026-04-23 13:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "1a2b3c4d5e6f"
down_revision: Union[str, Sequence[str], None] = "e8c4a9b1d2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "orders", sa.Column("last_name", sa.String(length=100), nullable=True)
    )
    op.add_column(
        "orders", sa.Column("first_name", sa.String(length=100), nullable=True)
    )
    op.add_column("orders", sa.Column("street", sa.String(length=255), nullable=True))
    op.add_column("orders", sa.Column("house", sa.String(length=50), nullable=True))
    op.add_column("orders", sa.Column("apartment", sa.String(length=50), nullable=True))
    op.add_column(
        "orders", sa.Column("postal_code", sa.String(length=20), nullable=True)
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("orders", "postal_code")
    op.drop_column("orders", "apartment")
    op.drop_column("orders", "house")
    op.drop_column("orders", "street")
    op.drop_column("orders", "first_name")
    op.drop_column("orders", "last_name")
