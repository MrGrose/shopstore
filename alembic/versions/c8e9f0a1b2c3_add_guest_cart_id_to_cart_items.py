"""add guest_cart_id to cart_items

Revision ID: c8e9f0a1b2c3
Revises: b1c2d3e4f5a6
Create Date: 2026-05-27 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "c8e9f0a1b2c3"
down_revision: Union[str, Sequence[str], None] = "b1c2d3e4f5a6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("cart_items", "user_id", existing_type=sa.Integer(), nullable=True)
    op.add_column(
        "cart_items",
        sa.Column("guest_cart_id", sa.String(length=36), nullable=True),
    )
    op.create_index(
        "ix_cart_items_guest_cart_id",
        "cart_items",
        ["guest_cart_id"],
        unique=False,
    )
    op.create_check_constraint(
        "ck_cart_items_user_or_guest",
        "cart_items",
        "num_nonnulls(user_id, guest_cart_id) = 1",
    )
    op.create_index(
        "uq_cart_guest_product_no_variant",
        "cart_items",
        ["guest_cart_id", "product_id"],
        unique=True,
        postgresql_where=sa.text("variant_id IS NULL AND guest_cart_id IS NOT NULL"),
    )
    op.create_index(
        "uq_cart_guest_product_variant",
        "cart_items",
        ["guest_cart_id", "product_id", "variant_id"],
        unique=True,
        postgresql_where=sa.text(
            "variant_id IS NOT NULL AND guest_cart_id IS NOT NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_cart_guest_product_variant", table_name="cart_items")
    op.drop_index("uq_cart_guest_product_no_variant", table_name="cart_items")
    op.drop_constraint("ck_cart_items_user_or_guest", "cart_items", type_="check")
    op.drop_index("ix_cart_items_guest_cart_id", table_name="cart_items")
    op.drop_column("cart_items", "guest_cart_id")
    op.alter_column("cart_items", "user_id", existing_type=sa.Integer(), nullable=False)
