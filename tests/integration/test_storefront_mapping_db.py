import pytest
from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from src.models.product import Product
from src.models.storefront_mapping import StorefrontMappingRelease, StorefrontNode
from src.repositories.session import async_session_maker
from src.repositories.storefront_mapping import (
    StorefrontChipLookupAmbiguousError,
    StorefrontMappingRepository,
)
from src.services.catalog import CatalogService
from src.services.catalog.display.catalog_read import StorefrontCatalogReadService
from src.services.catalog.display.compat_params import (
    StorefrontCompatParamError,
    StorefrontCompatParams,
)
from src.services.catalog.display.constants import (
    NODE_TYPE_CHIP,
    NODE_TYPE_ROOT,
    NODE_TYPE_SECTION,
    RELEASE_STATUS_BACKFILLED,
    RELEASE_STATUS_DRAFT,
)
from src.services.catalog.display.placement_service import StorefrontPlacementService
from src.services.catalog.display.reconciler import StorefrontMappingReconciler
from src.services.catalog.display.release_service import (
    StorefrontReleaseError,
    StorefrontReleaseService,
)
from src.services.catalog.display.seed import StorefrontGreenfieldSeeder
from src.services.catalog.display.ux_blueprint import load_storefront_ux_blueprint
from src.services.catalog.read.caches import invalidate_catalog_read_caches
from src.services.catalog.read.scope import (
    CATALOG_ALL_TOP_CATEGORY,
    CATALOG_TOP_ORDER,
    CatalogScope,
)


async def _session_or_fail():
    try:
        session = async_session_maker()
        await session.connection()
        return session
    except (OperationalError, OSError, Exception) as exc:
        pytest.fail(f"PostgreSQL недоступен для integration test: {exc}")


# Shadow parity: repo chip counts vs CatalogService API counts per sport.
async def _shadow_compare_release(session, release_id: int) -> dict:
    repo = StorefrontMappingRepository(session)
    read_svc = CatalogService(session)
    availability = read_svc.product_crud._catalog_base_filters()
    mismatches: list[dict[str, object]] = []

    repo_global = await repo.count_distinct_products_global(release_id, availability)
    api_global = await read_svc.get_catalog_product_count(
        top_category=CATALOG_ALL_TOP_CATEGORY,
        mapping_release_id=release_id,
        chip_node_ids=None,
    )
    if repo_global != api_global:
        mismatches.append(
            {
                "scope": CATALOG_ALL_TOP_CATEGORY,
                "repo_count": repo_global,
                "api_count": api_global,
            }
        )

    for sport in CATALOG_TOP_ORDER:
        chip_ids = tuple(await repo.descendant_chip_ids(release_id, sport))
        repo_count = await repo.count_distinct_products_for_chips(
            release_id,
            list(chip_ids),
            availability,
        )
        api_count = await read_svc.get_catalog_product_count(
            top_category=sport,
            mapping_release_id=release_id,
            chip_node_ids=chip_ids,
        )
        if repo_count != api_count:
            mismatches.append(
                {
                    "sport": sport,
                    "repo_count": repo_count,
                    "api_count": api_count,
                }
            )
    return {
        "release_id": release_id,
        "mismatch_count": len(mismatches),
        "mismatches": mismatches,
        "ok": len(mismatches) == 0,
    }


