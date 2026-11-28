"""F1 - `attendance.calculate_company` / `attendance.calculate_range` never report SUCCESS while
employee-dates are still undone.

The calculation service is replaced by a scripted fake (no database): each (employee, date) can
fail on chosen attempts, and the fake counts how often each pair was attempted and how often it
*succeeded* - a second success for a pair would be a duplicate calculation (and a duplicate audit
event in production). The tasks run through Celery's `apply()`, so the final state, the retry
chain and the Prometheus series are the real ones."""

import asyncio
from collections import Counter
from collections.abc import Callable
from contextlib import asynccontextmanager
from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
from prometheus_client import REGISTRY
from sqlalchemy.exc import OperationalError

import hrms.modules.attendance.tasks as tasks
from hrms.core.celery_app import celery_app
from hrms.modules.attendance.exceptions import AttendanceDayLockedError
from hrms.shared.business_time import business_today

COMPANY = uuid4()
E1, E2, E3 = uuid4(), uuid4(), uuid4()
TODAY = business_today("UTC")
DAYS = [TODAY - timedelta(days=n) for n in range(tasks.TRAILING_DAYS)]
COMPANY_TASK = "attendance.calculate_company"
RANGE_TASK = "attendance.calculate_range"


def _transient(_n: int) -> Exception:
    return OperationalError("UPDATE attendance_day", {}, Exception("connection lost"))


def _permanent(_n: int) -> Exception:
    return ValueError("a bug")


class Script:
    """`plan[(employee, date)]` is a callable `attempt_number -> exception | None`."""

    def __init__(self) -> None:
        self.plan: dict[tuple[UUID, date], Callable[[int], Exception | None]] = {}
        self.attempts: Counter[tuple[UUID, date]] = Counter()
        self.succeeded: Counter[tuple[UUID, date]] = Counter()

    def fail_first(
        self, pair: tuple[UUID, date], times: int, make: Callable[[int], Exception]
    ) -> None:
        self.plan[pair] = lambda n: make(n) if n < times else None

    def always(self, pair: tuple[UUID, date], make: Callable[[int], Exception]) -> None:
        self.plan[pair] = make


@pytest.fixture
def script(monkeypatch: pytest.MonkeyPatch) -> Script:
    s = Script()

    class FakeDayService:
        def __init__(self, _session: object) -> None: ...

        async def calculate(self, _company: UUID, employee: UUID, target: date, **_k: Any) -> None:
            key = (employee, target)
            n = s.attempts[key]
            s.attempts[key] += 1
            exc = s.plan.get(key, lambda _n: None)(n)
            if exc is not None:
                raise exc
            s.succeeded[key] += 1

    class FakeOrganisationService:
        def __init__(self, _session: object) -> None: ...

        async def get_company_profile(self, _company: UUID) -> SimpleNamespace:
            return SimpleNamespace(timezone="UTC")

    class FakeEmployeeRepository:
        async def list_employees(self, _session: object, *, company_id: UUID) -> list[Any]:
            return [SimpleNamespace(id=e, is_active=True) for e in (E1, E2)]

    class FakeEmploymentService:
        def __init__(self, _session: object) -> None: ...

        async def list_legal_entity_spans(self, _company: UUID, **_k: Any) -> list[Any]:
            return [(e, uuid4(), DAYS[-1], None) for e in (E1, E2)]

    @asynccontextmanager
    async def fake_scope(**_k: Any) -> Any:
        yield object()

    monkeypatch.setattr("hrms.modules.attendance.service.AttendanceDayService", FakeDayService)
    monkeypatch.setattr(
        "hrms.modules.organisation.service.OrganisationService", FakeOrganisationService
    )
    monkeypatch.setattr(
        "hrms.modules.employee.repository.EmployeeRepository", FakeEmployeeRepository
    )
    monkeypatch.setattr("hrms.modules.employee.service.EmploymentService", FakeEmploymentService)
    monkeypatch.setattr(tasks, "session_scope", fake_scope)
    monkeypatch.setattr(tasks, "run_task", asyncio.run)
    return s


