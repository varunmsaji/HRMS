"""Approved GET cases SEC-R02 and SEC-R04 through SEC-R14. No other routes."""

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
EVIDENCE = ROOT / "evidence_sec_r_2026-10-26"
BASE = "http://127.0.0.1:18000"
TZ = ZoneInfo("Asia/Kolkata")
COUNT_TABLES = (
    "employee",
    "email_log",
    "employment",
    "employee_assignment",
    "employee_compensation",
    "employee_statutory",
    "employee_bank",
    "employee_experience",
    "employee_education",
    "employee_dependent",
    "employee_document",
    "company",
    '"user"',
    "session",
)

FOUNDRY = {
    "marker": "MARKER-FOUNDRY",
    "name": "QA Foundry MARKER-FOUNDRY",
    "email": "founder.a@example.com",
    "company_id": "a6c1f28f-3c8c-4148-b7f5-e43dbecf91f4",
    "employee_id": "eee9f7cc-292c-49f4-aff9-92d490ff6b1f",
}
NORTHWIND = {
    "marker": "MARKER-NORTHWIND",
    "name": "QA Northwind MARKER-NORTHWIND",
    "email": "founder.b@example.com",
    "company_id": "567bc97e-c165-4cc4-a0bc-98f527077f2c",
    "employee_id": "d265d407-1d86-4947-b147-f1805eb91d21",
}
LISTS = (
    ("SEC-R06", "/employments"),
    ("SEC-R07", "/assignments"),
    ("SEC-R08", "/compensation"),
    ("SEC-R09", "/statutory"),
    ("SEC-R10", "/bank"),
    ("SEC-R11", "/experience"),
    ("SEC-R12", "/education"),
    ("SEC-R13", "/dependents"),
    ("SEC-R14", "/documents"),
)


def now() -> str:
    return datetime.now(TZ).isoformat(timespec="seconds")


def other(tenant: dict[str, str]) -> dict[str, str]:
    return NORTHWIND if tenant is FOUNDRY else FOUNDRY


def foreign_needles(tenant: dict[str, str]) -> list[str]:
    banned = other(tenant)
    return [banned["marker"], banned["name"], banned["email"], banned["company_id"], banned["employee_id"]]


def hits(body: str, needles: list[str]) -> list[str]:
    return [needle for needle in needles if needle in body]


