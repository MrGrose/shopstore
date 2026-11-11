from decimal import Decimal
from urllib.parse import urlparse

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    PAGINATION_SIZES: list[int] = [10, 20, 50, 100]
    MEDIA_ROOT: str = "media/products"
    STORAGE_BACKEND: str = "local"
    S3_ENDPOINT: str = ""
    S3_ACCESS_KEY: str = ""
    S3_SECRET_KEY: str = ""
    S3_BUCKET: str = "shopstore-media"
    S3_REGION: str = "us-east-1"
    MEDIA_PUBLIC_BASE: str = ""
    MAX_IMAGE_SIZE: int = 2 * 1024 * 1024
    PREVIEW_SIZES: list[int] = [300, 600, 900]

    DATABASE_URL: str | None = None
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: str = "5432"
    POSTGRES_USER: str = "shopstore"
    POSTGRES_PASSWORD: str = "shopstore"
    POSTGRES_DB: str = "shopstore_db"
    APP_ENV: str = "prod"

    STOREFRONT_DIST_DIR: str = "frontend/dist"
    AUTH_SECRET: str = "change-me"
    ACCESS_TOKEN_TTL_SECONDS: int = 86400
    TG_LOGIN_MAX_AGE_SECONDS: int = 3600

    ADMIN_TG_IDS: str = ""
    # Вход в /internal/admin логином и паролем (не Telegram).
    ADMIN_PANEL_LOGIN: str = ""
    ADMIN_PANEL_PASSWORD: str = ""
    TG_ADMIN_ID: int = 0
    TG_BOT_SHOP: str = ""
    TG_BOT_USERNAME: str = ""
    # SOCKS5/HTTP прокси для polling, если api.telegram.org недоступен с сервера.
    TG_BOT_PROXY: str = ""
    TG_MINI_APP_URL: str = ""
    # Telegram-группы: заказы и поддержка (отрицательный id супергруппы).
    TG_ORDERS_CHAT_ID: int = 0
    TG_SUPPORT_CHAT_ID: int = 0
    # Публичный сайт витрины для тг.
    PUBLIC_SITE_URL: str = ""
    # Ссылка на сообщество VK (футер витрины).
    PUBLIC_VK_URL: str = ""

    # Локальная разработка Mini App
    DEV_AUTH_BYPASS: bool = False

    # Курс EUR
    EUR_RATE_API_URL: str = "https://api.rapira.net/open/market/rates"
    EUR_RATE_SYMBOL: str = "USDT/RUB"
    EUR_RATE_MULTIPLIER: float = 1.2
    EUR_RATE_HISTORY_RETENTION_DAYS: int = 90

    # SBP (СБП)
    SBP_ENABLED: bool = False
    SBP_AUTH_BASE_URL: str = "https://auth.example.com/api/v1"
    SBP_API_BASE_URL: str = "https://payments.example.com/api/v1"
    SBP_LOGIN: str = ""
    SBP_PASSWORD: str = ""
    SBP_TSP_ID: int = 0
    SBP_CALLBACK_URL: str = ""
    SBP_WEBHOOK_PUBLIC_KEY: str = ""
    SBP_SKIP_SIGNATURE_VERIFY: bool = False
    SBP_TEST_MODE: bool = True
    SBP_TIMEOUT_SECONDS: int = 15
    SBP_MIN_PAYMENT_AMOUNT_MINOR: int = 100
    SBP_MAX_PAYMENT_AMOUNT_MINOR: int = 1_000_000

    # Лимиты жизненного цикла неоплаченного заказа.
    ORDER_MAX_PAYMENT_ATTEMPTS: int = Field(default=5, ge=1)
    ORDER_PAYMENT_DEADLINE_HOURS: int = Field(default=24, ge=1)
    ORDER_MAX_ACTIVE_UNPAID_ORDERS_PER_USER: int = Field(default=3, ge=1)

    REDIS_URL: str = "redis://localhost:6379/0"
    REDIS_HEALTH_ALERT_SECONDS: int = Field(default=60, ge=10, le=3600)
    TELEGRAM_LINK_TOKEN_TTL_SECONDS: int = Field(default=600, ge=60, le=3600)
    # Email settings.
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = ""
    SMTP_USE_TLS: bool = True
    EMAIL_OTP_TTL_SECONDS: int = Field(default=600, ge=60)
    EMAIL_OTP_MAX_ATTEMPTS: int = Field(default=5, ge=1)
    EMAIL_OTP_RATE_LIMIT_EMAIL: int = Field(default=3, ge=1)
    EMAIL_OTP_RATE_LIMIT_IP: int = Field(default=10, ge=1)
    EMAIL_OTP_RATE_LIMIT_WINDOW_SECONDS: int = Field(default=900, ge=60)
    # Telegram Gateway (verification codes) — отдельно от TG_BOT_SHOP.
    TELEGRAM_GATEWAY_ACCESS_TOKEN: str = ""
    TELEGRAM_GATEWAY_BASE_URL: str = "https://gatewayapi.telegram.org"
    PHONE_LOGIN_CODE_TTL_SECONDS: int = Field(default=600, ge=30, le=3600)
    PHONE_LOGIN_CODE_LENGTH: int = Field(default=6, ge=4, le=8)
    PHONE_LOGIN_SEND_COOLDOWN_SECONDS: int = Field(default=60, ge=1)
    PHONE_LOGIN_RATE_LIMIT_PHONE: int = Field(default=3, ge=1)
    PHONE_LOGIN_RATE_LIMIT_IP: int = Field(default=10, ge=1)
    PHONE_LOGIN_RATE_LIMIT_WINDOW_SECONDS: int = Field(default=900, ge=60)
    PHONE_LOGIN_VERIFY_MAX_ATTEMPTS: int = Field(default=5, ge=1)
    PHONE_LOGIN_GLOBAL_SEND_MAX: int = Field(default=500, ge=1)
    PHONE_LOGIN_GLOBAL_SEND_WINDOW_SECONDS: int = Field(default=86400, ge=60)
    PHONE_VERIFICATION_CODE_ENABLED: bool = False
    # Zvonok phone auth
    PHONE_AUTH_ENABLED: bool = False
    PHONE_AUTH_CHANNEL_ORDER: str = "flash_call,voice_code,verification_number"
    PHONE_FLASH_CALL_ENABLED: bool = True
    PHONE_VOICE_CODE_ENABLED: bool = True
    PHONE_VERIFICATION_NUMBER_ENABLED: bool = True
    PHONE_SMS_ENABLED: bool = False
    PHONE_CALL_FLOW_TTL_SECONDS: int = Field(default=300, ge=60, le=3600)
    PHONE_CALL_COOLDOWN_SECONDS: int = Field(default=30, ge=1, le=300)
    PHONE_VERIFICATION_NUMBER_COOLDOWN_SECONDS: int = Field(default=120, ge=30, le=300)
    PHONE_CALL_MAX_REQUESTS_PER_CHANNEL: int = Field(default=2, ge=1, le=5)
    PHONE_CALL_VERIFY_MAX_ATTEMPTS: int = Field(default=5, ge=1, le=20)
    PHONE_CALL_RATE_LIMIT_PHONE: int = Field(default=12, ge=6)
    PHONE_CALL_RATE_LIMIT_IP: int = Field(default=20, ge=6)
    ZVONOK_ENABLED: bool = False
    ZVONOK_BASE_URL: str = "https://zvonok.com"
    ZVONOK_PUBLIC_KEY: str = ""
    ZVONOK_FLASH_CALL_CAMPAIGN_ID: int = Field(default=578564922, gt=0)
    ZVONOK_VOICE_CODE_CAMPAIGN_ID: int = Field(default=1519197036, gt=0)
    ZVONOK_VERIFICATION_NUMBER_CAMPAIGN_ID: int = Field(default=1602583414, gt=0)
    ZVONOK_VERIFICATION_PHONE_NUMBER: str = "+78005553968"
    # Support API rate limits (per user).
    SUPPORT_RATE_LIMIT_CREATE_PER_WINDOW: int = Field(default=5, ge=1)
    SUPPORT_RATE_LIMIT_MESSAGE_PER_WINDOW: int = Field(default=30, ge=1)
    SUPPORT_RATE_LIMIT_COOLDOWN_SECONDS: int = Field(default=30, ge=1)
    SUPPORT_RATE_LIMIT_WINDOW_SECONDS: int = Field(default=3600, ge=60)
    SUPPORT_TICKETS_PAGE_SIZE_DEFAULT: int = Field(default=20, ge=1)
    SUPPORT_TICKETS_PAGE_SIZE_MAX: int = Field(default=50, ge=1)
    SUPPORT_ADMIN_TICKETS_PAGE_SIZE_DEFAULT: int = Field(default=50, ge=1)
    SUPPORT_ATTACHMENT_MAX_FILES: int = Field(default=10, ge=1, le=20)
    SUPPORT_ATTACHMENT_MAX_UPLOAD_BYTES: int = Field(
        default=20 * 1024 * 1024, ge=1024 * 1024
    )
    SUPPORT_ATTACHMENT_RETENTION_DAYS: int = Field(default=180, ge=1)
    # Кэш каталога.
    CATALOG_FACETS_CACHE_TTL_SECONDS: int = Field(default=120, ge=0)
    CATALOG_SUBCATEGORIES_CACHE_TTL_SECONDS: int = Field(default=900, ge=0)
    CATALOG_COUNT_CACHE_TTL_SECONDS: int = Field(default=180, ge=0)
    STOREFRONT_MAPPING_COMPAT_PARAMS: bool = Field(default=True)
    CATALOG_IMPORT_QUEUE: str = "catalog_import"
    CATALOG_DOM_QUEUE: str = "catalog_dom"
    CATALOG_FINALIZE_QUEUE: str = "catalog_finalize"
    TRANSLATION_QUEUE: str = "translation"
    # Очередь пересчета цен.
    PRICING_QUEUE: str = "pricing"
    PRICING_BATCH_SIZE: int = Field(default=1000, ge=1, le=10000)
    # Режим уведомлений: inline (TG) или outbox (очередь RQ).
    NOTIFICATION_MODE: str = "outbox"
    # Очередь уведомлений.
    NOTIFICATION_QUEUE: str = "notifications"
    # Очередь проверки трекинга поставщика.
    SUPPLIER_TRACKING_QUEUE: str = "supplier_tracking"
    SUPPLIER_TRACKING_USER_ID: int = Field(default=133, ge=1)
    SUPPLIER_TRACKING_WAIT_HOURS: int = Field(default=4, ge=1)
    SUPPLIER_TRACKING_ACTIVE_HOURS: int = Field(default=24, ge=1)
    SUPPLIER_TRACKING_BLOCKED_HOURS: int = Field(default=24, ge=1)
    DHL_TRACKING_PROXY_URL: str = ""
    POCHTA_TRACKING_PROXY_URL: str = ""
    DHL_TRACKING_USE_BROWSER: bool = True
    DHL_BROWSER_TRACKING_QUEUE: str = "dhl_browser_tracking"
    DHL_BROWSER_FETCH_TIMEOUT_SECONDS: int = Field(default=75, ge=30)
    SUPPLIER_AVAILABILITY_ENABLED: bool = False
    SUPPLIER_AVAILABILITY_QUEUE: str = "supplier_availability"
    SUPPLIER_AVAILABILITY_SNAPSHOT_TTL_MINUTES: int = Field(default=5, ge=1)
    SUPPLIER_AVAILABILITY_MAX_RETRIES: int = Field(default=2, ge=1)
    SUPPLIER_AVAILABILITY_ITEM_PAUSE_SECONDS: float = Field(default=2.5, ge=0)
    SUPPLIER_AVAILABILITY_RETRY_PAUSE_SECONDS: float = Field(default=1.5, ge=0)
    SUPPLIER_AVAILABILITY_REQUIRE_STORAGE_STATE: bool = True
    DELIVERED_ALERT_RETRY_QUEUE: str = "delivered_alert_retry"
    DELIVERED_ALERT_RETRY_MINUTES: int = Field(default=30, ge=1)

    # Витрина: пороги наличия (см. stock_display).
    STOCK_OK_FROM_QTY: int = Field(default=6, ge=1)
    STOCK_LOW_MIN_QTY: int = Field(default=2, ge=1)
    STOCK_LABEL_IN_STOCK: str = "В наличии"
    STOCK_LABEL_LOW: str = "Мало"
    STOCK_LABEL_LAST: str = "Последний"
    STOCK_LABEL_OUT: str = "Нет в наличии"

    # Текст доставки
    SHIPPING_ESTIMATE_FALLBACK: str = "Доставка 14 дней"

    # Лимит счёта Supplier-Demo (товары + доставка поставщика).
    SUPPLIER_ORDER_MAX_EUR: Decimal = Field(default=Decimal("300"), gt=0)
    # Доставка поставщика, входит в SUPPLIER_ORDER_MAX_EUR.
    SUPPLIER_ORDER_SHIPPING_EUR: Decimal = Field(default=Decimal("29.99"), ge=0)
    # Беспошлинный лимит (Лимит 200€).
    CUSTOMS_DUTY_FREE_EUR: int = Field(default=200, ge=0)
    # Коеф для расчета НДС (0.15 = 15%).
    CUSTOMS_DUTY_RATE: float = Field(default=0.15, ge=0, le=1)
    CUSTOMS_DUTY_NOTICE: str = (
        "На данный заказ будет рассчитан таможенный платеж в размере: {amount}, "
        "т.к. сумма заказа превысила беспошлинный лимит {limit}. "
        "Оплата производится при получении и не включается в итоговую стоимость заказа."
    )

    # Разрешённые Host
    ALLOWED_HOSTS: str = ""
    SECURITY_HSTS_MAX_AGE: int = Field(default=0, ge=0)

    # Юр. реквизиты витрины (футер, /privacy, /terms, /consent).
    LEGAL_ENTITY_NAME: str = ""
    LEGAL_INN: str = ""
    LEGAL_OGRNIP: str = ""
    LEGAL_ADDRESS: str = ""
    LEGAL_EMAIL: str = ""
    LEGAL_PHONE: str = ""
    # Дата редакции юр. документов, формат ДД.ММ.ГГГГ (напр. 27.05.2026).
    # Пусто - текущая дата UTC.
    LEGAL_REVISION_DATE: str = ""

    @model_validator(mode="after")
    def _normalize_sbp_dev_flags(self) -> "Settings":
        if self.SBP_SKIP_SIGNATURE_VERIFY and not self.is_dev:
            object.__setattr__(self, "SBP_SKIP_SIGNATURE_VERIFY", False)
        return self

    # Нормализует MEDIA_PUBLIC_BASE: http(s), без credentials и хвостового /.
    @model_validator(mode="after")
    def _normalize_media_public_base(self) -> "Settings":
        raw = self.MEDIA_PUBLIC_BASE.strip()
        if not raw:
            object.__setattr__(self, "MEDIA_PUBLIC_BASE", "")
            return self
        parsed = urlparse(raw)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError(
                "MEDIA_PUBLIC_BASE должен быть абсолютным URL "
                "с протоколом http или https"
            )
        if parsed.username or parsed.password:
            raise ValueError(
                "MEDIA_PUBLIC_BASE не должен содержать учётные данные в URL"
            )
        path = (parsed.path or "").rstrip("/")
        normalized = f"{parsed.scheme}://{parsed.netloc}{path}"
        object.__setattr__(self, "MEDIA_PUBLIC_BASE", normalized)
        return self

    @model_validator(mode="after")
    def _normalize_stock_low_min(self) -> "Settings":
        if self.STOCK_LOW_MIN_QTY >= self.STOCK_OK_FROM_QTY:
            object.__setattr__(
                self,
                "STOCK_LOW_MIN_QTY",
                max(1, int(self.STOCK_OK_FROM_QTY) - 1),
            )
        return self

    @property
    # Список хостов для TrustedHostMiddleware; пустой - middleware не подключается.
    def trusted_hosts(self) -> list[str]:
        raw = self.ALLOWED_HOSTS.strip()
        if not raw:
            return []
        hosts = [h.strip() for h in raw.split(",") if h.strip()]
        # Healthcheck внутри контейнера идет на 127.0.0.1/localhost (см. /ready).
        # Добавляем их всегда, чтобы TrustedHostMiddleware не ломал readiness.
        for h in ("localhost", "127.0.0.1"):
            if h not in hosts:
                hosts.append(h)
        return hosts

    @property
    # Парсит ADMIN_TG_IDS из env; невалидные фрагменты пропускаются.
    def admin_telegram_ids(self) -> frozenset[int]:
        raw = self.ADMIN_TG_IDS.strip()
        if not raw:
            return frozenset()
        out: list[int] = []
        for part in raw.split(","):
            chunk = part.strip()
            if not chunk:
                continue
            try:
                out.append(int(chunk))
            except ValueError:
                continue
        return frozenset(out)

    @property
    def is_dev(self) -> bool:
        return self.APP_ENV.strip().lower() == "dev"

    @property
    # Регистрировать /docs и OpenAPI (доступ в prod — только admin по telegram_id).
    def api_docs_enabled(self) -> bool:
        return self.is_dev or self.TG_ADMIN_ID > 0 or bool(self.admin_telegram_ids)

    @property
    # Для dev-входа на витрину: первый id в ADMIN_TG_IDS, иначе TG_ADMIN_ID.
    def dev_storefront_login_telegram_id(self) -> int | None:
        raw = self.ADMIN_TG_IDS.strip()
        if raw:
            for part in raw.split(","):
                chunk = part.strip()
                if not chunk:
                    continue
                try:
                    return int(chunk)
                except ValueError:
                    continue
        admin_id = self.TG_ADMIN_ID
        return admin_id if admin_id > 0 else None

    @property
    def smtp_configured(self) -> bool:
        return bool(self.SMTP_HOST.strip() and self.SMTP_FROM.strip())

    @property
    def telegram_gateway_configured(self) -> bool:
        return bool(self.TELEGRAM_GATEWAY_ACCESS_TOKEN.strip())

    @property
    # Возвращает включённые каналы каскада в заданном порядке.
    def phone_auth_channels(self) -> list[str]:
        enabled = {
            "flash_call": self.PHONE_FLASH_CALL_ENABLED,
            "voice_code": self.PHONE_VOICE_CODE_ENABLED,
            "verification_number": self.PHONE_VERIFICATION_NUMBER_ENABLED,
        }
        return [
            channel
            for channel in (
                part.strip() for part in self.PHONE_AUTH_CHANNEL_ORDER.split(",")
            )
            if channel and enabled.get(channel, False)
        ]

    @property
    def admin_panel_login_enabled(self) -> bool:
        return bool(
            self.ADMIN_PANEL_LOGIN.strip() and self.ADMIN_PANEL_PASSWORD.strip()
        )

    @property
    def sbp_configured(self) -> bool:
        return bool(
            self.SBP_LOGIN.strip()
            and self.SBP_PASSWORD.strip()
            and self.SBP_CALLBACK_URL.strip()
            and self.SBP_WEBHOOK_PUBLIC_KEY.strip()
        )

    @property
    # Собирает подключение к psql.
    def database_url(self) -> str:
        if self.DATABASE_URL:
            return self.DATABASE_URL
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


