import asyncio
import json
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
    payload = {
        "invalid_taxonomy": report.invalid_taxonomy,
        "unexpected_unmapped": report.unexpected_unmapped,
        "mapping_error": report.mapping_error,
        "mapped": report.mapped,
        "excluded": report.excluded,
        "integrity_failures": report.integrity_failures,
        "blocks_activation": report.blocks_activation,
    }
    if "--json" in sys.argv:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        for key, value in payload.items():
            print(f"{key}={value}")


if __name__ == "__main__":
    asyncio.run(main())
