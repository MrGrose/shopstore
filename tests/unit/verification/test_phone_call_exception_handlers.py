from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.api.http_utils import register_phone_call_exception_responses
from src.services.verification.phone.errors import (
    PhoneCallConflictError,
    PhoneCallInputError,
    PhoneCallUnavailableError,
)


def test_phone_call_errors_are_mapped_outside_router() -> None:
    app = FastAPI()
    register_phone_call_exception_responses(app)

    @app.get("/input")
    async def input_error() -> None:
        raise PhoneCallInputError("Некорректный телефон")

    @app.get("/conflict")
    async def conflict_error() -> None:
        raise PhoneCallConflictError("Подтверждение завершено")

    @app.get("/unavailable")
    async def unavailable_error() -> None:
        raise PhoneCallUnavailableError("Провайдер недоступен")

    client = TestClient(app)

    assert client.get("/input").status_code == 422
    assert client.get("/input").json() == {"detail": "Некорректный телефон"}
    assert client.get("/conflict").status_code == 409
    assert client.get("/unavailable").status_code == 503
