"""add finance report fields

Revision ID: c0d1e2f3a4b5
Revises: a8b9c0d1e2f3
Create Date: 2026-07-06 00:10:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "c0d1e2f3a4b5"
down_revision: Union[str, Sequence[str], None] = "a8b9c0d1e2f3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column(
            "supplier_cost_eur_snapshot",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "order_items",
        sa.Column(
            "supplier_price_eur_captured",
            sa.Numeric(precision=10, scale=2),
            nullable=True,
        ),
    )
    op.add_column(
        "pricing_settings",
        sa.Column(
            "service_commission_percent",
            sa.Numeric(precision=5, scale=2),
            nullable=False,
            server_default="6.50",
        ),
    )
    op.create_index(
        "ix_orders_payment_paid_at",
        "orders",
        ["payment_paid_at"],
        unique=False,
        postgresql_where=sa.text("payment_paid_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "ix_orders_payment_paid_at",
        table_name="orders",
        postgresql_where=sa.text("payment_paid_at IS NOT NULL"),
    )
    op.drop_column("pricing_settings", "service_commission_percent")
    op.drop_column("order_items", "supplier_price_eur_captured")
    op.drop_column("orders", "supplier_cost_eur_snapshot")
