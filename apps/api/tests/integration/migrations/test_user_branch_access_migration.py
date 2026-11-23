"""Migration `20261122090000` (admin-assigned branch access), on SCRATCH databases.

Same approach as `test_shift_name_unique_migration.py`: each test works in a database it creates
inside the disposable QA Postgres (a copy of a template migrated to the revision just before the one
under test) and drops it afterwards. Rows are synthetic.

Cases: U1 clean upgrade creates the table, the invite column and FORCE RLS; U2 the backfill keeps
existing reach: HR gets every live branch, a branch manager only the branch of their current
assignment, nobody else anything; U3 the database refuses a branch of
another company; U4 one live row per (company, user, branch), history is allowed; U5 tenant
isolation holds for the runtime role; U6 downgrade and re-upgrade are clean and the backfill is
idempotent; U7 an empty database upgrades.
"""

# ruff: noqa: E501 - long SQL strings

import uuid
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import psycopg
import pytest
from psycopg import errors as pgerr

from .test_b13_migrations import (
    _admin,
    _admin_url,
    _alembic,
    _company,
    _conn,
    _insert,
    _plain,
    _url_for,
    _version,
)
from .test_shift_name_unique_migration import _prepare

REV_BEFORE = "20261117090000"
REV = "20261122090000"


@pytest.fixture(scope="module")
def template_db() -> Iterator[str]:
    name = f"ubamig_tpl_{uuid.uuid4().hex[:8]}"
    with _admin() as admin:
        admin.execute(f'CREATE DATABASE "{name}"')
    try:
        _prepare(name)
        rc, out = _alembic(name, "upgrade", REV_BEFORE)
        assert rc == 0, out[-2000:]
        yield name
    finally:
        with _admin() as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


@pytest.fixture
def scratch(template_db: str) -> Iterator[str]:
    name = f"ubamig_{uuid.uuid4().hex[:8]}"
    with _admin() as admin:
        admin.execute(f'CREATE DATABASE "{name}" TEMPLATE "{template_db}"')
    try:
        yield name
    finally:
        with _admin() as admin:
            admin.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')


def _upgrade(db: str) -> tuple[int, str]:
    return _alembic(db, "upgrade", REV)


def _branch(
    c: psycopg.Connection[Any],
    company: uuid.UUID,
    name: str,
    *,
    active: bool = True,
    deleted: bool = False,
) -> uuid.UUID:
    return _insert(
        c,
        "branch",
        company_id=company,
        name=name,
        is_active=active,
        deleted_at="2026-01-01T00:00:00Z" if deleted else None,
    )


def _role(c: psycopg.Connection[Any], company: uuid.UUID, code: str) -> uuid.UUID:
    return _insert(
        c, "role", company_id=company, code=code, name=code, is_system=True, deleted_at=None
    )


def _user(
    c: psycopg.Connection[Any], company: uuid.UUID, roles: dict[str, uuid.UUID], *codes: str
) -> uuid.UUID:
    """A user with a membership in `company` holding the given role codes."""
    user_id = _insert(c, "user", email=f"{uuid.uuid4().hex}@example.test")
    membership = _insert(c, "user_company", company_id=company, user_id=user_id, status="ACTIVE")
    for code in codes:
        _insert(c, "user_role", user_company_id=membership, role_id=roles[code])
    return user_id


def _place(
    c: psycopg.Connection[Any],
    company: uuid.UUID,
    user_id: uuid.UUID,
    branch_id: uuid.UUID,
    *,
    past_branch_id: uuid.UUID | None = None,
) -> None:
    """Links an employee to `user_id` and gives them a CURRENT assignment at `branch_id` (and,
    optionally, an ended one at `past_branch_id`)."""
    employee = _insert(
        c,
        "employee",
        company_id=company,
        user_id=user_id,
        employee_code=f"E{uuid.uuid4().hex[:8]}",
        deleted_at=None,
    )
    if past_branch_id is not None:
        _insert(
            c,
            "employee_assignment",
            company_id=company,
            employee_id=employee,
            branch_id=past_branch_id,
            effective_from="2025-01-01",
            effective_to="2025-12-31",
            deleted_at=None,
        )
    _insert(
        c,
        "employee_assignment",
        company_id=company,
        employee_id=employee,
        branch_id=branch_id,
        effective_from="2026-01-01",
        effective_to=None,
        deleted_at=None,
    )


def _rows(db: str, company: uuid.UUID | None = None) -> dict[uuid.UUID, set[uuid.UUID]]:
    sql = "SELECT user_id, branch_id FROM user_branch_access WHERE deleted_at IS NULL"
    args: tuple[Any, ...] = ()
    if company is not None:
        sql += " AND company_id = %s"
        args = (company,)
    out: dict[uuid.UUID, set[uuid.UUID]] = {}
    with _conn(db) as c:
        for user_id, branch_id in c.execute(sql, args).fetchall():
            out.setdefault(user_id, set()).add(branch_id)
    return out


