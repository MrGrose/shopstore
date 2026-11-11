"""add users referral_alias

Revision ID: t0u1v2w3x4y5
Revises: s9t0u1v2w3x4
Create Date: 2026-06-18 18:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "t0u1v2w3x4y5"
down_revision: Union[str, Sequence[str], None] = "s9t0u1v2w3x4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("referral_alias", sa.String(length=32), nullable=True),
    )
    op.create_index(
        op.f("ix_users_referral_alias"),
        "users",
        ["referral_alias"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_users_referral_alias"), table_name="users")
    op.drop_column("users", "referral_alias")
