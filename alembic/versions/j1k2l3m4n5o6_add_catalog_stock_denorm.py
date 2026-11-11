"""add catalog_in_stock and available_qty to products

Revision ID: j1k2l3m4n5o6
Revises: g3h4i5j6k7l8
Create Date: 2026-06-10 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "j1k2l3m4n5o6"
down_revision: Union[str, Sequence[str], None] = "i5j6k7l8m9n0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column(
            "catalog_in_stock",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "products",
        sa.Column(
            "available_qty",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_index(
        "ix_products_catalog_in_stock",
        "products",
        ["catalog_in_stock"],
        unique=False,
    )
    op.create_index(
        "ix_products_sport_active_l2",
        "products",
        ["sport_type", "is_active", "category_l2"],
        unique=False,
    )
    op.create_index(
        "ix_products_sport_l3",
        "products",
        ["sport_type", "category_l3"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_products_sport_l3", table_name="products")
    op.drop_index("ix_products_sport_active_l2", table_name="products")
    op.drop_index("ix_products_catalog_in_stock", table_name="products")
    op.drop_column("products", "available_qty")
    op.drop_column("products", "catalog_in_stock")
