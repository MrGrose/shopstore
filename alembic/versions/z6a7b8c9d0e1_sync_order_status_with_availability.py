"""sync order status with availability; add supplier fields

Revision ID: z6a7b8c9d0e1
Revises: y5z6a7b8c9d0
Create Date: 2026-07-03 18:40:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "z6a7b8c9d0e1"
down_revision: Union[str, Sequence[str], None] = "y5z6a7b8c9d0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

orders = sa.table(
    "orders",
    sa.column("status", sa.String()),
    sa.column("availability_confirmation_status", sa.String()),
)


def build_status_sync_statement() -> sa.Update:
    return (
        orders.update()
        .where(
            orders.c.status == "processing",
            orders.c.availability_confirmation_status.in_(
                ("not_required", "confirmed")
            ),
        )
        .values(status="created")
    )


def upgrade() -> None:
    op.add_column(
        "orders",
        sa.Column("supplier_order_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("supplier_tracking_id", sa.String(length=128), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("supplier_delivery_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("failed_from_status", sa.String(length=32), nullable=True),
    )
    op.execute(build_status_sync_statement())


def downgrade() -> None:
    op.drop_column("orders", "failed_from_status")
    op.drop_column("orders", "supplier_delivery_json")
    op.drop_column("orders", "supplier_tracking_id")
    op.drop_column("orders", "supplier_order_id")
