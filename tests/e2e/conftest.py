import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


# Подгружает .env для локальных E2E (логин админки, base URL).
def load_dotenv() -> None:
    env_path = ROOT / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


@pytest.fixture(scope="session")
def e2e_base_url() -> str:
    load_dotenv()
    if not os.environ.get("ADMIN_PANEL_LOGIN") or not os.environ.get(
        "ADMIN_PANEL_PASSWORD"
    ):
        pytest.skip("ADMIN_PANEL_LOGIN / ADMIN_PANEL_PASSWORD не заданы")
    return os.environ.get("ADMIN_SMOKE_BASE", "http://localhost:8000")
