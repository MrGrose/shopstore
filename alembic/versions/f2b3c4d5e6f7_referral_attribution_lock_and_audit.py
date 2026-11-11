"""referral attribution lock and customer_referral_audit"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "f2b3c4d5e6f7"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "referral_attribution_locked",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_table(
        "customer_referral_audit",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("customer_id", sa.Integer(), nullable=False),
        sa.Column("admin_user_id", sa.Integer(), nullable=False),
        sa.Column("old_referrer_id", sa.Integer(), nullable=True),
        sa.Column("new_referrer_id", sa.Integer(), nullable=True),
        sa.Column("old_attribution_locked", sa.Boolean(), nullable=False),
        sa.Column("new_attribution_locked", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(["admin_user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["customer_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["new_referrer_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["old_referrer_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_customer_referral_audit_admin_user_id"),
        "customer_referral_audit",
        ["admin_user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_customer_referral_audit_customer_id"),
        "customer_referral_audit",
        ["customer_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_customer_referral_audit_customer_id"),
        table_name="customer_referral_audit",
    )
    op.drop_index(
        op.f("ix_customer_referral_audit_admin_user_id"),
        table_name="customer_referral_audit",
    )
    op.drop_table("customer_referral_audit")
    op.drop_column("users", "referral_attribution_locked")
