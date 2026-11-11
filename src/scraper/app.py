import argparse
import asyncio
import logging
import time
from typing import Any

from rq import Queue
from rq.registry import FailedJobRegistry, StartedJobRegistry

from src.jobs.admin_job_snapshots import (
    PARSER_NIGHTLY_SNAPSHOT,
    save_admin_job_snapshot,
)
from src.jobs.queue import (
    get_catalog_dom_queue,
    get_catalog_finalize_queue,
    get_catalog_import_queue,
)
from src.scraper.config.settings import Settings, load_settings
from src.scraper.snapshots.catalog_snapshot import (
    ScrapeCatalogSnapshot,
    fetch_live_graphql_snapshot,
)
from src.scraper.sources.collection_dom import fetch_all_collection_dom_products
from src.scraper.sources.graphql_catalog import fetch_collection_products_page

logger = logging.getLogger(__name__)


# Парсит GraphQL и добавляет в очередь импорт.
async def _parse_graphql_and_enqueue_chunks(
    collection_url: str,
    env: Settings,
    snapshot: ScrapeCatalogSnapshot,
    skip_dom: bool = False,
) -> tuple[int, int, int]:
    logger.info("GraphQL режим: старт сбора для %s", collection_url)
    queue = get_catalog_import_queue()
    dom_queue = get_catalog_dom_queue()
    total_seen = 0
    page_no = 0
    cursor: str | None = None
    has_next = True
    pending: list[dict] = []
    enqueued_chunks = 0
    enqueued_dom_jobs = 0
    chunk_size = max(1, env.import_chunk_size)

    # Добавляет чанк в очередь импорт.
    def _enqueue_base_chunk(chunk: list[dict]) -> None:
        nonlocal enqueued_chunks, enqueued_dom_jobs
        if not chunk:
            return
        for product in chunk:
            product["import_source"] = "graphql_base"
        snapshot.absorb_chunk(chunk)
        job = queue.enqueue(
            env.catalog_import_func,
            chunk,
            False,
            env.import_download_images,
            job_timeout=env.catalog_job_timeout,
        )
        enqueued_chunks += 1
        logger.info(
            "GraphQL-база: задача в очереди, размер=%s (id=%s), всего_чанков=%s",
            len(chunk),
            job.id,
            enqueued_chunks,
        )
        if not skip_dom:
            dom_job = dom_queue.enqueue(
                env.catalog_dom_enrichment_func,
                chunk,
                env.import_download_images,
                depends_on=job,
                job_timeout=env.catalog_dom_job_timeout,
            )
            enqueued_dom_jobs += 1
            logger.info(
                "DOM-обогащение: задача в очереди, размер=%s (id=%s), всего=%s",
                len(chunk),
                dom_job.id,
                enqueued_dom_jobs,
            )

    while has_next:
        products_page, cursor, has_next = await asyncio.to_thread(
            fetch_collection_products_page,
            endpoint=env.storefront_graphql_endpoint,
            token=env.storefront_access_token,
            collection_url=collection_url,
            cursor=cursor,
            base_url=env.base_url,
            user_agent=env.user_agent,
            timeout_seconds=env.graphql_timeout_seconds,
        )
        page_no += 1
        if env.max_products:
            remaining = max(0, env.max_products - total_seen)
            products_page = products_page[:remaining]
        total_seen += len(products_page)
        pending.extend(products_page)
        logger.info(
            "GraphQL: страница %s получена, товаров=%s, всего=%s, в_буфере=%s",
            page_no,
            len(products_page),
            total_seen,
            len(pending),
        )
        while len(pending) >= chunk_size:
            chunk = pending[:chunk_size]
            del pending[:chunk_size]
            logger.info("GraphQL-база: подготовка чанка, размер=%s", len(chunk))
            _enqueue_base_chunk(chunk)
        if env.max_products and total_seen >= env.max_products:
            logger.info("GraphQL: достигнут max_products=%s", env.max_products)
            break

    if pending:
        logger.info(
            "GraphQL-база: подготовка финального чанка, размер=%s",
            len(pending),
        )
        _enqueue_base_chunk(pending)
        pending.clear()

    if not enqueued_chunks:
        logger.warning("GraphQL: пустой payload для %s", collection_url)
        return 0, 0, 0
    logger.info(
        "GraphQL-база: импорт разбит на %s задач, всего=%s, размер_чанка=%s для %s",
        enqueued_chunks,
        total_seen,
        chunk_size,
        collection_url,
    )
    return enqueued_chunks, enqueued_dom_jobs, total_seen


