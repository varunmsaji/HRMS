"""B13 Workstream A - the transactional e-mail outbox (`onboarding/email_outbox.py`).

Everything here uses synthetic senders (`Recorder`) or the logging provider; nothing contacts a mail
server. Dispatch is `none` unless a test says otherwise, so the window between "committed" and
"delivered" is held open and every step is driven explicitly - the way a crash or a slow worker
looks from the database.

Time is simulated by moving `next_attempt_at` / `locked_until` into the past with SQL (never by
sleeping through a 30 s backoff).
"""

import asyncio
import json
import time
from typing import Any
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from tests.integration.b12_support import audit_count, run_proc, scalar

from hrms.core.config.settings import Settings, get_settings
from hrms.core.db.post_commit import run_post_commit
from hrms.core.db.session import get_session_factory, session_scope
from hrms.modules.onboarding import email_outbox as ob
from hrms.modules.onboarding.email_sender import (
    EmailDeliveryError,
    queue_email_after_commit,
)

pytestmark = [pytest.mark.asyncio, pytest.mark.usefixtures("seeded_plan_catalogue")]

DOMAIN = "@b13.test"


# ------------------------------------------------------------------------------------- helpers


class Recorder:
    """Synthetic sender. `script` is consumed one entry per call: None = accept, an exception =
    raise it. Once the script is exhausted every call is accepted."""

    def __init__(self, script: list[BaseException | None] | None = None) -> None:
        self.script = list(script or [])
        self.calls: list[str] = []

    async def send(self, *, to: str, subject: str, html_body: str, text_body: str) -> None:
        self.calls.append(to)
        await asyncio.sleep(0)  # let concurrent workers interleave
        if self.script:
            outcome = self.script.pop(0)
            if outcome is not None:
                raise outcome


def transient() -> EmailDeliveryError:
    return EmailDeliveryError("test", "network", True, "not_sent", None, error_type=OSError())


def unknown_outcome() -> EmailDeliveryError:
    return EmailDeliveryError("test", "timeout", True, "unknown", None, error_type=TimeoutError())


def permanent() -> EmailDeliveryError:
    return EmailDeliveryError("test", "rejected", False, "not_sent", 550, error_type=ValueError())


@pytest.fixture(autouse=True)
async def _clean(monkeypatch: pytest.MonkeyPatch) -> Any:
    monkeypatch.setenv("EMAIL_OUTBOX_DISPATCH", "none")
    get_settings.cache_clear()

    async def purge() -> None:
        async with get_session_factory()() as s:
            await s.execute(
                text(
                    "DELETE FROM email_outbox WHERE recipient LIKE '%@b13.test' "
                    "OR recipient LIKE '%@b13.example.com'"
                )
            )
            await s.commit()

    await purge()
    yield
    await purge()


def addr() -> str:
    return f"{uuid4().hex[:12]}{DOMAIN}"


async def enqueue(
    *,
    to: str | None = None,
    key: str | None = None,
    company_id: UUID | None = None,
    settings: Settings | None = None,
) -> tuple[UUID, str]:
    """Stores one message and COMMITS - no dispatch has run (the 'crash after commit' state)."""
    to = to or addr()
    async with get_session_factory()() as session:
        oid = await ob.enqueue_email(
            session,
            message_id=key or f"b13test:{uuid4()}",
            kind="b13.test",
            failure_kind="b13_test",
            to=to,
            subject="Subject",
            html_body="<p>link https://x/accept-invite/abcdefghijklmnopqrstuvwxyz0123456789</p>",
            text_body="link",
            company_id=company_id,
            context={"case_id": "c-1"},
            settings=settings,
        )
        await session.commit()
    return oid, to


async def row(oid: UUID) -> dict[str, Any]:
    async with get_session_factory()() as s:
        r = (
            (
                await s.execute(
                    text(
                        "SELECT status, attempts, max_attempts, text_body, html_body, locked_by, "
                        "locked_until, next_attempt_at, last_attempt_at, last_failure_class, "
                        "sent_at, "
                        "failed_at, message_id, recipient FROM email_outbox WHERE id = :i"
                    ),
                    {"i": oid},
                )
            )
            .mappings()
            .one()
        )
    return dict(r)


async def count_where(sql: str, **p: Any) -> int:
    async with get_session_factory()() as s:
        return int(
            (
                await s.execute(text(f"SELECT count(*) FROM email_outbox WHERE {sql}"), p)
            ).scalar_one()
        )


