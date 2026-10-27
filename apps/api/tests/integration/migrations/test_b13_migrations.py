"""B13 Workstreams B and C - migration readiness, proved on SCRATCH databases.

Every test works in a database it creates inside the disposable QA Postgres (a copy of a template
migrated to the revision just before the one under test), never in the run's main database and never
anywhere else; the databases are dropped afterwards. The migrations are run exactly as the harness runs
them (`python -m alembic ... upgrade/downgrade`, `MIGRATIONS_DATABASE_URL` pointing at the scratch DB).
Rows are synthetic and are inserted with FK triggers off (`session_replication_role = replica`) so
the legacy / invalid shapes can be built at all.

B: `20261027091000` partial unique index on live onboarding cases (company, lower(email)).
C: `20261027092000` composite FK attendance_day(company_id, employee_id) -> employee(company_id, id).
"""

# ruff: noqa: E501 - long SQL strings

import os
import subprocess
import sys
import uuid
from collections.abc import Iterator
from datetime import date
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest
from psycopg import errors as pgerr
from psycopg.types.json import Jsonb

REV_BEFORE_B = "20261027090000"
REV_B = "20261027091000"
REV_C = "20261027092000"
INDEX = "onboarding_case_company_live_email_key"
FK = "attendance_day_company_employee_fkey"


def _admin_url() -> str:
    url = os.environ["MIGRATIONS_DATABASE_URL"]
    parts = urlsplit(url)
    # Only the disposable QA server: loopback, the QA private port, a QA-named database.
    assert parts.hostname == "127.0.0.1" and parts.port == 15432, url
    assert parts.path.startswith("/hrms_qa_"), url
    return url


def _url_for(db: str) -> str:
    parts = urlsplit(_admin_url())
    return urlunsplit(parts._replace(path=f"/{db}"))


def _plain(url: str) -> str:
    return url.replace("postgresql+psycopg://", "postgresql://")


def _alembic(db: str, *args: str) -> tuple[int, str]:
    env = {**os.environ, "MIGRATIONS_DATABASE_URL": _url_for(db)}
    proc = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "alembic", "-c", "alembic.ini", *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    return proc.returncode, proc.stdout + proc.stderr


def _admin() -> psycopg.Connection[Any]:
    return psycopg.connect(_plain(_admin_url()), autocommit=True)


def _conn(db: str, *, enforce: bool = False) -> psycopg.Connection[Any]:
    """`enforce=False` (seeding): FK triggers off so legacy / invalid shapes can be built at all;
    scratch DB only. `enforce=True`: a normal session, every constraint live."""
    conn = psycopg.connect(_plain(_url_for(db)), autocommit=True)
    if not enforce:
        conn.execute("SET session_replication_role = replica")
    return conn


@pytest.fixture(scope="module")
def template_db() -> Iterator[str]:
    name = f"b13mig_tpl_{uuid.uuid4().hex[:8]}"
    with _admin() as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    try:
        rc, out = _alembic(name, "upgrade", REV_BEFORE_B)
        assert rc == 0, out[-2000:]
        yield name
    finally:
        with _admin() as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
def scratch(template_db: str) -> Iterator[str]:
    name = f"b13mig_{uuid.uuid4().hex[:8]}"
    with _admin() as admin:
        admin.execute(f'CREATE DATABASE "{name}" TEMPLATE "{template_db}"')
    try:
        yield name
    finally:
        with _admin() as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def _insert(conn: psycopg.Connection[Any], table: str, **values: Any) -> uuid.UUID:
    """Inserts one synthetic row; required columns not given get a type-appropriate dummy."""
    cols = conn.execute(
        "SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name=%s ORDER BY ordinal_position",
        (table,),
    ).fetchall()
    row: dict[str, Any] = {}
    for name, dtype, nullable, default in cols:
        if name in values:
            row[name] = values[name]
        elif nullable == "NO" and default is None:
            row[name] = {
                "uuid": uuid.uuid4(),
                "date": date(2026, 1, 1),
                "boolean": False,
                "integer": 0,
                "bigint": 0,
                "smallint": 0,
                "numeric": 0,
                "jsonb": Jsonb({}),
                "json": Jsonb({}),
            }.get(dtype, "x" if "char" in dtype or dtype == "text" else None)
            if dtype.startswith("timestamp"):
                row[name] = "2026-01-01T00:00:00Z"
    if "id" in {c[0] for c in cols} and "id" not in row:
        row["id"] = uuid.uuid4()
    names = ", ".join(f'"{c}"' for c in row)
    marks = ", ".join(["%s"] * len(row))
    conn.execute(f'INSERT INTO "{table}" ({names}) VALUES ({marks})', list(row.values()))
    return row["id"]  # type: ignore[no-any-return]


