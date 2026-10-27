"""B12 regression suite - DEF-B11-01 (cross-tenant attendance calculation) and OBS-HRA-01 for the
four attendance handlers that ignored their permission's data scope.

Routes (exact, from the B11 defect register):
  POST /v1/attendance/days/calculate?employee_id&date           ATTENDANCE.VIEW_ALL
  POST /v1/attendance/days/{id}/recompute                       ATTENDANCE.RECOMPUTE
  POST /v1/attendance/days/calculate-range                      ATTENDANCE.RECOMPUTE
  POST /v1/attendance/days/{id}/work-on-leave/keep-leave        ATTENDANCE.RECOMPUTE

Every denied case asserts the database fingerprint (rows + content hash of attendance_day,
audit_log, account_invite, overtime_record, plus email_log count) of BOTH tenants is unchanged.
"""

from datetime import date
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.core.errors.base import NotFoundError
from hrms.modules.attendance import tasks as attendance_tasks
from hrms.modules.attendance.permissions import ATTENDANCE_RECOMPUTE, ATTENDANCE_VIEW_ALL
from hrms.modules.attendance.service import AttendanceDayService

from ...b12_support import audit_count, fingerprint, scalar
from ...tenant_wipe import wipe_tenant
from .test_attendance_day import _build_wired_employee, _register_tenant
from .test_leave_projection import _cleanup_leave_projection, _sync
from .test_period_summary_scope import World, _custom, _teardown, _world

pytestmark = pytest.mark.asyncio

DAY = "2026-08-10"


# --------------------------------------------------------------------------------------------
# DEF-B11-01 - cross-tenant calculation
# --------------------------------------------------------------------------------------------


async def _day_ids(client: AsyncClient, headers: dict[str, str]) -> dict[str, str]:
    data = (await client.get("/v1/attendance/days", headers=headers)).json()["data"]
    return {row["employee_id"]: row["id"] for row in data}


def _body(response) -> dict:  # type: ignore[no-untyped-def]
    """Response without the per-request meta, for byte-comparison of two denials."""
    data = response.json()
    data.pop("meta", None)
    if isinstance(data.get("error"), dict):
        data["error"].pop("request_id", None)
    return data


