"""cleanup users schema drift

Revision ID: s9t0u1v2w3x4
Revises: r8s9t0u1v2w3
Create Date: 2026-06-18 12:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "s9t0u1v2w3x4"
down_revision: Union[str, Sequence[str], None] = "r8s9t0u1v2w3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Убирает legacy tg_id и приводит referral_code к nullable в модели User.
def upgrade() -> None:
    op.drop_constraint("users_tg_id_key", "users", type_="unique")
    op.drop_column("users", "tg_id")
    op.alter_column(
        "users",
        "referral_code",
        existing_type=sa.String(length=16),
        nullable=True,
    )


# Восстанавливает tg_id и NOT NULL referral_code для отката.
def downgrade() -> None:
    op.alter_column(
        "users",
        "referral_code",
        existing_type=sa.String(length=16),
        nullable=False,
    )
    op.add_column("users", sa.Column("tg_id", sa.Integer(), nullable=True))
    op.create_unique_constraint("users_tg_id_key", "users", ["tg_id"])
