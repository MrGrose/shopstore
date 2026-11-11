import asyncio
import sys

from src.repositories.session import async_session_maker
from src.services.catalog.display.release_service import StorefrontReleaseService


async def main() -> None:
    release_id = None
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--release-id" and i + 1 < len(args):
            release_id = int(args[i + 1])
    if release_id is None:
        raise SystemExit("--release-id required")

    async with async_session_maker() as session:
        release = await StorefrontReleaseService(session).activate_release(release_id)
        await session.commit()
    print(f"activated release_id={release.id}")


if __name__ == "__main__":
    asyncio.run(main())