@pytest.mark.asyncio
async def test_reconciler_flags_missing_resolution_for_catalogized_product() -> None:
    session = await _session_or_fail()
    try:
        seeder = StorefrontGreenfieldSeeder(session)
        release_id = await seeder.ensure_draft_release(None)
        await seeder.seed_release(release_id)
        product = (
            await session.execute(
                select(Product)
                .where(
                    Product.is_active.is_(True),
                    Product.sport_type.is_not(None),
                    Product.category_l2.is_not(None),
                )
                .limit(1)
            )
        ).scalar_one_or_none()
        if product is None:
            pytest.skip("no catalogized products in DB")

        reconciler = StorefrontMappingReconciler(session)
        report = await reconciler.run(release_id)
        assert report.integrity_failures.get("missing_resolution", 0) >= 1
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_mark_verified_requires_backfilled_status() -> None:
    session = await _session_or_fail()
    try:
        seeder = StorefrontGreenfieldSeeder(session)
        release_id = await seeder.ensure_draft_release(None)
        release = await session.get(StorefrontMappingRelease, release_id)
        assert release is not None
        assert release.status == "draft"
        svc = StorefrontReleaseService(session)
        with pytest.raises(StorefrontReleaseError, match="backfill"):
            await svc.mark_verified(release_id)
        release.status = RELEASE_STATUS_BACKFILLED
        await session.flush()
        with pytest.raises(StorefrontReleaseError, match="Verify failed"):
            await svc.mark_verified(release_id)
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_backfill_then_reconciler_has_no_integrity_failures() -> None:
    session = await _session_or_fail()
    try:
        seeder = StorefrontGreenfieldSeeder(session)
        release_id = await seeder.ensure_draft_release(None)
        await seeder.seed_release(release_id)
        placement_svc = StorefrontPlacementService(session)
        recomputed = await placement_svc.backfill_release(release_id)
        assert recomputed >= 0
        release = await session.get(StorefrontMappingRelease, release_id)
        assert release is not None
        release.status = RELEASE_STATUS_BACKFILLED
        await session.flush()

        report = await StorefrontMappingReconciler(session).run(release_id)
        assert sum(report.integrity_failures.values()) == 0
        assert report.invalid_taxonomy == 0
        assert report.mapping_error == 0
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_subcategories_built_from_seeded_release() -> None:
    session = await _session_or_fail()
    try:
        seeder = StorefrontGreenfieldSeeder(session)
        release_id = await seeder.ensure_draft_release(None)
        await seeder.seed_release(release_id)
        svc = CatalogService(session)
        rows = await svc.get_catalog_subcategories(
            "Tennis",
            mapping_release_id=release_id,
        )
        assert rows
        assert all(row.slug for row in rows)
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_repo_and_catalog_service_counts_match_for_release() -> None:
    session = await _session_or_fail()
    try:
        seeder = StorefrontGreenfieldSeeder(session)
        release_id = await seeder.ensure_draft_release(None)
        await seeder.seed_release(release_id)
        await StorefrontPlacementService(session).backfill_release(release_id)

        repo = StorefrontMappingRepository(session)
        svc = CatalogService(session)
        chip_ids = await repo.descendant_chip_ids(release_id, "Padel")
        repo_count = await repo.count_distinct_products_for_chips(
            release_id,
            chip_ids,
            svc.product_crud._catalog_base_filters(),
        )
        api_count = await svc.get_catalog_product_count(
            top_category="Padel",
            mapping_release_id=release_id,
            chip_node_ids=tuple(chip_ids),
        )
        assert repo_count == api_count
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_draft_release_starts_with_draft_status() -> None:
    session = await _session_or_fail()
    try:
        seeder = StorefrontGreenfieldSeeder(session)
        release_id = await seeder.ensure_draft_release(None)
        release = await session.get(StorefrontMappingRelease, release_id)
        assert release is not None
        assert release.status == RELEASE_STATUS_DRAFT
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_greenfield_seed_full_pipeline_idempotent_twice() -> None:
    for _run in (1, 2):
        session = await _session_or_fail()
        try:
            seeder = StorefrontGreenfieldSeeder(session)
            release_id = await seeder.ensure_draft_release(None)
            first = await seeder.seed_release(release_id)
            assert first["nodes_created"] == 237
            assert first["rules_created"] == 400
            assert len(load_storefront_ux_blueprint()["rules"]) == 403

            second = await seeder.seed_release(release_id)
            assert second["nodes_created"] == 0
            assert second["rules_created"] == 0

            await StorefrontPlacementService(session).backfill_release(release_id)
            release = await session.get(StorefrontMappingRelease, release_id)
            assert release is not None
            release.status = RELEASE_STATUS_BACKFILLED
            await session.flush()

            report = await StorefrontMappingReconciler(session).run(release_id)
            assert report.invalid_taxonomy == 0
            assert report.mapping_error == 0
            assert sum(report.integrity_failures.values()) == 0

            shadow = await _shadow_compare_release(session, release_id)
            assert shadow["ok"] is True
            assert shadow["mismatch_count"] == 0
        finally:
            await session.rollback()
            await session.close()


