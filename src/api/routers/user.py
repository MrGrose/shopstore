from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.deps import get_current_user, require_admin_user
from src.api.http_utils import client_ip_from_request
from src.api.user_me import build_user_me_schema
from src.api.user_schema import build_user_schema
from src.core.config import settings
from src.core.redis import async_redis
from src.core.referral_cookie import (
    REFERRAL_COOKIE_NAME,
    clear_referral_cookie_response,
    should_clear_referral_cookie,
)
from src.deps import get_db
from src.models.user import User
from src.schemas.auth import (
    EmailSendCodeRequest,
    EmailVerifyRequest,
    PhoneSendCodeRequest,
    PhoneVerifyRequest,
    TelegramLinkResponse,
    TelegramUnifiedLoginRequest,
)
from src.schemas.order import DeliveryAddressCreate
from src.schemas.referral import MyReferrerSchema, ReferrerApplyResponse
from src.schemas.user import (
    IdentitySchema,
    UserCreate,
    UserMeSchema,
    UserMeUpdate,
    UserSchema,
    UserUpdate,
)
from src.services.auth.telegram_link import TelegramLinkService
from src.services.auth_service import AuthService
from src.services.delivery_profile_service import DeliveryProfileService
from src.services.email_otp_service import EmailOtpService
from src.services.identity_service import IdentityService
from src.services.referral_service import ReferralService
from src.services.user_service import UserService
from src.services.verification.phone.service import PhoneVerificationService
from src.utils.phone import normalize_ru_mobile_phone

router = APIRouter(prefix="/users", tags=["users"])