class Recorder:
    def __init__(self) -> None:
        self.events: list[tuple[str, str, dict[str, Any]]] = []

    def _add(self, level: str) -> Callable[..., None]:
        return lambda event, **fields: self.events.append((level, event, fields))

    warning = property(lambda self: self._add("warning"))
    error = property(lambda self: self._add("error"))
    info = property(lambda self: self._add("info"))

    def named(self, event: str) -> list[dict[str, Any]]:
        return [f for _, e, f in self.events if e == event]


@pytest.fixture
def logs(monkeypatch: pytest.MonkeyPatch) -> Recorder:
    rec = Recorder()
    monkeypatch.setattr(tasks, "_logger", rec)
    return rec


def sample(name: str, **labels: str) -> float:
    return REGISTRY.get_sample_value(name, labels) or 0.0


def finished(task: str, state: str) -> float:
    return sample("hrms_celery_tasks_finished_total", task=task, state=state)


def run_company(**kwargs: Any) -> Any:
    return tasks.calculate_company.apply(args=[str(COMPANY)], kwargs=kwargs)


def all_pairs() -> list[tuple[UUID, date]]:
    return [(e, d) for e in (E1, E2) for d in DAYS]


# 1 ----------------------------------------------------------------------------------------------
def test_every_date_succeeds_so_the_task_succeeds_and_is_stamped(
    script: Script, logs: Recorder
) -> None:
    before = finished(COMPANY_TASK, "SUCCESS")
    stamp = sample("hrms_celery_task_last_success_timestamp_seconds", task=COMPANY_TASK)
    result = run_company()
    assert result.state == "SUCCESS" and result.result == len(all_pairs())
    assert set(script.succeeded.values()) == {1} and set(script.succeeded) == set(all_pairs())
    assert finished(COMPANY_TASK, "SUCCESS") == before + 1
    assert sample("hrms_celery_task_last_success_timestamp_seconds", task=COMPANY_TASK) >= stamp
    assert logs.named("attendance_calculation_retry") == []
    assert logs.named("attendance_calculation_incomplete") == []


