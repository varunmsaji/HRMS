"""Phase 1 migrations (R-2 ceiling, half-day recovery, downgrade protections), proved on SCRATCH
databases inside the disposable QA Postgres.

Same discipline as `test_b13_migrations.py` (whose helpers and strict guards this reuses): every
test works in a database it creates (a clone of a template migrated to the revision just before
`20261116090000`) and drops it afterwards; the run's main database is never touched. The admin
connection is only accepted for loopback, the private QA port and an `hrms_qa_*` database
(`_admin_url`); the whole module is skipped unless the strict sandbox is up (`HRMS_QA_STRICT=1`)
and, in the CI migration job, `HRMS_REQUIRE_MIGRATION_TESTS=1` turns any skip into a failure
(`conftest.py` next to this file).

Rows are synthetic and inserted with FK triggers off (`session_replication_role = replica`) so the
shapes that matter can be built without a whole tenant; CHECK constraints stay live.

Revisions: 090000 supersede action, 100000 shortfall table, 110000 half-day marker (+ recovery
backfill), 120000 mark-credit ceiling.
"""

# ruff: noqa: E501 - long SQL strings

import uuid
from collections.abc import Callable, Iterator
from datetime import date
from typing import Any

import psycopg
import pytest
from psycopg import errors as pgerr

from .test_b13_migrations import _admin, _alembic, _conn, _insert, _version

REV_BASE = "20261115090000"
REV_SUPERSEDE = "20261116090000"
REV_SHORTFALL = "20261116100000"
REV_HALF_DAY = "20261116110000"
REV_CEILING = "20261116120000"

ONE_STEP_DOWN = {
    REV_CEILING: REV_HALF_DAY,
    REV_HALF_DAY: REV_SHORTFALL,
    REV_SHORTFALL: REV_SUPERSEDE,
    REV_SUPERSEDE: REV_BASE,
}


def _prepare(db: str) -> None:
    """What the repo's init scripts do for a real database: the extensions, and the runtime role
    with default privileges, so grants on tables the migrations create can be asserted."""
    with _conn(db, enforce=True) as c:
        c.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
        c.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
        c.execute(
            """
            DO $$
            BEGIN
              IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hrms_app') THEN
                CREATE ROLE hrms_app LOGIN PASSWORD 'migtest-only'
                  NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
              END IF;
            END $$
            """
        )
        owner = c.execute("SELECT current_user").fetchone()
        assert owner is not None
        c.execute("GRANT USAGE ON SCHEMA public TO hrms_app")
        c.execute(
            f'ALTER DEFAULT PRIVILEGES FOR ROLE "{owner[0]}" IN SCHEMA public '
            "GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO hrms_app"
        )
        c.execute(
            f'ALTER DEFAULT PRIVILEGES FOR ROLE "{owner[0]}" IN SCHEMA public '
            "GRANT SELECT, UPDATE ON SEQUENCES TO hrms_app"
        )


@pytest.fixture(scope="module")
def template_db() -> Iterator[str]:
    name = f"r2mig_tpl_{uuid.uuid4().hex[:8]}"
    with _admin() as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    try:
        _prepare(name)
        rc, out = _alembic(name, "upgrade", REV_BASE)
        assert rc == 0, out[-2000:]
        yield name
    finally:
        with _admin() as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
def scratch(template_db: str) -> Iterator[str]:
    name = f"r2mig_{uuid.uuid4().hex[:8]}"
    with _admin() as admin:
        admin.execute(f'CREATE DATABASE "{name}" TEMPLATE "{template_db}"')
    try:
        yield name
    finally:
        with _admin() as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
def scratch_at(scratch: str) -> Callable[[str], str]:
    def _go(revision: str) -> str:
        rc, out = _alembic(scratch, "upgrade", revision)
        assert rc == 0, out[-2000:]
        assert _version(scratch) == revision
        return scratch

    return _go


