import asyncio
import sys

from src.repositories.session import async_session_maker
from src.services.catalog.display.constants import RELEASE_STATUS_BACKFILLED
from src.services.catalog.display.placement_service import StorefrontPlacementService


async def main() -> None:
    release_id = None
    product_ids: list[int] = []
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--release-id" and i + 1 < len(args):
            release_id = int(args[i + 1])
        if arg == "--product-ids" and i + 1 < len(args):
            product_ids = [int(x) for x in args[i + 1].split(",") if x.strip()]

    if release_id is None:
        raise SystemExit("--release-id required")

    async with async_session_maker() as session:
        svc = StorefrontPlacementService(session)
        if product_ids:
            count = await svc.recompute_batch(release_id, product_ids)
        else:
            count = await svc.backfill_release(release_id)
        release = await svc.repo.get_release(release_id)
        if release is not None and release.status == "draft":
            release.status = RELEASE_STATUS_BACKFILLED
            await session.flush()
        await session.commit()
    print(f"release_id={release_id} recomputed={count}")


if __name__ == "__main__":
    asyncio.run(main())
