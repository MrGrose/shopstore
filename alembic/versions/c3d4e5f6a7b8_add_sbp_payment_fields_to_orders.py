"""add sbp payment fields to orders

Revision ID: c3d4e5f6a7b8
Revises: b9c7d5e3f1a0
Create Date: 2026-04-23 23:40:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b9c7d5e3f1a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "orders", sa.Column("payment_provider", sa.String(length=32), nullable=True)
    )
    op.add_column(
        "orders", sa.Column("payment_order_id", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "orders",
        sa.Column("payment_external_order_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "orders", sa.Column("payment_status", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "orders", sa.Column("payment_qr_id", sa.String(length=128), nullable=True)
    )
    op.add_column("orders", sa.Column("payment_qr_payload", sa.Text(), nullable=True))
    op.add_column("orders", sa.Column("payment_meta_json", sa.JSON(), nullable=True))
    op.add_column(
        "orders", sa.Column("payment_last_callback_at", sa.DateTime(), nullable=True)
    )
    op.add_column("orders", sa.Column("payment_paid_at", sa.DateTime(), nullable=True))
    op.create_index(
        op.f("ix_orders_payment_order_id"), "orders", ["payment_order_id"], unique=True
    )
    op.create_index(
        op.f("ix_orders_payment_status"), "orders", ["payment_status"], unique=False
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_orders_payment_status"), table_name="orders")
    op.drop_index(op.f("ix_orders_payment_order_id"), table_name="orders")
    op.drop_column("orders", "payment_paid_at")
    op.drop_column("orders", "payment_last_callback_at")
    op.drop_column("orders", "payment_meta_json")
    op.drop_column("orders", "payment_qr_payload")
    op.drop_column("orders", "payment_qr_id")
    op.drop_column("orders", "payment_status")
    op.drop_column("orders", "payment_external_order_id")
    op.drop_column("orders", "payment_order_id")
    op.drop_column("orders", "payment_provider")
