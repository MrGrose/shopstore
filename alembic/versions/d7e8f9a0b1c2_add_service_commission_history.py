"""add service commission history

Revision ID: d7e8f9a0b1c2
Revises: c0d1e2f3a4b5
Create Date: 2026-07-06 12:30:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "d7e8f9a0b1c2"
down_revision: Union[str, Sequence[str], None] = "c0d1e2f3a4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "service_commission_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("effective_from", sa.Date(), nullable=False),
        sa.Column(
            "commission_percent", sa.Numeric(precision=5, scale=2), nullable=False
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "effective_from", name="uq_service_commission_effective_from"
        ),
    )
    op.create_index(
        "ix_service_commission_history_effective_from",
        "service_commission_history",
        ["effective_from"],
        unique=False,
    )
    op.execute(
        """
        INSERT INTO service_commission_history (effective_from, commission_percent)
        SELECT DATE '2020-01-01', service_commission_percent
        FROM pricing_settings
        LIMIT 1
        """
    )


def downgrade() -> None:
    op.drop_index(
        "ix_service_commission_history_effective_from",
        table_name="service_commission_history",
    )
    op.drop_table("service_commission_history")