def _scalar(db: str, sql: str, *params: Any) -> Any:
    with _conn(db, enforce=True) as c:
        row = c.execute(sql, params).fetchone()
    assert row is not None
    return row[0]


def _has_column(db: str, table: str, column: str) -> bool:
    return bool(
        _scalar(
            db,
            "SELECT count(*) FROM information_schema.columns WHERE table_schema='public' "
            "AND table_name=%s AND column_name=%s",
            table,
            column,
        )
    )


def _has_table(db: str, table: str) -> bool:
    return _scalar(db, "SELECT to_regclass(%s) IS NOT NULL", f"public.{table}") is True


def _refused(db: str, target: str, fragment: str, *, still_at: str) -> str:
    """A downgrade that must be refused: non-zero exit, the stated reason, and NOTHING changed -
    the revision, and (through the callers) the data and the schema."""
    rc, out = _alembic(db, "downgrade", target)
    assert rc != 0, out[-2000:]
    assert fragment in out, out[-2000:]
    assert _version(db) == still_at
    return out


# ----------------------------------------------------------------------------- the chain


def test_the_chain_has_one_head_and_it_is_the_ceiling_revision(scratch: str) -> None:
    rc, out = _alembic(scratch, "heads")
    assert rc == 0, out
    heads = [line for line in out.splitlines() if "(head)" in line]
    assert len(heads) == 1 and heads[0].startswith(REV_CEILING), out


def test_each_migration_round_trips_on_an_empty_history(scratch_at: Callable[[str], str]) -> None:
    db = scratch_at(REV_CEILING)
    assert _has_table(db, "leave_balance_shortfall")
    assert _has_column(db, "leave_application", "half_day")
    assert _has_column(db, "attendance_policy_version", "mark_credit_ceiling_minutes")
    # one step at a time all the way down, then all the way up again
    current = REV_CEILING
    while current != REV_BASE:
        target = ONE_STEP_DOWN[current]
        rc, out = _alembic(db, "downgrade", target)
        assert rc == 0, f"{current} -> {target}\n{out[-2000:]}"
        assert _version(db) == target
        current = target
    assert not _has_table(db, "leave_balance_shortfall")
    assert not _has_column(db, "leave_application", "half_day")
    assert not _has_column(db, "attendance_policy_version", "mark_credit_ceiling_minutes")
    rc, out = _alembic(db, "upgrade", "head")
    assert rc == 0, out[-2000:]
    assert _version(db) == REV_CEILING


# ------------------------------------------------------- 090000: supersede history is protected


def _supersede_row(db: str) -> uuid.UUID:
    with _conn(db) as c:
        return _insert(
            c,
            "overtime_action",
            company_id=uuid.uuid4(),
            overtime_record_id=uuid.uuid4(),
            action="SUPERSEDED_BY_RECALCULATION",
            comment='{"outcome": "CAPPED"}',
        )


def test_090000_downgrade_refuses_while_supersede_history_exists(
    scratch_at: Callable[[str], str],
) -> None:
    db = scratch_at(REV_CEILING)
    _supersede_row(db)
    out = _refused(db, REV_BASE, "Refusing to downgrade 20261116090000", still_at=REV_CEILING)
    assert "audit history" in out
    # nothing changed: the whole chain rolled back as one transaction
    assert _scalar(db, "SELECT count(*) FROM overtime_action") == 1
    assert _has_table(db, "leave_balance_shortfall")
    assert _has_column(db, "leave_application", "half_day")
    assert _has_column(db, "attendance_policy_version", "mark_credit_ceiling_minutes")
    assert _scalar(
        db,
        "SELECT strpos(pg_get_constraintdef(oid), 'SUPERSEDED_BY_RECALCULATION') > 0 FROM pg_constraint "
        "WHERE conname = 'overtime_action_action_check'",
    )


