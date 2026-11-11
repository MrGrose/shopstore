import asyncio
import logging
import random
import re
import time
from typing import Any

from src.jobs.dom_observability import get_dom_chunk_context, log_dom_product
from src.scraper.config.settings import Settings
from src.scraper.enrichment.http_validate import (
    classify_lane_http_event,
    is_cf_challenge_html,
    is_real_captcha_html,
    reject_http_html_reason,
)
from src.scraper.parsers.product_pdp import (
    parse_product_page_details,
    parse_product_page_prices,
)
from src.scraper.sources.graphql_catalog import apply_variant_stock
from src.scraper.telemetry import DomFetchMeta, PathTelemetry, map_dom_error_class
from src.services.catalog.importing.product_complete import validate_full_dom_details
from src.services.orders.supplier_availability.client import parse_member_price_eur

logger = logging.getLogger(__name__)

_NOT_FOUND_HTTP_REASONS = frozenset({"status=404", "status=410"})


# True для 404/410 у поставщика — recovery и retry бессмысленны.
def is_non_recoverable_dom_error(reason: str) -> bool:
    raw = (reason or "").strip().lower()
    if raw == "not_found":
        return True
    return raw in _NOT_FOUND_HTTP_REASONS or raw.startswith("status=404")


# HTTP reject reason означает, что карточки у поставщика больше нет.
def _http_reject_is_not_found(reject_reason: str | None) -> bool:
    if not reject_reason:
        return False
    return is_non_recoverable_dom_error(reject_reason)


# Shopify 404 иногда приходит с HTTP 200 — проверяем title и canonical.
def _is_not_found_page(
    html: str,
    status: int | None,
    title: str | None,
) -> bool:
    if status in (404, 410):
        return True
    title_low = (title or "").lower()
    if "404 not found" in title_low or "page not found" in title_low:
        return True
    low = (html or "").lower()
    return 'rel="canonical" href="' in low and "/404" in low


# True если сигнал реальный, а не ключ dict со значением False.
def _has_true_error_signal(text: str, key: str) -> bool:
    lowered = text.lower()
    for token in (
        f"'{key}': false",
        f'"{key}": false',
        f"{key}=false",
        f"{key}: false",
    ):
        lowered = lowered.replace(token, " ")
    for token in (
        f"'{key}': true",
        f'"{key}": true',
        f"{key}=true",
        f"{key}: true",
    ):
        if token in text.lower():
            return True
    return key in lowered


# Классифицирует исключение DOM fetch для логов и dom_last_error.
def classify_dom_error(error: Exception | str) -> str:
    text = str(error).lower()
    if "not_found" in text or "'status': 404" in text or "status=404" in text:
        return "not_found"
    if "'status': 429" in text or "status=429" in text:
        return "rate_limited"
    if _has_true_error_signal(text, "captcha") or "turnstile" in text:
        return "captcha"
    if _has_true_error_signal(text, "challenge") or "cloudflare" in text:
        return "challenge"
    if (
        _has_true_error_signal(text, "blocked")
        or "access denied" in text
        or "temporarily unavailable" in text
    ):
        return "blocked"
    if "timeout" in text or "timed out" in text:
        return "timeout"
    if "log in" in text or "/account/login" in text:
        return "login"
    if "product-data" in text:
        return "no_product_data"
    return "error"


# Нужна ли длинная пауза перед следующим SKU (challenge/timeout).
def _needs_dom_backoff(reason: str) -> bool:
    return reason in {"captcha", "challenge", "blocked", "timeout"}


# Резервный HTTP через cloudscraper (если установлен).
def _fetch_product_html_with_cloudscraper(url: str, env: Settings) -> str | None:
    try:
        import cloudscraper
    except ImportError:
        return None

    try:
        scraper = cloudscraper.create_scraper()
        response = scraper.get(
            url,
            timeout=env.cloudscraper_timeout_seconds,
            headers={"User-Agent": env.user_agent},
        )
    except Exception as exc:
        logger.debug("cloudscraper: резервный запрос не сработал для %s: %s", url, exc)
        return None
    if not response.ok:
        return None
    html = response.text
    return html if "product-data" in html else None


# Диагностическая строка при отсутствии product-data в browser HTML.
def _html_markers(html: str, url: str, title: str, status: int | None) -> str:
    low = html.lower()
    captcha = status not in (404, 410, 429) and is_real_captcha_html(html)
    challenge = is_cf_challenge_html(html, title) or status == 429
    if status == 429:
        captcha = False
    blocked = "access denied" in low or "temporarily unavailable" in low
    markers: dict[str, object] = {
        "status": status,
        "title": title[:120],
        "len": len(html),
        "product_data": "product-data" in low,
        "login": "log in" in low or "/account/login" in low,
    }
    if captcha:
        markers["captcha"] = True
    if challenge:
        markers["challenge"] = True
    if blocked:
        markers["blocked"] = True
    snippet = re.sub(r"\s+", " ", html[:500]).strip()
    return f"url={url}, markers={markers}, head={snippet!r}"


