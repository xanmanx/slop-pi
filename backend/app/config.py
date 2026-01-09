"""Configuration management for slop-pi."""

from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=("../../.env", "../.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    environment: str = "development"
    log_level: str = "info"

    # Supabase
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str

    # USDA FoodData Central
    usda_api_key: str

    # OpenAI
    openai_api_key: str

    # Notifications (ntfy.sh)
    ntfy_server: str = "https://ntfy.sh"
    ntfy_topic: str | None = None

    # Cron
    cron_secret: str | None = None

    # API Security
    pi_api_key: str | None = None

    # Paths
    data_dir: str = "./data"
    usda_cache_db: str = "./data/usda_cache.db"

    # Feature Flags
    feature_barcode_lookup: bool = True
    feature_receipt_ocr: bool = False  # Phase 2
    feature_price_tracking: bool = False  # Phase 2
    feature_expiration_dates: bool = False  # Phase 2
    feature_inventory_prediction: bool = False  # Phase 3
    feature_drinks_caffeine: bool = False  # Phase 3

    # Consumption processing frequency in minutes
    # Note: Timezone is now per-user from their preferences (foodos2_preference_profiles.timezone)
    consumption_interval_minutes: int = 2

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
