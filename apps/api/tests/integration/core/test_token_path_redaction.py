"""LOG-04 — bearer tokens that travel in URL paths (public onboarding and account-invite APIs; the
web pages email links point at) must not reach any API log sink intact.

Covered here: the shared `redact_path` helper; uvicorn's access-log record, through the filter
`configure_logging` installs on the `uvicorn.access` logger (the logger both plain uvicorn and
gunicorn's `UvicornWorker` write the access line to); and the API's own error events, which log
the route template. Nginx's own masking is validated separately against the real
`nginx:1.27-alpine` image (see the remediation report)."""

import json
import logging
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from pytest import CaptureFixture

from hrms.app import create_app
from hrms.core.observability.redaction import (
    REDACTED,
    AccessLogPathRedactionFilter,
    redact_path,
)

TOKEN = "tok_9QxSENTINELzP3"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (f"/v1/public/onboarding/{TOKEN}", f"/v1/public/onboarding/{REDACTED}"),
        (
            f"/v1/public/onboarding/{TOKEN}/documents/abc?x=1",
            f"/v1/public/onboarding/{REDACTED}/documents/abc",
        ),
        (
            f"/v1/public/account-invites/{TOKEN}/accept",
            f"/v1/public/account-invites/{REDACTED}/accept",
        ),
        (f"/reset-password/{TOKEN}", f"/reset-password/{REDACTED}"),
        (f"/verify-email/{TOKEN}", f"/verify-email/{REDACTED}"),
        (f"/accept-invite/{TOKEN}", f"/accept-invite/{REDACTED}"),
        (f"/onboarding/{TOKEN}?_rsc=1", f"/onboarding/{REDACTED}"),
        ("/v1/employees/123?page=2", "/v1/employees/123"),  # untouched, query dropped
        ("/doc.pdf?X-Amz-Signature=abc", "/doc.pdf"),
        ("/v1/public/onboarding/", "/v1/public/onboarding/"),  # no token segment
    ],
)
def test_redact_path(raw: str, expected: str) -> None:
    assert redact_path(raw) == expected


def test_access_log_filter_masks_the_uvicorn_record() -> None:
    record = logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("10.0.0.1:5000", "GET", f"/v1/public/onboarding/{TOKEN}/documents?a=b", "1.1", 200),
        None,
    )
    assert AccessLogPathRedactionFilter().filter(record) is True
    message = record.getMessage()
    assert TOKEN not in message
    assert f'"GET /v1/public/onboarding/{REDACTED}/documents HTTP/1.1" 200' in message


def test_configure_logging_installs_the_filter_once() -> None:
    from hrms.core.observability.logging import configure_logging

    configure_logging()
    configure_logging()
    filters = logging.getLogger("uvicorn.access").filters
    assert sum(isinstance(f, AccessLogPathRedactionFilter) for f in filters) == 1


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    from hrms.modules.account_invite.service import AccountInviteService

    async def _explode(self: object, token: str) -> None:
        raise RuntimeError("invite lookup failed")

    monkeypatch.setattr(AccountInviteService, "resolve", _explode)
    with TestClient(create_app()) as c:
        yield c


def test_crash_on_a_token_route_logs_the_template_not_the_token(
    client: TestClient, capfd: CaptureFixture[str]
) -> None:
    capfd.readouterr()
    r = client.get(f"/v1/public/account-invites/{TOKEN}")
    raw = capfd.readouterr()
    assert r.status_code == 500
    assert TOKEN not in raw.out and TOKEN not in raw.err

    entry = next(
        json.loads(line)
        for line in raw.out.splitlines()
        if line.startswith("{") and '"unhandled_exception"' in line
    )
    assert entry["http_path"] == "/v1/public/account-invites/{token}"
