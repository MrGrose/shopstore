"""add product related tables

Revision ID: f4a1b9c2d3e4
Revises: c1f2b8d4e9a1
Create Date: 2026-04-22 17:20:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "f4a1b9c2d3e4"
down_revision: Union[str, Sequence[str], None] = "c1f2b8d4e9a1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "products", sa.Column("external_id", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "products", sa.Column("category_l1", sa.String(length=100), nullable=True)
    )
    op.add_column(
        "products", sa.Column("category_l2", sa.String(length=100), nullable=True)
    )
    op.add_column(
        "products", sa.Column("category_l3", sa.String(length=100), nullable=True)
    )
    op.add_column(
        "products", sa.Column("sport_type", sa.String(length=50), nullable=True)
    )
    op.add_column(
        "products", sa.Column("trade_group", sa.String(length=50), nullable=True)
    )
    op.add_column("products", sa.Column("gender", sa.String(length=50), nullable=True))
    op.create_unique_constraint("uq_products_external_id", "products", ["external_id"])

    op.create_table(
        "product_variants",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("variant_external_id", sa.String(length=64), nullable=True),
        sa.Column("sku", sa.String(length=64), nullable=True),
        sa.Column("barcode", sa.String(length=64), nullable=True),
        sa.Column("option1", sa.String(length=100), nullable=True),
        sa.Column("option2", sa.String(length=100), nullable=True),
        sa.Column("option3", sa.String(length=100), nullable=True),
        sa.Column("price", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("compare_at_price", sa.Numeric(precision=10, scale=2), nullable=True),
        sa.Column("inventory_quantity", sa.Integer(), nullable=False),
        sa.Column("available", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "variant_external_id", name="uq_product_variants_external_id"
        ),
    )
    op.create_index(
        op.f("ix_product_variants_product_id"),
        "product_variants",
        ["product_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_product_variants_sku"), "product_variants", ["sku"], unique=False
    )
    op.create_index(
        op.f("ix_product_variants_barcode"),
        "product_variants",
        ["barcode"],
        unique=False,
    )

    op.create_table(
        "product_images",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(length=512), nullable=False),
        sa.Column("alt", sa.String(length=255), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_product_images_product_id"),
        "product_images",
        ["product_id"],
        unique=False,
    )

    op.create_table(
        "product_features",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("product_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("value", sa.String(length=255), nullable=True),
        sa.Column("icon_url", sa.String(length=512), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_product_features_product_id"),
        "product_features",
        ["product_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_product_features_product_id"), table_name="product_features")
    op.drop_table("product_features")

    op.drop_index(op.f("ix_product_images_product_id"), table_name="product_images")
    op.drop_table("product_images")

    op.drop_index(op.f("ix_product_variants_barcode"), table_name="product_variants")
    op.drop_index(op.f("ix_product_variants_sku"), table_name="product_variants")
    op.drop_index(op.f("ix_product_variants_product_id"), table_name="product_variants")
    op.drop_table("product_variants")

    op.drop_constraint("uq_products_external_id", "products", type_="unique")
    op.drop_column("products", "gender")
    op.drop_column("products", "trade_group")
    op.drop_column("products", "sport_type")
    op.drop_column("products", "category_l3")
    op.drop_column("products", "category_l2")
    op.drop_column("products", "category_l1")
    op.drop_column("products", "external_id")
