# Document 09 — API Standards

**Version:** 2.0 — migrated from Document 05 v1.0 ("API Specification & Contracts"). **The REST
design itself is entirely stack-independent** (Document 04 v1.0 §2.2, unchanged principle) — every
convention in this document was true under NestJS and remains true under FastAPI. What changed is
how the contract is generated and enforced: FastAPI produces the OpenAPI document natively from
Pydantic models and type-hinted path operations, with no separate annotation layer to keep in sync.

**Style:** REST over HTTPS, JSON only.
**Base:** `https://api.<domain>/v1`
**Spec artefact:** OpenAPI 3.1, generated natively by FastAPI from route type hints and Pydantic
models, published at `/v1/openapi.json` and rendered at `/docs` (Swagger UI) and `/redoc`.
**The OpenAPI file is the contract; this document is the design law.**

---

## 1. Conventions

### 1.1 URL & Method
| Rule | Example |
|---|---|
| Plural, kebab-case resources | `/employees`, `/leave-applications` |
| Nested only one level deep | `/employees/{id}/documents` — beyond that, use filters |
| Actions that are not CRUD use a verb sub-resource | `POST /pay-runs/{id}/finalise` |
| No verbs in resource names | ✗ `/getEmployees` |
| Version in the path | `/v1/...` |

`GET` list · `GET` detail · `POST` create · `PATCH` partial update · `PUT` full replace (rare) ·
`DELETE` soft-delete/deactivate.

### 1.2 Required Headers
```
Authorization: Bearer <access_token>
X-Company-Id: <uuid>          # active tenant; must match a company the user belongs to
X-Request-Id: <uuid>          # client-generated; echoed back; used in logs and audit
Idempotency-Key: <uuid>       # REQUIRED on all POST that create money/attendance/approval effects
Accept-Language: en|hi|ml|ta
```

In FastAPI these are typed `Header(...)` parameters consumed by dependencies (Document 07 §2.1),
not hand-parsed from a raw request object — `X-Company-Id` in particular is read by
`get_tenant_context`, `X-Request-Id` by request-scoped logging middleware, and `Idempotency-Key` by
a shared dependency (`shared/idempotency.py`) applied to every mutating endpoint that requires it.

### 1.3 Standard Response Envelope

Success (single):
```json
{
  "data": { "id": "…", "…": "…" },
  "meta": { "request_id": "…", "server_time": "2026-08-03T09:12:33Z" }
}
```

Success (list):
```json
{
  "data": [ … ],
  "pagination": {
    "page": 1, "per_page": 50, "total": 1287, "total_pages": 26,
    "next_cursor": "eyJpZCI6…"
  },
  "meta": { "request_id": "…" }
}
```

Error:
```json
{
  "error": {
    "code": "LEAVE_INSUFFICIENT_BALANCE",
    "message": "You have 2.5 days of Casual Leave; 3 days requested.",
    "details": [
      { "field": "total_days", "code": "EXCEEDS_BALANCE", "message": "…",
        "context": { "available": 2.5, "requested": 3 } }
    ],
    "request_id": "…",
    "documentation_url": "https://docs…/errors/LEAVE_INSUFFICIENT_BALANCE"
  }
}
```

**Error code rules:** machine-readable `code` is `SCREAMING_SNAKE`, stable across versions, and
namespaced by domain. `message` is human-readable, localised, and safe to display. Never leak
internal identifiers, SQL, or stack traces. This envelope is produced by the single set of FastAPI
exception handlers described in Document 07 §8 — routers never build error responses by hand.

Every envelope shape above is itself a Pydantic model (`DataEnvelope[T]`, `ListEnvelope[T]`,
`ErrorEnvelope`) in `shared/pagination.py` / `core/errors/`, generic over the resource type, so the
OpenAPI schema for every endpoint's response is exact and machine-checkable — this is a genuine
improvement over the original NestJS design, where the envelope shape was a documented convention
enforced by discipline rather than the type system.

