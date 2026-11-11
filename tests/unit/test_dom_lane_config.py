from pathlib import Path

from src.scraper.config.config import ParseConfig
from src.scraper.config.settings import Settings
from src.scraper.infrastructure.browser_manager import (
    _build_proxy_configs,
    resolve_proxy_worker_slot,
)
from src.scraper.infrastructure.http_client import aiohttp_proxy_kwargs


# SCRAPER_STORAGE_STATE_PATH попадает в ParseConfig, если путь не передан явно.
def test_parse_config_reads_storage_state_path_from_env(monkeypatch, tmp_path) -> None:
    state = tmp_path / "session-1" / "storage_state.json"
    state.parent.mkdir()
    state.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("SCRAPER_STORAGE_STATE_PATH", str(state))
    monkeypatch.setenv("SCRAPER_LANE_ID", "1")
    env = Settings()
    assert env.storage_state_path == str(state)
    assert env.lane_id == "1"
    config = ParseConfig()
    assert str(config.storage_state_path) == str(state)


# Явный storage_state_path важнее env.
def test_parse_config_explicit_path_wins(monkeypatch, tmp_path) -> None:
    env_path = tmp_path / "from-env.json"
    env_path.write_text("{}", encoding="utf-8")
    explicit = tmp_path / "explicit.json"
    explicit.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("SCRAPER_STORAGE_STATE_PATH", str(env_path))
    config = ParseConfig(storage_state_path=explicit)
    assert config.storage_state_path == explicit


# Replicas одной lane не разъезжаются по разным proxy endpoint.
def test_resolve_proxy_worker_slot_is_always_zero() -> None:
    assert resolve_proxy_worker_slot(1) == 0
    assert resolve_proxy_worker_slot(4) == 0
    assert resolve_proxy_worker_slot(0) == 0


# Пустой proxy → HTTP-first идёт напрямую, без trust_env.
def test_empty_lane_proxy_is_direct(monkeypatch) -> None:
    monkeypatch.setenv("SCRAPER_PROXY_SERVER", "")
    monkeypatch.setenv("SCRAPER_PROXY_USERNAME", "")
    monkeypatch.setenv("SCRAPER_PROXY_PASSWORD", "")
    env = Settings()
    assert _build_proxy_configs(env) == []
    assert aiohttp_proxy_kwargs(None) == {}
    assert aiohttp_proxy_kwargs({}) == {}


# HTTP-first берёт тот же server/user, что и Playwright lane proxy.
def test_http_proxy_kwargs_match_playwright_lane_proxy(monkeypatch) -> None:
    monkeypatch.setenv("SCRAPER_PROXY_SERVER", "http://127.0.0.1:8080")
    monkeypatch.setenv("SCRAPER_PROXY_USERNAME", "lane-user")
    monkeypatch.setenv("SCRAPER_PROXY_PASSWORD", "lane-pass")
    monkeypatch.setenv("SCRAPER_PROXY_PORTS", "")
    env = Settings()
    pool = _build_proxy_configs(env)
    assert len(pool) == 1
    playwright_proxy = pool[0]
    http_kw = aiohttp_proxy_kwargs(playwright_proxy)
    assert playwright_proxy["server"] == "http://127.0.0.1:8080"
    assert http_kw["proxy"] == playwright_proxy["server"]
    assert http_kw["proxy_auth"].login == "lane-user"
    assert http_kw["proxy_auth"].password == "lane-pass"


# Compose задаёт egress на lane, не на replica и не через TG_BOT_PROXY.
def test_compose_lane_proxy_is_lane_scoped() -> None:
    compose = Path("docker-compose.yml").read_text(encoding="utf-8")
    lane1 = compose.split("worker-dom-1:")[1].split("worker-dom-2:")[0]
    lane2 = compose.split("worker-dom-2:")[1].split("worker-finalize:")[0]
    assert "${LANE_1_PROXY_SERVER:-}" in lane1
    assert "${LANE_1_PROXY_USERNAME:-}" in lane1
    assert "${LANE_1_PROXY_PASSWORD:-}" in lane1
    assert "${LANE_2_PROXY_SERVER:-}" in lane2
    assert "${LANE_2_PROXY_USERNAME:-}" in lane2
    assert "${LANE_2_PROXY_PASSWORD:-}" in lane2
    assert "TG_BOT_PROXY" not in lane1
    assert "TG_BOT_PROXY" not in lane2
    assert (
        "SCRAPER_STORAGE_STATE_PATH: /app/src/scraper/infrastructure/session-1/"
        in lane1
    )
    assert (
        "SCRAPER_STORAGE_STATE_PATH: /app/src/scraper/infrastructure/session-2/"
        in lane2
    )
