"""RELEASE_HARDENING_PHASE_5A (`docs/audits/RELEASE_HARDENING_PHASE_5A_EMAIL.md`) — the
non-AWS SMTP email transport that replaced `SesEmailSender`, plus the later Mailtrap HTTP-API
transport added alongside it. Mocks the SMTP transport (`aiosmtplib.send`) and the Mailtrap
transport (`httpx.AsyncClient.post`) throughout; no real SMTP server or Mailtrap API is required
or contacted by this file."""

from unittest.mock import AsyncMock

import aiosmtplib
import httpx
import pytest
import structlog
from pydantic import ValidationError
from structlog.testing import capture_logs

from hrms.core.config.settings import Settings
from hrms.modules.onboarding.email_sender import (
    EmailDeliveryError,
    HostingerEmailSender,
    LoggingEmailSender,
    MailtrapEmailSender,
    SmtpEmailSender,
    get_email_sender,
    log_email_failure,
)

_SMTP_SECRET_MARKER = "s3cr3t-smtp-password-marker-zzz"
_MAILTRAP_TOKEN_MARKER = "s3cr3t-mailtrap-token-marker-zzz"


@pytest.fixture(autouse=True)
def _uncached_logger(monkeypatch: pytest.MonkeyPatch) -> None:
    """`cache_logger_on_first_use` lets a module-level logger keep whatever pipeline was active
    when an earlier test first used it, which `capture_logs()` cannot intercept."""
    monkeypatch.setattr(
        "hrms.modules.onboarding.email_sender.logger",
        structlog.get_logger("hrms.modules.onboarding.email_sender"),
    )


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


def _mailtrap_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "environment": "development",
        "email_provider": "mailtrap",
        "mailtrap_api_token": _MAILTRAP_TOKEN_MARKER,
        "smtp_from_email": "onboarding@hrms.example.com",
        "smtp_from_name": "Staff Spectrum HRMS",
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


def test_mailtrap_provider_selected_when_configured() -> None:
    settings = _mailtrap_settings()
    assert isinstance(get_email_sender(settings), MailtrapEmailSender)


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
        web_app_base_url="https://app.example.com",
    )
    assert settings.email_provider == "smtp"


# --- Mailtrap configuration validation (Settings._guard_mailtrap_config) ---------------------


def test_mailtrap_missing_token_rejected() -> None:
    with pytest.raises(ValidationError):
        _mailtrap_settings(mailtrap_api_token="")


def test_mailtrap_missing_from_email_rejected() -> None:
    with pytest.raises(ValidationError):
        _mailtrap_settings(smtp_from_email="")


def test_mailtrap_valid_configuration_accepted() -> None:
    settings = _mailtrap_settings()
    assert settings.email_provider == "mailtrap"
    assert settings.mailtrap_api_token == _MAILTRAP_TOKEN_MARKER


def test_production_rejects_logging_provider_for_mailtrap_style_config() -> None:
    with pytest.raises(ValidationError):
        _mailtrap_settings(environment="production", email_provider="logging")


def test_production_accepts_mailtrap_provider() -> None:
    settings = _mailtrap_settings(
        environment="production",
        jwt_access_secret="Zx7!qP9$mK2#vL5^rT8&nB1@wD4%yF6*hJ0",
        jwt_refresh_secret="Qm3&zR8!kX1#pL6^bN9$vT2@yH5%wD0*jF4",
        cors_allowed_origins=("https://app.example.com",),
        pii_master_key="Nb4$hK7!wQ2#xM9^rF3&tY6@pL1%vD8*sG5",
        s3_endpoint_url="http://minio:9000",
        s3_bucket_documents="hrms-test-documents",
        aws_access_key_id="test-access-key",
        aws_secret_access_key="test-secret-key",
        web_app_base_url="https://app.example.com",
    )
    assert settings.email_provider == "mailtrap"


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
        with pytest.raises(EmailDeliveryError) as exc_info:
            await sender.send(
                to="alice@example.com",
                subject="Verify your email",
                html_body=f"<p><a href='{token_marker}'>Verify</a></p>",
                text_body=token_marker,
            )
        # Mission Phase 6 — the sender classifies; the caller logs once with the email's kind.
        log_email_failure("email_verification", exc_info.value, user_id="u-1")

    for log in logs:
        assert token_marker not in repr(log)
        assert "alice@example.com" not in repr(log)

    (failure,) = [log for log in logs if log.get("event") == "email.delivery.failed"]
    assert failure["log_level"] == "warning"
    assert failure["email_kind"] == "email_verification"
    assert failure["provider"] == "smtp"
    assert failure["failure_class"] == "rejected"
    assert failure["retryable"] is False
    assert failure["outcome"] == "not_sent"
    assert failure["error_type"] == "SMTPRecipientsRefused"
    assert "to" not in failure and "subject" not in failure


# --- Email sending (Mailtrap transport mocked) -------------------------------------------


def _mailtrap_response(status_code: int = 200) -> httpx.Response:
    request = httpx.Request("POST", MailtrapEmailSender._API_URL)
    return httpx.Response(status_code, request=request, json={"success": status_code < 400})


async def test_mailtrap_sender_posts_correct_payload_and_auth_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_post = AsyncMock(return_value=_mailtrap_response(200))
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    settings = _mailtrap_settings()
    sender = MailtrapEmailSender(settings)
    await sender.send(
        to="alice@example.com",
        subject="Verify your email",
        html_body="<p>Click <a href='https://x/y'>here</a></p>",
        text_body="Click https://x/y",
    )

    fake_post.assert_awaited_once()
    args, kwargs = fake_post.await_args.args, fake_post.await_args.kwargs
    assert args[0] == MailtrapEmailSender._API_URL
    assert kwargs["headers"]["Authorization"] == f"Bearer {_MAILTRAP_TOKEN_MARKER}"
    payload = kwargs["json"]
    assert payload["from"] == {
        "email": "onboarding@hrms.example.com",
        "name": "Staff Spectrum HRMS",
    }
    assert payload["to"] == [{"email": "alice@example.com"}]
    assert payload["subject"] == "Verify your email"
    assert payload["text"] == "Click https://x/y"
    assert payload["html"] == "<p>Click <a href='https://x/y'>here</a></p>"