@pytest.mark.asyncio
async def test_legacy_node_key_resolves_after_new_release_activation() -> None:
    session = await _session_or_fail()
    try:
        seeder = StorefrontGreenfieldSeeder(session)
        release_id = await seeder.ensure_draft_release(None)
        await seeder.seed_release(release_id)
        await StorefrontPlacementService(session).backfill_release(release_id)
        release = await session.get(StorefrontMappingRelease, release_id)
        assert release is not None
        release.status = RELEASE_STATUS_BACKFILLED
        await session.flush()

        repo = StorefrontMappingRepository(session)
        overgrips_section = await repo.find_section_node(
            release_id, "Tennis", "accessories"
        )
        assert overgrips_section is not None

        overgrips_chip = await repo.find_chip_node(
            release_id,
            "Tennis",
            "tennis.overgrips",
            section_id=overgrips_section.id,
        )
        assert overgrips_chip is not None
        assert overgrips_chip.display_key == "tennis.accessories.overgrips"

        by_slug = await repo.find_chip_node(
            release_id,
            "Tennis",
            "overgrips",
            section_id=overgrips_section.id,
        )
        assert by_slug is not None
        assert by_slug.id == overgrips_chip.id

        bare = await repo.find_chip_node(release_id, "Tennis", "tennis.overgrips")
        assert bare is not None
        assert bare.id == overgrips_chip.id

        filt = await StorefrontCompatParams(session).resolve_filter(
            release_id,
            "Tennis",
            "accessories",
            "tennis.overgrips",
        )
        assert filt.chip_node_ids == (overgrips_chip.id,)

        other_chip = await repo.find_chip_node(
            release_id,
            "Tennis",
            "grips",
            section_id=overgrips_section.id,
        )
        assert other_chip is not None
        meta = dict(other_chip.metadata_json or {})
        meta["legacy_query_keys"] = ["tennis.overgrips"]
        other_chip.metadata_json = meta
        await session.flush()

        with pytest.raises(StorefrontCompatParamError, match="неоднозначен"):
            await StorefrontCompatParams(session).resolve_filter(
                release_id,
                "Tennis",
                None,
                "tennis.overgrips",
            )
        with pytest.raises(StorefrontChipLookupAmbiguousError):
            await repo.find_chip_node(release_id, "Tennis", "tennis.overgrips")
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_greenfield_full_workflow_from_empty_draft() -> None:
    session = await _session_or_fail()
    try:
        seeder = StorefrontGreenfieldSeeder(session)
        release_id = await seeder.ensure_draft_release(None)
        assert not await StorefrontMappingRepository(session).load_taxonomy_nodes(
            release_id
        )

        seeded = await seeder.seed_release(release_id)
        assert seeded["nodes_created"] == 237
        assert seeded["rules_created"] == 400
        assert len(load_storefront_ux_blueprint()["rules"]) == 403

        repo = StorefrontMappingRepository(session)
        nodes = await repo.load_taxonomy_nodes(release_id)
        by_id = {n.id: n for n in nodes}
        roots = [n for n in nodes if n.node_type == NODE_TYPE_ROOT]
        sections = [n for n in nodes if n.node_type == NODE_TYPE_SECTION]
        chips = [n for n in nodes if n.node_type == NODE_TYPE_CHIP]
        assert len(roots) == 3
        assert len(sections) == 16
        assert len(chips) == 218
        for section in sections:
            parent = by_id[section.parent_id]
            assert parent.node_type == NODE_TYPE_ROOT
            assert parent.sport_type == section.sport_type
        for chip in chips:
            parent = by_id[chip.parent_id]
            assert parent.node_type == NODE_TYPE_SECTION
            assert parent.sport_type == chip.sport_type

        await StorefrontPlacementService(session).backfill_release(release_id)
        release = await session.get(StorefrontMappingRelease, release_id)
        assert release is not None
        release.status = RELEASE_STATUS_BACKFILLED
        await session.flush()

        report = await StorefrontMappingReconciler(session).run(release_id)
        assert report.mapping_error == 0
        assert sum(report.integrity_failures.values()) == 0

        shadow = await _shadow_compare_release(session, release_id)
        assert shadow["ok"] is True

        verified = await session.get(StorefrontMappingRelease, release_id)
        assert verified is not None
        assert verified.status == RELEASE_STATUS_BACKFILLED
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_global_all_scope_returns_products_with_active_placements() -> None:
    session = await _session_or_fail()
    try:
        seeder = StorefrontGreenfieldSeeder(session)
        release_id = await seeder.ensure_draft_release(None)
        await seeder.seed_release(release_id)
        await StorefrontPlacementService(session).backfill_release(release_id)

        filt = await StorefrontCompatParams(session).resolve_filter(
            release_id,
            "All",
            None,
            None,
        )
        assert filt.sport_type == CATALOG_ALL_TOP_CATEGORY
        assert filt.chip_node_ids is None

        svc = CatalogService(session)
        scope = CatalogScope.storefront_public()
        stock_kwargs = scope.list_filter_kwargs()
        hidden = await svc._hidden_brands_for_read(scope.exclude_hidden_brands)
        availability = svc.product_crud._catalog_base_filters(**stock_kwargs)
        svc.product_crud._append_hidden_brands_filter(availability, Product, hidden)
        repo = StorefrontMappingRepository(session)
        invalidate_catalog_read_caches(reason="test_global_all_scope")
        repo_count = await repo.count_distinct_products_global(release_id, availability)
        api_count = await svc.get_catalog_product_count(
            top_category=CATALOG_ALL_TOP_CATEGORY,
            mapping_release_id=release_id,
            chip_node_ids=None,
            exclude_hidden_brands=scope.exclude_hidden_brands,
            **stock_kwargs,
        )
        assert repo_count == api_count
        if repo_count > 0:
            items, total, _ = await svc.get_products_list(
                page=1,
                page_size=5,
                top_category=CATALOG_ALL_TOP_CATEGORY,
                mapping_release_id=release_id,
                chip_node_ids=None,
                exclude_hidden_brands=scope.exclude_hidden_brands,
                **stock_kwargs,
            )
            assert total == repo_count
            assert items
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_global_all_scope_without_top_category_param() -> None:
    session = await _session_or_fail()
    try:
        seeder = StorefrontGreenfieldSeeder(session)
        release_id = await seeder.ensure_draft_release(None)
        await seeder.seed_release(release_id)
        await StorefrontPlacementService(session).backfill_release(release_id)

        filt = await StorefrontCompatParams(session).resolve_filter(
            release_id,
            None,
            None,
            None,
        )
        assert filt.chip_node_ids is None

        svc = CatalogService(session)
        none_count = await svc.get_catalog_product_count(
            top_category=CATALOG_ALL_TOP_CATEGORY,
            mapping_release_id=release_id,
            chip_node_ids=None,
        )
        assert none_count >= 0
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_unknown_top_category_rejected_by_compat_params() -> None:
    session = await _session_or_fail()
    try:
        seeder = StorefrontGreenfieldSeeder(session)
        release_id = await seeder.ensure_draft_release(None)
        await seeder.seed_release(release_id)
        with pytest.raises(StorefrontCompatParamError, match="Football"):
            await StorefrontCompatParams(session).resolve_filter(
                release_id,
                "Football",
                None,
                None,
            )
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_active_release_public_nodes_have_russian_label_ru() -> None:
    session = await _session_or_fail()
    try:
        repo = StorefrontMappingRepository(session)
        active = await repo.get_active_release()
        if active is None:
            pytest.skip("no active release")
        nodes = await repo.load_taxonomy_nodes(active.id)
        assert nodes
        for node in nodes:
            label = (node.label_ru or "").strip()
            assert label, node.display_key
            assert any("\u0400" <= ch <= "\u04ff" for ch in label), node.display_key
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_taxonomy_public_response_uses_label_ru() -> None:
    session = await _session_or_fail()
    try:
        seeder = StorefrontGreenfieldSeeder(session)
        release_id = await seeder.ensure_draft_release(None)
        await seeder.seed_release(release_id)

        payload = await StorefrontCatalogReadService(session).build_taxonomy(release_id)
        assert payload["sports"]
        tennis = next(s for s in payload["sports"] if s["sport"] == "Tennis")
        assert tennis["label"] == "Теннис"
        assert tennis["sections"]
        section = next(s for s in tennis["sections"] if s["slug"] == "accessories")
        assert section["label"] == "Аксессуары"
        overgrips = next(
            c
            for c in section["chips"]
            if c["display_key"] == "tennis.accessories.overgrips"
        )
        assert overgrips["label"] == "Овергрипы"
        assert overgrips["label"] != overgrips["display_key"]
        assert overgrips["label"] != overgrips["slug"]
    finally:
        await session.rollback()
        await session.close()


@pytest.mark.asyncio
async def test_invalid_chip_parent_assignment_fails_hierarchy_trigger() -> None:
    session = await _session_or_fail()
    try:
        seeder = StorefrontGreenfieldSeeder(session)
        release_id = await seeder.ensure_draft_release(None)
        root = StorefrontNode(
            release_id=release_id,
            display_key="tennis",
            sport_type="Tennis",
            parent_id=None,
            node_type=NODE_TYPE_ROOT,
            slug="tennis",
            label_ru="Tennis",
            sort_order=1,
            active=True,
        )
        session.add(root)
        await session.flush()

        bad_chip = StorefrontNode(
            release_id=release_id,
            display_key="tennis.bad-chip",
            sport_type="Tennis",
            parent_id=root.id,
            node_type=NODE_TYPE_CHIP,
            slug="bad-chip",
            label_ru="Bad",
            sort_order=2,
            active=True,
        )
        session.add(bad_chip)
        await session.flush()

        with pytest.raises(Exception, match="chip parent must be section"):
            await session.commit()
    finally:
        await session.rollback()
        await session.close()
