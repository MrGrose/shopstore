import logging
from typing import Any

from src.jobs.dom_enqueue_lock import release_dom_enqueue_locks
from src.jobs.dom_observability import dom_chunk_context, log_dom_chunk_start
from src.jobs.dom_processing_claim import (
    filter_held_dom_processing_products,
    release_dom_processing_claims_by_products,
)
from src.repositories.session import async_session_maker
from src.schemas.catalog_import import ProductImportList
from src.services.catalog.importing.coordinator import ProductImportService
from src.services.catalog.importing.dom_status import (
    dom_error_counts,
    record_dom_status,
    split_terminal_dom_failures,
)
from src.services.catalog.read.caches import (
    invalidate_catalog_read_caches,
    invalidate_if_catalog_boundary_changed,
)

logger = logging.getLogger(__name__)


# Снимает Redis lock и DB claim независимо; возвращает ошибки release.
async def _release_dom_chunk_claims(
    products_chunk: list[dict],
    owner_token: str | None = None,
) -> list[BaseException]:
    errors: list[BaseException] = []
    try:
        release_dom_enqueue_locks(products_chunk, owner_token)
    except Exception as exc:
        logger.exception("DOM chunk: не удалось снять Redis enqueue lock")
        errors.append(exc)
    try:
        await release_dom_processing_claims_by_products(products_chunk, owner_token)
    except Exception as exc:
        logger.exception("DOM chunk: не удалось снять DB dom_processing claim")
        errors.append(exc)
    return errors


# Инвалидирует read-кэши при смене storefront boundary после DOM import.
def _invalidate_dom_import_stock_boundary(
    import_result: dict[str, int | list[int]],
) -> None:
    raw = import_result.get("stock_boundary_flipped_ids")
    flipped = [int(pid) for pid in raw] if isinstance(raw, list) else []
    invalidate_if_catalog_boundary_changed(
        flipped,
        reason="dom_stock_boundary",
    )


# Импортирует напрямую переданный чанк товаров.
def _run_import(
    products: list[dict],
    deactivate_missing: bool,
    download_images: bool,
) -> dict[str, int | list[int]]:
    payload = ProductImportList.from_raw_products(products)
    import asyncio

    async def _run() -> dict[str, int | list[int]]:
        async with async_session_maker() as session:
            svc = ProductImportService(session)
            return await svc.import_products(
                payload,
                download_images=download_images,
                deactivate_missing=deactivate_missing,
            )

    return asyncio.run(_run())


# Импортирует чанк товаров из RQ (GraphQL parser).
def run_catalog_import_chunk(
    products_chunk: list[dict],
    deactivate_missing: bool = False,
    download_images: bool = False,  # fail-safe; scraper передаёт env
) -> dict[str, int | list[int]]:
    return _run_import(
        products=products_chunk,
        deactivate_missing=deactivate_missing,
        download_images=download_images,
    )


