"""add shipments table

Revision ID: c5d6e7f8a9b0
Revises: b3c4d5e6f7a8
Create Date: 2026-08-19
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c5d6e7f8a9b0"
down_revision: str | Sequence[str] | None = "b3c4d5e6f7a8"
branch_labels = None
depends_on = None


# Таблица customer-facing Shipment; данные — service backfill, не SQL здесь.
def upgrade() -> None:
    op.create_table(
        "shipments",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("supplier_order_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("supplier_carrier", sa.String(length=64), nullable=True),
        sa.Column("supplier_tracking_number", sa.String(length=128), nullable=True),
        sa.Column("supplier_tracking_url", sa.Text(), nullable=True),
        sa.Column("customer_carrier", sa.String(length=64), nullable=True),
        sa.Column("customer_tracking_number", sa.String(length=128), nullable=True),
        sa.Column("customer_tracking_url", sa.Text(), nullable=True),
        sa.Column("status_updated_at", sa.DateTime(), nullable=True),
        sa.Column("delivered_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=True,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=True,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["supplier_order_id"],
            ["supplier_orders.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("supplier_order_id", name="uq_shipments_supplier_order_id"),
        sa.CheckConstraint(
            "status IN ('preparing', 'in_transit', 'delivered')",
            name="ck_shipments_status",
        ),
    )
    op.create_index("ix_shipments_order_id", "shipments", ["order_id"])


def downgrade() -> None:
    op.drop_index("ix_shipments_order_id", table_name="shipments")
    op.drop_table("shipments")
