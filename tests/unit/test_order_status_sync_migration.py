import importlib.util
from pathlib import Path

from sqlalchemy.dialects import postgresql

MIGRATION_FILENAME = "z6a7b8c9d0e1_sync_order_status_with_availability.py"


def _load_migration_module(filename: str) -> object:
    migration_path = Path(__file__).resolve().parents[2] / "alembic/versions" / filename
    spec = importlib.util.spec_from_file_location("migration_mod", migration_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Не удалось загрузить {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_sync_migration_revision_chain() -> None:
    migration = _load_migration_module(MIGRATION_FILENAME)
    assert migration.revision == "z6a7b8c9d0e1"
    assert migration.down_revision == "y5z6a7b8c9d0"


def test_sync_migration_statement_matches_documented_rule() -> None:
    migration = _load_migration_module(MIGRATION_FILENAME)
    statement = migration.build_status_sync_statement()
    compiled = statement.compile(
        dialect=postgresql.dialect(),
        compile_kwargs={"literal_binds": True},
    )
    normalized = " ".join(str(compiled).split())
    assert "SET status='created'" in normalized
    assert "orders.status = 'processing'" in normalized
    assert (
        "orders.availability_confirmation_status IN ('not_required', 'confirmed')"
        in normalized
    )
    assert "pending" not in normalized
    assert "unavailable" not in normalized
