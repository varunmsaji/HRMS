"""SC-01 / SC-02 - migration `20261117090000` (one live shift name per company), on SCRATCH databases.

Same approach as `test_shift_tenant_fk_migrations.py`: every test works in a database it creates inside
the disposable QA Postgres (a copy of a template migrated to the revision just before the one under
test) and drops it afterwards. Rows are synthetic.

Owner decisions under test: D-1 (a deactivated shift keeps its name), D-2 (existing values are never
rewritten; collisions and blank names stop the migration with a report instead).

Cases: N1 clean upgrade; N2 duplicates stop it with a full report and change nothing; N3 blank names;
N4 history (deleted shifts) never conflicts; N5 a deactivated shift still conflicts; N6 other
companies never conflict; N7 the rules hold afterwards; N8 downgrade and re-upgrade; N9 stored names
are not rewritten; N10 a writer in flight is waited for and then checked; N11 a lock timeout leaves
nothing half-applied.
"""

# ruff: noqa: E501 - long SQL strings

import threading
import time
import uuid
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from psycopg import errors as pgerr

from .test_b13_migrations import (
    _admin,
    _alembic,
    _company,
    _conn,
    _insert,
    _plain,
    _table_digest,
    _url_for,
    _version,
)

REV_BEFORE = "20261116120000"
REV = "20261117090000"
INDEX = "shift_company_live_name_key"
CHECK = "shift_live_name_not_blank_check"


def _prepare(db: str) -> None:
    """What the repo's init scripts do for a real database: the extensions and the runtime role the
    later migrations grant to (the role is cluster-wide, so it may already exist)."""
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
    name = f"scmig_tpl_{uuid.uuid4().hex[:8]}"
    with _admin() as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    try:
        _prepare(name)  # extensions + the hrms_app role the later migrations grant to
        rc, out = _alembic(name, "upgrade", REV_BEFORE)
        assert rc == 0, out[-2000:]
        yield name
    finally:
        with _admin() as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
def scratch(template_db: str) -> Iterator[str]:
    name = f"scmig_{uuid.uuid4().hex[:8]}"
    with _admin() as admin:
        admin.execute(f'CREATE DATABASE "{name}" TEMPLATE "{template_db}"')
    try:
        yield name
    finally:
        with _admin() as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def _shift(
    conn: psycopg.Connection[Any],
    company: uuid.UUID,
    name: str,
    *,
    active: bool = True,
    deleted: bool = False,
    code: str | None = None,
) -> uuid.UUID:
    return _insert(
        conn,
        "shift",
        company_id=company,
        name=name,
        code=code or f"SHF-{uuid.uuid4().hex[:5]}",
        start_time="09:00",
        end_time="18:00",
        is_active=active,
        deleted_at="2026-01-01T00:00:00Z" if deleted else None,
    )


def _upgrade(db: str) -> tuple[int, str]:
    return _alembic(db, "upgrade", REV)


def _objects(db: str) -> tuple[bool, bool]:
    with _conn(db) as c:
        idx = c.execute("SELECT 1 FROM pg_indexes WHERE indexname = %s", (INDEX,)).fetchone()
        chk = c.execute("SELECT 1 FROM pg_constraint WHERE conname = %s", (CHECK,)).fetchone()
    return idx is not None, chk is not None


def _names(db: str) -> list[str]:
    with _conn(db) as c:
        return [r[0] for r in c.execute("SELECT name FROM shift ORDER BY name, id").fetchall()]


def test_n1_clean_data_upgrades_and_no_row_is_rewritten(scratch: str) -> None:
    with _conn(scratch) as c:
        a, b = _company(c, "A"), _company(c, "B")
        _shift(c, a, "Morning")
        _shift(c, a, "Evening")
        _shift(c, b, "Morning")
        before = _table_digest(c, "shift")
    rc, out = _upgrade(scratch)
    assert rc == 0, out[-2000:]
    assert _version(scratch) == REV
    assert _objects(scratch) == (True, True)
    with _conn(scratch) as c:
        assert _table_digest(c, "shift") == before


def test_n1b_an_empty_shift_table_upgrades(scratch: str) -> None:
    rc, out = _upgrade(scratch)
    assert rc == 0, out[-2000:]
    assert _objects(scratch) == (True, True)


