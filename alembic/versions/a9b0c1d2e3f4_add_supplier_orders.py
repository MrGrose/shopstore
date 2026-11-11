"""add supplier_orders and supplier_order_lines

Revision ID: a9b0c1d2e3f4
Revises: p1v2s3t4u5v6
Create Date: 2026-08-19
"""

import sqlalchemy as sa

from alembic import op
from src.core.config import settings

revision = "a9b0c1d2e3f4"
down_revision = "p1v2s3t4u5v6"
branch_labels = None
depends_on = None

_BACKFILL_PLACED_BY = "backfill:3a"


# Создаёт таблицы SupplierOrder и зеркалирует legacy supplier_order_id.
def upgrade() -> None:
    op.create_table(
        "supplier_orders",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("seq", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("goods_eur", sa.Numeric(12, 2), nullable=False),
        sa.Column("supplier_shipping_eur", sa.Numeric(12, 2), nullable=False),
        sa.Column("placed_at", sa.DateTime(), nullable=True),
        sa.Column("placed_by", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=True,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=True,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("order_id", "seq", name="uq_supplier_orders_order_id_seq"),
        sa.UniqueConstraint("external_id", name="uq_supplier_orders_external_id"),
    )

    op.create_table(
        "supplier_order_lines",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("supplier_order_id", sa.Integer(), nullable=False),
        sa.Column("order_item_id", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("unit_supplier_eur", sa.Numeric(10, 2), nullable=False),
        sa.ForeignKeyConstraint(
            ["supplier_order_id"],
            ["supplier_orders.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["order_item_id"],
            ["order_items.id"],
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "supplier_order_id",
            "order_item_id",
            name="uq_supplier_order_lines_so_item",
        ),
        sa.CheckConstraint(
            "quantity > 0", name="ck_supplier_order_lines_quantity_positive"
        ),
    )
    op.create_index(
        "ix_supplier_order_lines_order_item_id",
        "supplier_order_lines",
        ["order_item_id"],
    )

    shipping = str(settings.SUPPLIER_ORDER_SHIPPING_EUR)
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            INSERT INTO supplier_orders (
                order_id,
                seq,
                external_id,
                status,
                goods_eur,
                supplier_shipping_eur,
                placed_at,
                placed_by,
                created_at,
                updated_at
            )
            SELECT
                o.id,
                1,
                btrim(o.supplier_order_id),
                'placed',
                round(
                    coalesce(
                        sum(
                            oi.quantity
                            * round(
                                coalesce(oi.supplier_price_eur_captured, 0),
                                2
                            )
                        ),
                        0
                    ),
                    2
                ),
                :shipping,
                now(),
                :placed_by,
                now(),
                now()
            FROM orders o
            LEFT JOIN order_items oi ON oi.order_id = o.id
            WHERE o.supplier_order_id IS NOT NULL
              AND btrim(o.supplier_order_id) <> ''
              AND NOT EXISTS (
                  SELECT 1
                  FROM supplier_orders so
                  WHERE so.order_id = o.id
              )
            GROUP BY o.id, o.supplier_order_id
            ON CONFLICT ON CONSTRAINT uq_supplier_orders_external_id DO NOTHING
            """
        ),
        {"shipping": shipping, "placed_by": _BACKFILL_PLACED_BY},
    )
    bind.execute(
        sa.text(
            """
            INSERT INTO supplier_order_lines (
                supplier_order_id,
                order_item_id,
                quantity,
                unit_supplier_eur
            )
            SELECT
                so.id,
                oi.id,
                oi.quantity,
                round(coalesce(oi.supplier_price_eur_captured, 0), 2)
            FROM supplier_orders so
            JOIN order_items oi ON oi.order_id = so.order_id
            WHERE so.seq = 1
              AND oi.quantity > 0
              AND NOT EXISTS (
                  SELECT 1
                  FROM supplier_order_lines sol
                  WHERE sol.supplier_order_id = so.id
                    AND sol.order_item_id = oi.id
              )
            """
        )
    )


# Удаляет таблицы SupplierOrder (lines сначала).
def downgrade() -> None:
    op.drop_table("supplier_order_lines")
    op.drop_table("supplier_orders")
