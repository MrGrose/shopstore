from datetime import UTC, datetime
from pathlib import Path
from typing import Any

_INFRASTRUCTURE_DIR = Path(__file__).resolve().parent

# Дефолт: login.py и scraper пишут/читают JSON здесь (availability).
SESSION_DIR = _INFRASTRUCTURE_DIR / "session"
DEFAULT_STORAGE_STATE_PATH = SESSION_DIR / "storage_state.json"

# DOM lanes: отдельные storage_state для worker-dom-1/2 (не availability session/).
DOM_LANE_SESSION_PATHS: tuple[tuple[str, str, Path], ...] = (
    ("1", "worker-dom-1", _INFRASTRUCTURE_DIR / "session-1" / "storage_state.json"),
    ("2", "worker-dom-2", _INFRASTRUCTURE_DIR / "session-2" / "storage_state.json"),
)


# Пути автопоиска storage_state, если explicit_path не задан.
def storage_state_search_paths() -> tuple[Path, ...]:
    return (DEFAULT_STORAGE_STATE_PATH,)


# Первый существующий JSON storage_state (как в BrowserManager).
def resolve_storage_state_path(explicit_path: str | Path | None = None) -> Path | None:
    if explicit_path:
        candidate = Path(explicit_path)
        return candidate if candidate.is_file() else None
    for candidate in storage_state_search_paths():
        if candidate.is_file():
            return candidate
    return None


# Метаданные файла сессии для админки: mtime, возраст, статус свежести.
def storage_state_file_status(
    explicit_path: str | Path | None = None,
    warn_after_hours: float = 72,
    err_after_hours: float = 168,
) -> dict[str, Any]:
    path = resolve_storage_state_path(explicit_path)
    if path is None:
        expected = explicit_path or DEFAULT_STORAGE_STATE_PATH
        return {
            "exists": False,
            "path": str(expected),
            "filename": Path(expected).name,
            "size_bytes": None,
            "updated_at": None,
            "age_hours": None,
            "warn_after_days": round(warn_after_hours / 24, 1),
            "refresh_hint": "нужно обновить",
            "status": "err",
            "status_label": "файл не найден",
        }

    stat = path.stat()
    updated_at = datetime.fromtimestamp(stat.st_mtime, UTC).replace(tzinfo=None)
    age_hours = max(
        0.0,
        (datetime.now(UTC).replace(tzinfo=None) - updated_at).total_seconds() / 3600,
    )
    if age_hours >= err_after_hours:
        status, status_label = "err", "давно не обновлялась"
        refresh_hint = "нужно обновить"
    elif age_hours >= warn_after_hours:
        status, status_label = "warn", "пора обновить"
        refresh_hint = "пора обновить"
    else:
        status, status_label = "ok", "свежая"
        hours_left = max(0.0, warn_after_hours - age_hours)
        days_left = round(hours_left / 24, 1)
        refresh_hint = f"через {days_left} дн"

    return {
        "exists": True,
        "path": str(path),
        "filename": path.name,
        "size_bytes": int(stat.st_size),
        "updated_at": updated_at,
        "age_hours": round(age_hours, 1),
        "warn_after_days": round(warn_after_hours / 24, 1),
        "refresh_hint": refresh_hint,
        "status": status,
        "status_label": status_label,
    }


# Сводка availability + DOM lane sessions для админки (только file age, не login proof).
def build_dashboard_sessions(
    warn_after_hours: float = 72,
    err_after_hours: float = 168,
) -> dict[str, Any]:
    availability = storage_state_file_status(
        explicit_path=DEFAULT_STORAGE_STATE_PATH,
        warn_after_hours=warn_after_hours,
        err_after_hours=err_after_hours,
    )
    availability["kind"] = "availability"
    availability["label"] = "Availability login"
    availability["session_dir"] = "session/"

    lanes: list[dict[str, Any]] = []
    for lane_id, worker, path in DOM_LANE_SESSION_PATHS:
        row = storage_state_file_status(
            explicit_path=path,
            warn_after_hours=warn_after_hours,
            err_after_hours=err_after_hours,
        )
        row.update(
            {
                "lane_id": lane_id,
                "worker": worker,
                "kind": "dom_lane",
                "label": f"Lane {lane_id}",
                "session_dir": f"session-{lane_id}/",
            }
        )
        lanes.append(row)

    return {"availability": availability, "lanes": lanes}
