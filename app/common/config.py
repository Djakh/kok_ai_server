from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "KOK.AI API"
    env: str = "dev"
    debug: bool = False
    api_prefix: str = "/api/v1"

    database_url: str = "postgresql+psycopg://kok:kok@localhost:5432/kok"
    redis_url: str = "redis://localhost:6379/0"

    jwt_access_secret: str = Field(default="change_me_access_secret_123", min_length=16)
    jwt_refresh_secret: str = Field(default="change_me_refresh_secret_456", min_length=16)
    jwt_access_expire_minutes: int = 15
    jwt_refresh_expire_days: int = 30

    cors_origins: str = "*"

    public_api_base_url: str = "http://localhost:8000"
    minimum_supported_mobile_version: str = "1.0.0"
    latest_mobile_version: str = "1.0.0"
    ios_store_url: str | None = None
    android_store_url: str | None = None
    maintenance_mode: bool = False
    maintenance_message: str | None = None
    kindwise_api_key: str = ""
    kindwise_base_url: str = "https://plant.id/api/v3"
    kindwise_language: Literal["en", "ru", "uz"] = "en"
    kindwise_fallback_language: Literal["en"] = "en"
    kindwise_health_mode: Literal["off", "auto", "all"] = "off"
    kindwise_suggestion_filter: str = "tree"
    kindwise_classification_level: str = "species"
    kindwise_timeout_seconds: float = Field(default=12.0, gt=0, le=30)
    kindwise_max_concurrency: int = Field(default=4, ge=1, le=100)
    idempotency_ttl_hours: int = Field(default=24, ge=24, le=720)
    abandoned_upload_ttl_hours: int = Field(default=24, ge=1, le=720)
    analysis_ttl_hours: int = Field(default=24, ge=1, le=720)

    ai_max_images: int = Field(default=5, ge=1, le=5)
    ai_max_image_bytes: int = Field(default=15 * 1024 * 1024, gt=0)
    ai_max_request_bytes: int = Field(default=40_000_000, gt=0)
    request_multipart_overhead_bytes: int = Field(default=2_000_000, ge=0, le=5_000_000)
    ai_max_pixels: int = Field(default=40_000_000, gt=0)
    ai_low_confidence_threshold: float = Field(default=0.55, ge=0, le=1)
    ai_max_concurrent_analyses: int = Field(default=4, ge=1, le=100)
    analysis_rate_limit_per_minute: int = Field(default=10, ge=1, le=10_000)
    s3_endpoint_url: str = "http://localhost:9000"
    s3_access_key: str = "minioadmin"
    s3_secret_key: str = "minioadmin"
    s3_bucket: str = "kok-assets"
    s3_region: str = "us-east-1"
    s3_public_base_url: str = "http://localhost:9000"
    s3_use_ssl: bool = False
    s3_initialize_bucket_on_startup: bool = False

    max_image_size_bytes: int = 15 * 1024 * 1024
    allowed_image_types: str = "image/jpeg,image/png"

    rate_limit_auth_per_minute: int = 20
    rate_limit_write_per_minute: int = 60

    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    tree_detector_enabled: bool = False
    tree_detector_model_path: str = "tree_detector/treedetect.pt"
    tree_detector_confidence: float = 0.25
    tree_detector_model_version: str = "treedetect.pt"

    model_config = SettingsConfigDict(
        env_prefix="KOK_",
        env_file=".env",
        case_sensitive=False,
        extra="ignore",
    )

    @property
    def allowed_image_types_list(self) -> list[str]:
        return [x.strip() for x in self.allowed_image_types.split(",") if x.strip()]

    @property
    def cors_origins_list(self) -> list[str]:
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]

    @property
    def is_production(self) -> bool:
        return self.env.lower() in {"production", "prod"}

    def production_config_errors(self) -> list[str]:
        if not self.is_production:
            return []
        errors: list[str] = []
        if not self.kindwise_api_key:
            errors.append("KOK_KINDWISE_API_KEY is required")
        if "*" in self.cors_origins_list:
            errors.append("KOK_CORS_ORIGINS must be an explicit allowlist")
        if "localhost" in self.database_url or "@localhost" in self.database_url:
            errors.append("KOK_DATABASE_URL must not point to localhost")
        if "localhost" in self.redis_url:
            errors.append("KOK_REDIS_URL must not point to localhost")
        if self.jwt_access_secret.startswith("change_me") or self.jwt_refresh_secret.startswith(
            "change_me"
        ):
            errors.append("JWT secrets must be changed")
        if not self.s3_bucket or not self.s3_access_key or not self.s3_secret_key:
            errors.append("S3-compatible object storage settings are required")
        if "localhost" in self.s3_endpoint_url or "localhost" in self.s3_public_base_url:
            errors.append("KOK_S3 endpoints must not point to localhost")
        if not self.kindwise_base_url.startswith("https://"):
            errors.append("KOK_KINDWISE_BASE_URL must use HTTPS")
        if not self.public_api_base_url.startswith("https://"):
            errors.append("KOK_PUBLIC_API_BASE_URL must use HTTPS")
        if self.ios_store_url and not self.ios_store_url.startswith("https://"):
            errors.append("KOK_IOS_STORE_URL must use HTTPS")
        if self.android_store_url and not self.android_store_url.startswith("https://"):
            errors.append("KOK_ANDROID_STORE_URL must use HTTPS")
        if self.kindwise_health_mode not in {"off", "auto", "all"}:
            errors.append("KOK_KINDWISE_HEALTH_MODE must be off, auto, or all")
        if self.ai_max_request_bytes > 50_000_000:
            errors.append("KOK_AI_MAX_REQUEST_BYTES must not exceed the provider limit")
        return errors


@lru_cache
def get_settings() -> Settings:
    return Settings()
