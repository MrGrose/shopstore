from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.storefront_mapping import (
    StorefrontMappingRelease,
    StorefrontMappingRule,
    StorefrontNode,
)
from src.repositories.storefront_mapping import StorefrontMappingRepository
from src.services.catalog.display.constants import (
    RELEASE_ACTIVATION_LOCK_KEY,
    RELEASE_EDITABLE_STATUSES,
    RELEASE_MARK_VERIFIABLE_STATUSES,
    RELEASE_STATUS_ACTIVE,
    RELEASE_STATUS_ARCHIVED,
    RELEASE_STATUS_BACKFILLED,
    RELEASE_STATUS_VERIFIED,
)
from src.services.catalog.display.placement_service import StorefrontPlacementService
from src.services.catalog.display.reconciler import StorefrontMappingReconciler
from src.utils.datetime_fmt import utc_now_naive


class StorefrontReleaseError(Exception):
    pass


class StorefrontReleaseService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = StorefrontMappingRepository(session)
        self.placements = StorefrontPlacementService(session)
        self.reconciler = StorefrontMappingReconciler(session)

    # Требует editable release для mutation nodes/rules.
    def assert_editable(self, release: StorefrontMappingRelease) -> None:
        if release.status not in RELEASE_EDITABLE_STATUSES:
            raise StorefrontReleaseError(
                f"Release {release.id} status={release.status} не редактируется"
            )

    # Активирует verified release под advisory lock.
    async def activate_release(self, release_id: int) -> StorefrontMappingRelease:
        await self.session.execute(
            text("SELECT pg_advisory_xact_lock(:key)"),
            {"key": RELEASE_ACTIVATION_LOCK_KEY},
        )
        release = await self.repo.get_release(release_id)
        if release is None:
            raise StorefrontReleaseError(f"Release {release_id} не найден")
        if release.status != RELEASE_STATUS_VERIFIED or release.dirty_at is not None:
            raise StorefrontReleaseError(f"Release {release_id} не verified или dirty")
        report = await self.reconciler.run(release_id)
        if report.blocks_activation:
            raise StorefrontReleaseError(f"Activation gate failed: {report}")
        await self.repo.archive_active_release()
        release.status = RELEASE_STATUS_ACTIVE
        release.activated_at = utc_now_naive()
        await self.session.flush()
        return release

    # Помечает release verified после backfill.
    async def mark_verified(self, release_id: int) -> StorefrontMappingRelease:
        release = await self.repo.get_release(release_id)
        if release is None:
            raise StorefrontReleaseError(f"Release {release_id} не найден")
        if release.status not in RELEASE_MARK_VERIFIABLE_STATUSES:
            raise StorefrontReleaseError(
                f"Release {release_id} status={release.status}: "
                "verify разрешён только после backfill (backfilled/verified_dirty)"
            )
        report = await self.reconciler.run(release_id)
        if report.blocks_activation:
            raise StorefrontReleaseError(f"Verify failed: {report}")
        release.status = RELEASE_STATUS_VERIFIED
        release.verified_at = utc_now_naive()
        release.dirty_at = None
        await self.session.flush()
        return release

    # Клонирует archived release config в новый draft.
    async def clone_release(
        self, source_release_id: int, comment: str | None = None
    ) -> StorefrontMappingRelease:
        source = await self.repo.get_release(source_release_id)
        if source is None:
            raise StorefrontReleaseError(f"Release {source_release_id} не найден")
        if source.status != RELEASE_STATUS_ARCHIVED:
            raise StorefrontReleaseError("Clone только из archived release")

        draft = await self.repo.create_draft_release(
            comment=comment or f"clone from {source_release_id}",
            cloned_from_release_id=source_release_id,
        )
        nodes_result = await self.session.execute(
            select(StorefrontNode)
            .where(StorefrontNode.release_id == source_release_id)
            .order_by(StorefrontNode.id)
        )
        old_nodes = list(nodes_result.scalars().all())
        id_map: dict[int, int] = {}
        for _pass in range(3):
            for old in old_nodes:
                if old.id in id_map:
                    continue
                if old.parent_id is not None and old.parent_id not in id_map:
                    continue
                new_node = StorefrontNode(
                    release_id=draft.id,
                    display_key=old.display_key,
                    sport_type=old.sport_type,
                    parent_id=id_map.get(old.parent_id) if old.parent_id else None,
                    node_type=old.node_type,
                    slug=old.slug,
                    label_ru=old.label_ru,
                    sort_order=old.sort_order,
                    active=old.active,
                    metadata_json=old.metadata_json,
                )
                self.session.add(new_node)
                await self.session.flush()
                id_map[old.id] = new_node.id

        rules_result = await self.session.execute(
            select(StorefrontMappingRule).where(
                StorefrontMappingRule.release_id == source_release_id
            )
        )
        for old_rule in rules_result.scalars().all():
            new_node_id = (
                id_map.get(old_rule.storefront_node_id)
                if old_rule.storefront_node_id
                else None
            )
            self.session.add(
                StorefrontMappingRule(
                    release_id=draft.id,
                    storefront_node_id=new_node_id,
                    sport_type=old_rule.sport_type,
                    category_l1=old_rule.category_l1,
                    category_l2=old_rule.category_l2,
                    category_l3=old_rule.category_l3,
                    match_mode=old_rule.match_mode,
                    priority=old_rule.priority,
                    active=old_rule.active,
                    outcome=old_rule.outcome,
                    comment=old_rule.comment,
                )
            )
        await self.session.flush()
        return draft

    # Rollback: clone archived → backfill → verify → activate.
    async def rollback_from_archived(
        self, archived_release_id: int
    ) -> StorefrontMappingRelease:
        draft = await self.clone_release(archived_release_id, comment="rollback")
        await self.placements.backfill_release(draft.id)
        release = await self.repo.get_release(draft.id)
        if release is not None:
            release.status = RELEASE_STATUS_BACKFILLED
            await self.session.flush()
        await self.mark_verified(draft.id)
        return await self.activate_release(draft.id)
