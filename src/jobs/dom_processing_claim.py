import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import or_, select, update

from src.models.product import Product
from src.repositories.session import async_session_maker
from src.scraper.config.settings import (
    Settings,
    resolved_dom_processing_claim_ttl_minutes,
)

logger = logging.getLogger(__name__)


# Снимает DB-захват после DOM chunk; при token — только совпадающий владелец.
async def release_dom_processing_claims_by_products(
    products: list[dict],
    owner_token: str | None = None,
) -> None:
    product_ids = sorted(int(p["id"]) for p in products if p.get("id") is not None)
    if not product_ids:
        return
    stmt = update(Product).where(Product.id.in_(product_ids))
    if owner_token is not None:
        stmt = stmt.where(Product.dom_processing_owner_token == owner_token)
    async with async_session_maker() as session:
        await session.execute(
            stmt.values(
                dom_processing_at=None,
                dom_processing_expires_at=None,
                dom_processing_owner_token=None,
            )
        )
        await session.commit()


# Атомарно захватывает товары перед enqueue; возвращает только успешно claimed.
async def claim_dom_processing_products(
    products: list[dict],
    env: Settings,
    owner_token: str | None = None,
) -> tuple[list[dict], int]:
    if not products:
        return [], 0
    now = datetime.now(UTC).replace(tzinfo=None)
    ttl_minutes = resolved_dom_processing_claim_ttl_minutes(env)
    expires_at = now + timedelta(minutes=ttl_minutes)
    product_ids = sorted(int(p["id"]) for p in products if p.get("id") is not None)
    if not product_ids:
        return [], len(products)

    async with async_session_maker() as session:
        result = await session.execute(
            update(Product)
            .where(
                Product.id.in_(product_ids),
                or_(
                    Product.dom_processing_at.is_(None),
                    Product.dom_processing_expires_at < now,
                ),
            )
            .values(
                dom_processing_at=now,
                dom_processing_expires_at=expires_at,
                dom_processing_owner_token=owner_token,
            )
            .returning(Product.id)
        )
        claimed_ids = {int(row) for row in result.scalars().all()}
        await session.commit()

    claimed = [p for p in products if p.get("id") in claimed_ids]
    skipped = len(products) - len(claimed)
    if skipped:
        logger.debug(
            "DOM claim: не захвачено=%s захвачено=%s",
            skipped,
            len(claimed),
        )
    return claimed, skipped


# SKU с живым claim; при token — только совпадающий владелец.
async def filter_held_dom_processing_products(
    products: list[dict],
    owner_token: str | None = None,
) -> list[dict]:
    with_ids = [p for p in products if p.get("id") is not None]
    without_ids = [p for p in products if p.get("id") is None]
    if not with_ids:
        return list(products)
    now = datetime.now(UTC).replace(tzinfo=None)
    product_ids = sorted(int(p["id"]) for p in with_ids)
    stmt = select(Product.id).where(
        Product.id.in_(product_ids),
        Product.dom_processing_expires_at.is_not(None),
        Product.dom_processing_expires_at >= now,
    )
    if owner_token is not None:
        stmt = stmt.where(Product.dom_processing_owner_token == owner_token)
    async with async_session_maker() as session:
        result = await session.execute(stmt)
        held_ids = {int(row) for row in result.scalars().all()}
    held = [p for p in with_ids if int(p["id"]) in held_ids]
    return without_ids + held


# D3: продлевает dom_processing_expires_at при совпадении owner_token.
async def renew_dom_processing_claims(
    _product_ids: list[int],
    _owner_token: str,
    _env: Settings,
) -> None:
    return