# Ожидает очередь пуста.
async def _wait_queue_idle(env: Settings, queue: Queue, label: str) -> None:
    deadline = time.monotonic() + env.catalog_drain_timeout_seconds
    poll = env.catalog_drain_poll_seconds
    while time.monotonic() < deadline:
        started = StartedJobRegistry(queue=queue).count
        if queue.count == 0 and started == 0:
            failed = FailedJobRegistry(queue=queue).count
            if failed:
                logger.warning(
                    "Очередь %s пуста, но в реестре ошибок %s задач(и)",
                    label,
                    failed,
                )
            return
        await asyncio.sleep(poll)
    raise TimeoutError(
        f"Таймаут ожидания очереди {label} ({env.catalog_drain_timeout_seconds}s)"
    )


# Добавляет в очередь деактивацию пропавших товаров.
def _enqueue_deactivate_missing(env: Settings, snapshot: ScrapeCatalogSnapshot) -> None:
    if not env.finalize_missing:
        logger.info("Деактивация пропавших отключена (SCRAPER_FINALIZE_MISSING=false).")
        return
    if not snapshot.top_categories:
        logger.warning("Пропуск деактивации: в снимке нет sport_type.")
        return
    if not snapshot.has_catalog_data:
        logger.warning("Пропуск деактивации: снимок каталога пуст.")
        return
    if not snapshot.complete:
        logger.warning(
            "Finalize пропущен: GraphQL-снимок неполный "
            "(пагинация не дошла до конца или сработал max_products). "
            "Товары не снимаем."
        )
        return
    queue = get_catalog_finalize_queue()
    job = queue.enqueue(
        env.catalog_finalize_func,
        list(snapshot.external_ids),
        list(snapshot.urls),
        list(snapshot.top_categories),
        job_timeout=env.catalog_finalize_job_timeout,
    )
    logger.info(
        "Деактивация в очереди id=%s: категорий=%s, external_id=%s, url=%s, "
        "complete=%s, fetched=%s",
        job.id,
        len(snapshot.top_categories),
        len(snapshot.external_ids),
        len(snapshot.urls),
        snapshot.complete,
        snapshot.products_fetched,
    )


# Собирает итог цикла парсера для snapshot админки.
def _scrape_cycle_result(
    import_chunks: int,
    dom_jobs: int,
    collection_errors: int,
    finalize_ran: bool,
    graphql_only: bool,
    skip_dom: bool,
    reason: str | None = None,
) -> dict[str, Any]:
    return {
        "ok": import_chunks > 0 and collection_errors == 0,
        "import_chunks": import_chunks,
        "dom_jobs": dom_jobs,
        "finalize_ran": finalize_ran,
        "collection_errors": collection_errors,
        "graphql_only": graphql_only,
        "skip_dom": skip_dom,
        "reason": reason,
    }


