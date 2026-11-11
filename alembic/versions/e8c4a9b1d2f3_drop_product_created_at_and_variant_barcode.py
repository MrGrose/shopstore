"""drop product created_at and variant barcode

Revision ID: e8c4a9b1d2f3
Revises: d2a4b6c8e0f1
Create Date: 2026-04-23 10:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "e8c4a9b1d2f3"
down_revision: Union[str, Sequence[str], None] = "d2a4b6c8e0f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.drop_index(op.f("ix_product_variants_barcode"), table_name="product_variants")
    op.drop_column("product_variants", "barcode")
    op.drop_column("products", "created_at")


def downgrade() -> None:
    """Downgrade schema."""
    op.add_column(
        "products",
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True
        ),
    )
    op.add_column(
        "product_variants",
        sa.Column("barcode", sa.String(length=64), nullable=True),
    )
    op.create_index(
        op.f("ix_product_variants_barcode"),
        "product_variants",
        ["barcode"],
        unique=False,
    )
