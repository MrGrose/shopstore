"""add order payment deadline and cancellation reason

Revision ID: y5z6a7b8c9d0
Revises: w3x4y5z6a7b8
Create Date: 2026-07-01 16:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "y5z6a7b8c9d0"
down_revision: Union[str, Sequence[str], None] = "w3x4y5z6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("payment_due_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("cancellation_reason", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_orders_status_payment_due_at",
        "orders",
        ["status", "payment_due_at"],
        unique=False,
    )

    op.execute(
        """
        UPDATE orders
        SET payment_due_at = NULL
        WHERE payment_paid_at IS NOT NULL
        """
    )
    op.execute(
        """
        UPDATE orders
        SET payment_due_at = NULL
        WHERE availability_confirmation_status = 'pending'
        """
    )
    op.execute(
        """
        UPDATE orders
        SET payment_due_at = now() + interval '24 hours'
        WHERE payment_paid_at IS NULL
          AND status IN ('created', 'processing')
          AND availability_confirmation_status != 'pending'
          AND payment_due_at IS NULL
        """
    )


def downgrade() -> None:
    op.drop_index("ix_orders_status_payment_due_at", table_name="orders")
    op.drop_column("orders", "cancellation_reason")
    op.drop_column("orders", "payment_due_at")
