"""add order item snapshots for supplier

Revision ID: 8d9e0f1a2b3c
Revises: 7c8d9e0f1a2b
Create Date: 2026-04-23 15:10:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "8d9e0f1a2b3c"
down_revision: Union[str, Sequence[str], None] = "7c8d9e0f1a2b"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "order_items",
        sa.Column("product_title_snapshot", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "order_items",
        sa.Column("product_external_id_snapshot", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "order_items",
        sa.Column("variant_external_id_snapshot", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "order_items",
        sa.Column("variant_sku_snapshot", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "order_items",
        sa.Column("variant_option1_snapshot", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "order_items",
        sa.Column("variant_option2_snapshot", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "order_items",
        sa.Column("variant_option3_snapshot", sa.String(length=100), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("order_items", "variant_option3_snapshot")
    op.drop_column("order_items", "variant_option2_snapshot")
    op.drop_column("order_items", "variant_option1_snapshot")
    op.drop_column("order_items", "variant_sku_snapshot")
    op.drop_column("order_items", "variant_external_id_snapshot")
    op.drop_column("order_items", "product_external_id_snapshot")
    op.drop_column("order_items", "product_title_snapshot")
