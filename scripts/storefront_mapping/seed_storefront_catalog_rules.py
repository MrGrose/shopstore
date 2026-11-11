import asyncio
import sys

from src.repositories.session import async_session_maker
from src.services.catalog.display.seed import StorefrontMappingSeeder


async def main() -> None:
    release_id = None
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--release-id" and i + 1 < len(args):
            release_id = int(args[i + 1])
    if release_id is None:
        raise SystemExit("--release-id required")

    async with async_session_maker() as session:
        seeder = StorefrontMappingSeeder(session)
        release = await seeder.repo.get_release(release_id)
        if release is None:
            raise SystemExit(f"Release {release_id} not found")
        seeder.releases.assert_editable(release)
        result = await seeder.seed_release(release_id)
        await session.commit()
    print(
        f"release_id={release_id} nodes_created={result['nodes_created']} "
        f"rules_created={result['rules_created']}"
    )


if __name__ == "__main__":
    asyncio.run(main())