# Возвращает текущего пользователя по Bearer-токену (включая роль).
@router.get("/me", response_model=UserMeSchema, summary="Текущий пользователь")
async def get_me(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserMeSchema:
    return await build_user_me_schema(db, current_user)


# Обновляет имя текущего пользователя.
@router.patch("/me", response_model=UserMeSchema, summary="Обновить профиль")
async def patch_me(
    payload: UserMeUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserMeSchema:
    if payload.name is not None:
        normalized = payload.name.strip() or None
        current_user.name = normalized
        db.add(current_user)
        await db.commit()
        await db.refresh(current_user)
    user = await ReferralService(db).ensure_referral_code(current_user)
    return await build_user_me_schema(db, user)


# Возвращает сохранённый профиль доставки текущего пользователя.
@router.get(
    "/me/delivery-profile",
    response_model=DeliveryAddressCreate | None,
    summary="Профиль доставки",
)
async def get_my_delivery_profile(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DeliveryAddressCreate | None:
    profile = await DeliveryProfileService(db).get_profile(current_user.id)
    if profile is None:
        return None
    return DeliveryAddressCreate.model_validate(profile, from_attributes=True)


# Сохраняет профиль доставки текущего пользователя.
@router.put(
    "/me/delivery-profile",
    response_model=DeliveryAddressCreate,
    summary="Обновить профиль доставки",
)
async def put_my_delivery_profile(
    payload: DeliveryAddressCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> DeliveryAddressCreate:
    profile = await DeliveryProfileService(db).upsert_from_delivery(
        current_user.id,
        payload,
    )
    return DeliveryAddressCreate.model_validate(profile, from_attributes=True)


# Привязка к рефереру из cookie (после отвязки или новой ссылки).
@router.post(
    "/me/referrer/apply",
    response_model=ReferrerApplyResponse,
    summary="Применить реф-код",
)
async def apply_my_referrer(
    request: Request,
    response: Response,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> ReferrerApplyResponse:
    referral_code = (request.cookies.get(REFERRAL_COOKIE_NAME) or "").strip() or None
    referral_svc = ReferralService(db)
    result = await referral_svc.attribute_referrer(current_user, referral_code)
    await referral_svc.ensure_referral_code(result.user)
    if should_clear_referral_cookie(result.status):
        clear_referral_cookie_response(
            response,
            secure=request.url.scheme == "https",
        )
    return ReferrerApplyResponse(status=result.status)


# Список привязанных способов входа.
@router.get(
    "/me/identities",
    response_model=list[IdentitySchema],
    summary="Способы входа",
)
async def list_my_identities(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[IdentitySchema]:
    me = await build_user_me_schema(db, current_user)
    return me.identities


# Отправляет OTP для привязки email к текущему аккаунту.
@router.post(
    "/me/identities/email/send-code",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="OTP для привязки email",
)
async def link_email_send_code(
    request: Request,
    payload: EmailSendCodeRequest,
    current_user: User = Depends(get_current_user),
) -> Response:
    otp_service = EmailOtpService()
    try:
        await otp_service.send_code(
            payload.email,
            current_user.id,
            client_ip=client_ip_from_request(request),
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# Подтверждает OTP и привязывает email к текущему аккаунту.
@router.post(
    "/me/identities/email/verify",
    response_model=UserMeSchema,
    summary="Привязать email",
)
async def link_email_verify(
    payload: EmailVerifyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserMeSchema:
    otp_service = EmailOtpService()
    try:
        await otp_service.verify_code(
            payload.email,
            payload.code,
            current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    try:
        user = await IdentityService(db).link_email_to_user(current_user, payload.email)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return await build_user_me_schema(db, user)


# Отправляет verification code для привязки телефона к текущему аккаунту.
@router.post(
    "/me/identities/phone/send-code",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Код для привязки телефона",
)
async def link_phone_send_code(
    request: Request,
    payload: PhoneSendCodeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Response:
    try:
        normalize_ru_mobile_phone(payload.phone)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    identity_svc = IdentityService(db)
    if await identity_svc.identity_repo.get_phone_for_user(current_user.id) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Телефон уже привязан к другому аккаунту",
        )

    verification_service = PhoneVerificationService()
    try:
        await verification_service.send_code(
            phone=payload.phone,
            client_ip=client_ip_from_request(request),
            purpose="link",
            user_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# Подтверждает код и привязывает телефон к текущему аккаунту.
@router.post(
    "/me/identities/phone/verify",
    response_model=UserMeSchema,
    summary="Привязать телефон",
)
async def link_phone_verify(
    payload: PhoneVerifyRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserMeSchema:
    try:
        phone_e164 = normalize_ru_mobile_phone(payload.phone)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    verification_service = PhoneVerificationService()
    try:
        await verification_service.verify_code(
            phone=payload.phone,
            code=payload.code,
            purpose="link",
            user_id=current_user.id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        ) from exc
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    try:
        user = await IdentityService(db).link_phone_to_user(current_user, phone_e164)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return await build_user_me_schema(db, user)


# Привязывает Telegram Login Widget к текущему аккаунту.
@router.post(
    "/me/identities/telegram",
    response_model=UserMeSchema,
    summary="Привязать Telegram",
)
async def link_telegram_identity(
    payload: TelegramUnifiedLoginRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> UserMeSchema:
    if payload.source != "widget" or payload.id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Нужен source=widget и данные Telegram Login Widget",
        )
    auth_service = AuthService(db)
    try:
        widget_user = auth_service.validate_telegram_widget_payload(
            payload.model_dump(exclude_none=True)
        )
        user = await IdentityService(db).link_telegram_to_user(
            current_user,
            telegram_id=widget_user.id,
            telegram_username=widget_user.telegram_username,
            name=widget_user.name,
            photo_url=widget_user.photo_url,
        )
        user = await UserService(db).refresh_user_role_from_telegram_allowlist(user)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    return await build_user_me_schema(db, user)


# Создаёт одноразовую ссылку для привязки Telegram к текущему аккаунту.
@router.post(
    "/me/identities/telegram/link",
    response_model=TelegramLinkResponse,
    summary="Ссылка для привязки Telegram",
)
async def create_telegram_link(
    current_user: User = Depends(get_current_user),
) -> TelegramLinkResponse:
    bot_username = (settings.TG_BOT_USERNAME or "").strip().lstrip("@")
    if not bot_username:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Привязка Telegram временно недоступна",
        )
    token_service = TelegramLinkService(
        async_redis(),
        ttl_seconds=settings.TELEGRAM_LINK_TOKEN_TTL_SECONDS,
    )
    token = await token_service.create_token(current_user.id)
    return TelegramLinkResponse(
        url=f"https://t.me/{bot_username}?start=link_{token}",
        expires_in=settings.TELEGRAM_LINK_TOKEN_TTL_SECONDS,
    )


# Статус привязки покупателя к рефереру.
@router.get("/me/referrer", response_model=MyReferrerSchema, summary="Мой реферер")
async def get_my_referrer(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MyReferrerSchema:
    status_payload = await ReferralService(db).get_my_referrer_status(current_user)
    return MyReferrerSchema.model_validate(status_payload)


# Получает всех пользователей.
@router.get("/", response_model=list[UserSchema], summary="Получить всех пользователей")
async def get_users(
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> list[UserSchema]:
    user_svc = UserService(db)
    users = await user_svc.get_users()
    result: list[UserSchema] = []
    for user in users:
        result.append(await build_user_schema(db, user))
    return result


# Возвращает пользователя, создавая его при отсутствии.
@router.get("/{user_id}", response_model=UserSchema, summary="Получить пользователя")
async def get_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> UserSchema:
    user_svc = UserService(db)
    user = await user_svc.ensure_user(user_id=user_id)
    return await build_user_schema(db, user)


# Возвращает пользователя по telegram_id; 404 если не найден.
@router.get(
    "/telegram/{telegram_id}",
    response_model=UserSchema,
    summary="Получить пользователя по telegram_id",
)
async def get_user_by_telegram_id(
    telegram_id: int, db: AsyncSession = Depends(get_db)
) -> UserSchema:
    user_svc = UserService(db)
    user = await user_svc.get_by_telegram_id(telegram_id=telegram_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден"
        )
    return await build_user_schema(db, user)


# Создает нового пользователя.
@router.post(
    "/",
    response_model=UserSchema,
    status_code=status.HTTP_201_CREATED,
    summary="Создать пользователя",
)
async def create_user(
    user: UserCreate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> UserSchema:
    user_svc = UserService(db)
    created = await user_svc.create_user(user=user)
    return await build_user_schema(db, created)


# Обновляет пользователя; 404 если не найден.
@router.put("/{user_id}", response_model=UserSchema, summary="Обновить пользователя")
async def update_user(
    user_id: int,
    user: UserUpdate,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> UserSchema:
    user_svc = UserService(db)
    updated = await user_svc.update_user(user_id=user_id, user=user)
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден"
        )
    return await build_user_schema(db, updated)


# Удаляет пользователя; 404 если не найден.
@router.delete("/{user_id}", response_model=UserSchema, summary="Удалить пользователя")
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(require_admin_user),
) -> UserSchema:
    user_svc = UserService(db)
    try:
        deleted = await user_svc.delete_user(user_id=user_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Ошибка при удалении пользователя",
        )
    return await build_user_schema(db, deleted)
