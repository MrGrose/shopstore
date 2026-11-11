"""add eur rate history

Revision ID: c4d5e6f7a8b9
Revises: f2b3c4d5e6f7
Create Date: 2026-07-15 23:10:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "c4d5e6f7a8b9"
down_revision: Union[str, Sequence[str], None] = "f2b3c4d5e6f7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "eur_rate_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("eur_rate", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("eur_rate_source", sa.String(length=128), nullable=True),
        sa.Column("trigger", sa.String(length=32), nullable=False),
        sa.Column(
            "recorded_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_eur_rate_history_recorded_at",
        "eur_rate_history",
        ["recorded_at"],
        unique=False,
    )
    op.execute(
        """
        INSERT INTO eur_rate_history (eur_rate, eur_rate_source, trigger, recorded_at)
        SELECT eur_rate, COALESCE(eur_rate_source, 'manual'), 'baseline_seed',
               eur_rate_updated_at
        FROM pricing_settings
        WHERE eur_rate IS NOT NULL
        LIMIT 1
        """
    )


def downgrade() -> None:
    op.drop_index("ix_eur_rate_history_recorded_at", table_name="eur_rate_history")
    op.drop_table("eur_rate_history")
