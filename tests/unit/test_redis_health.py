from unittest.mock import patch

from src.core.redis import health as redis_health


def test_evaluate_redis_health_ok_resets_alert_state():
    redis_health.reset_redis_health_tracker()
    with (
        patch("src.core.redis.health.ping_sync_redis", return_value=True),
        patch("src.core.redis.health.asyncio.run", return_value=True),
    ):
        result = redis_health.evaluate_redis_health()
    assert result["ok"] is True
    assert result["alerted"] is False


def test_evaluate_redis_health_alerts_after_threshold():
    redis_health.reset_redis_health_tracker()
    redis_health._last_ok_monotonic = 0.0
    with (
        patch("src.core.redis.health.ping_sync_redis", return_value=False),
        patch("src.core.redis.health.asyncio.run", return_value=False),
        patch("src.core.redis.health.time.monotonic", return_value=120.0),
    ):
        result = redis_health.evaluate_redis_health()

    assert result["ok"] is False
    assert result["alerted"] is True
    assert result["outage_seconds"] == 120