# HTTP-first через Playwright ctx.request (без ScraperHttpClient).
async def _fetch_product_html_via_http_legacy(
    ctx, url: str, env: Settings
) -> tuple[str | None, DomFetchMeta]:
    started = time.monotonic()
    meta = DomFetchMeta(path="http", latency_ms=0, source="http_path")
    try:
        response = await ctx.request.get(url, timeout=env.dom_http_timeout_ms)
        html = (await response.text()) or ""
        status = response.status
    except TimeoutError as exc:
        logger.debug("DOM HTTP-first: timeout для %s — %s", url, exc)
        meta.latency_ms = int((time.monotonic() - started) * 1000)
        meta.http_reject_reason = "timeout"
        meta.error_class = map_dom_error_class("timeout")
        return None, meta
    except Exception as exc:
        logger.debug("DOM HTTP-first: запрос не сработал для %s — %s", url, exc)
        meta.latency_ms = int((time.monotonic() - started) * 1000)
        meta.http_reject_reason = "request_error"
        meta.error_class = map_dom_error_class("request_error")
        return None, meta

    reject_reason = reject_http_html_reason(html, status)
    meta.latency_ms = int((time.monotonic() - started) * 1000)
    if reject_reason:
        meta.http_reject_reason = reject_reason
        meta.error_class = map_dom_error_class(reject_reason)
        logger.debug("DOM HTTP-first: reject %s для %s", reject_reason, url)
        return None, meta

    meta.success = True
    logger.debug("DOM HTTP-first: принят HTML для %s", url)
    return html, meta


# HTTP-first через ScraperHttpClient с cookies из DomSession.
async def _fetch_product_html_via_http_synced(
    session,
    url: str,
    env: Settings,
) -> tuple[str | None, DomFetchMeta]:
    started = time.monotonic()
    meta = DomFetchMeta(path="http", latency_ms=0, source="http_path")
    referer = session.http_client.last_listing_url if session.http_client else None
    html, status, reject_reason = await session.http_client.fetch(
        url,
        session.ctx,
        referer=referer,
    )
    meta.latency_ms = int((time.monotonic() - started) * 1000)
    if reject_reason or html is None:
        meta.http_reject_reason = reject_reason
        meta.error_class = map_dom_error_class(reject_reason or "error")
        return None, meta
    meta.success = True
    return html, meta


# Browser fallback: new_page, goto, ждём script#product-data.
async def _fetch_product_html_browser(
    ctx,
    url: str,
    env: Settings,
    source: str,
) -> tuple[str, DomFetchMeta]:
    started = time.monotonic()
    meta = DomFetchMeta(path="browser", latency_ms=0, source=source)
    page = await ctx.new_page()
    try:
        response = await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=env.dom_page_timeout_ms,
        )
        status = response.status if response is not None else None
        html = (await page.content()) or ""
        title = await page.title()
        if _is_not_found_page(html, status, title):
            raise RuntimeError(
                "DOM not_found; " + _html_markers(html, url, title, status)
            )
        for attempt in range(1, env.dom_product_data_attempts + 1):
            try:
                await page.wait_for_selector(
                    "script#product-data",
                    state="attached",
                    timeout=(
                        env.dom_first_selector_timeout_ms
                        if attempt == 1
                        else env.dom_retry_selector_timeout_ms
                    ),
                )
            except Exception:
                pass

            html = (await page.content()) or ""
            title = await page.title()
            if _is_not_found_page(html, status, title):
                raise RuntimeError(
                    "DOM not_found; " + _html_markers(html, url, title, status)
                )
            if "product-data" in html:
                meta.latency_ms = int((time.monotonic() - started) * 1000)
                meta.success = True
                return html, meta

            if attempt == 1:
                try:
                    await page.wait_for_load_state(
                        "networkidle", timeout=env.dom_networkidle_timeout_ms
                    )
                except Exception as exc:
                    logger.debug("DOM: timeout networkidle для %s — %s", url, exc)
            elif attempt == 2:
                try:
                    response = await page.reload(
                        wait_until="networkidle",
                        timeout=env.dom_page_timeout_ms,
                    )
                    status = response.status if response is not None else status
                except Exception as exc:
                    logger.debug(
                        "DOM: повторная загрузка не сработала для %s — %s", url, exc
                    )
            else:
                break

        html = (await page.content()) or ""
        title = await page.title()
        meta.latency_ms = int((time.monotonic() - started) * 1000)
        if _is_not_found_page(html, status, title):
            raise RuntimeError(
                "DOM not_found; " + _html_markers(html, url, title, status)
            )
        raise RuntimeError(
            "DOM без product-data; " + _html_markers(html, url, title, status)
        )
    finally:
        await page.close()


