from pathlib import Path

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_SCRAPER_DIR = Path(__file__).resolve().parent.parent
DEFAULT_COLLECTION_URLS = (
    "https://www.supplier-demo.com/collections/padel",
    "https://www.supplier-demo.com/collections/tennis-rackets",
    "https://www.supplier-demo.com/collections/tennis-clothing",
    "https://www.supplier-demo.com/collections/tennis-shoes",
    "https://www.supplier-demo.com/collections/tennis-bags",
    "https://www.supplier-demo.com/collections/tennis-balls",
    "https://www.supplier-demo.com/collections/tennis-strings",
    "https://www.supplier-demo.com/collections/accessories",
    "https://www.supplier-demo.com/collections/running",
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_SCRAPER_DIR / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    email: str = Field(
        default="", validation_alias=AliasChoices("EMAIL", "LOGIN_EMAIL")
    )
    password: str = Field(
        default="", validation_alias=AliasChoices("PASSWORD", "LOGIN_PASSWORD")
    )
    playwright_profile: str = Field(
        default="",
        validation_alias="SCRAPER_PLAYWRIGHT_PROFILE",
    )
    playwright_channel: str = Field(
        default="", validation_alias="SRC3_PLAYWRIGHT_CHANNEL"
    )
    login_cdp_url: str = Field(default="", validation_alias="SCRAPER_LOGIN_CDP_URL")
    login_use_proxy: bool = Field(
        default=False,
        validation_alias="SCRAPER_LOGIN_USE_PROXY",
    )
    base_url: str = Field(
        default="https://www.supplier-demo.com",
        validation_alias="SCRAPER_BASE_URL",
    )
    user_agent: str = Field(
        default=(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
        ),
        validation_alias="SCRAPER_USER_AGENT",
    )
    graphql_timeout_seconds: int = Field(
        default=60,
        validation_alias="SCRAPER_GRAPHQL_TIMEOUT_SECONDS",
    )
    cloudscraper_timeout_seconds: int = Field(
        default=30,
        validation_alias="SCRAPER_CLOUDSCRAPER_TIMEOUT_SECONDS",
    )
    dom_http_first: bool = Field(
        default=True,
        validation_alias="SCRAPER_DOM_HTTP_FIRST",
    )
    dom_http_timeout_ms: int = Field(
        default=30_000,
        validation_alias="SCRAPER_DOM_HTTP_TIMEOUT_MS",
    )
    dom_page_timeout_ms: int = Field(
        default=120_000,
        validation_alias="SCRAPER_DOM_PAGE_TIMEOUT_MS",
    )
    dom_first_selector_timeout_ms: int = Field(
        default=10_000,
        validation_alias="SCRAPER_DOM_FIRST_SELECTOR_TIMEOUT_MS",
    )
    dom_retry_selector_timeout_ms: int = Field(
        default=20_000,
        validation_alias="SCRAPER_DOM_RETRY_SELECTOR_TIMEOUT_MS",
    )
    dom_networkidle_timeout_ms: int = Field(
        default=30_000,
        validation_alias="SCRAPER_DOM_NETWORKIDLE_TIMEOUT_MS",
    )
    dom_product_data_attempts: int = Field(
        default=3,
        validation_alias="SCRAPER_DOM_PRODUCT_DATA_ATTEMPTS",
    )
    collection_page_timeout_ms: int = Field(
        default=120_000,
        validation_alias="SCRAPER_COLLECTION_PAGE_TIMEOUT_MS",
    )
    collection_settle_timeout_ms: int = Field(
        default=1_500,
        validation_alias="SCRAPER_COLLECTION_SETTLE_TIMEOUT_MS",
    )
    enrich_retry_rounds: int = Field(
        default=2, validation_alias="SCRAPER_ENRICH_RETRY_ROUNDS"
    )
    enrich_sleep_min: float = Field(
        default=1.2, validation_alias="SCRAPER_ENRICH_SLEEP_MIN"
    )
    enrich_sleep_max: float = Field(
        default=2.5, validation_alias="SCRAPER_ENRICH_SLEEP_MAX"
    )
    dom_min_success_ratio: float = Field(
        default=0.9,
        validation_alias="SCRAPER_DOM_MIN_SUCCESS_RATIO",
    )
    storefront_graphql_endpoint: str = Field(
        default="https://www.supplier-demo.com/api/unstable/graphql.json",
        validation_alias="SCRAPER_STOREFRONT_GRAPHQL_ENDPOINT",
    )
    storefront_access_token: str = Field(
        default="",
        validation_alias="SCRAPER_STOREFRONT_ACCESS_TOKEN",
    )
    storefront_stock_workers: int = Field(
        default=1,
        validation_alias="SCRAPER_STOREFRONT_STOCK_WORKERS",
    )
    dom_max_attempts: int = Field(
        default=5,
        validation_alias="SCRAPER_DOM_MAX_ATTEMPTS",
    )
    dom_retry_cooldown_seconds: int = Field(
        default=21_600,
        validation_alias="SCRAPER_DOM_RETRY_COOLDOWN_SECONDS",
    )
    dom_backoff_min_seconds: float = Field(
        default=30.0,
        validation_alias="SCRAPER_DOM_BACKOFF_MIN_SECONDS",
    )
    dom_backoff_max_seconds: float = Field(
        default=90.0,
        validation_alias="SCRAPER_DOM_BACKOFF_MAX_SECONDS",
    )
    dom_max_products_per_run: int = Field(
        default=0,
        validation_alias="SCRAPER_DOM_MAX_PRODUCTS_PER_RUN",
    )
    dom_stale_job_seconds: int = Field(
        default=3_600,
        validation_alias="SCRAPER_DOM_STALE_JOB_SECONDS",
    )
    headless: bool = Field(default=False, validation_alias="SCRAPER_HEADLESS")
    max_products: int = Field(default=10000, validation_alias="SCRAPER_MAX_PRODUCTS")
    import_chunk_size: int = Field(
        default=36, validation_alias="SCRAPER_IMPORT_CHUNK_SIZE"
    )
    translate_parallelism: int = Field(
        default=1,
        validation_alias="SCRAPER_TRANSLATE_PARALLELISM",
    )
    translate_sleep_min: float = Field(
        default=0.4,
        validation_alias="SCRAPER_TRANSLATE_SLEEP_MIN",
    )
    translate_sleep_max: float = Field(
        default=1.2,
        validation_alias="SCRAPER_TRANSLATE_SLEEP_MAX",
    )
    libretranslate_url: str = Field(
        default="",
        validation_alias=AliasChoices(
            "SCRAPER_LIBRETRANSLATE_URL",
            "LIBRETRANSLATE_URL",
        ),
    )
    libretranslate_timeout: float = Field(
        default=60.0,
        validation_alias="SCRAPER_LIBRETRANSLATE_TIMEOUT",
    )
    import_download_images: bool = Field(
        default=False,
        validation_alias="SCRAPER_IMPORT_DOWNLOAD_IMAGES",
    )
    catalog_job_timeout: str = Field(
        default="3h", validation_alias="SCRAPER_CATALOG_JOB_TIMEOUT"
    )
    catalog_import_func: str = Field(
        default="src.jobs.catalog_import_job.run_catalog_import_chunk",
        validation_alias="SCRAPER_CATALOG_IMPORT_FUNC",
    )
    catalog_dom_enrichment_func: str = Field(
        default="src.jobs.catalog_import_job.run_catalog_dom_enrichment_chunk",
        validation_alias="SCRAPER_CATALOG_DOM_ENRICHMENT_FUNC",
    )
    catalog_finalize_func: str = Field(
        default="src.jobs.catalog_import_job.run_catalog_deactivate_missing",
        validation_alias="SCRAPER_CATALOG_FINALIZE_FUNC",
    )
    catalog_dom_job_timeout: str = Field(
        default="3h", validation_alias="SCRAPER_CATALOG_DOM_JOB_TIMEOUT"
    )
    catalog_finalize_job_timeout: str = Field(
        default="30m",
        validation_alias="SCRAPER_CATALOG_FINALIZE_JOB_TIMEOUT",
    )
    catalog_drain_timeout_seconds: int = Field(
        default=14_400,
        validation_alias="SCRAPER_CATALOG_DRAIN_TIMEOUT_SECONDS",
    )
    catalog_drain_poll_seconds: float = Field(
        default=5.0,
        validation_alias="SCRAPER_CATALOG_DRAIN_POLL_SECONDS",
    )
    finalize_missing: bool = Field(
        default=True,
        validation_alias="SCRAPER_FINALIZE_MISSING",
    )
    loop_interval_seconds: int = Field(
        default=86_400,
        validation_alias="SCRAPER_LOOP_INTERVAL_SECONDS",
    )
    collection_urls_csv: str = Field(
        default="", validation_alias="SCRAPER_COLLECTION_URLS"
    )
    proxy_server: str = Field(default="", validation_alias="SCRAPER_PROXY_SERVER")
    proxy_ports: str = Field(default="", validation_alias="SCRAPER_PROXY_PORTS")
    proxy_username: str = Field(default="", validation_alias="SCRAPER_PROXY_USERNAME")
    proxy_password: str = Field(default="", validation_alias="SCRAPER_PROXY_PASSWORD")
    proxy_worker_slot: int | None = Field(
        default=None,
        validation_alias="SCRAPER_PROXY_WORKER_SLOT",
    )
    lane_id: str = Field(default="", validation_alias="SCRAPER_LANE_ID")
    storage_state_path: str = Field(
        default="",
        validation_alias="SCRAPER_STORAGE_STATE_PATH",
    )

    # Финальный прогон только упавших страниц
    recovery_proxy_server: str = Field(
        default="", validation_alias="SCRAPER_RECOVERY_PROXY_SERVER"
    )
    recovery_proxy_ports: str = Field(
        default="", validation_alias="SCRAPER_RECOVERY_PROXY_PORTS"
    )
    recovery_proxy_username: str = Field(
        default="", validation_alias="SCRAPER_RECOVERY_PROXY_USERNAME"
    )
    recovery_proxy_password: str = Field(
        default="", validation_alias="SCRAPER_RECOVERY_PROXY_PASSWORD"
    )

    dom_session_enabled: bool = Field(
        default=False,
        validation_alias="SCRAPER_DOM_SESSION_ENABLED",
    )
    http_cookie_sync_enabled: bool = Field(
        default=False,
        validation_alias="SCRAPER_HTTP_COOKIE_SYNC",
    )
    burst_pacing_enabled: bool = Field(
        default=False,
        validation_alias="SCRAPER_BURST_PACING",
    )
    session_warming_enabled: bool = Field(
        default=False,
        validation_alias="SCRAPER_SESSION_WARMING",
    )
    challenge_throttle_enabled: bool = Field(
        default=False,
        validation_alias="SCRAPER_CHALLENGE_THROTTLE",
    )
    burst_min: int = Field(default=15, validation_alias="SCRAPER_BURST_MIN")
    burst_max: int = Field(default=40, validation_alias="SCRAPER_BURST_MAX")
    burst_pause_min: int = Field(default=20, validation_alias="SCRAPER_BURST_PAUSE_MIN")
    burst_pause_max: int = Field(default=60, validation_alias="SCRAPER_BURST_PAUSE_MAX")
    warm_every_products: int = Field(
        default=400, validation_alias="SCRAPER_WARM_EVERY_PRODUCTS"
    )
    warm_every_minutes: int = Field(
        default=25, validation_alias="SCRAPER_WARM_EVERY_MINUTES"
    )
    challenge_medium_threshold: float = Field(
        default=0.05,
        validation_alias="SCRAPER_CHALLENGE_MEDIUM_THRESHOLD",
    )
    challenge_high_threshold: float = Field(
        default=0.12,
        validation_alias="SCRAPER_CHALLENGE_HIGH_THRESHOLD",
    )
    throttle_cooldown_max: int = Field(
        default=300,
        validation_alias="SCRAPER_THROTTLE_COOLDOWN_MAX",
    )
    throttle_window_size: int = Field(
        default=50,
        validation_alias="SCRAPER_THROTTLE_WINDOW_SIZE",
    )
    lane_429_cooldowns: str = Field(
        default="15,30,45,60",
        validation_alias="SCRAPER_LANE_429_COOLDOWNS",
    )
    lane_429_throttle_enabled: bool = Field(
        default=True,
        validation_alias="SCRAPER_LANE_429_THROTTLE",
    )
    cookie_sync_every_n: int = Field(
        default=50,
        validation_alias="SCRAPER_COOKIE_SYNC_EVERY_N",
    )

    dom_rolling_batch_size: int = Field(
        default=100,
        validation_alias=AliasChoices(
            "SCRAPER_DOM_ROLLING_BATCH_SIZE",
            "SCRAPER_ROLLING_REFRESH_BATCH_SIZE",
        ),
    )
    dom_refresh_stale_hours: int = Field(
        default=6,
        validation_alias=AliasChoices(
            "SCRAPER_DOM_REFRESH_STALE_HOURS",
            "DOM_REFRESH_STALE_HOURS",
        ),
    )
    dom_queue_max_pending: int = Field(
        default=60,
        validation_alias="SCRAPER_DOM_QUEUE_MAX_PENDING",
    )
    dom_enqueue_lock_ttl_seconds: int = Field(
        default=1800,
        validation_alias="SCRAPER_DOM_ENQUEUE_LOCK_TTL_SECONDS",
    )
    dom_processing_claim_ttl_minutes: int = Field(
        default=15,
        validation_alias="SCRAPER_DOM_PROCESSING_CLAIM_TTL_MINUTES",
    )
    dom_owner_token_enqueue_enabled: bool = Field(
        default=False,
        validation_alias="SCRAPER_DOM_OWNER_TOKEN_ENQUEUE_ENABLED",
    )
    dom_rolling_fetch_multiplier: int = Field(
        default=3,
        validation_alias="SCRAPER_DOM_ROLLING_FETCH_MULTIPLIER",
    )
    # Восстановление отпечатка шапки за такт. Пакет по умолчанию=100, fetch_limit=300;
    # Планировщик использует значение min(это значение, batch_size // 2),
    # поэтому восстановление не может заполнить пакет.
    dom_priority_recovery_limit: int = Field(
        default=20,
        validation_alias="SCRAPER_DOM_PRIORITY_RECOVERY_LIMIT",
    )
    dom_doctor_batch_size: int = Field(
        default=50,
        validation_alias="SCRAPER_DOM_DOCTOR_BATCH_SIZE",
    )

    # Возвращает список URL коллекций: из env через запятую или дефолтный набор.
    def get_collection_urls(self) -> list[str]:
        raw = self.collection_urls_csv.strip()
        if not raw:
            return list(DEFAULT_COLLECTION_URLS)
        return [u.strip() for u in raw.split(",") if u.strip()]


# RQ timeout "3h" / "30m" / "90" → секунды; иначе None.
def duration_to_seconds(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float):
        return max(0, int(value))
    if not isinstance(value, str):
        return None
    raw = value.strip().lower()
    if not raw:
        return None
    try:
        if raw.endswith("h"):
            return max(0, int(float(raw[:-1]) * 3600))
        if raw.endswith("m"):
            return max(0, int(float(raw[:-1]) * 60))
        if raw.endswith("s"):
            return max(0, int(float(raw[:-1])))
        return max(0, int(float(raw)))
    except (TypeError, ValueError):
        return None


# Целое поле env или fallback, если mock/битое значение.
def _positive_int(value: object, fallback: int) -> int:
    if isinstance(value, bool):
        return fallback
    if isinstance(value, int):
        return value if value >= 1 else fallback
    if isinstance(value, str):
        try:
            parsed = int(value)
        except ValueError:
            return fallback
        return parsed if parsed >= 1 else fallback
    return fallback


# DB claim TTL: не короче catalog_dom_job_timeout.
def resolved_dom_processing_claim_ttl_minutes(env: Settings) -> int:
    configured = _positive_int(
        getattr(env, "dom_processing_claim_ttl_minutes", None), 1
    )
    job_seconds = duration_to_seconds(getattr(env, "catalog_dom_job_timeout", None))
    if job_seconds is None:
        return configured
    job_minutes = max(1, (job_seconds + 59) // 60)
    return max(configured, job_minutes)


# Redis enqueue lock TTL: не короче catalog_dom_job_timeout.
def resolved_dom_enqueue_lock_ttl_seconds(env: Settings) -> int:
    configured = _positive_int(getattr(env, "dom_enqueue_lock_ttl_seconds", None), 1)
    job_seconds = duration_to_seconds(getattr(env, "catalog_dom_job_timeout", None))
    if job_seconds is None:
        return configured
    return max(configured, max(1, job_seconds))


def load_settings() -> Settings:
    return Settings()