# Один проход по всем коллекциям: парсинг, импорт чанков, деактивация пропавших.
async def run_scrape_cycle(*, graphql_only: bool = False) -> dict[str, Any]:
    env = load_settings()
    urls = env.get_collection_urls()
    snapshot = ScrapeCatalogSnapshot()
    import_chunks = 0
    dom_jobs = 0
    collection_errors = 0
    skip_dom = True
    if graphql_only:
        mode = "GraphQL без finalize"
    else:
        mode = "GraphQL + finalize (DOM через scheduler)"
    logger.info(
        "Старт цикла парсинга (%s, %s коллекции).",
        mode,
        len(urls),
    )
    if skip_dom and not graphql_only:
        logger.info(
            "DOM enqueue при parser отключён; stock/price — через dom_scheduler."
        )
    # Listing href/?variant= discovery; в import available/qty не пишет.
    if not graphql_only:
        try:
            await fetch_all_collection_dom_products(urls, env)
        except Exception:
            logger.exception("DOM-листинг коллекций: не удалось собрать данные")
    for collection_url in urls:
        try:
            (
                collection_import_chunks,
                collection_dom_jobs,
                _collection_products,
            ) = await _parse_graphql_and_enqueue_chunks(
                collection_url,
                env,
                snapshot,
                skip_dom=skip_dom,
            )
            import_chunks += collection_import_chunks
            dom_jobs += collection_dom_jobs
        except Exception:
            collection_errors += 1
            logger.exception("Сбой парсинга/очереди для %s", collection_url)
    if not import_chunks:
        logger.warning("Цикл завершён без задач импорта — деактивация не выполняется.")
        return _scrape_cycle_result(
            import_chunks=0,
            dom_jobs=dom_jobs,
            collection_errors=collection_errors,
            finalize_ran=False,
            graphql_only=graphql_only,
            skip_dom=skip_dom,
            reason="no_import_chunks",
        )
    if skip_dom:
        logger.info(
            "GraphQL-база: завершено (%s чанков), DOM enqueue=0.",
            import_chunks,
        )
    else:
        logger.info(
            "GraphQL-база: завершено (%s чанков), DOM поставлен в очередь (%s чанков).",
            import_chunks,
            dom_jobs,
        )
    logger.info("Ожидание catalog_import перед финализацией пропавших товаров...")
    await _wait_queue_idle(env, get_catalog_import_queue(), "catalog_import")
    finalize_ran = False
    if graphql_only:
        logger.info("GraphQL без finalize: finalize пропущен.")
    elif collection_errors:
        logger.warning(
            "Finalize пропущен: %s коллекций завершились с ошибкой — "
            "товары не снимаем.",
            collection_errors,
        )
    else:
        logger.info("Finalize: сверка со свежим GraphQL-снимком каталога поставщика...")
        try:
            live_snapshot = await fetch_live_graphql_snapshot(env, urls)
        except Exception:
            logger.exception(
                "Finalize пропущен: не удалось получить свежий GraphQL-снимок — "
                "товары не снимаем."
            )
        else:
            ids_before = len(live_snapshot.external_ids)
            _enqueue_deactivate_missing(env, live_snapshot)
            await _wait_queue_idle(
                env, get_catalog_finalize_queue(), "catalog_finalize"
            )
            finalize_ran = True
            logger.info(
                "Finalize: сверка завершена, в снимке %s external_id, %s url.",
                ids_before,
                len(live_snapshot.urls),
            )
    logger.info(
        "Цикл парсинга завершён: базовый импорт%s. "
        "DOM-обогащение продолжит выполняться в catalog_dom.",
        " и finalize" if finalize_ran else " (finalize не выполнялся — снятий нет)",
    )
    return _scrape_cycle_result(
        import_chunks=import_chunks,
        dom_jobs=dom_jobs,
        collection_errors=collection_errors,
        finalize_ran=finalize_ran,
        graphql_only=graphql_only,
        skip_dom=skip_dom,
    )


# Бесконечный режим (локальная отладка): sleep между циклами.
async def main(*, loop_forever: bool, graphql_only: bool = False) -> None:
    while True:
        result = await run_scrape_cycle(graphql_only=graphql_only)
        save_admin_job_snapshot(PARSER_NIGHTLY_SNAPSHOT, result)
        if not loop_forever:
            break
        interval = load_settings().loop_interval_seconds
        logger.info("Следующий запуск через %s секунд.", interval)
        await asyncio.sleep(interval)


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Парсер - очередь RQ catalog (импорт обрабатывает worker).",
    )
    p.add_argument(
        "--once",
        action="store_true",
        help="Один проход по коллекциям и выход.",
    )
    p.add_argument(
        "--graphql-only",
        action="store_true",
        help="Только GraphQL import: без DOM и без finalize.",
    )
    return p.parse_args()


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    args = _parse_args()
    asyncio.run(main(loop_forever=not args.once, graphql_only=args.graphql_only))
