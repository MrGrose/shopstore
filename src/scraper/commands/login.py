import logging

from src.scraper.config.config import ParseConfig
from src.scraper.config.settings import load_settings
from src.scraper.infrastructure.browser_manager import BrowserManager

logger = logging.getLogger(__name__)


def main() -> None:
    # Конфигурация для логина
    config = ParseConfig()
    env = load_settings()

    browser_manager = BrowserManager(config)

    # Запуск логина и сохранения состояния
    state_path = browser_manager.run_login_and_save_state(
        manual_fallback=True,  # Разрешить ручной ввод при проблемах
        connect_cdp_url=(env.login_cdp_url.strip() or None),
    )

    logger.info("Логин завершён, состояние сохранено в %s", state_path)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(message)s",
    )
    main()
