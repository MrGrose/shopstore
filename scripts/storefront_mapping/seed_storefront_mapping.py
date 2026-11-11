import asyncio
import sys

from src.repositories.session import async_session_maker
from src.services.catalog.display.seed import StorefrontMappingSeeder


async def _parse_release_id(argv: list[str]) -> int | None:
    release_id = None
    for i, arg in enumerate(argv):
        if arg == "--release-id" and i + 1 < len(argv):
            release_id = int(argv[i + 1])
    return release_id


async def main() -> None:
    release_id = await _parse_release_id(sys.argv[1:])
    async with async_session_maker() as session:
        seeder = StorefrontMappingSeeder(session)
        rid = await seeder.ensure_draft_release(release_id)
        result = await seeder.seed_release(rid)
        await session.commit()
    print(
        f"release_id={rid} nodes_created={result['nodes_created']} "
        f"rules_created={result['rules_created']}"
    )


if __name__ == "__main__":
    asyncio.run(main())
