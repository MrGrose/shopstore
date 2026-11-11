from sqlalchemy.ext.asyncio import AsyncSession

from src.models.storefront_mapping import StorefrontMappingRule, StorefrontNode
from src.repositories.storefront_mapping import StorefrontMappingRepository
from src.services.catalog.display.constants import (
    NODE_TYPE_CHIP,
    NODE_TYPE_ROOT,
    NODE_TYPE_SECTION,
)
from src.services.catalog.display.release_service import StorefrontReleaseService
from src.services.catalog.display.ux_blueprint import (
    StorefrontUxBlueprintError,
    load_storefront_ux_blueprint,
)


def _merge_legacy_metadata(
    node: StorefrontNode,
    legacy_keys: list[str],
) -> bool:
    if not legacy_keys:
        return False
    meta = dict(node.metadata_json or {})
    existing = list(meta.get("legacy_query_keys") or [])
    merged = sorted(set(existing) | set(legacy_keys))
    if merged == existing:
        return False
    meta["legacy_query_keys"] = merged
    node.metadata_json = meta
    return True


class StorefrontGreenfieldSeeder:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = StorefrontMappingRepository(session)
        self.releases = StorefrontReleaseService(session)

    # Создаёт draft release если не передан release_id.
    async def ensure_draft_release(self, release_id: int | None) -> int:
        if release_id is not None:
            release = await self.repo.get_release(release_id)
            if release is None:
                raise ValueError(f"Release {release_id} not found")
            self.releases.assert_editable(release)
            return release_id
        draft = await self.repo.create_draft_release(comment="greenfield seed")
        return draft.id

    # Строит UX nodes и supplier mapping rules из curated blueprint.
    async def seed_release(self, release_id: int) -> dict[str, int]:
        try:
            blueprint = load_storefront_ux_blueprint()
        except StorefrontUxBlueprintError as exc:
            raise ValueError(str(exc)) from exc
        node_index = {
            n.display_key: n for n in await self.repo.load_taxonomy_nodes(release_id)
        }
        nodes_created = await self._seed_blueprint_nodes(
            release_id,
            blueprint["nodes"],
            node_index,
        )
        existing_rules = await self.repo.load_rule_rows(release_id)
        rule_keys = {
            (
                row.sport_type,
                row.category_l1,
                row.category_l2,
                row.category_l3,
                row.match_mode,
                row.outcome,
                row.storefront_node_id,
            )
            for row in existing_rules
        }
        rules_created = await self._seed_blueprint_rules(
            release_id,
            blueprint["rules"],
            node_index,
            rule_keys,
        )
        return {"nodes_created": nodes_created, "rules_created": rules_created}

    # Создаёт root → section → chip в topological order с release-scoped parent lookup.
    async def _seed_blueprint_nodes(
        self,
        release_id: int,
        node_defs: list[dict],
        node_index: dict[str, StorefrontNode],
    ) -> int:
        roots = sorted(
            (d for d in node_defs if d["node_type"] == NODE_TYPE_ROOT),
            key=lambda d: int(d["sort_order"]),
        )
        sections = sorted(
            (d for d in node_defs if d["node_type"] == NODE_TYPE_SECTION),
            key=lambda d: int(d["sort_order"]),
        )
        chips = sorted(
            (d for d in node_defs if d["node_type"] == NODE_TYPE_CHIP),
            key=lambda d: int(d["sort_order"]),
        )
        expected = len(roots) + len(sections) + len(chips)
        if expected != len(node_defs):
            raise ValueError(
                f"UX blueprint contains unknown node_type entries: "
                f"{len(node_defs) - expected} invalid"
            )

        created = 0
        created += await self._seed_root_nodes(release_id, roots, node_index)
        await self.session.flush()
        created += await self._seed_section_nodes(release_id, sections, node_index)
        await self.session.flush()
        created += await self._seed_chip_nodes(release_id, chips, node_index)
        await self.session.flush()
        return created

    async def _seed_root_nodes(
        self,
        release_id: int,
        node_defs: list[dict],
        node_index: dict[str, StorefrontNode],
    ) -> int:
        created = 0
        for defn in node_defs:
            created += await self._insert_blueprint_node(
                release_id,
                defn,
                node_index,
                expected_type=NODE_TYPE_ROOT,
                parent_id=None,
            )
        return created

    async def _seed_section_nodes(
        self,
        release_id: int,
        node_defs: list[dict],
        node_index: dict[str, StorefrontNode],
    ) -> int:
        created = 0
        for defn in node_defs:
            parent_key = defn.get("parent_display_key")
            if not parent_key:
                raise ValueError(
                    f"section {defn['display_key']!r} requires parent_display_key"
                )
            parent = await self._resolve_release_parent(
                release_id, str(parent_key), node_index
            )
            if parent.node_type != NODE_TYPE_ROOT:
                raise ValueError(
                    f"section {defn['display_key']!r}: parent "
                    f"{parent_key!r} must be root, got {parent.node_type}"
                )
            if parent.sport_type != str(defn["sport_type"]):
                raise ValueError(
                    f"section {defn['display_key']!r}: sport_type mismatch with parent"
                )
            created += await self._insert_blueprint_node(
                release_id,
                defn,
                node_index,
                expected_type=NODE_TYPE_SECTION,
                parent_id=parent.id,
            )
        return created

    async def _seed_chip_nodes(
        self,
        release_id: int,
        node_defs: list[dict],
        node_index: dict[str, StorefrontNode],
    ) -> int:
        created = 0
        for defn in node_defs:
            parent_key = defn.get("parent_display_key")
            if not parent_key:
                raise ValueError(
                    f"chip {defn['display_key']!r} requires parent_display_key"
                )
            parent = await self._resolve_release_parent(
                release_id, str(parent_key), node_index
            )
            if parent.node_type != NODE_TYPE_SECTION:
                raise ValueError(
                    f"chip {defn['display_key']!r}: parent "
                    f"{parent_key!r} must be section, got {parent.node_type}"
                )
            if parent.sport_type != str(defn["sport_type"]):
                raise ValueError(
                    f"chip {defn['display_key']!r}: sport_type mismatch with parent"
                )
            created += await self._insert_blueprint_node(
                release_id,
                defn,
                node_index,
                expected_type=NODE_TYPE_CHIP,
                parent_id=parent.id,
            )
        return created

    # Parent lookup только внутри release (display_key), с refresh из DB.
    async def _resolve_release_parent(
        self,
        release_id: int,
        parent_display_key: str,
        node_index: dict[str, StorefrontNode],
    ) -> StorefrontNode:
        cached = node_index.get(parent_display_key)
        if cached is not None and cached.release_id == release_id:
            return cached
        parent = await self.repo.find_node_by_display_key(
            release_id, parent_display_key
        )
        if parent is None:
            raise ValueError(
                f"parent {parent_display_key!r} not found in release {release_id}"
            )
        node_index[parent_display_key] = parent
        return parent

    async def _insert_blueprint_node(
        self,
        release_id: int,
        defn: dict,
        node_index: dict[str, StorefrontNode],
        expected_type: str,
        parent_id: int | None,
    ) -> int:
        display_key = str(defn["display_key"])
        node_type = str(defn["node_type"])
        if node_type != expected_type:
            raise ValueError(
                f"node {display_key!r}: expected type {expected_type}, got {node_type}"
            )

        label_ru = str(defn.get("label_ru") or "").strip()
        if not label_ru:
            raise ValueError(f"node {display_key!r}: label_ru is required in blueprint")

        existing = node_index.get(display_key)
        if existing is not None:
            if existing.release_id != release_id:
                raise ValueError(
                    f"node {display_key!r} exists in another release "
                    f"{existing.release_id}"
                )
            if existing.node_type != expected_type:
                raise ValueError(
                    f"node {display_key!r}: existing type {existing.node_type} "
                    f"!= blueprint {expected_type}"
                )
            changed = False
            if existing.label_ru != label_ru:
                existing.label_ru = label_ru
                changed = True
            legacy = (defn.get("metadata_json") or {}).get("legacy_query_keys") or []
            if legacy and _merge_legacy_metadata(existing, list(legacy)):
                changed = True
            if changed:
                await self.session.flush()
            return 0

        node = StorefrontNode(
            release_id=release_id,
            display_key=display_key,
            sport_type=str(defn["sport_type"]),
            parent_id=parent_id,
            node_type=node_type,
            slug=str(defn["slug"]),
            label_ru=label_ru,
            sort_order=int(defn["sort_order"]),
            active=True,
            metadata_json=defn.get("metadata_json"),
        )
        self.session.add(node)
        await self.session.flush()
        node_index[display_key] = node
        return 1

    # Создаёт supplier→chip rules из blueprint (только после полного seed nodes).
    async def _seed_blueprint_rules(
        self,
        release_id: int,
        rule_defs: list[dict],
        node_index: dict[str, StorefrontNode],
        rule_keys: set[tuple],
    ) -> int:
        created = 0
        for defn in rule_defs:
            chip_key = defn.get("chip_display_key")
            node_id = None
            if chip_key:
                chip = node_index.get(str(chip_key))
                if chip is None or chip.release_id != release_id:
                    chip = await self.repo.find_node_by_display_key(
                        release_id, str(chip_key)
                    )
                if chip is None or chip.node_type != NODE_TYPE_CHIP:
                    raise ValueError(
                        f"UX blueprint rule chip_display_key={chip_key!r} "
                        f"not seeded in release {release_id}"
                    )
                node_id = chip.id
            key = (
                str(defn["sport_type"]),
                defn.get("category_l1"),
                defn.get("category_l2"),
                defn.get("category_l3"),
                str(defn["match_mode"]),
                str(defn["outcome"]),
                node_id,
            )
            if key in rule_keys:
                continue
            self.session.add(
                StorefrontMappingRule(
                    release_id=release_id,
                    storefront_node_id=node_id,
                    sport_type=str(defn["sport_type"]),
                    category_l1=defn.get("category_l1"),
                    category_l2=defn.get("category_l2"),
                    category_l3=defn.get("category_l3"),
                    match_mode=str(defn["match_mode"]),
                    priority=int(defn.get("priority") or 25),
                    active=True,
                    outcome=str(defn["outcome"]),
                    comment=defn.get("comment"),
                )
            )
            rule_keys.add(key)
            created += 1
        return created


class StorefrontMappingSeeder(StorefrontGreenfieldSeeder):
    # Совместимость CLI: seed UX nodes + supplier rules из blueprint.
    async def seed_nodes(self, release_id: int) -> int:
        result = await self.seed_release(release_id)
        return result["nodes_created"]

    async def seed_rules(self, release_id: int) -> int:
        result = await self.seed_release(release_id)
        return result["rules_created"]

    async def seed_all(self, release_id: int) -> dict[str, int]:
        return await self.seed_release(release_id)
