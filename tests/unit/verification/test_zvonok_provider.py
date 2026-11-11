import pytest

from src.integrations.zvonok.provider import ZvonokPhoneProvider


def test_zvonok_status_mapping():
    provider = ZvonokPhoneProvider()
    assert provider._map_status("in_process") == "pending"
    assert provider._map_status("pincode_ok") == "verified"
    assert provider._map_status("expires") == "expired"
    assert provider._map_status("pincode_nook") == "failed"
    assert provider._map_status("attempts_exc") == "failed"
    assert provider._map_status("compl_finished") == "pending"
    assert provider._map_status("") == "pending"


@pytest.mark.asyncio
async def test_zvonok_start_uses_post_form_data(monkeypatch):
    provider = ZvonokPhoneProvider()
    provider.public_key = "test-key"
    captured = {}

    async def fake_request(method: str, url: str, **kwargs):
        captured.update(method=method, url=url, kwargs=kwargs)
        return {
            "status": "ok",
            "data": {"call_id": 123, "pincode": 42},
        }

    monkeypatch.setattr(provider, "_request_json", fake_request)
    result = await provider.start("flash_call", "+79991234567")
    assert captured["method"] == "POST"
    assert str(captured["url"]).endswith("/phones/flashcall/")
    assert type(captured["kwargs"]["data"]).__name__ == "FormData"
    assert captured["kwargs"]["data"].is_multipart
    assert result.external_id == "123"
    assert result.code == "0042"


@pytest.mark.asyncio
async def test_zvonok_status_uses_documented_get(monkeypatch):
    provider = ZvonokPhoneProvider()
    provider.public_key = "test-key"
    captured = {}

    async def fake_request(method: str, url: str, **kwargs):
        captured.update(method=method, url=url, kwargs=kwargs)
        return [{"call_id": "call-1", "call_status": "pincode_ok"}]

    monkeypatch.setattr(provider, "_request_json", fake_request)
    assert await provider.get_status("call-1") == "verified"
    assert captured["method"] == "GET"
    assert str(captured["url"]).endswith("/phones/call_by_id/")
    assert captured["kwargs"]["params"]["call_id"] == "call-1"