def test_090000_downgrade_proceeds_and_keeps_other_history_when_none_is_superseded(
    scratch_at: Callable[[str], str],
) -> None:
    db = scratch_at(REV_CEILING)
    with _conn(db) as c:
        _insert(
            c,
            "overtime_action",
            company_id=uuid.uuid4(),
            overtime_record_id=uuid.uuid4(),
            action="APPROVED",
        )
    rc, out = _alembic(db, "downgrade", REV_BASE)
    assert rc == 0, out[-2000:]
    assert _scalar(db, "SELECT count(*) FROM overtime_action") == 1  # untouched
    # the narrower constraint is back
    assert not _scalar(
        db,
        "SELECT strpos(pg_get_constraintdef(oid), 'SUPERSEDED_BY_RECALCULATION') > 0 FROM pg_constraint "
        "WHERE conname = 'overtime_action_action_check'",
    )


# ----------------------------------------------------- 100000: shortfall history is protected


@pytest.mark.parametrize("status,resolution", [("OPEN", None), ("RESOLVED", "DEBITED")])
def test_100000_downgrade_refuses_while_any_shortfall_row_exists(
    scratch_at: Callable[[str], str], status: str, resolution: str | None
) -> None:
    db = scratch_at(REV_SHORTFALL)
    with _conn(db) as c:
        _insert(
            c,
            "leave_balance_shortfall",
            status=status,
            resolution=resolution,
            calendar_date=date(2026, 11, 3),
            required_fraction=1,
            available_balance=0,
        )
    _refused(db, REV_SUPERSEDE, "Refusing to downgrade 20261116100000", still_at=REV_SHORTFALL)
    assert _scalar(db, "SELECT count(*) FROM leave_balance_shortfall") == 1


def test_100000_downgrade_drops_an_empty_table(scratch_at: Callable[[str], str]) -> None:
    db = scratch_at(REV_SHORTFALL)
    rc, out = _alembic(db, "downgrade", REV_SUPERSEDE)
    assert rc == 0, out[-2000:]
    assert not _has_table(db, "leave_balance_shortfall")


def test_100000_table_has_forced_rls_a_tenant_policy_and_runtime_grants(
    scratch_at: Callable[[str], str],
) -> None:
    db = scratch_at(REV_SHORTFALL)
    assert _scalar(
        db,
        "SELECT relrowsecurity AND relforcerowsecurity FROM pg_class "
        "WHERE oid = 'public.leave_balance_shortfall'::regclass",
    )
    assert (
        _scalar(
            db,
            "SELECT count(*) FROM pg_policies WHERE tablename = 'leave_balance_shortfall' "
            "AND policyname = 'tenant_isolation'",
        )
        == 1
    )
    for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        assert _scalar(
            db,
            "SELECT has_table_privilege('hrms_app', 'public.leave_balance_shortfall', %s)",
            privilege,
        )


# ------------------------------------------------------ 110000: recovery backfill and downgrade


def _application(
    conn: psycopg.Connection[Any],
    *,
    start: date = date(2026, 11, 3),
    end: date | None = None,
    half_day: str | None = None,
    with_column: bool = True,
) -> uuid.UUID:
    values: dict[str, Any] = {
        "start_date": start,
        "end_date": end or start,
        "status": "APPROVED",
        "approval_chain": "AUTO",
        "total_days": 0,
    }
    if with_column and half_day is not None:
        values["half_day"] = half_day
    return _insert(conn, "leave_application", **values)


def _day(conn: psycopg.Connection[Any], application: uuid.UUID, half: str | None) -> None:
    _insert(
        conn,
        "leave_application_day",
        leave_application_id=application,
        calendar_date=date(2026, 11, 3),
        fraction=0.5,
        half=half,
    )


def _projection(
    conn: psycopg.Connection[Any], application: uuid.UUID, half: str | None, status: str
) -> None:
    _insert(
        conn,
        "leave_day_projection",
        leave_application_id=application,
        attendance_date=date(2026, 11, 3),
        fraction=0.5 if half else 1,
        is_paid=True,
        half=half,
        status=status,
    )