def _seed(db: str) -> dict[str, Any]:
    """Company A: branches b1, b2 live, b3 inactive, b4 deleted. Company B: one live branch."""
    with _conn(db) as c:
        a, b = _company(c, "A"), _company(c, "B")
        b1, b2 = _branch(c, a, "Bengaluru"), _branch(c, a, "Mumbai")
        closed = _branch(c, a, "Closed", active=False)
        _branch(c, a, "Gone", deleted=True)
        bb = _branch(c, b, "Delhi")
        roles_a = {
            code: _role(c, a, code)
            for code in ("COMPANY_ADMIN", "HR_ADMIN", "BRANCH_MANAGER", "EMPLOYEE")
        }
        roles_b = {
            code: _role(c, b, code)
            for code in ("COMPANY_ADMIN", "HR_ADMIN", "BRANCH_MANAGER", "EMPLOYEE")
        }
        bm = _user(c, a, roles_a, "BRANCH_MANAGER")
        _place(c, a, bm, b1, past_branch_id=b2)  # current: Bengaluru; Mumbai is history
        bm_mumbai = _user(c, a, roles_a, "BRANCH_MANAGER")
        _place(c, a, bm_mumbai, b2)
        bm_closed = _user(c, a, roles_a, "BRANCH_MANAGER")
        _place(c, a, bm_closed, closed)  # placed at a branch that is no longer active
        both = _user(c, a, roles_a, "HR_ADMIN", "BRANCH_MANAGER")
        _place(c, a, both, b1)
        return {
            "a": a,
            "b": b,
            "b1": b1,
            "b2": b2,
            "bb": bb,
            "hr": _user(c, a, roles_a, "HR_ADMIN"),
            "bm": bm,
            "bm_mumbai": bm_mumbai,
            "bm_closed": bm_closed,
            "bm_unplaced": _user(c, a, roles_a, "BRANCH_MANAGER"),  # no employee at all
            "both": both,
            "admin_hr": _user(c, a, roles_a, "COMPANY_ADMIN", "HR_ADMIN"),
            "admin": _user(c, a, roles_a, "COMPANY_ADMIN"),
            "emp": _user(c, a, roles_a, "EMPLOYEE"),
            "hr_b": _user(c, b, roles_b, "HR_ADMIN"),
        }


def test_u1_clean_upgrade_creates_the_table_the_column_and_force_rls(scratch: str) -> None:
    rc, out = _upgrade(scratch)
    assert rc == 0, out[-2000:]
    assert _version(scratch) == REV
    with _conn(scratch) as c:
        rls = c.execute(
            "SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = 'user_branch_access'"
        ).fetchone()
        policy = c.execute(
            "SELECT 1 FROM pg_policies WHERE tablename = 'user_branch_access' AND policyname = 'tenant_isolation'"
        ).fetchone()
        column = c.execute(
            "SELECT data_type, is_nullable FROM information_schema.columns "
            "WHERE table_name = 'account_invite' AND column_name = 'branch_ids'"
        ).fetchone()
    assert rls == (True, True)
    assert policy is not None
    assert column == ("ARRAY", "NO")


def test_u2_backfill_keeps_existing_reach_and_gives_nobody_else_anything(scratch: str) -> None:
    s = _seed(scratch)
    rc, out = _upgrade(scratch)
    assert rc == 0, out[-2000:]
    live = {s["b1"], s["b2"]}  # not the inactive and not the deleted branch
    rows = _rows(scratch)
    assert rows[s["hr"]] == live  # HR was company-wide
    assert rows[s["both"]] == live  # HR + branch manager: HR's reach
    assert rows[s["hr_b"]] == {s["bb"]}  # only its own company's branch
    # A branch manager's scope was their own CURRENT branch: not every branch, and not history.
    assert rows[s["bm"]] == {s["b1"]}
    assert rows[s["bm_mumbai"]] == {s["b2"]}
    # No current live branch, no row: they saw no one before and still see no one.
    for none in ("bm_closed", "bm_unplaced", "admin_hr", "admin", "emp"):
        assert s[none] not in rows, f"{none} must get no rows"


def test_u3_the_database_refuses_a_branch_of_another_company(scratch: str) -> None:
    s = _seed(scratch)
    rc, out = _upgrade(scratch)
    assert rc == 0, out[-2000:]
    with _conn(scratch, enforce=True) as c:
        with pytest.raises(pgerr.ForeignKeyViolation):
            c.execute(
                "INSERT INTO user_branch_access (company_id, user_id, branch_id) VALUES (%s, %s, %s)",
                (s["a"], s["hr"], s["bb"]),  # company A row, company B's branch
            )
        with pytest.raises(pgerr.ForeignKeyViolation):
            c.execute(
                "INSERT INTO user_branch_access (company_id, user_id, branch_id) VALUES (%s, %s, %s)",
                (s["a"], uuid.uuid4(), s["b1"]),  # unknown user
            )


