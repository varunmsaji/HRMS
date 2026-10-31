"""Stage 11 - migration `20261031090000` (composite shift FKs), proved on SCRATCH databases.

Same approach as `test_b13_migrations.py`: every test works in a database it creates inside the
disposable QA Postgres (a copy of a template migrated to the revision just before the one under
test) and drops it afterwards; the run's main database is never touched. Migrations run exactly as
the harness runs them. Synthetic rows are seeded with FK triggers off (`session_replication_role =
replica`) so legacy invalid shapes can be built at all.

Cases M1-M7 follow docs/blind-audit-2026-10-29/HRMS_STAGE10_SHIFT_COMPOSITE_FK_DESIGN.md section 4;
M8 proves a lock timeout aborts the migration without leaving partial schema changes.
"""

# ruff: noqa: E501 - long SQL strings

import threading
import uuid
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest

from .test_b13_migrations import (
    _admin,
    _alembic,
    _company,
    _conn,
    _employee,
    _insert,
    _plain,
    _table_digest,
    _url_for,
    _version,
)

REV_BEFORE = "20261030090000"
REV = "20261031090000"
UNIQUE = "shift_company_id_id_key"
ROSTER_FK = "shift_roster_company_shift_fkey"
REG_FK = "attendance_regularization_request_company_shift_fkey"


@pytest.fixture(scope="module")
def template_db() -> Iterator[str]:
    name = f"s11mig_tpl_{uuid.uuid4().hex[:8]}"
    with _admin() as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    try:
        rc, out = _alembic(name, "upgrade", REV_BEFORE)
        assert rc == 0, out[-2000:]
        yield name
    finally:
        with _admin() as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
def scratch(template_db: str) -> Iterator[str]:
    name = f"s11mig_{uuid.uuid4().hex[:8]}"
    with _admin() as admin:
        admin.execute(f'CREATE DATABASE "{name}" TEMPLATE "{template_db}"')
    try:
        yield name
    finally:
        with _admin() as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def _shift(conn: psycopg.Connection[Any], company: uuid.UUID, code: str) -> uuid.UUID:
    return _insert(
        conn,
        "shift",
        company_id=company,
        name=code,
        code=code,
        start_time="09:00",
        end_time="18:00",
    )


def _roster(
    conn: psycopg.Connection[Any],
    company: uuid.UUID,
    employee: uuid.UUID,
    shift: uuid.UUID | None,
    day: str,
) -> uuid.UUID:
    return _insert(
        conn,
        "shift_roster",
        company_id=company,
        employee_id=employee,
        shift_id=shift,
        roster_date=day,
        status="DRAFT",
        is_week_off_override=shift is None,
        is_holiday_working_override=False,
    )


def _regularization(
    conn: psycopg.Connection[Any],
    company: uuid.UUID,
    employee: uuid.UUID,
    shift: uuid.UUID | None,
    day: str,
    status: str = "SUBMITTED",
) -> uuid.UUID:
    return _insert(
        conn,
        "attendance_regularization_request",
        company_id=company,
        employee_id=employee,
        requested_shift_id=shift,
        attendance_date=day,
        request_type="WRONG_SHIFT",
        status=status,
        approval_chain="HR",
    )


def _dataset(conn: psycopg.Connection[Any]) -> dict[str, uuid.UUID]:
    """Two companies, one shift and one employee each, all-valid rows plus NULL-shift rows."""
    a, b = _company(conn, "A"), _company(conn, "B")
    ea, eb = _employee(conn, a, "A-1"), _employee(conn, b, "B-1")
    sa, sb = _shift(conn, a, "SA"), _shift(conn, b, "SB")
    return {
        "a": a,
        "b": b,
        "ea": ea,
        "eb": eb,
        "sa": sa,
        "sb": sb,
        "roster_ok": _roster(conn, a, ea, sa, "2026-09-01"),
        "roster_null": _roster(conn, a, ea, None, "2026-09-02"),
        "reg_ok": _regularization(conn, a, ea, sa, "2026-09-01"),
        "reg_null": _regularization(conn, a, ea, None, "2026-09-02"),
    }


def _digests(db: str) -> dict[str, tuple[int, str]]:
    with _conn(db, enforce=True) as c:
        return {
            t: _table_digest(c, t)
            for t in (
                "company",
                "employee",
                "shift",
                "shift_roster",
                "attendance_regularization_request",
            )
        }


