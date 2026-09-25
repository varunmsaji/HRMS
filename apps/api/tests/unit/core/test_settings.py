"""SEC-01/OPS-01 (PLATFORM_READINESS_SECURITY_AUDIT_2026-09-17, Production Hardening Batch 1).

`Settings(...)` constructor kwargs take precedence over environment variables and any local
`.env` file (pydantic-settings precedence), so every test here constructs `Settings` directly
rather than mutating `os.environ` — isolated, and no real secret ever needs to touch the
environment or a log line.
"""

from pydantic import ValidationError

from hrms.core.config.settings import Settings

#: 40 chars, high character variety — comfortably clears the non-development floor
#: (32+ chars, 8+ distinct characters) without resembling either repository default.
_STRONG_ACCESS_SECRET = "Zx7!qP9$mK2#vL5^rT8&nB1@wD4%yF6*hJ0"
_STRONG_REFRESH_SECRET = "Qm3&zR8!kX1#pL6^bN9$vT2@yH5%wD0*jF4"


#: RELEASE_HARDENING_PHASE_3A — a strong (test-only) application master key, so every
#: pre-existing CORS/JWT test below (which does not care about the PII-encryption guard at all)
#: keeps passing once `pii_master_key` is validated with the same entropy floor as the JWT
#: secrets. Replaces this file's previous KMS-ARN fixture (`kms_cmk_arn` was removed —
#: docs/audits/RELEASE_HARDENING_PHASE_3A_SECURITY_REMEDIATION.md §9).
_TEST_PII_MASTER_KEY = "Nb4$hK7!wQ2#xM9^rF3&tY6@pL1%vD8*sG5"


def _non_dev_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "environment": "production",
        "jwt_access_secret": _STRONG_ACCESS_SECRET,
        "jwt_refresh_secret": _STRONG_REFRESH_SECRET,
        "cors_allowed_origins": ("https://app.example.com",),
        "pii_master_key": _TEST_PII_MASTER_KEY,
        "s3_endpoint_url": "http://minio:9000",
        "s3_bucket_documents": "hrms-test-documents",
        "aws_access_key_id": "test-access-key",
        "aws_secret_access_key": "test-secret-key",
        # RELEASE_HARDENING_PHASE_5A — a valid SMTP shape so every pre-existing test below (none
        # of which cares about email config) keeps passing once email_provider="smtp" is required
        # outside development. See test_email_settings.py for the email-config-specific tests.
        "email_provider": "smtp",
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_username": "hrms-app",
        "smtp_password": "test-smtp-password",
        "smtp_from_email": "onboarding@hrms.example.com",
        "smtp_use_tls": True,
        "smtp_use_ssl": False,
    }
    base.update(overrides)
    return Settings(**base)


# --- SEC-01: JWT secret guard --------------------------------------------------------------


def test_development_allows_the_repository_default_secrets() -> None:
    # Explicit kwargs override the test session's own `JWT_ACCESS_SECRET`/`JWT_REFRESH_SECRET`
    # env vars (set in `tests/conftest.py`) — this asserts development tolerates the *known
    # repository defaults* specifically, not just "whatever is already in the environment".
    settings = Settings(
        environment="development",
        jwt_access_secret="change-me-local-dev-only-min-16",
        jwt_refresh_secret="change-me-local-dev-too-min-16",
    )
    assert settings.jwt_access_secret == "change-me-local-dev-only-min-16"
    assert settings.jwt_refresh_secret == "change-me-local-dev-too-min-16"


def test_staging_rejects_the_default_access_secret() -> None:
    try:
        _non_dev_settings(
            environment="staging", jwt_access_secret="change-me-local-dev-only-min-16"
        )
        raised = False
    except ValidationError:
        raised = True
    assert raised


def test_production_rejects_the_default_access_secret() -> None:
    try:
        _non_dev_settings(jwt_access_secret="change-me-local-dev-only-min-16")
        raised = False
    except ValidationError:
        raised = True
    assert raised


def test_production_rejects_the_default_refresh_secret() -> None:
    try:
        _non_dev_settings(jwt_refresh_secret="change-me-local-dev-too-min-16")
        raised = False
    except ValidationError:
        raised = True
    assert raised


def test_staging_rejects_a_missing_secret() -> None:
    try:
        _non_dev_settings(environment="staging", jwt_access_secret="")
        raised = False
    except ValidationError:
        raised = True
    assert raised


def test_production_rejects_a_missing_secret() -> None:
    try:
        _non_dev_settings(jwt_refresh_secret="")
        raised = False
    except ValidationError:
        raised = True
    assert raised


def test_production_rejects_a_weak_but_novel_secret() -> None:
    """Not the repository default, still 32+ chars — but low character variety. Guards
    against a "len(secret) >= 16 => accept" style check that the known default would pass."""
    try:
        _non_dev_settings(jwt_access_secret="a" * 40)
        raised = False
    except ValidationError:
        raised = True
    assert raised


def test_staging_accepts_a_strong_secret() -> None:
    settings = _non_dev_settings(environment="staging")
    assert settings.jwt_access_secret == _STRONG_ACCESS_SECRET


