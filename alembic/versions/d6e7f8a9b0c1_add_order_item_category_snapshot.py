"""add order item category snapshot

Revision ID: d6e7f8a9b0c1
Revises: c5d6e7f8a9b0
Create Date: 2026-08-20
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d6e7f8a9b0c1"
down_revision: str | Sequence[str] | None = "c5d6e7f8a9b0"
branch_labels = None
depends_on = None


# Snapshot L2/L3 на OrderItem + разовый backfill с Product.
def upgrade() -> None:
    op.add_column(
        "order_items",
        sa.Column("category_l2_captured", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "order_items",
        sa.Column("category_l3_captured", sa.String(length=100), nullable=True),
    )
    op.execute(
        """
        UPDATE order_items AS oi
        SET
            category_l2_captured = p.category_l2,
            category_l3_captured = p.category_l3
        FROM products AS p
        WHERE oi.product_id = p.id
        """
    )


# Удаляет snapshot-колонки категории с order_items.
def downgrade() -> None:
    op.drop_column("order_items", "category_l3_captured")
    op.drop_column("order_items", "category_l2_captured")
