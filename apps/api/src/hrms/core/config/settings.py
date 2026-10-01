from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

#: Repository-visible development defaults (`env/.env.dev.example`, this file's own field
#: defaults). Must never be reachable outside `environment=development` — see
#: `_guard_non_development_secrets` below (SEC-01, PLATFORM_READINESS_SECURITY_AUDIT_2026-09-17
#: §OPS-01/SEC-01, Production Hardening Batch 1).
_DEV_JWT_ACCESS_SECRET_DEFAULT = "change-me-local-dev-only-min-16"
_DEV_JWT_REFRESH_SECRET_DEFAULT = "change-me-local-dev-too-min-16"

#: DATA-01 (`docs/audits/DATA_01_PII_ENCRYPTION_IMPLEMENTATION_PLAN.md` §5.4) — the repository-
#: visible development-only local encryption key. `DekCache` only honors this in
#: `environment=development` (mirroring the JWT-secret pattern above); staging/production use
#: `_DEV_PII_MASTER_KEY_DEFAULT` below instead, guarded the same way the JWT secrets are.
_DEV_ENCRYPTION_KEY_DEFAULT = "change-me-local-dev-encryption-key-min-16"

#: RELEASE_HARDENING_PHASE_3A (`docs/audits/RELEASE_HARDENING_PHASE_3A_SECURITY_REMEDIATION.md`
#: §9) — the application-level master key that wraps this environment's DEK(s)
#: (`core/crypto/master_key.py`), replacing this project's previous AWS KMS dependency: KMS was a
#: hard, enforced boot-time requirement for every non-development environment, which directly
#: contradicted the deployment's cost-constrained, self-hosted (Hostinger VPS, no AWS-managed
#: services) architecture. Guarded exactly like the JWT signing secrets below — required, must not
#: be the repository-visible dev default, must meet the same entropy floor.
_DEV_PII_MASTER_KEY_DEFAULT = "change-me-local-dev-pii-master-key-min-16"

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
    # `_split_comma_list`. `NoDecode` (RELEASE_HARDENING_PHASE_3B) is required for a `tuple[str,
    # ...]` field to actually take that codepath from a real environment variable/`.env` file:
    # without it, pydantic-settings' own `EnvSettingsSource` treats any complex-typed field as
    # JSON and tries `json.loads()` on the raw string *before* this field's `mode="before"`
    # validator ever runs, raising `SettingsError` on every plain comma-separated value — a
    # container boot failure this codebase's own tests never caught, because every existing test
    # constructs `Settings(cors_allowed_origins=(...))` directly (bypassing the env-var decode
    # path entirely) rather than through a real `CORS_ALLOWED_ORIGINS` environment variable. Found
    # by actually running `docker compose -f docker-compose.prod.yml run migrate` against a real
    # `.env.production` file — see RELEASE_HARDENING_PHASE_3B_PRODUCTION_INFRASTRUCTURE.md.
    cors_allowed_origins: Annotated[tuple[str, ...], NoDecode] = ()

    # OPS-02 — hosts/CIDRs of the immediate reverse proxy(ies) allowed to set
    # `X-Forwarded-For`/`X-Forwarded-Proto`. Empty by default: a direct connection's
    # `X-Forwarded-For` is then always ignored (`app.py` wires this into
    # `uvicorn.middleware.proxy_headers.ProxyHeadersMiddleware`, which resolves the real client
    # through a chain of trusted hops rather than trusting the header wholesale). Same `NoDecode`
    # requirement as `cors_allowed_origins` above, same reason.
    trusted_proxy_hosts: Annotated[tuple[str, ...], NoDecode] = ()

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
    # scoped EmailSender's own config. `email_provider` is deliberately its own explicit flag.
    # RELEASE_HARDENING_PHASE_5A (`docs/audits/RELEASE_HARDENING_PHASE_5A_EMAIL.md`) replaced the
    # previous `"ses"` option (a hard AWS SES dependency, contradicting this deployment's no-AWS
    # architecture — the same contradiction Phase 3A found and fixed for KMS) with `"smtp"`, a
    # provider-agnostic authenticated-SMTP transport; `"mailtrap"` (a transactional-email vendor's
    # HTTP API, called via `httpx` rather than SMTP) was added alongside it so switching providers
    # is a config change, not a code change — both implement the same `EmailSender` protocol in
    # `onboarding/email_sender.py`. Defaults to the logging-only sender everywhere until
    # explicitly switched; `_guard_non_development_config` below refuses to boot staging/
    # production with `"logging"` still selected, so a pilot deployment can never silently believe
    # emails are being sent when they are merely being logged.
    email_provider: Literal["logging", "smtp", "mailtrap"] = "logging"

    # Sender identity shown on outgoing email — shared by whichever provider is active (`"smtp"`
    # or `"mailtrap"`); not itself an SMTP protocol detail, despite the field name predating the
    # `"mailtrap"` option.
    smtp_from_email: str = ""
    smtp_from_name: str = "Staff Spectrum HRMS"

    # SMTP transport config (RELEASE_HARDENING_PHASE_5A) — only meaningful, and only validated,
    # when `email_provider == "smtp"` (see `_guard_smtp_config` below). Deliberately provider-
    # agnostic: any standard authenticated SMTP endpoint (a transactional-email vendor's SMTP
    # relay, a self-hosted MTA, etc.) works — nothing here names a specific commercial vendor.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    # STARTTLS (upgrade a plaintext connection) — the common case for port 587/25.
    smtp_use_tls: bool = True
    # Implicit TLS from the first byte (common for port 465). Mutually exclusive in practice with
    # STARTTLS, but both are validated together, not toggled automatically by port number, so the
    # operator's choice is always explicit.
    smtp_use_ssl: bool = False

    # Mailtrap Send API config — only meaningful, and only validated, when
    # `email_provider == "mailtrap"` (see `_guard_mailtrap_config` below). `MailtrapEmailSender`
    # calls Mailtrap's HTTP API directly over `httpx` rather than via Mailtrap's own (synchronous)
    # Python SDK, to stay consistent with this module's fully async transport.
    mailtrap_api_token: str = ""

    # Face attendance (`attendance/face_verification.py`). `"disabled"` (the default) rejects every
    # face punch/enrollment as unavailable — there is deliberately no fake always-match provider,
    # since one leaking into a real deployment would let anyone punch as anyone.
    face_verification_provider: Literal["disabled", "facepp"] = "disabled"
    facepp_api_key: str = ""
    facepp_api_secret: str = ""
    facepp_api_base_url: str = "https://api-us.faceplusplus.com"
    # Applied on top of the provider's own verified/not-verified verdict.
    face_match_min_similarity: float = Field(default=0.90, ge=0.0, le=1.0)
    face_provider_timeout_seconds: float = Field(default=15.0, gt=0.0)
    # Failed face punches allowed per employee within the window before further tries get a 429.
    face_punch_max_failed_attempts: int = Field(default=5, ge=1)
    face_punch_attempt_window_minutes: int = Field(default=10, ge=1)
    # How long an HR-opened self-enrollment window stays usable.
    face_enrollment_window_hours: int = Field(default=48, ge=1)
    # Turned-head captures score lower than straight-on ones; each must still clear this against
    # the front capture to prove all angles are the same person.
    face_enrollment_angle_min_similarity: float = Field(default=0.80, ge=0.0, le=1.0)

    web_app_base_url: str = "http://localhost:3000"

    # PAY-006 (`docs/audits/PAYROLL_BUSINESS_DECISIONS.md` decision 16) — employees with
    # unresolved INCOMPLETE days are reminded daily from this many days before an open attendance
    # period's end until it is closed; HR gets a matching digest.
    attendance_incomplete_reminder_lead_days: int = 3

    rate_limit_window_ms: int = 60000
    rate_limit_max: int = 100

    celery_broker_url: str | None = None
    celery_result_backend: str | None = None

    # RELEASE_HARDENING_PHASE_3A — the application master key that wraps this environment's DEK(s)
    # (`core/crypto/master_key.py`). See `_DEV_PII_MASTER_KEY_DEFAULT` above for why this replaced
    # the previous `kms_cmk_arn` AWS KMS setting.
    pii_master_key: str = Field(default=_DEV_PII_MASTER_KEY_DEFAULT, min_length=16)

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
    def _guard_smtp_config(self) -> "Settings":
        """RELEASE_HARDENING_PHASE_5A — validated whenever `"smtp"` is selected, in every
        environment (not only staging/production): a half-configured SMTP transport should fail
        loudly at boot, not on the first email a real user is waiting on. `"logging"` requires
        none of this — the fields below stay at their empty defaults and are never read."""
        if self.email_provider != "smtp":
            return self

        if not self.smtp_host:
            raise ValueError(
                "smtp_host must be set explicitly when email_provider='smtp' — refusing to boot "
                "without an SMTP endpoint to send through."
            )
        if not (1 <= self.smtp_port <= 65535):
            raise ValueError(
                f"smtp_port ({self.smtp_port}) is not a valid TCP port for email_provider='smtp'."
            )
        if not self.smtp_from_email:
            raise ValueError(
                "smtp_from_email must be set explicitly when email_provider='smtp' — refusing to "
                "boot without a sender address."
            )
        # Paired, not individually required: an internal relay that accepts unauthenticated
        # submission from this host is a legitimate configuration; a username with no password
        # (or vice versa) is always a mistake, not a valid unauthenticated setup.
        if bool(self.smtp_username) != bool(self.smtp_password):
            raise ValueError(
                "smtp_username and smtp_password must both be set, or both left empty, for "
                "email_provider='smtp' — a lone username or password is not a valid credential."
            )
        if not self.smtp_use_tls and not self.smtp_use_ssl:
            raise ValueError(
                "email_provider='smtp' requires encrypted transport — set smtp_use_tls=true "
                "(STARTTLS) or smtp_use_ssl=true (implicit TLS); refusing to send production "
                "credentials and PII-adjacent email content over plaintext SMTP."
            )
        if self.smtp_use_tls and self.smtp_use_ssl:
            raise ValueError(
                "smtp_use_tls and smtp_use_ssl are mutually exclusive — choose STARTTLS (587) or "
                "implicit TLS (465), not both."
            )

        return self

    @model_validator(mode="after")
    def _guard_mailtrap_config(self) -> "Settings":
        """Mirrors `_guard_smtp_config` above for the `"mailtrap"` provider: validated whenever
        `"mailtrap"` is selected, in every environment, so a half-configured Mailtrap transport
        fails loudly at boot rather than on the first email a real user is waiting on."""
        if self.email_provider != "mailtrap":
            return self

        if not self.mailtrap_api_token:
            raise ValueError(
                "mailtrap_api_token must be set explicitly when email_provider='mailtrap' — "
                "refusing to boot without an API token to authenticate with."
            )
        if not self.smtp_from_email:
            raise ValueError(
                "smtp_from_email must be set explicitly when email_provider='mailtrap' — "
                "refusing to boot without a sender address."
            )

        return self

    @model_validator(mode="after")
    def _guard_face_verification_config(self) -> "Settings":
        if self.face_verification_provider == "facepp" and not (
            self.facepp_api_key and self.facepp_api_secret
        ):
            raise ValueError(
                "facepp_api_key and facepp_api_secret must both be set explicitly when "
                "face_verification_provider='facepp' — refusing to boot without credentials to "
                "authenticate with."
            )
        return self

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
            ("pii_master_key", self.pii_master_key, _DEV_PII_MASTER_KEY_DEFAULT),
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

        # RELEASE_HARDENING_PHASE_5A — `"logging"` never delivers a real email; a pilot deployment
        # must never be able to silently believe verification/invite/password-reset emails are
        # being sent when they are, in fact, only written to a log line. `_guard_smtp_config`/
        # `_guard_mailtrap_config` (above) have already validated the chosen provider's own fields
        # by the time this is reached.
        if self.email_provider not in ("smtp", "mailtrap"):
            raise ValueError(
                "email_provider must be 'smtp' or 'mailtrap' for environment="
                f"{self.environment!r} — refusing to boot with the logging-only email sender in "
                "a non-development environment; real users cannot receive verification, invite, "
                "or password-reset emails otherwise."
            )

        # DATA-01 (plan §5.4/§10.3) — the complementary, database-backed half of the boot guard
        # (at least one ACTIVE `encryption_keys` row) requires a query and cannot run here — it is
        # enforced separately, in `app.py`'s `lifespan()`, the same place `get_engine` first
        # touches the database. `pii_master_key` itself is validated above, in the same loop as
        # the JWT secrets (RELEASE_HARDENING_PHASE_3A — this used to be a separate KMS-specific
        # check here).

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
