import logging

from fastapi import APIRouter, HTTPException, Request, Response, status

from src.api.http_utils import client_ip_from_request, reject_email_login
from src.core.config import settings
from src.core.referral_cookie import read_referral_cookie
from src.core.user_access import assert_user_can_authenticate
from src.repositories.session import async_session_maker
from src.schemas.auth import (
    MiniAppAuthProbeRequest,
    PhoneCallFlowResponse,
    PhoneCallStartRequest,
    PhoneCallVerifyRequest,
    PhoneLoginResponse,
    PhoneSendCodeRequest,
    PhoneSendCodeResponse,
    PhoneVerifyRequest,
    TelegramLoginResponse,
    TelegramUnifiedLoginRequest,
    UnifiedLoginRequest,
)
from src.services.auth.phone import PhoneAuthService, PhoneCallLoginService
from src.services.auth_service import AuthService
from src.services.identity_service import IdentityService
from src.services.login_finalize_service import finalize_login
from src.services.verification.phone.call_service import PhoneCallAuthService
from src.services.verification.phone.service import PhoneVerificationService
from src.utils.phone import normalize_ru_mobile_phone

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger(__name__)


# Диагностика Mini App: почему initData не дошёл до unified-login.
@router.post("/telegram/miniapp-probe", status_code=status.HTTP_204_NO_CONTENT)
async def telegram_miniapp_probe(payload: MiniAppAuthProbeRequest) -> Response:
    logger.info(
        "Mini App auth probe phase=%s platform=%s init_len=%s has_tg=%s has_webapp=%s "
        "version=%s inside=%s err=%s",
        payload.phase,
        payload.platform or "-",
        payload.init_data_len,
        payload.has_telegram,
        payload.has_webapp,
        payload.version or "-",
        payload.inside_webapp,
        payload.error_message or "-",
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# Общий handler Telegram-логина с finalize_login.
async def _telegram_login_handler(
    request: Request,
    response: Response,
    source: str,
    payload: dict[str, object],
) -> TelegramLoginResponse:
    logger.info(
        "Попытка входа через Telegram source=%s init_len=%s",
        source,
        len(str(payload.get("init_data") or "")),
    )
    referral_code = read_referral_cookie(request)
    async with async_session_maker() as session:
        auth_service = AuthService(session)
        try:
            user = await auth_service.authenticate_telegram_unified(
                source=source,
                payload=payload,
            )
            access_token, user = await finalize_login(
                session,
                user,
                request,
                response,
                referral_code=referral_code,
            )
        except ValueError as exc:
            logger.warning("Вход через Telegram отклонён: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(exc),
            ) from exc
    return TelegramLoginResponse(access_token=access_token, user=user)


# Отправляет OTP-код на email (legacy, отключён).
@router.post("/email/send-code", status_code=status.HTTP_204_NO_CONTENT)
async def email_send_code() -> Response:
    reject_email_login()


# Проверяет OTP и выполняет вход по email (legacy, отключён).
@router.post("/email/verify", response_model=TelegramLoginResponse)
async def email_verify() -> TelegramLoginResponse:
    reject_email_login()


# Общий handler phone verify-логина с finalize_login.
async def _phone_login_handler(
    request: Request,
    response: Response,
    phone: str,
    code: str,
) -> PhoneLoginResponse:
    referral_code = read_referral_cookie(request)
    verification_service = PhoneVerificationService()
    try:
        await verification_service.verify_code(phone=phone, code=code, purpose="login")
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

    phone_e164 = normalize_ru_mobile_phone(phone)
    async with async_session_maker() as session:
        try:
            user, is_new_user = await PhoneAuthService(session).authenticate_by_phone(
                phone_e164
            )
            access_token, user = await finalize_login(
                session,
                user,
                request,
                response,
                referral_code=referral_code,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(exc),
            ) from exc
    return PhoneLoginResponse(
        access_token=access_token,
        user=user,
        is_new_user=is_new_user,
    )


# Отправляет verification code на телефон через Telegram Gateway.
@router.post("/phone/send-code", response_model=PhoneSendCodeResponse)
async def phone_send_code(
    request: Request,
    payload: PhoneSendCodeRequest,
) -> PhoneSendCodeResponse:
    if not settings.PHONE_VERIFICATION_CODE_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Вход по коду отключён",
        )
    try:
        phone_e164 = normalize_ru_mobile_phone(payload.phone)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    async with async_session_maker() as session:
        existing = await IdentityService(session).resolve_user_by_phone(phone_e164)
        if existing is not None:
            try:
                assert_user_can_authenticate(existing)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=str(exc),
                ) from exc

    verification_service = PhoneVerificationService()
    try:
        expires_in = await verification_service.send_code(
            phone=payload.phone,
            client_ip=client_ip_from_request(request),
            purpose="login",
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
    return PhoneSendCodeResponse(expires_in=expires_in)


# Проверяет phone code и выполняет вход.
@router.post("/phone/verify", response_model=PhoneLoginResponse)
async def phone_verify(
    request: Request,
    payload: PhoneVerifyRequest,
    response: Response,
) -> PhoneLoginResponse:
    if not settings.PHONE_VERIFICATION_CODE_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Вход по коду отключён",
        )
    try:
        normalize_ru_mobile_phone(payload.phone)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return await _phone_login_handler(
        request,
        response,
        payload.phone,
        payload.code,
    )


