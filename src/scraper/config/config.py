from pathlib import Path

from src.scraper.config.settings import load_settings


class ParseConfig:
    # Явный path, иначе SCRAPER_STORAGE_STATE_PATH, иначе search-path.
    def __init__(
        self,
        storage_state_path: str | Path | None = None,
        use_storage_state_if_exists: bool = True,
        # Если True - без файла storage_state парсер не стартует.
        require_storage_state: bool = False,
        # False - без окна.
        headless: bool = False,
        base_url: str | None = None,
    ):
        settings = load_settings()
        env_path = (settings.storage_state_path or "").strip()
        self.storage_state_path = storage_state_path or env_path or None
        self.use_storage_state_if_exists = use_storage_state_if_exists
        self.require_storage_state = require_storage_state
        self.headless = headless
        self.base_url = (base_url or settings.base_url).rstrip("/")