def test_n2_duplicates_stop_the_upgrade_with_a_full_report_and_change_nothing(scratch: str) -> None:
    with _conn(scratch) as c:
        a, b = _company(c, "A"), _company(c, "B")
        first = _shift(c, a, "Morning", code="SHF-001")
        second = _shift(c, a, " MORNING ", code="SHF-002", active=False)
        _shift(c, a, "Evening")
        c1 = _shift(c, b, "Night", code="SHF-010")
        c2 = _shift(c, b, "night", code="SHF-011")
        c3 = _shift(c, b, "NIGHT", code="SHF-012")
        before = _table_digest(c, "shift")

    rc, out = _upgrade(scratch)
    assert rc != 0
    assert "2 duplicate name group(s)" in out and "0 blank" in out, out[-2500:]
    for needle in (str(a), str(b), str(first), str(second), str(c1), str(c2), str(c3)):
        assert needle in out, f"{needle} missing from the report"
    assert "SHF-001" in out and "SHF-012" in out
    assert "active=false" in out  # the inactive duplicate is identified as such
    assert "no row was changed" in out
    assert _version(scratch) == REV_BEFORE
    assert _objects(scratch) == (False, False)
    with _conn(scratch) as c:
        assert _table_digest(c, "shift") == before

    # After a person renames the offenders, the same upgrade goes through.
    with _conn(scratch) as c:
        c.execute("UPDATE shift SET name = 'Morning 2' WHERE id = %s", (second,))
        c.execute("UPDATE shift SET name = 'Night 2' WHERE id = %s", (c2,))
        c.execute("UPDATE shift SET name = 'Night 3' WHERE id = %s", (c3,))
    rc, out = _upgrade(scratch)
    assert rc == 0, out[-2000:]
    assert _objects(scratch) == (True, True)


def test_n3_blank_names_stop_the_upgrade_with_a_report(scratch: str) -> None:
    with _conn(scratch) as c:
        a = _company(c, "A")
        ok = _shift(c, a, "Morning")
        empty = _shift(c, a, "", code="SHF-020")
        spaces = _shift(c, a, "   ", code="SHF-021")
        tabs = _shift(c, a, "\t \n", code="SHF-022")
        before = _table_digest(c, "shift")

    rc, out = _upgrade(scratch)
    assert rc != 0
    assert "3 blank name(s)" in out, out[-2500:]
    for needle in (str(empty), str(spaces), str(tabs), "SHF-020", "SHF-022"):
        assert needle in out
    assert str(ok) not in out  # a good shift is not reported
    assert _version(scratch) == REV_BEFORE and _objects(scratch) == (False, False)
    with _conn(scratch) as c:
        assert _table_digest(c, "shift") == before
        c.execute("UPDATE shift SET name = 'Fixed ' || code WHERE name ~ '^[[:space:]]*$'")
    rc, out = _upgrade(scratch)
    assert rc == 0, out[-2000:]


def test_n3b_blank_and_duplicate_are_reported_together(scratch: str) -> None:
    with _conn(scratch) as c:
        a = _company(c, "A")
        _shift(c, a, "Same")
        _shift(c, a, "same")
        _shift(c, a, " ")
    rc, out = _upgrade(scratch)
    assert rc != 0
    assert "1 blank name(s) and 1 duplicate name group(s)" in out, out[-2500:]


def test_n4_deleted_shifts_never_conflict(scratch: str) -> None:
    with _conn(scratch) as c:
        a = _company(c, "A")
        _shift(c, a, "Morning")
        _shift(c, a, "Morning", deleted=True)
        _shift(c, a, "morning ", deleted=True)
        _shift(c, a, "   ", deleted=True)
    rc, out = _upgrade(scratch)
    assert rc == 0, out[-2000:]
    assert _objects(scratch) == (True, True)


def test_n5_a_deactivated_shift_still_conflicts_with_a_live_one(scratch: str) -> None:
    """D-1: deactivated shifts keep their names."""
    with _conn(scratch) as c:
        a = _company(c, "A")
        _shift(c, a, "Night")
        _shift(c, a, "night", active=False)
    rc, out = _upgrade(scratch)
    assert rc != 0
    assert "1 duplicate name group(s)" in out, out[-2500:]


def test_n6_the_same_name_in_different_companies_is_fine(scratch: str) -> None:
    with _conn(scratch) as c:
        for i in range(5):
            _shift(c, _company(c, f"C{i}"), "Morning")
    rc, out = _upgrade(scratch)
    assert rc == 0, out[-2000:]


def test_n7_the_database_enforces_the_rules_afterwards(scratch: str) -> None:
    with _conn(scratch) as c:
        a, b = _company(c, "A"), _company(c, "B")
        _shift(c, a, "Morning")
        gone = _shift(c, a, "Gone")
        c.execute("UPDATE shift SET deleted_at = now() WHERE id = %s", (gone,))
    assert _upgrade(scratch)[0] == 0

    with _conn(scratch, enforce=True) as c:
        with pytest.raises(pgerr.UniqueViolation):
            _shift(c, a, " MORNING ")
        with pytest.raises(pgerr.CheckViolation):
            _shift(c, a, "   ")
        with pytest.raises(pgerr.CheckViolation):
            c.execute(
                "UPDATE shift SET name = ' ' WHERE company_id = %s AND name = 'Morning'", (a,)
            )
        # Allowed: another company, a released (deleted) name, a blank deleted row, a rename
        # of the only holder, and a name differing by more than case and surrounding spaces.
        _shift(c, b, "Morning")
        _shift(c, a, "Gone")
        _shift(c, a, "   ", deleted=True)
        _shift(c, a, "Morning shift")
        c.execute(
            "UPDATE shift SET name = 'Morning' WHERE company_id = %s AND name = 'Morning'", (a,)
        )
        c.execute(
            "UPDATE shift SET name = 'MORNING' WHERE company_id = %s AND name = 'Morning'", (a,)
        )
        # Soft-deleting frees the name for a new live shift.
        c.execute(
            "UPDATE shift SET deleted_at = now() WHERE company_id = %s AND name = 'MORNING'", (a,)
        )
        _shift(c, a, "morning")


