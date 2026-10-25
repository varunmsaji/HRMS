# Data models & schema dictionary

* **Per-module field dictionaries (generated from the live Pydantic/OpenAPI schemas, 455 schemas):** [models/](models/) — `employee`, `attendance`, `leave`, `payroll`, `organisation`, `onboarding`, `account_invite`, `employee_import`, `platform`, `identity` (auth/session), `shared` (money/date helpers, envelopes), and [models/ENUMS.md](models/ENUMS.md) for string vocabularies that OpenAPI types as plain `string`.
* This page covers what is *shared* by all models and the inconsistencies between representations. Field-level request/response tables for each endpoint are in [modules/](modules/).

## 1. Shared building blocks

### Envelopes
```text
DataEnvelope<T>  { data: T,   meta: ResponseMeta }
ListEnvelope<T>  { data: T[], pagination: PaginationMeta | null, meta: ResponseMeta }
ResponseMeta     { request_id: string, server_time: string | null }          // server_time ISO-8601 UTC "Z"
PaginationMeta   { page: int, per_page: int, total: int, total_pages: int, next_cursor: string | null /* never set */ }
ErrorEnvelope    { error: { code, message, details: [{field?, code, message, context?}], request_id, documentation_url? } }
```
OpenAPI generates one concrete schema per instantiation (`DataEnvelope_PayslipRead_`, …); they are omitted from the dictionaries and described here once.

### Identity / session models ([`models/identity.md`](models/identity.md))
| Model | Fields | Notes |
|---|---|---|
| `LoginRequest` | `email` (email), `password` (1–128), `company_id?` (uuid|null) | |
| `PublicTokenResponseData` | `access_token`, `token_type="Bearer"`, `expires_in_minutes` (int, **minutes**), `company_id`, `companies[CompanySummary]` | No `refresh_token` — cookie only. The internal `TokenResponseData` (with `refresh_token`) is never serialised to clients. |
| `CompanySummary` | `id`, `name`, `is_primary` | |
| `MeResponseData.user` (`UserProfile`) | `id`, `email|null`, `company_id`, `employee_id|null`, `permissions[]` (strings), `company_timezone` (IANA), `company_status` (default `"ACTIVE"`) | **No name/avatar fields** — fetch the person from `/employees/{employee_id}`. `company_status` ∈ `PENDING_APPROVAL, TRIAL, ACTIVE, SUSPENDED, REJECTED, TERMINATED` (REJECTED/TERMINATED never reach a signed-in client). |
| `RefreshRequest` | `refresh_token?` | optional alternative to the cookie |
| `CompanyDetail` | `id`, `name`, `status` | `GET /auth/companies/{id}` (own company only) |

### Cross-cutting field patterns (observed across `*Read` models)
| Pattern | Meaning |
|---|---|
| `id` (uuid), `company_id` (uuid) | Server-generated, read-only. `company_id` is always your tenant. |
| `version` (int) — present on 50 of 105 `*Read` models | Optimistic-concurrency token; echo as `If-Match`. |
| `created_at`, `updated_at`, `*_at` | Server-generated instants. 159 such fields are typed plain `string` and only 15 carry `format: date-time` — all are ISO-8601 UTC (`…Z`). |
| `is_active` (bool) | Soft-delete/deactivation flag; `DELETE` on master data sets it false. |
| `status` / `*_status` | Closed vocabulary but typed `string` in most models (48 fields) — values in [models/ENUMS.md](models/ENUMS.md). |
| `*_minor` (int) | Money in minor units (paise). |
| decimal strings | `"1.50"`; 21 fields carry the decimal regex, a few similar fields (`paid_days`, `lop_days` in payroll/attendance-period summaries) are bare `string`. |
| `*_by_user_id` / `*_by` | Audit actor ids, read-only. |
| `custom_fields` | Free-form `object|null`. |

### Request vs. response representations
For each resource the code uses separate `*Create`, `*Update` (PATCH, all optional), and `*Read` models. The generated dictionaries list, per `*Read`, the fields that are absent from the matching `*Create`/`*Update` as "server-generated / read-only" (an inference from names, not a declared flag). Rules observed in schemas:
* `*Update` models never accept immutable keys (e.g. `HolidayUpdate` has no `date`/`calendar_id`; `CalendarExceptionUpdate` no date/type) — corrections are deactivate-then-insert.
* Some request models set `extra="forbid"` (e.g. `RegularizationRequestedPunchInput`, `PunchCreateSelf`), so an unknown key is a `422`; others are lenient. *Per-model behaviour is in the source `schemas.py`; do not rely on lenient models silently dropping fields in the future.*
* `AwareIsoDatetime` fields (on-behalf punch time, regularization `requested_time`) **require a timezone offset**; naive datetimes are rejected.

