"""add paid_supplier_order_count on orders

Revision ID: b3c4d5e6f7a8
Revises: a9b0c1d2e3f4
Create Date: 2026-08-19
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op
from src.core.order_limits import max_supplier_goods_eur

revision: str = "b3c4d5e6f7a8"
down_revision: Union[str, Sequence[str], None] = "a9b0c1d2e3f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("paid_supplier_order_count", sa.Integer(), nullable=True),
    )
    cap = max_supplier_goods_eur()
    op.execute(
        sa.text(
            """
            UPDATE orders
            SET paid_supplier_order_count = CASE
                WHEN COALESCE(supplier_cost_eur_snapshot, 0) <= 0 THEN
                    CASE
                        WHEN EXISTS (
                            SELECT 1 FROM order_items
                            WHERE order_items.order_id = orders.id
                        ) THEN 1
                        ELSE 0
                    END
                ELSE CAST(
                    CEILING(supplier_cost_eur_snapshot / :cap) AS INTEGER
                )
            END
            WHERE payment_paid_at IS NOT NULL
            """
        ).bindparams(cap=cap)
    )


def downgrade() -> None:
    op.drop_column("orders", "paid_supplier_order_count")