def test_production_accepts_a_strong_secret() -> None:
    settings = _non_dev_settings()
    assert settings.jwt_refresh_secret == _STRONG_REFRESH_SECRET


def test_rejection_error_never_echoes_the_rejected_secret_value() -> None:
    marker_secret = "leaked-marker-value"  # short => weak => rejected, but distinctive
    try:
        _non_dev_settings(jwt_access_secret=marker_secret)
        raised_message = ""
    except ValidationError as exc:
        raised_message = str(exc)
    assert raised_message
    assert marker_secret not in raised_message


# --- OPS-01: CORS origin guard --------------------------------------------------------------


def test_development_has_no_explicit_origins_but_a_valid_fallback() -> None:
    settings = Settings(environment="development")
    assert settings.cors_allowed_origins == ()
    origins = settings.effective_cors_origins
    assert origins
    assert "*" not in origins


def test_staging_requires_explicit_origins() -> None:
    try:
        _non_dev_settings(environment="staging", cors_allowed_origins=())
        raised = False
    except ValidationError:
        raised = True
    assert raised


def test_production_requires_explicit_origins() -> None:
    try:
        _non_dev_settings(cors_allowed_origins=())
        raised = False
        error_text = ""
    except ValidationError as exc:
        raised = True
        error_text = str(exc)
    assert raised
    assert "cors_allowed_origins" in error_text


def test_production_accepts_an_explicit_origin() -> None:
    settings = _non_dev_settings(cors_allowed_origins=("https://app.example.com",))
    assert settings.effective_cors_origins == ["https://app.example.com"]


def test_cors_allowed_origins_env_string_splits_on_commas() -> None:
    settings = _non_dev_settings(
        cors_allowed_origins="https://a.example.com, https://b.example.com"
    )
    assert settings.cors_allowed_origins == ("https://a.example.com", "https://b.example.com")


def test_wildcard_origin_never_appears_alongside_credentials_in_any_environment() -> None:
    dev = Settings(environment="development")
    prod = _non_dev_settings()
    assert "*" not in dev.effective_cors_origins
    assert "*" not in prod.effective_cors_origins


# --- OPS-02: trusted proxy hosts parsing -----------------------------------------------------


def test_trusted_proxy_hosts_defaults_to_empty() -> None:
    settings = Settings(environment="development")
    assert settings.trusted_proxy_hosts == ()


def test_trusted_proxy_hosts_env_string_splits_on_commas() -> None:
    settings = Settings(environment="development", trusted_proxy_hosts="10.0.0.5, 10.0.0.6")
    assert settings.trusted_proxy_hosts == ("10.0.0.5", "10.0.0.6")


# --- INFRA-01: self-hosted MinIO storage guard (Upload Security Batch A) --------------------


def test_development_allows_no_s3_endpoint() -> None:
    settings = Settings(environment="development", s3_endpoint_url=None)
    assert settings.s3_endpoint_url is None


def test_staging_rejects_a_missing_s3_endpoint() -> None:
    try:
        _non_dev_settings(environment="staging", s3_endpoint_url=None)
        raised = False
    except ValidationError:
        raised = True
    assert raised


def test_production_rejects_a_missing_s3_endpoint() -> None:
    """The core INFRA-01 guard: an unset endpoint would otherwise let aioboto3/boto3 resolve
    against real AWS S3 rather than this deployment's self-hosted MinIO."""
    try:
        _non_dev_settings(s3_endpoint_url=None)
        raised = False
        error_text = ""
    except ValidationError as exc:
        raised = True
        error_text = str(exc)
    assert raised
    assert "s3_endpoint_url" in error_text


def test_production_rejects_an_empty_s3_endpoint() -> None:
    try:
        _non_dev_settings(s3_endpoint_url="")
        raised = False
    except ValidationError:
        raised = True
    assert raised


def test_production_rejects_a_missing_bucket() -> None:
    try:
        _non_dev_settings(s3_bucket_documents="")
        raised = False
        error_text = ""
    except ValidationError as exc:
        raised = True
        error_text = str(exc)
    assert raised
    assert "s3_bucket_documents" in error_text


def test_production_rejects_missing_access_key() -> None:
    try:
        _non_dev_settings(aws_access_key_id="")
        raised = False
    except ValidationError:
        raised = True
    assert raised


def test_production_rejects_missing_secret_key() -> None:
    try:
        _non_dev_settings(aws_secret_access_key="")
        raised = False
    except ValidationError:
        raised = True
    assert raised


def test_production_accepts_a_valid_minio_configuration() -> None:
    settings = _non_dev_settings(
        s3_endpoint_url="http://minio:9000",
        s3_bucket_documents="hrms-prod-documents",
        aws_access_key_id="prod-access-key",
        aws_secret_access_key="prod-secret-key",
    )
    assert settings.s3_endpoint_url == "http://minio:9000"
    assert settings.s3_bucket_documents == "hrms-prod-documents"


def test_s3_public_endpoint_url_defaults_to_none_and_is_independent_of_the_guard() -> None:
    """Optional in every environment — `DocumentStorageService.presigned_get_url` falls back to
    `s3_endpoint_url` when it is unset, so the boot guard must not require it separately."""
    settings = _non_dev_settings()
    assert settings.s3_public_endpoint_url is None
