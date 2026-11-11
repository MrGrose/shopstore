from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

import aiohttp
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.core.config import settings as app_settings
from src.models.pricing import (
    EurRateHistory,
    MarginRule,
    MarginRuleHistory,
    PricingRecalculationJob,
    PricingSettings,
    ServiceCommissionHistory,
)
from src.models.product import Product, ProductVariant
from src.repositories.pricing_repo import PricingRepository
from src.services.catalog.display.pricing_nav_registry import CATALOG_SUBCATEGORIES
from src.services.catalog.read.caches import invalidate_catalog_read_caches
from src.services.pricing.calculator import (
    MAX_MONEY,
    calculate_delivery_rub,
    calculate_price_rub,
    normalize_supplier_eur,
)
from src.services.pricing.groups import resolve_pricing_group
from src.services.pricing.price_check import (
    ExpectedStorefrontPrice,
    apply_expected_storefront_price,
)
from src.services.pricing.rules import pricing_category_key, resolve_margin_rule
from src.utils.datetime_fmt import msk_today, utc_now_naive


class PricingService:
    MAX_MONEY = MAX_MONEY
    EUR_RATE_HISTORY_UI_DAYS = 7
    EUR_RATE_HISTORY_PAGE_SIZE = 20

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = PricingRepository(session)

    # Возвращает актуальные настройки ценообразования.
    async def get_settings(self) -> PricingSettings:
        settings_obj = await self.repo.get_settings()
        if settings_obj:
            return settings_obj
        return await self.repo.create_default_settings()

    # Возвращает правила маржи.
    async def get_margin_rules(self) -> list[MarginRule]:
        return await self.repo.get_margin_rules()

    # Определяет storefront pricing key товара.
    @staticmethod
    def resolve_category_key(
        sport_type: str | None,
        category_l2: str | None,
    ) -> str:
        resolution = resolve_pricing_group(sport_type, category_l2)
        return pricing_category_key(resolution.sport_type, resolution.subcategory_slug)

    # Считает итоговую цену товара в RUB.
    @staticmethod
    def normalize_supplier_eur(value: Decimal) -> Decimal:
        return normalize_supplier_eur(value)

    @staticmethod
    def calculate_price_rub(
        supplier_price_eur: Decimal,
        eur_rate: Decimal,
        margin_percent: Decimal,
    ) -> Decimal:
        return calculate_price_rub(supplier_price_eur, eur_rate, margin_percent)

    # Возвращает стоимость доставки в RUB.
    @staticmethod
    def calculate_delivery_rub(delivery_fee_eur: Decimal, eur_rate: Decimal) -> Decimal:
        return calculate_delivery_rub(delivery_fee_eur, eur_rate)

    # Возвращает множитель курса Rapira из настроек или env.
    @staticmethod
    def resolve_eur_rate_multiplier(
        settings: PricingSettings | None = None,
    ) -> Decimal:
        if settings is not None and settings.markup_multiplier is not None:
            return Decimal(str(settings.markup_multiplier))
        return Decimal(str(app_settings.EUR_RATE_MULTIPLIER))

    # Парсит курс EUR из ответа Rapira API.
    @staticmethod
    def parse_rapira_eur_rate(
        payload: dict,
        symbol: str | None = None,
        multiplier: Decimal | None = None,
    ) -> Decimal:
        if payload.get("code") != 0:
            message = payload.get("message") or "unknown error"
            raise ValueError(f"Ошибка API Rapira: {message}")

        target_symbol = symbol or app_settings.EUR_RATE_SYMBOL
        pair = next(
            (
                item
                for item in payload.get("data", [])
                if item.get("symbol") == target_symbol
            ),
            None,
        )
        if not pair:
            raise ValueError(f"Пара {target_symbol} не найдена в ответе Rapira")

        ask_price = Decimal(str(pair.get("askPrice") or "0"))
        if ask_price <= 0:
            raise ValueError(f"Некорректный askPrice для {target_symbol}")

        rate_multiplier = multiplier or Decimal(str(app_settings.EUR_RATE_MULTIPLIER))
        return (ask_price * rate_multiplier).quantize(
            Decimal("0.0001"), rounding=ROUND_HALF_UP
        )

    @staticmethod
    def normalize_markup_multiplier(value: Decimal) -> Decimal:
        return value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @staticmethod
    def rapira_eur_rate_source(
        symbol: str | None = None,
        multiplier: Decimal | None = None,
    ) -> str:
        target_symbol = symbol or app_settings.EUR_RATE_SYMBOL
        rate_multiplier = PricingService.normalize_markup_multiplier(
            multiplier or Decimal(str(app_settings.EUR_RATE_MULTIPLIER))
        )
        return f"rapira:{target_symbol}*{rate_multiplier:.2f}"

    @staticmethod
    def format_eur_rate_source_display(source: str | None) -> str:
        if not source:
            return "manual"
        if not source.startswith("rapira:") or "*" not in source:
            return source
        prefix, multiplier_raw = source.rsplit("*", 1)
        try:
            multiplier = PricingService.normalize_markup_multiplier(
                Decimal(multiplier_raw.replace(",", "."))
            )
        except Exception:
            return source
        return f"{prefix}*{multiplier:.2f}"

    @staticmethod
    def eur_rate_change_pct(
        previous: Decimal | None,
        new: Decimal | None,
    ) -> Decimal | None:
        if previous is None or new is None or previous == 0:
            return None
        return ((new - previous) / previous * Decimal("100")).quantize(
            Decimal("0.1"), rounding=ROUND_HALF_UP
        )

    @staticmethod
    def format_eur_rate_trend(
        current: Decimal | None,
        previous: Decimal | None,
    ) -> tuple[str | None, str]:
        pct = PricingService.eur_rate_change_pct(previous, current)
        if pct is None:
            return None, ""
        if pct > 0:
            return f"+{pct}%", "up"
        if pct < 0:
            return f"{pct}%", "down"
        return "0%", ""

    @staticmethod
    def format_eur_rate_change_flash(
        previous: Decimal | None,
        new: Decimal | None,
    ) -> str | None:
        if previous is None or new is None or previous == new:
            return None
        pct = PricingService.eur_rate_change_pct(previous, new)
        if pct is None:
            return "Курс EUR обновлён"
        if pct > 0:
            label = f"+{pct}%"
        elif pct < 0:
            label = f"{pct}%"
        else:
            label = "0%"
        return (
            f"Курс {label} к прошлому; переоценка по расписанию "
            "(каждые 6 ч) или кнопка «Переоценка»"
        )

    # Обновляет курс EUR через внешний API.
    async def refresh_eur_rate(self) -> PricingSettings:
        settings_obj = await self.get_settings()
        timeout = aiohttp.ClientTimeout(total=8)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(app_settings.EUR_RATE_API_URL) as response:
                response.raise_for_status()
                payload = await response.json()
        rub_rate = self.parse_rapira_eur_rate(
            payload,
            multiplier=self.resolve_eur_rate_multiplier(settings_obj),
        )
        return await self.repo.update_settings(
            settings=settings_obj,
            eur_rate=rub_rate,
            eur_rate_source=self.rapira_eur_rate_source(
                multiplier=self.resolve_eur_rate_multiplier(settings_obj),
            ),
            eur_rate_trigger="rapira_refresh",
        )

    # Применяет формулу цены к товару и его вариантам.
    async def apply_pricing_to_product(self, product: Product) -> Product:
        settings_obj = await self.get_settings()
        rules = await self.repo.get_active_margin_rules()
        resolved_rule = resolve_margin_rule(
            product.sport_type, product.category_l2, rules
        )
        category_key = resolved_rule.category_key
        margin = Decimal(resolved_rule.rule.margin_percent)
        supplier_price = Decimal(product.supplier_price_eur or product.sale_price or 0)
        normalized_supplier_price = self.normalize_supplier_eur(supplier_price)
        if normalized_supplier_price != supplier_price:
            product.supplier_price_eur = normalized_supplier_price
            supplier_price = normalized_supplier_price
        margin_multiplier = Decimal("1") + (margin / Decimal("100"))
        raw_result = (
            supplier_price * Decimal(settings_obj.eur_rate) * margin_multiplier
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if raw_result > self.MAX_MONEY:
            max_rate = (
                (self.MAX_MONEY / (supplier_price * margin_multiplier)).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
                if supplier_price > 0
                else Decimal("0")
            )
            raise ValueError(
                "Товар переполняет Numeric(10,2): "
                f"id={product.id}, title='{product.title}', "
                f"supplier_price_eur={supplier_price}, "
                f"eur_rate={Decimal(settings_obj.eur_rate)}, margin_percent={margin}, "
                f"result={raw_result}, max_allowed={self.MAX_MONEY}, "
                f"max_rate_for_product={max_rate}"
            )
        final_price = self.calculate_price_rub(
            supplier_price_eur=supplier_price,
            eur_rate=Decimal(settings_obj.eur_rate),
            margin_percent=margin,
        )
        product.supplier_price_eur = supplier_price
        product.sale_price = final_price
        product.regular_price = final_price
        product.pricing_category_key = category_key
        product.eur_rate_snapshot = Decimal(settings_obj.eur_rate)
        product.margin_snapshot_percent = margin
        product.markup_snapshot = Decimal(settings_obj.markup_multiplier)
        for variant in product.variants:
            variant.price = final_price
        self.session.add(product)
        return product

    # Проверяет и атомарно обновляет storefront-цену одного товара.
    async def verify_storefront_price(
        self,
        product_id: int,
        expected_rule_version: datetime | None = None,
    ) -> bool:
        product_stmt = (
            select(Product)
            .where(Product.id == product_id)
            .options(selectinload(Product.variants))
            .with_for_update()
        )
        product = await self.session.scalar(product_stmt)
        if product is None:
            raise ValueError(f"Товар {product_id} не найден")
        await self.session.scalars(
            select(ProductVariant)
            .where(ProductVariant.product_id == product_id)
            .with_for_update()
        )
        settings_obj = await self.repo.get_settings_for_update()
        rules = await self.repo.get_margin_rules_for_update()
        return self.verify_loaded_storefront_price(
            product,
            settings_obj,
            rules,
            expected_rule_version,
        )

    # Проверяет уже заблокированный товар с загруженным pricing-контекстом.
    def verify_loaded_storefront_price(
        self,
        product: Product,
        settings_obj: PricingSettings,
        rules: list[MarginRule],
        expected_rule_version: datetime | None = None,
    ) -> bool:
        resolved_rule = resolve_margin_rule(
            product.sport_type, product.category_l2, rules
        )
        if expected_rule_version is not None and (
            resolved_rule.rule.updated_at != expected_rule_version
        ):
            raise ValueError("Версия правила изменилась во время пересчёта")
        supplier_price = Decimal(product.supplier_price_eur or product.sale_price or 0)
        supplier_price = normalize_supplier_eur(supplier_price)
        expected = ExpectedStorefrontPrice(
            supplier_price_eur=supplier_price,
            final_price=calculate_price_rub(
                supplier_price,
                Decimal(settings_obj.eur_rate),
                Decimal(resolved_rule.rule.margin_percent),
            ),
            category_key=resolved_rule.category_key,
            eur_rate=Decimal(settings_obj.eur_rate),
            margin_percent=Decimal(resolved_rule.rule.margin_percent),
            markup_snapshot=Decimal(settings_obj.markup_multiplier),
        )
        changed = apply_expected_storefront_price(product, expected)
        if changed:
            self.session.add(product)
        return changed

    # Массово пересчитывает цены всех товаров.
    async def recalculate_all_products(self) -> int:
        settings_obj = await self.get_settings()
        stmt = select(Product).options(selectinload(Product.variants))
        products = (await self.session.scalars(stmt)).all()
        updated = 0
        for product in products:
            try:
                await self.apply_pricing_to_product(product)
                updated += 1
            except ValueError:
                continue
        await self.repo.touch_settings_updated(settings_obj)
        await self.session.commit()
        if updated:
            invalidate_catalog_read_caches(reason="pricing_recalculate_all")
        return updated

    # Обновляет настройки ценообразования из админки.
    async def update_admin_settings(
        self,
        eur_rate: Decimal | None = None,
        delivery_fee_eur: Decimal | None = None,
        referral_commission_percent: Decimal | None = None,
        service_commission_percent: Decimal | None = None,
        markup_multiplier: Decimal | None = None,
    ) -> PricingSettings:
        settings = await self.get_settings()
        await self.repo.ensure_service_commission_history_baseline(settings)
        if (
            service_commission_percent is not None
            and service_commission_percent != settings.service_commission_percent
        ):
            effective_from = msk_today()
            await self.repo.upsert_service_commission_history(
                effective_from=effective_from,
                commission_percent=service_commission_percent,
            )
        rate_kwargs: dict[str, str] = {}
        if eur_rate is not None and eur_rate != settings.eur_rate:
            rate_kwargs = {
                "eur_rate_source": "manual",
                "eur_rate_trigger": "manual_admin",
            }
        elif (
            markup_multiplier is not None
            and markup_multiplier != settings.markup_multiplier
            and settings.eur_rate_source
            and settings.eur_rate_source.startswith("rapira:")
        ):
            rate_kwargs = {
                "eur_rate_source": self.rapira_eur_rate_source(
                    multiplier=self.normalize_markup_multiplier(markup_multiplier)
                ),
            }
        normalized_markup = (
            self.normalize_markup_multiplier(markup_multiplier)
            if markup_multiplier is not None
            else None
        )
        return await self.repo.update_settings(
            settings=settings,
            eur_rate=eur_rate,
            delivery_fee_eur=delivery_fee_eur,
            markup_multiplier=normalized_markup,
            referral_commission_percent=referral_commission_percent,
            service_commission_percent=service_commission_percent,
            **rate_kwargs,
        )

    # Возвращает историю курса EUR для админки.
    async def list_eur_rate_history_admin(
        self,
        before_id: int | None = None,
    ) -> list[EurRateHistory]:
        limit = self.EUR_RATE_HISTORY_PAGE_SIZE
        if before_id is None:
            since = utc_now_naive() - timedelta(days=self.EUR_RATE_HISTORY_UI_DAYS)
            return await self.repo.list_eur_rate_history(since=since, limit=limit)
        return await self.repo.list_eur_rate_history(before_id=before_id, limit=limit)

    # Предыдущий курс EUR для тренда (из истории БД).
    async def get_eur_rate_trend_previous(self) -> Decimal | None:
        return await self.repo.get_previous_eur_rate_for_trend()

    # Предыдущий курс EUR: история БД, fallback Redis.
    async def resolve_eur_rate_trend_previous(self) -> Decimal | None:
        previous = await self.get_eur_rate_trend_previous()
        if previous is not None:
            return previous
        try:
            from redis import Redis

            raw_prev = Redis.from_url(app_settings.REDIS_URL).get(
                "pricing:eur_rate_prev"
            )
            if not raw_prev:
                return None
            prev = Decimal(
                str(raw_prev.decode() if isinstance(raw_prev, bytes) else raw_prev)
            )
            if prev > 0:
                return prev
        except Exception:
            return None
        return None

    # Тренд курса EUR для админки: подпись и направление.
    async def get_eur_rate_trend_for_admin(self) -> tuple[str | None, str]:
        settings = await self.get_settings()
        current = (
            Decimal(str(settings.eur_rate))
            if settings and settings.eur_rate is not None
            else None
        )
        previous = await self.resolve_eur_rate_trend_previous()
        return self.format_eur_rate_trend(current, previous)

    # Возвращает ставку комиссии на дату оплаты (MSK).
    @staticmethod
    def service_commission_percent_for_date(
        paid_date: date,
        history: list[ServiceCommissionHistory],
        fallback: Decimal,
    ) -> Decimal:
        rate = fallback
        for row in sorted(history, key=lambda item: item.effective_from):
            if paid_date >= row.effective_from:
                rate = Decimal(str(row.commission_percent))
        return rate

    # Возвращает историю комиссии сервиса для админки.
    async def list_service_commission_history(
        self,
    ) -> list[ServiceCommissionHistory]:
        settings = await self.get_settings()
        await self.repo.ensure_service_commission_history_baseline(settings)
        return await self.repo.list_service_commission_history()

    # Обновляет правило маржи без запуска batch-job.
    async def update_margin_rule_admin(
        self,
        rule_id: int,
        margin_percent: Decimal,
    ) -> MarginRule:
        rule = await self.repo.get_margin_rule_by_id(rule_id)
        if not rule:
            raise ValueError("Правило не найдено")
        updated_rule = await self.repo.update_margin_rule(
            rule=rule,
            margin_percent=margin_percent,
            is_active=None,
        )
        return updated_rule

    # Возвращает хронологию изменений выбранного правила.
    async def list_margin_rule_history(
        self,
        rule_id: int,
    ) -> list[MarginRuleHistory]:
        return await self.repo.list_margin_rule_history(rule_id)

    # Сохраняет правило и ставит batch-переоценку в очередь.
    async def update_margin_rule_and_enqueue(
        self,
        rule_id: int,
        margin_percent: Decimal,
    ) -> tuple[MarginRule, PricingRecalculationJob]:
        rule = await self.repo.get_margin_rule_by_id(rule_id)
        if rule is None:
            raise ValueError("Правило не найдено")
        rule = await self.repo.update_margin_rule(
            rule=rule,
            margin_percent=margin_percent,
            is_active=None,
        )
        job = await self.enqueue_margin_rule_recalculation(rule)
        return rule, job

    # Создаёт и ставит в очередь job для уже сохранённого правила.
    async def enqueue_margin_rule_recalculation(
        self,
        rule: MarginRule,
    ) -> PricingRecalculationJob:
        settings_obj = await self.get_settings()
        rules = await self.repo.get_margin_rules()
        total_count = await self.repo.count_group_products(
            rule,
            rules,
            storefront_only=True,
        )
        job = await self.repo.create_recalculation_job(
            rule,
            settings_obj,
            total_count,
        )
        from src.services.pricing.repricing import enqueue_repricing_job

        try:
            rq_job_id = enqueue_repricing_job(job.id)
        except Exception as exc:
            message = f"Не удалось поставить пересчёт в очередь Redis: {exc}"
            await self.repo.mark_recalculation_enqueue_failed(job, message)
            raise ValueError(message) from exc
        await self.repo.set_recalculation_rq_job_id(job, rq_job_id)
        return job

    # Собирает карточки правил и counters выбранного спорта для админки.
    async def get_margin_admin_data(self, sport_type: str) -> dict[str, object]:
        rules = await self.repo.get_margin_rules()
        by_key = {(rule.sport_type, rule.subcategory_slug): rule for rule in rules}
        groups: list[dict[str, object]] = []
        for group in CATALOG_SUBCATEGORIES.get(sport_type, ()):
            rule = by_key.get((sport_type, group.slug))
            if rule is None:
                continue
            groups.append(
                {
                    "slug": group.slug,
                    "label": group.label,
                    "rule": rule,
                    "total_count": await self.repo.count_group_products(
                        rule, rules, storefront_only=False
                    ),
                    "storefront_count": await self.repo.count_group_products(
                        rule, rules, storefront_only=True
                    ),
                    "active_job": await self.repo.get_active_recalculation_job(rule.id),
                    "last_job": await self.repo.get_latest_finished_recalculation_job(
                        rule.id
                    ),
                }
            )
        fallback = by_key.get((sport_type, "__fallback__"))
        fallback_data = None
        if fallback is not None:
            fallback_data = {
                "rule": fallback,
                "total_count": await self.repo.count_group_products(
                    fallback, rules, storefront_only=False
                ),
                "storefront_count": await self.repo.count_group_products(
                    fallback, rules, storefront_only=True
                ),
                "active_job": await self.repo.get_active_recalculation_job(fallback.id),
                "last_job": await self.repo.get_latest_finished_recalculation_job(
                    fallback.id
                ),
            }
        return {"groups": groups, "fallback": fallback_data, "rules": rules}

    # Возвращает страницу видимых товаров, использующих fallback.
    async def get_unmapped_products(
        self,
        sport_type: str,
        page: int,
        page_size: int = 20,
    ) -> tuple[list[dict[str, object]], int]:
        rules = await self.repo.get_margin_rules()
        fallback = next(
            (
                rule
                for rule in rules
                if rule.sport_type == sport_type
                and rule.subcategory_slug == "__fallback__"
            ),
            None,
        )
        if fallback is None:
            return [], 0
        products, total = await self.repo.list_unmapped_products(
            fallback,
            rules,
            page,
            page_size,
        )
        rows = []
        for product in products:
            resolved = resolve_margin_rule(
                product.sport_type, product.category_l2, rules
            )
            rows.append(
                {
                    "product": product,
                    "reason": resolved.fallback_reason,
                    "margin_percent": resolved.rule.margin_percent,
                }
            )
        return rows, total