### 1.4 HTTP Status Usage
| Code | When |
|---|---|
| 200 | Successful GET/PATCH |
| 201 | Created (with `Location` header) |
| 202 | Accepted — long-running job queued (returns `job_id`) |
| 204 | Successful delete |
| 400 | Malformed request |
| 401 | Missing/invalid token |
| 403 | Authenticated but lacking permission |
| **404** | Resource not found **OR belongs to another tenant** — never 403 for cross-tenant |
| 409 | Conflict (duplicate, version mismatch, state-machine violation) |
| 422 | Validation failure (business rule) — note FastAPI also uses 422 natively for request-shape validation errors raised by Pydantic; both cases share the error envelope in §1.3 |
| 423 | Locked (payroll period locked, attendance locked) |
| 429 | Rate limited (with `Retry-After`) |
| 500/503 | Server error / degraded |

### 1.5 Pagination, Filtering, Sorting
```
GET /employees?page=1&per_page=50&sort=-joining_date,last_name
  &filter[department_id]=uuid&filter[status]=ACTIVE
  &filter[joining_date][gte]=2025-01-01
  &search=priya&fields=id,employee_code,display_name,designation
  &include=assignment,department
```
- Default `per_page=25`, max `100` (max `1000` for export endpoints, which are async).
- Cursor pagination mandatory for `punch`, `audit_log`, `notification_log` (offset pagination on
  100M-row tables is a performance trap) — implemented with `shared/pagination.py`'s cursor helper,
  used identically across every module's `repository.py`.
- `fields` (sparse fieldsets) and `include` (relations) reduce payloads for mobile.

### 1.6 Idempotency
`POST` endpoints that create attendance punches, leave applications, approvals, payments or pay
runs **must** accept `Idempotency-Key`. The server stores key → response for 24 hours (Redis, keyed
`idempotency:{company_id}:{key}`); a repeat key returns the original response with
`Idempotency-Replayed: true`. This is essential for the mobile offline-sync path. Implemented as a
reusable FastAPI dependency, not per-endpoint logic — Document 07 §4.

### 1.7 Concurrency
Mutable resources return `ETag`; `PATCH` accepts `If-Match`. Version mismatch → `409 STALE_RESOURCE`
with the current representation, so the client can show a diff rather than silently overwrite. The
`ETag` is derived from each table's `version` column (Document 08 header) — optimistic locking is
enforced at the repository layer via a `WHERE version = :expected_version` clause on the update, not
merely checked in the service layer, so a race between two requests cannot both succeed.

### 1.8 Dates, Times, Money
| Type | Format | Example |
|---|---|---|
| Date | ISO-8601 date | `"2026-08-03"` |
| Timestamp | ISO-8601 UTC with Z | `"2026-08-03T09:12:33Z"` |
| Time of day | `HH:mm` (24h) | `"09:30"` |
| Money | object, minor units | `{"amount": 4500000, "currency": "INR"}` → ₹45,000.00 |
| Percentage | number | `12.0` means 12% |
| Duration | minutes as integer | `480` |

**Never** send money as a float or a formatted string. **Never** send a naive local timestamp.
The `Money` and date/time types here map 1:1 to the `shared/value_objects/` types (Document 07 §6);
a Pydantic schema field typed `Money` serialises to exactly this JSON shape via a custom
`pydantic` serializer, so there is no hand-written serialisation code per endpoint that could drift.

