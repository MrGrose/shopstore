from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.product import Product
from src.models.storefront_mapping import (
    ProductStorefrontPlacement,
    ProductStorefrontResolution,
    StorefrontNode,
)
from src.repositories.storefront_mapping import StorefrontMappingRepository
from src.services.catalog.categories.taxonomy_policy import (
    refine_storefront_mapping_taxonomy,
)
from src.services.catalog.display.constants import (
    NODE_TYPE_CHIP,
    NODE_TYPE_ROOT,
    RESOLUTION_EXCLUDED,
    RESOLUTION_MAPPED,
    RESOLUTION_MAPPING_ERROR,
    RESOLUTION_UNMAPPED,
)
from src.services.catalog.display.resolver import DisplayMappingResolver
from src.services.catalog.display.taxonomy import (
    is_catalogized_product,
    is_invalid_taxonomy_product,
)


@dataclass(frozen=True)
class CoverageReport:
    invalid_taxonomy: int
    unexpected_unmapped: int
    mapping_error: int
    mapped: int
    excluded: int
    integrity_failures: dict[str, int] = field(default_factory=dict)

    @property
    def blocks_activation(self) -> bool:
        if sum(self.integrity_failures.values()) > 0:
            return True
        return (
            self.invalid_taxonomy > 0
            or self.unexpected_unmapped > 0
            or self.mapping_error > 0
        )


class StorefrontMappingReconciler:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = StorefrontMappingRepository(session)
        self.resolver = DisplayMappingResolver()

    # Coverage + integrity report для release.
    async def run(self, release_id: int) -> CoverageReport:
        invalid_taxonomy = 0
        unexpected_unmapped = 0
        mapping_error = 0
        mapped = 0
        excluded = 0

        products_result = await self.session.execute(select(Product))
        products = list(products_result.scalars().all())
        rules = await self.repo.load_rule_rows(release_id)

        for product in products:
            if is_invalid_taxonomy_product(product):
                invalid_taxonomy += 1
                continue
            if not is_catalogized_product(product) or not product.is_active:
                continue
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
                rules,
            )
            if result.status == RESOLUTION_UNMAPPED:
                unexpected_unmapped += 1
            elif result.status == RESOLUTION_MAPPING_ERROR:
                mapping_error += 1
            elif result.status == RESOLUTION_MAPPED:
                mapped += 1
            elif result.status == RESOLUTION_EXCLUDED:
                excluded += 1

        integrity = await self._integrity_checks(release_id, rules, products)
        return CoverageReport(
            invalid_taxonomy=invalid_taxonomy,
            unexpected_unmapped=unexpected_unmapped,
            mapping_error=mapping_error,
            mapped=mapped,
            excluded=excluded,
            integrity_failures=integrity,
        )

    async def _integrity_checks(
        self, release_id: int, rules: tuple, products: list[Product]
    ) -> dict[str, int]:
        failures: dict[str, int] = {}

        def bump(key: str, n: int = 1) -> None:
            failures[key] = failures.get(key, 0) + n

        placements = await self.session.execute(
            select(ProductStorefrontPlacement, Product)
            .join(Product, Product.id == ProductStorefrontPlacement.product_id)
            .where(ProductStorefrontPlacement.release_id == release_id)
        )
        for placement, product in placements.all():
            if not is_catalogized_product(product):
                bump("stale_placement_non_catalogized")
                continue
            node = await self.session.get(StorefrontNode, placement.storefront_node_id)
            if node is None or node.release_id != release_id:
                bump("cross_release_drift")
                continue
            if node.node_type != NODE_TYPE_CHIP or not node.active:
                bump("invalid_node_placement")

        resolutions = await self.session.execute(
            select(ProductStorefrontResolution, Product)
            .join(Product, Product.id == ProductStorefrontResolution.product_id)
            .where(ProductStorefrontResolution.release_id == release_id)
        )
        for resolution, product in resolutions.all():
            if not is_catalogized_product(product):
                bump("stale_resolution_non_catalogized")

        root_dup = await self.session.execute(
            select(StorefrontNode.sport_type, func.count())
            .where(
                StorefrontNode.release_id == release_id,
                StorefrontNode.node_type == NODE_TYPE_ROOT,
            )
            .group_by(StorefrontNode.sport_type)
            .having(func.count() > 1)
        )
        if root_dup.first() is not None:
            bump("duplicate_root")

        resolution_rows = await self.session.execute(
            select(ProductStorefrontResolution).where(
                ProductStorefrontResolution.release_id == release_id
            )
        )
        resolution_by_product = {
            row.product_id: row for row in resolution_rows.scalars().all()
        }
        placement_counts_result = await self.session.execute(
            select(
                ProductStorefrontPlacement.product_id,
                func.count(),
            )
            .where(ProductStorefrontPlacement.release_id == release_id)
            .group_by(ProductStorefrontPlacement.product_id)
        )
        placement_counts = {
            product_id: int(count)
            for product_id, count in placement_counts_result.all()
        }

        for product in products:
            if not product.is_active or not is_catalogized_product(product):
                continue
            category_l1, category_l2, category_l3 = refine_storefront_mapping_taxonomy(
                product.category_l1,
                product.category_l2,
                product.category_l3,
                product.sport_type,
                product.title,
            )
            expected = self.resolver.resolve(
                release_id,
                product.sport_type or "",
                category_l1,
                category_l2,
                category_l3,
                rules,
            )
            resolution = resolution_by_product.get(product.id)
            if resolution is None:
                bump("missing_resolution")
                continue
            if resolution.resolver_hash != expected.resolver_hash:
                bump("stale_resolution")
            pcount = placement_counts.get(product.id, 0)
            if expected.status == RESOLUTION_MAPPED and pcount == 0:
                bump("missing_placement")
            if expected.status != RESOLUTION_MAPPED and pcount > 0:
                bump("stale_placement")

        return failures
