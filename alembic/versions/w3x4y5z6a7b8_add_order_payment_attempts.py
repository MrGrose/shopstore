"""add order payment attempts

Revision ID: w3x4y5z6a7b8
Revises: v2w3x4y5z6a7
Create Date: 2026-07-01 12:00:00.000000

"""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op
from src.utils.datetime_fmt import utc_now_naive

revision: str = "w3x4y5z6a7b8"
down_revision: Union[str, Sequence[str], None] = "v2w3x4y5z6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

MERCHANT_PREFIX = "shopstore-"
QR_TTL = timedelta(minutes=15)
TERMINAL_STATUSES = ("IPS_ACCEPTED", "DECLINED")


def _amount_minor_from_total(total_amount: object) -> int:
    return int((Decimal(str(total_amount)) * Decimal("100")).to_integral_value())


def _parse_meta_datetime(meta: dict, *keys: str) -> datetime | None:
    for key in keys:
        raw = meta.get(key)
        if not raw:
            continue
        try:
            return datetime.fromisoformat(str(raw))
        except ValueError:
            continue
    return None


def _backfill_payment_attempts(connection: sa.Connection) -> None:
    rows = connection.execute(
        sa.text(
            """
            SELECT id, payment_order_id, payment_external_order_id, payment_status,
                   payment_paid_at, payment_last_callback_at, payment_meta_json,
                   total_amount
            FROM orders
            WHERE payment_order_id IS NOT NULL
              AND NOT EXISTS (
                SELECT 1 FROM order_payment_attempts a
                WHERE a.order_id = orders.id
              )
            """
        )
    ).fetchall()
    if not rows:
        return
    now = utc_now_naive()
    insert_stmt = sa.text(
        """
        INSERT INTO order_payment_attempts (
            order_id, attempt_number, provider, merchant_order_id,
            x_req_id_order, x_req_id_qr, payment_amount_minor, payment_currency,
            init_state, provider_order_id, provider_external_order_id, provider_status,
            qr_created_at, qr_expires_at, paid_at, last_callback_at,
            created_at, updated_at
        ) VALUES (
            :order_id, 1, 'sbp', :merchant_order_id,
            :x_req_id_order, :x_req_id_qr, :payment_amount_minor, 'RUB',
            :init_state, :provider_order_id, :provider_external_order_id,
            :provider_status,
            :qr_created_at, :qr_expires_at, :paid_at, :last_callback_at,
            :created_at, :updated_at
        )
        """
    )
    for row in rows:
        meta = row.payment_meta_json or {}
        if not isinstance(meta, dict):
            meta = {}
        merchant_order_id = str(
            meta.get("merchant_order_id") or f"{MERCHANT_PREFIX}{row.id}"
        )
        amount_minor = meta.get("payment_amount_minor")
        if amount_minor is None:
            amount_minor = _amount_minor_from_total(row.total_amount)
        x_req_id_order = str(meta.get("x_req_id") or f"shopstore-order-{row.id}")
        x_req_id_qr = f"shopstore-qrc-{row.id}"
        init_state = str(meta.get("init_state") or "ready")
        qr_created_at = _parse_meta_datetime(meta, "qr_created_at", "init_started_at")
        qr_expires_at = None
        if qr_created_at is not None:
            qr_expires_at = qr_created_at + QR_TTL
        elif row.payment_status and str(row.payment_status).upper() in {
            "QRCDATA_CREATED",
            "IN_PROCESS",
            "QRCDATA_IN_PROGRESS",
        }:
            qr_expires_at = now
        connection.execute(
            insert_stmt,
            {
                "order_id": row.id,
                "merchant_order_id": merchant_order_id,
                "x_req_id_order": x_req_id_order,
                "x_req_id_qr": x_req_id_qr,
                "payment_amount_minor": int(amount_minor),
                "init_state": init_state,
                "provider_order_id": str(row.payment_order_id),
                "provider_external_order_id": row.payment_external_order_id,
                "provider_status": row.payment_status,
                "qr_created_at": qr_created_at,
                "qr_expires_at": qr_expires_at,
                "paid_at": row.payment_paid_at,
                "last_callback_at": row.payment_last_callback_at,
                "created_at": now,
                "updated_at": now,
            },
        )


def upgrade() -> None:
    op.create_table(
        "order_payment_attempts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("order_id", sa.Integer(), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("merchant_order_id", sa.String(length=128), nullable=False),
        sa.Column("x_req_id_order", sa.String(length=128), nullable=False),
        sa.Column("x_req_id_qr", sa.String(length=128), nullable=False),
        sa.Column("payment_amount_minor", sa.Integer(), nullable=False),
        sa.Column("payment_currency", sa.String(length=8), nullable=False),
        sa.Column("init_state", sa.String(length=32), nullable=False),
        sa.Column("provider_order_id", sa.String(length=64), nullable=True),
        sa.Column("provider_external_order_id", sa.String(length=128), nullable=True),
        sa.Column("provider_status", sa.String(length=64), nullable=True),
        sa.Column("qr_created_at", sa.DateTime(), nullable=True),
        sa.Column("qr_expires_at", sa.DateTime(), nullable=True),
        sa.Column("paid_at", sa.DateTime(), nullable=True),
        sa.Column("last_callback_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True
        ),
        sa.Column(
            "updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True
        ),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "order_id", "attempt_number", name="uq_order_payment_attempt"
        ),
        sa.UniqueConstraint(
            "provider_order_id", name="uq_payment_attempt_provider_order"
        ),
        sa.UniqueConstraint(
            "merchant_order_id", name="uq_payment_attempt_merchant_order"
        ),
    )
    op.create_index(
        op.f("ix_order_payment_attempts_order_id"),
        "order_payment_attempts",
        ["order_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_order_payment_attempts_provider_order_id"),
        "order_payment_attempts",
        ["provider_order_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_order_payment_attempts_provider_status"),
        "order_payment_attempts",
        ["provider_status"],
        unique=False,
    )
    op.create_index(
        op.f("ix_order_payment_attempts_qr_expires_at"),
        "order_payment_attempts",
        ["qr_expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_order_payment_attempts_status_expiry",
        "order_payment_attempts",
        ["provider_status", "qr_expires_at"],
        unique=False,
    )
    op.create_index(
        "ix_order_payment_attempts_active_qr",
        "order_payment_attempts",
        ["provider_status", "qr_expires_at"],
        unique=False,
        postgresql_where=sa.text(
            "qr_expires_at IS NOT NULL AND provider_status NOT IN "
            "('IPS_ACCEPTED', 'DECLINED')"
        ),
    )
    connection = op.get_bind()
    _backfill_payment_attempts(connection)


def downgrade() -> None:
    op.drop_index(
        "ix_order_payment_attempts_active_qr", table_name="order_payment_attempts"
    )
    op.drop_index(
        "ix_order_payment_attempts_status_expiry", table_name="order_payment_attempts"
    )
    op.drop_index(
        op.f("ix_order_payment_attempts_qr_expires_at"),
        table_name="order_payment_attempts",
    )
    op.drop_index(
        op.f("ix_order_payment_attempts_provider_status"),
        table_name="order_payment_attempts",
    )
    op.drop_index(
        op.f("ix_order_payment_attempts_provider_order_id"),
        table_name="order_payment_attempts",
    )
    op.drop_index(
        op.f("ix_order_payment_attempts_order_id"), table_name="order_payment_attempts"
    )
    op.drop_table("order_payment_attempts")