## 2. Identifier & reference semantics
* All references are UUIDs; there are no human-readable keys in paths. Human codes exist as data (`employee_code` e.g. `EMP-0001`, policy `code`, leave type `code`) and are unique per company where noted by `*_CODE_ALREADY_EXISTS` errors.
* `employee_id` vs `user_id`: a `user` is a login identity (global, email-unique, may belong to several companies); an `employee` is the HR record inside one company. The token carries both; `employee_id` may be `null`.
* Effective-dated resources (employee assignments, compensation, statutory, bank; policy versions; shift versions; policy assignments) are append-only histories with `effective_from`/`effective_to`; reads accept `as_of`. Writes close the open row and insert a new one (that is why `If-Match` is "required only when a current row exists").

## 3. Inconsistencies between database, schema and wire (documented, not hidden)
| # | Observation | Evidence | Mobile impact |
|---|---|---|---|
| D-1 | Timestamps are formatted manually in many `*Read` builders and declared as bare `string`, so generated clients will not type them as dates. | `attendance/schemas.py:_format_timestamp`; 159 vs 15 fields | Parse manually; do not trust generated types. |
| D-2 | Closed vocabularies (direction, status, request_type, half_day, …) appear as `string` in OpenAPI though validators restrict them. | [models/ENUMS.md](models/ENUMS.md) | Code-gen yields stringly-typed APIs; maintain enums by hand and tolerate unknown values. Not every vocabulary is available even there (e.g. regularization `request_type`). |
| D-3 | Decimal handling is mixed: regex-typed decimal strings vs untyped strings vs ints (`*_minor`). | stats above | Use a decimal type; treat all as strings. |
| D-4 | Unpaginated lists return `pagination: null`, paginated lists an object — same `ListEnvelope` type. | recorded | Null-check `pagination`. |
| D-5 | `FacePunchRead.similarity` is a decimal string while `liveness_score` is an optional decimal string; `PunchRead.source` is a free `string` and a self punch is labelled `"WEB"`. | recorded/source | Don't branch on `source` to detect mobile. |
| D-6 | Several response schemas are declared as `{}` (CSV/image/binary endpoints). | OpenAPI | Handle by content type. |
| D-7 | OpenAPI marks `Idempotency-Key` as an optional header on endpoints where the dependency makes it mandatory; the published [openapi.json](openapi.json) corrects this. | `generated vs enriched` | Use the enriched spec. |
| D-8 | `X-Company-Id` is declared as an optional header on every route but only validated (against the token) when sent. | code | Safe to omit. |
| D-9 | Enum-typed fields that *are* declared (e.g. `FaceLivenessSessionCreate.direction` `IN|OUT`, `AssignmentCreate.change_type`) coexist with undeclared ones of the same concept (`PunchCreateSelf.direction` is `string`). | OpenAPI | Same values, different typing. |

## 4. Where to find each model
| Domain | Dictionary |
|---|---|
| Auth/session (login, tokens, `/auth/me`) | [models/identity.md](models/identity.md) |
| Money/date helpers, pagination & error schemas | [models/shared.md](models/shared.md) |
| Company, legal entity, branch, department, designation, grade, shift(+version), holiday/work calendars, weekly-off, policy assignment | [models/organisation.md](models/organisation.md) |
| Employee, employment, assignment, compensation, statutory, bank, education, experience, dependents, documents | [models/employee.md](models/employee.md) |
| Punch, attendance day/period, policies, roster, regularization, overtime, leave projection, face profile/enrollment/punch | [models/attendance.md](models/attendance.md) |
| Leave type/policy/ledger/application | [models/leave.md](models/leave.md) |
| Salary components/structures, pay runs, payslip, statutory rates, adjustments | [models/payroll.md](models/payroll.md) |
| Onboarding case/section/document | [models/onboarding.md](models/onboarding.md) |
| Users, invites, roles | [models/account_invite.md](models/account_invite.md) |
| Employee import batch/row errors | [models/employee_import.md](models/employee_import.md) |
| Platform console | [models/platform.md](models/platform.md) |
