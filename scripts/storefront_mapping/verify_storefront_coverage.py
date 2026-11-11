import asyncio
import sys

from src.repositories.session import async_session_maker
from src.services.catalog.display.reconciler import StorefrontMappingReconciler


async def main() -> None:
    release_id = None
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--release-id" and i + 1 < len(args):
            release_id = int(args[i + 1])
    if release_id is None:
        raise SystemExit("--release-id required")

    async with async_session_maker() as session:
        report = await StorefrontMappingReconciler(session).run(release_id)
    if report.blocks_activation:
        print("FAIL", report)
        raise SystemExit(1)
    print("OK", report)


if __name__ == "__main__":
    asyncio.run(main())