def _company(conn: psycopg.Connection[Any], name: str) -> uuid.UUID:
    return _insert(conn, "company", name=name)


def _case(
    conn: psycopg.Connection[Any], company: uuid.UUID, email: str, status: str, **kw: Any
) -> uuid.UUID:
    return _insert(
        conn,
        "onboarding_case",
        company_id=company,
        personal_email=email,
        status=status,
        created_by_user_id=uuid.uuid4(),
        **kw,
    )


def _table_digest(conn: psycopg.Connection[Any], table: str) -> tuple[int, str]:
    row = conn.execute(
        f"SELECT count(*), coalesce(md5(string_agg(to_jsonb(t)::text, '|' ORDER BY t.id::text)), '') "
        f"FROM {table} t"
    ).fetchone()
    assert row is not None
    return int(row[0]), str(row[1])


def _version(db: str) -> str:
    with _conn(db) as c:
        row = c.execute("SELECT version_num FROM alembic_version").fetchone()
    assert row is not None
    return str(row[0])


def _index_def(db: str) -> str | None:
    with _conn(db) as c:
        row = c.execute("SELECT indexdef FROM pg_indexes WHERE indexname=%s", (INDEX,)).fetchone()
    return None if row is None else str(row[0])


# ------------------------------------------------------------------------------ Workstream B


def _legacy_clean_dataset(conn: psycopg.Connection[Any]) -> dict[str, uuid.UUID]:
    c1, c2 = _company(conn, "B13 Co 1"), _company(conn, "B13 Co 2")
    ids = {
        # terminal / deleted history beside ONE live case for the same address: never a conflict
        "live": _case(conn, c1, "dup@example.com", "INVITED"),
        "activated": _case(conn, c1, "dup@example.com", "ACTIVATED"),
        "cancelled": _case(conn, c1, "DUP@example.com", "CANCELLED"),  # legacy mixed case
        "expired": _case(conn, c1, "Dup@Example.com", "EXPIRED"),
        "deleted": _case(conn, c1, "dup@example.com", "DRAFT", deleted_at="2026-02-01T00:00:00Z"),
        # same address, other tenant: allowed
        "other_tenant": _case(conn, c2, "dup@example.com", "INVITED"),
        # distinct address
        "other_address": _case(conn, c1, "someone.else@example.com", "DRAFT"),
    }
    ids["c1"], ids["c2"] = c1, c2
    return ids


def test_b_upgrade_succeeds_with_only_historical_duplicates_and_enforces_the_rule(
    scratch: str,
) -> None:
    with _conn(scratch) as conn:
        ids = _legacy_clean_dataset(conn)
        before = _table_digest(conn, "onboarding_case")

    rc, out = _alembic(scratch, "upgrade", REV_B)
    assert rc == 0, out[-2500:]
    assert _version(scratch) == REV_B

    definition = _index_def(scratch)
    assert definition is not None
    assert "UNIQUE" in definition and "lower((personal_email)::text)" in definition
    assert "deleted_at IS NULL" in definition and "ACTIVATED" in definition

    # (FK triggers stay off for these synthetic inserts; unique indexes are always enforced)
    with _conn(scratch) as conn:
        assert _table_digest(conn, "onboarding_case") == before  # no row touched
        # the live case blocks a second live case for the same company + address, any case
        for variant in ("dup@example.com", "DUP@EXAMPLE.COM", "Dup@example.com"):
            with pytest.raises(pgerr.UniqueViolation) as err:
                _case(conn, ids["c1"], variant, "DRAFT")
            assert err.value.diag.constraint_name == INDEX
        # other tenant, other address and terminal rows remain insertable
        _case(conn, ids["c2"], "fresh@example.com", "DRAFT")
        _case(conn, ids["c1"], "dup@example.com", "CANCELLED")
        # once the live case is terminal the address is free again (status change, same row)
        conn.execute("UPDATE onboarding_case SET status='CANCELLED' WHERE id=%s", (ids["live"],))
        _case(conn, ids["c1"], "dup@example.com", "DRAFT")
        # ... and then it is taken again
        with pytest.raises(pgerr.UniqueViolation):
            _case(conn, ids["c1"], "dup@example.com", "INVITED")