def test_u4_one_live_row_per_user_and_branch_but_history_is_allowed(scratch: str) -> None:
    s = _seed(scratch)
    rc, out = _upgrade(scratch)
    assert rc == 0, out[-2000:]
    insert = "INSERT INTO user_branch_access (company_id, user_id, branch_id) VALUES (%s, %s, %s)"
    with _conn(scratch, enforce=True) as c:
        with pytest.raises(pgerr.UniqueViolation):
            c.execute(insert, (s["a"], s["hr"], s["b1"]))  # the backfill already made this row
        c.execute(
            "UPDATE user_branch_access SET deleted_at = now() WHERE user_id = %s AND branch_id = %s",
            (s["hr"], s["b1"]),
        )
        c.execute(
            insert, (s["a"], s["hr"], s["b1"])
        )  # soft-deleted history does not block a new live row
    assert _rows(scratch)[s["hr"]] == {s["b1"], s["b2"]}


def test_u5_tenant_isolation_holds_for_the_runtime_role(scratch: str) -> None:
    s = _seed(scratch)
    rc, out = _upgrade(scratch)
    assert rc == 0, out[-2000:]
    parts = urlsplit(_admin_url())
    app_url = _plain(
        urlunsplit(
            parts._replace(
                netloc=f"hrms_app:migtest-only@{parts.hostname}:{parts.port}", path=f"/{scratch}"
            )
        )
    )
    with psycopg.connect(app_url, autocommit=True) as app:
        assert app.execute("SELECT count(*) FROM user_branch_access").fetchone() == (
            0,
        )  # no tenant set
        app.execute("SELECT set_config('app.company_id', %s, false)", (str(s["a"]),))
        seen = app.execute("SELECT DISTINCT company_id FROM user_branch_access").fetchall()
        assert seen == [(s["a"],)]
        app.execute("SELECT set_config('app.company_id', %s, false)", (str(s["b"]),))
        assert app.execute("SELECT count(*) FROM user_branch_access").fetchone() == (1,)
        with pytest.raises(pgerr.InsufficientPrivilege):  # cannot write a row for the other company
            app.execute(
                "INSERT INTO user_branch_access (company_id, user_id, branch_id) VALUES (%s, %s, %s)",
                (s["a"], s["hr"], s["b1"]),
            )


def test_u6_downgrade_and_reupgrade_are_clean_and_the_backfill_is_idempotent(scratch: str) -> None:
    s = _seed(scratch)
    rc, out = _upgrade(scratch)
    assert rc == 0, out[-2000:]
    first = _rows(scratch)
    rc, out = _alembic(scratch, "downgrade", REV_BEFORE)
    assert rc == 0, out[-2000:]
    assert _version(scratch) == REV_BEFORE
    with _conn(scratch) as c:
        assert c.execute("SELECT to_regclass('user_branch_access')").fetchone() == (None,)
        assert (
            c.execute(
                "SELECT 1 FROM information_schema.columns WHERE table_name = 'account_invite' AND column_name = 'branch_ids'"
            ).fetchone()
            is None
        )
        # The parent key belongs to an earlier migration (geofencing) and must survive.
        assert (
            c.execute(
                "SELECT 1 FROM pg_constraint WHERE conname = 'branch_company_id_id_key'"
            ).fetchone()
            is not None
        )
        assert c.execute(
            "SELECT count(*) FROM branch WHERE company_id = %s", (s["a"],)
        ).fetchone() == (4,)
    rc, out = _upgrade(scratch)
    assert rc == 0, out[-2000:]
    assert _rows(scratch) == first


def test_u7_an_empty_database_upgrades(scratch: str) -> None:
    rc, out = _upgrade(scratch)
    assert rc == 0, out[-2000:]
    assert _rows(scratch) == {}
    assert _url_for(scratch)  # keeps the helper import honest


def test_u8_hard_deleting_a_branch_or_user_takes_its_access_rows_with_it(scratch: str) -> None:
    s = _seed(scratch)
    rc, out = _upgrade(scratch)
    assert rc == 0, out[-2000:]
    with _conn(scratch, enforce=True) as c:
        c.execute("DELETE FROM branch WHERE id = %s", (s["b2"],))
        assert c.execute(
            "SELECT count(*) FROM user_branch_access WHERE branch_id = %s", (s["b2"],)
        ).fetchone() == (0,)
        c.execute("DELETE FROM user_branch_access WHERE user_id = %s", (s["hr"],))
        c.execute(
            "DELETE FROM user_role WHERE user_company_id IN (SELECT id FROM user_company WHERE user_id = %s)",
            (s["bm"],),
        )
        c.execute("DELETE FROM user_company WHERE user_id = %s", (s["bm"],))
        c.execute('DELETE FROM "user" WHERE id = %s', (s["bm"],))
        assert s["bm"] not in _rows(scratch)
