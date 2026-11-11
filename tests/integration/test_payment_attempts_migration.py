import importlib.util
import uuid
from decimal import Decimal
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy import create_engine

from src.core.config import settings

pytestmark = pytest.mark.integration


def _load_backfill() -> object:
    migration_path = (
        Path(__file__).resolve().parents[2]
        / "alembic/versions/w3x4y5z6a7b8_add_order_payment_attempts.py"
    )
    spec = importlib.util.spec_from_file_location(
        "payment_attempts_migration", migration_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Не удалось загрузить migration-модуль")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module._backfill_payment_attempts


def _sync_database_url() -> str:
    url = settings.database_url
    return url.replace("+asyncpg", "")


# Backfill переносит legacy payment_external_order_id в attempt.
def test_backfill_copies_payment_external_order_id() -> None:
    engine = create_engine(_sync_database_url())
    external_id = "legacy-ext-order-991"
    with engine.connect() as connection:
        trans = connection.begin()
        try:
            connection.execute(
                sa.text(
                    """
                    ALTER TABLE order_payment_attempts
                    ADD COLUMN IF NOT EXISTS provider_external_order_id VARCHAR(128)
                    """
                )
            )
            provider_id = f"legacy-prov-mig-{uuid.uuid4().hex[:10]}"
            order_id = connection.execute(
                sa.text(
                    """
                    INSERT INTO orders (
                        user_id, status, total_amount, items_subtotal_amount,
                        discount_items_amount, delivery_fee_eur_snapshot,
                        delivery_fee_amount, eur_rate_snapshot,
                        payment_provider, payment_order_id, payment_external_order_id,
                        payment_status
                    )
                    SELECT
                        u.id, 'processing', 1500.00, 1000.00,
                        0, 0, 500.00, 100.00,
                        'sbp', :provider_id, :external_id, 'QRCDATA_CREATED'
                    FROM users u
                    ORDER BY u.id
                    LIMIT 1
                    RETURNING id
                    """
                ),
                {"external_id": external_id, "provider_id": provider_id},
            ).scalar_one()
            connection.execute(
                sa.text(
                    "DELETE FROM order_payment_attempts WHERE order_id = :order_id"
                ),
                {"order_id": order_id},
            )
            _backfill_payment_attempts = _load_backfill()
            _backfill_payment_attempts(connection)
            row = connection.execute(
                sa.text(
                    """
                    SELECT provider_external_order_id, provider_order_id,
                           merchant_order_id, payment_amount_minor
                    FROM order_payment_attempts
                    WHERE order_id = :order_id
                    """
                ),
                {"order_id": order_id},
            ).one()
            assert row.provider_external_order_id == external_id
            assert row.provider_order_id == provider_id
            assert row.merchant_order_id == f"shopstore-{order_id}"
            assert int(row.payment_amount_minor) == int(
                (Decimal("1500.00") * Decimal("100")).to_integral_value()
            )
        finally:
            trans.rollback()
