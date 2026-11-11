import logging

from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories.storefront_mapping import StorefrontMappingRepository
from src.services.catalog.categories.taxonomy_policy import (
    refine_storefront_mapping_taxonomy,
)
from src.services.catalog.display.resolver import DisplayMappingResolver, MappingRuleRow
from src.services.catalog.display.taxonomy import is_catalogized_product

logger = logging.getLogger(__name__)


class StorefrontPlacementService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = StorefrontMappingRepository(session)
        self.resolver = DisplayMappingResolver()

    # Пересчитывает placements/resolution одного товара в release.
    async def recompute_product(
        self,
        release_id: int,
        product_id: int,
        rules: tuple[MappingRuleRow, ...] | None = None,
    ) -> None:
        product = await self.repo.get_product(product_id)
        if product is None:
            return
        if not is_catalogized_product(product):
            await self.repo.clear_product_materialization(release_id, product_id)
            if product.is_active:
                logger.warning(
                    "Активный товар %s без taxonomy: placements удалены в release %s",
                    product_id,
                    release_id,
                )
            return
        rule_rows = (
            rules if rules is not None else await self.repo.load_rule_rows(release_id)
        )
        category_l1, category_l2, category_l3 = refine_storefront_mapping_taxonomy(
            product.category_l1,
            product.category_l2,
            product.category_l3,
            product.sport_type,
            product.title,
        )
        result = self.resolver.resolve(
            release_id,
            product.sport_type or "",
            category_l1,
            category_l2,
            category_l3,
            rule_rows,
        )
        placement_pairs = tuple(
            (p.storefront_node_id, p.mapping_rule_id) for p in result.placements
        )
        await self.repo.write_materialization(
            release_id,
            product_id,
            result.status,
            result.reason,
            result.resolver_hash,
            placement_pairs,
        )

    # Batch recompute catalogized products с одной загрузкой rules.
    async def recompute_batch(
        self, release_id: int, product_ids: list[int], batch_size: int = 200
    ) -> int:
        if not product_ids:
            return 0
        rules = await self.repo.load_rule_rows(release_id)
        count = 0
        for i in range(0, len(product_ids), batch_size):
            chunk = product_ids[i : i + batch_size]
            for product_id in chunk:
                await self.recompute_product(release_id, product_id, rules=rules)
                count += 1
        return count

    # Backfill всех catalogized products в release.
    async def backfill_release(self, release_id: int) -> int:
        product_ids = await self.repo.list_catalogized_product_ids()
        return await self.recompute_batch(release_id, product_ids)

    # Hook после изменения taxonomy: recompute active + mark verified dirty.
    async def on_product_taxonomy_changed(self, product_id: int) -> None:
        release_ids = await self.repo.list_recompute_release_ids()
        for release_id in release_ids:
            release = await self.repo.get_release(release_id)
            if release is None:
                continue
            if release.status in ("verified", "verified_dirty"):
                await self.repo.mark_verified_dirty(release_id)
            if release.status in ("draft", "backfilled"):
                release.status = "draft"
            await self.recompute_product(release_id, product_id)