def test_n7b_deactivation_does_not_release_a_name(scratch: str) -> None:
    with _conn(scratch) as c:
        a = _company(c, "A")
        _shift(c, a, "Night")
    assert _upgrade(scratch)[0] == 0
    with _conn(scratch, enforce=True) as c:
        c.execute("UPDATE shift SET is_active = false WHERE company_id = %s", (a,))
        with pytest.raises(pgerr.UniqueViolation):
            _shift(c, a, "night")


def test_n8_downgrade_removes_the_rules_keeps_data_and_reupgrade_is_clean(scratch: str) -> None:
    with _conn(scratch) as c:
        a = _company(c, "A")
        _shift(c, a, "Morning")
        before = _table_digest(c, "shift")
    assert _upgrade(scratch)[0] == 0
    rc, out = _alembic(scratch, "downgrade", REV_BEFORE)
    assert rc == 0, out[-2000:]
    assert _version(scratch) == REV_BEFORE
    assert _objects(scratch) == (False, False)
    with _conn(scratch) as c:
        assert _table_digest(c, "shift") == before
        _shift(c, a, "morning")  # duplicates are possible again, as before the migration
    rc, out = _upgrade(scratch)
    assert rc != 0 and "1 duplicate name group(s)" in out
    with _conn(scratch) as c:
        c.execute("DELETE FROM shift WHERE name = 'morning'")
    assert _upgrade(scratch)[0] == 0


def test_n9_stored_names_are_not_normalised(scratch: str) -> None:
    """D-2: a single shift with padded or mixed-case text keeps it byte for byte."""
    with _conn(scratch) as c:
        a = _company(c, "A")
        _shift(c, a, "  Legacy Padded  ")
        _shift(c, a, "MiXeD CaSe")
    before = _names(scratch)
    assert _upgrade(scratch)[0] == 0
    assert _names(scratch) == before


def test_n10_a_writer_in_flight_is_waited_for_and_its_row_is_checked(scratch: str) -> None:
    """The table is locked before the check, so a shift created while the migration starts cannot
    slip a duplicate in between the check and the index build."""
    with _conn(scratch) as c:
        a = _company(c, "A")
        _shift(c, a, "Morning")
    writer = psycopg.connect(_plain(_url_for(scratch)), autocommit=False)
    result: list[tuple[int, str]] = []
    try:
        _insert(
            writer,
            "shift",
            company_id=a,
            name="MORNING",
            code="SHF-777",
            start_time="09:00",
            end_time="18:00",
        )
        t = threading.Thread(target=lambda: result.append(_upgrade(scratch)))
        t.start()
        time.sleep(4)
        assert not result, "the migration should be waiting for the open write"
        writer.commit()
        t.join(timeout=120)
    finally:
        writer.close()
    assert result, "migration did not return"
    rc, out = result[0]
    assert rc != 0
    assert "1 duplicate name group(s)" in out and "SHF-777" in out, out[-2500:]
    assert _objects(scratch) == (False, False)
    assert _version(scratch) == REV_BEFORE


def test_n11_a_lock_timeout_aborts_cleanly(scratch: str) -> None:
    with _conn(scratch) as c:
        _shift(c, _company(c, "A"), "Morning")
        before = _table_digest(c, "shift")
    holder = psycopg.connect(_plain(_url_for(scratch)), autocommit=False)
    try:
        holder.execute("LOCK TABLE shift IN ACCESS EXCLUSIVE MODE")
        result: list[tuple[int, str]] = []
        t = threading.Thread(target=lambda: result.append(_upgrade(scratch)))
        t.start()
        t.join(timeout=180)
        assert result, "migration did not return"
    finally:
        holder.rollback()
        holder.close()
    rc, out = result[0]
    assert rc != 0
    assert "lock timeout" in out.lower() or "lock_timeout" in out.lower(), out[-1500:]
    assert _version(scratch) == REV_BEFORE
    assert _objects(scratch) == (False, False)
    with _conn(scratch) as c:
        assert _table_digest(c, "shift") == before
    assert _upgrade(scratch)[0] == 0  # and it succeeds once the lock is gone
