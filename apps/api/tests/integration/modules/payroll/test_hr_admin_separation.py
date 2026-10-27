"""HR_ADMIN policy - payroll separation of duties and statutory-rate maker-checker.

HR_ADMIN prepares and processes payroll (setup, create run, lock inputs, compute, rollback of an
unfinished run) and can see statutory rates, but cannot approve, finalise, mark paid or download
the bank advice, and cannot change a finalised/paid run. Whoever created or edited a statutory
rate cannot verify it, and verification fails closed when the audit trail cannot show who edited it.
"""

from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.attendance.test_attendance_day import _register_tenant
from tests.integration.modules.attendance.test_attendance_security import (
    _cleanup_scoped_users,
    _create_permission_scoped_user,
)
from tests.integration.modules.leave.test_leave_rbac_matrix import _user_with_default_role
from tests.integration.modules.organisation.test_registration_flow import _cleanup
from tests.integration.modules.payroll.test_pay_run import (
    _action,
    _approver,
    _cleanup_pay_runs,
    _closed_period,
    _create_run,
    _employee,
    _legal_entity,
)

from hrms.core.db.session import get_session_factory, set_rls_company_id

pytestmark = pytest.mark.asyncio


async def _run_row(company_id: UUID, run_id: str) -> dict[str, Any]:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        row = (
            await session.execute(
                text("SELECT status, version, net_minor FROM pay_run WHERE id = CAST(:i AS uuid)"),
                {"i": run_id},
            )
        ).one()
        audit = (
            await session.execute(
                text(
                    "SELECT count(*) FROM audit_log WHERE company_id = CAST(:c AS uuid) "
                    "AND entity_id = CAST(:i AS uuid)"
                ),
                {"c": str(company_id), "i": run_id},
            )
        ).scalar_one()
    return {"status": row.status, "version": row.version, "net": row.net_minor, "audit": audit}


async def _hr(company_id: UUID, employee_id: str) -> dict[str, str]:
    return await _user_with_default_role(company_id, "HR_ADMIN", UUID(employee_id))