### 1.9 Rate Limits
| Scope | Limit |
|---|---|
| Per user | 300 req/min |
| Per tenant | 3,000 req/min |
| Auth endpoints | 10/min per IP + 5/min per account |
| Punch ingestion | 10,000/min per tenant |
| Export/report generation | 20/hour per user |
| AI endpoints | per plan quota |
Headers: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`. Implemented with a
Redis-backed sliding-window limiter (`shared/rate_limit.py`), applied as a dependency or ASGI
middleware depending on scope (per-tenant/global limits as middleware; per-endpoint limits like
export/AI quotas as a `Depends`).

---

## 2. Authentication Endpoints

Full authentication architecture (token design, MFA, SSO) is in Document 10. This section lists the
endpoint surface only, unchanged from v1.0:

| Method | Path | Description |
|---|---|---|
| POST | `/auth/login` | email+password → tokens + company list |
| POST | `/auth/login/otp/request` | mobile → OTP sent |
| POST | `/auth/login/otp/verify` | mobile+otp → tokens |
| POST | `/auth/mfa/verify` | complete MFA challenge |
| POST | `/auth/token/refresh` | rotate refresh token |
| POST | `/auth/logout` | revoke current session |
| POST | `/auth/logout/all` | revoke all sessions |
| POST | `/auth/password/forgot` | request reset |
| POST | `/auth/password/reset` | reset with token |
| POST | `/auth/password/change` | authenticated change |
| GET | `/auth/me` | current user + active company + permissions + employee summary |
| POST | `/auth/company/switch` | switch active tenant → new token |
| GET | `/auth/sessions` / DELETE `/auth/sessions/{id}` | session management |
| POST | `/auth/mfa/enroll` / `/auth/mfa/disable` | TOTP setup |
| GET | `/auth/sso/{tenant}/metadata` · POST `/auth/sso/{tenant}/acs` | SAML |

**`POST /auth/login` response:**
```json
{
  "data": {
    "access_token": "eyJ…",
    "expires_in": 900,
    "token_type": "Bearer",
    "mfa_required": false,
    "companies": [
      { "id": "…", "name": "Acme Manufacturing", "logo_url": "…", "is_default": true,
        "employee_id": "…", "roles": ["HR_MANAGER"] }
    ]
  }
}
```
Refresh token is set as an HttpOnly cookie for web; returned in the body only for mobile clients
identified by `X-Client-Type: mobile`.

**`GET /auth/me` response (drives the entire client UI):**
```json
{
  "data": {
    "user": { "id": "…", "email": "priya@acme.com", "mfa_enabled": true },
    "company": { "id": "…", "name": "Acme", "timezone": "Asia/Kolkata", "currency": "INR",
                 "fy_start_month": 4, "logo_url": "…", "theme": {…} },
    "employee": { "id": "…", "employee_code": "ACM0042", "display_name": "Priya S",
                  "designation": "HR Manager", "department": "Human Resources",
                  "branch": "Kochi", "reporting_manager": {"id":"…","name":"Vikram R"},
                  "photo_url": "…", "shift": {"id":"…","name":"General 9-6"} },
    "roles": ["HR_MANAGER"],
    "permissions": ["EMPLOYEE.VIEW", "EMPLOYEE.CREATE", "LEAVE.APPROVE", …],
    "data_scope": { "type": "BRANCH", "branch_ids": ["…"] },
    "enabled_modules": ["EMPLOYEE","ATTENDANCE","LEAVE","PAYROLL","RECRUITMENT","ESS"],
    "feature_flags": { "ai_resume_screening": true, "whatsapp_notifications": false }
  }
}
```

---

## 3. Endpoint Catalogue by Module

Unchanged from v1.0 in shape and coverage; reproduced here in full as it remains the design law for
the API surface across all 20+ modules.

### 3.1 Organisation
```
GET/POST/PATCH  /companies/current
GET/POST        /legal-entities            GET/PATCH/DELETE  /legal-entities/{id}
GET/POST        /branches                  GET/PATCH/DELETE  /branches/{id}
GET/POST        /departments               GET/PATCH/DELETE  /departments/{id}
GET             /departments/tree
GET/POST        /designations              GET/PATCH/DELETE  /designations/{id}
GET/POST        /grades                    GET/PATCH/DELETE  /grades/{id}
GET/POST        /cost-centres
GET/POST        /employment-types
GET/POST        /holiday-calendars         POST /holiday-calendars/{id}/holidays
GET             /holidays?year=2026&branch_id=…
GET/POST        /week-off-patterns
GET/POST/PATCH  /custom-fields
GET/PATCH       /number-series
GET             /org-chart?root_employee_id=…&depth=3
```

### 3.2 Employees
```
GET    /employees                     list + filter + search
POST   /employees                     create
GET    /employees/{id}                summary
GET    /employees/{id}/full           360° view (all tabs in one call, mobile-optimised)
PATCH  /employees/{id}
DELETE /employees/{id}                deactivate only
GET    /employees/{id}/assignments    effective-dated history
POST   /employees/{id}/assignments    transfer/promotion/manager change
GET    /employees/{id}/compensation   permission-gated
POST   /employees/{id}/compensation   salary revision
GET    /employees/{id}/statutory      PATCH …
GET    /employees/{id}/bank-accounts  POST …
GET    /employees/{id}/documents      POST … / PATCH {docId}/verify
GET    /employees/{id}/dependents|education|experience|skills   (+POST)
GET    /employees/{id}/timeline       unified event feed
GET    /employees/{id}/team           direct reports
GET    /employees/{id}/reporting-tree full subtree
POST   /employees/{id}/confirm        probation confirmation
POST   /employees/import              multipart → 202 + job_id
GET    /employees/import/{batchId}    validation result
GET    /employees/export              202 + job_id
POST   /employees/{id}/letters        generate letter from template
GET    /employees/directory           lightweight, cached, for ESS
POST   /profile-change-requests       employee-initiated edit
```

**`POST /employees` request:**
```json
{
  "first_name": "Rahul", "last_name": "Menon",
  "date_of_birth": "1995-04-12", "gender": "MALE",
  "personal_email": "rahul.m@gmail.com", "personal_mobile": "+919876543210",
  "employment": {
    "legal_entity_id": "…", "date_of_joining": "2026-09-01",
    "employment_type_id": "…", "probation_days": 180
  },
  "assignment": {
    "branch_id": "…", "department_id": "…", "designation_id": "…",
    "grade_id": "…", "reporting_manager_id": "…", "shift_id": "…"
  },
  "compensation": {
    "salary_structure_id": "…", "annual_ctc": { "amount": 90000000, "currency": "INR" }
  },
  "statutory": { "is_pf_applicable": true, "tax_regime": "NEW", "pt_state_code": "KL" },
  "custom_fields": { "t_shirt_size": "L" }
}
```
→ `201` with the created employee, generated `employee_code`, and `onboarding_id` if a template
matched. In FastAPI this request body is a single `EmployeeCreate` Pydantic model with nested
sub-models (`EmploymentCreate`, `AssignmentCreate`, `CompensationCreate`, `StatutoryCreate`) — the
nesting in the JSON above is the nesting of the Pydantic model, not a hand-assembled dict.

### 3.3 Attendance
```
POST   /attendance/punch                  employee punch (mobile/web)
POST   /attendance/punch/bulk-sync        offline queue sync (array, idempotent)
GET    /attendance/me/today               current state + shift + hours
GET    /attendance/me?from=&to=           own calendar
GET    /attendance/days                   matrix: employees × dates
GET    /attendance/days/{employeeId}/{date}
PATCH  /attendance/days/{employeeId}/{date}   manual override (permissioned, reason required)
POST   /attendance/recompute              range + employee filter → 202 job
GET    /attendance/summary                monthly summary (payroll input contract)
GET/POST /regularisation-requests         POST /regularisation-requests/{id}/approve|reject
GET/POST /ot-requests
GET/POST /shifts                          GET/PATCH/DELETE /shifts/{id}
GET/POST /shift-rosters                   POST /shift-rosters/generate (from pattern)
GET/POST /geofences
GET/POST /attendance-devices              GET /attendance-devices/{id}/health
POST     /attendance/lock                 POST /attendance/unlock
GET      /attendance/exceptions           missing punch, absent without leave, anomalies
```

**`POST /attendance/punch` request:**
```json
{
  "punch_time": "2026-08-03T03:42:11Z",
  "direction": "IN",
  "source": "MOBILE_GPS",
  "location": { "latitude": 10.0159, "longitude": 76.3419, "accuracy_m": 12 },
  "selfie_file_id": "…",
  "device_info": { "device_id": "…", "os": "Android 14", "app_version": "1.4.2",
                   "is_mock_location": false, "device_time": "2026-08-03T09:12:11+05:30" }
}
```
Response `201`:
```json
{ "data": {
    "punch_id": "…", "accepted": true, "direction": "IN",
    "within_geofence": true, "geofence_name": "Kochi Office",
    "attendance_day": { "date": "2026-08-03", "status": "PRESENT",
      "first_in_at": "2026-08-03T03:42:11Z", "worked_minutes": 0,
      "shift": {"name":"General 9-6","start":"09:00","end":"18:00"},
      "late_by_minutes": 12 },
    "message": "Punched in at 9:12 AM. You are 12 minutes late." } }
