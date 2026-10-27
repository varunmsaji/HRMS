"""K-1 privilege investigation (ATT-PUNCH-006, TEN-RLS-002, ENV-GRANT-001).  Runs INSIDE the QA
runner against the DISPOSABLE database only.  Usage: k1_privileges.py <label>   (e.g. after-migrate)

* Refuses unless the DB host starts with 'qa-' and the DB name starts with 'hrms_qa_'.
* Part A (owner connection): role attributes, privilege matrix for hrms_app on every public table.
* Part B (hrms_app connection): behavioural probes inside transactions that are ALWAYS rolled back.
  `UPDATE/DELETE ... WHERE false` is enough: Postgres checks table privileges before it scans rows,
  so no data is read or changed.  TRUNCATE is probed inside the same rolled-back transaction.
Writes /artifacts/k1_<label>.json and prints a markdown table.
"""
import json
import os
import sys
from urllib.parse import urlsplit

import psycopg

label = sys.argv[1] if len(sys.argv) > 1 else "run"
owner_url = os.environ["MIGRATIONS_DATABASE_URL"]
app_url = os.environ["HRMS_APP_DATABASE_URL"]
sys.path.insert(0, ".")
from tests import isolation_guard  # noqa: E402

os.environ["HRMS_QA_STRICT"] = "1"
isolation_guard.check(os.environ)  # raises unless every URL is a private loopback hrms_qa_* target
for u in (owner_url, app_url):
    p = urlsplit(u)
    assert p.hostname == "127.0.0.1" and p.path.lstrip("/").startswith("hrms_qa_"), f"refusing non-disposable target {p.hostname}{p.path}"

TARGET = ["punch", "attendance_regularization_action", "attendance_period_action"]
CONTROL_APPEND_ONLY = ["audit_log", "leave_ledger", "leave_application_action", "email_log", "leave_year_end_run", "platform_audit_log"]
CONTROL_MUTABLE = ["employee", "idempotency_key"]
PRIVS = ["SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE"]
EXPECTED = {t: {"SELECT": True, "INSERT": True, "UPDATE": False, "DELETE": False, "TRUNCATE": False} for t in TARGET + CONTROL_APPEND_ONLY}
EXPECTED["employee"] = {"SELECT": True, "INSERT": True, "UPDATE": True, "DELETE": True, "TRUNCATE": False}
EXPECTED["idempotency_key"] = {"SELECT": True, "INSERT": True, "UPDATE": True, "DELETE": False, "TRUNCATE": False}

out: dict = {"label": label}
with psycopg.connect(owner_url, autocommit=True) as cx:
    cur = cx.cursor()
    cur.execute("select run from qa.disposable")
    marker = [r[0] for r in cur.fetchall()]
    assert marker == [os.environ["QA_RUN_ID"]], f"disposable marker missing or for another run: {marker}"
    cur.execute("select current_database(), current_user, inet_server_addr()::text, version()")
    out["identity"] = dict(zip(("database", "user", "server_addr", "version"), cur.fetchone()))
    out["disposable_marker"] = marker
    cur.execute("select rolname, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole, rolcanlogin from pg_roles where rolname in ('hrms','hrms_app')")
    out["roles"] = [dict(zip(("role", "super", "bypassrls", "createdb", "createrole", "login"), r)) for r in cur.fetchall()]
    cur.execute("select count(*) from alembic_version"); out["alembic_rows"] = cur.fetchone()[0]
    cur.execute("select version_num from alembic_version"); out["alembic_version"] = [r[0] for r in cur.fetchall()]
    cur.execute("select tablename from pg_tables where schemaname='public' order by 1")
    tables = [r[0] for r in cur.fetchall()]
    out["tables"] = len(tables)
    matrix = {}
    for t in tables:
        cur.execute("select " + ",".join(f"has_table_privilege('hrms_app', %s, '{p}')" for p in PRIVS), [f"public.{t}"] * len(PRIVS))
        matrix[t] = dict(zip(PRIVS, cur.fetchone()))
    out["matrix"] = matrix
    cur.execute("select c.relname, c.relrowsecurity, c.relforcerowsecurity, pg_get_userbyid(c.relowner) from pg_class c join pg_namespace n on n.oid=c.relnamespace where n.nspname='public' and c.relkind='r' and c.relname = any(%s)", [TARGET])
    out["rls_and_owner"] = [dict(zip(("table", "rls", "force_rls", "owner"), r)) for r in cur.fetchall()]
    cur.execute("select c.relname, t.tgname from pg_trigger t join pg_class c on c.oid=t.tgrelid where not t.tgisinternal and c.relname = any(%s)", [TARGET + CONTROL_APPEND_ONLY])
    out["triggers_on_guarded_tables"] = [list(r) for r in cur.fetchall()]
    cur.execute("select c.relname, a.attname from pg_class c join pg_attribute a on a.attrelid=c.oid where c.relname=any(%s) and a.attnum>0 and not a.attisdropped and a.attname in ('updated_at','version')", [TARGET])
    out["mutable_looking_columns"] = [list(r) for r in cur.fetchall()]

# expected vs observed
diffs = []
for t, exp in EXPECTED.items():
    obs = matrix.get(t)
    if obs is None:
        diffs.append({"table": t, "problem": "table missing"}); continue
    for p, want in exp.items():
        if obs[p] != want:
            diffs.append({"table": t, "privilege": p, "expected": want, "observed": obs[p]})
out["expected_vs_observed_differences"] = diffs
out["all_tables_where_hrms_app_can_UPDATE_DELETE_or_TRUNCATE"] = sorted(t for t, m in matrix.items() if m["UPDATE"] or m["DELETE"] or m["TRUNCATE"])

probes = []
with psycopg.connect(app_url) as cx:
    cur = cx.cursor()
    cur.execute("select current_user, (select rolbypassrls from pg_roles where rolname=current_user)")
    out["app_connection"] = dict(zip(("user", "bypassrls"), cur.fetchone()))
    for t in TARGET + ["leave_ledger", "employee"]:
        for op, sql in (("UPDATE", f"UPDATE {t} SET company_id = company_id WHERE false"),
                        ("DELETE", f"DELETE FROM {t} WHERE false"),
                        ("TRUNCATE", f"TRUNCATE {t}")):
            try:
                cur.execute(sql)
                res = "ALLOWED"
            except psycopg.errors.InsufficientPrivilege as e:
                res = "DENIED (" + str(e).splitlines()[0] + ")"
            except Exception as e:  # noqa: BLE001
                res = "OTHER ERROR " + type(e).__name__ + ": " + str(e).splitlines()[0]
            cx.rollback()
            probes.append({"table": t, "op": op, "result": res})
out["behavioural_probes_rolled_back"] = probes

os.makedirs("/artifacts", exist_ok=True)
json.dump(out, open(f"/artifacts/k1_{label}.json", "w"), indent=1, default=str)
print(f"# K-1 {label}: db={out['identity']['database']} alembic={out['alembic_version']} tables={out['tables']}")
print("| table | " + " | ".join(PRIVS) + " | expected differs |")
print("|---|" + "---|" * (len(PRIVS) + 1))
for t in TARGET + CONTROL_APPEND_ONLY + CONTROL_MUTABLE:
    m = matrix[t]
    d = [x["privilege"] for x in diffs if x.get("table") == t]
    print(f"| {t} | " + " | ".join("Y" if m[p] else "-" for p in PRIVS) + f" | {','.join(d) or 'no'} |")
for p in probes:
    print(f"probe {p['table']:36s} {p['op']:8s} {p['result']}")
print("DIFFERENCES:", json.dumps(diffs))