# Primary fetch: HTTP-first при возможности, иначе browser.
async def fetch_product_html(
    ctx,
    url: str,
    env: Settings,
    session=None,
    telemetry: PathTelemetry | None = None,
    source: str = "browser_path",
    http_first: bool = True,
    sku: object | None = None,
) -> tuple[str, str, str | None]:
    http_reject_reason: str | None = None
    throttle = getattr(session, "throttle", None) if session is not None else None
    lane_throttle_on = bool(
        throttle is not None and getattr(env, "lane_429_throttle_enabled", True)
    )
    if http_first and env.dom_http_first:
        if lane_throttle_on and throttle is not None:
            await throttle.await_http_allowed(sku=sku)
        http_client = None
        if session is not None:
            http_client = getattr(session, "http_client", None)
        if http_client is not None:
            html, meta = await _fetch_product_html_via_http_synced(session, url, env)
        else:
            html, meta = await _fetch_product_html_via_http_legacy(ctx, url, env)
        if telemetry is not None:
            telemetry.record_fetch(meta)
        if lane_throttle_on and throttle is not None:
            if html:
                event = "http_success"
            else:
                event = classify_lane_http_event(
                    html="",
                    status=None,
                    reject_reason=meta.http_reject_reason,
                )
            await throttle.observe_http_event(event, sku=sku)
        if html:
            return html, "http", None
        http_reject_reason = meta.http_reject_reason
        if _http_reject_is_not_found(meta.http_reject_reason):
            raise RuntimeError(
                f"DOM not_found; url={url}, reason={meta.http_reject_reason}"
            )
        logger.info(
            "[LANE %s] HTTP не принят (%s) → browser fallback",
            getattr(env, "lane_id", None) or "?",
            meta.http_reject_reason or "empty",
        )

    html, meta = await _fetch_product_html_browser(ctx, url, env, source=source)
    if telemetry is not None:
        telemetry.record_fetch(meta)
    if session is not None and meta.success:
        await session.sync_cookies_after_browser()
    return html, "browser", http_reject_reason


# Снимок sale_price из payload до/после apply_dom_details.
def _sale_price_snapshot(product: dict) -> str:
    return str(
        product.get("sale_price_numeric") or product.get("sale_price") or ""
    ).strip()


# Пишет structured log dom_product по результату enrich одного SKU.
def _log_dom_product_enrich(
    product: dict,
    env: Settings,
    pass_label: str,
    fetch_path: str,
    outcome: str,
    sale_price_before: str,
    html: str = "",
    http_reject: str | None = None,
    dom_error: str | None = None,
) -> None:
    ctx = get_dom_chunk_context()
    lane_id = (env.lane_id or "").strip() or (ctx.lane_id or "")
    sale_after = _sale_price_snapshot(product)
    import_source_dom = product.get("import_source") == "dom"
    payload: dict[str, Any] = {
        "product_id": product.get("id"),
        "rq_job_id": ctx.rq_job_id,
        "owner_token": ctx.owner_token,
        "lane_id": lane_id or None,
        "pass": pass_label,
        "fetch_path": fetch_path,
        "outcome": outcome,
        "sale_price_before": sale_price_before or None,
        "sale_price_after": sale_after or None,
        "price_changed": (
            (sale_price_before != sale_after)
            if (sale_price_before or sale_after)
            else False
        ),
        "import_source_dom": import_source_dom,
    }
    if not import_source_dom:
        payload["db_outcome"] = "not_imported"
    if html:
        payload["member_present"] = "tp-price-item__member-price" in html
        prices = parse_product_page_prices(html)
        current = str(prices.get("sale_price") or "").strip()
        if current:
            payload["current_price"] = current
        member = parse_member_price_eur(html)
        if member:
            payload["member_price"] = member
    if http_reject:
        payload["http_reject"] = http_reject
    if dom_error:
        payload["dom_error"] = dom_error
    log_dom_product({k: v for k, v in payload.items() if v is not None})