```
Failure `422`:
```json
{ "error": { "code": "PUNCH_OUTSIDE_GEOFENCE",
    "message": "You are 340 m from Kochi Office. Punch requires approval.",
    "details": [{ "code": "DISTANCE_EXCEEDED",
      "context": { "distance_m": 340, "allowed_m": 100, "can_request_approval": true } }] } }
```

### 3.4 Leave
```
GET    /leave-types                     GET/POST/PATCH /leave-policies
GET    /leave/balances?employee_id=      all types, current year
GET    /leave/balances/{leaveTypeId}/statement    full ledger (the dispute-ender)
POST   /leave/calculate-days            preview day count before submit
GET/POST /leave-applications
GET    /leave-applications/{id}
POST   /leave-applications/{id}/cancel
POST   /leave-applications/{id}/approve · /reject   (via workflow)
GET    /leave/team-calendar?from=&to=&department_id=
GET    /leave/holidays
POST   /leave/accrual/run               manual trigger (admin) → 202
POST   /leave/year-end-process          preview=true|false
GET/POST /comp-off
POST   /leave/encashment-requests
```

**`POST /leave/calculate-days` — call this before every submit; it prevents the majority of
support tickets:**
```json
// request
{ "leave_type_id": "…", "from_date": "2026-08-14", "to_date": "2026-08-18",
  "from_half": "FULL", "to_half": "FULL" }
