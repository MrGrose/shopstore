"""add pricing settings and promo codes

Revision ID: b9c7d5e3f1a0
Revises: a1b2c3d4e5f6
Create Date: 2026-04-23 20:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "b9c7d5e3f1a0"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "products",
        sa.Column(
            "supplier_price_eur", sa.Numeric(10, 2), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "products",
        sa.Column("pricing_category_key", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "products", sa.Column("eur_rate_snapshot", sa.Numeric(12, 4), nullable=True)
    )
    op.add_column(
        "products",
        sa.Column("margin_snapshot_percent", sa.Numeric(6, 2), nullable=True),
    )
    op.add_column(
        "products", sa.Column("markup_snapshot", sa.Numeric(10, 4), nullable=True)
    )

    op.add_column(
        "orders",
        sa.Column(
            "items_subtotal_amount",
            sa.Numeric(10, 2),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "orders",
        sa.Column(
            "discount_items_amount",
            sa.Numeric(10, 2),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "orders",
        sa.Column(
            "delivery_fee_eur_snapshot",
            sa.Numeric(10, 2),
            nullable=False,
            server_default="30",
        ),
    )
    op.add_column(
        "orders",
        sa.Column(
            "delivery_fee_amount", sa.Numeric(10, 2), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "orders",
        sa.Column(
            "eur_rate_snapshot", sa.Numeric(12, 4), nullable=False, server_default="0"
        ),
    )
    op.add_column(
        "orders", sa.Column("promo_code_applied", sa.String(length=64), nullable=True)
    )

    op.create_table(
        "pricing_settings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("eur_rate", sa.Numeric(12, 4), nullable=False),
        sa.Column("markup_multiplier", sa.Numeric(10, 4), nullable=False),
        sa.Column("delivery_fee_eur", sa.Numeric(10, 2), nullable=False),
        sa.Column("eur_rate_source", sa.String(length=128), nullable=True),
        sa.Column("eur_rate_updated_at", sa.DateTime(), nullable=True),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "margin_rules",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("category_key", sa.String(length=64), nullable=False),
        sa.Column("label", sa.String(length=128), nullable=False),
        sa.Column("margin_percent", sa.Numeric(6, 2), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("category_key", name="uq_margin_rule_category"),
    )
    op.create_table(
        "promo_codes",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("discount_type", sa.String(length=32), nullable=False),
        sa.Column("usage_mode", sa.String(length=32), nullable=False),
        sa.Column("value", sa.Numeric(10, 2), nullable=False),
        sa.Column("min_order_amount", sa.Numeric(10, 2), nullable=False),
        sa.Column("max_discount_amount", sa.Numeric(10, 2), nullable=True),
        sa.Column("usage_limit_total", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("active_from", sa.DateTime(), nullable=True),
        sa.Column("active_to", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code", name="uq_promo_code"),
    )
    op.create_table(
        "promo_code_usages",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("promo_code_id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.ForeignKeyConstraint(["promo_code_id"], ["promo_codes.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_promo_code_usages_order_id"),
        "promo_code_usages",
        ["order_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_promo_code_usages_promo_code_id"),
        "promo_code_usages",
        ["promo_code_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_promo_code_usages_user_id"),
        "promo_code_usages",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f("ix_promo_code_usages_user_id"), table_name="promo_code_usages")
    op.drop_index(
        op.f("ix_promo_code_usages_promo_code_id"), table_name="promo_code_usages"
    )
    op.drop_index(op.f("ix_promo_code_usages_order_id"), table_name="promo_code_usages")
    op.drop_table("promo_code_usages")
    op.drop_table("promo_codes")
    op.drop_table("margin_rules")
    op.drop_table("pricing_settings")

    op.drop_column("orders", "promo_code_applied")
    op.drop_column("orders", "eur_rate_snapshot")
    op.drop_column("orders", "delivery_fee_amount")
    op.drop_column("orders", "delivery_fee_eur_snapshot")
    op.drop_column("orders", "discount_items_amount")
    op.drop_column("orders", "items_subtotal_amount")

    op.drop_column("products", "markup_snapshot")
    op.drop_column("products", "margin_snapshot_percent")
    op.drop_column("products", "eur_rate_snapshot")
    op.drop_column("products", "pricing_category_key")
    op.drop_column("products", "supplier_price_eur")
