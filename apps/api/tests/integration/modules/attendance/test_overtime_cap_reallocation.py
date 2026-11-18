"""Independent pre-commit review R-4, R-5, R-6 and R-7 (16 Nov 2026), through the real API.

* R-4 - when an earlier day's overtime changes, the weekly and monthly caps are re-allocated across
  a month boundary: a week that spans two months, and the later days of the second month whose
  monthly budget read the days that moved.
* R-5 - an HR approval (full or partial) or rejection frees or takes budget just as a calculation
  does, so the later days of the week and month are re-allocated in the same request.
* R-6 - the sibling-day pass runs only when the overtime policy has a weekly or monthly cap.
* R-7 - a policy version change re-pricing a decided record is audited as `POLICY_VERSION_CHANGED`,
  not `CAPPED`.

Default day: 09:00-18:00 shift, OUT at 19:00 = 60 minutes of overtime. 2026-08-31 is a Monday, so
31 Aug - 6 Sep is one week across two months.
"""

import json
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from tests.integration.modules.attendance.test_attendance_day import (
    _build_wired_employee,
    _register_tenant,
)
from tests.integration.modules.attendance.test_attendance_rules_remediation import (
    MON,
    TUE,
    WED,
    _calc,
    _cleanup_all,
    _records,
    _stored,
    _work,
)
from tests.integration.modules.attendance.test_attendance_security import (
    _create_permission_scoped_user,
)
from tests.integration.modules.attendance.test_overtime_record import _create_overtime_policy
from tests.integration.modules.attendance.test_regularization import _create_regularization_policy
from tests.integration.modules.attendance.test_shift_window import _sql

from hrms.modules.attendance import recalc
from hrms.modules.attendance.permissions import ATTENDANCE_OVERTIME_APPROVE

pytestmark = pytest.mark.asyncio

AUG31, SEP1, SEP2, SEP7, SEP8 = "2026-08-31", "2026-09-01", "2026-09-02", "2026-09-07", "2026-09-08"


async def _approved_map(
    client: AsyncClient, headers: dict[str, str], employee_id: str, first: str, last: str
) -> dict[str, int]:
    records = await _records(client, headers, employee_id, first, last)
    return {d: r["minutes_approved"] for d, r in sorted(records.items()) if r["minutes_approved"]}


async def _detected_map(
    client: AsyncClient, headers: dict[str, str], employee_id: str, first: str, last: str
) -> dict[str, int]:
    records = await _records(client, headers, employee_id, first, last)
    return {d: r["minutes_detected"] for d, r in sorted(records.items()) if r["minutes_detected"]}


async def _correct_out_to_six(
    client: AsyncClient, headers: dict[str, str], employee_id: str, day: str
) -> None:
    corrected = await client.post(
        "/v1/regularizations",
        headers=headers,
        json={
            "employee_id": employee_id,
            "attendance_date": day,
            "request_type": "WRONG_PUNCH",
            "reason": "Wrong OUT time",
            "requested_punches": [{"direction": "OUT", "requested_time": f"{day}T18:00:00Z"}],
        },
    )
    assert corrected.status_code == 201, corrected.text


async def _employee(client: AsyncClient, headers: dict[str, str], **policy: Any) -> str:
    employee_id = str((await _build_wired_employee(client, headers))["employee"]["id"])
    await _create_overtime_policy(client, headers, **policy)
    await _create_regularization_policy(client, headers, approval_chain="AUTO")
    return employee_id


# --- R-4: across the month boundary --------------------------------------------------------------


