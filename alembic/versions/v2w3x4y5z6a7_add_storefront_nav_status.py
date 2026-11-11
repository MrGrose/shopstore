"""add storefront_nav_status denorm to products

Revision ID: v2w3x4y5z6a7
Revises: u1v2w3x4y5z6
Create Date: 2026-06-20 18:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "v2w3x4y5z6a7"
down_revision: Union[str, Sequence[str], None] = "u1v2w3x4y5z6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column(
            "storefront_nav_status",
            sa.String(length=20),
            nullable=False,
            server_default="not_sellable",
        ),
    )
    op.create_index(
        "ix_products_storefront_nav_status",
        "products",
        ["storefront_nav_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_products_storefront_nav_status", table_name="products")
    op.drop_column("products", "storefront_nav_status")