def test_b_conflicting_live_duplicates_fail_safely_with_diagnostics_then_succeed_after_manual_fix(
    scratch: str,
) -> None:
    with _conn(scratch) as conn:
        c1, c2 = _company(conn, "B13 Co 1"), _company(conn, "B13 Co 2")
        exact_a = _case(conn, c1, "same@example.com", "INVITED")  # exact-case duplicate
        exact_b = _case(conn, c1, "same@example.com", "IN_PROGRESS")
        var_a = _case(conn, c1, "Mixed@Example.com", "DRAFT")  # case-variant duplicate (legacy)
        var_b = _case(conn, c1, "mixed@example.com", "SUBMITTED")
        ok_other = _case(conn, c2, "same@example.com", "INVITED")  # other tenant: not a conflict
        _case(conn, c1, "same@example.com", "ACTIVATED")  # history: not a conflict
        digests = {t: _table_digest(conn, t) for t in ("onboarding_case", "company")}

    rc, out = _alembic(scratch, "upgrade", REV_B)
    assert rc != 0
    assert "unique index NOT created, no row was changed" in out
    assert "2 company/e-mail group(s)" in out
    for case_id in (exact_a, exact_b, var_a, var_b):
        assert str(case_id) in out, f"diagnostics must name case {case_id}"
    assert str(ok_other) not in out
    assert "INVITED" in out and "IN_PROGRESS" in out and "SUBMITTED" in out
    assert str(c1) in out and "mixed@example.com" in out

    # fails SAFE: still at the previous revision, no index, nothing deleted/merged/edited
    assert _version(scratch) == REV_BEFORE_B
    assert _index_def(scratch) is None
    with _conn(scratch) as conn:
        assert {t: _table_digest(conn, t) for t in digests} == digests
        # operator decision (not the migration's): cancel one case in each group
        conn.execute(
            "UPDATE onboarding_case SET status='CANCELLED' WHERE id = ANY(%s)", ([exact_b, var_b],)
        )
    rc, out = _alembic(scratch, "upgrade", REV_B)
    assert rc == 0, out[-2500:]
    assert _version(scratch) == REV_B and _index_def(scratch) is not None


def test_b_downgrade_and_reupgrade_are_clean_and_keep_data(scratch: str) -> None:
    with _conn(scratch) as conn:
        _legacy_clean_dataset(conn)
        before = _table_digest(conn, "onboarding_case")
    assert _alembic(scratch, "upgrade", REV_B)[0] == 0
    rc, out = _alembic(scratch, "downgrade", REV_BEFORE_B)
    assert rc == 0, out[-2000:]
    assert _version(scratch) == REV_BEFORE_B and _index_def(scratch) is None
    with _conn(scratch) as conn:
        assert _table_digest(conn, "onboarding_case") == before
    assert _alembic(scratch, "upgrade", REV_B)[0] == 0
    assert _index_def(scratch) is not None


# ------------------------------------------------------------------------------ Workstream C


def _employee(conn: psycopg.Connection[Any], company: uuid.UUID, code: str) -> uuid.UUID:
    return _insert(conn, "employee", company_id=company, employee_code=code, first_name="Syn")


def _day(
    conn: psycopg.Connection[Any], company: uuid.UUID, employee: uuid.UUID, day: date
) -> uuid.UUID:
    return _insert(
        conn,
        "attendance_day",
        company_id=company,
        employee_id=employee,
        attendance_date=day,
        attendance_status="PRESENT",
        timezone="UTC",
    )


def _fk_state(db: str) -> tuple[bool, bool] | None:
    with _conn(db) as c:
        row = c.execute("SELECT convalidated FROM pg_constraint WHERE conname=%s", (FK,)).fetchone()
        uniq = c.execute(
            "SELECT 1 FROM pg_constraint WHERE conname='employee_company_id_id_key'"
        ).fetchone()
    return None if row is None else (bool(row[0]), uniq is not None)


def _at_fk(db: str) -> None:
    assert _alembic(db, "upgrade", REV_B)[0] == 0
    rc, out = _alembic(db, "upgrade", REV_C)
    assert rc == 0, out[-2500:]


