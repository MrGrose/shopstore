"""add variant_id to cart and order items

Revision ID: b7d9c3e4f5a6
Revises: f4a1b9c2d3e4
Create Date: 2026-04-22 19:20:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "b7d9c3e4f5a6"
down_revision: Union[str, Sequence[str], None] = "f4a1b9c2d3e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column("cart_items", sa.Column("variant_id", sa.Integer(), nullable=True))
    op.add_column("order_items", sa.Column("variant_id", sa.Integer(), nullable=True))

    op.create_foreign_key(
        "fk_cart_items_variant_id_product_variants",
        "cart_items",
        "product_variants",
        ["variant_id"],
        ["id"],
    )
    op.create_foreign_key(
        "fk_order_items_variant_id_product_variants",
        "order_items",
        "product_variants",
        ["variant_id"],
        ["id"],
    )
    op.create_index(
        op.f("ix_cart_items_variant_id"),
        "cart_items",
        ["variant_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_order_items_variant_id"),
        "order_items",
        ["variant_id"],
        unique=False,
    )

    op.drop_constraint("uq_cart_user_product", "cart_items", type_="unique")
    op.create_index(
        "uq_cart_user_product_no_variant",
        "cart_items",
        ["user_id", "product_id"],
        unique=True,
        postgresql_where=sa.text("variant_id IS NULL"),
    )
    op.create_index(
        "uq_cart_user_product_variant",
        "cart_items",
        ["user_id", "product_id", "variant_id"],
        unique=True,
        postgresql_where=sa.text("variant_id IS NOT NULL"),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index("uq_cart_user_product_variant", table_name="cart_items")
    op.drop_index("uq_cart_user_product_no_variant", table_name="cart_items")
    op.create_unique_constraint(
        "uq_cart_user_product",
        "cart_items",
        ["user_id", "product_id"],
    )

    op.drop_index(op.f("ix_order_items_variant_id"), table_name="order_items")
    op.drop_index(op.f("ix_cart_items_variant_id"), table_name="cart_items")
    op.drop_constraint(
        "fk_order_items_variant_id_product_variants",
        "order_items",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_cart_items_variant_id_product_variants",
        "cart_items",
        type_="foreignkey",
    )
    op.drop_column("order_items", "variant_id")
    op.drop_column("cart_items", "variant_id")
