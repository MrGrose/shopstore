import asyncio
import sys

from src.repositories.session import async_session_maker
from src.services.catalog.display.release_service import StorefrontReleaseService


async def main() -> None:
    archived_id = None
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--from-archived-id" and i + 1 < len(args):
            archived_id = int(args[i + 1])
    if archived_id is None:
        raise SystemExit("--from-archived-id required")

    async with async_session_maker() as session:
        release = await StorefrontReleaseService(session).rollback_from_archived(
            archived_id
        )
        await session.commit()
    print(f"rollback activated release_id={release.id}")


if __name__ == "__main__":
    asyncio.run(main())
