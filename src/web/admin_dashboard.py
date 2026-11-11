import logging
import time
from datetime import timedelta
from decimal import Decimal
from typing import Any

from redis import Redis  # type: ignore[import-untyped]
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.core.config import settings as app_settings
from src.jobs.queue import get_catalog_queue_stats, get_scraper_run_status
from src.models.order import Order
from src.models.product import Product
from src.repositories.order_repo import CrudOrder
from src.services.catalog.importing.product_complete import (
    enrichment_hold_sql_criterion,
)
from src.services.catalog.read.caches import invalidate_catalog_read_caches
from src.services.catalog.read.scope import CATALOG_ALL_TOP_CATEGORY, CATALOG_TOP_ORDER
from src.services.pricing_service import PricingService
from src.utils.datetime_fmt import format_datetime_msk, utc_now_naive
from src.web.admin_labels import ADMIN_ORDER_QUEUE_KEYS
from src.web.parsing_health import format_relative_age
from src.web.storefront_spa import spa_index_path

logger = logging.getLogger(__name__)

_ORDER_QUEUE_FOOT_LABELS: dict[str, str] = {
    "availability": "наличие",
    "assembling": "сборка",
    "tracking": "трек",
}


# Подпись под метрикой заказов: разбивка по очередям или «очередь пуста».
def _orders_action_foot(queues: dict[str, int]) -> str:
    parts: list[str] = []
    for key in ADMIN_ORDER_QUEUE_KEYS:
        count = int(queues.get(key) or 0)
        if count:
            parts.append(f"{count} {_ORDER_QUEUE_FOOT_LABELS[key]}")
    return " · ".join(parts) if parts else "очередь пуста"


# Одна строка этапа парсинга: label, pill status, detail, icon.
def _step_snapshot(
    *,
    pending: int,
    running: int,
    failed: int,
    label: str,
    icon: str,
    product_errors: int = 0,
) -> dict[str, str]:
    if failed > 0:
        return {
            "label": label,
            "status": "err",
            "detail": f"ошибки · {failed}",
            "icon": icon,
        }
    if running > 0:
        return {
            "label": label,
            "status": "warn",
            "detail": "идёт",
            "icon": icon,
        }
    if pending > 0:
        return {
            "label": label,
            "status": "warn",
            "detail": f"очередь · {pending}",
            "icon": icon,
        }
    if product_errors > 0:
        return {
            "label": label,
            "status": "err",
            "detail": f"ошибки · {product_errors} товаров",
            "icon": icon,
        }
    return {
        "label": label,
        "status": "ok",
        "detail": "готово",
        "icon": icon,
    }


