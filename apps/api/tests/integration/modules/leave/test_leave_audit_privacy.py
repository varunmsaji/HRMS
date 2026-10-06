"""Decision 19 - free text a person typed into a leave record (medical reasons, comments,
attachment names) is never copied into the immutable audit log. Audit entries carry structure only,
from an explicit allow-list, and record the correct before and after state."""

import json
from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.modules.leave.test_leave_application import (
    _cleanup,
    _register_tenant,
    _setup_full,
    _submit,
    _teardown,
)

from hrms.core.db.session import get_session_factory, set_rls_company_id
from hrms.modules.leave.schemas import LEAVE_APPLICATION_AUDIT_FIELDS

pytestmark = pytest.mark.asyncio

_MARKERS = (
    "SECRET-REASON",
    "SECRET-ATTACHMENT",
    "SECRET-REVIEW",
    "SECRET-REJECT",
    "SECRET-CANCEL",
    "SECRET-ADJUST",
    "SECRET-ENCASH",
)


async def _audit_rows(company_id: UUID, application_ids: list[str]) -> list[dict[str, Any]]:
    async with get_session_factory()() as session:
        await set_rls_company_id(session, str(company_id))
        rows = await session.execute(
            text(
                "SELECT action, entity_type, entity_id, before_json, after_json, request_id "
                "FROM audit_log WHERE company_id = CAST(:c AS uuid) ORDER BY occurred_at"
            ),
            {"c": str(company_id)},
        )
        return [dict(r._mapping) for r in rows]


async def test_free_text_is_never_written_to_the_audit_log(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(
            client, headers, approval_chain="HR", balance="30.00", encashment_allowed=True
        )
        employee_id, leave_type_id = ctx["employee"]["id"], ctx["leave_type"]["id"]

        def day(n: int) -> dict[str, str]:
            return {"start_date": f"2026-09-{n:02d}", "end_date": f"2026-09-{n:02d}"}

        submitted = []
        for n in (8, 9, 10):
            response = await _submit(
                client,
                headers,
                employee_id=employee_id,
                leave_type_id=leave_type_id,
                reason="SECRET-REASON surgery",
                attachment_reference="SECRET-ATTACHMENT-medical-cert.pdf",
                expected_delivery_date="2026-11-01",
                **day(n),
            )
            assert response.status_code == 201, response.text
            submitted.append(response.json()["data"])
        approve_me, reject_me, cancel_me = submitted

        approved = await client.post(
            f"/v1/leave-applications/{approve_me['id']}/approve",
            headers={**headers, "If-Match": str(approve_me["version"])},
            json={"reviewer_comment": "SECRET-REVIEW ok"},
        )
        assert approved.status_code == 200, approved.text
        rejected = await client.post(
            f"/v1/leave-applications/{reject_me['id']}/reject",
            headers={**headers, "If-Match": str(reject_me["version"])},
            json={"reviewer_comment": "SECRET-REVIEW no", "rejection_reason": "SECRET-REJECT"},
        )
        assert rejected.status_code == 200, rejected.text
        cancelled = await client.post(
            f"/v1/leave-applications/{cancel_me['id']}/cancel",
            headers={**headers, "If-Match": str(cancel_me["version"])},
            json={"reason": "SECRET-CANCEL changed plans"},
        )
        assert cancelled.status_code == 200, cancelled.text
        adjusted = await client.post(
            "/v1/leave-ledger/adjustments",
            headers=headers,
            json={
                "employee_id": employee_id,
                "leave_type_id": leave_type_id,
                "amount": "1.00",
                "effective_date": "2026-09-08",
                "reason": "SECRET-ADJUST correction",
            },
        )
        assert adjusted.status_code == 201, adjusted.text
        encashed = await client.post(
            "/v1/leave-ledger/encashments",
            headers=headers,
            json={
                "employee_id": employee_id,
                "leave_type_id": leave_type_id,
                "days": "1.00",
                "effective_date": "2026-09-08",
                "reason": "SECRET-ENCASH",
            },
        )
        assert encashed.status_code == 201, encashed.text

        rows = await _audit_rows(company_id, [a["id"] for a in submitted])
        leave_rows = [r for r in rows if r["entity_type"] in ("leave_application", "leave_ledger")]
        assert len(leave_rows) >= 8
        dumped = json.dumps([[r["before_json"], r["after_json"]] for r in leave_rows], default=str)
        for marker in _MARKERS:
            assert marker not in dumped, f"{marker} reached the audit log"
        assert "surgery" not in dumped
        assert "2026-11-01" not in dumped  # expected_delivery_date

        # application entries carry exactly the allow-listed structure
        for row in leave_rows:
            if row["entity_type"] == "leave_application":
                for payload in (row["before_json"], row["after_json"]):
                    if payload is not None:
                        assert set(payload) <= set(LEAVE_APPLICATION_AUDIT_FIELDS) | {
                            "stage",
                            "approver_employee_id",
                        }
            else:
                for payload in (row["before_json"], row["after_json"]):
                    if payload is not None:
                        assert "reason" not in payload
                        assert "entry_type" in payload and "amount" in payload

        # the correct before/after states are recorded (the before-state used to show the
        # post-update row for reject and cancel)
        by_action: dict[str, list[dict[str, Any]]] = {}
        for row in leave_rows:
            by_action.setdefault(row["action"], []).append(row)
        rejected_row = next(
            r for r in by_action["LEAVE_APPLICATION_REJECTED"] if r["entity_id"] is not None
        )
        assert rejected_row["before_json"]["status"] == "SUBMITTED"
        assert rejected_row["after_json"]["status"] == "REJECTED"
        cancelled_row = by_action["LEAVE_APPLICATION_CANCELLED"][0]
        assert cancelled_row["before_json"]["status"] == "SUBMITTED"
        assert cancelled_row["after_json"]["status"] == "CANCELLED"
        assert cancelled_row["request_id"]
        assert by_action["LEAVE_APPLICATION_SUBMITTED"][0]["after_json"]["status"] == "SUBMITTED"

        # ... while the business records themselves still hold the text (it is not lost)
        fetched = await client.get(f"/v1/leave-applications/{approve_me['id']}", headers=headers)
        assert fetched.json()["data"]["reason"] == "SECRET-REASON surgery"
        ledger = await client.get(
            "/v1/leave-ledger", headers=headers, params={"employee_id": employee_id}
        )
        assert any(e["reason"] == "SECRET-ADJUST correction" for e in ledger.json()["data"])
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)


async def test_a_stale_conflict_does_not_echo_free_text_either(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        ctx = await _setup_full(client, headers, approval_chain="HR")
        submitted = (
            await _submit(
                client,
                headers,
                employee_id=ctx["employee"]["id"],
                leave_type_id=ctx["leave_type"]["id"],
                reason="SECRET-REASON surgery",
            )
        ).json()["data"]
        stale = await client.post(
            f"/v1/leave-applications/{submitted['id']}/reject",
            headers={**headers, "If-Match": "99"},
            json={"rejection_reason": "x"},
        )
        assert stale.status_code == 409, stale.text
        assert "SECRET-REASON" not in stale.text
    finally:
        await _teardown(company_id=company_id)
        await _cleanup(company_id=company_id, user_id=user_id)
