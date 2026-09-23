from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

#: Repository-visible development defaults (`env/.env.dev.example`, this file's own field
#: defaults). Must never be reachable outside `environment=development` — see
#: `_guard_non_development_secrets` below (SEC-01, PLATFORM_READINESS_SECURITY_AUDIT_2026-09-17
#: §OPS-01/SEC-01, Production Hardening Batch 1).
_DEV_JWT_ACCESS_SECRET_DEFAULT = "change-me-local-dev-only-min-16"
_DEV_JWT_REFRESH_SECRET_DEFAULT = "change-me-local-dev-too-min-16"

#: DATA-01 (`docs/audits/DATA_01_PII_ENCRYPTION_IMPLEMENTATION_PLAN.md` §5.4) — the repository-
#: visible development-only local encryption key. Never a real KMS-wrapped DEK; `DekCache` only
#: honors this in `environment=development` (mirroring the JWT-secret pattern above), and
#: `_guard_non_development_config` below refuses to boot staging/production with `kms_cmk_arn`
#: unset or equal to the placeholder value.
_DEV_ENCRYPTION_KEY_DEFAULT = "change-me-local-dev-encryption-key-min-16"
_DEV_KMS_CMK_ARN_PLACEHOLDER = "__FROM_SECRETS_MANAGER__"

#: Entropy/strength floor for staging+production JWT secrets. Deliberately well above the
#: 16-char `Field(min_length=...)` sanity check below — that floor is satisfied by the known
#: dev default, so it cannot be the thing standing between a forgotten secret and a booted
#: production API.
_MIN_NON_DEV_SECRET_LENGTH = 32
_MIN_NON_DEV_SECRET_UNIQUE_CHARS = 8


def _is_weak_secret(secret: str) -> bool:
    if len(secret) < _MIN_NON_DEV_SECRET_LENGTH:
        return True
    return len(set(secret)) < _MIN_NON_DEV_SECRET_UNIQUE_CHARS


