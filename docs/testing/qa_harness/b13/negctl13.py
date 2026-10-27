"""B13 negative controls: a pytest plugin that REMOVES one B13 protection at runtime (in-memory
monkeypatch in the disposable runner); no source file is edited. Activate with env NEGCTL=<name>[,<name>]
and `-p negctl13` (PYTHONPATH=/qa/b13, set by `b13_run.sh`).

  confirm_lock   WS-D: `confirm_employee` no longer takes the per-employee lock before reading
  seat_lock      WS-E: the per-company seat advisory lock becomes a no-op
  outbox_immediate  WS-A: e-mail is sent in-request, before commit (the pre-B12 behaviour; no outbox)
  outbox_autocommit WS-A: the outbox row is written in its own committed session, not the business
                    transaction (a rollback no longer removes it)
  outbox_noclaim    WS-A: the claim ignores status/lease/backoff (duplicate task deliveries all send)
  outbox_nolease    WS-A: a stuck SENDING row is never taken over (lease recovery removed)
"""

import os
import sys

_ACTIVE = {x for x in os.environ.get("NEGCTL", "").split(",") if x}


def pytest_configure(config):  # noqa: ANN001
    if "confirm_lock" in _ACTIVE:
        import hrms.modules.employee.service as svc

        orig = svc.lock_employee_leave_dates

        async def _selective(session, company_id, employee_id):  # noqa: ANN001
            if sys._getframe(1).f_code.co_name == "confirm_employee":
                return None
            return await orig(session, company_id, employee_id)

        svc.lock_employee_leave_dates = _selective
    if "seat_lock" in _ACTIVE:
        from hrms.modules.employee.repository import EmployeeRepository

        async def _nolock(self, session, *, company_id):  # noqa: ANN001
            return None

        EmployeeRepository.lock_company_seats = _nolock
    if "outbox_immediate" in _ACTIVE:
        import hrms.modules.account_invite.service as inv
        import hrms.modules.onboarding.email_sender as es
        import hrms.modules.onboarding.service as onb

        async def _immediate(session, sender, *, to, subject, html_body, text_body, failure_kind, message_key=None, **ids):  # noqa: ANN001, ANN003
            frame = sys._getframe(1)
            module = frame.f_globals.get("__name__", "").rsplit(".", 2)
            token = es._KIND_OVERRIDE.set(f"{module[-2]}.{frame.f_code.co_name}"[:80])
            try:
                await sender.send(to=to, subject=subject, html_body=html_body, text_body=text_body)
            except Exception as exc:  # noqa: BLE001
                es.log_email_failure(failure_kind, exc, **ids)
            finally:
                es._KIND_OVERRIDE.reset(token)
            return True

        es.queue_email_after_commit = _immediate
        inv.queue_email_after_commit = _immediate
        onb.queue_email_after_commit = _immediate
    if "outbox_autocommit" in _ACTIVE:
        import hrms.modules.onboarding.email_outbox as ob

        orig_enqueue = ob.enqueue_email

        async def _own_commit(session, **kw):  # noqa: ANN001, ANN003
            from hrms.core.db.session import get_session_factory

            async with get_session_factory()() as other:
                oid = await orig_enqueue(other, **kw)
                await other.commit()
            return oid

        ob.enqueue_email = _own_commit
    if "outbox_noclaim" in _ACTIVE:
        import hrms.modules.onboarding.email_outbox as ob

        ob._CLAIMABLE = "true"
        # with no claim guard a sweep would re-claim the same rows until its time budget ends
        # (150 s); bound it so the control finishes. Fewer sweeps cannot hide a duplicate delivery.
        import functools

        ob.deliver_due = functools.partial(ob.deliver_due, time_budget_seconds=1.0)
    if "outbox_nolease" in _ACTIVE:
        import hrms.modules.onboarding.email_outbox as ob

        ob._CLAIMABLE = ob._CLAIMABLE.replace(
            "OR (status = 'SENDING' AND locked_until < clock_timestamp())", ""
        )
    for name in sorted(_ACTIVE):
        print(f"NEGCTL13 active: {name}")
