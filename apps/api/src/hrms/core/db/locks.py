"""Advisory locks shared by more than one module.

`attendance-period-close` orders attendance period finalisation against leave changes for the same
company. Finalisation freezes a per-employee summary and locks the attendance days from what it
read when it started; a leave approval or reversal that commits in the middle changes those days
after the read, leaving a frozen summary that does not count the leave. Finalisation therefore takes
the lock exclusively and every leave change that recalculates attendance takes it shared: leave
changes still run concurrently with each other, finalisation waits for the ones in flight and then
reads their committed result, and a leave change that arrives while it runs waits and re-checks the
period (now closed) afterwards.

`leave-dates` is the per-employee lock that orders everything deciding which dates an employee has
leave on: leave submission, approval, ledger adjustments and encashments, and the employment changes
that move the boundaries those dates are validated against (termination). It is always the FIRST
lock taken; the attendance period-close lock and the leave balance lock come after it.

`payroll-finalise` serialises pay-run finalisation per legal entity. Arrears are looked up per
legal entity, so two runs of one entity that were both prepared with the same unpaid arrears must
not both finalise on that read: the second waits, then sees what the first paid and is refused as
stale. Runs of different entities never contend.

Payroll finalisation also holds the attendance period-close lock SHARED, and attendance reopen
takes it EXCLUSIVE. Finalise therefore cannot commit a run on a period that is being reopened,
and a reopen cannot slip in between finalise's "period is CLOSED" check and its commit: whichever
goes second waits and then re-reads (a finalised run blocks the reopen; an OPEN period blocks the
finalise).

`pay-adjustment` serialises paid-day corrections of one employee in one finalised run (PAY-B04).
Each correction is checked against the sum of the earlier ones, so two concurrent corrections
must not both pass that check on the same total. It is a LEAF lock: it is taken first in the
correction request (after the idempotency claim, which is a row, not a lock) and nothing else in
this list is acquired while holding it, so it cannot take part in a cycle.

`onboarding-case-email` serialises creation of onboarding cases for one normalised candidate e-mail
within a company (B12 / DEF-B11-03). "No second active case for this e-mail" is a check followed by
an insert; without a lock, parallel creates all pass the check. It is a LEAF lock - taken, then the
check and the insert, then the transaction ends - and nothing else in this list is acquired while
holding it.

Lock order, outermost first — always acquire in this order, never the reverse:

    leave-dates  ->  payroll-finalise  ->  attendance-period-close  ->  leave balance

Only payroll finalisation takes more than one of these in the payroll chain; attendance period
finalisation and reopen take only the period-close lock, and leave takes leave-dates before the
period-close lock, so the order is acyclic.

Both ends wait a bounded time (`attendance_lock_timeout_ms`) and fail with a retryable lock timeout
rather than queuing indefinitely.
"""

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from hrms.core.config.settings import get_settings
from hrms.core.db.timeouts import bounded_lock_wait


async def lock_attendance_period_close(
    session: AsyncSession, company_id: UUID, *, exclusive: bool
) -> None:
    """Held until the transaction ends. `exclusive=True` is finalisation; `False` is a leave
    approval or reversal."""
    key = f"attendance-period-close:{company_id}"
    advisory = func.pg_advisory_xact_lock if exclusive else func.pg_advisory_xact_lock_shared
    async with bounded_lock_wait(
        session, lock_timeout_ms=get_settings().attendance_lock_timeout_ms
    ):
        await session.execute(select(advisory(func.hashtextextended(key, 0))))


async def lock_employee_leave_dates(
    session: AsyncSession, company_id: UUID, employee_id: UUID
) -> None:
    """Held until the transaction ends. Reentrant within one transaction. Takes the same key the
    Leave module has always used for its per-employee date lock, so existing and new callers
    serialise against each other."""
    key = f"leave-dates:{company_id}:{employee_id}"
    async with bounded_lock_wait(session, lock_timeout_ms=get_settings().leave_lock_wait_ms):
        await session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0))))


async def lock_payroll_finalise(
    session: AsyncSession, company_id: UUID, legal_entity_id: UUID
) -> None:
    """Held until the transaction ends. Taken before `lock_attendance_period_close`; see the
    module docstring for the order."""
    key = f"payroll-finalise:{company_id}:{legal_entity_id}"
    async with bounded_lock_wait(
        session, lock_timeout_ms=get_settings().attendance_lock_timeout_ms
    ):
        await session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0))))


async def lock_pay_adjustment(
    session: AsyncSession, company_id: UUID, pay_run_id: UUID, employee_id: UUID
) -> None:
    """Held until the transaction ends. A leaf lock; see the module docstring."""
    key = f"pay-adjustment:{company_id}:{pay_run_id}:{employee_id}"
    async with bounded_lock_wait(
        session, lock_timeout_ms=get_settings().attendance_lock_timeout_ms
    ):
        await session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0))))


async def lock_onboarding_case_email(session: AsyncSession, company_id: UUID, email: str) -> None:
    """Held until the transaction ends. `email` must already be normalised (stripped, lower-cased)
    so that spellings of one address share one lock. A leaf lock; see the module docstring."""
    key = f"onboarding-case-email:{company_id}:{email}"
    async with bounded_lock_wait(
        session, lock_timeout_ms=get_settings().attendance_lock_timeout_ms
    ):
        await session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0))))


async def lock_calendar_policy_dependencies(session: AsyncSession, company_id: UUID) -> None:
    """Held until the transaction ends. Serialises, per company, deactivating a work calendar or
    weekly-off pattern against creating an assignment (or default link) that depends on it, so a
    dependency cannot slip in between "no active assignment" and the deactivation. Taken after
    `work-calendar-change:<company>` when both are needed (change-impact confirmation). A leaf
    lock otherwise."""
    key = f"calendar-policy-dependencies:{company_id}"
    async with bounded_lock_wait(
        session, lock_timeout_ms=get_settings().attendance_lock_timeout_ms
    ):
        await session.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(key, 0))))