def _constraints(db: str) -> dict[str, tuple[str, bool]]:
    with _conn(db, enforce=True) as c:
        rows = c.execute(
            "SELECT conname, pg_get_constraintdef(oid), convalidated FROM pg_constraint "
            "WHERE conname IN (%s, %s, %s)",
            (UNIQUE, ROSTER_FK, REG_FK),
        ).fetchall()
    return {r[0]: (r[1], r[2]) for r in rows}


def _upgrade(db: str) -> tuple[int, str]:
    return _alembic(db, "upgrade", REV)


def test_m1_clean_data_upgrades_and_the_constraints_are_validated(scratch: str) -> None:
    with _conn(scratch) as c:
        _dataset(c)
    before = _digests(scratch)
    rc, out = _upgrade(scratch)
    assert rc == 0, out[-2000:]
    assert _version(scratch) == REV
    found = _constraints(scratch)
    assert set(found) == {UNIQUE, ROSTER_FK, REG_FK}
    assert all(validated for _, validated in found.values())
    assert "UNIQUE (company_id, id)" in found[UNIQUE][0]
    assert (
        "FOREIGN KEY (company_id, shift_id) REFERENCES shift(company_id, id)" in found[ROSTER_FK][0]
    )
    assert "ON DELETE SET NULL (shift_id)" in found[ROSTER_FK][0]
    assert "ON DELETE SET NULL (requested_shift_id)" in found[REG_FK][0]
    assert _digests(scratch) == before  # no business row changed


def test_m2_cross_company_roster_aborts_before_ddl_with_row_ids_then_succeeds_after_manual_fix(
    scratch: str,
) -> None:
    with _conn(scratch) as c:
        d = _dataset(c)
        bad = _roster(c, d["a"], d["ea"], d["sb"], "2026-09-03")  # A's roster -> B's shift
    before = _digests(scratch)
    rc, out = _upgrade(scratch)
    assert rc != 0
    assert str(bad) in out and str(d["sb"]) in out and str(d["b"]) in out  # actionable identifiers
    assert "no constraint was added, no row was changed" in out
    assert _version(scratch) == REV_BEFORE
    assert _constraints(scratch) == {}
    assert _digests(scratch) == before  # nothing altered automatically

    with _conn(scratch) as c:  # the deliberate, manual correction
        c.execute(
            "UPDATE shift_roster SET shift_id = NULL, is_week_off_override = true WHERE id = %s",
            (bad,),
        )
    rc, out = _upgrade(scratch)
    assert rc == 0, out[-2000:]
    assert set(_constraints(scratch)) == {UNIQUE, ROSTER_FK, REG_FK}


def test_m3_cross_company_regularization_aborts_before_ddl_with_row_ids_then_succeeds(
    scratch: str,
) -> None:
    with _conn(scratch) as c:
        d = _dataset(c)
        bad = _regularization(c, d["a"], d["ea"], d["sb"], "2026-09-03")
    before = _digests(scratch)
    rc, out = _upgrade(scratch)
    assert rc != 0
    assert str(bad) in out and str(d["sb"]) in out
    assert _version(scratch) == REV_BEFORE and _constraints(scratch) == {}
    assert _digests(scratch) == before

    with _conn(scratch) as c:
        c.execute(
            "UPDATE attendance_regularization_request SET requested_shift_id = NULL WHERE id = %s",
            (bad,),
        )
    rc, out = _upgrade(scratch)
    assert rc == 0, out[-2000:]
    assert set(_constraints(scratch)) == {UNIQUE, ROSTER_FK, REG_FK}


def test_m4_null_shift_references_upgrade_untouched(scratch: str) -> None:
    with _conn(scratch) as c:
        a = _company(c, "A")
        e = _employee(c, a, "A-1")
        _roster(c, a, e, None, "2026-09-01")
        _regularization(c, a, e, None, "2026-09-01")
    before = _digests(scratch)
    rc, out = _upgrade(scratch)
    assert rc == 0, out[-2000:]
    assert _digests(scratch) == before
    with _conn(scratch, enforce=True) as c:
        assert c.execute("SELECT count(*) FROM shift_roster WHERE shift_id IS NULL").fetchone() == (
            1,
        )


