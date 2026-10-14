"""Minimal onboarding-scoped email sender (O3) — plan §8.4 option (a): a small port plus one
real implementation, not a prerequisite on the full Notifications engine
(`docs/product/VERSION_1_ROADMAP.md` row 6, "Not started"). Designed to be swapped for that
engine later without touching onboarding's business logic — every caller depends only on the
`EmailSender` protocol, never on which implementation `get_email_sender` selected.

The plan named three templates (invite, changes-requested, activated); only the invite one
exists yet (`email_templates.py`) — the other two have no caller until O6/O7 land, and adding
them now would be code nothing exercises.

RELEASE_HARDENING_PHASE_5A (`docs/audits/RELEASE_HARDENING_PHASE_5A_EMAIL.md`) replaced the
original `SesEmailSender` (a hard AWS SES/`aioboto3` dependency — the only real delivery path
this module ever had, directly contradicting this deployment's no-AWS-managed-services
architecture) with `SmtpEmailSender`, a provider-agnostic authenticated-SMTP transport. Nothing
about the `EmailSender` protocol, the caller sites, or the message content this module receives
changed — only the transport.

`MailtrapEmailSender` (added after Phase 5A) is a second real transport, selected via
`Settings.email_provider="mailtrap"` — same `EmailSender` protocol, same caller sites, only the
transport differs again. It calls Mailtrap's HTTP Send API directly over `httpx` (already a
dependency) rather than via Mailtrap's own synchronous Python SDK, so sending stays fully async
like `SmtpEmailSender` instead of blocking the event loop on a sync HTTP call."""

from email.message import EmailMessage
from typing import Protocol

import aiosmtplib
import httpx

from hrms.core.config.settings import Settings
from hrms.core.observability.logging import get_logger

logger = get_logger(__name__)


class EmailSender(Protocol):
    async def send(self, *, to: str, subject: str, html_body: str, text_body: str) -> None: ...


class LoggingEmailSender:
    """Selected whenever `Settings.email_provider == "logging"` (the default) — every local dev
    environment and this module's own test suite today. Logs the email instead of sending
    it, so onboarding is fully exercisable end-to-end (including reading the invite URL back out
    of the admin API response) without a real mailbox or SMTP credentials.

    Deliberately development/test-only: `Settings._guard_non_development_config` refuses to boot
    any staging/production process with `email_provider="logging"` still selected — a pilot
    deployment can never silently believe real email is being delivered when it is only being
    logged here."""

    async def send(self, *, to: str, subject: str, html_body: str, text_body: str) -> None:
        del html_body  # not useful in a log line; the text body is
        get_logger(__name__).info(
            "onboarding_email_not_sent_smtp_not_configured",
            to=to,
            subject=subject,
            text_body=text_body,
        )


