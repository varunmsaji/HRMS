"""Approved initial smoke requests only. Does not call AUTH-008 or non-employee resources."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import psycopg

ROOT = Path("/media/varun/varun12/work/staff-spectrum/HRMS/docs/qa/comprehensive_hrms")
EVIDENCE = ROOT / "evidence_smoke_2026-10-26"
BASE = "http://127.0.0.1:18000"
TZ = ZoneInfo("Asia/Kolkata")

FOUNDRY = {
    "marker": "MARKER-FOUNDRY",
    "email": "founder.a@example.com",
    "company_id": "a6c1f28f-3c8c-4148-b7f5-e43dbecf91f4",
    "employee_id": "eee9f7cc-292c-49f4-aff9-92d490ff6b1f",
}
NORTHWIND = {
    "marker": "MARKER-NORTHWIND",
    "email": "founder.b@example.com",
    "company_id": "567bc97e-c165-4cc4-a0bc-98f527077f2c",
    "employee_id": "d265d407-1d86-4947-b147-f1805eb91d21",
}


def now() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


def assert_database() -> None:
    parts = urlsplit(os.environ["DATABASE_URL"])
    if (parts.hostname, parts.port, parts.path) != ("127.0.0.1", 15433, "/hrms_qa_20261026"):
        raise SystemExit("ISOLATION BLOCKED smoke database target")


def passwords() -> dict[str, str]:
    found: dict[str, str] = {}
    for line in (ROOT / "runtime" / "fixture-secrets.env").read_text().splitlines():
        email, password = line.split("=", 1)
        found[email] = password
    return found


def call(method: str, path: str, headers: dict[str, str] | None = None, body: bytes | None = None):
    request = urllib.request.Request(BASE + path, data=body, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            payload = response.read()
            return response.status, dict(response.headers), payload.decode()
    except urllib.error.HTTPError as exc:
        payload = exc.read()
        return exc.code, dict(exc.headers), payload.decode()


def forbidden(owner: dict[str, str]) -> list[str]:
    other = NORTHWIND if owner is FOUNDRY else FOUNDRY
    return [other["marker"], other["email"], other["company_id"], other["employee_id"]]


def hits(body: str, needles: list[str]) -> list[str]:
    return [needle for needle in needles if needle in body]


def write_case(name: str, record: dict) -> None:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    (EVIDENCE / f"{name}.json").write_text(json.dumps(record, indent=2) + "\n")


def employee_image(conn) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id::text, company_id::text, first_name, last_name, updated_at "
            "FROM employee ORDER BY id"
        )
        return list(cur.fetchall())


def email_count(conn) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM email_log")
        return int(cur.fetchone()[0])


def main() -> None:
    assert_database()
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    started = now()
    secret = passwords()
    results: list[dict] = []
    stopped = False

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        before_employees = employee_image(conn)
        before_email = email_count(conn)

    def record(name: str, expected: str, status: int, headers: dict, body: str, verdict: str, note: str):
        safe_headers = {
            key: value
            for key, value in headers.items()
            if key.lower() in {"www-authenticate", "content-type", "x-request-id"}
        }
        item = {
            "case": name,
            "environment": "hrms_qa_20261026",
            "started_at": started,
            "observed_at": now(),
            "timezone": "Asia/Kolkata",
            "expected": expected,
            "http_status": status,
            "headers": safe_headers,
            "body": body,
            "verdict": verdict,
            "note": note,
        }
        results.append(item)
        write_case(name, item)
        return item

    status, headers, body = call("GET", "/health")
    health_needles = [
        FOUNDRY["marker"],
        NORTHWIND["marker"],
        FOUNDRY["email"],
        NORTHWIND["email"],
        FOUNDRY["company_id"],
        NORTHWIND["company_id"],
        "@",
    ]
    leaked = hits(body, health_needles)
    if leaked:
        record(
            "PLT-001",
            "200. Body has no email, name, or company list.",
            status,
            headers,
            body,
            "FAIL",
            "health body contained " + ", ".join(leaked),
        )
        stopped = True
    elif status != 200:
        record(
            "PLT-001",
            "200. Body has no email, name, or company list.",
            status,
            headers,
            body,
            "FAIL",
            "status was not 200",
        )
    else:
        record(
            "PLT-001",
            "200. Body has no email, name, or company list.",
            status,
            headers,
            body,
            "PASS",
            "anonymous health body has the health fields only",
        )

    if not stopped:
        status, headers, body = call("GET", "/v1/employees")
        leaked = hits(
            body,
            [
                FOUNDRY["marker"],
                NORTHWIND["marker"],
                FOUNDRY["email"],
                NORTHWIND["email"],
                FOUNDRY["employee_id"],
                NORTHWIND["employee_id"],
            ],
        )
        if leaked:
            record(
                "AUTH-004",
                "401. Body has no employee names.",
                status,
                headers,
                body,
                "FAIL",
                "anonymous body contained " + ", ".join(leaked),
            )
            stopped = True
        elif status != 401:
            record(
                "AUTH-004",
                "401. Body has no employee names.",
                status,
                headers,
                body,
                "FAIL",
                "status was not 401",
            )
        else:
            record(
                "AUTH-004",
                "401. Body has no employee names.",
                status,
                headers,
                body,
                "PASS",
                "WWW-Authenticate=" + headers.get("WWW-Authenticate", headers.get("www-authenticate", "")),
            )

    tokens: dict[str, str] = {}
    if not stopped:
        for tenant in (FOUNDRY, NORTHWIND):
            raw = json.dumps({"email": tenant["email"], "password": secret[tenant["email"]]}).encode()
            status, headers, body = call(
                "POST",
                "/v1/auth/login",
                {"Content-Type": "application/json"},
                raw,
            )
            redacted = body
            try:
                parsed = json.loads(body)
                token = parsed.get("data", {}).get("access_token")
                if token:
                    tokens[tenant["marker"]] = token
                    parsed["data"]["access_token"] = "[redacted]"
                redacted = json.dumps(parsed)
            except json.JSONDecodeError:
                pass
            other = forbidden(tenant)
            leaked = hits(redacted, other)
            login_name = "login-" + tenant["marker"]
            if leaked:
                record(login_name, "200 for own company only; not a scored case", status, headers, redacted, "FAIL", "login exposed the other tenant")
                stopped = True
                break
            if status != 200 or tenant["marker"] not in tokens:
                record(login_name, "200 for own company only; not a scored case", status, headers, redacted, "FAIL", "login did not return a usable token")
                stopped = True
                break
            company_id = json.loads(body).get("data", {}).get("company_id")
            if company_id != tenant["company_id"]:
                record(login_name, "200 for own company only; not a scored case", status, headers, redacted, "FAIL", "token company did not match the fixture")
                stopped = True
                break
            record(login_name, "200 for own company only; not a scored case", status, headers, redacted, "SETUP", "authentication for the approved GET cases")

    def authed(tenant: dict[str, str], company_id: str) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {tokens[tenant['marker']]}",
            "X-Company-Id": company_id,
        }

    if not stopped:
        status, headers, body = call("GET", "/v1/employees", authed(FOUNDRY, NORTHWIND["company_id"]))
        leaked = hits(body, forbidden(FOUNDRY))
        if leaked:
            record("AUTH-009", "403 or 404. Zero company B rows.", status, headers, body, "FAIL", "cross-company response contained " + ", ".join(leaked))
            stopped = True
        elif status not in (403, 404):
            record("AUTH-009", "403 or 404. Zero company B rows.", status, headers, body, "FAIL", "status was not 403 or 404")
        elif FOUNDRY["employee_id"] in body or FOUNDRY["marker"] in body:
            record("AUTH-009", "403 or 404. Zero company B rows.", status, headers, body, "FAIL", "response included Foundry employee data while naming Northwind")
        else:
            record("AUTH-009", "403 or 404. Zero company B rows.", status, headers, body, "PASS", "no employee payload")

    if not stopped:
        for tenant in (FOUNDRY, NORTHWIND):
            status, headers, body = call("GET", "/v1/employees", authed(tenant, tenant["company_id"]))
            leaked = hits(body, forbidden(tenant))
            name = "SEC-001-" + tenant["marker"]
            if leaked:
                record(name, "200 with only the caller. Other marker absent.", status, headers, body, "FAIL", "list contained " + ", ".join(leaked))
                stopped = True
                break
            if status != 200 or tenant["marker"] not in body or tenant["employee_id"] not in body:
                record(name, "200 with only the caller. Other marker absent.", status, headers, body, "FAIL", "own employee was not returned")
                break
            record(name, "200 with only the caller. Other marker absent.", status, headers, body, "PASS", "own marker present; other tenant absent")

    if not stopped:
        pairs = (
            ("SEC-002-own-FOUNDRY", FOUNDRY, FOUNDRY["employee_id"], 200),
            ("SEC-002-cross-NORTHWIND-reads-FOUNDRY", NORTHWIND, FOUNDRY["employee_id"], 404),
            ("SEC-002-own-NORTHWIND", NORTHWIND, NORTHWIND["employee_id"], 200),
            ("SEC-002-cross-FOUNDRY-reads-NORTHWIND", FOUNDRY, NORTHWIND["employee_id"], 404),
        )
        for name, actor, employee_id, expected_status in pairs:
            status, headers, body = call(
                "GET",
                f"/v1/employees/{employee_id}",
                authed(actor, actor["company_id"]),
            )
            leaked = hits(body, forbidden(actor))
            if leaked:
                record(name, "own 200 with own marker; cross 404 with no other-tenant data", status, headers, body, "FAIL", "body contained " + ", ".join(leaked))
                stopped = True
                break
            if expected_status == 200:
                ok = status == 200 and actor["marker"] in body and employee_id in body
                record(
                    name,
                    "200 and the caller's own employee only",
                    status,
                    headers,
                    body,
                    "PASS" if ok else "FAIL",
                    "ownership control",
                )
                if not ok:
                    break
            else:
                ok = status == 404 and FOUNDRY["marker"] not in body and NORTHWIND["marker"] not in body
                record(
                    name,
                    "404. Other tenant marker absent.",
                    status,
                    headers,
                    body,
                    "PASS" if ok else "FAIL",
                    "cross-tenant GET",
                )
                if not ok:
                    stopped = True
                    break

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        after_employees = employee_image(conn)
        after_email = email_count(conn)
    write_case(
        "database-after",
        {
            "environment": "hrms_qa_20261026",
            "observed_at": now(),
            "timezone": "Asia/Kolkata",
            "employees_unchanged": before_employees == after_employees,
            "email_log_before": before_email,
            "email_log_after": after_email,
            "stopped_for_leak": stopped,
            "results": [
                {"case": item["case"], "verdict": item["verdict"], "http_status": item["http_status"]}
                for item in results
            ],
        },
    )
    print(json.dumps([
        {"case": item["case"], "verdict": item["verdict"], "http_status": item["http_status"]}
        for item in results
    ], indent=2))
    print("EMPLOYEES_UNCHANGED", before_employees == after_employees)
    print("EMAIL_LOG", before_email, after_email)
    print("STOPPED", stopped)


if __name__ == "__main__":
    main()