# Режим обогащения из dom_mode в payload (FULL по умолчанию).
def _dom_update_details(product: dict) -> bool:
    from src.services.catalog.importing.dom_mode import dom_mode_from_payload

    return dom_mode_from_payload(product) == "FULL"


# Мержит распарсенный PDP в product dict (цена, stock, опционально details).
def apply_dom_details(
    product: dict,
    details: dict,
    update_prices: bool = True,
    update_details: bool = False,
) -> bool:
    enriched = apply_variant_stock(
        product,
        details.get("product_data") or {},
        details.get("selected_variant") or {},
    )
    prices = details.get("prices") or {}
    sale_price = str(prices.get("sale_price") or "").strip()
    regular_price = str(prices.get("regular_price") or "").strip()
    if sale_price and update_prices:
        old_sale_price = product.get("sale_price_numeric") or product.get("sale_price")
        product["sale_price"] = sale_price
        product["sale_price_numeric"] = sale_price
        product["regular_price"] = regular_price or sale_price
        variants = (product.get("product_data") or {}).get("variants") or []
        for variant in variants:
            if not isinstance(variant, dict):
                continue
            variant["price"] = sale_price
            variant["compare_at_price"] = regular_price or sale_price
        selected_variant = product.get("selected_variant") or {}
        if isinstance(selected_variant, dict):
            selected_variant["price"] = sale_price
            selected_variant["compare_at_price"] = regular_price or sale_price
        if str(old_sale_price or "") != sale_price:
            logger.info(
                "DOM-цена: %s %s -> %s EUR",
                product.get("item_id") or product.get("product_url"),
                old_sale_price,
                sale_price,
            )
        enriched = True
    if update_details:
        features = details.get("features") or []
        if features:
            product["features"] = features
            enriched = True
        media_gallery = details.get("media_gallery") or []
        if media_gallery:
            product["media_gallery"] = media_gallery
            product["image_url"] = media_gallery[0].get("url") or product.get(
                "image_url"
            )
            enriched = True
        description = details.get("description") or ""
        if description:
            product["description"] = description
            enriched = True
        pdp_meta = details.get("pdp_meta") or {}
        if pdp_meta:
            product["pdp_meta"] = pdp_meta
            enriched = True
    if enriched:
        product["import_source"] = "dom"
    return enriched


