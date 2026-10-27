"""B12 negative controls: a pytest plugin that REMOVES one fix at runtime (monkeypatch, in memory,
in the disposable runner) so the matching regression test can be seen to fail. No source file is
edited. Activate with env NEGCTL=<name>[,<name>] and `-p negctl` (PYTHONPATH=/qa/b12).

  att_guard       DEF-B11-01 / OBS-HRA-01: `_ensure_employee_visible` becomes a no-op (attendance)
  invite_scope    OBS-HRA-01: the invite lookup ignores the visibility set
  act_lock        DEF-B11-02: the activation row lock is removed (`get_case_for_update` -> plain read)
  email_immediate DEF-B11-04: emails are sent in-request, before commit (the pre-fix behaviour)
  dup_lock        DEF-B11-03: the advisory lock around check-and-insert is removed
  dup_exact       DEF-B11-05: the duplicate lookup is the pre-fix exact, single-row query
  confirm_guard   DEF-B11-06: the employment-ended check in confirm is neutralised
"""
import os

_ACTIVE = {x for x in os.environ.get("NEGCTL", "").split(",") if x}


def pytest_configure(config):  # noqa: ANN001
    if "att_guard" in _ACTIVE:
        import hrms.modules.attendance.service as svc

        async def _noop(*_a, **_k):  # noqa: ANN002, ANN003
            return None

        svc._ensure_employee_visible = _noop
    if "invite_scope" in _ACTIVE:
        from hrms.modules.employee.service import EmployeeService

        orig = EmployeeService.resolve_visible_employee_ids

        async def _all(self, company_id, scope, caller):  # noqa: ANN001
            return None

        EmployeeService.resolve_visible_employee_ids = _all
        _ = orig
    if "act_lock" in _ACTIVE:
        from hrms.modules.onboarding.repository import OnboardingCaseRepository

        async def _plain(self, session, *, company_id, case_id):  # noqa: ANN001
            return await self.get_case(session, company_id=company_id, case_id=case_id)

        OnboardingCaseRepository.get_case_for_update = _plain
    if "email_immediate" in _ACTIVE:
        import sys

        import hrms.modules.account_invite.service as inv
        import hrms.modules.onboarding.email_sender as es
        import hrms.modules.onboarding.service as onb

        async def _immediate(session, sender, *, to, subject, html_body, text_body, failure_kind, **ids):  # noqa: ANN001, ANN003
            frame = sys._getframe(1)
            module = frame.f_globals.get("__name__", "").rsplit(".", 2)
            token = es._KIND_OVERRIDE.set(f"{module[-2]}.{frame.f_code.co_name}"[:80])
            try:
                await sender.send(to=to, subject=subject, html_body=html_body, text_body=text_body)
            except Exception as exc:  # noqa: BLE001
                es.log_email_failure(failure_kind, exc, **ids)
            finally:
                es._KIND_OVERRIDE.reset(token)

        inv.queue_email_after_commit = _immediate
        onb.queue_email_after_commit = _immediate
    if "dup_lock" in _ACTIVE:
        import hrms.modules.onboarding.service as onb2

        async def _nolock(*_a, **_k):  # noqa: ANN002, ANN003
            return None

        onb2.lock_onboarding_case_email = _nolock
    if "dup_exact" in _ACTIVE:
        from sqlalchemy import select

        from hrms.modules.onboarding.models import OnboardingCase
        from hrms.modules.onboarding.repository import OnboardingCaseRepository
        from hrms.modules.onboarding.schemas import ONBOARDING_CASE_TERMINAL_STATUSES

        async def _exact(self, session, *, company_id, personal_email):  # noqa: ANN001
            stmt = select(OnboardingCase).where(
                OnboardingCase.company_id == company_id,
                OnboardingCase.personal_email == personal_email,
                OnboardingCase.deleted_at.is_(None),
                OnboardingCase.status.not_in(ONBOARDING_CASE_TERMINAL_STATUSES),
            )
            return (await session.execute(stmt)).scalar_one_or_none()

        OnboardingCaseRepository.get_active_case_by_email = _exact
    if "confirm_guard" in _ACTIVE:
        from hrms.modules.employee.repository import EmploymentRepository

        async def _none(self, session, *, company_id, employee_id):  # noqa: ANN001
            return []

        EmploymentRepository.list_employments = _none
    for name in sorted(_ACTIVE):
        print(f"NEGCTL active: {name}")