// response
{ "data": {
   "total_days": 3,
   "breakdown": [
     { "date": "2026-08-14", "counted": 1,   "reason": "Working day" },
     { "date": "2026-08-15", "counted": 0,   "reason": "Holiday: Independence Day" },
     { "date": "2026-08-16", "counted": 0,   "reason": "Weekly off" },
     { "date": "2026-08-17", "counted": 1,   "reason": "Working day" },
     { "date": "2026-08-18", "counted": 1,   "reason": "Working day" }
   ],
   "balance_before": 8.5, "balance_after": 5.5,
   "warnings": [], "requires_document": false,
   "approvers": [{ "level": 1, "name": "Arun K", "designation": "Team Lead" }] } }
```

### 3.5 Payroll
```
GET/POST  /salary-components            GET/PATCH /salary-components/{id}
POST      /salary-components/validate-formula
GET/POST  /salary-structures
POST      /salary-structures/{id}/preview    CTC → breakup preview
GET       /statutory-master?type=PF&as_of=2026-08-01
GET/POST  /pay-runs
GET       /pay-runs/{id}
POST      /pay-runs/{id}/lock-inputs
POST      /pay-runs/{id}/compute              → 202 job
GET       /pay-runs/{id}/status               progress %, current step
GET       /pay-runs/{id}/validation-report
GET       /pay-runs/{id}/variance-report
POST      /pay-runs/{id}/variance/{empId}/acknowledge
POST      /pay-runs/{id}/approve
POST      /pay-runs/{id}/finalise             irreversible
POST      /pay-runs/{id}/cancel               only before finalise
GET       /pay-runs/{id}/payslips
GET       /pay-runs/{id}/bank-advice?bank=HDFC&format=NEFT
GET       /pay-runs/{id}/statutory/{type}     ECR | ESI | PT | 24Q
GET       /pay-runs/{id}/journal-voucher?format=tally
GET       /payslips/me?year=2026
GET       /payslips/{id}                      GET /payslips/{id}/pdf
GET/POST  /payroll-inputs                     ad-hoc earnings/deductions
GET/POST  /loans                              GET /loans/{id}/schedule
GET/POST  /tax-declarations                   POST /tax-declarations/{id}/submit-proof
GET       /tax/computation?employee_id=&fy=2026-27
GET       /tax/regime-comparison?employee_id=&fy=
POST      /fnf-settlements                    GET /fnf-settlements/{id}
GET       /form16?employee_id=&fy=
```

**`GET /pay-runs/{id}/status`** (poll during compute):
```json
{ "data": { "pay_run_id": "…", "status": "COMPUTING",
    "step": "COMPUTE", "step_index": 3, "total_steps": 8,
    "processed": 1840, "total": 5000, "percent": 36.8,
    "started_at": "…", "eta_seconds": 220, "errors": [] } }
