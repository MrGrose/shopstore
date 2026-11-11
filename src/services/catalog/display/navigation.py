from sqlalchemy.ext.asyncio import AsyncSession

from src.schemas.catalog_labels import (
    CatalogNavigationActiveNodeSchema,
    CatalogNavigationLinkSchema,
    CatalogNavigationSchema,
    CatalogSubCategorySchema,
)
from src.services.catalog.display.catalog_read import StorefrontCatalogReadService
from src.services.catalog.display.compat_params import (
    StorefrontCompatParams,
    StorefrontNodeFilter,
)
from src.services.catalog.display.constants import (
    NODE_TYPE_CHIP,
    NODE_TYPE_ROOT,
    NODE_TYPE_SECTION,
)
from src.services.catalog.display.runtime import require_active_release_id
from src.services.catalog.read.scope import CATALOG_ALL_TOP_CATEGORY
from src.utils.labels import translate_sport_type


# Собирает query-параметры ссылки для legacy или mapping scope.
def _url_params_for_scope(
    use_mapping_params: bool,
    sub: str,
    category_type: str,
) -> dict[str, str]:
    params: dict[str, str] = {}
    if use_mapping_params:
        if sub:
            params["section"] = sub
        if category_type:
            params["node"] = category_type
    else:
        if sub:
            params["sub"] = sub
        if category_type:
            params["category_type"] = category_type
    return params


# Возвращает русские подписи section и chip из taxonomy nodes.
async def _section_labels(
    session: AsyncSession,
    release_id: int,
    sport_type: str,
    section_slug: str | None,
    type_key: str | None,
) -> tuple[str | None, str | None]:
    if not section_slug:
        return None, None
    read_svc = StorefrontCatalogReadService(session)
    nodes = await read_svc.repo.load_taxonomy_nodes(release_id)
    root = next(
        (
            node
            for node in nodes
            if node.node_type == NODE_TYPE_ROOT and node.sport_type == sport_type
        ),
        None,
    )
    if root is None:
        return None, None
    section = next(
        (
            node
            for node in nodes
            if node.parent_id == root.id
            and node.node_type == NODE_TYPE_SECTION
            and node.slug == section_slug
        ),
        None,
    )
    if section is None:
        return None, None
    type_label = None
    if type_key:
        chip = next(
            (
                node
                for node in nodes
                if node.parent_id == section.id
                and node.node_type == NODE_TYPE_CHIP
                and node.display_key == type_key
            ),
            None,
        )
        if chip is not None:
            type_label = chip.label_ru
    return section.label_ru, type_label


# Проверяет, что у спорта в release есть mapping sections.
def _sport_uses_mapping_sections(
    sport_type: str,
    nodes: list,
) -> bool:
    root = next(
        (
            node
            for node in nodes
            if node.node_type == NODE_TYPE_ROOT and node.sport_type == sport_type
        ),
        None,
    )
    if root is None:
        return False
    return any(
        node.parent_id == root.id and node.node_type == NODE_TYPE_SECTION
        for node in nodes
    )


# Резолвит scope URL в canonical node filter через compat params.
async def _resolve_node_filter(
    session: AsyncSession,
    top_category: str | None,
    section: str | None,
    node: str | None,
    sub: str | None,
    category_type: str | None,
    legacy_type: str | None,
) -> StorefrontNodeFilter:
    release_id = await require_active_release_id(session)
    compat = StorefrontCompatParams(session)
    type_key = (category_type or legacy_type or "").strip() or None
    return await compat.resolve_filter(
        release_id,
        top_category,
        section,
        node,
        legacy_sub=sub,
        legacy_category_type=type_key,
    )


# Строит хлебные крошки для текущего scope каталога.
def _build_breadcrumbs(
    sport_type: str,
    sub: str,
    category_type: str,
    use_mapping_params: bool,
    section_label: str | None,
    type_label: str | None,
) -> list[CatalogNavigationLinkSchema]:
    if sport_type == CATALOG_ALL_TOP_CATEGORY:
        return [
            CatalogNavigationLinkSchema(
                label=translate_sport_type(sport_type) or sport_type,
                url_params={},
            )
        ]

    crumbs: list[CatalogNavigationLinkSchema] = [
        CatalogNavigationLinkSchema(
            label=translate_sport_type(sport_type) or sport_type,
            url_params={},
        )
    ]
    if sub:
        crumbs.append(
            CatalogNavigationLinkSchema(
                label=section_label or sub,
                url_params=_url_params_for_scope(
                    use_mapping_params,
                    sub,
                    "",
                ),
            )
        )
    if sub and category_type:
        crumbs.append(
            CatalogNavigationLinkSchema(
                label=type_label or category_type,
                url_params=_url_params_for_scope(
                    use_mapping_params,
                    sub,
                    category_type,
                ),
            )
        )
    return crumbs


# Собирает navigation payload: scope, breadcrumbs, subcategories, url_params.
async def build_catalog_navigation(
    session: AsyncSession,
    top_category: str | None = None,
    section: str | None = None,
    node: str | None = None,
    sub: str | None = None,
    category_type: str | None = None,
    legacy_type: str | None = None,
    include_out_of_stock: bool = False,
    zero_stock_only: bool = False,
    inactive_only: bool = False,
    exclude_over_supplier_unit_cap: bool = False,
    require_complete: bool = False,
) -> CatalogNavigationSchema:
    node_filter = await _resolve_node_filter(
        session,
        top_category,
        section,
        node,
        sub,
        category_type,
        legacy_type,
    )
    sport_type = node_filter.sport_type
    canonical_sub = (node_filter.section_slug or "").strip()
    canonical_type = (node_filter.node_key or "").strip()

    read_svc = StorefrontCatalogReadService(session)
    nodes = await read_svc.repo.load_taxonomy_nodes(node_filter.release_id)
    use_mapping_params = _sport_uses_mapping_sections(sport_type, nodes)
    section_label, type_label = await _section_labels(
        session,
        node_filter.release_id,
        sport_type,
        canonical_sub or None,
        canonical_type or None,
    )

    subcategories: list[CatalogSubCategorySchema] = []
    if sport_type != CATALOG_ALL_TOP_CATEGORY:
        subcategories = await read_svc.build_subcategories(
            node_filter.release_id,
            sport_type,
            canonical_sub or None,
            include_out_of_stock=include_out_of_stock,
            zero_stock_only=zero_stock_only,
            inactive_only=inactive_only,
            exclude_over_supplier_unit_cap=exclude_over_supplier_unit_cap,
            require_complete=require_complete,
        )

    url_params = _url_params_for_scope(
        use_mapping_params,
        canonical_sub,
        canonical_type,
    )
    active_node = None
    if canonical_sub or canonical_type:
        active_node = CatalogNavigationActiveNodeSchema(
            sub=canonical_sub,
            category_type=canonical_type,
            section_label=section_label,
            type_label=type_label,
        )

    return CatalogNavigationSchema(
        top_category=sport_type,
        use_mapping_params=use_mapping_params,
        sub=canonical_sub,
        category_type=canonical_type,
        url_params=url_params,
        active_node=active_node,
        breadcrumbs=_build_breadcrumbs(
            sport_type,
            canonical_sub,
            canonical_type,
            use_mapping_params,
            section_label,
            type_label,
        ),
        subcategories=subcategories,
    )
