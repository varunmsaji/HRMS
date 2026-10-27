"""Helpers for the loopback browser stack. Every command refuses a shared database.

Passwords stay in the environment and are never printed. The employee test password is the
same synthetic value the API integration suite already uses; it is not written to artifacts.
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import date
from urllib.parse import urlparse

import psycopg

FORBIDDEN_DB_NAMES = {"hrms_dev", "hrms", "postgres"}
FORBIDDEN_PORTS = {5432, 5433, 6379, 6380}
# Synthetic password. Not printed. Matches the API integration fixtures.
_EMPLOYEE_PASSWORD = "CorrectHorse9"


def _url(name: str) -> str:
    value = __import__("os").environ.get(name, "")
    if not value:
        raise SystemExit(f"ABORT: {name} is not set")
    if "hrms_dev" in value or ":5433/" in value or ":6380" in value:
        raise SystemExit(f"ABORT: {name} points at a shared service")
    return value


def _connect(url: str):
    parsed = urlparse(url)
    if parsed.hostname != "127.0.0.1":
        raise SystemExit(f"ABORT: database host is {parsed.hostname}, not loopback")
    if parsed.port in FORBIDDEN_PORTS or parsed.port is None:
        raise SystemExit(f"ABORT: database port {parsed.port} is not the disposable port")
    db = (parsed.path or "/").lstrip("/")
    if not db.startswith("hrms_browser_") or db in FORBIDDEN_DB_NAMES:
        raise SystemExit(f"ABORT: refusing database {db}")
    return psycopg.connect(url), db, parsed


def _expect_run(conn, run: str) -> None:
    marker = conn.execute("select run from qa.disposable").fetchone()
    if marker is None or marker[0] != run:
        raise SystemExit("ABORT: disposable marker does not match this run")
    current = conn.execute("select current_database()").fetchone()[0]
    if current.startswith("hrms_dev") or not current.startswith("hrms_browser_"):
        raise SystemExit(f"ABORT: connected to {current}")


def prove(run: str, out_path: str) -> None:
    from hrms.core.config.settings import get_settings

    app_url = _url("DATABASE_URL")
    mig_url = _url("MIGRATIONS_DATABASE_URL")
    redis_url = _url("REDIS_URL")
    redis = urlparse(redis_url)
    if redis.hostname != "127.0.0.1" or redis.port in FORBIDDEN_PORTS:
        raise SystemExit("ABORT: redis URL is not the disposable instance")

    settings = get_settings()
    effective = settings.database_url
    if "hrms_dev" in effective or ":5433" in effective:
        raise SystemExit("ABORT: effective application database URL is the shared database")
    if "hrms_browser_" not in effective:
        raise SystemExit("ABORT: effective application database is not a browser database")
    if not settings.redis_url.startswith("redis://127.0.0.1:16380/"):
        raise SystemExit(f"ABORT: effective redis is {settings.redis_url}")

    with _connect(app_url)[0] as app_conn:
        app_user, app_db = app_conn.execute("select current_user, current_database()").fetchone()
        if not str(app_db).startswith("hrms_browser_") or str(app_db) in FORBIDDEN_DB_NAMES:
            raise SystemExit(f"ABORT: application connected to {app_db}")
    with _connect(mig_url)[0] as mig_conn:
        _expect_run(mig_conn, run)
        mig_user, mig_db = mig_conn.execute("select current_user, current_database()").fetchone()
        if mig_db != app_db:
            raise SystemExit("ABORT: application and migration connections are different databases")

    if app_user != "hrms_app":
        raise SystemExit(f"ABORT: application role is {app_user}, expected hrms_app")
    if mig_user != "hrms":
        raise SystemExit(f"ABORT: migration role is {mig_user}, expected hrms")
    if app_db in FORBIDDEN_DB_NAMES:
        raise SystemExit(f"ABORT: connected to {app_db}")

    payload = {
        "all_ok": True,
        "run": run,
        "database": app_db,
        "database_host": "127.0.0.1",
        "database_port": 15433,
        "database_user": app_user,
        "migrations_user": mig_user,
        "redis": "127.0.0.1:16380/2",
        "cors_origin": list(settings.effective_cors_origins),
        "shared_dev_database": False,
        "loopback_only": True,
    }
    with open(out_path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    print(
        f"ISOLATION PROVED run={run} database={app_db} user={app_user} "
        f"redis=127.0.0.1:16380/2 cors={payload['cors_origin']}"
    )


def assert_proven(path: str, run: str) -> None:
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    if payload.get("all_ok") is not True or payload.get("run") != run:
        raise SystemExit("ABORT: isolation proof missing or for a different run")
    if payload.get("database_port") != 15433 or payload.get("shared_dev_database") is not False:
        raise SystemExit("ABORT: isolation proof is not for the loopback browser database")
    prove(run, path)


def _uuid(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise SystemExit(f"ABORT: not a uuid: {value}") from exc


def _owner():
    conn, db, _parsed = _connect(_url("MIGRATIONS_DATABASE_URL"))
    return conn, db


def hashes(company_id: str) -> None:
    company_id = _uuid(company_id)
    tables = (
        "leave_application",
        "leave_application_day",
        "leave_ledger",
        "attendance_day",
        "attendance_period",
        "pay_run",
        "holiday",
        "calendar_exception",
    )
    out: dict[str, dict[str, object]] = {}
    with _owner()[0] as conn:
        for table in tables:
            count, digest = conn.execute(
                f"SELECT count(*), coalesce(md5(string_agg(t::text, '|' ORDER BY t.id::text)), '') "
                f"FROM {table} t WHERE company_id = %s",
                (company_id,),
            ).fetchone()
            out[table] = {"count": int(count), "md5": digest}
    json.dump(out, sys.stdout)
    sys.stdout.write("\n")


def verify_email(email: str) -> None:
    if "@" not in email or len(email) > 200:
        raise SystemExit("ABORT: refusing email")
    with _owner()[0] as conn:
        row = conn.execute(
            'UPDATE "user" SET email_verified_at = now() '
            "WHERE email = %s AND email_verified_at IS NULL RETURNING id",
            (email,),
        ).fetchone()
        conn.commit()
    print(f"verified_rows={0 if row is None else 1}")


def link_employee(company_id: str, employee_id: str, email: str) -> None:
    from hrms.core.auth.passwords import hash_password

    company_id = _uuid(company_id)
    employee_id = _uuid(employee_id)
    if not email.endswith("@example.com"):
        raise SystemExit("ABORT: employee login must be an example.com address")
    password_hash = hash_password(_EMPLOYEE_PASSWORD)
    user_id = str(uuid.uuid4())
    membership_id = str(uuid.uuid4())
    with _owner()[0] as conn:
        role = conn.execute(
            "SELECT id FROM role WHERE company_id = %s AND code = 'EMPLOYEE'",
            (company_id,),
        ).fetchone()
        if role is None:
            raise SystemExit("ABORT: company has no EMPLOYEE role")
        conn.execute(
            'INSERT INTO "user" (id, email, password_hash, first_name, last_name, '
            "email_verified_at, status, mfa_enabled, failed_login_count, version, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, now(), 'ACTIVE', false, 0, 1, now(), now())",
            (user_id, email, password_hash, "Synthetic", "Employee"),
        )
        conn.execute(
            "INSERT INTO user_company (id, company_id, user_id, is_primary, status, created_at, updated_at) "
            "VALUES (%s, %s, %s, true, 'ACTIVE', now(), now())",
            (membership_id, company_id, user_id),
        )
        conn.execute(
            "INSERT INTO user_role (id, user_company_id, role_id) VALUES (%s, %s, %s)",
            (str(uuid.uuid4()), membership_id, role[0]),
        )
        updated = conn.execute(
            "UPDATE employee SET user_id = %s WHERE id = %s AND company_id = %s AND user_id IS NULL "
            "RETURNING id",
            (user_id, employee_id, company_id),
        ).fetchone()
        if updated is None:
            raise SystemExit("ABORT: employee was not linked")
        conn.commit()
    print(f"linked_employee={employee_id}")


def insert_protected(company_id: str, legal_entity_id: str, start: str, end: str) -> None:
    company_id = _uuid(company_id)
    legal_entity_id = _uuid(legal_entity_id)
    start_d = date.fromisoformat(start)
    end_d = date.fromisoformat(end)
    period_id = str(uuid.uuid4())
    pay_id = str(uuid.uuid4())
    with _owner()[0] as conn:
        conn.execute(
            "INSERT INTO attendance_period "
            "(id, company_id, legal_entity_id, period_start, period_end, status, opened_at, "
            "version, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, 'CLOSED', now(), 1, now(), now())",
            (period_id, company_id, legal_entity_id, start_d, end_d),
        )
        conn.execute(
            "INSERT INTO pay_run "
            "(id, company_id, legal_entity_id, period_month, period_start, period_end, "
            "days_in_month, status, pay_date, attendance_period_id, attendance_period_version, "
            "employee_count, gross_minor, deductions_minor, employer_contributions_minor, net_minor, "
            "error_count, warning_count, variance_flag_count, variance_open_count, finalised_at, "
            "version, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, 'FINALISED', %s, %s, 1, "
            "0, 0, 0, 0, 0, 0, 0, 0, 0, now(), 1, now(), now())",
            (
                pay_id,
                company_id,
                legal_entity_id,
                start_d.replace(day=1),
                start_d,
                end_d,
                (end_d - start_d).days + 1,
                end_d,
                period_id,
            ),
        )
        conn.commit()
    print(f"protected_period={period_id}")


def mark_pending(company_id: str, day: str) -> None:
    company_id = _uuid(company_id)
    date.fromisoformat(day)
    with _owner()[0] as conn:
        row = conn.execute(
            "UPDATE leave_application SET status = 'SUBMITTED' "
            "WHERE company_id = %s AND status = 'APPROVED' AND id IN ("
            "  SELECT leave_application_id FROM leave_application_day "
            "  WHERE company_id = %s AND calendar_date = %s"
            ") RETURNING id",
            (company_id, company_id, day),
        ).fetchone()
        conn.commit()
    print(f"pending_rows={0 if row is None else 1}")


def main() -> None:
    command = sys.argv[1]
    if command == "prove":
        prove(sys.argv[2], sys.argv[3])
    elif command == "assert-proven":
        assert_proven(sys.argv[2], sys.argv[3])
    elif command == "hash":
        hashes(sys.argv[2])
    elif command == "verify-email":
        verify_email(sys.argv[2])
    elif command == "link-employee":
        link_employee(sys.argv[2], sys.argv[3], sys.argv[4])
    elif command == "insert-protected":
        insert_protected(sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5])
    elif command == "mark-pending":
        mark_pending(sys.argv[2], sys.argv[3])
    else:
        raise SystemExit(f"ABORT: unknown helper {command}")


if __name__ == "__main__":
    main()