def call(path: str, headers: dict[str, str]):
    request = urllib.request.Request(BASE + path, method="GET", headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode()


def passwords() -> dict[str, str]:
    found = {}
    for line in (ROOT / "runtime" / "fixture-secrets.env").read_text().splitlines():
        email, password = line.split("=", 1)
        found[email] = password
    return found


def login(email: str, password: str) -> str:
    raw = json.dumps({"email": email, "password": password}).encode()
    request = urllib.request.Request(
        BASE + "/v1/auth/login",
        data=raw,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        payload = json.loads(response.read().decode())
    return payload["data"]["access_token"]


def headers_for(token: str, company_id: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}", "X-Company-Id": company_id}


def counts(conn) -> dict[str, int]:
    found = {}
    with conn.cursor() as cur:
        for table in COUNT_TABLES:
            cur.execute(f"SELECT count(*) FROM {table}")
            found[table.strip('"')] = int(cur.fetchone()[0])
    return found


def object_count() -> int:
    import boto3

    client = boto3.client(
        "s3",
        endpoint_url=os.environ["S3_ENDPOINT_URL"],
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
        region_name=os.environ.get("AWS_REGION", "us-east-1"),
    )
    response = client.list_objects_v2(Bucket=os.environ["S3_BUCKET_DOCUMENTS"])
    return int(response.get("KeyCount", 0))


def main() -> None:
    parts = urlsplit(os.environ["DATABASE_URL"])
    if (parts.hostname, parts.port, parts.path) != ("127.0.0.1", 15433, "/hrms_qa_20261026"):
        raise SystemExit("ISOLATION BLOCKED")
    free = os.statvfs("/var/lib/docker").f_bavail * os.statvfs("/var/lib/docker").f_frsize
    if free < 2 * 1024**3:
        raise SystemExit("DISK BLOCKED")
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    started = now()
    secret = passwords()
    results = []
    stopped = False

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        before = counts(conn)
    before_objects = object_count()

    tokens = {
        FOUNDRY["marker"]: login(FOUNDRY["email"], secret[FOUNDRY["email"]]),
        NORTHWIND["marker"]: login(NORTHWIND["email"], secret[NORTHWIND["email"]]),
    }

    def record(case: str, actor: str, kind: str, status: int, body: str, verdict: str, note: str):
        item = {
            "case": case,
            "direction": f"{actor}-{kind}",
            "environment": "hrms_qa_20261026",
            "started_at": started,
            "observed_at": now(),
            "timezone": "Asia/Kolkata",
            "http_status": status,
            "body": body,
            "verdict": verdict,
            "note": note,
            "rls": "not tested; API role hrms_qa bypasses RLS",
        }
        results.append(item)
        (EVIDENCE / f"{case}-{actor}-{kind}.json").write_text(json.dumps(item, indent=2) + "\n")
        return item

    def leak_stop(case: str, actor: str, kind: str, status: int, body: str, leaked: list[str]) -> bool:
        record(case, actor, kind, status, body, "FAIL", "foreign tenant data: " + ", ".join(leaked))
        return True

    for actor in (FOUNDRY, NORTHWIND):
        if stopped:
            break
        token = tokens[actor["marker"]]
        own = headers_for(token, actor["company_id"])
        foreign = headers_for(token, other(actor)["company_id"])
        banned = foreign_needles(actor)

        status, body = call("/v1/companies/current", own)
        leaked = hits(body, banned)
        if leaked:
            stopped = leak_stop("SEC-R02", actor["marker"], "own", status, body, leaked)
            break
        parsed = json.loads(body) if status == 200 else {}
        name = parsed.get("data", {}).get("name") if isinstance(parsed, dict) else None
        ok = status == 200 and name == actor["name"] and parsed.get("data", {}).get("id") == actor["company_id"]
        record("SEC-R02", actor["marker"], "own", status, body, "PASS" if ok else "FAIL", "own company profile")
        if stopped:
            break

        status, body = call("/v1/companies/current", foreign)
        leaked = hits(body, banned)
        if leaked:
            stopped = leak_stop("SEC-R02", actor["marker"], "foreign-header", status, body, leaked)
            break
        ok = status == 404 and "NOT_FOUND" in body
        record("SEC-R02", actor["marker"], "foreign-header", status, body, "PASS" if ok else "FAIL", "foreign company header")

        status, body = call("/v1/users", own)
        leaked = hits(body, banned)
        if leaked:
            stopped = leak_stop("SEC-R04", actor["marker"], "own", status, body, leaked)
            break
        parsed = json.loads(body) if status == 200 else {}
        rows = parsed.get("data", []) if isinstance(parsed, dict) else []
        emails = {row.get("email") for row in rows}
        names = {row.get("first_name") for row in rows}
        ok = status == 200 and emails == {actor["email"]} and actor["marker"] in names
        record("SEC-R04", actor["marker"], "own", status, body, "PASS" if ok else "FAIL", "own user list")

        status, body = call("/v1/users", foreign)
        leaked = hits(body, banned)
        if leaked:
            stopped = leak_stop("SEC-R04", actor["marker"], "foreign-header", status, body, leaked)
            break
        ok = status == 404 and "NOT_FOUND" in body and actor["email"] not in body
        record("SEC-R04", actor["marker"], "foreign-header", status, body, "PASS" if ok else "FAIL", "foreign company header")

        status, body = call(f"/v1/employees/{actor['employee_id']}/identity", own)
        leaked = hits(body, banned)
        if leaked:
            stopped = leak_stop("SEC-R05", actor["marker"], "own", status, body, leaked)
            break
        parsed = json.loads(body) if status == 200 else {}
        ok = status == 200 and parsed.get("data", {}).get("employee_id") == actor["employee_id"]
        record("SEC-R05", actor["marker"], "own", status, body, "PASS" if ok else "FAIL", "own identity")

        status, body = call(f"/v1/employees/{other(actor)['employee_id']}/identity", own)
        leaked = hits(body, banned)
        if leaked:
            stopped = leak_stop("SEC-R05", actor["marker"], "cross-id", status, body, leaked)
            break
        ok = status == 404 and "NOT_FOUND" in body
        record("SEC-R05", actor["marker"], "cross-id", status, body, "PASS" if ok else "FAIL", "other employee id")

        for case, suffix in LISTS:
            if stopped:
                break
            status, body = call(f"/v1/employees/{actor['employee_id']}{suffix}", own)
            leaked = hits(body, banned)
            if leaked:
                stopped = leak_stop(case, actor["marker"], "own", status, body, leaked)
                break
            parsed = json.loads(body) if status == 200 else {}
            data = parsed.get("data") if isinstance(parsed, dict) else None
            ok = status == 200 and data == []
            if case == "SEC-R14" and "http" in body.lower():
                ok = False
            record(case, actor["marker"], "own", status, body, "PASS" if ok else "FAIL", "own empty list")

            status, body = call(f"/v1/employees/{other(actor)['employee_id']}{suffix}", own)
            leaked = hits(body, banned)
            if leaked:
                stopped = leak_stop(case, actor["marker"], "cross-id", status, body, leaked)
                break
            ok = status == 404 and "NOT_FOUND" in body
            record(case, actor["marker"], "cross-id", status, body, "PASS" if ok else "FAIL", "other employee id")

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn:
        after = counts(conn)
    after_objects = object_count()
    business = [name for name in before if name != "session"]
    summary = {
        "environment": "hrms_qa_20261026",
        "observed_at": now(),
        "timezone": "Asia/Kolkata",
        "rls": "not tested; API role hrms_qa bypasses RLS",
        "stopped_for_foreign_data": stopped,
        "business_counts_unchanged": all(before[name] == after[name] for name in business),
        "counts_before": before,
        "counts_after": after,
        "object_count_before": before_objects,
        "object_count_after": after_objects,
        "results": [
            {"case": item["case"], "direction": item["direction"], "verdict": item["verdict"], "http_status": item["http_status"]}
            for item in results
        ],
    }
    (EVIDENCE / "database-after.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary["results"], indent=2))
    print("BUSINESS_UNCHANGED", summary["business_counts_unchanged"])
    print("OBJECTS", before_objects, after_objects)
    print("SESSION", before["session"], after["session"])
    print("STOPPED", stopped)


if __name__ == "__main__":
    main()