def test_110000_backfill_recovers_only_unambiguous_evidence(
    scratch_at: Callable[[str], str],
) -> None:
    db = scratch_at(REV_SHORTFALL)  # the revision before the half-day column
    cases: dict[str, uuid.UUID] = {}
    with _conn(db) as c:
        # 1. a stored day row carries the half (the original backfill)
        a = _application(c, with_column=False)
        _day(c, a, "FIRST")
        cases["day_row_first"] = a
        # 1b. the legacy value is copied as stored, not normalised
        a = _application(c, with_column=False)
        _day(c, a, "FIRST_HALF")
        cases["day_row_legacy_value"] = a
        # 2. day row released, ONE cancelled projection with a half: recovered
        a = _application(c, with_column=False)
        _projection(c, a, "SECOND", "CANCELLED")
        cases["released_one_projection"] = a
        # 2b. several projections, all the same half (cancelled and re-projected): recovered
        a = _application(c, with_column=False)
        _projection(c, a, "FIRST", "CANCELLED")
        _projection(c, a, "FIRST", "APPROVED")
        cases["released_same_half_twice"] = a
        # 3. ambiguous or absent evidence stays NULL
        a = _application(c, with_column=False)
        _projection(c, a, "FIRST", "CANCELLED")
        _projection(c, a, "SECOND", "APPROVED")
        cases["two_different_halves"] = a
        a = _application(c, with_column=False)
        _projection(c, a, None, "CANCELLED")
        cases["only_null_half"] = a
        a = _application(c, with_column=False)
        _projection(c, a, "FIRST", "CANCELLED")
        _projection(c, a, None, "APPROVED")
        cases["half_and_null_mixed"] = a
        a = _application(c, with_column=False)
        cases["no_day_no_projection"] = a
        a = _application(c, end=date(2026, 11, 4), with_column=False)
        _projection(c, a, "FIRST", "CANCELLED")
        cases["multi_date"] = a
    rc, out = _alembic(db, "upgrade", REV_HALF_DAY)
    assert rc == 0, out[-2000:]
    with _conn(db, enforce=True) as c:
        halves = {
            name: c.execute(
                "SELECT half_day FROM leave_application WHERE id = %s", (app_id,)
            ).fetchone()[0]  # type: ignore[index]
            for name, app_id in cases.items()
        }
    assert halves == {
        "day_row_first": "FIRST",
        "day_row_legacy_value": "FIRST_HALF",
        "released_one_projection": "SECOND",
        "released_same_half_twice": "FIRST",
        "two_different_halves": None,
        "only_null_half": None,
        "half_and_null_mixed": None,
        "no_day_no_projection": None,
        "multi_date": None,
    }


def test_110000_backfill_never_overwrites_a_stored_half(
    scratch_at: Callable[[str], str],
) -> None:
    """If the column already holds a value (the revision is idempotent: `ADD COLUMN IF NOT
    EXISTS`), neither backfill step may replace it, even with contradicting evidence."""
    db = scratch_at(REV_SHORTFALL)
    with _conn(db, enforce=True) as c:
        c.execute('ALTER TABLE leave_application ADD COLUMN "half_day" VARCHAR(20)')
    with _conn(db) as c:
        stored = _application(c, half_day="SECOND")
        _day(c, stored, "FIRST")  # step 1 would copy FIRST
        other = _application(c, half_day="SECOND")
        _projection(c, other, "FIRST", "CANCELLED")  # step 2 would copy FIRST
    rc, out = _alembic(db, "upgrade", REV_HALF_DAY)
    assert rc == 0, out[-2000:]
    assert _scalar(db, "SELECT count(*) FROM leave_application WHERE half_day = 'SECOND'") == 2


def test_110000_downgrade_refuses_when_a_stored_half_would_be_lost(
    scratch_at: Callable[[str], str],
) -> None:
    db = scratch_at(REV_HALF_DAY)
    with _conn(db) as c:
        _application(c, half_day="FIRST")  # no day row: the column is the only copy
    _refused(db, REV_SHORTFALL, "Refusing to downgrade 20261116110000", still_at=REV_HALF_DAY)
    assert _has_column(db, "leave_application", "half_day")


