from typing import NoReturn

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import JSONResponse

from src.services.verification.phone.errors import (
    PhoneCallConflictError,
    PhoneCallInputError,
    PhoneCallUnavailableError,
)


# Email остаётся только способом подтверждения уведомлений заказа.
def reject_email_login() -> NoReturn:
    raise HTTPException(
        status_code=status.HTTP_410_GONE,
        detail="Вход по email больше не поддерживается",
    )


# Возвращает IP клиента с учётом X-Forwarded-For.
def client_ip_from_request(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip() or None
    if request.client:
        return request.client.host
    return None


# Возвращает 422 для некорректных входных данных call flow.
async def _phone_call_input_error_response(
    _request: Request,
    exc: PhoneCallInputError,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": str(exc)},
    )


# Возвращает 409 для недопустимого состояния call flow.
async def _phone_call_conflict_error_response(
    _request: Request,
    exc: PhoneCallConflictError,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"detail": str(exc)},
    )


# Возвращает 503 при временной недоступности call provider.
async def _phone_call_unavailable_error_response(
    _request: Request,
    exc: PhoneCallUnavailableError,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        content={"detail": str(exc)},
    )


# Регистрирует централизованные HTTP-ответы ошибок phone call flow.
def register_phone_call_exception_responses(app: FastAPI) -> None:
    app.add_exception_handler(PhoneCallInputError, _phone_call_input_error_response)
    app.add_exception_handler(
        PhoneCallConflictError,
        _phone_call_conflict_error_response,
    )
    app.add_exception_handler(
        PhoneCallUnavailableError,
        _phone_call_unavailable_error_response,
    )