# Обогащает чанк товаров через DOM (primary/recovery pass_label).
async def enrich_products_with_dom(
    products: list[dict],
    env: Settings,
    ctx,
    session=None,
    pass_label: str = "primary",
    fail_fast_on_empty_batch: bool = False,
    raise_on_low_success: bool = True,
    update_prices: bool = True,
    http_first: bool = True,
) -> dict[str, Any]:
    if not products:
        return {"total": 0, "success": 0, "failed": 0, "failed_products": []}

    telemetry = session.telemetry if session is not None else None
    source_browser = "recovery_path" if pass_label == "recovery" else "browser_path"
    ok = 0
    failed_products: list[dict] = []
    total = len(products)
    workers = max(1, env.storefront_stock_workers)
    logger.info(
        "DOM-обогащение: старт, товаров=%s, воркеров=%s, pass=%s",
        total,
        workers,
        pass_label,
    )

    # Один SKU: fetch HTML, parse, apply_dom_details.
    async def _enrich_one(product: dict) -> tuple[bool, str]:
        url = str(product.get("product_url") or "")
        sale_price_before = _sale_price_snapshot(product)
        if not url:
            _log_dom_product_enrich(
                product,
                env=env,
                pass_label=pass_label,
                fetch_path="browser",
                outcome="not_enriched",
                sale_price_before=sale_price_before,
            )
            return False, "browser"
        fetch_path = "browser"
        http_reject: str | None = None
        if session is not None:
            await session.before_product()
        try:
            html, fetch_path, http_reject = await fetch_product_html(
                ctx,
                url,
                env,
                session=session,
                telemetry=telemetry,
                source=source_browser,
                http_first=http_first,
                sku=product.get("id"),
            )
            details = parse_product_page_details(html)
            product.pop("_dom_last_error", None)
            update_details = _dom_update_details(product)
            if update_details:
                invalid = validate_full_dom_details(details)
                if invalid:
                    product["_dom_last_error"] = invalid
                    logger.warning("DOM FULL: невалидный PDP %s (%s)", url, invalid)
                    _log_dom_product_enrich(
                        product,
                        env=env,
                        pass_label=pass_label,
                        fetch_path=fetch_path,
                        outcome="full_invalid",
                        sale_price_before=sale_price_before,
                        html=html,
                        http_reject=http_reject,
                        dom_error=invalid,
                    )
                    return False, fetch_path
            enriched = apply_dom_details(
                product,
                details,
                update_prices=update_prices,
                update_details=update_details,
            )
            _log_dom_product_enrich(
                product,
                env=env,
                pass_label=pass_label,
                fetch_path=fetch_path,
                outcome="parsed_ok" if enriched else "not_enriched",
                sale_price_before=sale_price_before,
                html=html,
                http_reject=http_reject,
            )
            return enriched, fetch_path
        except Exception as exc:
            reason = classify_dom_error(exc)
            product["_dom_last_error"] = reason
            logger.warning("DOM-остатки: %s — %s (%s)", url, exc, reason)
            _log_dom_product_enrich(
                product,
                env=env,
                pass_label=pass_label,
                fetch_path=fetch_path,
                outcome="parse_fail",
                sale_price_before=sale_price_before,
                http_reject=http_reject,
                dom_error=reason,
            )
            if telemetry is not None:
                telemetry.record_fetch(
                    DomFetchMeta(
                        path="browser",
                        latency_ms=0,
                        source=source_browser,
                        error_class=map_dom_error_class(reason),
                        success=False,
                    )
                )
            if _needs_dom_backoff(reason):
                await asyncio.sleep(
                    random.uniform(
                        env.dom_backoff_min_seconds,
                        env.dom_backoff_max_seconds,
                    )
                )
            return False, "browser"
        finally:
            if session is not None:
                await session.after_product(fetch_path)
            else:
                await asyncio.sleep(
                    random.uniform(env.enrich_sleep_min, env.enrich_sleep_max)
                )

    # Параллельный batch с semaphore по batch_workers.
    async def _run_batch(
        items: list[dict],
        label: str,
        batch_workers: int,
    ) -> list[dict]:
        nonlocal ok
        failed: list[dict] = []
        semaphore = asyncio.Semaphore(max(1, batch_workers))

        # Обёртка semaphore для одного SKU в batch.
        async def _limited(product: dict) -> tuple[dict, bool]:
            async with semaphore:
                enriched, _ = await _enrich_one(product)
                return product, enriched

        tasks = [asyncio.create_task(_limited(product)) for product in items]
        for idx, task in enumerate(asyncio.as_completed(tasks), 1):
            product, enriched = await task
            if enriched:
                ok += 1
            else:
                failed.append(product)
            if idx == 1 or idx % 10 == 0 or idx == len(items):
                logger.info(
                    "%s: прогресс %s/%s успешно=%s ошибок=%s",
                    label,
                    idx,
                    len(items),
                    ok,
                    len(failed),
                )
        return failed

    failed_products = await _run_batch(products, f"DOM-{pass_label}", workers)
    terminal_failed = [
        product
        for product in failed_products
        if is_non_recoverable_dom_error(str(product.get("_dom_last_error") or ""))
    ]
    if terminal_failed:
        logger.info(
            "DOM-%s: terminal not_found=%s (без retry/recovery)",
            pass_label,
            len(terminal_failed),
        )
    failed_products = [
        product
        for product in failed_products
        if not is_non_recoverable_dom_error(str(product.get("_dom_last_error") or ""))
    ]
    if fail_fast_on_empty_batch and failed_products and ok == 0:
        raise RuntimeError(
            f"DOM-обогащение остатков не сработало: {len(failed_products)}/{total}, "
            "success_ratio=0.000"
        )

    for round_no in range(1, env.enrich_retry_rounds + 1):
        if not failed_products:
            break
        retry_items = failed_products
        logger.info(
            "DOM-обогащение: повтор %s/%s, товаров=%s",
            round_no,
            env.enrich_retry_rounds,
            len(retry_items),
        )
        failed_products = await _run_batch(
            retry_items,
            f"DOM-повтор {round_no}",
            1,
        )

    failed_products.extend(terminal_failed)
    failed = len(failed_products)
    logger.info("DOM-остатки через браузер: успешно=%s ошибок=%s", ok, failed)
    success_ratio = ok / total if total else 1.0
    if failed and success_ratio < env.dom_min_success_ratio:
        message = (
            f"DOM-обогащение остатков не сработало: {failed}/{total}, "
            f"доля_успеха={success_ratio:.3f}"
        )
        if raise_on_low_success:
            raise RuntimeError(message)
        logger.warning(message)
    if failed:
        logger.warning(
            "DOM-остатки: продолжаем импорт, ошибок=%s/%s, доля_успеха=%.3f",
            failed,
            total,
            success_ratio,
        )
    return {
        "total": total,
        "success": ok,
        "failed": failed,
        "failed_products": failed_products,
        "success_ratio": success_ratio,
    }
