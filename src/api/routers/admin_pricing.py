from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.exc import OperationalError, ProgrammingError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import require_admin_user
from src.deps import get_db
from src.schemas.pricing import (
    MarginRuleSchema,
    MarginRuleUpdate,
    PricingSettingsSchema,
    PricingSettingsUpdate,
    PromoCodeCreate,
    PromoCodeSchema,
    PromoCodeUpdate,
)
from src.services.pricing_service import PricingService
from src.services.promo_service import PromoService

router = APIRouter(
    prefix="/admin/pricing",
    tags=["admin-pricing"],
    dependencies=[Depends(require_admin_user)],
)


def _raise_pricing_unavailable(exc: Exception) -> HTTPException:
    if isinstance(exc, OperationalError):
        message = (
            "Модуль цен недоступен: "
            "нет подключения к БД (проверьте host/port БД и запуск сервиса)"
        )
    elif isinstance(exc, ProgrammingError):
        message = "Модуль цен недоступен: структура БД неактуальна (проверьте миграции)"
    else:
        message = "Модуль цен недоступен: проверьте подключение к БД и миграции"
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=message,
    )


@router.get("/health", summary="Диагностика модуля цен")
async def pricing_health(db: AsyncSession = Depends(get_db)) -> dict[str, str | bool]:
    try:
        await db.execute(text("select 1"))
        settings = await PricingService(db).get_settings()
        rules = await PricingService(db).get_margin_rules()
        return {
            "ok": True,
            "db_connection": "ok",
            "settings_loaded": bool(settings),
            "margin_rules_count": str(len(rules)),
        }
    except OperationalError:
        return {
            "ok": False,
            "db_connection": "failed",
            "detail": "Нет подключения к БД.",
        }
    except ProgrammingError:
        return {
            "ok": False,
            "db_connection": "ok",
            "detail": "Нужны миграции.",
        }
    except SQLAlchemyError as exc:
        raw_message = str(exc).strip().replace("\n", " ")
        compact_message = raw_message[:240] if raw_message else "n/a"
        return {
            "ok": False,
            "db_connection": "unknown",
            "detail": "SQLAlchemy ошибка. Проверьте логи API.",
            "error_type": exc.__class__.__name__,
            "error": compact_message,
        }


@router.get("/settings", response_model=PricingSettingsSchema, summary="Настройки цен")
async def get_pricing_settings(
    db: AsyncSession = Depends(get_db),
) -> PricingSettingsSchema:
    try:
        pricing = await PricingService(db).get_settings()
        return PricingSettingsSchema.model_validate(pricing)
    except SQLAlchemyError as exc:
        raise _raise_pricing_unavailable(exc) from exc


@router.patch(
    "/settings", response_model=PricingSettingsSchema, summary="Обновить настройки цен"
)
async def update_pricing_settings(
    payload: PricingSettingsUpdate,
    db: AsyncSession = Depends(get_db),
) -> PricingSettingsSchema:
    try:
        service = PricingService(db)
        settings = await service.get_settings()
        pricing = await service.repo.update_settings(
            settings=settings,
            eur_rate=payload.eur_rate,
            markup_multiplier=payload.markup_multiplier,
            delivery_fee_eur=payload.delivery_fee_eur,
        )
        return PricingSettingsSchema.model_validate(pricing)
    except SQLAlchemyError as exc:
        raise _raise_pricing_unavailable(exc) from exc


@router.post(
    "/refresh-rate", response_model=PricingSettingsSchema, summary="Обновить курс EUR"
)
async def refresh_eur_rate(db: AsyncSession = Depends(get_db)) -> PricingSettingsSchema:
    service = PricingService(db)
    try:
        pricing = await service.refresh_eur_rate()
        return PricingSettingsSchema.model_validate(pricing)
    except SQLAlchemyError as exc:
        raise _raise_pricing_unavailable(exc) from exc
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Не удалось обновить курс EUR: проверьте внешний API или сеть сервера"
            ),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Не удалось обновить курс EUR",
        ) from exc


@router.get(
    "/margins", response_model=list[MarginRuleSchema], summary="Список правил маржи"
)
async def list_margin_rules(
    db: AsyncSession = Depends(get_db),
) -> list[MarginRuleSchema]:
    try:
        return await PricingService(db).get_margin_rules()
    except SQLAlchemyError as exc:
        raise _raise_pricing_unavailable(exc) from exc


@router.patch(
    "/margins/{rule_id}",
    response_model=MarginRuleSchema,
    summary="Обновить правило маржи",
)
async def update_margin_rule(
    rule_id: int,
    payload: MarginRuleUpdate,
    db: AsyncSession = Depends(get_db),
) -> MarginRuleSchema:
    try:
        service = PricingService(db)
        rule = await service.repo.get_margin_rule_by_id(rule_id)
        if not rule:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Правило маржи не найдено"
            )
        return await service.repo.update_margin_rule(
            rule=rule,
            margin_percent=payload.margin_percent,
            is_active=payload.is_active,
        )
    except SQLAlchemyError as exc:
        raise _raise_pricing_unavailable(exc) from exc


@router.post("/recalculate", summary="Пересчитать цены товаров")
async def recalculate_prices(
    rule_id: int | None = None,
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    try:
        service = PricingService(db)
        if rule_id is None:
            updated = await service.recalculate_all_products()
            return {"updated": updated}
        rule = await service.repo.get_margin_rule_by_id(rule_id)
        if rule is None:
            raise ValueError("Правило не найдено")
        job = await service.enqueue_margin_rule_recalculation(rule)
        return {"job_id": job.id, "total": job.total_count}
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Ошибка пересчета цен: {str(exc)}",
        ) from exc
    except SQLAlchemyError as exc:
        raw_message = str(exc).strip().replace("\n", " ")
        compact_message = raw_message[:240] if raw_message else "n/a"
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Ошибка пересчета цен ({exc.__class__.__name__}): {compact_message}"
            ),
        ) from exc


@router.get(
    "/promos", response_model=list[PromoCodeSchema], summary="Список промокодов"
)
async def list_promos(db: AsyncSession = Depends(get_db)) -> list[PromoCodeSchema]:
    try:
        return await PromoService(db).list_promo_codes()
    except SQLAlchemyError as exc:
        raise _raise_pricing_unavailable(exc) from exc


@router.post("/promos", response_model=PromoCodeSchema, summary="Создать промокод")
async def create_promo(
    payload: PromoCodeCreate, db: AsyncSession = Depends(get_db)
) -> PromoCodeSchema:
    try:
        return await PromoService(db).create_promo_code(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ошибка создания промокода",
        ) from exc
    except SQLAlchemyError as exc:
        raise _raise_pricing_unavailable(exc) from exc


@router.patch(
    "/promos/{promo_id}", response_model=PromoCodeSchema, summary="Обновить промокод"
)
async def update_promo(
    promo_id: int,
    payload: PromoCodeUpdate,
    db: AsyncSession = Depends(get_db),
) -> PromoCodeSchema:
    try:
        return await PromoService(db).update_promo_code(
            promo_id=promo_id, payload=payload.model_dump(exclude_unset=True)
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ошибка обновления промокода",
        ) from exc
    except SQLAlchemyError as exc:
        raise _raise_pricing_unavailable(exc) from exc


@router.delete(
    "/promos/{promo_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить промокод",
)
async def delete_promo(promo_id: int, db: AsyncSession = Depends(get_db)) -> None:
    try:
        await PromoService(db).delete_promo_code(promo_id=promo_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except SQLAlchemyError as exc:
        raise _raise_pricing_unavailable(exc) from exc
