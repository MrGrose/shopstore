from sqlalchemy import and_, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.constants.storefront_mapping import (
    NODE_TYPE_CHIP,
    NODE_TYPE_SECTION,
    RELEASE_STATUS_ACTIVE,
    RELEASE_STATUS_ARCHIVED,
    RELEASE_STATUS_BACKFILLED,
    RELEASE_STATUS_DRAFT,
    RELEASE_STATUS_VERIFIED,
    RELEASE_STATUS_VERIFIED_DIRTY,
)
from src.models.product import Product
from src.models.storefront_mapping import (
    ProductStorefrontPlacement,
    ProductStorefrontResolution,
    StorefrontMappingRelease,
    StorefrontMappingRule,
    StorefrontNode,
)
from src.repositories.storefront_mapping.predicates import catalogized_sql_filters
from src.repositories.storefront_mapping.rule_row import MappingRuleRow
from src.utils.datetime_fmt import utc_now_naive


class StorefrontChipLookupAmbiguousError(Exception):
    def __init__(
        self,
        node_key: str,
        sport_type: str,
        match_count: int,
    ) -> None:
        self.node_key = node_key
        self.sport_type = sport_type
        self.match_count = match_count
        super().__init__(
            f"legacy node key {node_key!r} неоднозначен для {sport_type}: "
            f"найдено {match_count} chip nodes"
        )


# Собирает chip nodes, совпадающие с node_key (display_key, slug, legacy_query_keys).
def match_chip_nodes(
    nodes: list[StorefrontNode],
    node_key: str,
) -> list[StorefrontNode]:
    matches: list[StorefrontNode] = []
    for node in nodes:
        if node.display_key == node_key or node.slug == node_key:
            matches.append(node)
            continue
        legacy_keys = (node.metadata_json or {}).get("legacy_query_keys") or []
        if node_key in legacy_keys:
            matches.append(node)
    return matches


# Возвращает единственный match или raises при неоднозначности.
def resolve_chip_node_match(
    matches: list[StorefrontNode],
    node_key: str,
    sport_type: str,
    section_id: int | None,
) -> StorefrontNode | None:
    if not matches:
        return None
    if len(matches) > 1:
        raise StorefrontChipLookupAmbiguousError(node_key, sport_type, len(matches))
    if section_id is not None and matches[0].parent_id != section_id:
        return None
    return matches[0]


class StorefrontMappingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # Возвращает active release или None.
    async def get_active_release(self) -> StorefrontMappingRelease | None:
        result = await self.session.execute(
            select(StorefrontMappingRelease).where(
                StorefrontMappingRelease.status == RELEASE_STATUS_ACTIVE
            )
        )
        return result.scalar_one_or_none()

    # Загружает release по id.
    async def get_release(self, release_id: int) -> StorefrontMappingRelease | None:
        result = await self.session.execute(
            select(StorefrontMappingRelease).where(
                StorefrontMappingRelease.id == release_id
            )
        )
        return result.scalar_one_or_none()

    # Создаёт draft release.
    async def create_draft_release(
        self,
        comment: str | None = None,
        cloned_from_release_id: int | None = None,
    ) -> StorefrontMappingRelease:
        row = StorefrontMappingRelease(
            status=RELEASE_STATUS_DRAFT,
            comment=comment,
            cloned_from_release_id=cloned_from_release_id,
        )
        self.session.add(row)
        await self.session.flush()
        return row

    # Загружает active mapping rules release.
    async def load_rule_rows(self, release_id: int) -> tuple[MappingRuleRow, ...]:
        result = await self.session.execute(
            select(StorefrontMappingRule)
            .where(
                StorefrontMappingRule.release_id == release_id,
                StorefrontMappingRule.active.is_(True),
            )
            .order_by(StorefrontMappingRule.id)
        )
        rows = result.scalars().all()
        return tuple(
            MappingRuleRow(
                id=r.id,
                sport_type=r.sport_type,
                category_l1=r.category_l1,
                category_l2=r.category_l2,
                category_l3=r.category_l3,
                match_mode=r.match_mode,
                priority=r.priority,
                outcome=r.outcome,
                storefront_node_id=r.storefront_node_id,
            )
            for r in rows
        )

    # Возвращает catalogized product ids для release backfill.
    async def list_catalogized_product_ids(self) -> list[int]:
        filters = catalogized_sql_filters(Product)
        result = await self.session.execute(
            select(Product.id).where(*filters).order_by(Product.id)
        )
        return list(result.scalars().all())

    # Загружает product для recompute.
    async def get_product(self, product_id: int) -> Product | None:
        result = await self.session.execute(
            select(Product).where(Product.id == product_id)
        )
        return result.scalar_one_or_none()

    # Удаляет placements и resolution product в release.
    async def clear_product_materialization(
        self, release_id: int, product_id: int
    ) -> None:
        await self.session.execute(
            delete(ProductStorefrontPlacement).where(
                ProductStorefrontPlacement.release_id == release_id,
                ProductStorefrontPlacement.product_id == product_id,
            )
        )
        await self.session.execute(
            delete(ProductStorefrontResolution).where(
                ProductStorefrontResolution.release_id == release_id,
                ProductStorefrontResolution.product_id == product_id,
            )
        )

    # Записывает placements и resolution после resolver.
    async def write_materialization(
        self,
        release_id: int,
        product_id: int,
        status: str,
        reason: str | None,
        resolver_hash: str,
        placements: tuple[tuple[int, int], ...],
    ) -> None:
        await self.clear_product_materialization(release_id, product_id)
        if status == "mapped" and placements:
            for node_id, rule_id in placements:
                self.session.add(
                    ProductStorefrontPlacement(
                        release_id=release_id,
                        product_id=product_id,
                        storefront_node_id=node_id,
                        mapping_rule_id=rule_id,
                    )
                )
        if status in ("mapped", "unmapped", "excluded", "mapping_error"):
            self.session.add(
                ProductStorefrontResolution(
                    release_id=release_id,
                    product_id=product_id,
                    status=status,
                    reason=reason,
                    resolver_hash=resolver_hash,
                )
            )

    # Ищет node по display_key внутри release.
    async def find_node_by_display_key(
        self, release_id: int, display_key: str
    ) -> StorefrontNode | None:
        result = await self.session.execute(
            select(StorefrontNode).where(
                StorefrontNode.release_id == release_id,
                StorefrontNode.display_key == display_key,
                StorefrontNode.active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    # Ищет section node по slug в release.
    async def find_section_node(
        self, release_id: int, sport_type: str, section_slug: str
    ) -> StorefrontNode | None:
        result = await self.session.execute(
            select(StorefrontNode).where(
                StorefrontNode.release_id == release_id,
                StorefrontNode.sport_type == sport_type,
                StorefrontNode.node_type == NODE_TYPE_SECTION,
                StorefrontNode.slug == section_slug,
                StorefrontNode.active.is_(True),
            )
        )
        return result.scalar_one_or_none()

    # Ищет chip node по display_key, slug или legacy_query_keys (strict/ambiguous-safe).
    async def find_chip_node(
        self,
        release_id: int,
        sport_type: str,
        node_key: str,
        section_id: int | None = None,
    ) -> StorefrontNode | None:
        if section_id is not None:
            nodes = await self._chip_candidates(release_id, sport_type, section_id)
            matches = match_chip_nodes(nodes, node_key)
            if len(matches) > 1:
                raise StorefrontChipLookupAmbiguousError(
                    node_key, sport_type, len(matches)
                )
            return matches[0] if matches else None

        nodes = await self._chip_candidates(release_id, sport_type, None)
        matches = match_chip_nodes(nodes, node_key)
        return resolve_chip_node_match(matches, node_key, sport_type, None)

    async def _chip_candidates(
        self,
        release_id: int,
        sport_type: str,
        section_id: int | None,
    ) -> list[StorefrontNode]:
        stmt = select(StorefrontNode).where(
            StorefrontNode.release_id == release_id,
            StorefrontNode.sport_type == sport_type,
            StorefrontNode.node_type == NODE_TYPE_CHIP,
            StorefrontNode.active.is_(True),
        )
        if section_id is not None:
            stmt = stmt.where(StorefrontNode.parent_id == section_id)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    # Возвращает descendant chip ids для section или root scope.
    async def descendant_chip_ids(
        self,
        release_id: int,
        sport_type: str,
        section_node_id: int | None = None,
        chip_node_id: int | None = None,
    ) -> list[int]:
        if chip_node_id is not None:
            return [chip_node_id]
        if section_node_id is not None:
            result = await self.session.execute(
                select(StorefrontNode.id).where(
                    StorefrontNode.release_id == release_id,
                    StorefrontNode.sport_type == sport_type,
                    StorefrontNode.node_type == NODE_TYPE_CHIP,
                    StorefrontNode.parent_id == section_node_id,
                    StorefrontNode.active.is_(True),
                )
            )
            return list(result.scalars().all())
        result = await self.session.execute(
            select(StorefrontNode.id).where(
                StorefrontNode.release_id == release_id,
                StorefrontNode.sport_type == sport_type,
                StorefrontNode.node_type == NODE_TYPE_CHIP,
                StorefrontNode.active.is_(True),
            )
        )
        return list(result.scalars().all())

    # Загружает taxonomy nodes release для API.
    async def load_taxonomy_nodes(self, release_id: int) -> list[StorefrontNode]:
        result = await self.session.execute(
            select(StorefrontNode)
            .where(
                StorefrontNode.release_id == release_id,
                StorefrontNode.active.is_(True),
            )
            .order_by(StorefrontNode.sort_order, StorefrontNode.id)
        )
        return list(result.scalars().all())

    # Считает DISTINCT products для chip ids с availability filters.
    async def count_distinct_products_for_chips(
        self,
        release_id: int,
        chip_ids: list[int],
        availability_filters: list,
    ) -> int:
        if not chip_ids:
            return 0
        stmt = (
            select(func.count(func.distinct(ProductStorefrontPlacement.product_id)))
            .select_from(ProductStorefrontPlacement)
            .join(Product, Product.id == ProductStorefrontPlacement.product_id)
            .where(
                ProductStorefrontPlacement.release_id == release_id,
                ProductStorefrontPlacement.storefront_node_id.in_(chip_ids),
                *availability_filters,
            )
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one() or 0)

    # Считает DISTINCT products с placement на любом active chip release.
    async def count_distinct_products_global(
        self,
        release_id: int,
        availability_filters: list,
    ) -> int:
        stmt = (
            select(func.count(func.distinct(ProductStorefrontPlacement.product_id)))
            .select_from(ProductStorefrontPlacement)
            .join(Product, Product.id == ProductStorefrontPlacement.product_id)
            .join(
                StorefrontNode,
                and_(
                    StorefrontNode.id == ProductStorefrontPlacement.storefront_node_id,
                    StorefrontNode.release_id == ProductStorefrontPlacement.release_id,
                ),
            )
            .where(
                ProductStorefrontPlacement.release_id == release_id,
                StorefrontNode.node_type == NODE_TYPE_CHIP,
                StorefrontNode.active.is_(True),
                *availability_filters,
            )
        )
        result = await self.session.execute(stmt)
        return int(result.scalar_one() or 0)

    # Загружает resolution товара в release.
    async def get_product_resolution(
        self, release_id: int, product_id: int
    ) -> ProductStorefrontResolution | None:
        result = await self.session.execute(
            select(ProductStorefrontResolution).where(
                ProductStorefrontResolution.release_id == release_id,
                ProductStorefrontResolution.product_id == product_id,
            )
        )
        return result.scalar_one_or_none()

    # Batch resolutions для admin nav pills.
    async def get_product_resolutions_map(
        self, release_id: int, product_ids: list[int]
    ) -> dict[int, ProductStorefrontResolution]:
        if not product_ids:
            return {}
        result = await self.session.execute(
            select(ProductStorefrontResolution).where(
                ProductStorefrontResolution.release_id == release_id,
                ProductStorefrontResolution.product_id.in_(product_ids),
            )
        )
        return {row.product_id: row for row in result.scalars().all()}

    # Помечает verified release dirty.
    async def mark_verified_dirty(self, release_id: int) -> None:
        release = await self.get_release(release_id)
        if release is None:
            return
        if release.status == RELEASE_STATUS_VERIFIED:
            release.status = RELEASE_STATUS_VERIFIED_DIRTY
            release.dirty_at = utc_now_naive()

    # Список release ids для taxonomy recompute hook.
    async def list_recompute_release_ids(self) -> list[int]:
        result = await self.session.execute(
            select(StorefrontMappingRelease.id).where(
                StorefrontMappingRelease.status.in_(
                    [
                        RELEASE_STATUS_DRAFT,
                        RELEASE_STATUS_BACKFILLED,
                        RELEASE_STATUS_ACTIVE,
                        RELEASE_STATUS_VERIFIED,
                        RELEASE_STATUS_VERIFIED_DIRTY,
                    ]
                )
            )
        )
        return list(result.scalars().all())

    # Архивирует текущий active release.
    async def archive_active_release(self) -> None:
        active = await self.get_active_release()
        if active is not None:
            active.status = RELEASE_STATUS_ARCHIVED
