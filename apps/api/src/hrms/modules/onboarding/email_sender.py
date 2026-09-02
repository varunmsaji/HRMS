"""Minimal onboarding-scoped email sender (O3) — plan §8.4 option (a): a small port plus one
real implementation, not a prerequisite on the full Notifications engine
(`docs/product/VERSION_1_ROADMAP.md` row 6, "Not started"). Designed to be swapped for that
engine later without touching onboarding's business logic — every caller depends only on the
`EmailSender` protocol, never on which implementation `get_email_sender` selected.

The plan named three templates (invite, changes-requested, activated); only the invite one
exists yet (`email_templates.py`) — the other two have no caller until O6/O7 land, and adding
them now would be code nothing exercises."""

from typing import Protocol

import aioboto3

from hrms.core.config.settings import Settings
from hrms.core.observability.logging import get_logger

logger = get_logger(__name__)


class EmailSender(Protocol):
    async def send(self, *, to: str, subject: str, html_body: str, text_body: str) -> None: ...


class LoggingEmailSender:
    """Selected whenever AWS credentials aren't configured (`Settings.aws_access_key_id`/
    `aws_secret_access_key` blank) — every local dev environment and this module's own test
    suite today. Logs the email instead of sending it, so onboarding is fully exercisable
    end-to-end (including reading the invite URL back out of the admin API response) without a
    real AWS account or a verified SES sender identity."""

    async def send(self, *, to: str, subject: str, html_body: str, text_body: str) -> None:
        del html_body  # not useful in a log line; the text body is
        logger.info(
            "onboarding_email_not_sent_no_ses_configured",
            to=to,
            subject=subject,
            text_body=text_body,
        )


class SesEmailSender:
    """Real delivery via Amazon SES, using the same `aioboto3` dependency already pulled in for
    S3 (plan §8.3) — this is its first actual consumer."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    async def send(self, *, to: str, subject: str, html_body: str, text_body: str) -> None:
        session = aioboto3.Session(
            aws_access_key_id=self._settings.aws_access_key_id,
            aws_secret_access_key=self._settings.aws_secret_access_key,
            region_name=self._settings.aws_region,
        )
        async with session.client("ses") as ses:
            await ses.send_email(
                Source=self._settings.email_sender_from_address,
                Destination={"ToAddresses": [to]},
                Message={
                    "Subject": {"Data": subject, "Charset": "UTF-8"},
                    "Body": {
                        "Html": {"Data": html_body, "Charset": "UTF-8"},
                        "Text": {"Data": text_body, "Charset": "UTF-8"},
                    },
                },
            )


def get_email_sender(settings: Settings) -> EmailSender:
    if settings.aws_access_key_id and settings.aws_secret_access_key:
        return SesEmailSender(settings)
    return LoggingEmailSender()