def test_m5_orphaned_shift_reference_aborts_with_missing_listed(scratch: str) -> None:
    ghost = uuid.uuid4()
    with _conn(scratch) as c:  # FK triggers off: only way to build the orphan
        a = _company(c, "A")
        e = _employee(c, a, "A-1")
        bad_r = _roster(c, a, e, ghost, "2026-09-01")
        bad_q = _regularization(c, a, e, ghost, "2026-09-01")
    before = _digests(scratch)
    rc, out = _upgrade(scratch)
    assert rc != 0
    assert str(bad_r) in out and str(bad_q) in out and "shift_company=missing" in out
    assert _version(scratch) == REV_BEFORE and _constraints(scratch) == {}
    assert _digests(scratch) == before


def test_m6_downgrade_then_reupgrade_is_clean_and_loses_no_rows(scratch: str) -> None:
    with _conn(scratch) as c:
        _dataset(c)
    assert _upgrade(scratch)[0] == 0
    upgraded = _digests(scratch)
    rc, out = _alembic(scratch, "downgrade", REV_BEFORE)
    assert rc == 0, out[-2000:]
    assert _version(scratch) == REV_BEFORE
    assert _constraints(scratch) == {}
    assert _digests(scratch) == upgraded  # downgrade changed no row
    with _conn(scratch, enforce=True) as c:  # the original single-column FKs are still there
        left = {
            r[0]
            for r in c.execute(
                "SELECT conname FROM pg_constraint WHERE conname IN "
                "('shift_roster_shift_id_fkey','attendance_regularization_request_requested_shift_id_fkey')"
            )
        }
    assert len(left) == 2
    rc, out = _upgrade(scratch)
    assert rc == 0, out[-2000:]
    assert set(_constraints(scratch)) == {UNIQUE, ROSTER_FK, REG_FK}
    assert _digests(scratch) == upgraded


def _upgrade_sql() -> str:
    """The exact SQL the migration's `upgrade()` hands to `op.execute`."""
    import importlib.util
    from pathlib import Path
    from unittest import mock

    path = Path(__file__).parents[3] / "alembic" / "versions" / f"{REV}_shift_tenant_fk.py"
    spec = importlib.util.spec_from_file_location("shift_tenant_fk_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    captured: list[str] = []
    with mock.patch.object(module.op, "execute", side_effect=captured.append):
        module.upgrade()
    assert len(captured) == 1
    return captured[0]


def test_m7_role_subject_to_rls_is_refused(scratch: str) -> None:
    # alembic itself cannot even read `alembic_version` as the runtime role, so the guard is proved
    # by running the migration's own SQL on a `hrms_app` connection to the scratch database.
    parts = urlsplit(_url_for(scratch))
    host = parts.netloc.rsplit("@", 1)[-1]
    app_url = _plain(urlunsplit(parts._replace(netloc=f"hrms_app:hrms_app_dev_password@{host}")))
    with _conn(scratch) as c:
        _dataset(c)
    before = _digests(scratch)
    with psycopg.connect(app_url, autocommit=False) as app:
        with pytest.raises(psycopg.errors.RaiseException, match="subject to row-level security"):
            app.execute(_upgrade_sql())
        app.rollback()
    assert _version(scratch) == REV_BEFORE and _constraints(scratch) == {}
    assert _digests(scratch) == before


def test_m8_lock_timeout_aborts_cleanly_without_partial_schema_changes(scratch: str) -> None:
    with _conn(scratch) as c:
        _dataset(c)
    before = _digests(scratch)
    holder = psycopg.connect(_plain(_url_for(scratch)), autocommit=False)
    try:
        holder.execute("LOCK TABLE shift IN ACCESS EXCLUSIVE MODE")
        result: list[tuple[int, str]] = []
        t = threading.Thread(target=lambda: result.append(_upgrade(scratch)))
        t.start()
        t.join(timeout=120)
        assert result, "migration did not return"
    finally:
        holder.rollback()
        holder.close()
    rc, out = result[0]
    assert rc != 0
    assert "lock timeout" in out.lower() or "lock_timeout" in out.lower(), out[-1500:]
    assert _version(scratch) == REV_BEFORE
    assert _constraints(scratch) == {}  # transactional: nothing half-applied
    assert _digests(scratch) == before
    assert _upgrade(scratch)[0] == 0  # and it succeeds once the lock is gone
