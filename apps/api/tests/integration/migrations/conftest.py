"""CI guard for the migration tests: they must RUN, not be skipped.

These tests need the disposable QA Postgres (`HRMS_QA_STRICT=1`); a plain run skips them, which is
right on a laptop. The dedicated CI migration job sets `HRMS_REQUIRE_MIGRATION_TESTS=1`, and then a
skipped test, or too few tests, fails the job - so deleting the service, the variable or the tests
cannot turn the job green silently.
"""

import os

import pytest

#: Fewer than this many passing tests in `test_attendance_r2_migrations.py` fails the required run.
#: Raise it when tests are added; never lower it to make a run pass.
MIN_REQUIRED_PASSES = 19

_REQUIRE = "HRMS_REQUIRE_MIGRATION_TESTS"
_counts = {"passed": 0, "skipped": 0}


def _required() -> bool:
    return os.environ.get(_REQUIRE) == "1"


def pytest_runtest_logreport(report: pytest.TestReport) -> None:
    if "test_attendance_r2_migrations.py" not in report.nodeid:
        return
    if report.when == "call" and report.passed:
        _counts["passed"] += 1
    if report.skipped:
        _counts["skipped"] += 1


def pytest_sessionfinish(session: pytest.Session, exitstatus: int) -> None:
    if not _required():
        return
    problems = []
    if _counts["skipped"]:
        problems.append(f"{_counts['skipped']} migration test(s) were skipped")
    if _counts["passed"] < MIN_REQUIRED_PASSES:
        problems.append(
            f"only {_counts['passed']} migration tests passed; at least {MIN_REQUIRED_PASSES} "
            "are required"
        )
    if problems:
        print(f"\n{_REQUIRE}=1: " + "; ".join(problems))  # noqa: T201
        session.exitstatus = 1