async def test_def_b11_01_calculate_rejects_foreign_and_unknown_employee_without_any_write(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    a_headers, a_company, a_user = await _register_tenant(client)
    b_headers, b_company, b_user = await _register_tenant(client)
    try:
        wired = await _build_wired_employee(client, a_headers)
        emp_a = wired["employee"]["id"]

        # 1. valid in-tenant calculation still works and is audited
        ok = await client.post(
            "/v1/attendance/days/calculate",
            headers=a_headers,
            params={"employee_id": emp_a, "date": DAY},
        )
        assert ok.status_code == 200, ok.text
        assert ok.json()["data"]["employee_id"] == emp_a
        day_id = ok.json()["data"]["id"]
        assert await audit_count(a_company) >= 1

        before_a, before_b = await fingerprint(a_company), await fingerprint(b_company)

        # 2. foreign-tenant employee id, from tenant B's COMPANY_ADMIN
        foreign = await client.post(
            "/v1/attendance/days/calculate",
            headers=b_headers,
            params={"employee_id": emp_a, "date": DAY},
        )
        assert foreign.status_code == 404, foreign.text

        # 3. unknown id: same status AND same body (no existence oracle) - also for tenant A's own
        # admin, who previously got a 500 from the unhandled foreign-key violation.
        for headers in (b_headers, a_headers):
            unknown = await client.post(
                "/v1/attendance/days/calculate",
                headers=headers,
                params={"employee_id": str(uuid4()), "date": DAY},
            )
            assert unknown.status_code == 404, unknown.text
            assert _body(unknown) == _body(foreign)

        # 4. forged / mismatched company header never reaches the service
        forged = await client.post(
            "/v1/attendance/days/calculate",
            headers={**b_headers, "X-Company-Id": str(a_company)},
            params={"employee_id": emp_a, "date": DAY},
        )
        assert forged.status_code in (401, 403, 404), forged.text

        # 5. date omitted (server default) takes the same guard
        no_date = await client.post(
            "/v1/attendance/days/calculate", headers=b_headers, params={"employee_id": emp_a}
        )
        assert no_date.status_code == 404

        # sibling handlers that look the day up by id: another tenant's day id is a plain 404
        for path, body in (
            (f"/v1/attendance/days/{day_id}/recompute", None),
            (f"/v1/attendance/days/{day_id}/work-on-leave/keep-leave", {"reason": "forged"}),
        ):
            r = await client.post(path, headers=b_headers, json=body)
            assert r.status_code == 404, (path, r.text)

        # 6. DB state / audit after every denial: both tenants byte-identical, and no row in B
        # references A's employee.
        assert await fingerprint(a_company) == before_a
        assert await fingerprint(b_company) == before_b
        assert (
            await scalar(
                b_company,
                "SELECT count(*) FROM attendance_day WHERE company_id = :cid AND employee_id = :e",
                e=UUID(emp_a),
            )
            == 0
        )
    finally:
        await wipe_tenant(company_id=b_company, user_id=b_user)
        await wipe_tenant(company_id=a_company, user_id=a_user)


async def test_def_b11_01_direct_service_call_is_guarded_at_the_service_boundary(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The guard lives in the service, not the route: a direct (internal) call with another
    tenant's employee id raises the same NotFoundError and persists nothing."""
    a_headers, a_company, a_user = await _register_tenant(client)
    b_headers, b_company, b_user = await _register_tenant(client)
    try:
        emp_a = (await _build_wired_employee(client, a_headers))["employee"]["id"]
        before_a, before_b = await fingerprint(a_company), await fingerprint(b_company)

        factory = get_session_factory()
        for unknown_or_foreign in (UUID(emp_a), uuid4()):
            async with factory() as session:
                await set_rls_company_id(session, str(b_company))
                with pytest.raises(NotFoundError):
                    await AttendanceDayService(session).calculate(
                        b_company, unknown_or_foreign, date.fromisoformat(DAY), actor_user_id=b_user
                    )
                await session.rollback()

        # the range job's per-employee unit (what the Celery task runs) rejects it too
        counts = await attendance_tasks._calculate_employee_dates(
            b_company, UUID(emp_a), [date.fromisoformat(DAY)], actor_user_id=None
        )
        assert counts["calculated"] == 0 and counts["failed"] == 1

        assert await fingerprint(a_company) == before_a
        assert await fingerprint(b_company) == before_b
    finally:
        await wipe_tenant(company_id=b_company, user_id=b_user)
        await wipe_tenant(company_id=a_company, user_id=a_user)


async def test_def_b11_01_calculate_range_celery_path_ignores_foreign_employee_ids(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """calculate-range is body-driven. Tenant B's admin may queue a job naming A's employee (the
    HTTP layer cannot know which ids exist without a lookup), but the task body - the code the
    Celery worker runs - must not create anything for it."""
    a_headers, a_company, a_user = await _register_tenant(client)
    b_headers, b_company, b_user = await _register_tenant(client)
    try:
        emp_a = (await _build_wired_employee(client, a_headers))["employee"]["id"]
        own = (await _build_wired_employee(client, b_headers))["employee"]["id"]
        before_a, before_b = await fingerprint(a_company), await fingerprint(b_company)

        with patch.object(
            attendance_tasks.calculate_range, "delay", return_value=SimpleNamespace(id="j")
        ) as delay:
            r = await client.post(
                "/v1/attendance/days/calculate-range",
                headers=b_headers,
                json={"date_from": DAY, "date_to": DAY, "employee_ids": [emp_a]},
            )
        # COMPANY scope: not a scope violation, so accepted; ownership is enforced by the job
        assert r.status_code == 202, r.text
        args = delay.call_args.args
        assert args[0] == str(b_company)

        counts = await attendance_tasks._calculate_range_async(
            b_company,
            date.fromisoformat(DAY),
            date.fromisoformat(DAY),
            [UUID(emp_a)],
            b_user,
        )
        assert counts["calculated"] == 0 and counts["employees"] == 0
        assert await fingerprint(a_company) == before_a
        assert (
            await scalar(
                b_company,
                "SELECT count(*) FROM attendance_day WHERE company_id = :cid AND employee_id = :e",
                e=UUID(emp_a),
            )
            == 0
        )
        # mixed list: B's own employee is calculated, A's is not
        mixed = await attendance_tasks._calculate_range_async(
            b_company,
            date.fromisoformat(DAY),
            date.fromisoformat(DAY),
            [UUID(emp_a), UUID(own)],
            b_user,
        )
        assert mixed["employees"] == 1 and mixed["calculated"] == 1
        assert (
            await scalar(
                b_company,
                "SELECT count(*) FROM attendance_day WHERE company_id = :cid AND employee_id = :e",
                e=UUID(emp_a),
            )
            == 0
        )
        assert await fingerprint(a_company) == before_a
        del before_b
    finally:
        await wipe_tenant(company_id=b_company, user_id=b_user)
        await wipe_tenant(company_id=a_company, user_id=a_user)


# --------------------------------------------------------------------------------------------
# OBS-HRA-01 - attendance handlers honour the permission's data scope
# --------------------------------------------------------------------------------------------

#: (scope, caller key, employee keys visible under it) - the same expectations the DEF-B6-02
#: summary tests pin for the employee reporting model (M manager, R report, G grandchild,
#: S other branch).
SCOPES = [
    ("SELF", "M", {"M"}),
    ("REPORTEES", "M", {"R"}),
    ("REPORTEE_TREE", "M", {"R", "G"}),
    ("BRANCH", "M", {"M", "R", "G"}),
    ("COMPANY", "M", {"M", "R", "G", "S"}),
]
ALL = {"M", "R", "G", "S"}


async def _expect_unchanged(w: World, other: tuple[UUID, dict] | None, action):  # type: ignore[no-untyped-def]
    before = await fingerprint(w.company_id)
    before_other = await fingerprint(other[0]) if other else None
    result = await action()
    assert await fingerprint(w.company_id) == before
    if other:
        assert await fingerprint(other[0]) == before_other
    return result


async def test_obs_hra01_calculate_and_recompute_enforce_scope(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    w = await _world(client)
    c_headers, c_company, c_user = await _register_tenant(client)  # unrelated third tenant
    try:
        days = await _day_ids(client, w.headers)
        assert set(days) == set(w.ids.values())
        for scope, caller, visible in SCOPES:
            for perm, kind in (
                (ATTENDANCE_VIEW_ALL, "calculate"),
                (ATTENDANCE_RECOMPUTE, "recompute"),
            ):
                headers = await _custom(w, [perm], scope, w.ids[caller])
                for key in ALL:
                    emp = w.ids[key]

                    async def call(emp=emp, kind=kind, headers=headers):  # type: ignore[no-untyped-def]
                        if kind == "calculate":
                            return await client.post(
                                "/v1/attendance/days/calculate",
                                headers=headers,
                                params={"employee_id": emp, "date": DAY},
                            )
                        return await client.post(
                            f"/v1/attendance/days/{days[emp]}/recompute", headers=headers
                        )

                    label = f"{kind}@{scope} caller={caller} target={key}"
                    if key in visible:
                        r = await call()
                        assert r.status_code == 200, (label, r.text)
                        assert r.json()["data"]["employee_id"] == emp
                    else:
                        r = await _expect_unchanged(w, (c_company, {}), call)
                        assert r.status_code == 404, (label, r.text)
                        unknown = await client.post(
                            "/v1/attendance/days/calculate",
                            headers=headers,
                            params={"employee_id": str(uuid4()), "date": DAY},
                        )
                        if kind == "calculate":
                            assert _body(unknown) == _body(r), label  # no oracle
        # no linked employee: every scope below COMPANY resolves to nobody
        for scope in ("SELF", "REPORTEES", "BRANCH"):
            headers = await _custom(w, [ATTENDANCE_VIEW_ALL], scope, None)
            r = await _expect_unchanged(
                w,
                None,
                lambda headers=headers: client.post(
                    "/v1/attendance/days/calculate",
                    headers=headers,
                    params={"employee_id": w.ids["M"], "date": DAY},
                ),
            )
            assert r.status_code == 404
        # another tenant's admin on this tenant's ids
        r = await _expect_unchanged(
            w,
            (c_company, {}),
            lambda: client.post(
                "/v1/attendance/days/calculate",
                headers=c_headers,
                params={"employee_id": w.ids["M"], "date": DAY},
            ),
        )
        assert r.status_code == 404
    finally:
        await wipe_tenant(company_id=c_company, user_id=c_user)
        await _teardown(w)


async def test_obs_hra01_calculate_range_enforces_scope_and_never_widens(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    w = await _world(client)
    other_headers, other_company, other_user = await _register_tenant(client)
    foreign_emp = (await _build_wired_employee(client, other_headers))["employee"]["id"]
    body = {"date_from": DAY, "date_to": DAY}
    try:
        for scope, caller, visible in SCOPES:
            headers = await _custom(w, [ATTENDANCE_RECOMPUTE], scope, w.ids[caller])
            visible_ids = {w.ids[k] for k in visible}
            with patch.object(
                attendance_tasks.calculate_range, "delay", return_value=SimpleNamespace(id="j")
            ) as delay:
                # omitted employee_ids: narrowed to the visible set, never the whole company
                r = await client.post(
                    "/v1/attendance/days/calculate-range", headers=headers, json=body
                )
                assert r.status_code == 202, (scope, r.text)
                queued = delay.call_args.args[3]
                if scope == "COMPANY":
                    assert queued is None  # legitimate company-wide behaviour preserved
                else:
                    assert set(queued) == visible_ids, (scope, queued)
                    assert r.json()["data"]["employee_ids"] is not None
                delay.reset_mock()

                # explicit list entirely inside scope
                inside = sorted(visible_ids)
                r = await client.post(
                    "/v1/attendance/days/calculate-range",
                    headers=headers,
                    json={**body, "employee_ids": inside},
                )
                assert r.status_code == 202, r.text
                assert set(delay.call_args.args[3]) == visible_ids
                delay.reset_mock()

                # one out-of-scope id (or another tenant's, or unknown) rejects the whole request
                outside = [w.ids[k] for k in ALL if k not in visible]
                for bad in [*outside, foreign_emp, str(uuid4())] if scope != "COMPANY" else []:
                    before = await fingerprint(w.company_id)
                    r = await client.post(
                        "/v1/attendance/days/calculate-range",
                        headers=headers,
                        json={**body, "employee_ids": [*inside, bad]},
                    )
                    assert r.status_code == 404, (scope, bad, r.text)
                    assert await fingerprint(w.company_id) == before
                    assert delay.call_count == 0  # nothing enqueued
        # caller with no linked employee below COMPANY sees nobody -> rejected, nothing queued
        headers = await _custom(w, [ATTENDANCE_RECOMPUTE], "SELF", None)
        with patch.object(attendance_tasks.calculate_range, "delay") as delay:
            r = await client.post("/v1/attendance/days/calculate-range", headers=headers, json=body)
            assert r.status_code == 404
            assert delay.call_count == 0
        # no success audit for the denials: only the accepted calls were audited
        assert (
            await audit_count(w.company_id, "ATTENDANCE_RANGE_CALCULATION_QUEUED")
            == len(SCOPES) * 2
        )
    finally:
        await wipe_tenant(company_id=other_company, user_id=other_user)
        await _teardown(w)


async def test_obs_hra01_keep_leave_enforces_scope_with_a_real_leave_conflict(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Real synthetic conflict: an APPROVED full-day leave and punches on the same day, so the
    day is `work_on_leave_flagged` and keep-leave is a genuine mutation (it sets the resolution)."""
    w = await _world(client)
    try:
        days = await _day_ids(client, w.headers)
        for emp in w.ids.values():
            await _sync(client, w.headers, employee_id=emp, fraction="1.00", is_paid=True)
            r = await client.post(
                "/v1/attendance/days/calculate",
                headers=w.headers,
                params={"employee_id": emp, "date": DAY},
            )
            assert r.json()["data"]["work_on_leave_flagged"] is True, r.text
            assert r.json()["data"]["work_on_leave_resolution"] is None

        reason = {"reason": "B12 scope test"}
        denied_total = 0
        for scope, caller, visible in SCOPES:
            headers = await _custom(w, [ATTENDANCE_RECOMPUTE], scope, w.ids[caller])
            for key in ALL - visible:
                before = await fingerprint(w.company_id)
                r = await client.post(
                    f"/v1/attendance/days/{days[w.ids[key]]}/work-on-leave/keep-leave",
                    headers=headers,
                    json=reason,
                )
                assert r.status_code == 404, (scope, key, r.text)
                assert await fingerprint(w.company_id) == before
                denied_total += 1
                resolution = await scalar(
                    w.company_id,
                    "SELECT work_on_leave_resolution FROM attendance_day "
                    "WHERE company_id = :cid AND id = :d",
                    d=UUID(days[w.ids[key]]),
                )
                assert resolution is None
        assert (
            denied_total > 0
            and await audit_count(w.company_id, "ATTENDANCE_WORK_ON_LEAVE_RESOLVED") == 0
        )

        # in scope: succeeds, mutates exactly that day, one audit event each
        resolved = 0
        for scope, caller, visible in SCOPES[:4]:  # SELF, REPORTEES, TREE, BRANCH
            headers = await _custom(w, [ATTENDANCE_RECOMPUTE], scope, w.ids[caller])
            for key in sorted(visible):
                row = await scalar(
                    w.company_id,
                    "SELECT work_on_leave_resolution FROM attendance_day "
                    "WHERE company_id = :cid AND id = :d",
                    d=UUID(days[w.ids[key]]),
                )
                if row is not None:
                    continue  # already resolved by an earlier, wider scope in this loop
                r = await client.post(
                    f"/v1/attendance/days/{days[w.ids[key]]}/work-on-leave/keep-leave",
                    headers=headers,
                    json=reason,
                )
                assert r.status_code == 200, (scope, key, r.text)
                assert r.json()["data"]["work_on_leave_resolution"] == "KEEP_LEAVE"
                resolved += 1
        # COMPANY control resolves whatever is left (S)
        headers = await _custom(w, [ATTENDANCE_RECOMPUTE], "COMPANY", w.ids["M"])
        r = await client.post(
            f"/v1/attendance/days/{days[w.ids['S']]}/work-on-leave/keep-leave",
            headers=headers,
            json=reason,
        )
        assert r.status_code == 200, r.text
        resolved += 1
        assert resolved == 4
        assert await audit_count(w.company_id, "ATTENDANCE_WORK_ON_LEAVE_RESOLVED") == resolved
    finally:
        await _cleanup_leave_projection(company_id=w.company_id)
        await _teardown(w)