```
This status is read from `pay_run.checkpoint` (Document 08 §8.4), updated by the Celery `chain`
after each step — the Celery task IDs themselves are an implementation detail, never exposed in the
API response.

**Payslip line with trace:**
```json
{ "component_code": "HRA", "component_label": "House Rent Allowance",
  "component_type": "EARNING",
  "amount": { "amount": 1800000, "currency": "INR" },
  "ytd_amount": { "amount": 7200000, "currency": "INR" },
  "calculation_trace": {
    "formula": "BASIC * 0.40",
    "inputs": { "BASIC": 5000000, "rate": 0.40 },
    "pre_proration": 2000000,
    "proration": { "payable_days": 27, "total_days": 30, "factor": 0.9 },
    "rounding": { "rule": "NEAREST", "before": 1800000, "after": 1800000 },
    "result": 1800000 } }
```

### 3.6 Recruitment
```
GET/POST  /requisitions                   POST /requisitions/{id}/approve|reject
GET/POST  /job-openings                   POST /job-openings/{id}/publish|close
GET       /careers/openings               PUBLIC, no auth, tenant by subdomain
POST      /careers/openings/{slug}/apply  PUBLIC, rate-limited, captcha
GET/POST  /candidates                     POST /candidates/bulk-upload (ZIP of resumes)
GET       /candidates/{id}                POST /candidates/{id}/merge
POST      /candidates/parse-resume        → 202 job_id (AI, Document 12)
GET/POST  /applications                   PATCH /applications/{id}/stage
POST      /applications/{id}/reject       bulk variant: POST /applications/bulk-reject
GET       /applications/{id}/timeline
GET/POST  /interviews                     POST /interviews/{id}/reschedule|cancel
POST      /interviews/{id}/feedback
GET       /interviews/me                  panel member's schedule
GET/POST  /offers                         POST /offers/{id}/approve|send|revise
POST      /offers/{id}/respond            PUBLIC via signed candidate link
POST      /applications/{id}/convert-to-employee
GET       /recruitment/analytics/funnel|time-to-hire|source-effectiveness
```

### 3.7 Workflow & Approvals
```
GET/POST  /workflow-definitions           POST /workflow-definitions/{id}/publish
GET       /workflow-definitions/{id}/versions
POST      /workflow-definitions/simulate  dry-run routing for a sample entity
GET       /approvals/pending              unified inbox across all entity types
GET       /approvals/{id}
POST      /approvals/{id}/approve         body: {comment}
POST      /approvals/{id}/reject          body: {comment}  — required
POST      /approvals/{id}/request-info
POST      /approvals/bulk-approve         body: {ids[], comment}
GET       /approvals/history?entity_type=&entity_id=
GET/POST  /delegations
```

**`GET /approvals/pending` — the single most-used manager endpoint. Must be one call, mobile-sized:**
```json
{ "data": [
  { "approval_id": "…", "entity_type": "LEAVE_APPLICATION", "entity_id": "…",
    "title": "Casual Leave — 3 days",
    "requester": { "id":"…", "name":"Meera P", "designation":"Executive",
                   "photo_url":"…", "employee_code":"ACM0219" },
    "summary": { "leave_type": "Casual Leave", "from": "2026-08-14",
                 "to": "2026-08-18", "days": 3, "reason": "Family function",
                 "balance_after": 5.5, "team_on_leave_same_days": 1 },
    "submitted_at": "…", "sla_due_at": "…", "is_overdue": false, "level": 1,
    "actions": ["APPROVE","REJECT","REQUEST_INFO"] } ],
  "pagination": { … },
  "meta": { "counts_by_type": { "LEAVE_APPLICATION": 7, "REGULARISATION": 3, "EXPENSE": 2 } } }
