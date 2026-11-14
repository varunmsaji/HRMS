"""B12 regression suite - DEF-B11-02 (concurrent onboarding activation) and DEF-B11-04
(email / outbox consistency).

The invariant under test is a DATABASE invariant, not "one response was 200": after any number of
concurrent or repeated activations of one VERIFIED case, the tenant holds exactly the rows one
activation creates (employee, employment, assignment, bank, statutory, one live
account invite, one activation audit event) and exactly the two emails that activation owns - each
counted straight from the tables.

Email: the dev/test sender is `LoggingEmailSender`, which records every delivery attempt in
`email_log` and contacts nothing. `email_log` is therefore the observable "deliverable message"
ledger: a row exists only if delivery was actually attempted.
"""

import asyncio
from typing import Any
from uuid import UUID

import pytest
from entrypoints.api import app
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from hrms.core.audit.service import AuditService
from hrms.core.config.settings import get_settings
from hrms.core.db.post_commit import run_post_commit
from hrms.core.db.session import set_rls_company_id
from hrms.core.tenancy.context import TenantContext, set_tenant
from hrms.modules.onboarding.exceptions import OnboardingCaseNotReadyForActivationError
from hrms.modules.onboarding.service import OnboardingActivationService

from ...b12_support import audit_count, fingerprint, scalar
from .test_onboarding_activation import _full_teardown, _verified_case
from .test_onboarding_case import _register_tenant

pytestmark = pytest.mark.asyncio

_GRAPH = {
    "employee": "employee",
    "employment": "employment",
    "assignment": "employee_assignment",
    "bank": "employee_bank",
    "statutory": "employee_statutory",
    "compensation": "employee_compensation",
    "invite": "account_invite",
}


async def graph(company_id: UUID) -> dict[str, int]:
    out = {
        name: int(await scalar(company_id, f"SELECT count(*) FROM {table} WHERE company_id=:cid"))
        for name, table in _GRAPH.items()
    }
    out["audit_activated"] = await audit_count(company_id, "ONBOARDING_CASE_ACTIVATED")
    out["mail_activation"] = int(
        await scalar(
            company_id,
            "SELECT count(*) FROM email_log "
            "WHERE company_id=:cid AND kind='onboarding.activate_case'",
        )
    )
    out["mail_account_invite"] = int(
        await scalar(
            company_id,
            "SELECT count(*) FROM email_log WHERE company_id=:cid AND kind='account_invite._issue'",
        )
    )
    return out


ONE = {
    "employee": 1,
    "employment": 1,
    "assignment": 1,
    "bank": 1,
    "statutory": 1,
    "compensation": 0,  # pay is set by HR afterwards, never from the candidate
    "invite": 1,
    "audit_activated": 1,
    "mail_activation": 1,
    "mail_account_invite": 1,
}
NONE = dict.fromkeys(ONE, 0)


def _times(n: int) -> dict[str, int]:
    return {k: v * n for k, v in ONE.items()}


async def _case_row(company_id: UUID, case_id: str) -> tuple[str, UUID | None]:
    factory = async_sessionmaker(create_async_engine(get_settings().database_url))
    async with factory() as session:
        await set_rls_company_id(session, str(company_id))
        from sqlalchemy import text

        row = (
            await session.execute(
                text(
                    "SELECT status, employee_id FROM onboarding_case WHERE id=:i AND company_id=:c"
                ),
                {"i": case_id, "c": str(company_id)},
            )
        ).one()
    return row[0], row[1]


def _activate(client: AsyncClient, headers: dict[str, str], case_id: str):  # type: ignore[no-untyped-def]
    return client.post(f"/v1/onboarding-cases/{case_id}/activate", headers=headers)


