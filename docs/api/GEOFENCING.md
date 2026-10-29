# Attendance geofencing — API contract

Hand-written (the generator in `tools/build_api_docs.py` currently aborts on an unrelated, pre-existing drift — `GET /metrics` is routed but absent from its OpenAPI view — so the generated `modules/` and `openapi.json` do **not** yet list these endpoints). Source of truth: `apps/api/src/hrms/modules/attendance/geofence*.py`. Narrative, privacy and rollout: [`../operations/ATTENDANCE_GEOFENCING.md`](../operations/ATTENDANCE_GEOFENCING.md).

## Concepts
* **Workplace geofence = a `Branch`** that has `latitude`, `longitude` and `geofence_radius_m` (no second location model). Edited through the existing branch API/screen.
* **Applicable workplaces** for a punch are resolved on the server only: the branch on the employee's assignment as of today (UTC date) **plus** administrator-created *workplace authorisations*. Inactive branches and branches without coordinates/radius are ignored. Nothing about the workplace, company, employee or thresholds is read from the request.
* **Policy** — three new fields on each *attendance policy version* (versioned/immutable once published, like every other policy field):

| Field | Values | Default |
|---|---|---|
| `geofence_mode` | `DISABLED` · `OPTIONAL` · `REQUIRED` | `DISABLED` |
| `geofence_max_accuracy_m` | 5 – 500 | 100 |
| `geofence_max_age_seconds` | 5 – 300 | 60 |

  `DISABLED`: nothing is evaluated or stored; any location sent is ignored. `OPTIONAL`: evaluated and recorded, **never blocks**. `REQUIRED`: a self-service punch is refused unless the outcome is `INSIDE`.
* Only **self-service** punches are checked: `POST /attendance/punches/me` (source `WEB`) and `POST /attendance/face-punches/me` (source `FACE`). HR corrections (`POST /attendance/punches`, source `ADMIN`) and regularizations are never location-checked.

## Decision rules (first failing rule wins)
1. Non-finite / out-of-range numbers, or a naive timestamp → `LOCATION_INVALID`
2. `captured_at` more than 30 s ahead of the server clock → `LOCATION_INVALID`
3. `captured_at` older than `geofence_max_age_seconds` → `LOCATION_STALE`
4. `accuracy_m` greater than `geofence_max_accuracy_m` → `LOCATION_TOO_INACCURATE`
5. No applicable workplace → `NO_APPLICABLE_WORKPLACE`
6. Haversine distance (mean Earth radius 6 371 008.8 m, rounded to 1 cm) to the nearest workplace centre **≤ radius** → `INSIDE` (the boundary is inclusive)
7. Otherwise `OUTSIDE_GEOFENCE`, or `OUTSIDE_GEOFENCE_UNCERTAIN` when `distance − accuracy ≤ radius` (still refused; the app should tell the user to improve the fix and retry).

"Nearest" = smallest `distance − radius`; ties break on the smaller branch id. The radius is never widened for poor accuracy. No location with `REQUIRED` → `LOCATION_REQUIRED`; the app reporting it could not get one → `LOCATION_UNAVAILABLE_CLIENT`.

## Punch request additions
`POST /v1/attendance/punches/me` (JSON; `extra="forbid"` still applies — no company/employee/branch/threshold fields exist):
```json
{ "direction": "IN",
  "idempotency_key": "…",
  "location": { "latitude": 9.9312, "longitude": 76.2673, "accuracy_m": 12.5,
                "captured_at": "2026-10-28T09:00:00Z" },
  "location_error": null }
```
`location` and `location_error` are mutually exclusive. `location_error` ∈ `PERMISSION_DENIED`, `PERMISSION_DENIED_FOREVER`, `SERVICES_DISABLED`, `TIMEOUT`, `UNAVAILABLE`. `captured_at` must carry a UTC offset.

`POST /v1/attendance/face-punches/me` (multipart) adds the form fields `location_latitude`, `location_longitude`, `location_accuracy_m`, `location_captured_at` (all four or none) **or** `location_error`. The location is checked **before** the liveness challenge is consumed or any face work is done, and again authoritatively at write time, so a refused location does not spend the one-time challenge.

