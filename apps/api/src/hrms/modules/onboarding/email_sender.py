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

import sys
from email.message import EmailMessage
from typing import Any, Literal, Protocol

import aiosmtplib
import httpx

from hrms.core.config.settings import Settings
from hrms.core.observability.logging import get_logger, safe_error, safe_log

logger = get_logger(__name__)

#: Mission Phase 6 — what is known about a failed send. `not_sent`: the provider certainly did not
#: take the message (connection refused, rejected, auth failure). `unknown`: the request may have
#: reached the provider before the failure (a read timeout, a dropped connection after sending, a
#: 5xx) — retrying could send it twice, so it is never retried blindly.
Outcome = Literal["not_sent", "unknown"]


def _classify_http(exc: httpx.HTTPError) -> tuple[str, bool, Outcome, int | None]:
    """(failure_class, retryable, outcome, status_code) for an HTTP API provider failure."""
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status in (401, 403):
            return "auth", False, "not_sent", status
        if status == 429:
            return "rate_limited", True, "not_sent", status
        if status >= 500:
            return "provider_error", True, "unknown", status
        return "rejected", False, "not_sent", status
    if isinstance(exc, httpx.ConnectTimeout):
        return "timeout", True, "not_sent", None
    if isinstance(exc, httpx.TimeoutException):
        return "timeout", True, "unknown", None
    if isinstance(exc, httpx.ConnectError):
        return "network", True, "not_sent", None
    return "network", True, "unknown", None


def _classify_smtp(exc: aiosmtplib.SMTPException) -> tuple[str, bool, Outcome, int | None]:
    code = getattr(exc, "code", None)
    if isinstance(exc, aiosmtplib.SMTPAuthenticationError):
        return "auth", False, "not_sent", code
    if isinstance(exc, aiosmtplib.SMTPRecipientsRefused | aiosmtplib.SMTPSenderRefused):
        return "rejected", False, "not_sent", code
    if isinstance(exc, aiosmtplib.SMTPConnectError | aiosmtplib.SMTPConnectTimeoutError):
        return "network", True, "not_sent", code
    if isinstance(exc, aiosmtplib.SMTPTimeoutError | aiosmtplib.SMTPServerDisconnected):
        return "timeout", True, "unknown", code
    if isinstance(code, int):
        transient = 400 <= code < 500
        return ("provider_error" if transient else "rejected"), transient, "not_sent", code
    return "provider_error", True, "unknown", code


def _accepted(provider: str) -> None:
    """The provider *accepted* the request. That is not delivery: bounces and spam filtering
    happen later and are invisible to this application."""
    safe_log(logger.info, "email.provider.accepted", provider=provider)


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
        del html_body  # not useful to a developer; the text body is
        # The structured log pipeline now redacts addresses and token links (LOG-08), which is
        # exactly what this dev-only sender exists to show. So the readable copy goes to stderr,
        # outside the JSON log stream, and the structured event carries no content.
        # `Settings._guard_non_development_config` keeps this sender out of staging/production.
        safe_log(logger.info, "email.logged_not_sent", provider="logging")
        try:
            sys.stderr.write(
                f"--- [dev email, not sent] to={to} subject={subject}\n{text_body}\n---\n"
            )
        except (OSError, ValueError):
            pass


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
            # Never the exception text: `aiosmtplib`'s messages are not a security-reviewed
            # contract. Classified here, logged once by the caller (`log_email_failure`), which
            # knows which email this was. The original stays on the chain (`from exc`).
            raise EmailDeliveryError("smtp", *_classify_smtp(exc), error_type=exc) from exc
        _accepted("smtp")


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
            # Never the API token or the response body (Mailtrap may echo request content).
            raise EmailDeliveryError("mailtrap", *_classify_http(exc), error_type=exc) from exc
        _accepted("mailtrap")


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
            # Never the token or the response body.
            raise EmailDeliveryError("hostinger", *_classify_http(exc), error_type=exc) from exc
        _accepted("hostinger")


class EmailDeliveryError(Exception):
    """Raised by every real sender on a transport-layer failure, carrying a safe classification
    (provider, failure class, whether a retry is reasonable, and whether the provider may have
    accepted the message anyway). Its own message is a fixed string — `from exc` preserves the
    original for local debugging only; callers must never surface `str(exc)`."""

    def __init__(
        self,
        provider: str,
        failure_class: str,
        retryable: bool,
        outcome: Outcome,
        status_code: int | None,
        *,
        error_type: BaseException,
    ) -> None:
        super().__init__(f"Failed to send email via {provider}.")
        self.provider = provider
        self.failure_class = failure_class
        self.retryable = retryable
        self.outcome = outcome
        self.status_code = status_code
        self.error_type = type(error_type).__name__

    def log_fields(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "failure_class": self.failure_class,
            "retryable": self.retryable,
            "outcome": self.outcome,
            "status_code": self.status_code,
            "error_type": self.error_type,
        }


def log_email_failure(kind: str, exc: BaseException, **ids: Any) -> None:
    """LOG-06 — the single failure record for a best-effort send. Every caller swallows the
    exception on purpose (an email failure must not fail the business action), so this is the
    only trace that a specific email was lost. `kind` names the email (`password_reset`,
    `onboarding_invite`, ...); `ids` are opaque identifiers only (`user_id`, `case_id`) — never
    the recipient address. A non-transport failure (template build, misconfiguration, a bug)
    has no provider classification and is logged at ERROR with its traceback, because it will
    keep happening until fixed."""
    if isinstance(exc, EmailDeliveryError):
        safe_log(
            logger.warning, "email.delivery.failed", email_kind=kind, **exc.log_fields(), **ids
        )
    else:
        safe_log(
            logger.error,
            "email.delivery.failed",
            email_kind=kind,
            failure_class="internal",
            retryable=False,
            outcome="not_sent",
            exc_info=exc,
            **safe_error(exc),
            **ids,
        )


def get_email_sender(settings: Settings) -> EmailSender:
    if settings.email_provider == "smtp":
        return SmtpEmailSender(settings)
    if settings.email_provider == "mailtrap":
        return MailtrapEmailSender(settings)
    if settings.email_provider == "hostinger":
        return HostingerEmailSender(settings)
    return LoggingEmailSender()