async def make_due(oid: UUID) -> None:
    """Simulates the backoff delay / the lease having elapsed."""
    async with get_session_factory()() as s:
        await s.execute(
            text(
                "UPDATE email_outbox SET next_attempt_at = now() - interval '1 second', "
                "locked_until = CASE WHEN locked_until IS NULL THEN NULL "
                "ELSE now() - interval '1 second' END WHERE id = :i"
            ),
            {"i": oid},
        )
        await s.commit()


async def email_log_count(to: str) -> int:
    async with get_session_factory()() as s:
        return int(
            (
                await s.execute(
                    text("SELECT count(*) FROM email_log WHERE recipient = :t"), {"t": to}
                )
            ).scalar_one()
        )


# ----------------------------------------------------------------- 1. commit creates the intent


async def test_commit_stores_the_message_and_nothing_is_delivered_before_a_worker_runs() -> None:
    rec = Recorder()
    to = addr()
    async with get_session_factory()() as session:
        await queue_email_after_commit(
            session, rec, to=to, subject="S", html_body="<p>h</p>", text_body="t",
            failure_kind="b13_test", message_key=f"b13test:{uuid4()}", company_id=str(uuid4()),
        )  # fmt: skip
        # not visible to anyone else, nothing sent, nothing in the ledger
        assert await count_where("recipient = :t", t=to) == 0
        assert rec.calls == [] and await email_log_count(to) == 0
        await session.commit()
        await run_post_commit(session)  # dispatch mode `none`: a hint that does nothing
    assert await count_where("recipient = :t AND status = 'PENDING' AND attempts = 0", t=to) == 1
    assert rec.calls == [] and await email_log_count(to) == 0  # still not delivered
    oid = (await ob_ids(to))[0]

    assert await ob.deliver_message(oid, sender=rec) == "sent"
    assert rec.calls == [to]
    done = await row(oid)
    assert done["status"] == "SENT" and done["attempts"] == 1 and done["sent_at"] is not None
    assert done["text_body"] is None and done["html_body"] is None  # single-use links not retained
    assert done["locked_by"] is None and done["locked_until"] is None


async def ob_ids(to: str) -> list[UUID]:
    async with get_session_factory()() as s:
        return [
            r[0]
            for r in (
                await s.execute(text("SELECT id FROM email_outbox WHERE recipient = :t"), {"t": to})
            ).all()
        ]


# ------------------------------------------------------------------------------- 2. rollback


async def test_rollback_and_savepoint_rollback_leave_nothing_deliverable() -> None:
    rec = Recorder()
    gone, kept = addr(), addr()
    async with get_session_factory()() as session:
        await queue_email_after_commit(
            session, rec, to=gone, subject="S", html_body="h", text_body="t",
            failure_kind="b13_test", message_key=f"b13test:{uuid4()}",
        )  # fmt: skip
        await session.rollback()
    assert await ob_ids(gone) == []

    async with get_session_factory()() as session:
        await queue_email_after_commit(
            session, rec, to=kept, subject="S", html_body="h", text_body="t",
            failure_kind="b13_test", message_key=f"b13test:{uuid4()}",
        )  # fmt: skip
        savepoint = await session.begin_nested()
        await queue_email_after_commit(
            session, rec, to=gone, subject="S", html_body="h", text_body="t",
            failure_kind="b13_test", message_key=f"b13test:{uuid4()}",
        )  # fmt: skip
        await savepoint.rollback()
        await session.commit()
    assert await ob_ids(gone) == [] and len(await ob_ids(kept)) == 1

    # a sweep has nothing for the rolled-back operations
    counts = await ob.deliver_due(sender=rec)
    assert gone not in rec.calls and rec.calls.count(kept) == 1 and counts["sent"] >= 1

    # an exception inside `session_scope` rolls the whole thing back, outbox row included
    boom = addr()
    with pytest.raises(RuntimeError):
        async with session_scope() as session:
            await queue_email_after_commit(
                session, rec, to=boom, subject="S", html_body="h", text_body="t",
                failure_kind="b13_test", message_key=f"b13test:{uuid4()}",
            )  # fmt: skip
            raise RuntimeError("business failure after the email was prepared")
    assert await ob_ids(boom) == []


# ------------------------------------------------------------ 3. crash after commit (real process)


async def test_process_crash_right_after_commit_does_not_lose_the_message() -> None:
    to, key = addr(), f"b13test:{uuid4()}"
    rc, _ = await run_proc("enqueue_and_die", key, to)
    assert rc == 137  # the committing process was killed before any dispatch or delivery
    oid = (await ob_ids(to))[0]
    assert (await row(oid))["status"] == "PENDING" and await email_log_count(to) == 0

    # a different, healthy worker process picks it up through the sweep
    rc, out = await run_proc("sweep")
    assert rc == 0 and json.loads(out)["sent"] >= 1
    assert (await row(oid))["status"] == "SENT"
    assert await email_log_count(to) == 1  # delivered once


