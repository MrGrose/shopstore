import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.utils.images import (  # noqa: E402
    MEDIA_ROOT,
    collect_referenced_media_filenames,
    find_orphan_media_files,
)

MEDIA_QUERY = text(
    """
    SELECT image_url FROM products WHERE image_url LIKE '/media/products/%'
    UNION
    SELECT url FROM product_images WHERE url LIKE '/media/products/%'
    """
)


def prune_orphan_media(*, dry_run: bool = False) -> tuple[int, int]:
    db_url = os.environ.get("ALEMBIC_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: set ALEMBIC_DATABASE_URL or DATABASE_URL", file=sys.stderr)
        raise SystemExit(1)
    if db_url.startswith("postgresql+asyncpg://"):
        db_url = db_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://", 1)

    engine = create_engine(db_url)
    with engine.connect() as conn:
        rows = conn.execute(MEDIA_QUERY).fetchall()

    referenced = collect_referenced_media_filenames(url for (url,) in rows)
    orphans = find_orphan_media_files(referenced)
    bytes_total = sum(path.stat().st_size for path in orphans)

    print(f"DB URLs: {len(rows)}")
    print(f"Referenced filenames: {len(referenced)}")
    print(f"Media dir: {MEDIA_ROOT}")
    print(f"Orphans: {len(orphans)} files ({bytes_total / 1024**3:.2f} GB)")

    if dry_run:
        print("Dry run — nothing deleted.")
        return len(orphans), bytes_total

    for path in orphans:
        path.unlink()
    print("Deleted orphan files.")
    return len(orphans), bytes_total


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="only report orphans, do not delete",
    )
    args = parser.parse_args()
    prune_orphan_media(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