async def test_mailtrap_sender_raises_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_post = AsyncMock(return_value=_mailtrap_response(422))
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    settings = _mailtrap_settings()
    sender = MailtrapEmailSender(settings)

    with pytest.raises(EmailDeliveryError):
        await sender.send(to="alice@example.com", subject="s", html_body="<p>h</p>", text_body="t")


async def test_mailtrap_sender_raises_on_connection_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _raise(*args: object, **kwargs: object) -> httpx.Response:
        raise httpx.ConnectError("connection refused")

    monkeypatch.setattr(httpx.AsyncClient, "post", _raise)

    settings = _mailtrap_settings()
    sender = MailtrapEmailSender(settings)

    with pytest.raises(EmailDeliveryError):
        await sender.send(to="alice@example.com", subject="s", html_body="<p>h</p>", text_body="t")


# --- Security: Mailtrap token and body must never reach a log line or an exception message ----


async def test_mailtrap_token_never_appears_in_the_failure_log(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_post = AsyncMock(return_value=_mailtrap_response(401))
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    settings = _mailtrap_settings()
    sender = MailtrapEmailSender(settings)

    with capture_logs() as logs:
        with pytest.raises(EmailDeliveryError) as exc_info:
            await sender.send(
                to="alice@example.com",
                subject="Reset your password",
                html_body="<p>token</p>",
                text_body="token",
            )

    assert _MAILTRAP_TOKEN_MARKER not in str(exc_info.value)
    for log in logs:
        assert _MAILTRAP_TOKEN_MARKER not in repr(log)


async def test_mailtrap_send_failure_does_not_log_the_email_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token_marker = "https://app.example.com/verify-email/super-secret-token-abc123"

    fake_post = AsyncMock(return_value=_mailtrap_response(422))
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    settings = _mailtrap_settings()
    sender = MailtrapEmailSender(settings)

    with capture_logs() as logs:
        with pytest.raises(EmailDeliveryError) as exc_info:
            await sender.send(
                to="alice@example.com",
                subject="Verify your email",
                html_body=f"<p><a href='{token_marker}'>Verify</a></p>",
                text_body=token_marker,
            )
        log_email_failure("email_verification", exc_info.value, user_id="u-1")

    for log in logs:
        assert token_marker not in repr(log)
        assert "alice@example.com" not in repr(log)

    (failure,) = [log for log in logs if log.get("event") == "email.delivery.failed"]
    assert failure["provider"] == "mailtrap"
    assert failure["status_code"] == 422
    assert failure["failure_class"] == "rejected"
    assert failure["error_type"] == "HTTPStatusError"


# --- Hostinger Mail API ------------------------------------------------------------------

_HOSTINGER_TOKEN_MARKER = "s3cr3t-hostinger-token-marker-zzz"
_HOSTINGER_MAILBOX_ID = "AC0000000000000000000000000000"


def _hostinger_settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "environment": "development",
        "email_provider": "hostinger",
        "hostinger_mail_api_token": _HOSTINGER_TOKEN_MARKER,
        "hostinger_mail_mailbox_id": _HOSTINGER_MAILBOX_ID,
        "smtp_from_name": "Staff Spectrum HRMS",
    }
    base.update(overrides)
    return Settings(**base)


def test_hostinger_provider_selected_when_configured() -> None:
    assert isinstance(get_email_sender(_hostinger_settings()), HostingerEmailSender)


def test_hostinger_missing_token_rejected() -> None:
    with pytest.raises(ValueError, match="hostinger_mail_api_token"):
        _hostinger_settings(hostinger_mail_api_token="")


def test_hostinger_missing_mailbox_id_rejected() -> None:
    with pytest.raises(ValueError, match="hostinger_mail_mailbox_id"):
        _hostinger_settings(hostinger_mail_mailbox_id="")


async def test_hostinger_sender_posts_correct_payload_and_auth_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = httpx.Request("POST", "https://api.mail.hostinger.com")
    fake_post = AsyncMock(return_value=httpx.Response(200, request=request, json={"data": {}}))
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    sender = HostingerEmailSender(_hostinger_settings())
    await sender.send(to="alice@example.com", subject="Hi", html_body="<p>h</p>", text_body="t")

    args, kwargs = fake_post.await_args.args, fake_post.await_args.kwargs
    assert args[0] == (
        f"https://api.mail.hostinger.com/api/v1/mailboxes/{_HOSTINGER_MAILBOX_ID}/send"
    )
    assert kwargs["headers"]["Authorization"] == f"Bearer {_HOSTINGER_TOKEN_MARKER}"
    assert kwargs["json"] == {
        "to": ["alice@example.com"],
        "display_name": "Staff Spectrum HRMS",
        "subject": "Hi",
        "text": "t",
        "html": "<p>h</p>",
    }


async def test_hostinger_sender_raises_on_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    request = httpx.Request("POST", "https://api.mail.hostinger.com")
    fake_post = AsyncMock(return_value=httpx.Response(401, request=request, json={}))
    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)

    with pytest.raises(EmailDeliveryError):
        await HostingerEmailSender(_hostinger_settings()).send(
            to="alice@example.com", subject="s", html_body="<p>h</p>", text_body="t"
        )