async def test_worker_killed_before_and_after_the_provider_accepted() -> None:
    # (a) dies after claiming, before sending: lease recovery re-delivers exactly once
    oid, to = await enqueue()
    rc, _ = await run_proc("claim_die", str(oid))
    assert rc == 137
    stuck = await row(oid)
    assert (
        stuck["status"] == "SENDING"
        and stuck["attempts"] == 1
        and stuck["locked_until"] is not None
    )
    assert await ob.deliver_message(oid, sender=Recorder()) == "skipped"  # lease still valid
    await make_due(oid)  # the lease elapses
    rec = Recorder()
    assert await ob.deliver_message(oid, sender=rec) == "sent" and rec.calls == [to]
    assert (await row(oid))["attempts"] == 2 and await email_log_count(to) == 0

    # (b) dies after the provider accepted, before SENT was recorded: at-least-once means the
    #     retry sends it AGAIN - the documented duplicate window, asserted so it cannot be forgotten
    oid2, to2 = await enqueue()
    rc, _ = await run_proc("claim_send_die", str(oid2))
    assert rc == 137 and await email_log_count(to2) == 1  # accepted once
    await make_due(oid2)
    rc, out = await run_proc("sweep")
    assert (await row(oid2))["status"] == "SENT"
    assert await email_log_count(to2) == 2  # duplicate delivery after the crash window


async def test_lease_is_exhausted_into_failed_not_stuck_in_sending() -> None:
    oid, _ = await enqueue(settings=Settings(email_outbox_max_attempts=1))
    assert (await run_proc("claim_die", str(oid)))[0] == 137
    await make_due(oid)
    await ob.deliver_due(sender=Recorder())
    done = await row(oid)
    assert done["status"] == "FAILED" and done["last_failure_class"] == "lease_expired"
    assert done["text_body"] is None and done["failed_at"] is not None


# -------------------------------------------------------------- 4. worker restart and retry


async def test_restart_and_retry_after_a_transient_failure_delivers_once() -> None:
    oid, to = await enqueue()
    first = Recorder([transient()])  # worker 1: provider down
    assert await ob.deliver_message(oid, sender=first) == "retry"
    waiting = await row(oid)
    assert waiting["status"] == "PENDING" and waiting["attempts"] == 1
    assert (
        waiting["last_failure_class"] == "network"
        and waiting["next_attempt_at"] > waiting["last_attempt_at"]
    )
    assert waiting["text_body"] is not None  # still needed for the retry
    # not due yet: a sweep (any worker) leaves it alone
    second = Recorder()
    await ob.deliver_due(sender=second)
    assert to not in second.calls

    await make_due(oid)  # backoff elapsed; "worker 1 restarted" = a brand new sender/process state
    assert await ob.deliver_due(sender=second)  # noqa: S101
    assert second.calls.count(to) == 1
    done = await row(oid)
    assert done["status"] == "SENT" and done["attempts"] == 2


# ----------------------------------------------------- 5. transient / permanent failure handling


async def test_transient_failures_back_off_exponentially_and_end_failed_when_exhausted() -> None:
    cfg = Settings(
        email_outbox_max_attempts=4,
        email_outbox_backoff_base_seconds=30,
        email_outbox_backoff_cap_seconds=100,
    )
    oid, to = await enqueue(settings=cfg)
    rec = Recorder([transient(), unknown_outcome(), transient(), transient()])
    delays = []
    for attempt in range(1, 4):
        assert await ob.deliver_message(oid, sender=rec, settings=cfg) == "retry"
        r = await row(oid)
        assert r["attempts"] == attempt and r["status"] == "PENDING"
        delays.append(round((r["next_attempt_at"] - r["last_attempt_at"]).total_seconds()))
        await make_due(oid)
    assert delays == [30, 60, 100]  # 30 * 2^(n-1), capped at 100
    assert await ob.deliver_message(oid, sender=rec, settings=cfg) == "failed"  # 4th = last allowed
    final = await row(oid)
    assert final["status"] == "FAILED" and final["attempts"] == 4 == final["max_attempts"]
    assert final["text_body"] is None and final["failed_at"] is not None
    # a failed message is never picked up again
    await make_due(oid)
    again = Recorder()
    await ob.deliver_due(sender=again)
    assert to not in again.calls and await ob.deliver_message(oid, sender=again) == "skipped"
    assert rec.calls.count(to) == 4


