"""drop region and country from orders

Revision ID: 7c8d9e0f1a2b
Revises: 6b7c8d9e0f1a
Create Date: 2026-04-23 14:40:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "7c8d9e0f1a2b"
down_revision: Union[str, Sequence[str], None] = "6b7c8d9e0f1a"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_column("orders", "country")
    op.drop_column("orders", "region")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column("orders", sa.Column("region", sa.String(length=100), nullable=True))
    op.add_column("orders", sa.Column("country", sa.String(length=100), nullable=True))