async def test_r4_a_correction_reallocates_a_week_that_spans_two_months_and_the_next_month(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Weekly cap 90, monthly cap 100. September's budget is spent by the 1st (30), the 7th (60)
    and, partly, the 8th (10). Correcting Monday 31 Aug to no overtime frees the week's budget:
    1 and 2 Sep take 60 + 30, which leaves only 10 for the 7th and none for the 8th. The 7th and
    8th are in the *next* week and the days of the next month the review (R-4) said were missed."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = await _employee(
            client, headers, approval_chain="AUTO", weekly_cap_minutes=90, monthly_cap_minutes=100
        )
        for day in (AUG31, SEP1, SEP2, SEP7, SEP8):
            await _work(client, headers, employee_id, day)
            await _calc(client, headers, employee_id, day)
        before = await _approved_map(client, headers, employee_id, AUG31, SEP8)
        assert before == {AUG31: 60, SEP1: 30, SEP7: 60, SEP8: 10}

        await _correct_out_to_six(client, headers, employee_id, AUG31)

        after = await _approved_map(client, headers, employee_id, AUG31, SEP8)
        assert after == {SEP1: 60, SEP2: 30, SEP7: 10}
        # The stored days agree with their overtime records.
        for day, minutes in {SEP1: 60, SEP2: 30, SEP7: 10, SEP8: 0}.items():
            assert (await _stored(client, headers, employee_id, day))["ot_minutes_approved"] == (
                minutes
            )
    finally:
        await _cleanup_all(company_id, user_id)