def test_c_valid_data_upgrades_and_the_database_enforces_tenant_integrity(scratch: str) -> None:
    with _conn(scratch) as conn:
        a, b = _company(conn, "Tenant A"), _company(conn, "Tenant B")
        emp_a, emp_b = _employee(conn, a, "A1"), _employee(conn, b, "B1")
        _day(conn, a, emp_a, date(2026, 3, 1))
        _day(conn, b, emp_b, date(2026, 3, 1))
        before = _table_digest(conn, "attendance_day")

    _at_fk(scratch)
    assert _version(scratch) == REV_C and _fk_state(scratch) == (True, True)  # validated

    with _conn(scratch, enforce=True) as conn:
        assert _table_digest(conn, "attendance_day") == before
        # valid same-tenant insert and update
        day_id = _day(conn, a, emp_a, date(2026, 3, 2))
        conn.execute(
            "UPDATE attendance_day SET attendance_date=%s WHERE id=%s", (date(2026, 3, 3), day_id)
        )
        # cross-tenant employee reference rejected at the database
        with pytest.raises(pgerr.ForeignKeyViolation) as err:
            _day(conn, a, emp_b, date(2026, 3, 4))
        assert err.value.diag.constraint_name == FK
        # unknown employee rejected
        with pytest.raises(pgerr.ForeignKeyViolation):
            _day(conn, a, uuid.uuid4(), date(2026, 3, 5))
        # bypass attempts on an existing row: change only the employee, or only the company
        with pytest.raises(pgerr.ForeignKeyViolation):
            conn.execute("UPDATE attendance_day SET employee_id=%s WHERE id=%s", (emp_b, day_id))
        with pytest.raises(pgerr.ForeignKeyViolation):
            conn.execute("UPDATE attendance_day SET company_id=%s WHERE id=%s", (b, day_id))
        # moving an employee that has attendance to another company is refused ...
        with pytest.raises(pgerr.ForeignKeyViolation):
            conn.execute("UPDATE employee SET company_id=%s WHERE id=%s", (b, emp_a))
        # ... and so is deleting it (RESTRICT)
        with pytest.raises(pgerr.ForeignKeyViolation):
            conn.execute("DELETE FROM employee WHERE id=%s", (emp_a,))
        # nothing above changed a row
        assert conn.execute(
            "SELECT company_id, employee_id FROM attendance_day WHERE id=%s", (day_id,)
        ).fetchone() == (a, emp_a)


def test_c_existing_cross_tenant_rows_fail_safely_with_diagnostics_then_succeed_after_manual_fix(
    scratch: str,
) -> None:
    assert _alembic(scratch, "upgrade", REV_B)[0] == 0
    with _conn(scratch) as conn:
        a, b = _company(conn, "Tenant A"), _company(conn, "Tenant B")
        emp_a, emp_b = _employee(conn, a, "A1"), _employee(conn, b, "B1")
        good = _day(conn, a, emp_a, date(2026, 3, 1))
        bad_cross = _day(conn, a, emp_b, date(2026, 3, 2))  # tenant A row -> tenant B employee
        bad_orphan = _day(conn, b, uuid.uuid4(), date(2026, 3, 3))  # employee that does not exist
        digest = _table_digest(conn, "attendance_day")

    rc, out = _alembic(scratch, "upgrade", REV_C)
    assert rc != 0
    assert "2 row(s) reference an employee of another company" in out
    assert "no constraint was added, no row was changed" in out
    assert str(bad_cross) in out and str(emp_b) in out and f"employee_company={b}" in out
    assert str(bad_orphan) in out and "employee_company=missing" in out
    assert str(good) not in out

    assert _version(scratch) == REV_B and _fk_state(scratch) is None  # nothing was added
    with _conn(scratch) as conn:
        assert _table_digest(conn, "attendance_day") == digest  # nothing rewritten or deleted
        # deliberate operator remediation, outside the migration
        conn.execute("DELETE FROM attendance_day WHERE id = ANY(%s)", ([bad_cross, bad_orphan],))
    rc, out = _alembic(scratch, "upgrade", REV_C)
    assert rc == 0, out[-2500:]
    assert _fk_state(scratch) == (True, True)


def test_c_downgrade_removes_the_constraints_and_keeps_data(scratch: str) -> None:
    with _conn(scratch) as conn:
        a = _company(conn, "Tenant A")
        emp = _employee(conn, a, "A1")
        _day(conn, a, emp, date(2026, 3, 1))
        before = _table_digest(conn, "attendance_day")
    _at_fk(scratch)
    rc, out = _alembic(scratch, "downgrade", REV_B)
    assert rc == 0, out[-2000:]
    assert _version(scratch) == REV_B and _fk_state(scratch) is None
    with _conn(scratch, enforce=True) as conn:
        assert _table_digest(conn, "attendance_day") == before
        # the pre-existing single-column FK is untouched by both directions
        assert conn.execute(
            "SELECT 1 FROM pg_constraint WHERE conname='attendance_day_employee_id_fkey'"
        ).fetchone()
    assert _alembic(scratch, "upgrade", REV_C)[0] == 0
    assert _fk_state(scratch) == (True, True)


# ------------------------------------------------------- the gap exists without the migrations


def test_before_the_migrations_the_database_accepts_both_invalid_shapes(scratch: str) -> None:
    """Control for B and C: at the previous revision nothing in the database stops a second live case
    for one address, or an attendance row of company A pointing at an employee of company B."""
    with _conn(scratch, enforce=False) as conn:
        a, b = _company(conn, "Tenant A"), _company(conn, "Tenant B")
        _case(conn, a, "x@example.com", "INVITED")
        _case(conn, a, "X@example.com", "INVITED")
        emp_b = _employee(conn, b, "B1")
        _day(conn, a, emp_b, date(2026, 3, 1))
    assert _version(scratch) == REV_BEFORE_B