# Сводка пайплайна каталога: импорт → DOM → публикация.
def _parsing_pipeline(
    stats: dict[str, Any],
    dom_errors: int = 0,
    workers: dict[str, Any] | None = None,
    run_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    import_pending = int(stats.get("pending_jobs") or 0)
    import_run = int(stats.get("running_jobs") or 0)
    import_failed = int(stats.get("failed_jobs") or 0)
    dom_pending = int(stats.get("dom_pending_jobs") or 0)
    dom_run = int(stats.get("dom_running_jobs") or 0)
    dom_failed = int(stats.get("dom_failed_jobs") or 0)
    finalize_pending = int(stats.get("finalize_pending_jobs") or 0)
    finalize_run = int(stats.get("finalize_running_jobs") or 0)
    finalize_failed = int(stats.get("finalize_failed_jobs") or 0)
    translation_pending = int(stats.get("translation_pending_jobs") or 0)
    translation_run = int(stats.get("translation_running_jobs") or 0)
    translation_failed = int(stats.get("translation_failed_jobs") or 0)
    products_pending = int(stats.get("estimated_products_pending") or 0)
    products_active = int(stats.get("estimated_products_in_progress") or 0)
    chunk_size = int(stats.get("import_chunk_size") or 10)
    wrk = workers or {}
    rs = run_status or {}

    pipeline_running = import_run + dom_run + finalize_run + translation_run > 0
    queue_total = import_pending + dom_pending + finalize_pending + translation_pending
    jobs_failed = import_failed + dom_failed + finalize_failed + translation_failed

    stage_defs = [
        ("import", "Импорт", "import", import_pending, import_run, import_failed, 0),
        (
            "dom",
            "Catalog DOM",
            "processes",
            dom_pending,
            dom_run,
            dom_failed,
            dom_errors,
        ),
        (
            "finalize",
            "Финализация",
            "box",
            finalize_pending,
            finalize_run,
            finalize_failed,
            0,
        ),
        (
            "translation",
            "Перевод",
            "translate",
            translation_pending,
            translation_run,
            translation_failed,
            0,
        ),
    ]
    steps = []
    stages = []
    for key, label, icon, pending, running, failed, product_errors in stage_defs:
        step = _step_snapshot(
            pending=pending,
            running=running,
            failed=failed,
            label=label,
            icon=icon,
            product_errors=product_errors,
        )
        steps.append(step)
        worker = wrk.get(key) or {"alive": False, "count": 0}
        blocked = False
        if key == "dom":
            blocked = bool(rs.get("dom_queue_overloaded"))
        elif pending > 0 and not worker.get("alive"):
            blocked = True
        est_skus = (
            (pending + running) * chunk_size
            if key not in {"finalize", "translation"}
            else None
        )
        stages.append(
            {
                "key": key,
                "label": label,
                "icon": icon,
                "pending": pending,
                "running": running,
                "failed": failed,
                "estimated_skus": est_skus,
                "worker": worker,
                "status": step["status"],
                "detail": step["detail"],
                "blocked": blocked,
            }
        )

    if dom_errors > 0 or jobs_failed > 0:
        overall_label = "Есть проблемы"
        overall_pill = "err"
    elif pipeline_running:
        overall_label = "Идёт обработка"
        overall_pill = "warn"
    elif queue_total > 0:
        overall_label = "В очереди"
        overall_pill = "warn"
    else:
        overall_label = "Всё в порядке"
        overall_pill = "ok"

    return {
        "pipeline_running": pipeline_running,
        "queue_total": queue_total,
        "products_pending": products_pending,
        "products_active": products_active,
        "jobs_failed": jobs_failed,
        "dom_errors": dom_errors,
        "steps": steps,
        "stages": stages,
        "overall_label": overall_label,
        "overall_pill": overall_pill,
    }


# Фильтры выборки товаров с DOM-ошибкой.
def _failed_dom_filters(
    error_filter: str | None,
    retry_only: bool,
    max_attempts: int | None,
    hold_only: bool = False,
) -> list[Any]:
    filters: list[Any] = [Product.dom_last_error.isnot(None)]
    if error_filter:
        filters.append(Product.dom_last_error == error_filter)
    if hold_only and max_attempts is not None:
        filters.append(enrichment_hold_sql_criterion(max_attempts))
    elif retry_only and max_attempts is not None:
        filters.extend(
            [
                Product.dom_attempts < max(1, max_attempts),
                Product.dom_last_error != "not_found",
            ]
        )
    return filters


# Товары с dom_last_error для таблицы на странице парсинга.
async def load_failed_dom_products(
    db: AsyncSession,
    limit: int = 30,
    offset: int = 0,
    error_filter: str | None = None,
    retry_only: bool = False,
    hold_only: bool = False,
    max_attempts: int | None = None,
) -> list[Product]:
    filters = _failed_dom_filters(
        error_filter, retry_only, max_attempts, hold_only=hold_only
    )
    rows = await db.scalars(
        select(Product)
        .where(*filters)
        .order_by(Product.dom_last_attempt_at.desc().nullslast(), Product.id.desc())
        .offset(max(0, offset))
        .limit(max(1, limit))
    )
    return list(rows.all())


# Считает товары с DOM-ошибкой для пагинации.
async def count_failed_dom_products(
    db: AsyncSession,
    error_filter: str | None = None,
    retry_only: bool = False,
    hold_only: bool = False,
    max_attempts: int | None = None,
) -> int:
    filters = _failed_dom_filters(
        error_filter, retry_only, max_attempts, hold_only=hold_only
    )
    return int(await db.scalar(select(func.count(Product.id)).where(*filters)) or 0)


# Топ комбинаций ошибка × sport_type для summary failed products.
async def failed_dom_breakdown_by_sport(
    db: AsyncSession,
    limit: int = 6,
) -> list[dict[str, Any]]:
    rows = await db.execute(
        select(Product.dom_last_error, Product.sport_type, func.count(Product.id))
        .where(Product.dom_last_error.isnot(None))
        .group_by(Product.dom_last_error, Product.sport_type)
        .order_by(func.count(Product.id).desc())
        .limit(max(1, limit))
    )
    return [
        {
            "error": str(error),
            "sport": str(sport or "—"),
            "count": int(count),
        }
        for error, sport, count in rows.all()
        if error
    ]


# Снимает товар с витрины и освобождает DOM claim.
async def deactivate_dom_failed_product(
    db: AsyncSession,
    product_id: int,
) -> str | None:
    product = await db.get(Product, product_id)
    if product is None:
        return "Товар не найден"
    now = utc_now_naive()
    product.is_active = False
    product.deactivated_at = now
    product.dom_last_error = None
    product.dom_processing_at = None
    product.dom_processing_expires_at = None
    product.dom_processing_owner_token = None
    db.add(product)
    await db.commit()
    invalidate_catalog_read_caches(reason="admin_dom_deactivate")
    return None


# Сбрасывает DOM-ошибку и claim — SKU снова eligible для rolling.
async def reset_dom_failed_product(
    db: AsyncSession,
    product_id: int,
) -> str | None:
    product = await db.get(Product, product_id)
    if product is None:
        return "Товар не найден"
    product.dom_last_error = None
    product.dom_attempts = 0
    product.dom_last_attempt_at = None
    product.dom_processing_at = None
    product.dom_processing_expires_at = None
    product.dom_processing_owner_token = None
    db.add(product)
    await db.commit()
    return None


# Массово снимает с витрины active-товары с заданной DOM-ошибкой.
async def bulk_deactivate_by_dom_error(db: AsyncSession, error: str) -> int:
    if not error:
        return 0
    now = utc_now_naive()
    result = await db.execute(
        update(Product)
        .where(
            Product.dom_last_error == error,
            Product.is_active.is_(True),
        )
        .values(
            is_active=False,
            deactivated_at=now,
            dom_last_error=None,
            dom_processing_at=None,
            dom_processing_expires_at=None,
            dom_processing_owner_token=None,
        )
    )
    await db.commit()
    rowcount = int(result.rowcount or 0)
    if rowcount:
        invalidate_catalog_read_caches(reason="admin_bulk_dom_deactivate")
    return rowcount


# Сбрасывает просроченные dom_processing_* метки (зависшие после crash воркера).
async def clear_stuck_dom_claims(db: AsyncSession) -> int:
    now = utc_now_naive()
    result = await db.execute(
        update(Product)
        .where(
            Product.dom_processing_at.isnot(None),
            Product.dom_processing_expires_at <= now,
        )
        .values(
            dom_processing_at=None,
            dom_processing_expires_at=None,
            dom_processing_owner_token=None,
        )
    )
    await db.commit()
    return int(result.rowcount or 0)


# Массово сбрасывает DOM-ошибку у товаров с заданной причиной.
async def bulk_reset_dom_error(db: AsyncSession, error: str) -> int:
    if not error:
        return 0
    result = await db.execute(
        update(Product)
        .where(Product.dom_last_error == error)
        .values(
            dom_last_error=None,
            dom_attempts=0,
            dom_last_attempt_at=None,
            dom_processing_at=None,
            dom_processing_expires_at=None,
            dom_processing_owner_token=None,
        )
    )
    await db.commit()
    return int(result.rowcount or 0)


# Группирует dom_last_error → число товаров.
async def _dom_errors_by_reason(db: AsyncSession) -> dict[str, int]:
    rows = await db.execute(
        select(Product.dom_last_error, func.count(Product.id))
        .where(Product.dom_last_error.isnot(None))
        .group_by(Product.dom_last_error)
        .order_by(func.count(Product.id).desc())
    )
    return {str(reason): int(count) for reason, count in rows.all() if reason}


# Считает товары с DOM-ошибкой, которые ещё можно повторить.
async def count_retry_eligible_dom_products(
    db: AsyncSession,
    max_attempts: int,
) -> int:
    return int(
        await db.scalar(
            select(func.count(Product.id)).where(
                Product.dom_last_error.isnot(None),
                Product.dom_last_error != "not_found",
                Product.dom_attempts < max(1, max_attempts),
            )
        )
        or 0
    )


# Возраст самой старой DOM-ошибки в каталоге.
async def oldest_dom_error_age(
    db: AsyncSession,
    now,
) -> str | None:
    oldest = await db.scalar(
        select(func.min(Product.dom_last_attempt_at)).where(
            Product.dom_last_error.isnot(None),
            Product.dom_last_attempt_at.isnot(None),
        )
    )
    return format_relative_age(oldest, now)


# Маскирует пароль в Redis URL для админки.
def _mask_redis_url(url: str) -> str:
    if "@" not in url:
        return url
    scheme, rest = url.split("://", 1)
    creds, host = rest.rsplit("@", 1)
    if ":" in creds:
        user = creds.split(":", 1)[0]
        return f"{scheme}://{user}:***@{host}"
    return f"{scheme}://***@{host}"


# Пингует Redis для дашборда парсинга.
def _redis_health_snapshot() -> dict[str, Any]:
    try:
        client = Redis.from_url(
            app_settings.REDIS_URL,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        if client.ping():
            return {"ok": True, "detail": "online", "ping_ok": True}
        return {"ok": False, "detail": "ping false", "ping_ok": False}
    except Exception as exc:
        return {
            "ok": False,
            "detail": str(exc)[:120] or "offline",
            "ping_ok": False,
        }


# Статус Redis для парсинга: ping или косвенно по живым воркерам/очередям RQ.
def redis_parsing_status(
    stats: dict[str, Any],
    workers: dict[str, Any],
) -> dict[str, Any]:
    snap = _redis_health_snapshot()
    url = _mask_redis_url(app_settings.REDIS_URL)
    workers_alive = any(
        (workers.get(role) or {}).get("alive") for role in ("import", "dom", "finalize")
    )
    queue_keys = (
        "pending_jobs",
        "running_jobs",
        "dom_pending_jobs",
        "dom_running_jobs",
        "finalize_pending_jobs",
        "finalize_running_jobs",
    )
    has_queues = any(int(stats.get(key) or 0) > 0 for key in queue_keys)
    if not snap["ok"] and (workers_alive or has_queues):
        return {
            "ok": True,
            "detail": "online (RQ)",
            "ping_ok": False,
            "url": url,
        }
    return {**snap, "url": url}


# Сводка парсинга для /internal/admin/parsing: очереди, rolling, ошибки, алерты.
async def build_parsing_overview(db: AsyncSession) -> dict[str, Any]:
    from src.scraper.config.settings import load_settings
    from src.services.catalog import CatalogService
    from src.web.parsing_health import build_parsing_alert, partition_parsing_alerts
    from src.web.parsing_lanes import build_parsing_lanes_overview
    from src.web.parsing_metrics import build_parsing_ops_metrics, default_parsing_ops

    now = utc_now_naive()
    env = load_settings()
    catalog_summary = await CatalogService(db).get_catalog_admin_summary(
        CATALOG_ALL_TOP_CATEGORY
    )
    in_catalog = int(catalog_summary.get("in_catalog") or 0)
    lanes_overview = build_parsing_lanes_overview(now)
    session_file = lanes_overview["availability"]
    stats = get_catalog_queue_stats()
    run_status = get_scraper_run_status()
    dom_errors = int(
        await db.scalar(
            select(func.count(Product.id)).where(Product.dom_last_error.isnot(None))
        )
        or 0
    )

    stale_hours = max(0, env.dom_refresh_stale_hours)
    stale_before = now - timedelta(hours=stale_hours) if stale_hours > 0 else now
    fresh_filters = [
        Product.is_active.is_(True),
        Product.sport_type.in_(CATALOG_TOP_ORDER),
        Product.catalog_synced_at.isnot(None),
        Product.catalog_synced_at >= stale_before,
    ]
    fresh_count = int(
        await db.scalar(select(func.count(Product.id)).where(*fresh_filters)) or 0
    )
    in_claim = int(
        await db.scalar(
            select(func.count(Product.id)).where(
                Product.dom_processing_at.isnot(None),
                Product.dom_processing_expires_at > now,
            )
        )
        or 0
    )
    stuck_claims = int(
        await db.scalar(
            select(func.count(Product.id)).where(
                Product.dom_processing_at.isnot(None),
                Product.dom_processing_expires_at <= now,
            )
        )
        or 0
    )

    since_1h = now - timedelta(hours=1)
    since_24h = now - timedelta(hours=24)
    synced_1h = int(
        await db.scalar(
            select(func.count(Product.id)).where(Product.catalog_synced_at >= since_1h)
        )
        or 0
    )
    synced_24h = int(
        await db.scalar(
            select(func.count(Product.id)).where(Product.catalog_synced_at >= since_24h)
        )
        or 0
    )

    fresh_pct = round(fresh_count * 100 / in_catalog) if in_catalog else 0
    stale_count = max(0, in_catalog - fresh_count)

    try:
        ops = await build_parsing_ops_metrics(db, env, now)
    except Exception:
        logger.warning(
            "Не удалось собрать ops-метрики парсинга, используем значения по умолчанию"
        )
        ops = default_parsing_ops()

    workers = ops.get("workers") or {}
    parsing = _parsing_pipeline(
        stats,
        dom_errors=dom_errors,
        workers=workers,
        run_status=run_status,
    )

    dom_pending = int(run_status.get("dom_queue_pending") or 0)
    dom_running = int(run_status.get("dom_queue_running") or 0)
    dom_limit = int(run_status.get("dom_queue_max_pending") or 0)
    dom_failed_jobs = int(run_status.get("dom_queue_failed") or 0)
    import_failed = int(run_status.get("import_queue_failed") or 0)
    finalize_failed = int(run_status.get("finalize_queue_failed") or 0)
    translation_failed = int(run_status.get("translation_queue_failed") or 0)
    import_pending = int(run_status.get("import_queue_pending") or 0)
    import_running = int(run_status.get("import_queue_running") or 0)
    finalize_pending = int(run_status.get("finalize_queue_pending") or 0)
    finalize_running = int(run_status.get("finalize_queue_running") or 0)
    dom_queue_busy = dom_pending + dom_running
    import_busy = import_pending + import_running
    finalize_busy = finalize_pending + finalize_running
    translation_pending = int(run_status.get("translation_queue_pending") or 0)
    translation_running = int(run_status.get("translation_queue_running") or 0)
    translation_busy = translation_pending + translation_running

    alerts: list[dict[str, Any]] = []
    if run_status.get("dom_queue_overloaded"):
        alerts.append(
            build_parsing_alert(
                alert_id="dom_queue_overloaded",
                level="warn",
                title="DOM очередь перегружена",
                text=(
                    f"{dom_pending} ожидает, {dom_running} в работе — "
                    f"новые задачи добавятся по мере разгребания (лимит {dom_limit})"
                ),
                cause=(
                    "Rolling scheduler приостановил автодобавление "
                    "при переполнении DOM-очереди"
                ),
                action_hint="Дождитесь разгребания или запустите watchdog вручную",
                priority=40,
            )
        )
    if stuck_claims > 5:
        sku_word = (
            "товар"
            if stuck_claims == 1
            else "товара" if 2 <= stuck_claims <= 4 else "товаров"
        )
        alerts.append(
            build_parsing_alert(
                alert_id="stuck_claims",
                level="info",
                title=f"Служебная метка у {stuck_claims} {sku_word}",
                text=(
                    "Воркер взял товар в работу, но не сбросил claim "
                    "(перезапуск, сбой job). Сейчас job не выполняется."
                ),
                cause="Истёк TTL claim без завершения DOM job",
                action_hint="Очистите метки или дождитесь watchdog",
                priority=70,
                action="clear_stuck_claims",
                action_label="Очистить метки",
            )
        )
    elif stuck_claims > 0:
        alerts.append(
            build_parsing_alert(
                alert_id="stuck_claims_minor",
                level="info",
                title=f"Служебные метки: {stuck_claims}",
                text="Не ошибка парсинга — можно игнорировать или очистить.",
                priority=90,
                banner=False,
            )
        )

    rq_failed_parts: list[str] = []
    if dom_failed_jobs > 0:
        rq_failed_parts.append(f"DOM: {dom_failed_jobs}")
    if import_failed > 0:
        rq_failed_parts.append(f"import: {import_failed}")
    if finalize_failed > 0:
        rq_failed_parts.append(f"finalize: {finalize_failed}")
    if translation_failed > 0:
        rq_failed_parts.append(f"translation: {translation_failed}")
    if rq_failed_parts:
        alerts.append(
            build_parsing_alert(
                alert_id="rq_failed_jobs",
                level="err",
                title="Failed jobs в RQ",
                text=f"{', '.join(rq_failed_parts)}",
                cause="Job упал с исключением и попал в FailedJobRegistry",
                action_hint="Очистите failed jobs или переотправьте через страж DOM",
                priority=5,
                action="clear_failed_jobs",
                action_label="Очистить failed",
            )
        )

    not_found_count = int(
        await db.scalar(
            select(func.count(Product.id)).where(
                Product.dom_last_error == "not_found",
                Product.is_active.is_(True),
            )
        )
        or 0
    )
    if not_found_count > 0:
        alerts.append(
            build_parsing_alert(
                alert_id="not_found_active",
                level="warn",
                title=f"Товаров not_found: {not_found_count}",
                text="Снимите с витрины или дождитесь авто-деактивации",
                cause="Поставщик вернул 404/410 — SKU больше не существует",
                action_hint="Bulk deactivate not_found в таблице ниже",
                priority=35,
            )
        )

    if not session_file["exists"]:
        alerts.append(
            build_parsing_alert(
                alert_id="availability_session_missing",
                level="warn",
                title="Availability session не найдена",
                text="session/storage_state.json отсутствует",
                cause="Нет infrastructure/session/ (make login)",
                action_hint="make login — availability, не DOM lane",
                priority=20,
            )
        )
    elif session_file["status"] == "err":
        alerts.append(
            build_parsing_alert(
                alert_id="availability_session_stale",
                level="warn",
                title=f"Availability session: {session_file['age_hours']}ч",
                text="Файл session/ устарел",
                cause="storage_state.json availability слишком старый",
                action_hint="make login для availability",
                priority=25,
            )
        )

    for lane in lanes_overview.get("lanes", []):
        session = lane.get("session") or {}
        lane_label = lane.get("label") or f"Lane {lane.get('lane_id')}"
        session_dir = session.get("session_dir") or f"session-{lane.get('lane_id')}/"
        if not session.get("exists"):
            alerts.append(
                build_parsing_alert(
                    alert_id=f"dom_lane_session_missing_{lane.get('lane_id')}",
                    level="err",
                    title=f"{lane_label}: session file не найден",
                    text=f"Нет {session_dir}storage_state.json",
                    cause="DOM lane без storage_state",
                    action_hint=f"make login-lane LANE={lane.get('lane_id')}",
                    priority=6,
                )
            )
        elif session.get("status") == "err":
            alerts.append(
                build_parsing_alert(
                    alert_id=f"dom_lane_session_stale_{lane.get('lane_id')}",
                    level="err",
                    title=f"{lane_label}: session {session.get('age_hours')}ч",
                    text="DOM lane session давно не обновлялась",
                    cause=f"Файл {session_dir} устарел",
                    action_hint=f"make login-lane LANE={lane.get('lane_id')}",
                    priority=9,
                )
            )
        elif lane.get("status") == "warn":
            alerts.append(
                build_parsing_alert(
                    alert_id=f"dom_lane_session_warn_{lane.get('lane_id')}",
                    level="warn",
                    title=f"{lane_label}: session {lane.get('age_hours')}ч",
                    text="Пора обновить DOM lane session",
                    cause=f"Файл {lane.get('session_dir')} стареет",
                    action_hint=f"make login-lane LANE={lane.get('lane_id')}",
                    priority=42,
                )
            )

    dom_worker = workers.get("dom") or {}
    import_worker = workers.get("import") or {}
    finalize_worker = workers.get("finalize") or {}
    if dom_queue_busy > 0 and not dom_worker.get("alive"):
        alerts.append(
            build_parsing_alert(
                alert_id="dom_worker_offline",
                level="err",
                title="DOM worker offline при активной очереди",
                text="Jobs не обрабатываются — очередь растёт",
                cause="worker-dom-1/2 остановлен или heartbeat истёк",
                action_hint="restart worker-dom-1 worker-dom-2; смотрите логи",
                priority=2,
            )
        )
    if import_busy > 0 and not import_worker.get("alive"):
        alerts.append(
            build_parsing_alert(
                alert_id="import_worker_offline",
                level="err",
                title="Import worker offline при активной очереди",
                text="Import jobs не обрабатываются",
                cause="worker-import остановлен или heartbeat истёк",
                action_hint="docker compose restart worker-import",
                priority=4,
            )
        )
    if finalize_busy > 0 and not finalize_worker.get("alive"):
        alerts.append(
            build_parsing_alert(
                alert_id="finalize_worker_offline",
                level="err",
                title="Finalize worker offline при активной очереди",
                text="Finalize jobs не обрабатываются",
                cause="worker-finalize остановлен или heartbeat истёк",
                action_hint="docker compose restart worker-finalize",
                priority=4,
            )
        )

    translation_worker = workers.get("translation") or {}
    if translation_busy > 0 and not translation_worker.get("alive"):
        alerts.append(
            build_parsing_alert(
                alert_id="translation_worker_offline",
                level="err",
                title="Translation worker offline при активной очереди",
                text="Translation jobs не обрабатываются",
                cause="worker-translation остановлен или heartbeat истёк",
                action_hint="docker compose restart worker-translation",
                priority=4,
            )
        )

    tel_1h = ops.get("dom_telemetry", {}).get("window_1h") or {}
    challenge_pct = float(tel_1h.get("challenge_ratio_pct") or 0)
    if challenge_pct >= 20:
        alerts.append(
            build_parsing_alert(
                alert_id="challenge_spike",
                level="warn",
                title=f"Challenge ratio {challenge_pct}% за 1 ч",
                text="Риск rate-limit — anti-bot защита активна",
                cause="Cloudflare/captcha/challenge на DOM-запросах",
                action_hint="Обновите сессию, проверьте pacing и proxy",
                priority=30,
            )
        )

    throttle_hits = int(tel_1h.get("throttle_cooldowns") or 0)
    if throttle_hits > 0:
        alerts.append(
            build_parsing_alert(
                alert_id="throttle_cooldown",
                level="info",
                title=f"Throttle cooldown: {throttle_hits} за 1 ч",
                text="Парсер сам замедляется — штатное поведение pacing",
                priority=95,
                banner=False,
            )
        )

    queue_stall = ops.get("queue_stall") or {}
    if queue_stall.get("is_stalled"):
        stall_stage = str(queue_stall.get("stage") or "?")
        idle_min = int(queue_stall.get("idle_minutes") or 0)
        alerts.append(
            build_parsing_alert(
                alert_id="queue_stalled",
                level="warn",
                title=f"Очередь {stall_stage} в застое {idle_min} мин",
                text=(
                    f"Глубина {queue_stall.get('queue_depth') or 0} не меняется — "
                    "возможен stuck worker или anti-bot"
                ),
                cause="Pending/running без прогресса дольше порога",
                action_hint="Проверьте worker logs, watchdog, сессию Playwright",
                priority=12,
            )
        )

    alert_banners, _ = partition_parsing_alerts(alerts)
    rolling = {
        "in_catalog": in_catalog,
        "stale_count": stale_count,
        "fresh_count": fresh_count,
        "fresh_pct": fresh_pct,
        "stale_hours": stale_hours,
        "batch_size": env.dom_rolling_batch_size,
        "in_claim": in_claim,
        "stuck_claims": stuck_claims,
    }
    throughput = {
        "synced_1h": synced_1h,
        "synced_24h": synced_24h,
    }
    session_payload = {
        **session_file,
        "updated_at_msk": (
            format_datetime_msk(session_file["updated_at"], with_tz_label=False)
            if session_file.get("updated_at")
            else None
        ),
    }
    redis = redis_parsing_status(stats, workers)

    return {
        "updated_at": format_datetime_msk(now) or "",
        "run_status": run_status,
        "stats": stats,
        "parsing": parsing,
        "rolling": rolling,
        "throughput": throughput,
        "session_file": session_payload,
        "lanes_overview": lanes_overview,
        "alerts": alert_banners,
        "ops": ops,
        "redis": redis,
        "retry_eligible": await count_retry_eligible_dom_products(
            db, int(ops.get("max_attempts") or env.dom_max_attempts)
        ),
        "oldest_error_age": await oldest_dom_error_age(db, now),
    }


# Четыре карточки метрик сверху дашборда (заказы, парсинг, EUR, dom_errors).
async def build_dashboard_metrics(db: AsyncSession) -> dict[str, Any]:
    now = utc_now_naive()

    queues = await CrudOrder(session=db, model=Order).admin_orders_queues()
    orders_action_count = sum(int(value) for value in queues.values())
    orders_foot = _orders_action_foot(queues)

    pricing_service = PricingService(db)
    settings_row = await pricing_service.get_settings()
    eur_rate = settings_row.eur_rate if settings_row else None
    eur_trend, eur_trend_dir = await pricing_service.get_eur_rate_trend_for_admin()
    if settings_row and settings_row.eur_rate_updated_at:
        eur_foot = (
            format_datetime_msk(settings_row.eur_rate_updated_at, with_tz_label=False)
            or "—"
        )
    else:
        eur_foot = "курс не обновлялся"

    stats = get_catalog_queue_stats()
    dom_errors = int(
        await db.scalar(
            select(func.count(Product.id)).where(Product.dom_last_error.isnot(None))
        )
        or 0
    )
    parsing = _parsing_pipeline(stats, dom_errors=dom_errors)
    parsing_trend = "обработка" if parsing["pipeline_running"] else None
    if parsing["pipeline_running"]:
        parsing_foot = f"≈{parsing['products_active']} товаров в работе"
    elif parsing["queue_total"]:
        parsing_foot = f"{parsing['queue_total']} задач в очереди"
    elif dom_errors > 0:
        parsing_foot = f"{dom_errors} ошибок DOM"
    elif parsing["overall_pill"] == "err":
        parsing_foot = "нужна проверка"
    else:
        parsing_foot = "очереди пусты"

    return {
        "orders_action_count": orders_action_count,
        "orders_foot": orders_foot,
        "parsing_queue_value": parsing["queue_total"] or parsing["products_pending"],
        "parsing_trend": parsing_trend,
        "parsing_trend_dir": "",
        "parsing_foot": parsing_foot,
        "eur_rate": (
            eur_rate.quantize(Decimal("0.01")) if eur_rate is not None else None
        ),
        "eur_trend": eur_trend,
        "eur_trend_dir": eur_trend_dir,
        "eur_foot": eur_foot,
        "dom_errors": dom_errors,
        "updated_at": format_datetime_msk(now) or "",
    }


# Строки «Состояние системы»: БД, Redis, сайт, платёжный шлюз.
async def build_health_rows(db: AsyncSession) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    t0 = time.perf_counter()
    db_ok = False
    try:
        await db.scalar(select(1))
        db_ok = True
    except Exception:
        db_ok = False
    db_ms = max(1, int((time.perf_counter() - t0) * 1000))
    rows.append(
        {
            "label": "База данных",
            "status": "ok" if db_ok else "err",
            "detail": f"{db_ms} ms" if db_ok else "недоступна",
            "icon": "check" if db_ok else "alert",
        }
    )

    redis_ok = False
    t0 = time.perf_counter()
    try:
        Redis.from_url(app_settings.REDIS_URL).ping()
        redis_ok = True
    except Exception:
        redis_ok = False
    rows.append(
        {
            "label": "Redis / RQ",
            "status": "ok" if redis_ok else "err",
            "detail": "online" if redis_ok else "offline",
            "icon": "check" if redis_ok else "alert",
        }
    )

    # Не HTTP-проба на 127.0.0.1:8000 — один uvicorn-worker зависает на self-request.
    # PUBLIC_SITE_URL с VPS часто недоступен (hairpin NAT).
    t0 = time.perf_counter()
    site_ok = spa_index_path() is not None
    site_ms = max(1, int((time.perf_counter() - t0) * 1000))
    site_detail = f"{site_ms} ms" if site_ok else "витрина не собрана"
    public_site = (app_settings.PUBLIC_SITE_URL or "").strip().rstrip("/")
    if site_ok and public_site:
        host = public_site.removeprefix("https://").removeprefix("http://")
        site_detail = f"{site_detail} · {host}"
    rows.append(
        {
            "label": "Сайт",
            "status": "ok" if site_ok else "warn",
            "detail": site_detail,
            "icon": "check" if site_ok else "alert",
        }
    )

    payment_configured = app_settings.sbp_configured
    if not payment_configured:
        rows.append(
            {
                "label": "Платёжный шлюз",
                "status": "err",
                "detail": "не подключён",
                "icon": "alert",
            }
        )
    elif not app_settings.SBP_ENABLED:
        rows.append(
            {
                "label": "Платёжный шлюз",
                "status": "warn",
                "detail": "credentials есть · SBP_ENABLED=false",
                "icon": "alert",
            }
        )
    else:
        rows.append(
            {
                "label": "Платёжный шлюз",
                "status": "ok",
                "detail": "SBP СБП · callback настроен",
                "icon": "check",
            }
        )

    return rows


# Карточка «Здоровье» на дашборде: N/M, бейдж OK/WARN/ERR.
def health_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    ok_count = sum(1 for row in rows if row.get("status") == "ok")
    if ok_count == total:
        trend, trend_dir, foot = "OK", "up", "все сервисы активны"
    elif ok_count == 0:
        trend, trend_dir, foot = "ERR", "down", "проверьте инфраструктуру"
    else:
        trend, trend_dir, foot = "WARN", "", f"{ok_count}/{total} сервисов в норме"
    return {
        "value": f"{ok_count}/{total}",
        "trend": trend,
        "trend_dir": trend_dir,
        "foot": foot,
    }
