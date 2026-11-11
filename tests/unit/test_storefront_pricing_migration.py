import importlib.util
from decimal import Decimal
from pathlib import Path

from src.models.pricing import PricingRecalculationJob

MIGRATION_FILENAME = "a0b1c2d3e4f5_add_storefront_pricing_rules.py"


# Загружает модуль миграции напрямую из alembic/versions.
def _load_migration_module() -> object:
    migration_path = (
        Path(__file__).resolve().parents[2] / "alembic/versions" / MIGRATION_FILENAME
    )
    spec = importlib.util.spec_from_file_location(
        "storefront_pricing_migration", migration_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Не удалось загрузить {MIGRATION_FILENAME}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Проверяет полный seed новых exact и fallback правил.
def test_storefront_pricing_migration_seed_matches_registry() -> None:
    migration = _load_migration_module()
    rows = migration.initial_margin_rule_rows()

    assert len(rows) == 19
    assert len({(row["sport_type"], row["subcategory_slug"]) for row in rows}) == 19
    assert {row["margin_percent"] for row in rows} == {Decimal("30.00")}
    assert {
        (row["sport_type"], row["subcategory_slug"])
        for row in rows
        if row["subcategory_slug"] == "__fallback__"
    } == {
        ("Padel", "__fallback__"),
        ("Tennis", "__fallback__"),
        ("Running", "__fallback__"),
    }


# DB job хранит причину ошибки постановки в Redis.
def test_pricing_job_has_enqueue_error_message_column() -> None:
    assert "error_message" in PricingRecalculationJob.__table__.columns
