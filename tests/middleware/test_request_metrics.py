import logging
import re

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.middleware.metrics import setup_request_metrics

_DURATION_MS_RE = re.compile(r"duration_ms=(\d+(?:\.\d+)?)")


def test_request_metrics_logs_duration_ms(caplog: pytest.LogCaptureFixture) -> None:
    app = FastAPI()
    setup_request_metrics(app)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    caplog.set_level(logging.INFO, logger="src.middleware.metrics")

    client = TestClient(app)
    response = client.get("/health")

    assert response.status_code == 200
    assert len(caplog.records) == 1
    message = caplog.records[0].getMessage()
    assert "method=GET" in message
    assert "path=/health" in message
    assert "status_code=200" in message
    assert "response_size=" in message
    match = _DURATION_MS_RE.search(message)
    assert match is not None
    assert float(match.group(1)) >= 0
