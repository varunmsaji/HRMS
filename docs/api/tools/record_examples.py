#!/usr/bin/env python3
"""Records REAL request/response pairs from a running API into docs/api/examples/*.md.

Only use against a throwaway environment (it registers companies and users). Intended target: a
local API pointed at the isolated `hrms_test` database, started with COMPANY_APPROVAL_REQUIRED=false
and EMAIL_PROVIDER=logging so the email-verification link is written to the server log:

    BASE_URL=http://127.0.0.1:8765 SERVER_LOG=/path/to/server.log \
      apps/api/.venv/bin/python -I docs/api/tools/record_examples.py

Secrets are redacted before writing: JWT access tokens, refresh cookie values and one-time email
tokens are replaced with placeholders. Everything else (ids, timestamps, messages) is verbatim.
"""

import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8765").rstrip("/")
LOG = Path(os.environ.get("SERVER_LOG", ""))
OUT = Path(__file__).resolve().parents[1] / "examples"
OUT.mkdir(exist_ok=True)

jar = http.cookiejar.CookieJar()
opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
PASSWORD = "Docs-Example-Pass1"
RUN = uuid.uuid4().hex[:8]
EMAIL = f"docs.admin.{RUN}@example.com"

transcript: list[dict] = []
SECRETS: dict[str, str] = {}


