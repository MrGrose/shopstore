from fastapi import Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.storefront_auth_cookie import set_storefront_auth_cookie
from src.core.guest_cart import read_guest_cart_id
from src.core.security import create_access_token
from src.models.user import User
from src.services.cart_service import CartService
from src.services.referral_service import ReferralService


# Единый post-login pipeline: корзина, referral, cookie, JWT.
async def finalize_login(
    session: AsyncSession,
    user: User,
    request: Request,
    response: Response,
    referral_code: str | None = None,
) -> tuple[str, User]:
    referral_svc = ReferralService(session)
    if referral_code and referral_code.strip():
        result = await referral_svc.attribute_referrer(user, referral_code.strip())
        user = result.user
    user = await referral_svc.ensure_referral_code(user)

    guest_cart_id = read_guest_cart_id(request)
    if guest_cart_id:
        await CartService(session).merge_guest_cart(guest_cart_id, user.id)

    access_token = create_access_token(user.id)
    set_storefront_auth_cookie(response, access_token)
    return access_token, user