class SmtpEmailSender:
    """Real delivery via a standard authenticated SMTP transport (RELEASE_HARDENING_PHASE_5A).
    Provider-agnostic by design — any SMTP-compatible relay works (a transactional-email vendor's
    SMTP endpoint, a self-hosted MTA, etc.); nothing here names a specific commercial vendor.
    `Settings._guard_smtp_config` has already validated host/port/from-address/TLS-mode/credential
    pairing before this class is ever constructed, so `send` itself does no config validation."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def send(self, *, to: str, subject: str, html_body: str, text_body: str) -> None:
        settings = self._settings
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
        message["To"] = to
        message.set_content(text_body)
        message.add_alternative(html_body, subtype="html")

        try:
            await aiosmtplib.send(
                message,
                hostname=settings.smtp_host,
                port=settings.smtp_port,
                username=settings.smtp_username or None,
                password=settings.smtp_password or None,
                start_tls=settings.smtp_use_tls,
                use_tls=settings.smtp_use_ssl,
            )
        except aiosmtplib.SMTPException as exc:
            # Deliberately `logger.error`, not `logger.exception`: the latter attaches the full
            # traceback/`str(exc)` to the log record, and `aiosmtplib`'s own exception messages
            # are not a security-reviewed contract — logging only the exception's type name here
            # keeps the "never log credentials" guarantee independent of any future change to
            # `aiosmtplib`'s own error formatting. The original exception is still preserved on
            # the Python exception chain (`from exc`) for local debugging/`repr()` in a traceback.
            get_logger(__name__).error(  # noqa: TRY400 — see comment above; exception() is deliberately avoided
                "onboarding_email_smtp_send_failed",
                to=to,
                subject=subject,
                error_type=type(exc).__name__,
            )
            raise EmailDeliveryError("Failed to send email via SMTP.") from exc


class MailtrapEmailSender:
    """Real delivery via the Mailtrap Send API (https://send.api.mailtrap.io/api/send). Called
    directly over `httpx.AsyncClient` rather than Mailtrap's own (synchronous) Python SDK — same
    reasoning as `SmtpEmailSender` using `aiosmtplib` instead of a blocking SMTP client.
    `Settings._guard_mailtrap_config` has already validated the API token and sender address
    before this class is ever constructed, so `send` itself does no config validation."""

    _API_URL = "https://send.api.mailtrap.io/api/send"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def send(self, *, to: str, subject: str, html_body: str, text_body: str) -> None:
        settings = self._settings
        payload = {
            "from": {"email": settings.smtp_from_email, "name": settings.smtp_from_name},
            "to": [{"email": to}],
            "subject": subject,
            "text": text_body,
            "html": html_body,
            "category": "Onboarding",
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    self._API_URL,
                    json=payload,
                    headers={"Authorization": f"Bearer {settings.mailtrap_api_token}"},
                )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            # Same log-hygiene rule as `SmtpEmailSender` above: never the API token, never the
            # response body (which Mailtrap may echo request content into on a validation error).
            status_code = (
                exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            )
            get_logger(__name__).error(
                "onboarding_email_mailtrap_send_failed",
                to=to,
                subject=subject,
                error_type=type(exc).__name__,
                status_code=status_code,
            )
            raise EmailDeliveryError("Failed to send email via Mailtrap.") from exc


class HostingerEmailSender:
    """Real delivery via the Hostinger Mail API
    (`POST /api/v1/mailboxes/{mailboxResourceId}/send`). The sender is the mailbox named by
    `Settings.hostinger_mail_mailbox_id`; only the display name is settable per message.
    `Settings._guard_hostinger_config` has already validated the token and mailbox id."""

    _API_BASE_URL = "https://api.mail.hostinger.com"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def send(self, *, to: str, subject: str, html_body: str, text_body: str) -> None:
        settings = self._settings
        url = f"{self._API_BASE_URL}/api/v1/mailboxes/{settings.hostinger_mail_mailbox_id}/send"
        payload = {
            "to": [to],
            "display_name": settings.smtp_from_name,
            "subject": subject,
            "text": text_body,
            "html": html_body,
        }

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    url,
                    json=payload,
                    headers={"Authorization": f"Bearer {settings.hostinger_mail_api_token}"},
                )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            # Same log-hygiene rule as the other senders: never the token or response body.
            status_code = (
                exc.response.status_code if isinstance(exc, httpx.HTTPStatusError) else None
            )
            get_logger(__name__).error(
                "onboarding_email_hostinger_send_failed",
                to=to,
                subject=subject,
                error_type=type(exc).__name__,
                status_code=status_code,
            )
            raise EmailDeliveryError("Failed to send email via Hostinger.") from exc


class EmailDeliveryError(Exception):
    """Raised by `SmtpEmailSender.send`/`MailtrapEmailSender.send` on any transport-layer
    failure. Deliberately carries no exception chain data in its own message (`from exc`
    preserves the original for local debugging/`repr()` in a traceback, never for anything
    serialized into a log line or an API response) — callers must not surface `str(exc)` to an
    HTTP response or a structured log."""


def get_email_sender(settings: Settings) -> EmailSender:
    if settings.email_provider == "smtp":
        return SmtpEmailSender(settings)
    if settings.email_provider == "mailtrap":
        return MailtrapEmailSender(settings)
    if settings.email_provider == "hostinger":
        return HostingerEmailSender(settings)
    return LoggingEmailSender()
