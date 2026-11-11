from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from src.repositories.storefront_mapping import (
    StorefrontChipLookupAmbiguousError,
    StorefrontMappingRepository,
)
from src.services.catalog.read.scope import (
    CATALOG_ALL_TOP_CATEGORY,
    UnknownCatalogTopCategoryError,
    resolve_public_catalog_top_category,
)


@dataclass(frozen=True)
class StorefrontNodeFilter:
    release_id: int
    sport_type: str
    chip_node_ids: tuple[int, ...] | None
    section_slug: str | None = None
    node_key: str | None = None


class StorefrontCompatParamError(Exception):
    pass


class StorefrontCompatParams:
    def __init__(self, session: AsyncSession) -> None:
        self.repo = StorefrontMappingRepository(session)

    # Резолвит canonical section/node или legacy sub/category_type.
    async def resolve_filter(
        self,
        release_id: int,
        top_category: str | None,
        section: str | None,
        node: str | None,
        legacy_sub: str | None = None,
        legacy_category_type: str | None = None,
    ) -> StorefrontNodeFilter:
        try:
            sport = resolve_public_catalog_top_category(top_category)
        except UnknownCatalogTopCategoryError as exc:
            raise StorefrontCompatParamError(str(exc)) from exc
        section_slug = (section or legacy_sub or "").strip() or None
        node_key = (node or legacy_category_type or "").strip() or None

        if sport == CATALOG_ALL_TOP_CATEGORY:
            if section_slug or node_key:
                raise StorefrontCompatParamError(
                    "section/node требуют sport scope (Tennis, Padel, Running)"
                )
            return StorefrontNodeFilter(
                release_id=release_id,
                sport_type=sport,
                chip_node_ids=None,
                section_slug=section_slug,
                node_key=node_key,
            )

        section_node = None
        if section_slug:
            section_node = await self.repo.find_section_node(
                release_id, sport, section_slug
            )
            if section_node is None:
                raise StorefrontCompatParamError(
                    f"section {section_slug!r} не найден в release {release_id}"
                )

        chip_node = None
        if node_key:
            try:
                chip_node = await self.repo.find_chip_node(
                    release_id,
                    sport,
                    node_key,
                    section_id=section_node.id if section_node else None,
                )
            except StorefrontChipLookupAmbiguousError as exc:
                raise StorefrontCompatParamError(str(exc)) from exc
            if chip_node is None:
                raise StorefrontCompatParamError(
                    f"node {node_key!r} не найден в release {release_id}"
                )

        chip_ids = await self.repo.descendant_chip_ids(
            release_id,
            sport,
            section_node_id=section_node.id if section_node else None,
            chip_node_id=chip_node.id if chip_node else None,
        )
        return StorefrontNodeFilter(
            release_id=release_id,
            sport_type=sport,
            chip_node_ids=tuple(chip_ids),
            section_slug=section_slug,
            node_key=node_key,
        )
