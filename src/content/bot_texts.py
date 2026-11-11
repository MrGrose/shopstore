from src.core.config import settings
from src.utils.urls import mini_app_account_tab_url

BOT_WELCOME_NEW_USER = (
    "Добро пожаловать в Shopstore! 🎾\n\n"
    "Здесь можно оформить заказ, следить за его статусом "
    "и связаться с поддержкой.\n\n"
    "Выберите нужный раздел ниже."
)

BOT_WELCOME_RETURNING_USER = "👋 С возвращением!\n\nЧто ищем сегодня?"

BOT_LOGIN_UNAVAILABLE = "Войти сейчас не получилось.\n\nАккаунт временно недоступен."

BOT_TG_LINK_OK = (
    "Готово! Telegram связан с аккаунтом Shopstore. "
    "Уведомления о заказах будут приходить сюда."
)

BOT_TG_LINK_ERR = (
    "Ссылка устарела или уже использована. "
    "Создайте новую ссылку в личном кабинете на сайте."
)

BOT_PHONE_LINK_OK = "Номер телефона привязан к аккаунту Shopstore."

BOT_REDIRECT_TO_ACCOUNT = (
    "Для вопросов по заказам и обращениям используйте личный кабинет — "
    "так мы быстрее поможем.\n\n"
    "Выберите нужный раздел."
)

BOT_BUTTON_OPEN_STORE = "🛍 Открыть магазин"
BOT_BUTTON_ORDERS = "📦 Мои заказы"
BOT_BUTTON_SUPPORT = "💬 Поддержка"
BOT_BUTTON_WRITE_SUPPORT = "💬 Написать в поддержку"
BOT_MENU_BUTTON_STORE = "🛍"
BOT_COMMAND_START_DESCRIPTION = "Главное меню"

BOT_DEFAULT_USERNAME = "любитель спорта"


# URL вкладки заказов в Mini App.
def account_orders_url() -> str | None:
    mini_app = (settings.TG_MINI_APP_URL or "").strip()
    if not mini_app:
        return None
    return mini_app_account_tab_url(mini_app, "orders")


# URL вкладки поддержки в Mini App.
def account_support_url() -> str | None:
    mini_app = (settings.TG_MINI_APP_URL or "").strip()
    if not mini_app:
        return None
    return mini_app_account_tab_url(mini_app, "support")


# Приветствие для возвращающегося пользователя.
def bot_welcome_returning_user(username: str) -> str:
    del username
    return BOT_WELCOME_RETURNING_USER
