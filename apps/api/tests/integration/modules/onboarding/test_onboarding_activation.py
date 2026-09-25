"""Integration tests for the Onboarding module's O7 slice —
`POST /onboarding-cases/{id}/activate`, the transaction that turns a fully-verified case into a
real `Employee`/`Employment`/`Assignment`(/`Bank`/`Statutory`) row graph.

Covers: the happy path (verified via the real employee-module read endpoints, not just the
onboarding response), rejection when not yet `VERIFIED`, rejection when `legal_entity_id` was
never set, the `AssignmentFieldsRequiredError` bubbling through unmodified when branch/
department/designation were never set on the case, permission gating, double-activation
rejection, and cross-tenant isolation."""

from typing import Any
from uuid import UUID

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from hrms.core.db.session import get_session_factory

from .test_onboarding_case import (
    _case_payload,
    _cleanup_scoped_users,
    _create_permission_scoped_user,
    _register_tenant,
    _teardown,
)
from .test_onboarding_public import _cleanup_tokens, _issue_token
from .test_onboarding_review import _cleanup_section_reviews
from .test_onboarding_submit import _fill_all_sections

pytestmark = pytest.mark.asyncio


async def _create_case(
    client: AsyncClient, headers: dict[str, str], **overrides: Any
) -> dict[str, Any]:
    response = await client.post(
        "/v1/onboarding-cases", headers=headers, json=_case_payload(**overrides)
    )
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _create_legal_entity(
    client: AsyncClient, headers: dict[str, str], name: str = "Acme Legal Entity"
) -> dict[str, Any]:
    response = await client.post("/v1/legal-entities", headers=headers, json={"name": name})
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _create_branch(
    client: AsyncClient, headers: dict[str, str], legal_entity_id: str, name: str = "HQ Branch"
) -> dict[str, Any]:
    response = await client.post(
        "/v1/branches", headers=headers, json={"legal_entity_id": legal_entity_id, "name": name}
    )
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _create_department(
    client: AsyncClient, headers: dict[str, str], name: str = "Engineering", **extra: Any
) -> dict[str, Any]:
    response = await client.post("/v1/departments", headers=headers, json={"name": name, **extra})
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


async def _create_designation(
    client: AsyncClient, headers: dict[str, str], title: str = "Software Engineer", **extra: Any
) -> dict[str, Any]:
    response = await client.post(
        "/v1/designations", headers=headers, json={"title": title, **extra}
    )
    assert response.status_code == 201, response.text
    return dict(response.json()["data"])


def _review_url(case_id: str, section: str) -> str:
    return f"/v1/onboarding-cases/{case_id}/sections/{section}/review"


_ALL_SECTIONS = [
    "personal_info",
    "address_info",
    "emergency_contact",
    "bank_info",
    "statutory_info",
    "compensation_info",
    "previous_employment_info",
    "education_info",
    "nominee_info",
]


async def _verified_case(
    client: AsyncClient, headers: dict[str, str], company_id: UUID, *, with_org: bool
) -> dict[str, Any]:
    """Creates a case (optionally with full org context — legal entity/branch/department/
    designation), fills and submits every section, then has HR verify all five, which
    auto-transitions the case to `VERIFIED` (O6) since there are no documents to also require."""
    overrides: dict[str, Any] = {}
    if with_org:
        legal_entity = await _create_legal_entity(client, headers)
        branch = await _create_branch(client, headers, legal_entity_id=legal_entity["id"])
        department = await _create_department(client, headers, branch_id=branch["id"])
        designation = await _create_designation(client, headers, department_id=department["id"])
        overrides = {
            "branch_id": branch["id"],
            "department_id": department["id"],
            "designation_id": designation["id"],
        }

    case = await _create_case(client, headers, **overrides)
    token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))
    await _fill_all_sections(client, token)
    submit = await client.post(f"/v1/public/onboarding/{token}/submit")
    assert submit.status_code == 200, submit.text

    for section in _ALL_SECTIONS:
        response = await client.post(
            _review_url(case["id"], section), headers=headers, json={"status": "VERIFIED"}
        )
        assert response.status_code == 200, response.text

    return case


