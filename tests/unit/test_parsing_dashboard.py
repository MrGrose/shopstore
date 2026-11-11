import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from src.jobs.dom_telemetry_store import _aggregate_by_lane, empty_telemetry_dashboard
from src.scraper.infrastructure.session_paths import (
    build_dashboard_sessions,
    resolve_storage_state_path,
    storage_state_file_status,
)
from src.web.admin_dashboard import _parsing_pipeline
from src.web.parsing_lanes import (
    build_parsing_lanes_overview,
    read_lane_throttle_dashboard,
    session_health_from_row,
)


def test_resolve_storage_state_path_explicit_missing_does_not_fallback(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing.json"
    assert resolve_storage_state_path(missing) is None


def test_build_dashboard_sessions_has_availability_and_lanes() -> None:
    data = build_dashboard_sessions()
    assert data["availability"]["kind"] == "availability"
    assert len(data["lanes"]) == 2
    assert data["lanes"][0]["lane_id"] == "1"
    assert data["lanes"][0]["worker"] == "worker-dom-1"
    assert data["lanes"][0]["session_dir"] == "session-1/"


def test_build_dashboard_sessions_availability_has_session_dir() -> None:
    data = build_dashboard_sessions()
    assert data["availability"]["session_dir"] == "session/"


def test_storage_state_file_status_missing(tmp_path: Path) -> None:
    row = storage_state_file_status(explicit_path=tmp_path / "missing.json")
    assert row["exists"] is False
    assert row["status"] == "err"
    assert row["status_label"] == "файл не найден"


def test_storage_state_file_status_fresh(tmp_path: Path) -> None:
    session_file = tmp_path / "storage_state.json"
    session_file.write_text("{}", encoding="utf-8")
    row = storage_state_file_status(
        explicit_path=session_file,
        warn_after_hours=72,
        err_after_hours=168,
    )
    assert row["exists"] is True
    assert row["status"] == "ok"
    assert row["status_label"] == "свежая"


def test_session_health_from_row_defaults_availability_session_dir() -> None:
    health = session_health_from_row({"kind": "availability", "status": "ok"})
    assert health["session_dir"] == "session/"


def test_build_parsing_lanes_overview_session_separate_from_throttle() -> None:
    sessions = {
        "availability": {
            "kind": "availability",
            "label": "Availability login",
            "session_dir": "session/",
            "exists": True,
            "status": "ok",
            "status_label": "свежая",
        },
        "lanes": [
            {
                "lane_id": "1",
                "worker": "worker-dom-1",
                "kind": "dom_lane",
                "label": "Lane 1",
                "session_dir": "session-1/",
                "exists": True,
                "status": "warn",
                "status_label": "пора обновить",
                "age_hours": 80.0,
            }
        ],
    }
    throttle = {
        "lane_id": "1",
        "status": "cooldown",
        "status_label": "Пауза",
        "cooldown_seconds": 30,
        "consecutive_429": 2,
        "healthy": False,
    }
    with (
        patch(
            "src.web.parsing_lanes.build_dashboard_sessions",
            return_value=sessions,
        ),
        patch(
            "src.web.parsing_lanes.read_lane_throttle_dashboard",
            return_value=throttle,
        ),
    ):
        overview = build_parsing_lanes_overview()
    lane = overview["lanes"][0]
    assert lane["worker"] == "worker-dom-1"
    assert lane["session"]["session_dir"] == "session-1/"
    assert lane["session"]["status"] == "warn"
    assert lane["throttle"]["status"] == "cooldown"
    assert overview["availability"]["session_dir"] == "session/"


def test_read_lane_throttle_dashboard_healthy_when_empty() -> None:
    with patch("src.core.redis.sync_redis") as redis_mock:
        redis_mock.return_value.get.return_value = None
        row = read_lane_throttle_dashboard("1")
    assert row["status"] == "healthy"
    assert row["cooldown_seconds"] == 0
    assert row["consecutive_429"] == 0


def test_read_lane_throttle_dashboard_cooldown() -> None:
    payload = {
        "cooldown_until": datetime.now().timestamp() + 30,
        "consecutive_429": 2,
    }
    with patch("src.core.redis.sync_redis") as redis_mock:
        redis_mock.return_value.get.return_value = json.dumps(payload)
        row = read_lane_throttle_dashboard("2")
    assert row["status"] == "cooldown"
    assert row["cooldown_seconds"] > 0
    assert row["consecutive_429"] == 2


def test_build_parsing_lanes_overview_watchdog_age() -> None:
    now = datetime(2026, 3, 10, 12, 0, 0)
    finished = (now - timedelta(minutes=8)).isoformat()
    with patch(
        "src.web.parsing_lanes.load_admin_job_snapshot",
        return_value={"finished_at": finished},
    ):
        overview = build_parsing_lanes_overview(now)
    assert overview["watchdog"]["last_run_age"] is not None
    assert overview["lanes"]


def test_aggregate_by_lane_groups_events() -> None:
    events = [
        {"lane_id": "1", "challenge_ratio_last_window": 0.1, "avg_dom_latency_ms": 100},
        {"lane_id": "2", "challenge_ratio_last_window": 0.2, "avg_dom_latency_ms": 200},
        {"lane_id": "1", "challenge_ratio_last_window": 0.0, "avg_dom_latency_ms": 50},
    ]
    lanes = _aggregate_by_lane(events)
    assert lanes["1"]["chunks"] == 2
    assert lanes["2"]["chunks"] == 1


def test_parsing_pipeline_includes_translation_stage() -> None:
    stats = {
        "import_pending_jobs": 0,
        "import_running_jobs": 0,
        "import_failed_jobs": 0,
        "dom_pending_jobs": 1,
        "dom_running_jobs": 0,
        "dom_failed_jobs": 0,
        "finalize_pending_jobs": 0,
        "finalize_running_jobs": 0,
        "finalize_failed_jobs": 0,
        "translation_pending_jobs": 3,
        "translation_running_jobs": 1,
        "translation_failed_jobs": 0,
        "estimated_products_pending": 10,
        "estimated_products_in_progress": 0,
        "import_chunk_size": 10,
    }
    workers = {
        "translation": {"alive": True, "count": 1, "names": ["worker-translation"]},
    }
    parsing = _parsing_pipeline(stats, workers=workers)
    keys = [stage["key"] for stage in parsing["stages"]]
    assert keys == ["import", "dom", "finalize", "translation"]
    translation = parsing["stages"][-1]
    assert translation["label"] == "Перевод"
    assert translation["pending"] == 3
    assert translation["running"] == 1
    assert translation["estimated_skus"] is None


def test_empty_telemetry_dashboard_has_lanes_1h() -> None:
    payload = empty_telemetry_dashboard()
    assert "lanes_1h" in payload
    assert payload["lanes_1h"] == {}
