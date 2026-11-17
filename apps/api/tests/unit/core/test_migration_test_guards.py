"""The migration tests may only ever reach the disposable QA Postgres.

`test_b13_migrations._admin_url` is the single gate every migration test goes through (it also
builds each scratch database URL). These tests prove it refuses everything that is not the
loopback QA port with an `hrms_qa_*` database - the shared dev stack, other hosts, other ports,
other database names - and that the CI enforcement hook and the sandbox-only list are in place.
"""

import pytest
from tests.integration.migrations import conftest as migration_conftest
from tests.integration.migrations.test_b13_migrations import _admin_url, _url_for

GOOD = "postgresql+psycopg://migtest_admin:pw@127.0.0.1:15432/hrms_qa_migtest"


def test_the_disposable_qa_database_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MIGRATIONS_DATABASE_URL", GOOD)
    assert _admin_url() == GOOD
    assert _url_for("r2mig_abc").endswith("127.0.0.1:15432/r2mig_abc")


@pytest.mark.parametrize(
    "url",
    [
        # the shared development database, every spelling of it
        "postgresql://hrms:pw@localhost:5433/hrms_dev",
        "postgresql://hrms:pw@127.0.0.1:5433/hrms_dev",
        "postgresql://hrms:pw@127.0.0.1:15432/hrms_dev",  # right port, wrong database
        "postgresql://hrms:pw@127.0.0.1:5433/hrms_qa_migtest",  # right name, the dev port
        # right port and name on another host, or by name instead of the loopback address
        "postgresql://u:pw@10.0.0.5:15432/hrms_qa_migtest",
        "postgresql://u:pw@localhost:15432/hrms_qa_migtest",
        "postgresql://u:pw@db.example.com:15432/hrms_qa_migtest",
        # the system Postgres and a production-looking name
        "postgresql://u:pw@127.0.0.1:5432/hrms_qa_migtest",
        "postgresql://u:pw@127.0.0.1:15432/hrms_prod",
        "postgresql://u:pw@127.0.0.1:15432/postgres",
    ],
)
def test_everything_else_is_refused(monkeypatch: pytest.MonkeyPatch, url: str) -> None:
    monkeypatch.setenv("MIGRATIONS_DATABASE_URL", url)
    with pytest.raises(AssertionError):
        _admin_url()


def test_the_new_migration_tests_are_sandbox_only_in_a_plain_run() -> None:
    from tests import conftest as root_conftest

    assert "test_attendance_r2_migrations.py" in root_conftest._QA_SANDBOX_ONLY


def test_the_required_run_fails_on_a_skip_or_too_few_tests(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class _Session:
        exitstatus = 0

    monkeypatch.setenv("HRMS_REQUIRE_MIGRATION_TESTS", "1")
    for counts, expect_fail in (
        ({"passed": migration_conftest.MIN_REQUIRED_PASSES, "skipped": 0}, False),
        ({"passed": migration_conftest.MIN_REQUIRED_PASSES, "skipped": 1}, True),
        ({"passed": migration_conftest.MIN_REQUIRED_PASSES - 1, "skipped": 0}, True),
        ({"passed": 0, "skipped": 0}, True),
    ):
        monkeypatch.setattr(migration_conftest, "_counts", dict(counts))
        session = _Session()
        migration_conftest.pytest_sessionfinish(session, 0)  # type: ignore[arg-type]
        assert (session.exitstatus == 1) is expect_fail, counts
    capsys.readouterr()
    # and it does nothing when the run is not required
    monkeypatch.delenv("HRMS_REQUIRE_MIGRATION_TESTS")
    monkeypatch.setattr(migration_conftest, "_counts", {"passed": 0, "skipped": 5})
    session = _Session()
    migration_conftest.pytest_sessionfinish(session, 0)  # type: ignore[arg-type]
    assert session.exitstatus == 0
