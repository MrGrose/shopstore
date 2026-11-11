import importlib.util
from pathlib import Path

import sqlalchemy as sa

MIGRATION_FILENAME = "i8b2c3d4e5f6_add_product_image_source_url.py"


# Загружает модуль миграции без пакета alembic.versions.
def _load_migration_module():
    migration_path = (
        Path(__file__).resolve().parents[2] / "alembic/versions" / MIGRATION_FILENAME
    )
    spec = importlib.util.spec_from_file_location(
        "product_image_source_migration", migration_path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Не удалось загрузить {MIGRATION_FILENAME}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# HTTP gallery URL уезжает в source_url, managed url становится NULL.
def test_backfill_moves_http_url_to_source() -> None:
    module = _load_migration_module()
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(
            sa.text(
                "CREATE TABLE product_images ("
                "url VARCHAR(512), source_url VARCHAR(512))"
            )
        )
        conn.execute(
            sa.text(
                "INSERT INTO product_images (url, source_url) VALUES "
                "('/media/products/a.jpg', NULL), "
                "('https://cdn.shopify.com/s/files/1/p.jpg', NULL)"
            )
        )
        assert module.backfill_source_urls(conn) == 1
        assert module.clear_http_managed_urls(conn) == 1
        rows = list(
            conn.execute(
                sa.text(
                    "SELECT url, source_url FROM product_images ORDER BY url IS NULL"
                )
            )
        )
        assert ("/media/products/a.jpg", None) in rows
        assert (None, "https://cdn.shopify.com/s/files/1/p.jpg") in rows
        assert module.restore_http_urls_from_source(conn) == 1
