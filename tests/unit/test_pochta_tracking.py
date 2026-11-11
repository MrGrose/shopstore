import json
from pathlib import Path

import pytest

from src.services.orders.pochta_tracking import (
    build_pochta_public_tracking_url,
    normalize_pochta_payload,
)

FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "pochta_tracking_cj687712480de.json"
)


@pytest.fixture
def pochta_payload() -> dict:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def test_build_pochta_public_tracking_url() -> None:
    url = build_pochta_public_tracking_url("CJ687712480DE")
    assert "pochta.ru/tracking" in url
    assert "CJ687712480DE" in url


def test_normalize_pochta_payload_maps_events(pochta_payload: dict) -> None:
    result = normalize_pochta_payload(pochta_payload, "CJ687712480DE")

    assert result["carrier_source"] == "pochta"
    assert result["tracking_number"] == "CJ687712480DE"
    assert result["common_status"] == "Прошло регистрацию"
    assert result["expected_delivery_at"] is not None
    assert len(result["events"]) >= 4
    assert result["events"][-1]["source"] == "pochta"
    assert result["events"][-1]["stage"] == "destination"
    assert "Брянск" in (result["events"][-1]["location"] or "")


def test_normalize_pochta_payload_empty() -> None:
    result = normalize_pochta_payload({"detailedTrackings": []}, "CJ000000000DE")

    assert result["events"] == []
    assert result["current_stage"] is None
    assert "pochta.ru/tracking" in result["carrier_url"]


def test_normalize_pochta_payload_ready_for_pickup() -> None:
    fixture = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "pochta_tracking_cj687518469de.json"
    )
    payload = json.loads(fixture.read_text(encoding="utf-8"))
    result = normalize_pochta_payload(payload, "CJ687518469DE")

    assert result["current_stage"] == "last_mile"
    assert "хранится в отделении" in (result["common_status"] or "").lower()
    assert result["storage_until_at"] is not None
    assert result["events"][-1]["stage"] == "last_mile"
    assert "ожидает адресата" in result["events"][-1]["title"].lower()