def redact(text: str) -> str:
    for value, placeholder in SECRETS.items():
        text = text.replace(value, placeholder)
    text = re.sub(r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+", "<jwt-access-token>", text)
    text = re.sub(r"(hrms_refresh=)[^;\s\"]+", r"\1<refresh-token>", text)
    text = re.sub(r"(/(?:verify-email|reset-password)/)[A-Za-z0-9_\-]+", r"\1<one-time-token>", text)
    return text


def call(label, method, path, *, body=None, headers=None, raw_cookie=None, form=None, note=""):
    url = BASE + path
    hdrs = {"Accept": "application/json", **(headers or {})}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        hdrs["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
    if raw_cookie:
        req.add_header("Cookie", raw_cookie)
    try:
        resp = opener.open(req, timeout=30)
    except urllib.error.HTTPError as e:
        resp = e
    status = resp.status if hasattr(resp, "status") else resp.code
    payload = resp.read().decode()
    rh = {k: v for k, v in resp.headers.items()}
    entry = {
        "label": label, "note": note, "method": method, "path": path, "req_headers": hdrs, "req_body": body,
        "status": status, "resp_headers": rh, "resp_body": payload,
    }
    transcript.append(entry)
    try:
        return status, json.loads(payload) if payload else None, rh
    except json.JSONDecodeError:
        return status, payload, rh


def render(entry) -> str:
    rh = {k: v for k, v in entry["req_headers"].items() if k.lower() in ("content-type", "authorization", "x-company-id", "if-match", "idempotency-key", "x-request-id")}
    if "Authorization" in rh:
        rh["Authorization"] = "Bearer <access_token>"
    keep = ("content-type", "set-cookie", "x-request-id", "retry-after", "www-authenticate", "idempotent-replayed")
    resp_h = {k: v for k, v in entry["resp_headers"].items() if k.lower() in keep}
    body = entry["resp_body"]
    try:
        body = json.dumps(json.loads(body), indent=2) if body else "(empty body)"
    except json.JSONDecodeError:
        pass
    reqb = json.dumps(entry["req_body"], indent=2) if entry["req_body"] is not None else None
    if reqb and "password" in reqb:
        pass  # example-only password, see PASSWORD above
    out = [f"### {entry['label']}", ""]
    if entry["note"]:
        out += [entry["note"], ""]
    out += ["```http", f"{entry['method']} {entry['path']}"]
    out += [f"{k}: {v}" for k, v in rh.items()]
    if reqb:
        out += ["", reqb]
    out += ["```", "", f"**Response `{entry['status']}`**", "", "```http"]
    out += [f"{k}: {v}" for k, v in resp_h.items()]
    out += ["", body, "```", ""]
    return redact("\n".join(out))



def read_invite_token():
    """The invite email (EMAIL_PROVIDER=logging) puts the link in the server log."""
    for _ in range(20):
        if LOG.exists():
            m = re.findall(r"/accept-invite/([A-Za-z0-9_\-]+)|/invite/([A-Za-z0-9_\-]+)|/accept/([A-Za-z0-9_\-]+)", LOG.read_text(errors="ignore"))
            flat = [x for t in m for x in t if x]
            if flat:
                return flat[-1]
        time.sleep(0.5)
    return None


def _unused_grant_attendance_out_of_band(company_id):
    import subprocess
    sql = ("insert into role_permission(role_id, permission_id, data_scope) select r.id, p.id, 'SELF' from role r "
           "join permission p on p.code in ('ATTENDANCE.PUNCH','ATTENDANCE.VIEW','ATTENDANCE.REGULARIZATION_REQUEST') "
           f"where r.company_id = '{company_id}' and r.code = 'EMPLOYEE' on conflict do nothing;")
    subprocess.run(["docker", "exec", "hrms-postgres", "psql", "-U", "hrms", "-d", "hrms_test", "-c", sql], check=True, capture_output=True)


def employee_flow(auth, reg):
    emp_email = f"docs.employee.{RUN}@example.com"
    s, le, _ = call("[setup] Create a legal entity", "POST", "/v1/legal-entities", headers=auth, body={"name": f"Docs Legal Entity {RUN}"})
    s, emp, _ = call("[setup] Create an employee", "POST", "/v1/employees", headers=auth,
                     body={"first_name": "Ravi", "last_name": "Kumar", "personal_email": emp_email})
    if s != 201:
        return None
    emp_id = emp["data"]["id"]
    call("[setup] Start the employment (joining date in the past)", "POST", f"/v1/employees/{emp_id}/employments", headers=auth,
         body={"legal_entity_id": le["data"]["id"], "joining_date": "2026-01-01"})
    s, inv, _ = call("[setup] Invite the employee to create an account", "POST", f"/v1/employees/{emp_id}/invite", headers=auth,
                     note="No request body: the invite goes to the employee's `personal_email`.")
    tok = read_invite_token()
    if not tok:
        print("could not find invite token in log", file=sys.stderr)
        return None
    SECRETS[tok] = "<one-time-token>"
    call("Resolve the invite link (public)", "GET", f"/v1/public/account-invites/{tok}")
    s, acc, hdr = call("Accept the invite (public) - creates the account and signs in", "POST", f"/v1/public/account-invites/{tok}/accept",
                       body={"password": PASSWORD}, note="Returns the same token payload as login; the refresh token is again only in `Set-Cookie`.")
    if s != 201:
        return None
    eauth = {"Authorization": f"Bearer {acc['data']['access_token']}"}
    s, me, _ = call("Employee: `/auth/me` (note `employee_id` and `permissions`)", "GET", "/v1/auth/me", headers=eauth)
    call("Employee: self punch IN (default `EMPLOYEE` role, no extra setup)", "POST", "/v1/attendance/punches/me", headers=eauth,
         body={"direction": "IN", "reference": "docs-example"},
         note="Since the C-1 remediation the default `EMPLOYEE` role holds SELF-scoped ATTENDANCE.PUNCH/VIEW/REGULARIZATION_REQUEST; "
              "before it this call returned 403 PERMISSION_DENIED.")
    call("Employee: cannot punch for someone else -> 403", "POST", "/v1/attendance/punches", headers=eauth,
         body={"employee_id": emp_id, "direction": "IN", "reference": "x", "punch_time": "2026-02-02T09:00:00Z"})
    call("Employee: punch IN again (what happens on a duplicate direction?)", "POST", "/v1/attendance/punches/me", headers=eauth, body={"direction": "IN"})
    call("Employee: bad direction -> 422", "POST", "/v1/attendance/punches/me", headers=eauth, body={"direction": "SIDEWAYS"})
    call("Employee: self punch OUT", "POST", "/v1/attendance/punches/me", headers=eauth, body={"direction": "OUT"})
    today = time.strftime("%Y-%m-%d", time.gmtime())
    call("Employee: my punches today", "GET", f"/v1/attendance/punches?employee_id={emp_id}&date_from={today}&date_to={today}", headers=eauth)
    call("Employee: bounded list - `per_page=1` pages through my punches", "GET", f"/v1/attendance/punches?employee_id={emp_id}&per_page=1&page=2", headers=eauth)
    call("Employee: my attendance days", "GET", f"/v1/attendance/days?employee_id={emp_id}&date_from={today}&date_to={today}", headers=eauth)
    call("Employee: another employee's id is refused/empty", "GET", f"/v1/attendance/days?employee_id={uuid.uuid4()}", headers=eauth)
    call("Employee: leave types", "GET", "/v1/leave-types", headers=eauth)
    call("Employee: leave balances (employee_id is a REQUIRED query param)", "GET", f"/v1/leave-balances?employee_id={emp_id}", headers=eauth)
    call("Employee: leave balances without employee_id -> 422", "GET", "/v1/leave-balances", headers=eauth)
    call("Employee: my own record", "GET", f"/v1/employees/{emp_id}", headers=eauth)
    call("Employee: my payslips (none yet)", "GET", "/v1/me/payslips", headers=eauth)
    call("Employee: admin-only route -> 403", "GET", "/v1/companies/current", headers=eauth)
    call("Employee: write to a manager-only route -> 403", "POST", "/v1/branches", headers=eauth, body={"name": "x"})
    call("Employee: logout", "POST", "/v1/auth/logout", headers=eauth)
    return emp_id

def write_files():
    groups = {
        "auth-and-session.md": ("Authentication & session - recorded exchanges", lambda e: e["path"].startswith(("/v1/auth", "/v1/companies")) and not e["label"].startswith("Employee")),
        "conventions-and-errors.md": ("Envelope, pagination, validation & error conventions - recorded exchanges",
                                       lambda e: not e["path"].startswith(("/v1/auth", "/v1/companies/register", "/v1/companies/registration")) and not e["label"].startswith(("Employee", "[setup]", "Resolve the invite", "Accept the invite"))),
        "employee-self-service.md": ("Employee self-service flow (invite, accept, punch, leave, payslips) - recorded exchanges",
                                      lambda e: e["label"].startswith(("Employee", "[setup]", "Resolve the invite", "Accept the invite"))),
    }
    for fname, (title, pred) in groups.items():
        entries = [e for e in transcript if pred(e)]
        head = [f"# {title}", "",
                "> **Recorded, not synthesized.** Produced by [`../tools/record_examples.py`](../tools/record_examples.py) against a local API "
                "(`ENVIRONMENT=development`, isolated `hrms_test` database, `COMPANY_APPROVAL_REQUIRED=false`, `EMAIL_PROVIDER=logging`) "
                f"on {time.strftime('%Y-%m-%d')}. Access tokens, refresh cookies and one-time email tokens are redacted; all other values are verbatim. "
                "The throwaway password in these files is a documentation-only value.", ""]
        (OUT / fname).write_text("\n".join(head) + "\n" + "\n".join(render(e) for e in entries))



def main():
    s, j, _ = call("Registration config (public)", "GET", "/v1/companies/registration-config")
    s, reg, _ = call("Register a company (public) - issues the first session", "POST", "/v1/companies/register", body={
        "name": f"Docs Example Pvt Ltd {RUN}", "country_code": "IN", "currency": "INR", "timezone": "Asia/Kolkata",
        "fy_start_month": 4, "admin_first_name": "Asha", "admin_last_name": "Verma", "admin_email": EMAIL,
        "admin_password": PASSWORD},
        note="The response body has no refresh token; it arrives in the `Set-Cookie: hrms_refresh=...` header (Path=/v1/auth, HttpOnly).")
    assert s == 201, (s, reg)
    access = reg["data"]["access_token"]
    company_id = reg["data"]["company_id"]
    auth = {"Authorization": f"Bearer {access}"}

    call("Current user (`/auth/me`)", "GET", "/v1/auth/me", headers=auth)
    call("Login before verifying the email -> 403", "POST", "/v1/auth/login", body={"email": EMAIL, "password": PASSWORD},
         note="Registration issues a session without verification, but a later *login* is refused until the email is verified.")

    token = None
    for _ in range(20):
        if LOG.exists():
            m = re.findall(r"/verify-email/([A-Za-z0-9_\-]+)", LOG.read_text(errors="ignore"))
            if m:
                token = m[-1]
                break
        time.sleep(0.5)
    if token:
        SECRETS[token] = "<one-time-token>"
        call("Verify email (token redacted)", "POST", "/v1/auth/email/verify", body={"token": token},
             note="The real token was read from the server log (EMAIL_PROVIDER=logging) and is redacted below.")
        call("Verify the same token again -> 401", "POST", "/v1/auth/email/verify", body={"token": token})
    call("Resend verification (always 202)", "POST", "/v1/auth/email/resend-verification", body={"email": "nobody@example.com"},
         note="Same 202 whether or not the address exists (anti-enumeration).")
    call("Forgot password (always 202)", "POST", "/v1/auth/password/forgot", body={"email": "nobody@example.com"})

    call("Login with a wrong password -> 401", "POST", "/v1/auth/login", body={"email": EMAIL, "password": "Wrong-Password-1"})
    s, login, hdr = call("Login (success)", "POST", "/v1/auth/login", body={"email": EMAIL, "password": PASSWORD, "company_id": company_id})
    assert s == 200, login
    access = login["data"]["access_token"]
    auth = {"Authorization": f"Bearer {access}"}
    first_cookie = next((v for k, v in hdr.items() if k.lower() == "set-cookie"), "").split(";")[0]
    SECRETS[first_cookie.split("=", 1)[1]] = "<refresh-token>"

    call("Refresh using the cookie (no body)", "POST", "/v1/auth/token/refresh",
         note="The cookie jar sends `hrms_refresh` automatically. The previous refresh token is rotated (single use).")
    call("Replay the rotated refresh token explicitly -> 401 and the family is revoked", "POST", "/v1/auth/token/refresh",
         body={"refresh_token": first_cookie.split("=", 1)[1]},
         note="Reuse detection: this revokes the whole token family and its session, so the newest cookie stops working too.")
    call("Refresh with the (now revoked) newest cookie -> 401", "POST", "/v1/auth/token/refresh")
    call("Access token of the revoked session -> 401", "GET", "/v1/auth/me", headers=auth,
         note="Revoking the session also invalidates the still-unexpired access token (checked on every request).")

    s, login, _ = call("Login again", "POST", "/v1/auth/login", body={"email": EMAIL, "password": PASSWORD})
    access = login["data"]["access_token"]
    auth = {"Authorization": f"Bearer {access}"}

    employee_flow(auth, reg)
    call("Request without a token -> 401", "GET", "/v1/branches")
    call("`X-Company-Id` that does not match the token -> 404", "GET", "/v1/branches",
         headers={**auth, "X-Company-Id": str(uuid.uuid4())})
    call("Paginated list (employees) - `pagination` object present", "GET", "/v1/employees?page=1&per_page=5", headers=auth)
    call("`per_page` above the cap (100) -> 422", "GET", "/v1/employees?per_page=500", headers=auth)
    idem = "docs-" + uuid.uuid4().hex
    emp_body = {"first_name": "Idem", "personal_email": f"docs.idem.{RUN}@example.com"}
    call("Create employee with an `Idempotency-Key`", "POST", "/v1/employees", headers={**auth, "Idempotency-Key": idem}, body=emp_body)
    call("Retry with the same key -> replay (`Idempotent-Replayed: true`, same employee)", "POST", "/v1/employees", headers={**auth, "Idempotency-Key": idem}, body=emp_body)
    call("Same key, different body -> 409", "POST", "/v1/employees", headers={**auth, "Idempotency-Key": idem}, body={**emp_body, "first_name": "Other"})
    call("Bounded collection: attendance days", "GET", "/v1/attendance/days?per_page=2", headers=auth)
    call("Counter-example: master-data lists are NOT paginated", "GET", "/v1/branches?page=2&per_page=5", headers=auth,
         note="`/v1/branches` accepts no `page`/`per_page`: the query is ignored and `pagination` is `null` (the whole collection is returned).")
    call("Validation error shape", "POST", "/v1/branches", headers=auth, body={"name": ""})
    call("PATCH without `If-Match` -> 422", "PATCH", "/v1/companies/current", headers=auth, body={"name": "Renamed"})
    s, comp, _ = call("Company profile (`version` is the concurrency token)", "GET", "/v1/companies/current", headers=auth)
    if s == 200:
        ver = comp["data"].get("version")
        call("PATCH with a stale `If-Match` -> 409", "PATCH", "/v1/companies/current", headers={**auth, "If-Match": str(ver + 5)}, body={"name": "Renamed"})
        call("PATCH with the current `If-Match`", "PATCH", "/v1/companies/current", headers={**auth, "If-Match": str(ver)}, body={"name": f"Docs Example Pvt Ltd {RUN}"})
    call("Self-service punch by a user with no employee record -> 422", "POST", "/v1/attendance/punches/me", headers=auth, body={"direction": "IN"},
         note="The company admin created at registration has no linked `Employee`, so `employee_id` in the token is null.")
    call("`Idempotency-Key` missing -> 422", "POST", "/v1/leave-applications", headers=auth, body={
        "leave_type_id": str(uuid.uuid4()), "start_date": "2026-02-02", "end_date": "2026-02-02"})
    call("Unknown route -> 404 envelope", "GET", "/v1/does-not-exist", headers=auth)
    call("Wrong method -> 405 envelope", "DELETE", "/v1/auth/login")

    call("Logout -> 204", "POST", "/v1/auth/logout", headers=auth)
    call("Use the access token after logout -> 401", "GET", "/v1/auth/me", headers=auth)

    # The login limiter keeps an IP-wide bucket (10/60s across *all* emails) as well as a per-email
    # one, so wait for the window to reset before each demonstration.
    if os.environ.get('SKIP_SLOW') == '1':
        write_files(); return
    time.sleep(62)
    email2 = f"docs.lock.{RUN}@example.com"
    call("Register a second company (for the lockout demo)", "POST", "/v1/companies/register", body={
        "name": f"Docs Lock Ltd {RUN}", "admin_first_name": "Lock", "admin_last_name": "Test", "admin_email": email2,
        "admin_password": PASSWORD})
    for i in range(1, 7):
        call(f"Wrong password #{i} (lockout after 5)", "POST", "/v1/auth/login", body={"email": email2, "password": "Wrong-Password-1"},
             note="Lockout is checked before the password, so even the correct password is refused with 423 while locked." if i == 6 else "")
    call("Correct password while locked -> 423", "POST", "/v1/auth/login", body={"email": email2, "password": PASSWORD})
    time.sleep(62)
    rl_email = f"ratelimit.{RUN}@example.com"
    last = None
    for i in range(1, 13):
        s, j, h = call(f"Login attempt {i} (rate-limit demo)", "POST", "/v1/auth/login", body={"email": rl_email, "password": "x"})
        if s == 429:
            last = i
            break

    write_files()
    summary = {"rate_limited_on_attempt": last, "calls": len(transcript)}
    print(json.dumps(summary))


if __name__ == "__main__":
    sys.exit(main())
