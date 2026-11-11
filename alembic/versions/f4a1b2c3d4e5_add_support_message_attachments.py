"""add support_message_attachments and closed_at index

Revision ID: f4a1b2c3d4e5
Revises: i8b2c3d4e5f6
Create Date: 2026-09-07 12:10:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "f4a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "i8b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Добавляет вложения поддержки и индекс closed_at для retention.
def upgrade() -> None:
    op.create_table(
        "support_message_attachments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("message_id", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["support_messages.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "storage_key",
            name="uq_support_message_attachments_storage_key",
        ),
    )
    op.create_index(
        "ix_support_message_attachments_message_id",
        "support_message_attachments",
        ["message_id"],
    )
    op.create_index(
        "ix_support_tickets_closed_at",
        "support_tickets",
        ["closed_at"],
    )


# Удаляет вложения поддержки и индекс closed_at.
def downgrade() -> None:
    op.drop_index("ix_support_tickets_closed_at", table_name="support_tickets")
    op.drop_index(
        "ix_support_message_attachments_message_id",
        table_name="support_message_attachments",
    )
    op.drop_table("support_message_attachments")
