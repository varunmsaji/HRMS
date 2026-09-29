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
changed — only the transport."""

from email.message import EmailMessage
from typing import Protocol

import aiosmtplib

from hrms.core.config.settings import Settings
from hrms.core.observability.logging import get_logger

logger = get_logger(__name__)


class EmailSender(Protocol):
    async def send(self, *, to: str, subject: str, html_body: str, text_body: str) -> None: ...


class LoggingEmailSender:
    """Selected whenever `Settings.email_provider != "smtp"` — every local dev environment and
    this module's own test suite today (default `"logging"`). Logs the email instead of sending
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


class EmailDeliveryError(Exception):
    """Raised by `SmtpEmailSender.send` on any SMTP-layer failure. Deliberately carries no
    exception chain data in its own message (`from exc` preserves the original for local
    debugging/`repr()` in a traceback, never for anything serialized into a log line or an API
    response) — callers must not surface `str(exc)` to an HTTP response or a structured log."""


def get_email_sender(settings: Settings) -> EmailSender:
    if settings.email_provider == "smtp":
        return SmtpEmailSender(settings)
    return LoggingEmailSender()