def test_110000_downgrade_proceeds_when_every_half_is_also_held_by_a_day_row(
    scratch_at: Callable[[str], str],
) -> None:
    db = scratch_at(REV_HALF_DAY)
    with _conn(db) as c:
        a = _application(c, half_day="FIRST")
        _day(c, a, "FIRST")
        _application(c)  # a full-day application: no half at all
    rc, out = _alembic(db, "downgrade", REV_SHORTFALL)
    assert rc == 0, out[-2000:]
    assert not _has_column(db, "leave_application", "half_day")
    assert _scalar(db, "SELECT count(*) FROM leave_application_day WHERE half = 'FIRST'") == 1


# ------------------------------------------------- 120000: the per-version mark credit ceiling


def _policy_version(conn: psycopg.Connection[Any], **extra: Any) -> uuid.UUID:
    return _insert(conn, "attendance_policy_version", status="DRAFT", **extra)


def test_120000_existing_versions_read_59_and_nothing_else_changes(
    scratch_at: Callable[[str], str],
) -> None:
    db = scratch_at(REV_HALF_DAY)
    with _conn(db) as c:
        _policy_version(c, grace_in_minutes=10)
        _policy_version(c, grace_in_minutes=0)
    before = _scalar(
        db,
        "SELECT md5(string_agg(to_jsonb(t)::text, '|' ORDER BY id::text)) FROM (SELECT id, grace_in_minutes, status FROM attendance_policy_version) t",
    )
    rc, out = _alembic(db, "upgrade", REV_CEILING)
    assert rc == 0, out[-2000:]
    assert _scalar(db, "SELECT count(*) FROM attendance_policy_version") == 2
    assert (
        _scalar(
            db,
            "SELECT count(*) FROM attendance_policy_version WHERE mark_credit_ceiling_minutes = 59",
        )
        == 2
    )
    after = _scalar(
        db,
        "SELECT md5(string_agg(to_jsonb(t)::text, '|' ORDER BY id::text)) FROM (SELECT id, grace_in_minutes, status FROM attendance_policy_version) t",
    )
    assert before == after


@pytest.mark.parametrize(
    "value,ok", [(-1, False), (0, True), (59, True), (120, True), (121, False)]
)
def test_120000_database_enforces_the_0_to_120_range(
    scratch_at: Callable[[str], str], value: int, ok: bool
) -> None:
    db = scratch_at(REV_CEILING)
    with _conn(db, enforce=False) as c:
        if ok:
            _policy_version(c, mark_credit_ceiling_minutes=value)
            assert (
                _scalar(
                    db,
                    "SELECT count(*) FROM attendance_policy_version WHERE mark_credit_ceiling_minutes = %s",
                    value,
                )
                == 1
            )
        else:
            with pytest.raises(pgerr.CheckViolation):
                _policy_version(c, mark_credit_ceiling_minutes=value)


def test_120000_downgrade_refuses_a_configured_value_and_allows_defaults(
    scratch_at: Callable[[str], str],
) -> None:
    db = scratch_at(REV_CEILING)
    with _conn(db) as c:
        _policy_version(c, mark_credit_ceiling_minutes=45)
    out = _refused(db, REV_HALF_DAY, "Refusing to downgrade 20261116120000", still_at=REV_CEILING)
    assert "other than 59" in out
    assert _scalar(db, "SELECT mark_credit_ceiling_minutes FROM attendance_policy_version") == 45
    # put the default back: now the column carries nothing the downgrade would discard
    with _conn(db) as c:
        c.execute("UPDATE attendance_policy_version SET mark_credit_ceiling_minutes = 59")
    rc, out = _alembic(db, "downgrade", REV_HALF_DAY)
    assert rc == 0, out[-2000:]
    assert not _has_column(db, "attendance_policy_version", "mark_credit_ceiling_minutes")
