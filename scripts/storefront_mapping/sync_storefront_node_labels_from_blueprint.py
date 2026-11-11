import asyncio
import sys

from src.repositories.session import async_session_maker
from src.repositories.storefront_mapping import StorefrontMappingRepository
from src.services.catalog.display.constants import NODE_TYPE_CHIP, NODE_TYPE_SECTION
from src.services.catalog.display.ux_blueprint import load_storefront_ux_blueprint


def _blueprint_node_keys(
    nodes: list[dict],
) -> dict[tuple[str, str, str, str | None], str]:
    by_key = {str(n["display_key"]): n for n in nodes}
    out: dict[tuple[str, str, str, str | None], str] = {}
    for node in nodes:
        sport = str(node["sport_type"])
        node_type = str(node["node_type"])
        slug = str(node["slug"])
        section_slug: str | None = None
        if node_type == NODE_TYPE_CHIP:
            parent_key = str(node.get("parent_display_key") or "")
            parent = by_key.get(parent_key)
            if parent is not None:
                section_slug = str(parent["slug"])
        out[(sport, node_type, slug, section_slug)] = str(node["label_ru"]).strip()
    return out


async def main() -> None:
    release_id = None
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--release-id" and i + 1 < len(args):
            release_id = int(args[i + 1])
    if release_id is None:
        raise SystemExit("--release-id required")

    blueprint = load_storefront_ux_blueprint()
    labels_by_display_key = {
        str(n["display_key"]): str(n["label_ru"]).strip() for n in blueprint["nodes"]
    }
    labels_by_structural_key = _blueprint_node_keys(blueprint["nodes"])

    updated = 0
    async with async_session_maker() as session:
        repo = StorefrontMappingRepository(session)
        nodes = await repo.load_taxonomy_nodes(release_id)
        by_id = {n.id: n for n in nodes}
        for node in nodes:
            new_label = labels_by_display_key.get(node.display_key)
            if new_label is None:
                section_slug = None
                if node.node_type == NODE_TYPE_CHIP and node.parent_id:
                    parent = by_id.get(node.parent_id)
                    if parent and parent.node_type == NODE_TYPE_SECTION:
                        section_slug = parent.slug
                new_label = labels_by_structural_key.get(
                    (node.sport_type, node.node_type, node.slug, section_slug)
                )
            if not new_label or node.label_ru == new_label:
                continue
            node.label_ru = new_label
            updated += 1
        await session.commit()
    print(f"release_id={release_id} labels_updated={updated}")


if __name__ == "__main__":
    asyncio.run(main())