### Success
`201` as before; `PunchRead.geofence` is `null` when the policy is `DISABLED` and otherwise
```json
{ "mode": "REQUIRED", "outcome": "INSIDE", "accepted": true,
  "workplace_name": "Kochi Office", "distance_m": 42.7, "radius_m": 100, "accuracy_m": 12.5 }
```
(no coordinates are ever returned to the employee).

### Refusal
`422`, `error.code` = `PUNCH_<OUTCOME>`, `error.details[0] = { field: "location", code: "<OUTCOME>", message, context: { distance_m, radius_m, accuracy_m, workplace_name } }`. Codes: `PUNCH_OUTSIDE_GEOFENCE`, `PUNCH_OUTSIDE_GEOFENCE_UNCERTAIN`, `PUNCH_LOCATION_TOO_INACCURATE`, `PUNCH_LOCATION_STALE`, `PUNCH_LOCATION_INVALID`, `PUNCH_LOCATION_REQUIRED`, `PUNCH_LOCATION_UNAVAILABLE_CLIENT`, `PUNCH_NO_APPLICABLE_WORKPLACE`. A refusal **creates no punch**, does not consume the `idempotency_key` (retry with the same key and a better fix), records one `geofence_attempt` row and one `PUNCH_REJECTED_GEOFENCE` audit event. A replay of an already-recorded key returns the original punch without re-evaluating the location.

## Endpoints
| Method & path | Permission | Notes |
|---|---|---|
| `GET /v1/attendance/geofence-policy/me` | `ATTENDANCE.PUNCH` | `{mode, max_accuracy_m, max_age_seconds}` for the caller's own resolved policy. Informational: lets the app decide whether to capture a location. |
| `GET /v1/attendance/geofences` | `ATTENDANCE.POLICY_MANAGE` | Every branch with coordinates, radius, `configured`, `assigned_employee_count`, `authorized_employee_count`. |
| `GET /v1/attendance/workplace-authorizations` | `ATTENDANCE.POLICY_MANAGE` | Filters `employee_id`, `branch_id`; paginated. |
| `POST /v1/attendance/workplace-authorizations` | `ATTENDANCE.POLICY_MANAGE` | `{employee_id, branch_id}`. 404 for an employee/branch of another company, 422 if the branch is inactive or lacks coordinates/radius, 409 if it already exists. Audited `WORKPLACE_AUTHORIZATION_ADDED`. |
| `DELETE /v1/attendance/workplace-authorizations/{id}` | `ATTENDANCE.POLICY_MANAGE` | 204. Audited `WORKPLACE_AUTHORIZATION_REMOVED`. |
| `GET /v1/attendance/geofence-attempts` | `ATTENDANCE.VIEW_ALL` (data-scoped) | Filters `employee_id`, `accepted`, `outcome`, `since`, `until`; newest first; limited to employees in the caller's data scope. Coordinates are rounded to 4 dp. |

`PATCH /v1/branches/{id}` with `is_active=false` now also fails with `409 BRANCH_HAS_WORKPLACE_AUTHORIZATIONS` while employees are authorised to punch there (it already failed while employees or departments are assigned).

## Exceptions and corrections
There is no new approval system. A rejected attempt stays on record as rejected; an employee who was genuinely at work uses the existing regularization workflow (`POST /regularizations`, reason mandatory, approval and audit as before) or HR records an on-behalf punch (`POST /attendance/punches`, `ATTENDANCE.PUNCH_ON_BEHALF`, reference mandatory).

## Rate limiting
`POST /attendance/punches/me` now has a per-tenant-per-IP flood ceiling (`PUNCH_REQUESTS_PER_MINUTE_PER_IP`, default 600 — same shape as the face-punch ceiling). The face endpoint keeps its own.

## Settings
`GEOFENCE_ATTEMPT_RETENTION_DAYS` (default 90, 1–3650) — attempts older than this are purged by `GeofenceService.purge_expired_attempts`. **Scheduling that purge is a deployment step** (see the operations doc).