async def test_sequential_activation_creates_exactly_one_graph(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _verified_case(client, headers, company_id, with_org=True)
        assert await graph(company_id) == NONE
        r = await _activate(client, headers, case["id"])
        assert r.status_code == 200, r.text
        assert await graph(company_id) == ONE
        status, employee_id = await _case_row(company_id, case["id"])
        assert status == "ACTIVATED" and str(employee_id) == r.json()["data"]["employee_id"]
    finally:
        await _full_teardown(company_id=company_id, user_id=user_id)


async def test_repeated_activation_is_refused_and_changes_nothing(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _verified_case(client, headers, company_id, with_org=True)
        assert (await _activate(client, headers, case["id"])).status_code == 200
        settled = await fingerprint(company_id)
        for _ in range(3):
            again = await _activate(client, headers, case["id"])
            assert again.status_code == 409, again.text
            assert again.json()["error"]["code"] == "ONBOARDING_CASE_NOT_READY_FOR_ACTIVATION"
        assert await graph(company_id) == ONE
        assert await fingerprint(company_id) == settled  # no row, audit event, invite or email
    finally:
        await _full_teardown(company_id=company_id, user_id=user_id)


async def test_def_b11_02_eight_concurrent_activations_have_exactly_one_winner(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _verified_case(client, headers, company_id, with_org=True)
        results = await asyncio.gather(*[_activate(client, headers, case["id"]) for _ in range(8)])
        codes = sorted(r.status_code for r in results)
        assert codes == [200] + [409] * 7, [(r.status_code, r.text[:120]) for r in results]
        for loser in (r for r in results if r.status_code == 409):
            assert loser.json()["error"]["code"] == "ONBOARDING_CASE_NOT_READY_FOR_ACTIVATION"
        winner = next(r for r in results if r.status_code == 200)
        # the database holds exactly one graph - not eight
        assert await graph(company_id) == ONE
        status, employee_id = await _case_row(company_id, case["id"])
        assert status == "ACTIVATED" and str(employee_id) == winner.json()["data"]["employee_id"]
        # and a later replay is still a no-op
        before = await fingerprint(company_id)
        assert (await _activate(client, headers, case["id"])).status_code == 409
        assert await fingerprint(company_id) == before
    finally:
        await _full_teardown(company_id=company_id, user_id=user_id)


async def test_def_b11_02_two_independent_connection_pools_share_one_winner(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    """Two separate engines (separate connection pools, as two worker processes would have) race
    the service directly. The lock lives in Postgres, so the outcome must be the same."""
    headers, company_id, user_id = await _register_tenant(client)
    engines = [create_async_engine(get_settings().database_url) for _ in range(2)]
    try:
        case = await _verified_case(client, headers, company_id, with_org=True)

        async def attempt(engine: Any) -> str:
            set_tenant(TenantContext(company_id=company_id, user_id=user_id))  # per-task context
            factory = async_sessionmaker(engine, expire_on_commit=False)
            async with factory() as session:
                await set_rls_company_id(session, str(company_id))
                try:
                    await OnboardingActivationService(session).activate_case(
                        company_id, UUID(case["id"]), actor_user_id=user_id
                    )
                    await session.commit()
                except OnboardingCaseNotReadyForActivationError:
                    await session.rollback()
                    return "refused"
                await run_post_commit(session)
                return "activated"

        outcomes = await asyncio.gather(*[attempt(e) for e in engines for _ in range(3)])
        assert sorted(outcomes) == ["activated"] + ["refused"] * 5
        assert await graph(company_id) == ONE
    finally:
        for e in engines:
            await e.dispose()
        await _full_teardown(company_id=company_id, user_id=user_id)


async def test_concurrent_activations_of_separate_cases_all_succeed_independently(
    client: AsyncClient, seeded_plan_catalogue: None
) -> None:
    headers, company_id, user_id = await _register_tenant(client)
    try:
        cases = [await _verified_case(client, headers, company_id, with_org=True) for _ in range(3)]
        # three requests per case, all nine at once
        results = await asyncio.gather(
            *[_activate(client, headers, c["id"]) for c in cases for _ in range(3)]
        )
        by_case: dict[str, list[int]] = {}
        for c, group in zip(cases, (results[i : i + 3] for i in range(0, 9, 3)), strict=True):
            by_case[c["id"]] = sorted(r.status_code for r in group)
        assert all(v == [200, 409, 409] for v in by_case.values()), by_case
        assert await graph(company_id) == _times(3)
        employees = {(await _case_row(company_id, c["id"]))[1] for c in cases}
        assert len(employees) == 3  # three distinct employees
    finally:
        await _full_teardown(company_id=company_id, user_id=user_id)


# --------------------------------------------------------------------------------------------
# Failure during activation, then retry - DEF-B11-02 (atomicity) and DEF-B11-04 (no stray email)
# --------------------------------------------------------------------------------------------


def _failing_transport() -> ASGITransport:
    return ASGITransport(app=app, raise_app_exceptions=False)


async def test_failure_during_activation_rolls_back_everything_including_emails_then_retry_works(
    client: AsyncClient, seeded_plan_catalogue: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """DEF-B11-04 reproduction: the final audit write fails AFTER the activation email and the
    account-invite email were prepared. Nothing may survive - no employee graph, no invite row,
    and above all no email record (nothing was handed to the delivery layer)."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _verified_case(client, headers, company_id, with_org=True)
        real_record = AuditService.record
        armed = {"on": True}

        async def flaky(self: AuditService, session: Any, **kw: Any) -> None:
            if armed["on"] and kw.get("action") == "ONBOARDING_CASE_ACTIVATED":
                raise RuntimeError("injected audit failure")
            await real_record(self, session, **kw)

        monkeypatch.setattr(AuditService, "record", flaky)
        before = await fingerprint(company_id)
        async with AsyncClient(transport=_failing_transport(), base_url="http://test") as c:
            failed = await _activate(c, headers, case["id"])
        assert failed.status_code == 500
        assert (
            await graph(company_id) == NONE
        )  # includes mail_activation == mail_account_invite == 0
        assert await fingerprint(company_id) == before
        assert (await _case_row(company_id, case["id"]))[0] == "VERIFIED"

        # retry succeeds exactly once, with exactly one of each email
        armed["on"] = False
        retry = await _activate(client, headers, case["id"])
        assert retry.status_code == 200, retry.text
        assert await graph(company_id) == ONE
        assert (await _activate(client, headers, case["id"])).status_code == 409
        assert await graph(company_id) == ONE
    finally:
        await _full_teardown(company_id=company_id, user_id=user_id)


async def test_invite_savepoint_rollback_drops_only_the_invite_email(
    client: AsyncClient, seeded_plan_catalogue: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The account-invite auto-issue runs in a SAVEPOINT. When it fails after its email was
    prepared, the invite and its email vanish with the SAVEPOINT while the activation - and its own
    notice - commit."""
    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _verified_case(client, headers, company_id, with_org=True)
        real_record = AuditService.record

        async def flaky(self: AuditService, session: Any, **kw: Any) -> None:
            if kw.get("action") == "ACCOUNT_INVITE_ISSUED":
                raise RuntimeError("injected invite audit failure")
            await real_record(self, session, **kw)

        monkeypatch.setattr(AuditService, "record", flaky)
        r = await _activate(client, headers, case["id"])
        assert r.status_code == 200, r.text
        assert await graph(company_id) == {**ONE, "invite": 0, "mail_account_invite": 0}
    finally:
        await _full_teardown(company_id=company_id, user_id=user_id)
