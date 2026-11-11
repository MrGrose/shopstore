import asyncio
import json
import sys
from pathlib import Path

from sqlalchemy import select

from src.models.storefront_mapping import StorefrontMappingRelease, StorefrontNode
from src.repositories.session import async_session_maker
from src.services.catalog.display.constants import (
    NODE_TYPE_CHIP,
    NODE_TYPE_ROOT,
    NODE_TYPE_SECTION,
)
from src.services.catalog.display.ux_blueprint import (
    SCHEMA_VERSION,
    compute_content_checksum,
    validate_storefront_ux_blueprint,
)

_REVIEW_BANNER = (
    "MANUAL REVIEW REQUIRED. Do not commit exported blueprint without UX review. "
    "Blueprint is version-controlled source of truth; seed never auto-regenerates it."
)


# Экспортирует candidate blueprint из archived/active release (только ручной workflow).
async def export_blueprint(
    release_id: int,
    output_path: Path | None,
) -> dict:
    async with async_session_maker() as session:
        release = await session.get(StorefrontMappingRelease, release_id)
        if release is None:
            raise SystemExit(f"Release {release_id} not found")
        nodes = list(
            (
                await session.execute(
                    select(StorefrontNode)
                    .where(StorefrontNode.release_id == release_id)
                    .order_by(StorefrontNode.id)
                )
            )
            .scalars()
            .all()
        )
        if not nodes:
            raise SystemExit(f"Release {release_id} has no nodes")

        by_id = {n.id: n for n in nodes}
        out_nodes: list[dict] = []
        key_map: dict[str, str] = {}
        for node in nodes:
            if node.node_type in (NODE_TYPE_ROOT, NODE_TYPE_SECTION):
                new_key = node.display_key
            elif node.node_type == NODE_TYPE_CHIP:
                parent = by_id[node.parent_id]
                new_key = f"{node.sport_type.lower()}.{parent.slug}.{node.slug}"
            else:
                new_key = node.display_key
            key_map[node.display_key] = new_key
            meta = dict(node.metadata_json or {})
            legacy = set(meta.get("legacy_query_keys") or [])
            if node.node_type == NODE_TYPE_CHIP and node.display_key != new_key:
                legacy.add(node.display_key)
            meta["legacy_query_keys"] = sorted(legacy) if legacy else None
            out_nodes.append(
                {
                    "sport_type": node.sport_type,
                    "node_type": node.node_type,
                    "display_key": new_key,
                    "parent_display_key": (
                        by_id[node.parent_id].display_key if node.parent_id else None
                    ),
                    "slug": node.slug,
                    "label_ru": node.label_ru,
                    "sort_order": node.sort_order,
                    "metadata_json": meta,
                }
            )

        from src.models.storefront_mapping import StorefrontMappingRule

        rules = list(
            (
                await session.execute(
                    select(StorefrontMappingRule).where(
                        StorefrontMappingRule.release_id == release_id
                    )
                )
            )
            .scalars()
            .all()
        )
        out_rules = []
        for rule in rules:
            chip_key = None
            if rule.storefront_node_id:
                old = by_id[rule.storefront_node_id]
                chip_key = key_map[old.display_key]
            out_rules.append(
                {
                    "sport_type": rule.sport_type,
                    "category_l1": rule.category_l1,
                    "category_l2": rule.category_l2,
                    "category_l3": rule.category_l3,
                    "match_mode": rule.match_mode,
                    "priority": rule.priority,
                    "outcome": rule.outcome,
                    "chip_display_key": chip_key,
                    "comment": rule.comment,
                }
            )

    payload = {
        "schema_version": SCHEMA_VERSION,
        "derived_from_release_id": release_id,
        "review_note": _REVIEW_BANNER,
        "nodes": out_nodes,
        "rules": out_rules,
    }
    payload["content_checksum"] = compute_content_checksum(out_nodes, out_rules)
    validate_storefront_ux_blueprint(payload)

    encoded = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if output_path is None:
        print(_REVIEW_BANNER, file=sys.stderr)
        print(encoded)
    else:
        output_path.write_text(encoded, encoding="utf-8")
        print(
            f"Wrote candidate blueprint to {output_path}. {_REVIEW_BANNER}",
            file=sys.stderr,
        )
    return payload


async def main() -> None:
    release_id = None
    output_path: Path | None = None
    args = sys.argv[1:]
    for i, arg in enumerate(args):
        if arg == "--release-id" and i + 1 < len(args):
            release_id = int(args[i + 1])
        if arg == "--out" and i + 1 < len(args):
            output_path = Path(args[i + 1])
    if release_id is None:
        raise SystemExit(
            "Usage: export_storefront_ux_blueprint.py --release-id ID [--out PATH]"
        )
    await export_blueprint(release_id, output_path)


if __name__ == "__main__":
    asyncio.run(main())