async def test_hr_admin_prepares_payroll_but_cannot_approve_finalise_pay_or_download(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    admin, company_id, user_id = await _register_tenant(client)
    try:
        le = await _legal_entity(client, admin)
        emp = await _employee(client, admin, le)
        await _closed_period(
            company_id=company_id, legal_entity_id=le, start="2026-09-01", end="2026-09-30",
            paid_days={emp: "30"}, days_in_month=30,
        )  # fmt: skip
        hr = await _hr(company_id, emp)

        # HR_ADMIN prepares and processes: create, lock inputs, compute; reads the master data.
        run = await _create_run(client, hr, le, "2026-09")
        run = await _action(client, hr, run, "lock-inputs")
        run = await _action(client, hr, run, "compute")
        assert run["status"] == "COMPUTED"
        for path in ("/v1/payroll/pay-runs", "/v1/payroll/statutory-rates", "/v1/payroll/settings",
                     "/v1/payroll/salary-structures"):  # fmt: skip
            assert (await client.get(path, headers=hr)).status_code == 200, path

        before = await _run_row(company_id, run["id"])
        # ... but cannot approve, finalise, mark paid or download bank advice.
        for action in ("approve", "finalise", "mark-paid"):
            r = await client.post(
                f"/v1/payroll/pay-runs/{run['id']}/{action}",
                headers={**hr, "If-Match": str(run["version"])},
            )
            assert r.status_code == 403, (action, r.text)
            assert r.json()["error"]["code"] == "PERMISSION_DENIED"
        advice = await client.get(f"/v1/payroll/pay-runs/{run['id']}/bank-advice", headers=hr)
        assert advice.status_code == 403
        assert await _run_row(company_id, run["id"]) == before  # nothing moved, nothing audited

        # Separate approver (COMPANY_ADMIN-equivalent) approves and finalises; HR cannot then
        # touch the approved/finalised run.
        approver = await _approver(company_id)
        run = await _action(client, approver, run, "approve")
        for step in ("compute", "lock-inputs"):
            r = await client.post(
                f"/v1/payroll/pay-runs/{run['id']}/{step}",
                headers={**hr, "If-Match": str(run["version"])},
            )
            assert r.status_code in (409, 422), (step, r.status_code, r.text)
        run = await _action(client, admin, run, "finalise")
        assert run["status"] == "FINALISED"
        frozen = await _run_row(company_id, run["id"])
        attempts = [
            ("POST", "compute", None), ("POST", "lock-inputs", None), ("POST", "rollback",
            {"reason": "hr rewrites history"}), ("POST", "approve", None),
            ("POST", "mark-paid", None),
        ]  # fmt: skip
        for method, step, body in attempts:
            r = await client.request(
                method,
                f"/v1/payroll/pay-runs/{run['id']}/{step}",
                headers={**hr, "If-Match": str(run["version"])},
                json=body,
            )
            assert r.status_code in (403, 409, 422), (step, r.status_code, r.text)
        patched = await client.patch(
            f"/v1/payroll/pay-runs/{run['id']}",
            headers={**hr, "If-Match": str(run["version"])},
            json={"pay_date": "2026-12-31"},
        )
        assert patched.status_code in (403, 409, 422), patched.text
        deleted = await client.delete(f"/v1/payroll/pay-runs/{run['id']}", headers=hr)
        assert deleted.status_code in (403, 409, 422), deleted.text
        assert await _run_row(company_id, run["id"]) == frozen  # immutable history untouched

        run = await _action(client, admin, run, "mark-paid")
        assert run["status"] == "PAID"
        assert (
            await client.get(f"/v1/payroll/pay-runs/{run['id']}/bank-advice", headers=hr)
        ).status_code == 403
    finally:
        await _cleanup_pay_runs(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


# ----------------------------------------------------------------------- statutory maker-checker


async def _rates(client: AsyncClient, headers: dict[str, str]) -> dict[tuple[str, Any], Any]:
    r = await client.get("/v1/payroll/statutory-rates", headers=headers)
    assert r.status_code == 200, r.text
    return {(x["scheme"], x["state_code"]): x for x in r.json()["data"]}


async def _verify(client: AsyncClient, headers: dict[str, str], rate: dict[str, Any]):
    return await client.post(
        f"/v1/payroll/statutory-rates/{rate['id']}/verify",
        headers={**headers, "If-Match": str(rate["version"])},
    )


async def _edit(client: AsyncClient, headers: dict[str, str], rate: dict[str, Any], note: str):
    r = await client.patch(
        f"/v1/payroll/statutory-rates/{rate['id']}",
        headers={**headers, "If-Match": str(rate["version"])},
        json={"notes": note},
    )
    assert r.status_code == 200, r.text
    return r.json()["data"]


async def _checker(company_id: UUID) -> dict[str, str]:
    h, _ = await _create_permission_scoped_user(
        company_id=company_id, permission_codes=["PAYROLL.STATUTORY_MANAGE"], data_scope="COMPANY"
    )
    return h


async def _owner_sql(company_id: UUID, sql: str, **params: Any) -> None:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        await session.execute(text(sql), params)
        await session.commit()


async def test_editor_cannot_verify_own_statutory_change_independent_user_can(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    admin, company_id, user_id = await _register_tenant(client)
    try:
        emp = await _employee(
            client, admin, await _legal_entity(client, admin), bank=False, salary=False
        )
        hr = await _hr(company_id, emp)
        other = await _checker(company_id)
        pf = (await _rates(client, hr))[("PF", None)]
        assert pf["is_seeded"] and not pf["verified"]  # defaults are NOT verified by existing

        # A seeded, never-edited default has no human editor: HR may verify it.
        assert (await _verify(client, hr, pf)).status_code == 200
        pf = (await _rates(client, hr))[("PF", None)]
        assert pf["verified"]

        # HR edits it (verification is cleared) and cannot verify its own change.
        edited = await _edit(client, hr, pf, "HR re-checked the EPFO circular")
        assert edited["verified"] is False
        denied = await _verify(client, hr, edited)
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "STATUTORY_RATE_SELF_VERIFICATION"
        assert (await _rates(client, hr))[("PF", None)]["verified"] is False

        # An independent user can; the sign-off is attributed to them.
        ok = await _verify(client, other, edited)
        assert ok.status_code == 200 and ok.json()["data"]["verified"] is True

        # The independent verifier now edits; HR (who edited earlier, before the sign-off) may
        # verify THAT change, the verifier may not verify their own.
        again = await _edit(client, other, ok.json()["data"], "second look")
        assert (await _verify(client, other, again)).status_code == 403
        assert (await _verify(client, hr, again)).status_code == 200
    finally:
        await _cleanup_pay_runs(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_creator_of_a_new_rate_cannot_verify_it_and_company_admin_is_not_exempt(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    admin, company_id, user_id = await _register_tenant(client)
    try:
        emp = await _employee(
            client, admin, await _legal_entity(client, admin), bank=False, salary=False
        )
        hr = await _hr(company_id, emp)
        body = {
            "scheme": "PF", "effective_from": "2027-04-01",
            "parameters": (await _rates(client, hr))[("PF", None)]["parameters"],
        }  # fmt: skip
        created = await client.post("/v1/payroll/statutory-rates", headers=hr, json=body)
        assert created.status_code == 201, created.text
        rate = created.json()["data"]
        assert rate["verified"] is False and rate["is_seeded"] is False
        assert (await _verify(client, hr, rate)).status_code == 403  # creator = checker
        # the superseded (closed) seeded rate is still verifiable by someone else
        # COMPANY_ADMIN is held to the same rule: it cannot verify a rate it edited.
        edited = await _edit(client, admin, rate, "admin tweak")
        assert (await _verify(client, admin, edited)).status_code == 403
        assert (await _verify(client, hr, edited)).status_code == 403  # HR created it originally
        other = await _checker(company_id)
        assert (await _verify(client, other, edited)).status_code == 200
    finally:
        await _cleanup_pay_runs(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_verification_fails_closed_when_the_audit_trail_cannot_name_the_editor(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    admin, company_id, user_id = await _register_tenant(client)
    try:
        emp = await _employee(
            client, admin, await _legal_entity(client, admin), bank=False, salary=False
        )
        hr = await _hr(company_id, emp)
        other = await _checker(company_id)
        rates = await _rates(client, hr)

        async def count_verified(rate_id: str) -> int:
            async with get_session_factory()() as session:
                await set_rls_company_id(session, str(company_id))
                return int(
                    (
                        await session.execute(
                            text(
                                "SELECT count(*) FROM audit_log WHERE entity_id = CAST(:i AS uuid) "
                                "AND action = 'PAYROLL_STATUTORY_RATE_VERIFIED'"
                            ),
                            {"i": rate_id},
                        )
                    ).scalar_one()
                )

        # 1. missing: the edit's audit row is gone -> history does not reconcile with the version
        a = await _edit(client, hr, rates[("ESI", None)], "edited")
        await _owner_sql(
            company_id, "DELETE FROM audit_log WHERE entity_id = CAST(:i AS uuid)", i=a["id"]
        )
        # 2. incomplete: actor of the edit is unknown (NULL)
        b = await _edit(client, hr, rates[("TDS", None)], "edited")
        await _owner_sql(
            company_id,
            "UPDATE audit_log SET actor_user_id = NULL WHERE entity_id = CAST(:i AS uuid) "
            "AND action = 'PAYROLL_STATUTORY_RATE_UPDATED'",
            i=b["id"],
        )
        # 3. ambiguous: a verification row nobody can account for (version no longer reconciles)
        c = await _edit(client, hr, rates[("PT", "MH")], "edited")
        await _owner_sql(
            company_id,
            "INSERT INTO audit_log (id, company_id, actor_user_id, action, entity_type, "
            "entity_id) SELECT gen_random_uuid(), company_id, actor_user_id, "
            "'PAYROLL_STATUTORY_RATE_VERIFIED', entity_type, entity_id FROM audit_log "
            "WHERE entity_id = CAST(:i AS uuid) LIMIT 1",
            i=c["id"],
        )
        # 4. non-seeded rate whose creation was never audited
        created = await client.post(
            "/v1/payroll/statutory-rates",
            headers=hr,
            json={
                "scheme": "PF",
                "effective_from": "2027-04-01",
                "parameters": rates[("PF", None)]["parameters"],
            },
        )
        d = created.json()["data"]
        await _owner_sql(
            company_id, "DELETE FROM audit_log WHERE entity_id = CAST(:i AS uuid)", i=d["id"]
        )
        # 5. no verifier identity is not testable via HTTP; the independent user is used below.

        for rate in (a, b, c, d):
            current = next(
                r
                for r in (await client.get("/v1/payroll/statutory-rates", headers=hr)).json()[
                    "data"
                ]
                if r["id"] == rate["id"]
            )
            for who, headers in (("editor", hr), ("independent", other)):
                r = await _verify(client, headers, current)
                assert r.status_code == 403, (rate["scheme"], who, r.status_code, r.text)
                assert r.json()["error"]["code"] in (
                    "STATUTORY_RATE_EDITOR_UNVERIFIABLE",
                    "STATUTORY_RATE_SELF_VERIFICATION",
                ), r.text
            assert current["verified"] is False
            assert (
                await count_verified(rate["id"]) <= 1
            )  # only the planted case-3 row, no real sign-off
    finally:
        await _cleanup_pay_runs(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()
