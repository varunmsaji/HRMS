"""Mission Phase 6 — every real sender classifies a failure (`failure_class`, `retryable`,
`outcome`) so the single caller-level `email.delivery.failed` event can distinguish a rejected
address from an outage, and a certain non-send from an *uncertain* outcome after a timeout
(provider may have accepted it — never retried blindly). Provider acceptance is logged as
`email.provider.accepted`, never as delivery."""

from unittest.mock import AsyncMock

import aiosmtplib
import httpx
import pytest
import structlog
from structlog.testing import capture_logs

from hrms.core.config.settings import Settings
from hrms.modules.onboarding.email_sender import (
    EmailDeliveryError,
    HostingerEmailSender,
    LoggingEmailSender,
    SmtpEmailSender,
    log_email_failure,
)

_REQUEST = httpx.Request("POST", "https://api.mail.hostinger.com/api/v1/mailboxes/x/send")


@pytest.fixture(autouse=True)
def _uncached_logger(monkeypatch: pytest.MonkeyPatch) -> None:
    """`cache_logger_on_first_use` lets a module-level logger keep whatever pipeline was active
    when an earlier test first used it, which `capture_logs()` cannot intercept. A fresh proxy
    per test makes these assertions independent of test order."""
    monkeypatch.setattr(
        "hrms.modules.onboarding.email_sender.logger",
        structlog.get_logger("hrms.modules.onboarding.email_sender"),
    )


def _hostinger() -> HostingerEmailSender:
    return HostingerEmailSender(
        Settings(
            environment="development",
            email_provider="hostinger",
            hostinger_mail_api_token="tok-SENTINEL",
            hostinger_mail_mailbox_id="AC0",
        )
    )


def _smtp() -> SmtpEmailSender:
    return SmtpEmailSender(
        Settings(
            environment="development",
            email_provider="smtp",
            smtp_host="smtp.example.com",
            smtp_port=587,
            smtp_from_email="noreply@example.com",
            smtp_use_tls=True,
        )
    )


async def _send(sender: object) -> None:
    await sender.send(  # type: ignore[attr-defined]
        to="person@example.com", subject="s", html_body="<p>h</p>", text_body="t"
    )


@pytest.mark.parametrize(
    ("outcome", "expected"),
    [
        (httpx.Response(401, request=_REQUEST), ("auth", False, "not_sent", 401)),
        (httpx.Response(403, request=_REQUEST), ("auth", False, "not_sent", 403)),
        (httpx.Response(422, request=_REQUEST), ("rejected", False, "not_sent", 422)),
        (httpx.Response(429, request=_REQUEST), ("rate_limited", True, "not_sent", 429)),
        (httpx.Response(503, request=_REQUEST), ("provider_error", True, "unknown", 503)),
        (httpx.ConnectError("refused"), ("network", True, "not_sent", None)),
        (httpx.ConnectTimeout("connect"), ("timeout", True, "not_sent", None)),
        (httpx.ReadTimeout("read"), ("timeout", True, "unknown", None)),
        (httpx.RemoteProtocolError("dropped"), ("network", True, "unknown", None)),
    ],
)
async def test_http_provider_failures_are_classified(
    monkeypatch: pytest.MonkeyPatch, outcome: object, expected: tuple[object, ...]
) -> None:
    mock = (
        AsyncMock(return_value=outcome)
        if isinstance(outcome, httpx.Response)
        else AsyncMock(side_effect=outcome)
    )
    monkeypatch.setattr(httpx.AsyncClient, "post", mock)
    with pytest.raises(EmailDeliveryError) as exc_info:
        await _send(_hostinger())
    err = exc_info.value
    assert (err.failure_class, err.retryable, err.outcome, err.status_code) == expected
    assert err.provider == "hostinger"
    assert "tok-SENTINEL" not in str(err)


@pytest.mark.parametrize(
    ("exc", "failure_class", "outcome"),
    [
        (aiosmtplib.SMTPAuthenticationError(535, "bad creds"), "auth", "not_sent"),
        (aiosmtplib.SMTPConnectError("refused"), "network", "not_sent"),
        (aiosmtplib.SMTPServerDisconnected("gone"), "timeout", "unknown"),
        (aiosmtplib.SMTPResponseException(451, "try later"), "provider_error", "not_sent"),
        (aiosmtplib.SMTPResponseException(554, "rejected"), "rejected", "not_sent"),
    ],
)
async def test_smtp_failures_are_classified(
    monkeypatch: pytest.MonkeyPatch, exc: Exception, failure_class: str, outcome: str
) -> None:
    monkeypatch.setattr(aiosmtplib, "send", AsyncMock(side_effect=exc))
    with pytest.raises(EmailDeliveryError) as exc_info:
        await _send(_smtp())
    assert exc_info.value.failure_class == failure_class
    assert exc_info.value.outcome == outcome


async def test_provider_acceptance_is_logged_as_acceptance_not_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        httpx.AsyncClient, "post", AsyncMock(return_value=httpx.Response(200, request=_REQUEST))
    )
    with capture_logs() as logs:
        await _send(_hostinger())
    (accepted,) = [e for e in logs if e["event"] == "email.provider.accepted"]
    assert accepted["provider"] == "hostinger"
    assert "person@example.com" not in repr(logs)


def _build_template() -> None:
    raise KeyError("template_variable")


def test_a_non_transport_failure_is_an_error_with_traceback() -> None:
    try:
        _build_template()
    except KeyError as exc:
        with capture_logs() as logs:
            log_email_failure("onboarding_activated", exc, case_id="c-1")
    (event,) = logs
    assert event["event"] == "email.delivery.failed"
    assert event["log_level"] == "error"
    assert event["failure_class"] == "internal"
    assert event["exception_type"] == "KeyError"
    assert event["case_id"] == "c-1"
    assert event["exc_info"] is not None


async def test_dev_logging_sender_keeps_content_out_of_the_structured_log(
    capsys: pytest.CaptureFixture[str],
) -> None:
    link = "http://localhost:3000/reset-password/dev-token-123"
    with capture_logs() as logs:
        await LoggingEmailSender().send(
            to="dev@example.com", subject="Reset", html_body="<p/>", text_body=link
        )
    assert [e["event"] for e in logs] == ["email.logged_not_sent"]
    assert link not in repr(logs) and "dev@example.com" not in repr(logs)
    # The developer still gets the readable copy (stderr, outside the JSON log stream).
    assert link in capsys.readouterr().err
