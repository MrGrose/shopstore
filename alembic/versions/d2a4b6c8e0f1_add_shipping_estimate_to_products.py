"""add shipping_estimate to products

Revision ID: d2a4b6c8e0f1
Revises: b7d9c3e4f5a6
Create Date: 2026-04-22 20:10:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "d2a4b6c8e0f1"
down_revision: Union[str, Sequence[str], None] = "b7d9c3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "products",
        sa.Column("shipping_estimate", sa.String(length=255), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("products", "shipping_estimate")
