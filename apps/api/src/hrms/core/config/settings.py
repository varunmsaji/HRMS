from functools import lru_cache
from typing import Annotated, Literal
from urllib.parse import urlparse
from uuid import UUID

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

#: FINDING-001 — the development frontend origin. Safe for a local `next dev` on port 3000.
#: Outside development this exact value, and any other loopback origin, is refused at boot:
#: verification, password-reset, invite, onboarding, and attendance emails embed it.
_DEV_WEB_APP_BASE_URL_DEFAULT = "http://localhost:3000"
_LOOPBACK_WEB_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0", "::1"})


def _is_weak_secret(secret: str) -> bool:
    if len(secret) < _MIN_NON_DEV_SECRET_LENGTH:
        return True
    return len(set(secret)) < _MIN_NON_DEV_SECRET_UNIQUE_CHARS


def _split_comma_list(value: object) -> object:
    if isinstance(value, str):
        return tuple(item.strip() for item in value.split(",") if item.strip())
    return value


def _normalize_web_app_base_url(value: str) -> str:
    return value.strip().rstrip("/")


def _web_app_base_url_is_unsafe_outside_development(value: str) -> bool:
    """True when `value` must not be embedded in an email outside development.

    Requires an absolute `https` URL whose host is not loopback. A path prefix is allowed
    (`https://app.example.com/hr`). Userinfo, a query, and a fragment are not: they would be
    copied into every reset, verification, invite, and reminder link.
    """
    parsed = urlparse(value)
    host = (parsed.hostname or "").rstrip(".").lower()
    if parsed.scheme.lower() != "https" or not host:
        return True
    if host in _LOOPBACK_WEB_HOSTS or host.endswith(".localhost"):
        return True
    if parsed.username is not None or parsed.password is not None:
        return True
    if parsed.query or parsed.fragment:
        return True
    return False


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
    # Local per-module log files (docs/operations/LOGGING_GUIDE.md). A relative `LOG_DIR` is
    # resolved against the API project root (`apps/api`, `/app` in the image), never the cwd.
    log_to_files: bool = True
    log_dir: str = "logs"
    log_file_max_bytes: int = Field(default=10 * 1024 * 1024, ge=0)
    log_file_backup_count: int = Field(default=5, ge=0, le=100)
    # Age limit for *rotated* backups, in days; 0 = keep by count only.
    log_retention_days: int = Field(default=0, ge=0)
    # true = refuse to start when the log directory is unusable; false = stdout-only fallback.
    log_files_required: bool = False

    database_url: str = Field(
        default="postgresql://hrms:hrms_dev_password@localhost:5433/hrms_dev",
        description="Async SQLAlchemy URL (postgresql+asyncpg://…)",
    )
    redis_url: str = "redis://localhost:6380/0"

    jwt_access_secret: str = Field(default=_DEV_JWT_ACCESS_SECRET_DEFAULT, min_length=16)
    jwt_access_ttl_minutes: int = 15
    jwt_refresh_secret: str = Field(default=_DEV_JWT_REFRESH_SECRET_DEFAULT, min_length=16)
    jwt_refresh_ttl_days: int = 30

    # Platform super-admin console. A newly registered company waits in `PENDING_APPROVAL` (it
    # can sign in and look around, read-only) until a platform admin approves it; turn this off
    # to restore the previous "registers straight into TRIAL" behaviour.
    company_approval_required: bool = True
    #: Platform tokens are short-lived and not refreshable: a platform admin signs in again.
    platform_access_ttl_minutes: int = Field(default=30, ge=1, le=240)
    #: How long a TERMINATED company's data is retained before it becomes eligible for purge.
    #: The purge itself is a separate, deliberately manual operation (nothing deletes data here).
    terminated_company_retention_days: int = Field(default=90, ge=1)

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
    email_provider: Literal["logging", "smtp", "mailtrap", "hostinger"] = "logging"

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

    # Hostinger Mail API config — only meaningful, and only validated, when
    # `email_provider == "hostinger"` (see `_guard_hostinger_config` below). Mail goes out from the
    # mailbox identified by `hostinger_mail_mailbox_id` (its `resourceId`, from `GET /api/v1/me`);
    # the sender address is that mailbox, so `smtp_from_email` is not used by this provider.
    hostinger_mail_api_token: str = ""
    hostinger_mail_mailbox_id: str = ""

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

    # Face liveness / presentation-attack detection (`attendance/liveness.py`), run on this
    # server — never trusted from the client. `"disabled"` (the default) makes face punching and
    # self-enrollment unavailable even when a face provider is configured: there is deliberately
    # no fallback to "face detected = live". `"minifasnet"` needs `face_liveness_model_dir`
    # (the verified `models/liveness/minifasnet-v1` assets) and the `liveness` extra (OpenCV).
    # The thresholds are UNCALIBRATED engineering defaults (see
    # docs/audits/FACE_ATTENDANCE_LIVENESS_IMPLEMENTATION_REPORT.md) — do not enable for
    # production attendance until device/attack calibration has been done and accepted.
    face_liveness_engine: Literal["disabled", "minifasnet"] = "disabled"
    face_liveness_model_dir: str = ""
    # A frame is LIVE when the fused P(real) reaches this; SPOOF_SUSPECTED when P(spoof) reaches
    # `face_liveness_spoof_threshold`; anything between is INCONCLUSIVE (rejected, retry).
    face_liveness_live_threshold: float = Field(default=0.90, gt=0.5, le=1.0)
    face_liveness_spoof_threshold: float = Field(default=0.50, gt=0.0, le=1.0)
    # Frames per face punch; every one must be LIVE. Upper bound matches FACE_LIVENESS_MAX_FRAMES.
    face_liveness_frames: int = Field(default=3, ge=1, le=5)
    # Smallest detected face side (pixels, in the submitted frame) the model is run on.
    face_liveness_min_face_px: int = Field(default=80, ge=32)
    face_liveness_timeout_seconds: float = Field(default=10.0, gt=0.0)
    # Lifetime of a server-issued, single-use liveness challenge.
    face_liveness_session_ttl_seconds: int = Field(default=120, ge=15, le=600)
    # Challenges one employee may request per `face_punch_attempt_window_minutes`.
    face_liveness_sessions_per_window: int = Field(default=20, ge=1)
    # Rejected self-enrollment submissions allowed per HR-opened window before further tries get a
    # 429 (`FACE_ENROLLMENT_ATTEMPTS_EXCEEDED`). Reopening the window (an HR action) starts a new
    # count. Provider/engine outages are not counted; they are not the employee's doing.
    face_enrollment_max_failed_attempts: int = Field(default=5, ge=1)

    # --- Face provider transport (`attendance/face_verification.py`) --------------------------
    # One shared, pooled HTTP client per process. These are OUR OWN bounds, not Face++ limits:
    # the account's real QPS / concurrency / FaceSet quotas are unconfirmed and must be obtained
    # from the vendor (docs/operations/FACE_ATTENDANCE_BASE_RELEASE_RUNBOOK.md §9).
    face_provider_connect_timeout_seconds: float = Field(default=5.0, gt=0.0)
    face_provider_max_concurrency: int = Field(default=4, ge=1, le=64)
    # Wall-clock ceiling for ALL provider calls of one self-enrollment (about 18 sequential
    # requests). Past it the submission is abandoned and any provider person created is removed.
    face_enrollment_provider_budget_seconds: float = Field(default=120.0, gt=0.0)
    # How long a started enrollment submission reserves its window. Must exceed the budget above
    # so a live submission is never mistaken for a dead one; a crashed worker's reservation
    # simply lapses.
    face_enrollment_lease_seconds: int = Field(default=240, ge=30)

    # --- Face endpoint request-level flood limits (`attendance/face_rate_limit.py`) ------------
    # Per (tenant, client IP) per minute, on top of the per-employee limits above. Deliberately
    # generous: they stop a single source flooding the biometric endpoints, they are not an
    # identity control, and a whole office can share one NAT address. The client IP is
    # `request.client.host`, which is the real peer unless it is a `trusted_proxy_hosts` entry.
    face_punch_requests_per_minute_per_ip: int = Field(default=600, ge=1)
    face_enrollment_requests_per_minute_per_ip: int = Field(default=60, ge=1)
    face_review_photo_requests_per_minute_per_ip: int = Field(default=120, ge=1)

    # --- External-deletion outbox (`attendance/face_deletion.py`) -----------------------------
    face_deletion_batch_size: int = Field(default=50, ge=1, le=500)
    # An outbox row still pending after this many attempts is logged at ERROR every run.
    face_deletion_alert_after_attempts: int = Field(default=5, ge=1)

    # Biometric-record retention (`attendance/face_cleanup.py`). The periods are a privacy/legal
    # decision that has NOT been taken, so none is defaulted: `None` means "keep, do nothing".
    # Even when set, the scheduled run only reports (`face_cleanup_dry_run=True`) until an
    # operator turns deletion on deliberately.
    face_liveness_session_retention_days: int | None = Field(default=None, ge=1)
    face_attempt_detail_retention_days: int | None = Field(default=None, ge=1)
    face_enrollment_attempt_retention_days: int | None = Field(default=None, ge=1)
    face_cleanup_dry_run: bool = True
    face_cleanup_batch_size: int = Field(default=500, ge=1, le=5000)
    face_cleanup_max_batches: int = Field(default=20, ge=1, le=1000)
    # Comma-separated company ids whose face records are under a legal/operational hold and are
    # never touched by cleanup.
    face_cleanup_hold_company_ids: str = ""

    # Bounded waits for attendance calculation (`core/db/timeouts.py`). A lock timeout stops a
    # request or sweep step queuing indefinitely behind another transaction's row lock; a
    # statement timeout stops one runaway SQL statement. They are separate knobs because they guard
    # different failures. Applied per calculation with SET LOCAL, never as a global DB setting.
    #
    # - A punch's immediate calculation is best-effort (the punch is already a stored fact and the
    #   scheduled sweep repairs the day), so it gives up quickly instead of delaying the response.
    # - Interactive and scheduled calculations wait longer for a lock but are still bounded.
    attendance_punch_calc_lock_timeout_ms: int = Field(default=1000, ge=100)
    attendance_lock_timeout_ms: int = Field(default=5000, ge=100)
    attendance_statement_timeout_ms: int = Field(default=30000, ge=1000)

    # Monthly leave accrual is scheduled DAILY but only acts during the first N company-local days
    # of a month. A missed day-1 firing (Beat down, worker crash) is then repaired by the next
    # day's run instead of silently losing a month; the cycle keys make every extra run a no-op.
    # Kept short so a retroactively assigned policy cannot back-credit the previous month late in
    # the month, and so a manual balance correction made for a missed run is not credited twice.
    leave_accrual_run_window_days: int = Field(default=5, ge=1, le=28)

    # Year-end processing (lapse / carry-forward cap / encashment / yearly accrual) is scheduled
    # DAILY and, like monthly accrual, repairs a missed firing: on any of the first N company-local
    # days of a leave year it handles every employee whose leave-year start fell in that window and
    # who has not been processed yet (`leave_year_end_run` marks the ones that were). Beyond the
    # window a missed year start is NOT repaired automatically - it needs an operator run.
    leave_year_end_catchup_days: int = Field(default=5, ge=1, le=28)

    # How long a leave request or sweep waits for a leave advisory lock (per-employee date lock,
    # per-balance lock) before giving up with a retryable "busy" error instead of queuing
    # indefinitely behind another transaction (`core/db/timeouts.py`).
    leave_lock_wait_ms: int = Field(default=5000, ge=100)
    # How long a request carrying an `Idempotency-Key` waits for an in-flight request with the same
    # key to finish (then replays its result) before failing with a retryable "busy" error.
    idempotency_wait_ms: int = Field(default=10000, ge=100)

    # Public frontend origin embedded in email links (verification, password reset, account
    # invite, onboarding, attendance reminders). Development keeps the localhost default.
    # `_guard_non_development_config` refuses to boot staging/production on that default, on
    # any other loopback host, or on a non-https URL. Operators set `WEB_APP_BASE_URL` to
    # `https://` plus the same host as compose's `WEB_DOMAIN` (see `.env.production.example`).
    web_app_base_url: str = _DEV_WEB_APP_BASE_URL_DEFAULT

    # PAY-006 (`docs/audits/PAYROLL_BUSINESS_DECISIONS.md` decision 16) — employees with
    # unresolved INCOMPLETE days are reminded daily from this many days before an open attendance
    # period's end until it is closed; HR gets a matching digest.
    attendance_incomplete_reminder_lead_days: int = 3

    # Initial-release product rule: a tenant has exactly one company (the `legal_entity` table)
    # with any number of branches under it. `0` removes the cap (multi-company), which is what the
    # test-suite sets so its multi-entity scenarios keep working.
    max_legal_entities_per_company: int = 1

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

    @field_validator("web_app_base_url")
    @classmethod
    def _canonicalize_web_app_base_url(cls, value: str) -> str:
        # A trailing slash would produce `https://app.example.com//reset-password/...` in every
        # builder that concatenates a path. Strip it once, here, including in development.
        return _normalize_web_app_base_url(value)

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
    def _guard_hostinger_config(self) -> "Settings":
        """Mirrors `_guard_mailtrap_config` for the `"hostinger"` provider."""
        if self.email_provider != "hostinger":
            return self

        if not self.hostinger_mail_api_token:
            raise ValueError(
                "hostinger_mail_api_token must be set explicitly when email_provider='hostinger' — "
                "refusing to boot without an API token to authenticate with."
            )
        if not self.hostinger_mail_mailbox_id:
            raise ValueError(
                "hostinger_mail_mailbox_id must be set explicitly when email_provider='hostinger' "
                "— refusing to boot without a mailbox to send from."
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
        if self.face_liveness_engine != "disabled" and not self.face_liveness_model_dir:
            raise ValueError(
                "face_liveness_model_dir must be set explicitly when face_liveness_engine is "
                "enabled — refusing to boot without the verified model assets."
            )
        if self.face_liveness_live_threshold + self.face_liveness_spoof_threshold <= 1.0:
            raise ValueError(
                "face_liveness_live_threshold + face_liveness_spoof_threshold must exceed 1.0, "
                "otherwise one frame could be both LIVE and SPOOF_SUSPECTED."
            )
        if self.face_enrollment_lease_seconds <= self.face_enrollment_provider_budget_seconds:
            raise ValueError(
                "face_enrollment_lease_seconds must exceed "
                "face_enrollment_provider_budget_seconds, otherwise a live enrollment could "
                "lose its reservation to a second submission."
            )
        # Parsed at boot so a typo in a hold list fails loudly instead of silently un-holding.
        _ = self.face_cleanup_hold_company_id_set
        return self

    @property
    def face_cleanup_hold_company_id_set(self) -> frozenset[UUID]:
        try:
            return frozenset(
                UUID(part.strip())
                for part in self.face_cleanup_hold_company_ids.split(",")
                if part.strip()
            )
        except ValueError as exc:
            raise ValueError(
                "face_cleanup_hold_company_ids must be a comma-separated list of company UUIDs"
            ) from exc

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
        if self.email_provider not in ("smtp", "mailtrap", "hostinger"):
            raise ValueError(
                "email_provider must be 'smtp' or 'mailtrap' for environment="
                f"{self.environment!r} — refusing to boot with the logging-only email sender in "
                "a non-development environment; real users cannot receive verification, invite, "
                "or password-reset emails otherwise."
            )

        # FINDING-001 — those emails embed `web_app_base_url`. The field default is
        # http://localhost:3000, and nothing else in this guard used to notice. A process that
        # followed `.env.production.example` therefore sent real mail whose links only resolved
        # on the API host. Refuse that, and any other loopback or cleartext origin. Do not
        # substitute a hard-coded production host: the operator must set WEB_APP_BASE_URL.
        if _web_app_base_url_is_unsafe_outside_development(self.web_app_base_url):
            raise ValueError(
                "web_app_base_url must be an explicit https URL with a non-loopback host for "
                f"environment={self.environment!r} — refusing to boot with "
                f"{_DEV_WEB_APP_BASE_URL_DEFAULT} or any other localhost, loopback, or "
                "non-https origin, because verification, password-reset, invite, onboarding, "
                "and attendance emails embed this URL. Set WEB_APP_BASE_URL to the public "
                "frontend origin (https:// plus the same host as WEB_DOMAIN)."
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
