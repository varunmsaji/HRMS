"""LOG-06 / mission Phase 5 — the best-effort steps after an onboarding activation must neither
undo it nor fail silently.

* A *database* failure inside the account-invite auto-issue used to leave the request transaction
  aborted, so the activation's own audit write and commit failed and the activation was undone
  (despite the code's stated intent). The auto-issue now runs in a SAVEPOINT; the activation
  commits and the failure is logged once, at ERROR, with identifiers.
* An activation-email transport failure is logged as `email.delivery.failed` without the
  candidate's address."""

import json
from typing import Any

import pytest
from httpx import AsyncClient
from pytest import CaptureFixture
from sqlalchemy import text

from hrms.modules.account_invite.service import AccountInviteService
from hrms.modules.onboarding import service as onboarding_service
from hrms.modules.onboarding.email_sender import EmailDeliveryError

from .test_onboarding_activation import _full_teardown, _verified_case
from .test_onboarding_case import _register_tenant

pytestmark = pytest.mark.asyncio


def _events(raw: str) -> list[dict[str, Any]]:
    out = []
    for line in raw.splitlines():
        try:
            parsed = json.loads(line)
        except ValueError:
            continue
        if isinstance(parsed, dict) and "event" in parsed:
            out.append(parsed)
    return out


async def test_db_failure_in_invite_auto_issue_does_not_undo_activation(
    client: AsyncClient,
    seeded_plan_catalogue: None,
    monkeypatch: pytest.MonkeyPatch,
    capfd: CaptureFixture[str],
) -> None:
    async def _aborting_issue(self: AccountInviteService, *_a: Any, **_k: Any) -> None:
        # A real database error on the request's own session: aborts the transaction (or,
        # with the fix, only the savepoint).
        await self._session.execute(text("SELECT * FROM no_such_table_auto_issue"))

    monkeypatch.setattr(AccountInviteService, "issue_for_employee", _aborting_issue)
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _verified_case(client, headers, company_id, with_org=True)
        capfd.readouterr()
        response = await client.post(f"/v1/onboarding-cases/{case['id']}/activate", headers=headers)
        raw = capfd.readouterr().out

        assert response.status_code == 200, response.text
        assert response.json()["data"]["status"] == "ACTIVATED"
        reread = await client.get(f"/v1/onboarding-cases/{case['id']}", headers=headers)
        assert reread.json()["data"]["status"] == "ACTIVATED"

        (failed,) = [e for e in _events(raw) if e["event"] == "account_invite.auto_issue_failed"]
        assert failed["level"] == "error"
        assert failed["company_id"] == str(company_id)
        assert failed["employee_id"] == response.json()["data"]["employee_id"]
        assert failed["error_category"] == "db_error"
        assert "Traceback" in failed["exception"]
    finally:
        await _full_teardown(company_id=company_id, user_id=user_id)


async def test_activation_email_failure_is_logged_without_the_address(
    client: AsyncClient,
    seeded_plan_catalogue: None,
    monkeypatch: pytest.MonkeyPatch,
    capfd: CaptureFixture[str],
) -> None:
    class _FailingSender:
        async def send(self, **_kwargs: Any) -> None:
            raise EmailDeliveryError(
                "hostinger", "provider_error", True, "unknown", 503, error_type=RuntimeError()
            )

    monkeypatch.setattr(onboarding_service, "get_email_sender", lambda _settings: _FailingSender())
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _verified_case(client, headers, company_id, with_org=True)
        capfd.readouterr()
        response = await client.post(f"/v1/onboarding-cases/{case['id']}/activate", headers=headers)
        raw = capfd.readouterr().out
        assert response.status_code == 200, response.text

        failures = [e for e in _events(raw) if e["event"] == "email.delivery.failed"]
        (activated,) = [e for e in failures if e["email_kind"] == "onboarding_activated"]
        assert activated["level"] == "warning"
        assert activated["case_id"] == case["id"]
        assert activated["outcome"] == "unknown"
        assert case["personal_email"] not in raw
    finally:
        await _full_teardown(company_id=company_id, user_id=user_id)
