"""add auth_identities and user avatar/updated_at

Revision ID: l3m4n5o6p7q8
Revises: k2l3m4n5o6p7
Create Date: 2026-06-11 20:00:00.000000

"""

import json
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy import text

from alembic import op

revision: str = "l3m4n5o6p7q8"
down_revision: Union[str, Sequence[str], None] = "k2l3m4n5o6p7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("avatar", sa.String(length=2048), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=True,
            server_default=sa.text("now()"),
        ),
    )

    op.create_table(
        "auth_identities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_user_id", sa.String(length=255), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("meta_json", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("now()"),
            nullable=True,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "provider",
            "provider_user_id",
            name="uq_auth_identity_provider_user",
        ),
    )
    op.create_index(
        op.f("ix_auth_identities_user_id"),
        "auth_identities",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_auth_identities_email"),
        "auth_identities",
        ["email"],
        unique=False,
    )

    conn = op.get_bind()

    tg_rows = conn.execute(
        text(
            """
            SELECT id, telegram_id, telegram_username
            FROM users
            WHERE telegram_id IS NOT NULL
            """
        )
    ).fetchall()
    for row in tg_rows:
        user_id, telegram_id, username = row
        meta = {"username": username} if username else None
        conn.execute(
            text(
                """
                INSERT INTO auth_identities
                    (user_id, provider, provider_user_id, email, meta_json)
                VALUES
                    (
                        :user_id,
                        'telegram',
                        :provider_user_id,
                        NULL,
                        CAST(:meta_json AS JSON)
                    )
                ON CONFLICT (provider, provider_user_id) DO NOTHING
                """
            ),
            {
                "user_id": user_id,
                "provider_user_id": str(telegram_id),
                "meta_json": json.dumps(meta) if meta else None,
            },
        )

    email_rows = conn.execute(
        text(
            """
            SELECT id, email
            FROM users
            WHERE email IS NOT NULL AND trim(email) <> ''
            """
        )
    ).fetchall()
    for row in email_rows:
        user_id, email = row
        normalized = email.strip().lower()
        conn.execute(
            text(
                """
                INSERT INTO auth_identities
                    (user_id, provider, provider_user_id, email, meta_json)
                VALUES
                    (:user_id, 'email', :provider_user_id, :email, NULL)
                ON CONFLICT (provider, provider_user_id) DO NOTHING
                """
            ),
            {
                "user_id": user_id,
                "provider_user_id": str(uuid.uuid4()),
                "email": normalized,
            },
        )


def downgrade() -> None:
    op.drop_index(op.f("ix_auth_identities_email"), table_name="auth_identities")
    op.drop_index(op.f("ix_auth_identities_user_id"), table_name="auth_identities")
    op.drop_table("auth_identities")
    op.drop_column("users", "updated_at")
    op.drop_column("users", "avatar")