```

### 3.8 Onboarding, Exit, ESS, Reports, Notifications, Files
```
GET/POST  /onboarding-templates
GET       /onboardings                    GET /onboardings/{id}/tasks
POST      /onboardings/{id}/tasks/{taskId}/complete
GET       /onboarding/preboarding/{token} PUBLIC candidate portal
POST      /onboarding/preboarding/{token}/submit

GET/POST  /exits                          POST /exits/{id}/accept|withdraw
GET       /exits/{id}/clearance           POST /exits/{id}/clearance/{itemId}/complete
POST      /exits/{id}/exit-interview
GET       /exits/{id}/documents

GET       /ess/dashboard                  single aggregated call for the home screen
GET       /ess/quick-actions

GET       /reports                        catalogue
POST      /reports/{code}/run             → 202 job_id  (or 200 for small reports)
GET       /reports/jobs/{jobId}           status + download URL
GET/POST  /reports/custom                 report builder definitions
POST      /reports/{id}/schedule

GET       /notifications                  in-app inbox
POST      /notifications/{id}/read        POST /notifications/read-all
GET/PATCH /notification-preferences
GET/POST  /notification-templates         admin

POST      /files                          multipart upload → file_id (virus-scanned async)
GET       /files/{id}                     302 to a presigned URL, short TTL
GET       /files/{id}/metadata
POST      /files/presign                  direct-to-S3/MinIO upload for large files
```

### 3.9 Device Ingestion (separate deployable, separate auth — Document 03 §1.1)
```
POST /ingest/v1/punches            device API key auth, batch array, idempotent
POST /ingest/v1/heartbeat
GET  /ingest/v1/commands           device polls for pending commands (user sync, time sync)
POST /ingest/v1/employees/sync     push enrolled users to a device
```
Auth: `X-Device-Serial` + `X-Device-Signature` (HMAC-SHA256 of the body with the device secret).
Never reuse user JWTs for devices. This router lives at `src/hrms/ingestion/routes.py`
(Document 06 §3) and is mounted **only** by the `entrypoints/ingestion.py` ASGI app — it is not
reachable through the Core API process.

---

## 4. Webhooks (outbound to customer systems)

Tenants register endpoints per event; delivery is signed and retried.

```
POST <customer-url>
Headers:
  X-HRMS-Event: employee.joined
  X-HRMS-Delivery-Id: uuid
  X-HRMS-Signature: sha256=<hmac of raw body with the tenant webhook secret>
  X-HRMS-Timestamp: 1754210000
Body:
{ "event": "employee.joined", "occurred_at": "…", "company_id": "…",
  "data": { "employee_id": "…", "employee_code": "…", "email": "…",
            "department": "…", "designation": "…", "joining_date": "…" } }
```

**Available events:** `employee.created|joined|updated|exited`, `leave.approved|rejected|cancelled`,
`attendance.day_finalised`, `payrun.finalised`, `payslip.published`, `candidate.applied`,
`offer.accepted`, `asset.assigned|returned`, `expense.approved`, `ticket.created|resolved`.

Retry: 5 attempts with exponential backoff (1m, 5m, 30m, 2h, 12h), implemented as a Celery task with
`retry_backoff=True` and a max-retries ceiling. After failure, the endpoint is marked degraded and
the tenant admin is alerted. A replay endpoint allows manual redelivery. Consumers must verify the
signature and treat delivery as at-least-once (dedupe on `X-HRMS-Delivery-Id`).

---

## 5. Long-Running Operations Pattern

Any operation that may exceed 5 seconds returns `202` with a job handle:
```json
{ "data": { "job_id": "…", "status": "QUEUED",
            "poll_url": "/v1/jobs/…", "estimated_seconds": 180 } }
```
`GET /v1/jobs/{id}`:
```json
{ "data": { "job_id":"…", "type":"PAYROLL_COMPUTE", "status":"RUNNING",
   "progress": { "processed": 1840, "total": 5000, "percent": 36.8 },
   "result": null, "error": null,
   "started_at":"…", "finished_at": null } }
