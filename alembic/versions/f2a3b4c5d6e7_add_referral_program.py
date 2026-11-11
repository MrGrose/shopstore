"""add referral program

Revision ID: f2a3b4c5d6e7
Revises: f1a2b3c4d5e7
Create Date: 2026-06-08 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "f2a3b4c5d6e7"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("referral_code", sa.String(length=16), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("referrer_id", sa.Integer(), nullable=True),
    )
    op.create_index(
        op.f("ix_users_referral_code"), "users", ["referral_code"], unique=True
    )
    op.create_foreign_key(
        "fk_users_referrer_id_users",
        "users",
        "users",
        ["referrer_id"],
        ["id"],
    )

    op.execute(
        "UPDATE users SET referral_code = 'PS-' || id WHERE referral_code IS NULL"
    )
    op.alter_column("users", "referral_code", nullable=False)

    op.add_column(
        "pricing_settings",
        sa.Column(
            "referral_commission_percent",
            sa.Numeric(5, 2),
            nullable=False,
            server_default="5.00",
        ),
    )

    op.create_table(
        "referral_earnings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("referrer_id", sa.Integer(), nullable=False),
        sa.Column("referred_user_id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("order_amount_rub", sa.Numeric(10, 2), nullable=False),
        sa.Column("commission_percent", sa.Numeric(5, 2), nullable=False),
        sa.Column("commission_amount_rub", sa.Numeric(10, 2), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.ForeignKeyConstraint(["referrer_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["referred_user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id", name="uq_referral_earnings_order_id"),
    )
    op.create_index(
        op.f("ix_referral_earnings_referrer_id"),
        "referral_earnings",
        ["referrer_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_referral_earnings_referred_user_id"),
        "referral_earnings",
        ["referred_user_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_referral_earnings_referred_user_id"), table_name="referral_earnings"
    )
    op.drop_index(
        op.f("ix_referral_earnings_referrer_id"), table_name="referral_earnings"
    )
    op.drop_table("referral_earnings")
    op.drop_column("pricing_settings", "referral_commission_percent")
    op.drop_constraint("fk_users_referrer_id_users", "users", type_="foreignkey")
    op.drop_index(op.f("ix_users_referral_code"), table_name="users")
    op.drop_column("users", "referrer_id")
    op.drop_column("users", "referral_code")
