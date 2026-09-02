from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings — validated at boot (Document 10 §4, Document 13 §1)."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: Literal["development", "staging", "production"] = "development"
    port: int = 8000
    log_level: str = "INFO"

    database_url: str = Field(
        default="postgresql://hrms:hrms_dev_password@localhost:5433/hrms_dev",
        description="Async SQLAlchemy URL (postgresql+asyncpg://…)",
    )
    redis_url: str = "redis://localhost:6380/0"

    jwt_access_secret: str = Field(default="change-me-local-dev-only-min-16", min_length=16)
    jwt_access_ttl_minutes: int = 15
    jwt_refresh_secret: str = Field(default="change-me-local-dev-too-min-16", min_length=16)
    jwt_refresh_ttl_days: int = 30

    app_timezone_default: str = "Asia/Kolkata"

    aws_region: str = "ap-south-1"
    s3_bucket_documents: str = ""
    s3_endpoint_url: str | None = None
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""

    # Onboarding O3 (docs/modules/onboarding/01_ONBOARDING_MODULE_PLAN.md §8.4) — the minimal
    # scoped EmailSender's own config. `email_provider` is deliberately its own explicit flag,
    # not inferred from `aws_access_key_id`/`aws_secret_access_key` above — those credentials are
    # also used for the MinIO-backed S3 client (O5), which is configured in every local dev
    # environment today, so "AWS credentials present" is no longer a safe proxy for "real SES is
    # reachable with them." Defaults to the logging-only sender everywhere until explicitly
    # switched to "ses".
    email_provider: Literal["logging", "ses"] = "logging"
    email_sender_from_address: str = "onboarding@hrms.local"
    web_app_base_url: str = "http://localhost:3000"

    rate_limit_window_ms: int = 60000
    rate_limit_max: int = 100

    celery_broker_url: str | None = None
    celery_result_backend: str | None = None

    @field_validator("database_url", mode="before")
    @classmethod
    def ensure_asyncpg_driver(cls, value: str) -> str:
        # Prisma-style ?schema=public is not a valid libpq/asyncpg option.
        if "?schema=" in value:
            value = value.split("?", 1)[0]
        if value.startswith("postgresql://"):
            return "postgresql+asyncpg://" + value[len("postgresql://") :]
        if value.startswith("postgres://"):
            return "postgresql+asyncpg://" + value[len("postgres://") :]
        return value

    @property
    def celery_broker(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def celery_backend(self) -> str:
        return self.celery_result_backend or self.redis_url

    @property
    def is_development(self) -> bool:
        return self.environment == "development"


@lru_cache
def get_settings() -> Settings:
    return Settings()
