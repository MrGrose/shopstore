"""drop storefront_nav_status denorm column

Revision ID: x4y5z6a7b8c9
Revises: w3x4y5z6a7b8
Create Date: 2026-06-21 18:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "x4y5z6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "m1n2o3p4q5r6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("ix_products_storefront_nav_status", table_name="products")
    op.drop_column("products", "storefront_nav_status")


def downgrade() -> None:
    op.add_column(
        "products",
        sa.Column(
            "storefront_nav_status",
            sa.String(length=20),
            server_default="not_sellable",
            nullable=False,
        ),
    )
    op.create_index(
        "ix_products_storefront_nav_status",
        "products",
        ["storefront_nav_status"],
        unique=False,
    )
