import asyncio
import json
import sys

from src.repositories.session import async_session_maker
from src.repositories.storefront_mapping import StorefrontMappingRepository
from src.services.catalog.display.constants import NODE_TYPE_ROOT
from src.services.catalog.read.scope import CATALOG_ALL_TOP_CATEGORY, CATALOG_TOP_ORDER
from src.services.catalog.read.service import CatalogService


async def main() -> None:
    release_id = None
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--release-id" and i + 1 < len(args):
            release_id = int(args[i + 1])
    if release_id is None:
        raise SystemExit("--release-id required")

    mismatches: list[dict[str, object]] = []
    async with async_session_maker() as session:
        repo = StorefrontMappingRepository(session)
        read_svc = CatalogService(session)
        availability = read_svc.product_crud._catalog_base_filters()
        nodes = await repo.load_taxonomy_nodes(release_id)
        roots = [n for n in nodes if n.node_type == NODE_TYPE_ROOT]

        repo_global = await repo.count_distinct_products_global(
            release_id,
            availability,
        )
        api_global = await read_svc.get_catalog_product_count(
            top_category=CATALOG_ALL_TOP_CATEGORY,
            mapping_release_id=release_id,
            chip_node_ids=None,
        )
        if repo_global != api_global:
            mismatches.append(
                {
                    "scope": CATALOG_ALL_TOP_CATEGORY,
                    "repo_count": repo_global,
                    "api_count": api_global,
                }
            )

        for sport in CATALOG_TOP_ORDER:
            root = next((n for n in roots if n.sport_type == sport), None)
            if root is None:
                continue
            chip_ids = tuple(await repo.descendant_chip_ids(release_id, sport))
            repo_count = await repo.count_distinct_products_for_chips(
                release_id,
                list(chip_ids),
                availability,
            )
            api_count = await read_svc.get_catalog_product_count(
                top_category=sport,
                mapping_release_id=release_id,
                chip_node_ids=chip_ids,
            )
            if repo_count != api_count:
                mismatches.append(
                    {
                        "sport": sport,
                        "repo_count": repo_count,
                        "api_count": api_count,
                    }
                )

    payload = {
        "release_id": release_id,
        "scopes_checked": len(CATALOG_TOP_ORDER) + 1,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
        "ok": len(mismatches) == 0,
    }
    if "--json" in sys.argv:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print(f"ok={payload['ok']} mismatches={payload['mismatch_count']}")
        for row in mismatches:
            print(row)
    if not payload["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
