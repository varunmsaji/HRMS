"""RELEASE_HARDENING_PHASE_5A (`docs/audits/RELEASE_HARDENING_PHASE_5A_EMAIL.md`) — the
non-AWS SMTP email transport that replaced `SesEmailSender`. Mocks the SMTP transport
(`aiosmtplib.send`) throughout; no real SMTP server is required or contacted by this file."""

from unittest.mock import AsyncMock

import aiosmtplib
import pytest
from pydantic import ValidationError
from structlog.testing import capture_logs

from hrms.core.config.settings import Settings
from hrms.modules.onboarding.email_sender import (
    EmailDeliveryError,
    LoggingEmailSender,
    SmtpEmailSender,
    get_email_sender,
)

_SMTP_SECRET_MARKER = "s3cr3t-smtp-password-marker-zzz"


def _smtp_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "environment": "development",
        "email_provider": "smtp",
        "smtp_host": "smtp.example.com",
        "smtp_port": 587,
        "smtp_username": "hrms-app",
        "smtp_password": _SMTP_SECRET_MARKER,
        "smtp_from_email": "onboarding@hrms.example.com",
        "smtp_from_name": "Staff Spectrum HRMS",
        "smtp_use_tls": True,
        "smtp_use_ssl": False,
    }
    base.update(overrides)
    return Settings(**base)


# --- Provider selection -----------------------------------------------------------------


def test_logging_provider_selected_by_default() -> None:
    settings = Settings(environment="development")
    assert isinstance(get_email_sender(settings), LoggingEmailSender)


def test_smtp_provider_selected_when_configured() -> None:
    settings = _smtp_settings()
    assert isinstance(get_email_sender(settings), SmtpEmailSender)


def test_invalid_provider_rejected_at_settings_construction() -> None:
    with pytest.raises(ValidationError):
        Settings(environment="development", email_provider="ses")  # type: ignore[arg-type]


# --- SMTP configuration validation (Settings._guard_smtp_config) -----------------------------


def test_smtp_missing_host_rejected() -> None:
    with pytest.raises(ValidationError):
        _smtp_settings(smtp_host="")


def test_smtp_missing_from_email_rejected() -> None:
    with pytest.raises(ValidationError):
        _smtp_settings(smtp_from_email="")


def test_smtp_invalid_port_rejected() -> None:
    with pytest.raises(ValidationError):
        _smtp_settings(smtp_port=0)
    with pytest.raises(ValidationError):
        _smtp_settings(smtp_port=70000)


def test_smtp_lone_username_rejected() -> None:
    with pytest.raises(ValidationError):
        _smtp_settings(smtp_username="hrms-app", smtp_password="")


def test_smtp_lone_password_rejected() -> None:
    with pytest.raises(ValidationError):
        _smtp_settings(smtp_username="", smtp_password="only-a-password")


def test_smtp_unauthenticated_relay_is_a_valid_configuration() -> None:
    # Paired absence, not required presence — an internal relay that accepts unauthenticated
    # submission from this host is legitimate; only a lone username/password is a mistake.
    settings = _smtp_settings(smtp_username="", smtp_password="")
    assert settings.smtp_username == ""
    assert settings.smtp_password == ""


def test_smtp_plaintext_transport_rejected() -> None:
    with pytest.raises(ValidationError):
        _smtp_settings(smtp_use_tls=False, smtp_use_ssl=False)


def test_smtp_both_tls_and_ssl_rejected() -> None:
    with pytest.raises(ValidationError):
        _smtp_settings(smtp_use_tls=True, smtp_use_ssl=True)


def test_smtp_valid_configuration_accepted() -> None:
    settings = _smtp_settings()
    assert settings.email_provider == "smtp"
    assert settings.smtp_host == "smtp.example.com"


def test_logging_provider_requires_no_smtp_configuration() -> None:
    # None of the SMTP-shape checks apply when email_provider="logging" — every field stays at
    # its empty default and boot must still succeed.
    settings = Settings(environment="development", email_provider="logging")
    assert settings.smtp_host == ""


def test_production_rejects_logging_provider() -> None:
    with pytest.raises(ValidationError):
        _smtp_settings(environment="production", email_provider="logging")


def test_production_accepts_smtp_provider() -> None:
    settings = _smtp_settings(
        environment="production",
        jwt_access_secret="Zx7!qP9$mK2#vL5^rT8&nB1@wD4%yF6*hJ0",
        jwt_refresh_secret="Qm3&zR8!kX1#pL6^bN9$vT2@yH5%wD0*jF4",
        cors_allowed_origins=("https://app.example.com",),
        pii_master_key="Nb4$hK7!wQ2#xM9^rF3&tY6@pL1%vD8*sG5",
        s3_endpoint_url="http://minio:9000",
        s3_bucket_documents="hrms-test-documents",
        aws_access_key_id="test-access-key",
        aws_secret_access_key="test-secret-key",
    )
    assert settings.email_provider == "smtp"