async def test_permanent_failure_fails_immediately_without_retry() -> None:
    oid, to = await enqueue()
    rec = Recorder([permanent()])
    assert await ob.deliver_message(oid, sender=rec) == "failed"
    r = await row(oid)
    assert r["status"] == "FAILED" and r["attempts"] == 1 and r["last_failure_class"] == "rejected"
    await make_due(oid)
    await ob.deliver_due(sender=rec)
    assert rec.calls == [to]  # one attempt, ever


async def test_non_transport_sender_error_is_retried_but_bounded() -> None:
    cfg = Settings(email_outbox_max_attempts=2)
    oid, _ = await enqueue(settings=cfg)
    rec = Recorder([RuntimeError("bug"), RuntimeError("bug")])
    assert await ob.deliver_message(oid, sender=rec, settings=cfg) == "retry"
    await make_due(oid)
    assert await ob.deliver_message(oid, sender=rec, settings=cfg) == "failed"
    assert (await row(oid))["last_failure_class"] == "internal"


# ---------------------------------------------------------------------- 6. duplicate delivery


async def test_duplicate_task_delivery_and_duplicate_enqueue_send_once() -> None:
    oid, to = await enqueue()
    rec = Recorder()
    outcomes = await asyncio.gather(*[ob.deliver_message(oid, sender=rec) for _ in range(8)])
    assert sorted(outcomes) == ["sent"] + ["skipped"] * 7 and rec.calls == [to]
    assert await ob.deliver_message(oid, sender=rec) == "skipped" and rec.calls == [
        to
    ]  # late duplicate

    # same logical message enqueued again (a replayed operation): still one row, one delivery
    key = f"b13test:{uuid4()}"
    to2 = addr()
    a, _ = await enqueue(to=to2, key=key)
    b, _ = await enqueue(to=to2, key=key)
    assert a == b and await count_where("message_id = :k", k=key) == 1
    rec2 = Recorder()
    await ob.deliver_due(sender=rec2)
    assert rec2.calls.count(to2) == 1

    # the real Celery task body, in a separate process, for a message that is already SENT
    rc, out = await run_proc("task", str(oid))
    assert rc == 0 and json.loads(out) == "skipped"


# ---------------------------------------------------------------- 7. concurrent workers


async def test_concurrent_workers_deliver_every_message_exactly_once() -> None:
    recipients = [addr() for _ in range(40)]
    for to in recipients:
        await enqueue(to=to)
    rec = Recorder()
    # four "workers" on independent connections, all sweeping the same backlog
    results = await asyncio.gather(*[ob.deliver_due(sender=rec) for _ in range(4)])
    mine = [c for c in rec.calls if c.endswith(DOMAIN)]
    assert sorted(mine) == sorted(recipients)  # each exactly once, none lost
    assert sum(r["sent"] for r in results) >= 40
    assert await count_where("recipient LIKE '%@b13.test' AND status = 'SENT'") == 40


async def test_concurrent_worker_processes_deliver_every_message_exactly_once() -> None:
    recipients = [addr() for _ in range(30)]
    for to in recipients:
        await enqueue(to=to)
    start = time.time() + 12
    runs = await asyncio.gather(*[run_proc("sweep", f"start_at={start}") for _ in range(3)])
    assert all(rc == 0 for rc, _ in runs)
    assert await count_where("recipient LIKE '%@b13.test' AND status = 'SENT'") == 30
    for to in recipients:  # `email_log` is written by the (logging) provider once per send
        assert await email_log_count(to) == 1, to


# ----------------------------------------------- 8. enqueue failure leaves the transaction usable


async def test_outbox_write_failure_does_not_poison_the_business_transaction() -> None:
    bad = Settings.model_construct(**{**Settings().model_dump(), "email_outbox_max_attempts": 0})
    marker = uuid4()
    async with get_session_factory()() as session:
        await session.execute(text("CREATE TEMP TABLE b13_marker (id uuid)"))
        await session.execute(text("INSERT INTO b13_marker VALUES (:i)"), {"i": marker})
        with pytest.raises(Exception):  # noqa: B017, PT011 - CHECK (max_attempts >= 1) violation
            await ob.enqueue_email(
                session, message_id=f"b13test:{uuid4()}", kind="k", failure_kind="f", to=addr(),
                subject="S", html_body="h", text_body="t", settings=bad,
            )  # fmt: skip
        # the SAVEPOINT absorbed the failure: earlier work in the transaction is intact and usable
        n = (await session.execute(text("SELECT count(*) FROM b13_marker"))).scalar_one()
        assert n == 1
        await session.rollback()