async def test_r4_a_weekly_cap_alone_still_reaches_the_days_of_the_week_in_the_next_month(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = await _employee(client, headers, approval_chain="AUTO", weekly_cap_minutes=90)
        for day in (AUG31, SEP1, SEP2):
            await _work(client, headers, employee_id, day)
            await _calc(client, headers, employee_id, day)
        assert await _approved_map(client, headers, employee_id, AUG31, SEP2) == {
            AUG31: 60,
            SEP1: 30,
        }
        await _correct_out_to_six(client, headers, employee_id, AUG31)
        assert await _approved_map(client, headers, employee_id, AUG31, SEP2) == {
            SEP1: 60,
            SEP2: 30,
        }
    finally:
        await _cleanup_all(company_id, user_id)


# --- R-5: HR decisions --------------------------------------------------------------------------


async def _hr(company_id: UUID) -> dict[str, str]:
    headers, _ = await _create_permission_scoped_user(
        company_id=company_id,
        permission_codes=[ATTENDANCE_OVERTIME_APPROVE],
        data_scope="COMPANY",
        caller_employee_id=None,
    )
    return headers


async def _pending_week(
    client: AsyncClient, headers: dict[str, str], employee_id: str
) -> dict[str, Any]:
    """Weekly cap 90 with human approval: Monday holds 60 detected, Tuesday 30, Wednesday none."""
    for day in (MON, TUE, WED):
        await _work(client, headers, employee_id, day)
        await _calc(client, headers, employee_id, day)
    assert await _detected_map(client, headers, employee_id, MON, WED) == {MON: 60, TUE: 30}
    records = await _records(client, headers, employee_id, MON, MON)
    return dict(records[MON])


async def test_r5_a_partial_approval_hands_the_freed_budget_to_later_days(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = await _employee(client, headers, approval_chain="HR", weekly_cap_minutes=90)
        monday = await _pending_week(client, headers, employee_id)
        hr = await _hr(company_id)

        approved = await client.post(
            f"/v1/overtime/{monday['id']}/approve",
            headers={**hr, "If-Match": str(monday["version"])},
            json={"minutes_approved": 30, "reviewer_comment": "Only the first half hour"},
        )
        assert approved.status_code == 200, approved.text
        assert approved.json()["data"]["minutes_approved"] == 30

        # Monday now uses 30 of the 90, so Tuesday can detect 60; that spends the 90 (Wednesday: 0).
        assert await _detected_map(client, headers, employee_id, MON, WED) == {MON: 60, TUE: 60}
        assert (await _stored(client, headers, employee_id, TUE))["ot_minutes_detected"] == 60
        assert (await _stored(client, headers, employee_id, WED))["ot_minutes_detected"] == 0
    finally:
        await _cleanup_all(company_id, user_id)


async def test_r5_a_rejection_hands_the_freed_budget_to_later_days(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = await _employee(client, headers, approval_chain="HR", weekly_cap_minutes=90)
        monday = await _pending_week(client, headers, employee_id)
        hr = await _hr(company_id)

        rejected = await client.post(
            f"/v1/overtime/{monday['id']}/reject",
            headers={**hr, "If-Match": str(monday["version"])},
            json={"reviewer_comment": "Not authorised", "rejection_reason": "No prior approval"},
        )
        assert rejected.status_code == 200, rejected.text

        assert await _detected_map(client, headers, employee_id, MON, WED) == {
            MON: 60,
            TUE: 60,
            WED: 30,
        }
        assert (await _stored(client, headers, employee_id, MON))["ot_minutes_approved"] == 0
    finally:
        await _cleanup_all(company_id, user_id)


async def test_r5_a_full_approval_changes_nothing_downstream(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Approving everything that was detected leaves the budget as it was reserved: Tuesday and
    Wednesday are not touched."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = await _employee(client, headers, approval_chain="HR", weekly_cap_minutes=90)
        monday = await _pending_week(client, headers, employee_id)
        hr = await _hr(company_id)
        calculated_before = (await _stored(client, headers, employee_id, TUE))["calculated_at"]

        approved = await client.post(
            f"/v1/overtime/{monday['id']}/approve",
            headers={**hr, "If-Match": str(monday["version"])},
            json={},
        )
        assert approved.status_code == 200, approved.text

        assert await _detected_map(client, headers, employee_id, MON, WED) == {MON: 60, TUE: 30}
        assert (await _stored(client, headers, employee_id, TUE))["calculated_at"] == (
            calculated_before
        )
    finally:
        await _cleanup_all(company_id, user_id)


# --- R-6: only when a cap is configured ----------------------------------------------------------


async def test_r6_without_a_cap_a_change_does_not_recalculate_the_sibling_days(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = await _employee(client, headers, approval_chain="AUTO")
        for day in (MON, TUE, WED):
            await _work(client, headers, employee_id, day)
            await _calc(client, headers, employee_id, day)
        calculated = {
            d: (await _stored(client, headers, employee_id, d))["calculated_at"] for d in (TUE, WED)
        }

        await _correct_out_to_six(client, headers, employee_id, MON)

        assert (await _stored(client, headers, employee_id, MON))["ot_minutes_approved"] == 0
        for day in (TUE, WED):
            stored = await _stored(client, headers, employee_id, day)
            assert stored["calculated_at"] == calculated[day], f"{day} was recalculated"
            assert stored["ot_minutes_approved"] == 60
    finally:
        await _cleanup_all(company_id, user_id)


async def test_r6_with_a_cap_the_same_change_does_recalculate_them(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """The control for the test above: the cap is what makes the siblings depend on Monday."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = await _employee(client, headers, approval_chain="AUTO", weekly_cap_minutes=90)
        for day in (MON, TUE, WED):
            await _work(client, headers, employee_id, day)
            await _calc(client, headers, employee_id, day)
        tuesday_before = (await _stored(client, headers, employee_id, TUE))["calculated_at"]

        await _correct_out_to_six(client, headers, employee_id, MON)

        assert (await _stored(client, headers, employee_id, TUE))["calculated_at"] != (
            tuesday_before
        )
    finally:
        await _cleanup_all(company_id, user_id)


# --- R-7: the audit outcome of a policy version change -------------------------------------------


async def _supersede_outcomes(company_id: UUID) -> list[str]:
    rows = await _sql(
        company_id,
        "SELECT comment FROM overtime_action WHERE company_id = :cid "
        "AND action = 'SUPERSEDED_BY_RECALCULATION' ORDER BY created_at",
    )
    return [json.loads(r[0])["outcome"] for r in rows]


async def test_r7_a_policy_version_change_is_not_recorded_as_capped(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = str((await _build_wired_employee(client, headers))["employee"]["id"])
        policy = await _create_overtime_policy(client, headers, approval_chain="HR")
        await _work(client, headers, employee_id, MON)
        await _calc(client, headers, employee_id, MON)
        record = (await _records(client, headers, employee_id, MON, MON))[MON]
        hr = await _hr(company_id)
        approved = await client.post(
            f"/v1/overtime/{record['id']}/approve",
            headers={**hr, "If-Match": str(record["version"])},
            json={},
        )
        assert approved.status_code == 200, approved.text
        assert await _supersede_outcomes(company_id) == []

        # Republish: the same minutes, a new policy version.
        draft = await client.post(
            f"/v1/overtime-policies/{policy['id']}/versions",
            headers=headers,
            json={
                "effective_from": MON,
                "eligibility": "ALWAYS",
                "min_ot_minutes": 0,
                "approval_chain": "HR",
                "requires_post_approval": True,
            },
        )
        assert draft.status_code == 201, draft.text
        versions = (
            await client.get(f"/v1/overtime-policies/{policy['id']}/versions", headers=headers)
        ).json()["data"]
        current = next(v for v in versions if v["status"] == "PUBLISHED")
        published = await client.post(
            f"/v1/overtime-policies/{policy['id']}/versions/{draft.json()['data']['id']}/publish",
            headers={**headers, "If-Match": "1"},
            json={"expected_previous_version": current["version"]},
        )
        assert published.status_code == 200, published.text
        await recalc.process_company_requests(company_id)

        after = (await _records(client, headers, employee_id, MON, MON))[MON]
        assert after["status"] == "APPROVED" and after["minutes_approved"] == 60
        assert after["overtime_policy_version_id"] != record["overtime_policy_version_id"]
        assert await _supersede_outcomes(company_id) == ["POLICY_VERSION_CHANGED"]
    finally:
        await _cleanup_all(company_id, user_id)


async def test_r7_a_real_cap_is_still_recorded_as_capped(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Approved 60, then the day is corrected to 30 minutes: the approval is cut back, `CAPPED`."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = str((await _build_wired_employee(client, headers))["employee"]["id"])
        await _create_overtime_policy(client, headers, approval_chain="HR")
        await _create_regularization_policy(client, headers, approval_chain="AUTO")
        await _work(client, headers, employee_id, MON)
        await _calc(client, headers, employee_id, MON)
        record = (await _records(client, headers, employee_id, MON, MON))[MON]
        hr = await _hr(company_id)
        approved = await client.post(
            f"/v1/overtime/{record['id']}/approve",
            headers={**hr, "If-Match": str(record["version"])},
            json={},
        )
        assert approved.status_code == 200, approved.text

        corrected = await client.post(
            "/v1/regularizations",
            headers=headers,
            json={
                "employee_id": employee_id,
                "attendance_date": MON,
                "request_type": "WRONG_PUNCH",
                "reason": "Wrong OUT time",
                "requested_punches": [{"direction": "OUT", "requested_time": f"{MON}T18:30:00Z"}],
            },
        )
        assert corrected.status_code == 201, corrected.text

        after = (await _records(client, headers, employee_id, MON, MON))[MON]
        assert after["minutes_approved"] == 30
        assert await _supersede_outcomes(company_id) == ["CAPPED"]
    finally:
        await _cleanup_all(company_id, user_id)


async def test_r7_a_correction_that_keeps_the_approval_is_recorded_as_detection_updated(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Detected 60, HR approves 30. The day is corrected to 45 detected minutes: the approval
    (30) is untouched and the policy version did not move, so only the detected figure changed.
    It is neither `CAPPED` (nothing was cut) nor `POLICY_VERSION_CHANGED`."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        employee_id = str((await _build_wired_employee(client, headers))["employee"]["id"])
        await _create_overtime_policy(client, headers, approval_chain="HR")
        await _create_regularization_policy(client, headers, approval_chain="AUTO")
        await _work(client, headers, employee_id, MON)
        await _calc(client, headers, employee_id, MON)
        record = (await _records(client, headers, employee_id, MON, MON))[MON]
        assert record["minutes_detected"] == 60
        hr = await _hr(company_id)
        approved = await client.post(
            f"/v1/overtime/{record['id']}/approve",
            headers={**hr, "If-Match": str(record["version"])},
            json={"minutes_approved": 30, "reviewer_comment": "Only the first half hour"},
        )
        assert approved.status_code == 200, approved.text
        assert await _supersede_outcomes(company_id) == []

        corrected = await client.post(
            "/v1/regularizations",
            headers=headers,
            json={
                "employee_id": employee_id,
                "attendance_date": MON,
                "request_type": "WRONG_PUNCH",
                "reason": "Wrong OUT time",
                "requested_punches": [{"direction": "OUT", "requested_time": f"{MON}T18:45:00Z"}],
            },
        )
        assert corrected.status_code == 201, corrected.text

        after = (await _records(client, headers, employee_id, MON, MON))[MON]
        assert after["minutes_detected"] == 45
        assert after["minutes_approved"] == 30 and after["status"] == "APPROVED"
        assert after["overtime_policy_version_id"] == record["overtime_policy_version_id"]
        assert await _supersede_outcomes(company_id) == ["DETECTION_UPDATED"]
    finally:
        await _cleanup_all(company_id, user_id)
