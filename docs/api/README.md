# HRMS API documentation for mobile development

Audit-based documentation of the API **as implemented** in `apps/api` (FastAPI, API prefix `/v1`, 333 operations). Nothing here is aspirational: each claim is traced to source code or to a recorded call against a running server, and anything unverified is labelled. Start with the audit verdict if you need to know whether to build now.

| Read this | When |
|---|---|
| [REMEDIATION_REPORT.md](REMEDIATION_REPORT.md) · [OFFLINE_ATTENDANCE_DESIGN.md](OFFLINE_ATTENDANCE_DESIGN.md) | What was fixed after the audit (C-1, H-1, H-3, H-4, H-6), what is blocked on decisions, exact test commands and results; the offline-attendance decision record |
| [API_CONTRACT_AUDIT.md](API_CONTRACT_AUDIT.md) | Is the backend ready? Critical/high blockers (e.g. the default `EMPLOYEE` role cannot punch — C-1), evidence, fixes |
| [API_OVERVIEW.md](API_OVERVIEW.md) | Base URLs, envelopes, headers, data types, pagination, idempotency, rate limits, upload limits |
| [AUTHENTICATION.md](AUTHENTICATION.md) | Login, rotating refresh cookie, revocation, registration, invites, roles/permissions/data scope, diagrams |
| [ERROR_HANDLING.md](ERROR_HANDLING.md) · [ERROR_CODES.md](ERROR_CODES.md) | Error envelope, status policy, client decision tree · all 291 codes |
| [API_WORKFLOWS.md](API_WORKFLOWS.md) | End-to-end flows with diagrams (sign-in, invite, punch, face punch, leave, payslips, onboarding…) and the list of missing capabilities |
| [MOBILE_INTEGRATION_GUIDE.md](MOBILE_INTEGRATION_GUIDE.md) | Client setup, serialization, timeouts/retries, offline, uploads — Dart (from the repo), Kotlin, Swift, TypeScript |
| [DATA_MODELS.md](DATA_MODELS.md) · [models/](models/) | Shared schemas, per-module data dictionaries, [string vocabularies](models/ENUMS.md) |
| [ENDPOINT_INVENTORY.md](ENDPOINT_INVENTORY.md) | Registry of all 333 operations by module (auth, permission, tier, tests) |
| [modules/](modules/) | One reference per module, a section per endpoint: [identity](modules/identity.md) · [organisation](modules/organisation.md) · [employee](modules/employee.md) · [attendance](modules/attendance.md) · [leave](modules/leave.md) · [payroll](modules/payroll.md) · [onboarding](modules/onboarding.md) · [account_invite](modules/account_invite.md) · [employee_import](modules/employee_import.md) · [platform](modules/platform.md) *(not for mobile)* · [health](modules/health.md) |
| [GEOFENCING.md](GEOFENCING.md) · [../operations/ATTENDANCE_GEOFENCING.md](../operations/ATTENDANCE_GEOFENCING.md) | Location-checked attendance: policy modes, punch request/response additions, geofence/authorisation/attempt endpoints, privacy, security limits, rollout (hand-written; not yet in the generated inventory) |
| [PERMISSIONS.md](PERMISSIONS.md) | Permission codes and the routes that use them |
| [openapi.json](openapi.json) | Enriched OpenAPI 3.1 (servers, security schemes incl. refresh cookie, error envelope, `x-hrms-*` metadata) |
| [postman/](postman/) | Importable collection + environment template |
| [examples/](examples/) | **Recorded** request/response pairs: [auth & session](examples/auth-and-session.md) · [conventions & errors](examples/conventions-and-errors.md) · [employee self-service](examples/employee-self-service.md) |
| [tools/](tools/) | Generators: `build_api_docs.py` (inventory, modules, models, OpenAPI, Postman), `record_examples.py` (live examples) |

## What is generated vs. hand-written
* **Generated** (re-run after any API change, from the repo root): `apps/api/.venv/bin/python -I docs/api/tools/build_api_docs.py` → `ENDPOINT_INVENTORY.md`, `modules/`, `models/`, `ERROR_CODES.md`, `PERMISSIONS.md`, `openapi.json`, `postman/`. It aborts if the route table and `app.openapi()` disagree. Request/response *examples* in `modules/` are **schema-derived and illustrative, not executed**.
* **Recorded**: `examples/` — real calls, secrets redacted (`record_examples.py`; needs a throwaway server, see its docstring).
* **Hand-written**: this page, the overview, authentication, error handling, workflows, mobile guide, data-model overview and the audit.

## Evidence legend used throughout
**[recorded]** exercised against a live server · **[source]** read from code but not executed · **[doc-gen]** derived from the generated inventory/OpenAPI · *inferred* / *not verified* are stated explicitly where they apply.

## Ground rules for the mobile client (summary)
1. Bearer access token (15 min) + HttpOnly **refresh cookie** (30 days, rotating, reuse = revoke-all) — keep a persistent cookie jar; one refresh in flight.
2. Every success is `{data, meta}` / `{data[], pagination|null, meta}`; every error is `{error:{code,message,details[],request_id}}` — branch on `code`.
3. Employee-scoped calls need `employee_id` from `GET /v1/auth/me`; it is `null` for the registering admin.
4. Money is integer minor units; decimals are strings; dates are plain `YYYY-MM-DD` in the company timezone; instants are UTC `Z`.
5. Send `If-Match: <version>` on versioned edits and a fresh `Idempotency-Key` on the four operations that require it.
6. Most lists are **not** paginated — always bound them with filters.