# --- Email sending (SMTP transport mocked) ----------------------------------------------


async def test_smtp_sender_sends_with_correct_envelope_and_tls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_send = AsyncMock(return_value=({}, "OK"))
    monkeypatch.setattr(aiosmtplib, "send", fake_send)

    settings = _smtp_settings()
    sender = SmtpEmailSender(settings)
    await sender.send(
        to="alice@example.com",
        subject="Verify your email",
        html_body="<p>Click <a href='https://x/y'>here</a></p>",
        text_body="Click https://x/y",
    )

    fake_send.assert_awaited_once()
    message, kwargs = fake_send.await_args.args[0], fake_send.await_args.kwargs
    assert message["To"] == "alice@example.com"
    assert message["From"] == "Staff Spectrum HRMS <onboarding@hrms.example.com>"
    assert message["Subject"] == "Verify your email"
    text_part = message.get_body(preferencelist=("plain",))
    assert text_part is not None
    assert "https://x/y" in text_part.get_content()
    assert kwargs["hostname"] == "smtp.example.com"
    assert kwargs["port"] == 587
    assert kwargs["username"] == "hrms-app"
    assert kwargs["password"] == _SMTP_SECRET_MARKER
    assert kwargs["start_tls"] is True
    assert kwargs["use_tls"] is False


async def test_smtp_sender_implicit_tls_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_send = AsyncMock(return_value=({}, "OK"))
    monkeypatch.setattr(aiosmtplib, "send", fake_send)

    settings = _smtp_settings(smtp_port=465, smtp_use_tls=False, smtp_use_ssl=True)
    sender = SmtpEmailSender(settings)
    await sender.send(to="alice@example.com", subject="s", html_body="<p>h</p>", text_body="t")

    kwargs = fake_send.await_args.kwargs
    assert kwargs["start_tls"] is False
    assert kwargs["use_tls"] is True


async def test_smtp_sender_unauthenticated_relay_passes_none_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_send = AsyncMock(return_value=({}, "OK"))
    monkeypatch.setattr(aiosmtplib, "send", fake_send)

    settings = _smtp_settings(smtp_username="", smtp_password="")
    sender = SmtpEmailSender(settings)
    await sender.send(to="alice@example.com", subject="s", html_body="<p>h</p>", text_body="t")

    kwargs = fake_send.await_args.kwargs
    assert kwargs["username"] is None
    assert kwargs["password"] is None


async def test_logging_sender_does_not_raise_and_never_contacts_smtp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_send = AsyncMock()
    monkeypatch.setattr(aiosmtplib, "send", fake_send)

    await LoggingEmailSender().send(
        to="alice@example.com", subject="s", html_body="<p>h</p>", text_body="t"
    )
    fake_send.assert_not_awaited()


# --- Security: credentials and tokens must never reach a log line or an exception message ----


async def test_smtp_password_never_appears_in_the_failure_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _raise(*args: object, **kwargs: object) -> None:
        raise aiosmtplib.SMTPConnectError("connection refused")

    monkeypatch.setattr(aiosmtplib, "send", _raise)

    settings = _smtp_settings()
    sender = SmtpEmailSender(settings)

    with capture_logs() as logs:
        with pytest.raises(EmailDeliveryError) as exc_info:
            await sender.send(
                to="alice@example.com",
                subject="Reset your password",
                html_body="<p>token</p>",
                text_body="token",
            )

    # The password must not appear anywhere: not in the raised exception's own message, and not
    # in any structured log line emitted while handling the failure.
    assert _SMTP_SECRET_MARKER not in str(exc_info.value)
    for log in logs:
        assert _SMTP_SECRET_MARKER not in repr(log)


async def test_smtp_send_failure_does_not_log_the_email_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The body (which, for a real verification/reset/invite email, contains the token URL) must
    # not be echoed into the failure log line — only non-sensitive metadata (to/subject/error type).
    token_marker = "https://app.example.com/verify-email/super-secret-token-abc123"

    async def _raise(*args: object, **kwargs: object) -> None:
        raise aiosmtplib.SMTPRecipientsRefused({"alice@example.com": (550, b"no such user")})

    monkeypatch.setattr(aiosmtplib, "send", _raise)

    settings = _smtp_settings()
    sender = SmtpEmailSender(settings)

    with capture_logs() as logs:
        with pytest.raises(EmailDeliveryError):
            await sender.send(
                to="alice@example.com",
                subject="Verify your email",
                html_body=f"<p><a href='{token_marker}'>Verify</a></p>",
                text_body=token_marker,
            )

    for log in logs:
        assert token_marker not in repr(log)

    failure_logs = [log for log in logs if log.get("event") == "onboarding_email_smtp_send_failed"]
    assert len(failure_logs) == 1
    assert failure_logs[0]["to"] == "alice@example.com"
    assert failure_logs[0]["subject"] == "Verify your email"
    assert "error_type" in failure_logs[0]
