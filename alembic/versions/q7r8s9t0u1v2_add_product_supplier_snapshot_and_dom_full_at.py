"""add supplier snapshot and dom_full_at to products

Revision ID: q7r8s9t0u1v2
Revises: p6q7r8s9t0u1
Create Date: 2026-06-14 22:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "q7r8s9t0u1v2"
down_revision: Union[str, Sequence[str], None] = "p6q7r8s9t0u1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column("supplier_snapshot_json", sa.JSON(), nullable=True),
    )
    op.add_column(
        "products",
        sa.Column("supplier_snapshot_hash", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "products",
        sa.Column("dom_full_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("products", "dom_full_at")
    op.drop_column("products", "supplier_snapshot_hash")
    op.drop_column("products", "supplier_snapshot_json")
