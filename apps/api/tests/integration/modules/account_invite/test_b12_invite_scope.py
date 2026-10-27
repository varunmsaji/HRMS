"""B12 / OBS-HRA-01 - `POST /v1/employees/{employee_id}/invite` (`EMPLOYEE.INVITE`) honours the
permission's data scope.

Previously the handler took the scope and ignored it: a SELF/REPORTEES/BRANCH grant could invite
any employee in the company. Denied calls must leave no invite row, no email record, no audit
event; in-scope calls must produce exactly one of each.
"""

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from hrms.core.db.session import get_session_factory, set_rls_company_id

from ...b12_support import audit_count, fingerprint, scalar
from ...tenant_wipe import wipe_tenant
from ..attendance.test_attendance_day import _register_tenant
from ..attendance.test_period_summary_scope import _custom, _teardown, _world

pytestmark = pytest.mark.asyncio

SCOPES = [
    ("SELF", "M", {"M"}),
    ("REPORTEES", "M", {"R"}),
    ("REPORTEE_TREE", "M", {"R", "G"}),
    ("BRANCH", "M", {"M", "R", "G"}),
    ("COMPANY", "M", {"M", "R", "G", "S"}),
]
ALL = {"M", "R", "G", "S"}


async def _give_emails(company_id: UUID, ids: dict[str, str]) -> dict[str, str]:
    emails = {k: f"b12-{k.lower()}-{uuid4().hex[:6]}@example.com" for k in ids}
    factory = get_session_factory()
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        for key, employee_id in ids.items():
            await session.execute(
                text("UPDATE employee SET personal_email = :e WHERE id = :i AND company_id = :c"),
                {"e": emails[key], "i": employee_id, "c": str(company_id)},
            )
        await session.commit()
    return emails


async def _invites_for(company_id: UUID) -> int:
    return int(
        await scalar(company_id, "SELECT count(*) FROM account_invite WHERE company_id=:cid")
    )


async def _invite_mails(company_id: UUID, to: str) -> int:
    return int(
        await scalar(
            company_id,
            "SELECT count(*) FROM email_log WHERE company_id=:cid AND recipient=:r "
            "AND kind LIKE 'account_invite%'",
            r=to,
        )
    )


async def test_obs_hra01_invite_enforces_scope_with_db_and_email_effects(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    w = await _world(client)
    o_headers, o_company, o_user = await _register_tenant(client)
    try:
        emails = await _give_emails(w.company_id, w.ids)
        denied_body: dict | None = None
        for scope, caller, visible in SCOPES:
            headers = await _custom(w, ["EMPLOYEE.INVITE"], scope, w.ids[caller])
            for key in sorted(ALL):
                emp = w.ids[key]
                label = f"invite@{scope} target={key}"
                if key in visible:
                    invites = await _invites_for(w.company_id)
                    mails = await _invite_mails(w.company_id, emails[key])
                    audits = await audit_count(w.company_id, "ACCOUNT_INVITE_ISSUED")
                    r = await client.post(f"/v1/employees/{emp}/invite", headers=headers)
                    assert r.status_code == 201, (label, r.text)
                    assert r.json()["data"]["email"] == emails[key]
                    # exactly one new invite row, one email record, one audit event
                    assert await _invites_for(w.company_id) == invites + 1, label
                    assert await _invite_mails(w.company_id, emails[key]) == mails + 1, label
                    assert await audit_count(w.company_id, "ACCOUNT_INVITE_ISSUED") == audits + 1
                else:
                    before, before_other = (
                        await fingerprint(w.company_id),
                        await fingerprint(o_company),
                    )
                    r = await client.post(f"/v1/employees/{emp}/invite", headers=headers)
                    assert r.status_code == 404, (label, r.text)
                    assert await fingerprint(w.company_id) == before, label
                    assert await fingerprint(o_company) == before_other
                    body = r.json()
                    body.pop("meta", None)
                    body.get("error", {}).pop("request_id", None)
                    denied_body = denied_body or body
                    assert body == denied_body  # one shape for every denial
        # unknown id and another tenant's admin look identical to an out-of-scope denial
        hr_scoped = await _custom(w, ["EMPLOYEE.INVITE"], "SELF", w.ids["M"])
        unknown = await client.post(f"/v1/employees/{uuid4()}/invite", headers=hr_scoped)
        foreign = await client.post(f"/v1/employees/{w.ids['M']}/invite", headers=o_headers)
        for r in (unknown, foreign):
            assert r.status_code == 404
            body = r.json()
            body.pop("meta", None)
            body.get("error", {}).pop("request_id", None)
            assert body == denied_body
        # a caller with no linked employee sees nobody below COMPANY
        nobody = await _custom(w, ["EMPLOYEE.INVITE"], "SELF", None)
        before = await fingerprint(w.company_id)
        assert (
            await client.post(f"/v1/employees/{w.ids['M']}/invite", headers=nobody)
        ).status_code == 404
        assert await fingerprint(w.company_id) == before
    finally:
        await wipe_tenant(company_id=o_company, user_id=o_user)
        await _teardown(w)
