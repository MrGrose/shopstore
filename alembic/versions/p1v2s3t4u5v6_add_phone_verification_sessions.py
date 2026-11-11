"""add phone_verification_sessions table

Revision ID: p1v2s3t4u5v6
Revises: x4y5z6a7b8c9
Create Date: 2026-08-06 17:00:00.000000

"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "p1v2s3t4u5v6"
down_revision: Union[str, Sequence[str], None] = "x4y5z6a7b8c9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "phone_verification_sessions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("session_key", sa.String(length=255), nullable=False),
        sa.Column("request_id", sa.String(length=128), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "session_key", name="uq_phone_verification_sessions_session_key"
        ),
    )
    op.create_index(
        "ix_phone_verification_sessions_expires_at",
        "phone_verification_sessions",
        ["expires_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_phone_verification_sessions_expires_at",
        table_name="phone_verification_sessions",
    )
    op.drop_table("phone_verification_sessions")