settings = Settings()


# Fail-fast SBP при старте API, если оплата включена (не при import в pytest/CLI).
def validate_sbp_startup_settings() -> None:
    if not settings.SBP_ENABLED:
        return
    missing: list[str] = []
    if not settings.SBP_LOGIN.strip():
        missing.append("SBP_LOGIN")
    if not settings.SBP_PASSWORD.strip():
        missing.append("SBP_PASSWORD")
    if not settings.SBP_CALLBACK_URL.strip():
        missing.append("SBP_CALLBACK_URL")
    if not settings.SBP_WEBHOOK_PUBLIC_KEY.strip():
        missing.append("SBP_WEBHOOK_PUBLIC_KEY")
    if missing:
        joined = ", ".join(missing)
        raise RuntimeError(
            f"SBP_ENABLED=true, но не заданы обязательные переменные: {joined}"
        )


# Проверяет настройки каскада звонков при включённом web-входе.
def validate_phone_auth_startup_settings() -> None:
    if not settings.PHONE_AUTH_ENABLED:
        return
    raw_channels = [
        part.strip()
        for part in settings.PHONE_AUTH_CHANNEL_ORDER.split(",")
        if part.strip()
    ]
    known = {"flash_call", "voice_code", "verification_number"}
    if not raw_channels or len(raw_channels) != len(set(raw_channels)):
        raise RuntimeError("PHONE_AUTH_CHANNEL_ORDER пуст или содержит повторы")
    unknown = [channel for channel in raw_channels if channel not in known]
    if unknown:
        raise RuntimeError(f"Неизвестные phone auth channels: {', '.join(unknown)}")
    if not settings.ZVONOK_ENABLED or not settings.ZVONOK_PUBLIC_KEY.strip():
        raise RuntimeError("PHONE_AUTH_ENABLED=true, но Zvonok не настроен")
    if (
        not settings.phone_auth_channels
        or settings.phone_auth_channels[0] != raw_channels[0]
    ):
        raise RuntimeError("Первый phone auth channel выключен")