def _split_comma_list(value: object) -> object:
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    return value


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

    jwt_access_secret: str = Field(default=_DEV_JWT_ACCESS_SECRET_DEFAULT, min_length=16)
    jwt_access_ttl_minutes: int = 15
    jwt_refresh_secret: str = Field(default=_DEV_JWT_REFRESH_SECRET_DEFAULT, min_length=16)
    jwt_refresh_ttl_days: int = 30

    # OPS-01 (PLATFORM_READINESS_SECURITY_AUDIT_2026-09-17) — empty outside `development` by
    # design: `_guard_non_development_config` below fails boot rather than silently falling
    # back to `["*"]`/`[]`/localhost. Accepts a comma-separated string from the environment
    # (`CORS_ALLOWED_ORIGINS=https://a.example.com,https://b.example.com`) via
    # `_split_comma_list`.
    cors_allowed_origins: tuple[str, ...] = ()

    # OPS-02 — hosts/CIDRs of the immediate reverse proxy(ies) allowed to set
    # `X-Forwarded-For`/`X-Forwarded-Proto`. Empty by default: a direct connection's
    # `X-Forwarded-For` is then always ignored (`app.py` wires this into
    # `uvicorn.middleware.proxy_headers.ProxyHeadersMiddleware`, which resolves the real client
    # through a chain of trusted hops rather than trusting the header wholesale).
    trusted_proxy_hosts: tuple[str, ...] = ()

    app_timezone_default: str = "Asia/Kolkata"

    # `DEC-TZ-02` (SELECTED) — India V1 restricts both public registration and authenticated
    # company-profile edits to this list. A setting rather than a hard-coded constant so
    # international expansion is a configuration change, not a code release (execution gate §6.3).
    allowed_company_timezones: tuple[str, ...] = ("Asia/Kolkata",)

    aws_region: str = "ap-south-1"
    s3_bucket_documents: str = ""
    # INFRA-01 (docs/audits/UPLOAD_BATCH_A_STORAGE_ARCHITECTURE.md) — the S3-compatible endpoint
    # `DocumentStorageService` talks to for every operation except presigned-URL generation.
    # Self-hosted MinIO on the Hostinger VPS, not AWS: `None` is only ever valid in development
    # (docker-compose's `minio` service is resolved via `.env`'s explicit
    # `S3_ENDPOINT_URL=http://localhost:9000`); `_guard_non_development_config` below refuses to
    # boot staging/production without an explicit value, specifically because aioboto3/boto3
    # silently resolve to real AWS S3 when `endpoint_url` is left unset.
    s3_endpoint_url: str | None = None
    # The hostname presigned GET URLs are signed against and handed to a browser, when it differs
    # from `s3_endpoint_url` above — true in every deployed environment, where MinIO's S3 API
    # sits on an internal Docker network address (e.g. `http://minio:9000`) that no browser can
    # resolve, while the public, Nginx-fronted hostname (e.g. `https://storage.hrms.example.com`)
    # is what the presigned URL's signature must be computed against so Nginx can forward the
    # request to MinIO with a matching `Host` header. Falls back to `s3_endpoint_url` when unset
    # (development, or any environment where the two happen to be the same host).
    s3_public_endpoint_url: str | None = None
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

    # DATA-01 (`docs/audits/DATA_01_PII_ENCRYPTION_IMPLEMENTATION_PLAN.md` §2.1/§5) — the KMS
    # customer-managed key (ARN or alias) that wraps this environment's application DEK(s).
    # Empty outside development by design: `_guard_non_development_config` below fails boot
    # rather than silently falling back to a fake/no-op key, matching SEC-01/OPS-01's own posture.
    kms_cmk_arn: str = ""

    # Development-only local encryption key (plan §5.4) — never used outside
    # `environment=development`; see `_DEV_ENCRYPTION_KEY_DEFAULT` above.
    dev_encryption_key: str = _DEV_ENCRYPTION_KEY_DEFAULT

    # Plan §2.1 — how long a resolved plaintext DEK stays cached in-process before the next
    # operation re-resolves it from the registry (not necessarily from KMS again, §2.2).
    encryption_dek_cache_ttl_seconds: int = 3600

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

    @field_validator("cors_allowed_origins", "trusted_proxy_hosts", mode="before")
    @classmethod
    def _parse_comma_separated(cls, value: object) -> object:
        return _split_comma_list(value)

    @model_validator(mode="after")
    def _guard_non_development_config(self) -> "Settings":
        """SEC-01/OPS-01 (PLATFORM_READINESS_SECURITY_AUDIT_2026-09-17) — enforced here, not
        only documented, because `env/.env.production.example` already documented Secrets
        Manager injection and that alone did not stop production from booting on defaults.
        Runs on every `Settings()` construction (`get_settings()` included), so a
        misconfigured staging/production process fails at boot, not on first request."""
        if self.is_development:
            return self

        for field_name, value, dev_default in (
            ("jwt_access_secret", self.jwt_access_secret, _DEV_JWT_ACCESS_SECRET_DEFAULT),
            ("jwt_refresh_secret", self.jwt_refresh_secret, _DEV_JWT_REFRESH_SECRET_DEFAULT),
        ):
            if not value:
                raise ValueError(
                    f"{field_name} must be set explicitly for environment={self.environment!r} "
                    "— refusing to boot without a production secret."
                )
            if value == dev_default:
                raise ValueError(
                    f"{field_name} is still the repository-visible development default for "
                    f"environment={self.environment!r} — refusing to boot with a public secret."
                )
            if _is_weak_secret(value):
                raise ValueError(
                    f"{field_name} does not meet the minimum strength requirement "
                    f"({_MIN_NON_DEV_SECRET_LENGTH}+ characters, "
                    f"{_MIN_NON_DEV_SECRET_UNIQUE_CHARS}+ distinct characters) for "
                    f"environment={self.environment!r}."
                )

        if not self.cors_allowed_origins:
            raise ValueError(
                "cors_allowed_origins must list at least one explicit origin for "
                f"environment={self.environment!r} — refusing to boot with no CORS origins."
            )

        # INFRA-01 (docs/audits/UPLOAD_BATCH_A_STORAGE_ARCHITECTURE.md) — without an explicit
        # `s3_endpoint_url`, aioboto3/boto3 resolve the S3 client against real AWS S3 rather than
        # the self-hosted MinIO instance this deployment actually runs. Refusing to boot rather
        # than documenting the requirement is the same posture as the JWT/CORS/KMS guards above:
        # a missing endpoint override must be a boot failure, not a silent connection to the
        # wrong (and, for a non-AWS deployment, nonexistent) bucket.
        if not self.s3_endpoint_url:
            raise ValueError(
                "s3_endpoint_url must be set explicitly for environment="
                f"{self.environment!r} — refusing to boot without it, since an unset endpoint "
                "resolves to real AWS S3 rather than this deployment's self-hosted MinIO."
            )
        if not self.s3_bucket_documents:
            raise ValueError(
                "s3_bucket_documents must be set explicitly for environment="
                f"{self.environment!r} — refusing to boot without a document storage bucket."
            )
        if not self.aws_access_key_id or not self.aws_secret_access_key:
            raise ValueError(
                "aws_access_key_id and aws_secret_access_key must both be set explicitly for "
                f"environment={self.environment!r} — refusing to boot without object storage "
                "credentials (self-hosted MinIO has no IAM instance-role fallback)."
            )

        # DATA-01 (plan §5.4/§10.3) — the Settings-level half of the boot guard: a real KMS key
        # must be configured. The complementary half (at least one ACTIVE `encryption_keys` row)
        # requires a database query and cannot run here — it is enforced separately, in `app.py`'s
        # `lifespan()`, the same place `get_engine` first touches the database.
        if not self.kms_cmk_arn:
            raise ValueError(
                "kms_cmk_arn must be set explicitly for environment="
                f"{self.environment!r} — refusing to boot without a KMS key for PII encryption."
            )
        if self.kms_cmk_arn == _DEV_KMS_CMK_ARN_PLACEHOLDER:
            raise ValueError(
                "kms_cmk_arn is still the documentation placeholder for environment="
                f"{self.environment!r} — refusing to boot with an unresolved secret reference."
            )

        return self

    @property
    def effective_cors_origins(self) -> list[str]:
        """The origin list `app.py` hands to `CORSMiddleware`. Never `["*"]`: outside
        development `_guard_non_development_config` has already required an explicit list, and
        in development an explicit fallback (rather than a wildcard) keeps
        `allow_credentials=True` a valid, browser-accepted combination (OPS-01)."""
        if self.cors_allowed_origins:
            return list(self.cors_allowed_origins)
        # Development-only fallback — unreachable with an empty list outside development.
        return list(dict.fromkeys([self.web_app_base_url, "http://localhost:3000"]))

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
