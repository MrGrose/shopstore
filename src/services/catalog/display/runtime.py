from dataclasses import dataclass

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings
from src.repositories.storefront_mapping import StorefrontMappingRepository
from src.services.catalog.display.compat_params import (
    StorefrontCompatParamError,
    StorefrontCompatParams,
)
from src.services.catalog.read.scope import (
    UnknownCatalogTopCategoryError,
    resolve_public_catalog_top_category,
)


@dataclass(frozen=True)
class CatalogQueryContext:
    top_category: str
    mapping_release_id: int
    chip_node_ids: tuple[int, ...] | None


class StorefrontMappingRuntimeError(Exception):
    pass


# Возвращает active release id или 503 если release отсутствует.
async def require_active_release_id(session: AsyncSession) -> int:
    repo = StorefrontMappingRepository(session)
    active = await repo.get_active_release()
    if active is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Storefront mapping active release не настроен",
        )
    return active.id


# Резолвит node filter для public catalog endpoints.
async def resolve_public_storefront_filter(
    session: AsyncSession,
    top_category: str | None,
    section: str | None,
    node: str | None,
    legacy_sub: str | None = None,
    legacy_category_type: str | None = None,
):
    release_id = await require_active_release_id(session)
    compat = StorefrontCompatParams(session)
    try:
        return await compat.resolve_filter(
            release_id,
            top_category,
            section,
            node,
            legacy_sub=(
                legacy_sub if settings.STOREFRONT_MAPPING_COMPAT_PARAMS else None
            ),
            legacy_category_type=(
                legacy_category_type
                if settings.STOREFRONT_MAPPING_COMPAT_PARAMS
                else None
            ),
        )
    except StorefrontCompatParamError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


# Единый резолвер query context для catalog endpoints.
async def resolve_catalog_query_context(
    session: AsyncSession,
    top_category: str | None = None,
    section: str | None = None,
    node: str | None = None,
    sub: str | None = None,
    category_type: str | None = None,
    legacy_type: str | None = None,
    category: str | None = None,
    categories: list[str] | None = None,
    category_l3: str | None = None,
) -> CatalogQueryContext:
    try:
        top = resolve_public_catalog_top_category(top_category)
    except UnknownCatalogTopCategoryError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    type_key = (category_type or legacy_type or "").strip() or None

    if category or categories or category_l3:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Legacy category params не поддерживаются",
        )

    node_filter = await resolve_public_storefront_filter(
        session,
        top,
        section,
        node,
        legacy_sub=sub,
        legacy_category_type=type_key,
    )
    return CatalogQueryContext(
        top_category=node_filter.sport_type,
        mapping_release_id=node_filter.release_id,
        chip_node_ids=node_filter.chip_node_ids,
    )