async def _cleanup_employee_graph(*, company_id: UUID) -> None:
    factory = get_session_factory()
    async with factory() as session:
        # FK-safe order: onboarding_case/account_invite (reference employee) -> bank/statutory/
        # assignment -> employment (references employee, legal_entity) -> employee (references
        # number_series) -> designation/department/branch (references legal_entity/company).
        # `account_invite` row added by activation's now-integrated invite-issuance
        # (`onboarding/service.py` -> `AccountInviteService.issue_for_employee`) — without
        # deleting it first, `DELETE FROM employee` below fails on
        # `account_invite_employee_id_fkey`.
        await session.execute(
            text("DELETE FROM onboarding_case WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.execute(
            text("DELETE FROM account_invite WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.execute(
            text("DELETE FROM employee_bank WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.execute(
            text("DELETE FROM employee_statutory WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        # E-02 part 3 (market-parity onboarding-data pass) — activation now creates a real
        # `employee_compensation` row via the newly-wired `compensation_info` section; without
        # deleting it first, `DELETE FROM employee` below fails on
        # `employee_compensation_employee_id_fkey`.
        await session.execute(
            text("DELETE FROM employee_compensation WHERE company_id = :cid"),
            {"cid": str(company_id)},
        )
        # Market-parity onboarding-data pass part 4 — same FK reasoning as
        # `employee_compensation` above, for the new `employee_experience` table.
        await session.execute(
            text("DELETE FROM employee_experience WHERE company_id = :cid"),
            {"cid": str(company_id)},
        )
        # Market-parity onboarding-data pass part 5 — same FK reasoning, for `employee_education`.
        await session.execute(
            text("DELETE FROM employee_education WHERE company_id = :cid"),
            {"cid": str(company_id)},
        )
        # Market-parity onboarding-data pass part 6 — same FK reasoning, for `employee_dependent`.
        await session.execute(
            text("DELETE FROM employee_dependent WHERE company_id = :cid"),
            {"cid": str(company_id)},
        )
        await session.execute(
            text("DELETE FROM employee_assignment WHERE company_id = :cid"),
            {"cid": str(company_id)},
        )
        await session.execute(
            text("DELETE FROM employment WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.execute(
            text("DELETE FROM employee WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.execute(
            text("DELETE FROM number_series WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.execute(
            text("DELETE FROM designation WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.execute(
            text("DELETE FROM department WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.execute(
            text("DELETE FROM branch WHERE company_id = :cid"), {"cid": str(company_id)}
        )
        await session.commit()


async def _full_teardown(*, company_id: UUID, user_id: UUID | None) -> None:
    await _cleanup_section_reviews(company_id=company_id)
    await _cleanup_tokens(company_id=company_id)
    await _cleanup_employee_graph(company_id=company_id)
    await _teardown(company_id=company_id, user_id=user_id)


async def test_activate_success_creates_full_employee_graph(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _verified_case(client, headers, company_id, with_org=True)

        response = await client.post(f"/v1/onboarding-cases/{case['id']}/activate", headers=headers)
        assert response.status_code == 200, response.text
        data = response.json()["data"]
        assert data["status"] == "ACTIVATED"
        employee_id = data["employee_id"]
        assert employee_id

        employee = (await client.get(f"/v1/employees/{employee_id}", headers=headers)).json()[
            "data"
        ]
        assert employee["first_name"] == "Asha"
        assert employee["personal_email"] == case["personal_email"]
        # E-02 part 2 — `address_info`/`emergency_contact` (filled by `_fill_all_sections` above:
        # city="Bengaluru", contact_name="Raj", phone="9876543210") must now actually land on the
        # activated Employee row; before this change, activation silently dropped both sections.
        assert employee["present_city"] == "Bengaluru"
        assert employee["permanent_same_as_present"] is True
        assert employee["emergency_contact_name"] == "Raj"
        assert employee["emergency_contact_phone"] == "9876543210"

        employments = (
            await client.get(f"/v1/employees/{employee_id}/employments", headers=headers)
        ).json()["data"]
        assert len(employments) == 1
        assert employments[0]["legal_entity_id"] == case["legal_entity_id"]
        assert employments[0]["joining_date"] == case["proposed_joining_date"]

        assignments = (
            await client.get(f"/v1/employees/{employee_id}/assignments", headers=headers)
        ).json()["data"]
        assert len(assignments) == 1
        assert assignments[0]["change_type"] == "INITIAL"
        assert assignments[0]["branch_id"] == case["branch_id"]
        assert assignments[0]["department_id"] == case["department_id"]
        assert assignments[0]["designation_id"] == case["designation_id"]

        banks = (await client.get(f"/v1/employees/{employee_id}/bank", headers=headers)).json()[
            "data"
        ]
        assert len(banks) == 1
        assert banks[0]["payment_mode"] == "BANK"

        statutories = (
            await client.get(f"/v1/employees/{employee_id}/statutory", headers=headers)
        ).json()["data"]
        assert len(statutories) == 1
        assert statutories[0]["tax_regime"] == "NEW"

        # E-02 part 3 — closes the gap `OnboardingActivationService`'s own docstring named:
        # Compensation was listed among the services composed here, but no call was ever wired
        # up; before this change, no `EmployeeCompensation` row could ever exist post-activation.
        compensations = (
            await client.get(f"/v1/employees/{employee_id}/compensation", headers=headers)
        ).json()["data"]
        assert len(compensations) == 1
        assert compensations[0]["annual_ctc_minor"] == 60000000
        assert compensations[0]["currency"] == "INR"
        assert compensations[0]["revision_type"] == "JOINING"
    finally:
        await _full_teardown(company_id=company_id, user_id=user_id)


async def test_activate_decrypts_bank_info_and_reencrypts_for_employee_bank(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """DATA-01 (`docs/audits/DATA_01_PII_ENCRYPTION_IMPLEMENTATION_PLAN.md` §9) — the
    decrypt-then-re-encrypt handoff at activation: the plaintext account number the candidate
    submitted during onboarding must survive intact through encrypted staging
    (`onboarding_case.bank_info`) -> decrypt -> re-encrypt into
    `employee_bank.account_number_enc` under a *different* ciphertext (a new AAD, bound to the
    new `employee_bank` row's own id, plan §2.4)."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        legal_entity = await _create_legal_entity(client, headers)
        branch = await _create_branch(client, headers, legal_entity_id=legal_entity["id"])
        department = await _create_department(client, headers, branch_id=branch["id"])
        designation = await _create_designation(client, headers, department_id=department["id"])
        case = await _create_case(
            client,
            headers,
            branch_id=branch["id"],
            department_id=department["id"],
            designation_id=designation["id"],
        )
        token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))
        account_number = "1122334455"

        await client.patch(
            f"/v1/public/onboarding/{token}/sections/personal_info", json={"first_name": "Asha"}
        )
        await client.patch(
            f"/v1/public/onboarding/{token}/sections/address_info", json={"city": "Bengaluru"}
        )
        await client.patch(
            f"/v1/public/onboarding/{token}/sections/emergency_contact",
            json={"contact_name": "Raj", "phone": "9876543210"},
        )
        bank_response = await client.patch(
            f"/v1/public/onboarding/{token}/sections/bank_info",
            json={
                "payment_mode": "BANK",
                "account_number_enc": account_number,
                "bank_name": "State Bank",
            },
        )
        assert bank_response.status_code == 200, bank_response.text
        # Candidate read-back must decrypt correctly, immediately after submission.
        assert bank_response.json()["data"]["bank_info"]["account_number_enc"] == account_number
        await client.patch(
            f"/v1/public/onboarding/{token}/sections/statutory_info",
            json={
                "is_pf_applicable": False,
                "is_esi_applicable": False,
                "is_lwf_applicable": False,
                "tax_regime": "NEW",
            },
        )
        await client.patch(
            f"/v1/public/onboarding/{token}/sections/compensation_info",
            json={"annual_ctc_minor": 60000000, "currency": "INR"},
        )
        await client.patch(
            f"/v1/public/onboarding/{token}/sections/previous_employment_info",
            json={"items": []},
        )
        await client.patch(
            f"/v1/public/onboarding/{token}/sections/education_info",
            json={"items": []},
        )
        await client.patch(
            f"/v1/public/onboarding/{token}/sections/nominee_info",
            json={"items": []},
        )
        submit = await client.post(f"/v1/public/onboarding/{token}/submit")
        assert submit.status_code == 200, submit.text

        for section in _ALL_SECTIONS:
            review = await client.post(
                _review_url(case["id"], section), headers=headers, json={"status": "VERIFIED"}
            )
            assert review.status_code == 200, review.text

        # HR case-detail read-back must also decrypt correctly.
        detail = await client.get(f"/v1/onboarding-cases/{case['id']}", headers=headers)
        assert detail.json()["data"]["bank_info"]["account_number_enc"] == account_number

        # Raw DB check — onboarding_case.bank_info holds ciphertext, never the plaintext.
        factory = get_session_factory()
        async with factory() as session:
            case_row = (
                (
                    await session.execute(
                        text(
                            "SELECT bank_info ->> 'account_number_enc' AS enc "
                            "FROM onboarding_case WHERE id = :cid"
                        ),
                        {"cid": case["id"]},
                    )
                )
                .mappings()
                .first()
            )
        assert case_row is not None
        assert case_row["enc"] != account_number
        assert case_row["enc"].startswith("v1:")

        activate = await client.post(f"/v1/onboarding-cases/{case['id']}/activate", headers=headers)
        assert activate.status_code == 200, activate.text
        employee_id = activate.json()["data"]["employee_id"]

        banks = (await client.get(f"/v1/employees/{employee_id}/bank", headers=headers)).json()[
            "data"
        ]
        assert len(banks) == 1
        assert banks[0]["account_number_enc"] == account_number

        # Raw DB check on the real employee_bank row: encrypted at rest, and under a DIFFERENT
        # ciphertext than the onboarding staging copy (different AAD — different record id).
        async with factory() as session:
            bank_row = (
                (
                    await session.execute(
                        text(
                            "SELECT account_number_enc FROM employee_bank WHERE employee_id = :eid"
                        ),
                        {"eid": employee_id},
                    )
                )
                .mappings()
                .first()
            )
        assert bank_row is not None
        assert bank_row["account_number_enc"] != account_number
        assert bank_row["account_number_enc"].startswith("v1:")
        assert bank_row["account_number_enc"] != case_row["enc"]
    finally:
        await _full_teardown(company_id=company_id, user_id=user_id)


async def test_activate_persists_pan_aadhaar_uan_and_fathers_name(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """E-02 (market-parity onboarding-data pass) — PAN/Aadhaar (case-level ciphertext, decrypted
    and re-encrypted under the employee's own AAD) and UAN/father's-or-husband's-name (plain)
    must land on the activated `Employee` row, readable back via the new identity sub-resource."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        legal_entity = await _create_legal_entity(client, headers)
        branch = await _create_branch(client, headers, legal_entity_id=legal_entity["id"])
        department = await _create_department(client, headers, branch_id=branch["id"])
        designation = await _create_designation(client, headers, department_id=department["id"])
        case = await _create_case(
            client,
            headers,
            branch_id=branch["id"],
            department_id=department["id"],
            designation_id=designation["id"],
        )
        token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))

        pan = "ABCDE1234F"
        aadhaar = "123456789012"
        await client.patch(
            f"/v1/public/onboarding/{token}/sections/personal_info",
            json={
                "first_name": "Asha",
                "father_or_husband_name": "Ram Rao",
                "pan_number_enc": pan,
                "aadhaar_number_enc": aadhaar,
            },
        )
        await client.patch(
            f"/v1/public/onboarding/{token}/sections/address_info", json={"city": "Bengaluru"}
        )
        await client.patch(
            f"/v1/public/onboarding/{token}/sections/emergency_contact",
            json={"contact_name": "Raj", "phone": "9876543210"},
        )
        await client.patch(
            f"/v1/public/onboarding/{token}/sections/bank_info",
            json={"payment_mode": "CASH"},
        )
        await client.patch(
            f"/v1/public/onboarding/{token}/sections/statutory_info",
            json={
                "is_pf_applicable": False,
                "is_esi_applicable": False,
                "is_lwf_applicable": False,
                "tax_regime": "NEW",
                "uan_number": "100200300400",
            },
        )
        await client.patch(
            f"/v1/public/onboarding/{token}/sections/compensation_info",
            json={"annual_ctc_minor": 60000000, "currency": "INR"},
        )
        await client.patch(
            f"/v1/public/onboarding/{token}/sections/previous_employment_info",
            json={"items": []},
        )
        await client.patch(
            f"/v1/public/onboarding/{token}/sections/education_info",
            json={"items": []},
        )
        await client.patch(
            f"/v1/public/onboarding/{token}/sections/nominee_info",
            json={"items": []},
        )
        submit = await client.post(f"/v1/public/onboarding/{token}/submit")
        assert submit.status_code == 200, submit.text

        for section in _ALL_SECTIONS:
            review = await client.post(
                _review_url(case["id"], section), headers=headers, json={"status": "VERIFIED"}
            )
            assert review.status_code == 200, review.text

        # Raw DB check — the staging column holds ciphertext, never the plaintext PAN/Aadhaar.
        factory = get_session_factory()
        async with factory() as session:
            case_row = (
                (
                    await session.execute(
                        text(
                            "SELECT personal_info ->> 'pan_number_enc' AS pan, "
                            "personal_info ->> 'aadhaar_number_enc' AS aadhaar "
                            "FROM onboarding_case WHERE id = :cid"
                        ),
                        {"cid": case["id"]},
                    )
                )
                .mappings()
                .first()
            )
        assert case_row is not None
        assert case_row["pan"] != pan
        assert case_row["pan"].startswith("v1:")
        assert case_row["aadhaar"] != aadhaar
        assert case_row["aadhaar"].startswith("v1:")

        activate = await client.post(f"/v1/onboarding-cases/{case['id']}/activate", headers=headers)
        assert activate.status_code == 200, activate.text
        employee_id = activate.json()["data"]["employee_id"]

        employee = (await client.get(f"/v1/employees/{employee_id}", headers=headers)).json()[
            "data"
        ]
        assert employee["father_or_husband_name"] == "Ram Rao"

        identity = (
            await client.get(f"/v1/employees/{employee_id}/identity", headers=headers)
        ).json()["data"]
        assert identity["pan_number"] == pan
        assert identity["aadhaar_number"] == aadhaar
        assert identity["uan_number"] == "100200300400"
        assert identity["father_or_husband_name"] == "Ram Rao"

        # Raw DB check on the real employee row: encrypted at rest, under a DIFFERENT ciphertext
        # than the onboarding staging copy (different AAD — different record id).
        async with factory() as session:
            employee_row = (
                (
                    await session.execute(
                        text(
                            "SELECT pan_number_enc, aadhaar_number_enc "
                            "FROM employee WHERE id = :eid"
                        ),
                        {"eid": employee_id},
                    )
                )
                .mappings()
                .first()
            )
        assert employee_row is not None
        assert employee_row["pan_number_enc"].startswith("v1:")
        assert employee_row["pan_number_enc"] != case_row["pan"]
        assert employee_row["aadhaar_number_enc"].startswith("v1:")
        assert employee_row["aadhaar_number_enc"] != case_row["aadhaar"]
    finally:
        await _full_teardown(company_id=company_id, user_id=user_id)


async def test_activate_persists_distinct_permanent_address(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """E-02 part 2 — when `permanent_same_as_present=False`, the candidate's distinct permanent
    address block must land on `Employee.permanent_*`, not just the present-address block."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        legal_entity = await _create_legal_entity(client, headers)
        branch = await _create_branch(client, headers, legal_entity_id=legal_entity["id"])
        department = await _create_department(client, headers, branch_id=branch["id"])
        designation = await _create_designation(client, headers, department_id=department["id"])
        case = await _create_case(
            client,
            headers,
            branch_id=branch["id"],
            department_id=department["id"],
            designation_id=designation["id"],
        )
        token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))

        await client.patch(
            f"/v1/public/onboarding/{token}/sections/personal_info", json={"first_name": "Asha"}
        )
        await client.patch(
            f"/v1/public/onboarding/{token}/sections/address_info",
            json={
                "city": "Bengaluru",
                "permanent_same_as_present": False,
                "permanent_city": "Mysuru",
                "permanent_pincode": "570001",
            },
        )
        await client.patch(
            f"/v1/public/onboarding/{token}/sections/emergency_contact",
            json={"contact_name": "Raj", "phone": "9876543210"},
        )
        await client.patch(
            f"/v1/public/onboarding/{token}/sections/bank_info", json={"payment_mode": "CASH"}
        )
        await client.patch(
            f"/v1/public/onboarding/{token}/sections/statutory_info",
            json={
                "is_pf_applicable": False,
                "is_esi_applicable": False,
                "is_lwf_applicable": False,
                "tax_regime": "NEW",
            },
        )
        await client.patch(
            f"/v1/public/onboarding/{token}/sections/compensation_info",
            json={"annual_ctc_minor": 60000000, "currency": "INR"},
        )
        await client.patch(
            f"/v1/public/onboarding/{token}/sections/previous_employment_info",
            json={"items": []},
        )
        await client.patch(
            f"/v1/public/onboarding/{token}/sections/education_info",
            json={"items": []},
        )
        await client.patch(
            f"/v1/public/onboarding/{token}/sections/nominee_info",
            json={"items": []},
        )
        submit = await client.post(f"/v1/public/onboarding/{token}/submit")
        assert submit.status_code == 200, submit.text

        for section in _ALL_SECTIONS:
            review = await client.post(
                _review_url(case["id"], section), headers=headers, json={"status": "VERIFIED"}
            )
            assert review.status_code == 200, review.text

        activate = await client.post(f"/v1/onboarding-cases/{case['id']}/activate", headers=headers)
        assert activate.status_code == 200, activate.text
        employee_id = activate.json()["data"]["employee_id"]

        employee = (await client.get(f"/v1/employees/{employee_id}", headers=headers)).json()[
            "data"
        ]
        assert employee["present_city"] == "Bengaluru"
        assert employee["permanent_same_as_present"] is False
        assert employee["permanent_city"] == "Mysuru"
        assert employee["permanent_pincode"] == "570001"
    finally:
        await _full_teardown(company_id=company_id, user_id=user_id)


async def test_activate_creates_one_experience_row_per_previous_employer(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Market-parity onboarding-data pass, part 4 — EPF Form 11's continuity block. Covers
    zero, one, and many previous employers in a single case to exercise the loop boundary."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        legal_entity = await _create_legal_entity(client, headers)
        branch = await _create_branch(client, headers, legal_entity_id=legal_entity["id"])
        department = await _create_department(client, headers, branch_id=branch["id"])
        designation = await _create_designation(client, headers, department_id=department["id"])
        case = await _create_case(
            client,
            headers,
            branch_id=branch["id"],
            department_id=department["id"],
            designation_id=designation["id"],
        )
        token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))

        await client.patch(
            f"/v1/public/onboarding/{token}/sections/personal_info", json={"first_name": "Asha"}
        )
        await client.patch(
            f"/v1/public/onboarding/{token}/sections/address_info", json={"city": "Bengaluru"}
        )
        await client.patch(
            f"/v1/public/onboarding/{token}/sections/emergency_contact",
            json={"contact_name": "Raj", "phone": "9876543210"},
        )
        await client.patch(
            f"/v1/public/onboarding/{token}/sections/bank_info", json={"payment_mode": "CASH"}
        )
        await client.patch(
            f"/v1/public/onboarding/{token}/sections/statutory_info",
            json={
                "is_pf_applicable": False,
                "is_esi_applicable": False,
                "is_lwf_applicable": False,
                "tax_regime": "NEW",
            },
        )
        await client.patch(
            f"/v1/public/onboarding/{token}/sections/compensation_info",
            json={"annual_ctc_minor": 60000000, "currency": "INR"},
        )
        previous_employment = await client.patch(
            f"/v1/public/onboarding/{token}/sections/previous_employment_info",
            json={
                "items": [
                    {
                        "company_name": "Acme Corp",
                        "designation": "Software Engineer",
                        "from_date": "2020-01-15",
                        "to_date": "2022-06-30",
                        "last_ctc_minor": 90000000,
                        "reason_for_leaving": "Career growth",
                        "had_prior_pf_membership": True,
                        "previous_uan": "100200300400",
                        "previous_pf_account_number": "KA/BGE/1234567/000/0001234",
                        "previous_esi_ip_number": "1234567890",
                    },
                    {
                        "company_name": "Globex Inc",
                        "designation": "Senior Engineer",
                        "from_date": "2022-07-01",
                        "to_date": "2026-09-30",
                        "had_prior_pf_membership": False,
                    },
                ]
            },
        )
        assert previous_employment.status_code == 200, previous_employment.text
        await client.patch(
            f"/v1/public/onboarding/{token}/sections/education_info",
            json={"items": []},
        )
        await client.patch(
            f"/v1/public/onboarding/{token}/sections/nominee_info",
            json={"items": []},
        )
        submit = await client.post(f"/v1/public/onboarding/{token}/submit")
        assert submit.status_code == 200, submit.text

        for section in _ALL_SECTIONS:
            review = await client.post(
                _review_url(case["id"], section), headers=headers, json={"status": "VERIFIED"}
            )
            assert review.status_code == 200, review.text

        activate = await client.post(f"/v1/onboarding-cases/{case['id']}/activate", headers=headers)
        assert activate.status_code == 200, activate.text
        employee_id = activate.json()["data"]["employee_id"]

        experiences = (
            await client.get(f"/v1/employees/{employee_id}/experience", headers=headers)
        ).json()["data"]
        assert len(experiences) == 2
        by_company = {e["company_name"]: e for e in experiences}
        assert by_company["Acme Corp"]["designation"] == "Software Engineer"
        assert by_company["Acme Corp"]["previous_uan"] == "100200300400"
        assert by_company["Acme Corp"]["had_prior_pf_membership"] is True
        assert by_company["Acme Corp"]["last_ctc_minor"] == 90000000
        assert by_company["Globex Inc"]["had_prior_pf_membership"] is False
        assert by_company["Globex Inc"]["previous_uan"] is None
    finally:
        await _full_teardown(company_id=company_id, user_id=user_id)


async def test_activate_creates_one_education_row_per_qualification(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Market-parity onboarding-data pass, part 5 — qualifications feed `employee_education`
    the same way previous employers feed `employee_experience`."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        legal_entity = await _create_legal_entity(client, headers)
        branch = await _create_branch(client, headers, legal_entity_id=legal_entity["id"])
        department = await _create_department(client, headers, branch_id=branch["id"])
        designation = await _create_designation(client, headers, department_id=department["id"])
        case = await _create_case(
            client,
            headers,
            branch_id=branch["id"],
            department_id=department["id"],
            designation_id=designation["id"],
        )
        token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))

        await client.patch(
            f"/v1/public/onboarding/{token}/sections/personal_info", json={"first_name": "Asha"}
        )
        await client.patch(
            f"/v1/public/onboarding/{token}/sections/address_info", json={"city": "Bengaluru"}
        )
        await client.patch(
            f"/v1/public/onboarding/{token}/sections/emergency_contact",
            json={"contact_name": "Raj", "phone": "9876543210"},
        )
        await client.patch(
            f"/v1/public/onboarding/{token}/sections/bank_info", json={"payment_mode": "CASH"}
        )
        await client.patch(
            f"/v1/public/onboarding/{token}/sections/statutory_info",
            json={
                "is_pf_applicable": False,
                "is_esi_applicable": False,
                "is_lwf_applicable": False,
                "tax_regime": "NEW",
            },
        )
        await client.patch(
            f"/v1/public/onboarding/{token}/sections/compensation_info",
            json={"annual_ctc_minor": 60000000, "currency": "INR"},
        )
        await client.patch(
            f"/v1/public/onboarding/{token}/sections/previous_employment_info",
            json={"items": []},
        )
        education = await client.patch(
            f"/v1/public/onboarding/{token}/sections/education_info",
            json={
                "items": [
                    {
                        "qualification": "B.Tech Computer Science",
                        "institution_name": "IIT Bombay",
                        "year_of_passing": 2019,
                    },
                    {
                        "qualification": "M.Tech Data Science",
                        "institution_name": "IIT Bombay",
                        "year_of_passing": 2021,
                    },
                ]
            },
        )
        assert education.status_code == 200, education.text
        await client.patch(
            f"/v1/public/onboarding/{token}/sections/nominee_info",
            json={"items": []},
        )
        submit = await client.post(f"/v1/public/onboarding/{token}/submit")
        assert submit.status_code == 200, submit.text

        for section in _ALL_SECTIONS:
            review = await client.post(
                _review_url(case["id"], section), headers=headers, json={"status": "VERIFIED"}
            )
            assert review.status_code == 200, review.text

        activate = await client.post(f"/v1/onboarding-cases/{case['id']}/activate", headers=headers)
        assert activate.status_code == 200, activate.text
        employee_id = activate.json()["data"]["employee_id"]

        education_rows = (
            await client.get(f"/v1/employees/{employee_id}/education", headers=headers)
        ).json()["data"]
        assert len(education_rows) == 2
        by_qualification = {e["qualification"]: e for e in education_rows}
        assert by_qualification["B.Tech Computer Science"]["institution_name"] == "IIT Bombay"
        assert by_qualification["B.Tech Computer Science"]["year_of_passing"] == 2019
        assert by_qualification["M.Tech Data Science"]["year_of_passing"] == 2021
    finally:
        await _full_teardown(company_id=company_id, user_id=user_id)


async def test_activate_creates_one_dependent_row_per_nominee(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Market-parity onboarding-data pass, part 6 — nominees/family members feed
    `employee_dependent` the same way qualifications feed `employee_education`. Also verifies
    the DATA-01 decrypt-then-re-encrypt handoff for each nominee's Aadhaar, and that the minor/
    guardian block and both nominee-scheme percentages survive activation intact."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        legal_entity = await _create_legal_entity(client, headers)
        branch = await _create_branch(client, headers, legal_entity_id=legal_entity["id"])
        department = await _create_department(client, headers, branch_id=branch["id"])
        designation = await _create_designation(client, headers, department_id=department["id"])
        case = await _create_case(
            client,
            headers,
            branch_id=branch["id"],
            department_id=department["id"],
            designation_id=designation["id"],
        )
        token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))

        await client.patch(
            f"/v1/public/onboarding/{token}/sections/personal_info", json={"first_name": "Asha"}
        )
        await client.patch(
            f"/v1/public/onboarding/{token}/sections/address_info", json={"city": "Bengaluru"}
        )
        await client.patch(
            f"/v1/public/onboarding/{token}/sections/emergency_contact",
            json={"contact_name": "Raj", "phone": "9876543210"},
        )
        await client.patch(
            f"/v1/public/onboarding/{token}/sections/bank_info", json={"payment_mode": "CASH"}
        )
        await client.patch(
            f"/v1/public/onboarding/{token}/sections/statutory_info",
            json={
                "is_pf_applicable": False,
                "is_esi_applicable": False,
                "is_lwf_applicable": False,
                "tax_regime": "NEW",
            },
        )
        await client.patch(
            f"/v1/public/onboarding/{token}/sections/compensation_info",
            json={"annual_ctc_minor": 60000000, "currency": "INR"},
        )
        await client.patch(
            f"/v1/public/onboarding/{token}/sections/previous_employment_info",
            json={"items": []},
        )
        await client.patch(
            f"/v1/public/onboarding/{token}/sections/education_info",
            json={"items": []},
        )
        nominee = await client.patch(
            f"/v1/public/onboarding/{token}/sections/nominee_info",
            json={
                "items": [
                    {
                        "full_name": "Sunita Rao",
                        "relationship": "SPOUSE",
                        "aadhaar_number_enc": "234567890123",
                        "is_pf_nominee": True,
                        "pf_nominee_share_percentage": 60,
                        "is_gratuity_nominee": True,
                        "gratuity_nominee_share_percentage": 100,
                        "is_esi_dependent": True,
                    },
                    {
                        "full_name": "Arjun Rao",
                        "relationship": "SON",
                        "is_minor": True,
                        "guardian_name": "Sunita Rao",
                        "guardian_relationship": "MOTHER",
                        "is_pf_nominee": True,
                        "pf_nominee_share_percentage": 40,
                    },
                ]
            },
        )
        assert nominee.status_code == 200, nominee.text
        # Candidate read-back must decrypt correctly, immediately after submission.
        assert nominee.json()["data"]["nominee_info"]["items"][0]["aadhaar_number_enc"] == (
            "234567890123"
        )
        submit = await client.post(f"/v1/public/onboarding/{token}/submit")
        assert submit.status_code == 200, submit.text

        for section in _ALL_SECTIONS:
            review = await client.post(
                _review_url(case["id"], section), headers=headers, json={"status": "VERIFIED"}
            )
            assert review.status_code == 200, review.text

        activate = await client.post(f"/v1/onboarding-cases/{case['id']}/activate", headers=headers)
        assert activate.status_code == 200, activate.text
        employee_id = activate.json()["data"]["employee_id"]

        dependents = (
            await client.get(f"/v1/employees/{employee_id}/dependents", headers=headers)
        ).json()["data"]
        assert len(dependents) == 2
        by_name = {d["full_name"]: d for d in dependents}
        # Re-encrypted under the new `employee_dependent` row's own AAD, then decrypted back here.
        assert by_name["Sunita Rao"]["aadhaar_number_enc"] == "234567890123"
        assert by_name["Sunita Rao"]["is_pf_nominee"] is True
        assert by_name["Sunita Rao"]["pf_nominee_share_percentage"] == 60
        assert by_name["Sunita Rao"]["is_gratuity_nominee"] is True
        assert by_name["Sunita Rao"]["gratuity_nominee_share_percentage"] == 100
        assert by_name["Sunita Rao"]["is_esi_dependent"] is True
        assert by_name["Arjun Rao"]["is_minor"] is True
        assert by_name["Arjun Rao"]["guardian_name"] == "Sunita Rao"
        assert by_name["Arjun Rao"]["aadhaar_number_enc"] is None
    finally:
        await _full_teardown(company_id=company_id, user_id=user_id)


async def test_activate_not_verified_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _create_case(client, headers)

        response = await client.post(f"/v1/onboarding-cases/{case['id']}/activate", headers=headers)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "ONBOARDING_CASE_NOT_READY_FOR_ACTIVATION"
    finally:
        await _full_teardown(company_id=company_id, user_id=user_id)


async def test_activate_without_legal_entity_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _verified_case(client, headers, company_id, with_org=False)

        response = await client.post(f"/v1/onboarding-cases/{case['id']}/activate", headers=headers)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "ONBOARDING_CASE_MISSING_LEGAL_ENTITY"
    finally:
        await _full_teardown(company_id=company_id, user_id=user_id)


async def test_activate_without_placement_fields_bubbles_assignment_error(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        legal_entity = await _create_legal_entity(client, headers)
        branch = await _create_branch(client, headers, legal_entity_id=legal_entity["id"])
        # branch_id derives the case's legal_entity_id automatically (single-legal-entity
        # product rule), but department_id/designation_id are still unset — the assignment
        # creation at activation should still reject on those.
        case = await _create_case(client, headers, branch_id=branch["id"])
        token = await _issue_token(company_id=company_id, case_id=UUID(case["id"]))
        await _fill_all_sections(client, token)
        await client.post(f"/v1/public/onboarding/{token}/submit")
        for section in _ALL_SECTIONS:
            await client.post(
                _review_url(case["id"], section), headers=headers, json={"status": "VERIFIED"}
            )

        response = await client.post(f"/v1/onboarding-cases/{case['id']}/activate", headers=headers)
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "ASSIGNMENT_FIELDS_REQUIRED"
    finally:
        await _full_teardown(company_id=company_id, user_id=user_id)


async def test_activate_without_permission_rejected(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    from hrms.modules.onboarding.permissions import ONBOARDING_REVIEW

    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _verified_case(client, headers, company_id, with_org=True)
        scoped_headers, _scoped_user_id = await _create_permission_scoped_user(
            company_id=company_id, permission_codes=[ONBOARDING_REVIEW]
        )

        response = await client.post(
            f"/v1/onboarding-cases/{case['id']}/activate", headers=scoped_headers
        )
        assert response.status_code == 403
        assert response.json()["error"]["code"] == "PERMISSION_DENIED"
    finally:
        await _full_teardown(company_id=company_id, user_id=user_id)
        await _cleanup_scoped_users()


async def test_activate_twice_rejected(client: AsyncClient, seeded_plan_catalogue: None) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _verified_case(client, headers, company_id, with_org=True)

        first = await client.post(f"/v1/onboarding-cases/{case['id']}/activate", headers=headers)
        assert first.status_code == 200

        second = await client.post(f"/v1/onboarding-cases/{case['id']}/activate", headers=headers)
        assert second.status_code == 409
        assert second.json()["error"]["code"] == "ONBOARDING_CASE_NOT_READY_FOR_ACTIVATION"
    finally:
        await _full_teardown(company_id=company_id, user_id=user_id)


async def test_activate_cross_tenant_isolation(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers_a, company_id_a, user_id_a = await _register_tenant(client)
    headers_b, company_id_b, user_id_b = await _register_tenant(client)
    try:
        case_a = await _verified_case(client, headers_a, company_id_a, with_org=True)

        response = await client.post(
            f"/v1/onboarding-cases/{case_a['id']}/activate", headers=headers_b
        )
        assert response.status_code == 404
    finally:
        await _full_teardown(company_id=company_id_a, user_id=user_id_a)
        await _full_teardown(company_id=company_id_b, user_id=user_id_b)
