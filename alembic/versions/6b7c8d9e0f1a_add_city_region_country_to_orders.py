"""add city region country to orders

Revision ID: 6b7c8d9e0f1a
Revises: 1a2b3c4d5e6f
Create Date: 2026-04-23 14:05:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "6b7c8d9e0f1a"
down_revision: Union[str, Sequence[str], None] = "1a2b3c4d5e6f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("orders", sa.Column("city", sa.String(length=100), nullable=True))
    op.add_column("orders", sa.Column("region", sa.String(length=100), nullable=True))
    op.add_column("orders", sa.Column("country", sa.String(length=100), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("orders", "country")
    op.drop_column("orders", "region")
    op.drop_column("orders", "city")