# --------------------------------------------- 9. business flows over HTTP: consistency + API


async def test_invite_flows_store_one_message_per_issue_and_expose_explicit_status_fields(
    client: AsyncClient,
) -> None:
    from tests.integration.modules.account_invite.uac_helpers import register_tenant, teardown

    tenant = await register_tenant(client)
    try:
        email = f"{uuid4().hex[:10]}@b13.example.com"
        tenant.emails.append(email)
        first = await client.post(
            "/v1/users/invite",
            headers=tenant.headers,
            json={"email": email, "role_code": "EMPLOYEE"},
        )
        assert first.status_code == 201, first.text
        data = first.json()["data"]
        # compatibility: the old name is still there with the B12 meaning; explicit fields are new
        assert data["email_sent"] is True and data["email_queued"] is True
        assert data["email_delivery_status"] == "QUEUED"
        invite_id = data["id"]
        assert await count_where("message_id = :k", k=f"account_invite:{invite_id}") == 1

        # inline mode is the suite default, but this test forced `none`: nothing delivered yet
        assert await email_log_count(email) == 0
        # a repeated request is a NEW logical message (new token), not a duplicate of the first
        second = await client.post(
            "/v1/users/invite",
            headers=tenant.headers,
            json={"email": email, "role_code": "EMPLOYEE"},
        )
        assert second.status_code == 201
        assert await count_where("recipient = :t", t=email) == 2
        # worker delivers both, once each
        rec = Recorder()
        await ob.deliver_due(sender=rec)
        assert rec.calls.count(email) == 2
        assert await count_where("recipient = :t AND status = 'SENT'", t=email) == 2
    finally:
        await teardown(tenant)


async def test_activation_outbox_is_atomic_with_the_business_state_and_survives_delivery_failure(
    client: AsyncClient,
) -> None:
    from tests.integration.modules.onboarding.test_onboarding_activation import (
        _full_teardown,
        _verified_case,
    )
    from tests.integration.modules.onboarding.test_onboarding_case import _register_tenant

    headers, company_id, user_id = await _register_tenant(client)
    try:
        case = await _verified_case(client, headers, company_id, with_org=True)

        async def outbox(company: UUID) -> list[tuple[str, str]]:
            async with get_session_factory()() as s:
                return [
                    (r[0], r[1])
                    for r in (
                        await s.execute(
                            text(
                                "SELECT message_id, status FROM email_outbox WHERE company_id = :c "
                                "ORDER BY message_id"
                            ),
                            {"c": company},
                        )
                    ).all()
                ]

        assert await outbox(company_id) == []
        ok = await client.post(f"/v1/onboarding-cases/{case['id']}/activate", headers=headers)
        assert ok.status_code == 200, ok.text
        rows = await outbox(company_id)
        # exactly the two messages one activation owns, in the same commit as the business rows
        assert [m for m, _ in rows if m.startswith("onboarding_activated:")] == [
            f"onboarding_activated:{case['id']}"
        ]
        assert sum(1 for m, _ in rows if m.startswith("account_invite:")) == 1
        assert all(s == "PENDING" for _, s in rows)
        employees = await scalar(company_id, "SELECT count(*) FROM employee WHERE company_id=:cid")
        assert employees == 1

        # repeated activation: refused, nothing new queued, nothing new in the business tables
        for _ in range(2):
            again = await client.post(
                f"/v1/onboarding-cases/{case['id']}/activate", headers=headers
            )
            assert again.status_code == 409
        assert await outbox(company_id) == rows

        # provider outage: delivery fails permanently; the business state is untouched and exactly
        # one employee / invite exists - a failed or retried message can never recreate records
        down = Recorder([permanent(), permanent()])
        await ob.deliver_due(sender=down)
        statuses = {m.split(":")[0]: s for m, s in await outbox(company_id)}
        assert statuses == {"onboarding_activated": "FAILED", "account_invite": "FAILED"}
        assert await scalar(company_id, "SELECT count(*) FROM employee WHERE company_id=:cid") == 1
        assert (
            await scalar(company_id, "SELECT count(*) FROM account_invite WHERE company_id=:cid")
            == 1
        )
        assert await audit_count(company_id, "ONBOARDING_CASE_ACTIVATED") == 1
    finally:
        await _full_teardown(company_id=company_id, user_id=user_id)
