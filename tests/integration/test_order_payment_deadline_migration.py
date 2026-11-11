import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect

from alembic import command
from alembic.config import Config
from src.core.config import settings

pytestmark = pytest.mark.integration


def _sync_database_url() -> str:
    url = settings.database_url
    return url.replace("+asyncpg", "")


def _load_migration_module(filename: str) -> object:
    migration_path = Path(__file__).resolve().parents[2] / "alembic/versions" / filename
    spec = importlib.util.spec_from_file_location("migration_mod", migration_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Не удалось загрузить {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _order_columns() -> set[str]:
    engine = create_engine(_sync_database_url())
    with engine.connect() as connection:
        return {col["name"] for col in inspect(connection).get_columns("orders")}


def test_x4_migration_removed() -> None:
    x4 = (
        Path(__file__).resolve().parents[2]
        / "alembic/versions/x4y5z6a7b8c9_add_payment_attempt_external_order_id.py"
    )
    assert not x4.exists()


def test_deadline_migration_revision_chain() -> None:
    migration = _load_migration_module("y5z6a7b8c9d0_add_order_payment_deadline.py")
    assert migration.revision == "y5z6a7b8c9d0"
    assert migration.down_revision == "w3x4y5z6a7b8"


def test_order_payment_deadline_migration_up_down_up() -> None:
    cfg = Config(str(Path(__file__).resolve().parents[2] / "alembic.ini"))
    cfg.set_main_option("sqlalchemy.url", _sync_database_url())

    try:
        command.downgrade(cfg, "w3x4y5z6a7b8")
        cols = _order_columns()
        assert "payment_due_at" not in cols
        assert "cancellation_reason" not in cols

        command.upgrade(cfg, "y5z6a7b8c9d0")
        cols = _order_columns()
        assert "payment_due_at" in cols
        assert "cancellation_reason" in cols

        engine = create_engine(_sync_database_url())
        with engine.connect() as connection:
            indexes = {
                idx["name"]
                for idx in inspect(connection).get_indexes("orders")
                if idx.get("name")
            }
        assert "ix_orders_status_payment_due_at" in indexes

        command.downgrade(cfg, "w3x4y5z6a7b8")
        cols = _order_columns()
        assert "payment_due_at" not in cols
    finally:
        command.upgrade(cfg, "head")
