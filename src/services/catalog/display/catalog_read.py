from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.product import Product
from src.models.storefront_mapping import ProductStorefrontPlacement
from src.repositories.storefront_mapping import StorefrontMappingRepository
from src.schemas.catalog_labels import (
    CatalogSubCategorySchema,
    CatalogSubCategoryTypeSchema,
    CatalogTaxonomyChipSchema,
    CatalogTaxonomySchema,
    CatalogTaxonomySectionSchema,
    CatalogTaxonomySportSchema,
)
from src.services.catalog.display.constants import (
    NODE_TYPE_CHIP,
    NODE_TYPE_ROOT,
    NODE_TYPE_SECTION,
)
from src.services.catalog.read.scope import CATALOG_TOP_ORDER


class StorefrontCatalogReadService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = StorefrontMappingRepository(session)

    # Строит taxonomy dict из nodes active release.
    async def build_taxonomy(self, release_id: int) -> dict:
        nodes = await self.repo.load_taxonomy_nodes(release_id)
        roots = [n for n in nodes if n.node_type == NODE_TYPE_ROOT]
        sports: list[CatalogTaxonomySportSchema] = []
        for sport_name in CATALOG_TOP_ORDER:
            root = next(
                (n for n in roots if n.sport_type == sport_name),
                None,
            )
            if root is None:
                continue
            sections = [
                n
                for n in nodes
                if n.parent_id == root.id and n.node_type == NODE_TYPE_SECTION
            ]
            section_schemas: list[CatalogTaxonomySectionSchema] = []
            for section in sections:
                chips = [
                    n
                    for n in nodes
                    if n.parent_id == section.id and n.node_type == NODE_TYPE_CHIP
                ]
                section_schemas.append(
                    CatalogTaxonomySectionSchema(
                        slug=section.slug,
                        label=section.label_ru,
                        chips=[
                            CatalogTaxonomyChipSchema(
                                display_key=chip.display_key,
                                slug=chip.slug,
                                label=chip.label_ru,
                            )
                            for chip in chips
                        ],
                    )
                )
            sports.append(
                CatalogTaxonomySportSchema(
                    sport=sport_name,
                    slug=root.slug,
                    label=root.label_ru,
                    sections=section_schemas,
                    subcategories=[],
                )
            )
        return CatalogTaxonomySchema(sports=sports, sub_slug_aliases={}).model_dump()

    # Availability filters из stock scope kwargs.
    def _availability_filters(
        self,
        include_out_of_stock: bool,
        zero_stock_only: bool,
        inactive_only: bool,
        exclude_over_supplier_unit_cap: bool = False,
        require_complete: bool = False,
    ) -> list:
        from src.repositories.product_repo import CrudProduct

        crud = CrudProduct(session=self.session, model=Product)
        return crud._catalog_base_filters(
            include_out_of_stock=include_out_of_stock,
            zero_stock_only=zero_stock_only,
            inactive_only=inactive_only,
            exclude_over_supplier_unit_cap=exclude_over_supplier_unit_cap,
            require_complete=require_complete,
        )

    # Считает DISTINCT counts по chip nodes release.
    async def chip_product_counts(
        self,
        release_id: int,
        chip_ids: list[int],
        availability_filters: list,
    ) -> dict[int, int]:
        if not chip_ids:
            return {}
        stmt = (
            select(
                ProductStorefrontPlacement.storefront_node_id,
                func.count(func.distinct(ProductStorefrontPlacement.product_id)),
            )
            .select_from(ProductStorefrontPlacement)
            .join(Product, Product.id == ProductStorefrontPlacement.product_id)
            .where(
                ProductStorefrontPlacement.release_id == release_id,
                ProductStorefrontPlacement.storefront_node_id.in_(chip_ids),
                *availability_filters,
            )
            .group_by(ProductStorefrontPlacement.storefront_node_id)
        )
        result = await self.session.execute(stmt)
        return {int(row[0]): int(row[1]) for row in result.all()}

    # Subcategories schema из storefront nodes + placement counts.
    async def build_subcategories(
        self,
        release_id: int,
        sport_type: str,
        sub_slug: str | None,
        include_out_of_stock: bool = False,
        zero_stock_only: bool = False,
        inactive_only: bool = False,
        exclude_over_supplier_unit_cap: bool = False,
        require_complete: bool = False,
    ) -> list[CatalogSubCategorySchema]:
        nodes = await self.repo.load_taxonomy_nodes(release_id)
        root = next(
            (
                n
                for n in nodes
                if n.node_type == NODE_TYPE_ROOT and n.sport_type == sport_type
            ),
            None,
        )
        if root is None:
            return []
        availability = self._availability_filters(
            include_out_of_stock,
            zero_stock_only,
            inactive_only,
            exclude_over_supplier_unit_cap,
            require_complete,
        )
        sections = [
            n
            for n in nodes
            if n.parent_id == root.id and n.node_type == NODE_TYPE_SECTION
        ]
        if not (sub_slug or "").strip():
            return [
                CatalogSubCategorySchema(
                    slug=section.slug,
                    label=section.label_ru,
                    type_level="chip",
                    types=[],
                )
                for section in sections
            ]

        section = next(
            (s for s in sections if s.slug == (sub_slug or "").strip()),
            None,
        )
        if section is None:
            return []
        chips = [
            n
            for n in nodes
            if n.parent_id == section.id and n.node_type == NODE_TYPE_CHIP
        ]
        counts = await self.chip_product_counts(
            release_id,
            [c.id for c in chips],
            availability,
        )
        types = [
            CatalogSubCategoryTypeSchema(
                key=chip.display_key,
                label_ru=chip.label_ru,
                count=counts.get(chip.id, 0),
            )
            for chip in chips
            if counts.get(chip.id, 0) > 0
        ]
        row = CatalogSubCategorySchema(
            slug=section.slug,
            label=section.label_ru,
            type_level="chip",
            types=types,
        )
        return [row] if types else []
