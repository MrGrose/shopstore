"""add lightweight supplier tracking state

Revision ID: f9a0b1c2d3e4
Revises: e8f9a0b1c2d3
Create Date: 2026-07-07 20:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "f9a0b1c2d3e4"
down_revision: Union[str, Sequence[str], None] = "e8f9a0b1c2d3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "orders", sa.Column("supplier_tracking_json", sa.JSON(), nullable=True)
    )
    op.add_column(
        "orders",
        sa.Column("supplier_tracking_checked_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("supplier_tracking_updated_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("supplier_tracking_next_check_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "orders", sa.Column("supplier_tracking_last_error", sa.Text(), nullable=True)
    )
    op.add_column(
        "orders",
        sa.Column(
            "supplier_tracking_failures",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "orders",
        sa.Column("supplier_tracking_sync_state", sa.String(16), nullable=True),
    )
    op.create_index(
        "ix_orders_supplier_tracking_next_check_at",
        "orders",
        ["supplier_tracking_next_check_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_orders_supplier_tracking_next_check_at", table_name="orders")
    op.drop_column("orders", "supplier_tracking_sync_state")
    op.drop_column("orders", "supplier_tracking_failures")
    op.drop_column("orders", "supplier_tracking_last_error")
    op.drop_column("orders", "supplier_tracking_next_check_at")
    op.drop_column("orders", "supplier_tracking_updated_at")
    op.drop_column("orders", "supplier_tracking_checked_at")
    op.drop_column("orders", "supplier_tracking_json")
