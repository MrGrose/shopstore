from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.constants.storefront_mapping import RELEASE_STATUS_ACTIVE
from src.core.config import settings as app_settings
from src.models.pricing import (
    EurRateHistory,
    MarginRule,
    MarginRuleHistory,
    PricingRecalculationJob,
    PricingRecalculationJobError,
    PricingSettings,
    ServiceCommissionHistory,
)
from src.models.product import CatalogHiddenBrand, Product, ProductVariant
from src.models.storefront_mapping import (
    ProductStorefrontPlacement,
    StorefrontMappingRelease,
)
from src.services.catalog.display.pricing_nav_registry import CATALOG_SUBCATEGORIES
from src.services.pricing.groups import FALLBACK_SUBCATEGORY_SLUG
from src.utils.datetime_fmt import utc_now_naive


class PricingRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # Возвращает единую запись настроек ценообразования.
    async def get_settings(self) -> PricingSettings | None:
        result = await self.session.scalars(select(PricingSettings).limit(1))
        return result.first()

    # Возвращает настройки с блокировкой для атомарной проверки цены.
    async def get_settings_for_update(self) -> PricingSettings:
        settings = await self.session.scalar(
            select(PricingSettings).limit(1).with_for_update()
        )
        if settings is None:
            raise ValueError("Настройки ценообразования не найдены")
        return settings

    # Создает настройки по умолчанию, если их нет.
    async def create_default_settings(self) -> PricingSettings:
        settings = PricingSettings(
            eur_rate=Decimal("100"),
            markup_multiplier=Decimal("1.2"),
            delivery_fee_eur=Decimal("30"),
            referral_commission_percent=Decimal("5.00"),
            service_commission_percent=Decimal("6.50"),
            eur_rate_source="default",
            eur_rate_updated_at=utc_now_naive(),
        )
        self.session.add(settings)
        await self.session.commit()
        await self.session.refresh(settings)
        return settings

    # Обновляет настройки ценообразования.
    async def update_settings(
        self,
        settings: PricingSettings,
        eur_rate: Decimal | None = None,
        markup_multiplier: Decimal | None = None,
        delivery_fee_eur: Decimal | None = None,
        referral_commission_percent: Decimal | None = None,
        service_commission_percent: Decimal | None = None,
        eur_rate_source: str | None = None,
        eur_rate_trigger: str | None = None,
    ) -> PricingSettings:
        changed = False
        rate_changed = False
        if eur_rate is not None:
            old_rate = settings.eur_rate
            if eur_rate != old_rate:
                settings.eur_rate = eur_rate
                settings.eur_rate_updated_at = utc_now_naive()
                if eur_rate_source is not None:
                    settings.eur_rate_source = eur_rate_source
                self.session.add(
                    EurRateHistory(
                        eur_rate=eur_rate,
                        eur_rate_source=eur_rate_source or settings.eur_rate_source,
                        trigger=eur_rate_trigger or "manual_admin",
                        recorded_at=utc_now_naive(),
                    )
                )
                changed = True
                rate_changed = True
        if eur_rate_source is not None and not rate_changed:
            settings.eur_rate_source = eur_rate_source
            changed = True
        if markup_multiplier is not None:
            settings.markup_multiplier = markup_multiplier
            changed = True
        if delivery_fee_eur is not None:
            settings.delivery_fee_eur = delivery_fee_eur
            changed = True
        if referral_commission_percent is not None:
            settings.referral_commission_percent = referral_commission_percent
            changed = True
        if service_commission_percent is not None:
            settings.service_commission_percent = service_commission_percent
            changed = True
        if changed:
            settings.updated_at = utc_now_naive()
        self.session.add(settings)
        await self.session.commit()
        if rate_changed:
            await self.prune_eur_rate_history()
        await self.session.refresh(settings)
        return settings

    # Возвращает историю курса EUR (новые записи первыми).
    async def list_eur_rate_history(
        self,
        since: datetime | None = None,
        before_id: int | None = None,
        limit: int = 20,
    ) -> list[EurRateHistory]:
        stmt = select(EurRateHistory).order_by(
            EurRateHistory.recorded_at.desc(),
            EurRateHistory.id.desc(),
        )
        if since is not None:
            stmt = stmt.where(EurRateHistory.recorded_at >= since)
        if before_id is not None:
            stmt = stmt.where(EurRateHistory.id < before_id)
        stmt = stmt.limit(limit)
        return list((await self.session.scalars(stmt)).all())

    # Предыдущий курс EUR для тренда на дашборде.
    async def get_previous_eur_rate_for_trend(self) -> Decimal | None:
        rows = await self.list_eur_rate_history(limit=2)
        if len(rows) < 2:
            return None
        return Decimal(str(rows[1].eur_rate))

    # Удаляет записи истории курса старше retention.
    async def prune_eur_rate_history(self) -> None:
        retention_days = int(app_settings.EUR_RATE_HISTORY_RETENTION_DAYS)
        cutoff = utc_now_naive() - timedelta(days=retention_days)
        await self.session.execute(
            delete(EurRateHistory).where(EurRateHistory.recorded_at < cutoff)
        )
        await self.session.commit()

    # Записывает новую ставку комиссии с даты (MSK), если она изменилась.
    async def upsert_service_commission_history(
        self,
        effective_from: date,
        commission_percent: Decimal,
    ) -> ServiceCommissionHistory:
        existing = await self.session.scalar(
            select(ServiceCommissionHistory).where(
                ServiceCommissionHistory.effective_from == effective_from
            )
        )
        if existing is not None:
            existing.commission_percent = commission_percent
            row = existing
        else:
            row = ServiceCommissionHistory(
                effective_from=effective_from,
                commission_percent=commission_percent,
            )
            self.session.add(row)
        await self.session.commit()
        await self.session.refresh(row)
        return row

    # Возвращает историю комиссии сервиса по возрастанию даты.
    async def list_service_commission_history(self) -> list[ServiceCommissionHistory]:
        result = await self.session.scalars(
            select(ServiceCommissionHistory).order_by(
                ServiceCommissionHistory.effective_from.asc()
            )
        )
        return list(result.all())

    # Создаёт базовую запись истории из текущих настроек, если таблица пуста.
    async def ensure_service_commission_history_baseline(
        self, settings: PricingSettings
    ) -> None:
        existing = await self.session.scalar(
            select(ServiceCommissionHistory.id).limit(1)
        )
        if existing is not None:
            return
        self.session.add(
            ServiceCommissionHistory(
                effective_from=date(2020, 1, 1),
                commission_percent=settings.service_commission_percent,
            )
        )
        await self.session.commit()

    # Обновляет updated_at в pricing_settings (только пересчёт цен).
    async def touch_settings_updated(self, settings: PricingSettings) -> None:
        settings.updated_at = utc_now_naive()
        self.session.add(settings)

    # Возвращает все правила маржи для админки.
    async def get_margin_rules(self) -> list[MarginRule]:
        result = await self.session.scalars(
            select(MarginRule).order_by(
                MarginRule.sport_type.asc(), MarginRule.subcategory_slug.asc()
            )
        )
        return list(result.all())

    # Возвращает активные правила маржи для расчетов цены.
    async def get_active_margin_rules(self) -> list[MarginRule]:
        result = await self.session.scalars(
            select(MarginRule)
            .where(MarginRule.is_active.is_(True))
            .order_by(MarginRule.id.asc())
        )
        return list(result.all())

    # Возвращает все правила с блокировкой для выбора версии.
    async def get_margin_rules_for_update(self) -> list[MarginRule]:
        result = await self.session.scalars(
            select(MarginRule).order_by(MarginRule.id.asc()).with_for_update()
        )
        return list(result.all())

    # Возвращает правило маржи по id.
    async def get_margin_rule_by_id(self, rule_id: int) -> MarginRule | None:
        return await self.session.get(MarginRule, rule_id)

    # Возвращает правило по storefront-ключу.
    async def get_margin_rule(
        self,
        sport_type: str,
        subcategory_slug: str,
    ) -> MarginRule | None:
        return await self.session.scalar(
            select(MarginRule).where(
                MarginRule.sport_type == sport_type,
                MarginRule.subcategory_slug == subcategory_slug,
            )
        )

    # Обновляет правило маржи.
    async def update_margin_rule(
        self,
        rule: MarginRule,
        margin_percent: Decimal,
        is_active: bool | None = None,
    ) -> MarginRule:
        previous_margin_percent = Decimal(rule.margin_percent)
        if previous_margin_percent != margin_percent:
            self.session.add(
                MarginRuleHistory(
                    margin_rule_id=rule.id,
                    previous_margin_percent=previous_margin_percent,
                    margin_percent=margin_percent,
                )
            )
        rule.margin_percent = margin_percent
        if is_active is not None:
            rule.is_active = is_active
        self.session.add(rule)
        await self.session.commit()
        await self.session.refresh(rule)
        return rule

    # Возвращает последние изменения наценки правила.
    async def list_margin_rule_history(
        self,
        rule_id: int,
        limit: int = 20,
    ) -> list[MarginRuleHistory]:
        result = await self.session.scalars(
            select(MarginRuleHistory)
            .where(MarginRuleHistory.margin_rule_id == rule_id)
            .order_by(MarginRuleHistory.created_at.desc(), MarginRuleHistory.id.desc())
            .limit(limit)
        )
        return list(result.all())

    # Возвращает L2, которые однозначно покрыты активным exact-правилом.
    @staticmethod
    def _mapped_category_l2(
        sport_type: str,
        rules: list[MarginRule],
    ) -> set[str]:
        active_exact = {
            rule.subcategory_slug
            for rule in rules
            if rule.sport_type == sport_type
            and rule.is_active
            and rule.subcategory_slug != FALLBACK_SUBCATEGORY_SLUG
        }
        matches_by_l2: dict[str, list[str]] = {}
        for group in CATALOG_SUBCATEGORIES.get(sport_type, ()):
            for category_l2 in group.category_l2:
                matches_by_l2.setdefault(category_l2, []).append(group.slug)
        return {
            category_l2
            for category_l2, matches in matches_by_l2.items()
            if len(matches) == 1 and matches[0] in active_exact
        }

    # Собирает SQL-фильтры группы без Python-фильтрации каталога.
    @classmethod
    def _group_filters(
        cls,
        rule: MarginRule,
        rules: list[MarginRule],
        storefront_only: bool,
    ) -> list:
        filters = [Product.sport_type == rule.sport_type]
        if rule.subcategory_slug == FALLBACK_SUBCATEGORY_SLUG:
            mapped_l2 = cls._mapped_category_l2(rule.sport_type, rules)
            if mapped_l2:
                filters.append(
                    or_(
                        Product.category_l2.is_(None),
                        Product.category_l2.notin_(mapped_l2),
                    )
                )
        else:
            group = next(
                (
                    item
                    for item in CATALOG_SUBCATEGORIES.get(rule.sport_type, ())
                    if item.slug == rule.subcategory_slug
                ),
                None,
            )
            if group is None:
                filters.append(Product.id.is_(None))
            else:
                filters.append(Product.category_l2.in_(group.category_l2))
        if storefront_only:
            hidden_brand = select(CatalogHiddenBrand.brand).where(
                CatalogHiddenBrand.brand == Product.brand
            )
            filters.extend(
                (
                    Product.is_active.is_(True),
                    Product.catalog_in_stock.is_(True),
                    exists(
                        select(1)
                        .select_from(ProductStorefrontPlacement)
                        .join(
                            StorefrontMappingRelease,
                            StorefrontMappingRelease.id
                            == ProductStorefrontPlacement.release_id,
                        )
                        .where(
                            ProductStorefrontPlacement.product_id == Product.id,
                            StorefrontMappingRelease.status == RELEASE_STATUS_ACTIVE,
                        )
                    ),
                    ~hidden_brand.exists(),
                )
            )
        return filters

    # Считает товары группы для admin total/storefront counters.
    async def count_group_products(
        self,
        rule: MarginRule,
        rules: list[MarginRule],
        storefront_only: bool,
    ) -> int:
        stmt = select(func.count(Product.id)).where(
            *self._group_filters(rule, rules, storefront_only)
        )
        return int(await self.session.scalar(stmt) or 0)

    # Загружает и блокирует следующую storefront-порцию с вариантами.
    async def load_repricing_batch(
        self,
        rule: MarginRule,
        rules: list[MarginRule],
        cursor_product_id: int | None,
        batch_size: int,
    ) -> list[Product]:
        filters = self._group_filters(rule, rules, storefront_only=True)
        if cursor_product_id is not None:
            filters.append(Product.id > cursor_product_id)
        stmt = (
            select(Product)
            .where(*filters)
            .order_by(Product.id.asc())
            .limit(batch_size)
            .options(selectinload(Product.variants))
            .with_for_update()
        )
        products = list((await self.session.scalars(stmt)).all())
        product_ids = [product.id for product in products]
        if product_ids:
            await self.session.scalars(
                select(ProductVariant)
                .where(ProductVariant.product_id.in_(product_ids))
                .with_for_update()
            )
        return products

    # Создаёт запись batch-переоценки для текущих версий правила и settings.
    async def create_recalculation_job(
        self,
        rule: MarginRule,
        settings: PricingSettings,
        total_count: int,
    ) -> PricingRecalculationJob:
        job = PricingRecalculationJob(
            margin_rule_id=rule.id,
            status="queued",
            margin_percent=rule.margin_percent,
            rule_version=rule.updated_at,
            settings_version=settings.updated_at,
            total_count=total_count,
        )
        self.session.add(job)
        await self.session.commit()
        await self.session.refresh(job)
        return job

    # Сохраняет RQ id после успешной постановки job в очередь.
    async def set_recalculation_rq_job_id(
        self,
        job: PricingRecalculationJob,
        rq_job_id: str,
    ) -> None:
        job.rq_job_id = rq_job_id
        self.session.add(job)
        await self.session.commit()

    # Завершает job ошибкой, если RQ не принял задачу.
    async def mark_recalculation_enqueue_failed(
        self,
        job: PricingRecalculationJob,
        message: str,
    ) -> None:
        job.status = "failed"
        job.error_message = message[:4000]
        job.finished_at = utc_now_naive()
        self.session.add(job)
        await self.session.commit()

    # Возвращает pricing job по id с опциональной блокировкой.
    async def get_recalculation_job(
        self,
        job_id: int,
        for_update: bool = False,
    ) -> PricingRecalculationJob | None:
        stmt = select(PricingRecalculationJob).where(
            PricingRecalculationJob.id == job_id
        )
        if for_update:
            stmt = stmt.with_for_update()
        return await self.session.scalar(stmt)

    # Возвращает текущий активный job правила.
    async def get_active_recalculation_job(
        self,
        rule_id: int,
    ) -> PricingRecalculationJob | None:
        return await self.session.scalar(
            select(PricingRecalculationJob)
            .where(
                PricingRecalculationJob.margin_rule_id == rule_id,
                PricingRecalculationJob.status.in_(("queued", "running")),
            )
            .order_by(PricingRecalculationJob.id.desc())
            .limit(1)
        )

    # Возвращает последний завершённый запуск правила.
    async def get_latest_finished_recalculation_job(
        self,
        rule_id: int,
    ) -> PricingRecalculationJob | None:
        return await self.session.scalar(
            select(PricingRecalculationJob)
            .where(
                PricingRecalculationJob.margin_rule_id == rule_id,
                PricingRecalculationJob.status.in_(
                    ("succeeded", "failed", "superseded")
                ),
            )
            .order_by(PricingRecalculationJob.id.desc())
            .limit(1)
        )

    # Возвращает страницу видимых fallback-товаров без загрузки всего каталога.
    async def list_unmapped_products(
        self,
        fallback_rule: MarginRule,
        rules: list[MarginRule],
        page: int,
        page_size: int,
    ) -> tuple[list[Product], int]:
        filters = self._group_filters(fallback_rule, rules, storefront_only=True)
        total = int(
            await self.session.scalar(select(func.count(Product.id)).where(*filters))
            or 0
        )
        stmt = (
            select(Product)
            .where(*filters)
            .order_by(Product.id.asc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        return list((await self.session.scalars(stmt)).all()), total

    # Сохраняет или обновляет ошибку товара для безопасного retry.
    async def save_recalculation_error(
        self,
        job_id: int,
        product_id: int,
        message: str,
    ) -> None:
        error = await self.session.scalar(
            select(PricingRecalculationJobError).where(
                PricingRecalculationJobError.pricing_job_id == job_id,
                PricingRecalculationJobError.product_id == product_id,
            )
        )
        if error is None:
            error = PricingRecalculationJobError(
                pricing_job_id=job_id,
                product_id=product_id,
                error_message=message[:4000],
            )
        else:
            error.error_message = message[:4000]
        self.session.add(error)

    # Проверяет, что курс устарел более суток.
    @staticmethod
    def is_rate_stale(settings: PricingSettings) -> bool:
        if not settings.eur_rate_updated_at:
            return True
        return settings.eur_rate_updated_at < utc_now_naive() - timedelta(days=1)