```
On completion, `result` carries the download URL or the resource id, and a notification is sent.
Applies to: payroll compute, imports, exports, report generation, bulk letter generation, payslip
PDF batches, resume bulk parsing, attendance recompute. `job_id` maps to a Celery task id internally
but is a platform-owned UUID recorded in `job_log` (Document 08 §11) — the API never leaks a raw
Celery task ID, so the queue implementation could change without an API contract break.

Optionally expose Server-Sent Events at `/v1/jobs/{id}/stream` for live progress bars — FastAPI's
native `StreamingResponse` makes this a small addition once the polling endpoint exists.

---

## 6. API Security Requirements

| Control | Requirement |
|---|---|
| Transport | TLS 1.2+ only; HSTS; no mixed content |
| Tenant isolation | `X-Company-Id` validated against `user_company` on **every** request; mismatch → 404 |
| Authorization | Declarative dependency per endpoint: `Depends(require_permission("LEAVE.APPROVE"))` — an endpoint with no explicit permission dependency **fails the build**, enforced by a CI check that inspects every registered route's dependency list against an allow-list of intentionally-public paths (careers page, webhooks, health check) |
| Data scope | Applied in the repository layer; every list endpoint has an automated test asserting scope enforcement (Document 15 §6) |
| Field masking | Response Pydantic models strip RESTRICTED fields server-side (Document 19 §6) — achieved with per-role response model selection or field-level exclusion, never by trusting the client to ignore a field it received |
| Input validation | Every endpoint's request body is a Pydantic model with `model_config = ConfigDict(extra="forbid")` — unknown properties are rejected, not silently ignored |
| Mass assignment | Explicit Pydantic `Create`/`Update` schemas per endpoint; never binding a request body directly onto an ORM model |
| SQL injection | SQLAlchemy parameterised queries only; any raw SQL (payroll aggregation, Document 08 §1) is parameterised and reviewed |
| File upload | Type allow-list, magic-byte check, size cap (10 MB docs / 25 MB bulk), virus scan before access, never served from the app domain |
| SSRF | No user-supplied URLs fetched server-side without an allow-list |
| CORS | Explicit origin allow-list per tenant; no wildcard with credentials |
| Secrets | Never in code or logs; AWS Secrets Manager with rotation (Document 13) |
| PII in logs | Redaction middleware for email, phone, PAN, Aadhaar, account numbers, salary |
| Enumeration | Random UUIDs everywhere; no sequential ids in URLs |
| Public endpoints | Careers apply, offer respond, preboarding — all rate-limited, captcha-protected, signed-token based |

---

## 7. Versioning & Deprecation Policy

- Breaking changes require a new major version path (`/v2`).
- Additive changes (new optional fields, new endpoints) ship in the current version.
- Clients must **ignore unknown fields** — stated in the developer guide and enforced in the SDKs.
- Deprecation: `Deprecation` and `Sunset` headers, minimum 6 months' notice, migration guide,
  usage dashboard so we know who still calls the old endpoint before removing it.
- Mobile apps: the server supports the current and the previous two app minor versions;
  `X-Client-Version` is checked and a forced-upgrade response (`426`) is returned below the floor.

See Document 07 §10 for the code-organisation consequence of running two API versions in parallel.

---

## 8. API Deliverables Checklist

- [ ] OpenAPI 3.1 spec generated natively by FastAPI and CI-validated against a committed snapshot
      (a diff on every PR makes an accidental breaking change visible in review)
- [ ] Postman/Bruno collection with environment files per environment
- [ ] Contract tests (schema-based, against the OpenAPI spec) between web/mobile and API
- [ ] TypeScript client SDK generated from OpenAPI (`openapi-typescript` or equivalent), published to
      the frontend/mobile workspace — the frontend remains TypeScript (Document 04 §1) and benefits
      from a generated client exactly as before
- [ ] Mock server from the OpenAPI spec so frontend and mobile can develop against a contract before
      an endpoint's real implementation lands
- [ ] Developer portal with authentication guide, webhook guide, error catalogue, and a sandbox tenant
