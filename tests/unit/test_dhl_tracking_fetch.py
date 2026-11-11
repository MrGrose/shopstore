import json

import pytest

from src.services.orders.dhl_tracking import (
    DhlTrackingFetchError,
    _looks_like_challenge,
    _looks_like_html_body,
    fetch_dhl_tracking,
    normalize_dhl_payload,
)

HTML_FEHLERMELDUNG = (
    "<!DOCTYPE html><html><head><title>Fehlermeldung</title></head>"
    "<body>Technischer Fehler</body></html>"
)
VALID_PAYLOAD = {
    "sendungen": [
        {
            "sendungsdetails": {
                "sendungsnummern": {"sendungsnummer": "CJ687844375DE"},
                "sendungsverlauf": {
                    "status": "Die Sendung wurde zugestellt.",
                    "events": [
                        {
                            "status": "Die Sendung wurde zugestellt.",
                            "datum": "01.08.2026 12:00",
                            "ort": "Berlin",
                        }
                    ],
                },
            }
        }
    ]
}


@pytest.fixture(autouse=True)
def _disable_dhl_browser_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.core.config import settings

    monkeypatch.setattr(settings, "DHL_TRACKING_USE_BROWSER", False)


def test_looks_like_challenge_detects_fehlermeldung() -> None:
    assert _looks_like_challenge(HTML_FEHLERMELDUNG) is True


def test_looks_like_html_body_detects_angle_bracket() -> None:
    assert _looks_like_html_body(HTML_FEHLERMELDUNG, "text/html") is True


def test_looks_like_html_body_ignores_json_content_type() -> None:
    assert _looks_like_html_body("<not-really-json", "application/json") is False


@pytest.mark.asyncio
async def test_fetch_dhl_tracking_html_fehlermeldung_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.services.orders import dhl_tracking

    class Response:
        def __init__(self) -> None:
            self.text = HTML_FEHLERMELDUNG
            self.status_code = 200
            self.headers = {"content-type": "text/html"}

        def json(self) -> dict:
            return json.loads(self.text)

    class Session:
        async def __aenter__(self) -> "Session":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, url: str, **kwargs: object) -> Response:
            return Response()

    monkeypatch.setattr(dhl_tracking, "AsyncStealthSession", Session)

    with pytest.raises(DhlTrackingFetchError) as err:
        await fetch_dhl_tracking("CJ687844375DE")

    assert err.value.code == "blocked"
    assert err.value.is_blocked is True


@pytest.mark.asyncio
async def test_fetch_dhl_tracking_valid_json_parses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.services.orders import dhl_tracking

    class Response:
        def __init__(self) -> None:
            self.text = json.dumps(VALID_PAYLOAD)
            self.status_code = 200
            self.headers = {"content-type": "application/json"}

        def json(self) -> dict:
            return json.loads(self.text)

    class Session:
        async def __aenter__(self) -> "Session":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, url: str, **kwargs: object) -> Response:
            return Response()

    monkeypatch.setattr(dhl_tracking, "AsyncStealthSession", Session)

    result = await fetch_dhl_tracking("CJ687844375DE")

    assert result["carrier_source"] == "dhl"
    assert result["events"]
    assert normalize_dhl_payload(VALID_PAYLOAD, "CJ687844375DE")["tracking_number"]


@pytest.mark.asyncio
async def test_fetch_dhl_tracking_http_403_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.services.orders import dhl_tracking

    class Response:
        def __init__(self) -> None:
            self.text = ""
            self.status_code = 403
            self.headers = {}

        def json(self) -> dict:
            return {}

    class Session:
        async def __aenter__(self) -> "Session":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, url: str, **kwargs: object) -> Response:
            return Response()

    monkeypatch.setattr(dhl_tracking, "AsyncStealthSession", Session)

    with pytest.raises(DhlTrackingFetchError) as err:
        await fetch_dhl_tracking("CJ687844375DE")

    assert err.value.code == "blocked"
    assert err.value.is_blocked is True


@pytest.mark.asyncio
async def test_fetch_dhl_tracking_retries_via_proxy_on_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from src.services.orders import dhl_tracking

    init_kwargs: list[dict[str, object]] = []
    get_count = 0

    class Response:
        def __init__(self, body: str, status_code: int = 200) -> None:
            self.text = body
            self.status_code = status_code
            self.headers = {
                "content-type": (
                    "application/json" if body.startswith("{") else "text/html"
                )
            }

        def json(self) -> dict:
            return json.loads(self.text)

    class Session:
        def __init__(self, **kwargs: object) -> None:
            init_kwargs.append(kwargs)

        async def __aenter__(self) -> "Session":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def get(self, url: str, **kwargs: object) -> Response:
            nonlocal get_count
            get_count += 1
            if get_count == 1:
                return Response(HTML_FEHLERMELDUNG)
            return Response(json.dumps(VALID_PAYLOAD))

    monkeypatch.setattr(dhl_tracking, "AsyncStealthSession", Session)

    result = await fetch_dhl_tracking(
        "CJ687844375DE",
        proxy_url="http://proxy.local:8080",
    )

    assert result["carrier_source"] == "dhl"
    assert get_count == 2
    assert init_kwargs[0] == {}
    assert init_kwargs[1] == {
        "proxies": {
            "https": "http://proxy.local:8080",
            "http": "http://proxy.local:8080",
        }
    }


@pytest.mark.asyncio
async def test_sync_dhl_uses_browser_fallback_when_http_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import MagicMock

    from src.core.config import settings
    from src.services.orders import supplier_tracking
    from src.services.orders.dhl_tracking import DhlTrackingFetchError

    monkeypatch.setattr(settings, "DHL_TRACKING_USE_BROWSER", True)

    order = MagicMock()
    order.supplier_tracking_id = "CJ687844375DE"
    order.supplier_tracking_failures = 0
    order.supplier_tracking_json = {}
    order.supplier_tracking_updated_at = None

    async def _blocked_fetch(*args: object, **kwargs: object) -> dict:
        raise DhlTrackingFetchError("blocked", "blocked", True)

    browser_payload = normalize_dhl_payload(VALID_PAYLOAD, "CJ687844375DE")

    async def _browser_fetch(piececode: str) -> dict:
        assert piececode == "CJ687844375DE"
        return browser_payload

    monkeypatch.setattr(supplier_tracking, "fetch_dhl_tracking", _blocked_fetch)

    svc = supplier_tracking.SupplierTrackingService(
        MagicMock(),
        dhl_browser_fetch=_browser_fetch,
    )

    normalized, dhl_error = await svc._try_fetch_dhl("CJ687844375DE")
    assert dhl_error is None
    assert normalized is not None
    now = supplier_tracking.utc_now_naive()
    changed = svc._apply_dhl_normalized(order, normalized, now)

    assert changed is True
    assert order.supplier_tracking_sync_state in {"active", "delivered"}