# Обогащает напрямую переданный чанк товаров.
def run_catalog_dom_enrichment_chunk(
    products_chunk: list[dict],
    download_images: bool = False,
    owner_token: str | None = None,
) -> dict[str, Any]:
    import asyncio

    async def _run() -> dict[str, Any]:
        from src.scraper.config.config import ParseConfig
        from src.scraper.config.settings import load_settings
        from src.scraper.dom_session import DomSession, open_dom_chunk
        from src.scraper.enrichment.product_dom import enrich_products_with_dom
        from src.scraper.infrastructure.browser_manager import (
            BrowserManager,
            build_recovery_proxy_pool,
        )

        env = load_settings()
        config = ParseConfig(headless=env.headless, require_storage_state=True)
        recovery_proxy_pool = build_recovery_proxy_pool(env)
        session = None
        session_closed = False
        metrics: dict[str, Any] = {}
        failed_products: list[dict] = []
        locks_released = False
        job_error: BaseException | None = None
        work_chunk = products_chunk
        try:
            work_chunk = await filter_held_dom_processing_products(
                products_chunk, owner_token
            )
            skipped_claim = len(products_chunk) - len(work_chunk)
            if skipped_claim:
                logger.warning(
                    "DOM chunk: пропуск %s SKU без живого claim (token=%s)",
                    skipped_claim,
                    "on" if owner_token else "off",
                )
            if not work_chunk:
                return {
                    "created": 0,
                    "updated": 0,
                    "skipped": skipped_claim,
                    "deactivated": 0,
                    "total": 0,
                    "success": 0,
                    "failed": 0,
                }
            chunk_ids = sorted(
                int(p["id"]) for p in work_chunk if p.get("id") is not None
            )
            lane_id = (env.lane_id or "").strip() or None
            with dom_chunk_context(owner_token=owner_token, lane_id=lane_id):
                log_dom_chunk_start(
                    chunk_ids,
                    owner_token=owner_token,
                    lane_id=lane_id,
                )
                session = await open_dom_chunk(env, config)
                try:
                    metrics = await enrich_products_with_dom(
                        work_chunk,
                        env,
                        session.ctx,
                        session=session,
                        pass_label="primary",
                        fail_fast_on_empty_batch=False,
                        raise_on_low_success=False,
                        update_prices=True,
                        http_first=True,
                    )
                    raw_failed = metrics.pop("failed_products", [])
                    failed_products = (
                        list(raw_failed) if isinstance(raw_failed, list) else []
                    )
                    terminal_failed: list[dict] = []
                    failed_products, terminal_failed = split_terminal_dom_failures(
                        failed_products
                    )
                    if terminal_failed:
                        logger.info(
                            "DOM recovery: пропуск terminal not_found=%s",
                            len(terminal_failed),
                        )
                    metrics["recovery_total"] = 0
                    metrics["recovery_success"] = 0
                    metrics["recovery_failed"] = 0
                    primary_failed_counts = dom_error_counts(failed_products)
                    if failed_products:
                        logger.info(
                            "DOM recovery: повтор на том же ctx, "
                            "товаров=%s, причины=%s",
                            len(failed_products),
                            primary_failed_counts,
                        )
                        recovery_metrics = await enrich_products_with_dom(
                            failed_products,
                            env,
                            session.ctx,
                            session=session,
                            pass_label="recovery",
                            fail_fast_on_empty_batch=False,
                            raise_on_low_success=False,
                            update_prices=True,
                            http_first=False,
                        )
                        recovery_failed = recovery_metrics.pop("failed_products", [])
                        failed_products = list(recovery_failed)
                        metrics = {
                            "total": metrics["total"],
                            "success": metrics["success"] + recovery_metrics["success"],
                            "failed": len(recovery_failed),
                            "recovery_total": recovery_metrics["total"],
                            "recovery_success": recovery_metrics["success"],
                            "recovery_failed": recovery_metrics["failed"],
                        }
                    chunk_extra: dict[str, str | int] = {"pass": "chunk"}
                    lane_id = (env.lane_id or "").strip()
                    if lane_id:
                        chunk_extra["lane_id"] = lane_id
                    throttle = (
                        session.throttle if isinstance(session, DomSession) else None
                    )
                    if throttle is not None:
                        chunk_extra["throttle_cooldowns"] = throttle._cooldowns_used
                        chunk_extra["throttle_mode"] = throttle.mode
                        chunk_extra["lane_429_cooldowns"] = (
                            throttle._lane_cooldowns_used
                        )
                        chunk_extra["consecutive_429"] = throttle.consecutive_429
                    else:
                        chunk_extra["throttle_cooldowns"] = 0
                        chunk_extra["throttle_mode"] = "off"
                    session.telemetry.log_dom_chunk(chunk_extra)
                    if failed_products and recovery_proxy_pool:
                        await session.close()
                        session_closed = True
                        manager = BrowserManager(config)
                        logger.info(
                            "DOM recovery proxy: повтор через recovery proxy, "
                            "товаров=%s, "
                            "причины=%s",
                            len(failed_products),
                            dom_error_counts(failed_products),
                        )
                        ctx = await manager.launch_browser(
                            proxy_pool=recovery_proxy_pool
                        )
                        try:
                            proxy_metrics = await enrich_products_with_dom(
                                failed_products,
                                env,
                                ctx,
                                pass_label="recovery_proxy",
                                fail_fast_on_empty_batch=False,
                                raise_on_low_success=False,
                                update_prices=True,
                                http_first=False,
                            )
                            proxy_failed = proxy_metrics.pop("failed_products", [])
                            failed_products = list(proxy_failed)
                            metrics["success"] = int(metrics["success"]) + int(
                                proxy_metrics["success"]
                            )
                            metrics["failed"] = len(proxy_failed)
                            prev_total = int(metrics.get("recovery_total") or 0)
                            metrics["recovery_total"] = prev_total + int(
                                proxy_metrics["total"]
                            )
                            prev_ok = int(metrics.get("recovery_success") or 0)
                            metrics["recovery_success"] = prev_ok + int(
                                proxy_metrics["success"]
                            )
                            prev_fail = int(metrics.get("recovery_failed") or 0)
                            metrics["recovery_failed"] = prev_fail + len(proxy_failed)
                        finally:
                            await manager.close_browser()
                    if terminal_failed:
                        failed_products = list(failed_products) + terminal_failed
                    logger.info(
                        "DOM chunk: всего=%s успешно=%s ошибок=%s "
                        "recovery_всего=%s recovery_успешно=%s recovery_ошибок=%s "
                        "причины_ошибок=%s",
                        metrics["total"],
                        metrics["success"],
                        metrics["failed"],
                        metrics.get("recovery_total", 0),
                        metrics.get("recovery_success", 0),
                        metrics.get("recovery_failed", 0),
                        dom_error_counts(failed_products),
                    )
                finally:
                    if session is not None and not session_closed:
                        await session.close()

                enriched_products = [
                    product
                    for product in work_chunk
                    if product.get("import_source") == "dom"
                ]
                await record_dom_status(
                    success_products=enriched_products,
                    failed_products=failed_products,
                )
                if not enriched_products:
                    return {
                        "created": 0,
                        "updated": 0,
                        "skipped": 0,
                        "deactivated": 0,
                        **metrics,
                    }
                async with async_session_maker() as session:
                    svc = ProductImportService(session)
                    result = await svc.import_products(
                        ProductImportList.from_raw_products(enriched_products),
                        download_images=download_images,
                        deactivate_missing=False,
                    )
                _invalidate_dom_import_stock_boundary(result)
                return {**result, **metrics}
        except BaseException as exc:
            job_error = exc
            raise
        finally:
            if not locks_released:
                release_errors = await _release_dom_chunk_claims(
                    work_chunk, owner_token
                )
                locks_released = True
                if release_errors and job_error is None:
                    raise release_errors[0]

    return asyncio.run(_run())


# После полного цикла парсинга: деактивировать товары, не попавшие в снимок.
def run_catalog_deactivate_missing(
    external_ids: list[str],
    urls: list[str],
    top_categories: list[str],
) -> dict[str, int]:
    import asyncio

    async def _run() -> dict[str, int]:
        async with async_session_maker() as session:
            svc = ProductImportService(session)
            deactivated = await svc.deactivate_missing_from_snapshot(
                incoming_external_ids=set(external_ids),
                incoming_urls=set(urls),
                incoming_top_categories=set(top_categories),
            )
            await session.commit()
            return {
                "created": 0,
                "updated": 0,
                "skipped": 0,
                "deactivated": deactivated,
            }

    result = asyncio.run(_run())
    invalidate_catalog_read_caches(reason="catalog_finalize")
    return result