# Запускает первый звонок нового web phone auth flow.
@router.post("/phone/start", response_model=PhoneCallFlowResponse)
async def phone_call_start(
    request: Request,
    payload: PhoneCallStartRequest,
) -> PhoneCallFlowResponse:
    service = PhoneCallAuthService()
    flow = await service.start(
        payload.phone,
        client_ip_from_request(request),
    )
    return PhoneCallFlowResponse.model_validate(service.public_state(flow))


# Возвращает состояние flow и проверяет verification number у provider.
@router.get("/phone/{flow_id}", response_model=PhoneCallFlowResponse)
async def phone_call_status(flow_id: str) -> PhoneCallFlowResponse:
    service = PhoneCallAuthService()
    flow = await service.status(flow_id)
    return PhoneCallFlowResponse.model_validate(service.public_state(flow))


# Повторно запускает текущий способ после cooldown.
@router.post("/phone/{flow_id}/retry", response_model=PhoneCallFlowResponse)
async def phone_call_retry(request: Request, flow_id: str) -> PhoneCallFlowResponse:
    service = PhoneCallAuthService()
    flow = await service.retry(
        flow_id,
        client_ip_from_request(request),
    )
    return PhoneCallFlowResponse.model_validate(service.public_state(flow))


# Вручную переключает flow на следующий доступный способ.
@router.post("/phone/{flow_id}/switch", response_model=PhoneCallFlowResponse)
async def phone_call_switch(request: Request, flow_id: str) -> PhoneCallFlowResponse:
    service = PhoneCallAuthService()
    flow = await service.switch(
        flow_id,
        client_ip_from_request(request),
    )
    return PhoneCallFlowResponse.model_validate(service.public_state(flow))


# Проверяет код звонка и выполняет общий phone login finalize.
@router.post("/phone/{flow_id}/verify", response_model=PhoneLoginResponse)
async def phone_call_verify(
    request: Request,
    response: Response,
    flow_id: str,
    payload: PhoneCallVerifyRequest,
) -> PhoneLoginResponse:
    service = PhoneCallAuthService()
    await service.verify_code(flow_id, payload.code)
    result = await PhoneCallLoginService(service).complete(
        flow_id,
        request,
        response,
        referral_code=read_referral_cookie(request),
    )
    return PhoneLoginResponse.model_validate(result, from_attributes=True)


# Завершает подтверждённый verification number flow.
@router.post("/phone/{flow_id}/complete", response_model=PhoneLoginResponse)
async def phone_call_complete(
    request: Request,
    response: Response,
    flow_id: str,
) -> PhoneLoginResponse:
    result = await PhoneCallLoginService().complete(
        flow_id,
        request,
        response,
        referral_code=read_referral_cookie(request),
    )
    return PhoneLoginResponse.model_validate(result, from_attributes=True)


# Единый endpoint авторизации (telegram / email).
@router.post("/login", response_model=TelegramLoginResponse)
async def unified_login(
    request: Request,
    payload: UnifiedLoginRequest,
    response: Response,
) -> TelegramLoginResponse:
    source = payload.source
    if source is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Укажите source: miniapp или widget",
        )
    return await _telegram_login_handler(
        request,
        response,
        source,
        payload.model_dump(exclude_none=True),
    )


# Единый endpoint tg авторизации для mini app и сайта (backward compat).
@router.post("/telegram/unified-login", response_model=TelegramLoginResponse)
async def telegram_unified_login(
    request: Request,
    payload: TelegramUnifiedLoginRequest,
    response: Response,
) -> TelegramLoginResponse:
    return await _telegram_login_handler(
        request,
        response,
        payload.source,
        payload.model_dump(exclude_none=True),
    )


# Выход пользователя: очищает auth-cookie на серверной стороне.
@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout() -> Response:
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(
        key="access_token",
        path="/",
        samesite="lax",
        secure=False,
    )
    return response