# 2 ----------------------------------------------------------------------------------------------
def test_a_transient_failure_while_loading_the_roster_is_retried_then_fails(
    script: Script, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Down:
        def __init__(self, _s: object) -> None: ...

        async def get_company_profile(self, _c: UUID) -> None:
            raise _transient(0)

    monkeypatch.setattr("hrms.modules.organisation.service.OrganisationService", Down)
    failed = finished(COMPANY_TASK, "FAILURE")
    result = run_company()
    assert result.state == "FAILURE"
    assert finished(COMPANY_TASK, "FAILURE") == failed + 1
    assert script.attempts == Counter()  # nothing was calculated


# 3 + 8 + 9 --------------------------------------------------------------------------------------
def test_a_transient_failure_on_one_date_is_retried_alone_and_recovers(
    script: Script, logs: Recorder
) -> None:
    flaky = (E1, DAYS[0])
    script.fail_first(flaky, 1, _transient)
    retries = sample("hrms_celery_task_retries_total", task=COMPANY_TASK)
    retried = finished(COMPANY_TASK, "RETRY")
    ok = finished(COMPANY_TASK, "SUCCESS")
    stamp = sample("hrms_celery_task_last_success_timestamp_seconds", task=COMPANY_TASK)

    result = run_company()

    assert result.state == "SUCCESS"
    # Every pair succeeded exactly once - nothing was calculated twice, so no duplicate audit event.
    assert script.succeeded == Counter(dict.fromkeys(all_pairs(), 1))
    # The flaky pair was attempted twice; every other pair exactly once (no whole-task re-run).
    assert script.attempts[flaky] == 2
    assert all(n == 1 for pair, n in script.attempts.items() if pair != flaky)
    assert sample("hrms_celery_task_retries_total", task=COMPANY_TASK) == retries + 1
    assert finished(COMPANY_TASK, "RETRY") == retried + 1
    assert finished(COMPANY_TASK, "SUCCESS") == ok + 1
    assert sample("hrms_celery_task_last_success_timestamp_seconds", task=COMPANY_TASK) >= stamp
    [retry_log] = logs.named("attendance_calculation_retry")
    assert retry_log["pending"] == 1 and retry_log["attempt"] == 1
    assert "countdown_seconds" in retry_log and 15 <= retry_log["countdown_seconds"] <= 30


# 4 + 7 + 10 + 11 + 12 --------------------------------------------------------------------------
def test_one_employee_keeps_failing_others_are_done_and_the_task_ends_as_failure(
    script: Script, logs: Recorder
) -> None:
    for day in DAYS:
        script.always((E1, day), _transient)
    stamp_before = sample("hrms_celery_task_last_success_timestamp_seconds", task=COMPANY_TASK)
    ok_before = finished(COMPANY_TASK, "SUCCESS")
    failed = finished(COMPANY_TASK, "FAILURE")
    retries = sample("hrms_celery_task_retries_total", task=COMPANY_TASK)

    result = run_company()

    assert result.state == "FAILURE"  # never SUCCESS while E1's dates are undone
    assert finished(COMPANY_TASK, "SUCCESS") == ok_before
    assert (
        sample("hrms_celery_task_last_success_timestamp_seconds", task=COMPANY_TASK) == stamp_before
    )
    assert finished(COMPANY_TASK, "FAILURE") == failed + 1
    # E2 was calculated once each; E1 was attempted 1 + 3 retries and never succeeded.
    assert {p: n for p, n in script.succeeded.items()} == dict.fromkeys([(E2, d) for d in DAYS], 1)
    assert all(script.attempts[(E1, d)] == 4 for d in DAYS)
    assert sample("hrms_celery_task_retries_total", task=COMPANY_TASK) == retries + 3
    [incomplete] = logs.named("attendance_calculation_incomplete")
    assert incomplete["transient"] == len(DAYS) and incomplete["permanent"] == 0
    assert incomplete["attempts"] == 4
    assert len(logs.named("attendance_calculation_retry")) == 3
    # The new summary records carry counts only - no employee id or date.
    summary_records = str(
        logs.named("attendance_calculation_retry") + logs.named("attendance_calculation_incomplete")
    )
    assert str(E1) not in summary_records and DAYS[0].isoformat() not in summary_records


# 5 ----------------------------------------------------------------------------------------------
def test_several_employees_failing_are_all_retried_together(script: Script) -> None:
    script.fail_first((E1, DAYS[0]), 1, _transient)
    script.fail_first((E2, DAYS[1]), 2, _transient)
    result = run_company()
    assert result.state == "SUCCESS"
    assert script.succeeded == Counter(dict.fromkeys(all_pairs(), 1))
    assert script.attempts[(E1, DAYS[0])] == 2 and script.attempts[(E2, DAYS[1])] == 3


# 6 ----------------------------------------------------------------------------------------------
def test_a_permanent_failure_is_not_retried_but_never_reports_success(
    script: Script, logs: Recorder
) -> None:
    script.always((E1, DAYS[0]), _permanent)
    retries = sample("hrms_celery_task_retries_total", task=COMPANY_TASK)
    result = run_company()
    assert result.state == "FAILURE"
    assert script.attempts[(E1, DAYS[0])] == 1  # a bug fails identically every time
    assert sample("hrms_celery_task_retries_total", task=COMPANY_TASK) == retries
    # Everything else still got done, once.
    done = {p for p in all_pairs() if p != (E1, DAYS[0])}
    assert set(script.succeeded) == done and set(script.succeeded.values()) == {1}
    [incomplete] = logs.named("attendance_calculation_incomplete")
    assert incomplete["permanent"] == 1 and incomplete["transient"] == 0


def test_a_permanent_failure_seen_before_a_retry_still_fails_the_final_attempt(
    script: Script, logs: Recorder
) -> None:
    script.always((E1, DAYS[0]), _permanent)
    script.fail_first((E2, DAYS[0]), 1, _transient)  # recovers on the retry
    result = run_company()
    assert result.state == "FAILURE"  # the retry succeeds, but the earlier bug is not forgotten
    assert script.succeeded[(E2, DAYS[0])] == 1
    [incomplete] = logs.named("attendance_calculation_incomplete")
    assert incomplete["permanent"] == 1 and incomplete["transient"] == 0


def test_a_locked_day_is_an_expected_skip_not_a_failure(script: Script) -> None:
    script.always((E1, DAYS[0]), lambda _n: AttendanceDayLockedError("locked"))
    assert run_company().state == "SUCCESS"


def test_a_lock_timeout_counts_as_transient(script: Script) -> None:
    class QueryCancelledError(Exception):
        sqlstate = "57014"

    err = lambda _n: OperationalError("SELECT", {}, QueryCancelledError())  # noqa: E731
    script.fail_first((E1, DAYS[0]), 1, err)
    assert run_company().state == "SUCCESS"
    assert script.attempts[(E1, DAYS[0])] == 2


# range task -------------------------------------------------------------------------------------
def run_range(**kwargs: Any) -> Any:
    return tasks.calculate_range.apply(
        args=[str(COMPANY), DAYS[-1].isoformat(), DAYS[0].isoformat(), None, None], kwargs=kwargs
    )


def test_range_recovers_after_a_transient_failure_without_recalculating_the_rest(
    script: Script, logs: Recorder
) -> None:
    flaky = (E2, DAYS[1])
    script.fail_first(flaky, 1, _transient)
    stamp = sample("hrms_celery_task_last_success_timestamp_seconds", task=RANGE_TASK)
    result = run_range()
    assert result.state == "SUCCESS"
    assert script.succeeded == Counter(dict.fromkeys(all_pairs(), 1))
    assert script.attempts[flaky] == 2
    assert all(n == 1 for pair, n in script.attempts.items() if pair != flaky)
    assert sample("hrms_celery_task_last_success_timestamp_seconds", task=RANGE_TASK) >= stamp


def test_range_that_cannot_finish_is_a_failure_and_says_how_much_is_missing(
    script: Script, logs: Recorder
) -> None:
    script.always((E1, DAYS[0]), _transient)
    ok_before = finished(RANGE_TASK, "SUCCESS")
    result = run_range()
    assert result.state == "FAILURE"
    assert finished(RANGE_TASK, "SUCCESS") == ok_before
    [incomplete] = logs.named("attendance_calculation_incomplete")
    assert incomplete["transient"] == 1 and incomplete["task"] == RANGE_TASK


def test_range_permanent_failure_is_not_retried(script: Script) -> None:
    script.always((E1, DAYS[0]), _permanent)
    assert run_range().state == "FAILURE"
    assert script.attempts[(E1, DAYS[0])] == 1


# contract kept for callers that do not go through Celery ---------------------------------------
def test_the_plain_async_helpers_keep_their_counts_contract(script: Script) -> None:
    script.always((E1, DAYS[0]), _transient)
    assert asyncio.run(tasks._calculate_company_async(COMPANY)) == len(all_pairs()) - 1
    counts = asyncio.run(tasks._calculate_range_async(COMPANY, DAYS[-1], DAYS[0], None, None))
    assert counts["failed"] == 1 and counts["calculated"] == len(all_pairs()) - 1


def test_the_retry_options_are_unchanged_for_the_setup_stage() -> None:
    task = celery_app.tasks[COMPANY_TASK]
    assert task.max_retries == 3 and task.acks_late
