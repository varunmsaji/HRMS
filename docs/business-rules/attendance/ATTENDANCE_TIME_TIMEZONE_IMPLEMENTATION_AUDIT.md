# Attendance — Time, Timestamp & Timezone Implementation Audit

**Audit date:** 2026-09-15
**Scope:** How the HRMS determines the instant of an attendance event and converts it to a local attendance date/time.
**Type:** AUDIT ONLY — no application code was changed, refactored, or fixed as part of this work.
**Method:** Source inspection of `apps/api`, `apps/web`, `alembic/versions`, `docs/`, `docker-compose.yml`, plus read-only execution of the shipped pure functions and a live `SHOW TimeZone` against the dev Postgres. Findings marked *(verified)* were reproduced by running the actual code; all others are direct source citations.

> **Superseded as the action surface (2026-09-15).** This audit remains the evidence of record for `F-01`…`F-27`. The **canonical** artefact for decisions, remediation sequencing and the test plan is
> [`../../audits/ATTENDANCE_TIMEZONE_DECISION_AND_REMEDIATION.md`](../../audits/ATTENDANCE_TIMEZONE_DECISION_AND_REMEDIATION.md). No finding was renamed.

---

## Executive Verdict

> ## **HIGH RISK**

The attendance **calculation engine** is genuinely well built: it is a pure, side-effect-free module that stores UTC, resolves an IANA timezone through an explicit documented precedence chain, and performs every comparison in tz-aware UTC. DST is handled correctly *(verified)*. That half of the system is close to production quality.

The **ingestion boundary is not**. The server accepts a fully client-supplied `punch_time` with no validation of any kind, the only shipped client always sends one, and the field is exposed in the UI as a freely editable text input. There is no upper bound, no lower bound, no clock-skew tolerance, no requirement that the timestamp be timezone-aware, and no restriction on which `source` an ordinary employee may claim. Attendance times are, in effect, self-declared.

This is not a timezone-arithmetic problem. The timezone arithmetic is right. It is an **authoritative-clock and input-validation problem**, and it sits directly upstream of payroll.

Three things must be true before this is production-ready:

1. A decision is recorded on whether client-supplied punch times are permitted at all (§3, DEC-TZ-01) — this is a **policy gap**, not merely a bug: no document in the repository states what the intended behaviour is.
2. The validation gaps in §27 are closed at the API boundary.
3. The four silent-no-op / correctness defects in §30 (F-04 dead rounding, F-05 cross-midnight breaks, F-06 dead night window, F-07 naive timestamps) are resolved.

Not production-ready for payroll-grade attendance.

---

## 1. Current Architecture

There is **no Flutter or mobile application in this repository** (`find . -name pubspec.yaml` returns nothing). The only client is the Next.js web app in `apps/web`. All mobile-specific questions in the audit brief are answered against that fact in §18, §19, §21, §22.

```
┌──────────────────────────────────────────────────────────────────────┐
│ Next.js web client (apps/web)                                        │
│   punch-entry-dialog.tsx — <input type="datetime-local">, user-edits │
│   nowForDatetimeLocal()  — seeds from BROWSER clock                  │
│   new Date(punchTime).toISOString() — BROWSER tz → UTC               │
└───────────────────────────────┬──────────────────────────────────────┘
                                │ POST /v1/attendance/punches
                                │ { employee_id, punch_time, direction, reference }
┌───────────────────────────────▼──────────────────────────────────────┐
│ FastAPI router — attendance/router.py:752 create_punch               │
│   RBAC: ATTENDANCE.PUNCH (self) | ATTENDANCE.PUNCH_ON_BEHALF (other) │
│   default_source = "WEB" (self) | "ADMIN" (on-behalf)                │
└───────────────────────────────┬──────────────────────────────────────┘
┌───────────────────────────────▼──────────────────────────────────────┐
│ PunchService.record_punch — service.py:2300                          │
│   _ensure_employee_visible(target)      ← authorization, solid       │
│   _ensure_date_open(punch_time.date())  ← period lock, UTC date      │
│   punch_time = body.punch_time OR datetime.now(UTC)   ◄── NO CHECKS  │
│   source     = body.source OR default_source          ◄── NO CHECKS  │
│   created_at = datetime.now(UTC)        ← true server receipt time   │
└───────────────────────────────┬──────────────────────────────────────┘
┌───────────────────────────────▼──────────────────────────────────────┐
│ punch table — TIMESTAMPTZ, append-only, RLS by company_id            │
└───────────────────────────────┬──────────────────────────────────────┘
        (no scheduled job — calculation is on-demand only, see §9)
┌───────────────────────────────▼──────────────────────────────────────┐
│ AttendanceDayService.calculate(company, employee, target_date)       │
│   _build_calculation_input — service.py:2711                         │
│     employment / assignment / branch / roster / shift version        │
│     resolve_timezone(shift > branch > company)   calculation.py:294  │
│     resolve_schedule_window → UTC load + scheduled spans             │
│     load punches in UTC window, ordered by punch_time                │
│   calc.evaluate_day(inputs)  ← pure, in-memory, UTC throughout       │
└───────────────────────────────┬──────────────────────────────────────┘
┌───────────────────────────────▼──────────────────────────────────────┐
│ attendance_day — one row per (company, employee, attendance_date)    │
│   stores the resolved `timezone` string alongside the result         │
└───────────────────────────────┬──────────────────────────────────────┘
┌───────────────────────────────▼──────────────────────────────────────┐
│ Web UI — format.ts formatClockTime/formatDateTime                    │
│   toLocaleTimeString(undefined, …) → renders in VIEWER's browser tz  │
│   (NOT the attendance_day.timezone the backend calculated against)   │
└──────────────────────────────────────────────────────────────────────┘
```

### Layer table

| Layer | File / symbol | Input | Output | Timestamp source | TZ source | Conversion | Validation |
|---|---|---|---|---|---|---|---|
| Client form | `punch-entry-dialog.tsx:33` `nowForDatetimeLocal` | — | `YYYY-MM-DDTHH:mm` | **Browser clock** | Browser tz | UTC-shift for display | none |
| Client submit | `punch-entry-dialog.tsx:94` | edited string | ISO-8601 Z | Browser clock | **Browser tz** | `new Date(s).toISOString()` | none |
| Schema | `schemas.py:1234` `PunchCreate.punch_time` | JSON | `datetime \| None` | client | offset in string, **or none** | Pydantic parse | direction + source enum only |
| Router | `router.py:752` `create_punch` | body | — | — | — | — | RBAC scope only |
| Service | `service.py:2337,2353` | body | row dict | `body.punch_time or now` | — | none | period lock only |
| Repository | `repository.py` `PunchRepository.insert` | dict | ORM row | — | — | asyncpg → TIMESTAMPTZ | DB CHECKs |
| Database | `punch.punch_time TIMESTAMPTZ` | — | UTC instant | — | UTC | libpq normalise | direction/source CHECK |
| Engine in | `service.py:2711` `_build_calculation_input` | dates | `AttendanceCalculationInput` | DB | **shift > branch > company** | `_local_to_utc` | fail-closed on missing config |
| Engine | `calculation.py:757` `evaluate_day` | inputs | result | — | `inputs.timezone` | UTC arithmetic | — |
| Persist | `AttendanceDay` | result | row | `calculated_at` | stores `timezone` | — | — |
| Serialize | `schemas.py:88` `_format_timestamp` | datetime | `…Z` string | — | UTC | `isoformat()`, `+00:00`→`Z` | — |
| UI | `format.ts:14,19` | ISO | display string | — | **Viewer browser tz** | `toLocaleTimeString` | — |

---

## 2. Timestamp Lifecycle

Five distinct instants exist for one punch. Only two are persisted:

| # | Instant | Persisted? | Column | Authoritative for attendance? |
|---|---|---|---|---|
| 1 | User opens dialog | no | — | no |
| 2 | Value in the `datetime-local` input (**user-editable**) | **yes** | `punch.punch_time` | **YES** |
| 3 | HTTP request sent | no | — | no |
| 4 | Server begins handling — `datetime.now(UTC)` (`service.py:2337`) | **yes** | `punch.created_at` | **no** (metadata only) |
| 5 | DB `now()` default | only if `created_at` omitted (it never is) | — | no |

The system therefore persists both the claimed time and the true server receipt time, but **never compares them** and never uses #4 for any calculation. The reconciliation data exists; nothing reads it.

---

## 3. Authoritative Clock

> **The authoritative clock is the client's clock.**

```
Source:    Client-submitted value (browser clock, user-editable)
File:      apps/api/src/hrms/modules/attendance/service.py
Function:  PunchService.record_punch
Line:      2353    "punch_time": body.punch_time or now,
Timezone:  Whatever offset the client encodes; may be absent entirely
Used for:  Every downstream attendance calculation
```

```
Source:    Server — datetime.now(UTC)
File:      apps/api/src/hrms/modules/attendance/service.py
Function:  PunchService.record_punch
Line:      2337    now = datetime.now(UTC)
Timezone:  UTC (explicit, correct)
Used for:  punch.created_at (audit metadata); fallback punch_time only when
           the client omits the field — which the shipped UI never does
```

The server-time fallback at line 2353 is **dead in practice**: `punch-entry-dialog.tsx:94` unconditionally sends `punch_time`. Server time is never the attendance time in any shipped flow.

### Complete inventory of attendance-participating timestamp creation

| Source | File:line | Timezone | Used for |
|---|---|---|---|
| `datetime.now(UTC)` | `service.py:2337` | UTC | `created_at`; unused `punch_time` fallback |
| `datetime.now(UTC)` | `service.py:3556` | UTC | monthly regularization request cap |
| `date.today()` | `service.py:3502` | **server OS local** | regularization future-date rejection |
| `date.today()` | `service.py:3547` | **server OS local** | regularization backdating window |
| `date.today()` | `leave/service.py:1979, 2597` | **server OS local** | leave backdating / effective date |
| `func.now()` | `core/db/base.py` `TimestampMixin` | UTC (server default) | `created_at` / `updated_at` |
| `server_default now()` | `alembic/…_punch.py` | UTC | `punch.created_at` default (always overridden) |
| `new Date()` | `punch-entry-dialog.tsx:34` | browser | **seeds the attendance timestamp** |
| `new Date().toISOString()` | `format.ts:28` `todayIso` | **UTC** | default date filters in 4 web pages |

`date.today()` is server-OS-local and therefore environment-dependent — see §4.

---

## 4. Server Timezone

| Layer | Configured value | Evidence |
|---|---|---|
| API container | **not set** → UTC | `apps/api/Dockerfile` contains no `TZ`/`ENV TZ`; `python:3.12-slim` defaults to UTC |
| Dev host (this machine) | **Asia/Kolkata (+05:30)** | `timedatectl` *(verified)* |
| Postgres container | **UTC** | `SHOW TimeZone` → `UTC` *(verified)*; `docker-compose.yml` sets no `TZ`/`PGTZ` |
| Application setting | `Asia/Kolkata` | `core/config/settings.py:32` `app_timezone_default` |
| Actual use of that setting | **Celery only** | `core/celery_app.py:18`; grep confirms no other reference |

**The API is not pinned to any timezone.** It runs UTC in Docker and Asia/Kolkata on the developer host. `app_timezone_default` looks like an application-wide timezone but is consumed exclusively by the Celery beat scheduler; **no attendance code path reads it**.

Consequence: the four `date.today()` call sites in §3 and the naive-datetime coercion in §7/F-07 produce **different results in dev and production** from identical input. Neither environment is "wrong" — nothing declares which is intended.

---

## 5. Database Timestamp Model

All attendance timestamp columns are `TIMESTAMPTZ` (`timestamp with time zone`). There are **no `timestamp without time zone` columns** anywhere in the attendance schema — this is a genuine strength.

| Table | Column | Type | Null | Default | TZ-aware | Meaning |
|---|---|---|---|---|---|---|
| `punch` | `punch_time` | TIMESTAMPTZ | no | — | yes | **Claimed** event instant (client-supplied) |
| `punch` | `created_at` | TIMESTAMPTZ | no | `now()` | yes | Server receipt (always set explicitly) |
| `attendance_day` | `attendance_date` | DATE | no | — | **n/a** | Local attendance date |
| `attendance_day` | `timezone` | VARCHAR(64) | no | — | n/a | IANA id the day was computed in |
| `attendance_day` | `scheduled_start` / `_end` | TIMESTAMPTZ | yes | — | yes | Shift span, local→UTC |
| `attendance_day` | `actual_first_in` / `actual_last_out` | TIMESTAMPTZ | yes | — | yes | Derived presence span |
| `attendance_day` | `calculated_at`, `locked_at` | TIMESTAMPTZ | yes | — | yes | Provenance |
| `shift_version` | `start_time`/`end_time`/`window_*`/`core_*` | TIME | yes | — | **no — local wall time** | Civil schedule times |
| `shift_version` | `timezone` | VARCHAR(64) | yes | — | n/a | Meaning of the TIME columns |
| `shift_roster` | `roster_date` | DATE | no | — | n/a | Schedule override date |
| `attendance_regularization_requested_punch` | `requested_time` | TIMESTAMPTZ | no | — | yes | Requested correction instant |
| `overtime_record` | `attendance_date` | DATE | no | — | n/a | OT day (no start/end instants) |
| `attendance_period` | `period_start`/`period_end` | DATE | no | — | n/a | Lock window, inclusive-inclusive |
| `leave_day_projection` | `attendance_date` | DATE | no | — | n/a | Leave overlay date |
| all `TimestampMixin` | `created_at`/`updated_at` | TIMESTAMPTZ | no | `now()` | yes | Row audit |

**Ambiguity risk:** the only path to an ambiguous stored instant is a **naive** client `punch_time`. `TIMESTAMPTZ` cannot store ambiguity, so asyncpg silently resolves it using the **Python process's OS timezone** — see F-07.

---

## 6. UTC Strategy

Storage and calculation are consistently UTC. The failures are all at the outer edges.

| Layer | Timestamp | UTC | Local | Naive | Conversion |
|---|---|---|---|---|---|
| Browser input | `datetime-local` string | — | ✔ browser | ✔ | none |
| Client → wire | `new Date(s).toISOString()` | ✔ | — | — | **browser tz** → UTC |
| Pydantic (offset given) | `datetime` | ✔ | — | — | offset preserved |
| Pydantic (**no offset**) | `datetime` | — | — | **✔** | **none — passed through naive** |
| asyncpg → TIMESTAMPTZ | instant | ✔ | — | — | naive assumed **process-OS-local** *(verified)* |
| Database | TIMESTAMPTZ | ✔ | — | — | stored as UTC |
| ORM read | `datetime` | ✔ | — | — | tz-aware |
| Engine | all arithmetic | ✔ | — | — | local→UTC via `ZoneInfo` |
| API response | `_format_timestamp` | ✔ | — | — | `isoformat()`, `+00:00`→`Z` |
| Web display | `toLocaleTimeString` | — | ✔ **viewer** | — | UTC → **viewer browser tz** |

**Timezone information is lost at exactly two points:**
1. **Ingestion** — a naive client timestamp loses its intended zone and is silently reinterpreted (F-07).
2. **Display** — the API returns the correct UTC instant *and* `attendance_day.timezone`, but the UI discards the latter and renders in the viewer's zone (F-08).

---

## 7. Timezone Resolution

**Implemented precedence (this is real, and matches documented policy):**

```
ShiftVersion.timezone   (organisation/models.py:294)
        ↓ if NULL
Branch.timezone         (organisation/models.py:136, via EmployeeAssignment.branch_id)
        ↓ if NULL
Company.timezone        (core/db/models/identity.py:45, default "Asia/Kolkata", NOT NULL)
```

`calculation.py:294-298`:
```python
def resolve_timezone(*, shift_version_timezone, branch_timezone, company_timezone) -> str:
    """WD-06: `ShiftVersion.timezone` > `Branch.timezone` > `Company.timezone`."""
    return shift_version_timezone or branch_timezone or company_timezone
```

Resolved in `service.py:2746-2786`; the result is persisted on every `attendance_day` row.

**Not implemented as timezone sources:** Employee, Department, Designation, Grade, Legal Entity, Device, Browser, IP, GPS. There is **no employee-level timezone column** anywhere in the schema (`employee/models.py` has none).

The chain terminates safely: `Company.timezone` is NOT NULL with a default, so timezone resolution can never fail — unlike calendar/policy resolution, which fails closed.

**But the chain's inputs are unguarded.** `OrganisationService._assert_timezone_change_allowed` (`organisation/service.py:702-709`) is an explicit empty no-op — *"Documented no-op hook until Payroll/Attendance modules exist"* — and `update_branch` never calls it at all. Attendance now exists, so the condition that hook was waiting on has been met. Changing `Company.timezone` or `Branch.timezone` today silently re-anchors every future attendance day, and every historical day that is subsequently recomputed. See F-27.

---

## 8. Attendance Event Model

Only **two** event kinds exist: `IN` and `OUT` (`punch_direction_check`). There is **no `BREAK_START` / `BREAK_END` event type**. Breaks are *inferred* from gaps between an `OUT` and the next `IN` (`presence_span` → `match_breaks`).

| Event | Timestamp source | Timezone | Stored as | Attendance date |
|---|---|---|---|---|
| `IN` | client `punch_time`, else server UTC | client-encoded offset (or none) | TIMESTAMPTZ (UTC) | assigned at calculation time, not at punch time |
| `OUT` | same | same | same | same |
| `BREAK_START` | **not implemented** | — | — | derived from an `OUT` |
| `BREAK_END` | **not implemented** | — | — | derived from the next `IN` |

Other event context: `source` (client-settable, 7 values), `reference` (free text), `recorded_by_user_id` (server, from JWT), `idempotency_key` (client). **No device id, no GPS, no IP on the punch row.** The `punch.raw_payload` JSONB column exists but **is never written by any code path** (grep confirms: declared in `models.py:464`, zero writes). `Branch.geofence_radius_m` exists but no punch path reads it — geofencing is unenforced.

---

## 9. Attendance Date Calculation

**The attendance date is never derived from a punch.** It is a caller-supplied parameter:

```
POST /v1/attendance/days/calculate?employee_id=…&date=2026-09-15
```

`AttendanceDayService.calculate(company_id, employee_id, target_date)` takes the date as input, then works **backwards** — resolving that date's shift and computing the UTC window that date's punches must fall in:

```python
# calculation.py:334-346  scheduled_span_utc
start    = _local_to_utc(attendance_date, start_time, tz)
end_date = attendance_date + timedelta(days=1) if is_cross_midnight else attendance_date
end      = _local_to_utc(end_date, end_time, tz)
if end <= start: end += timedelta(days=1)
```

Punches are then loaded from that span padded ±2 hours (`punch_window_utc`, `lookback_hours=2`, `lookahead_hours=2`).

**For the brief's worked example** — check-in `2026-09-15 22:00` local, check-out `2026-09-16 06:00` local, on a shift flagged `is_cross_midnight=True`:

> **`work_date = 2026-09-15`** — the shift's **start** date. Confirmed by `scheduled_span_utc` above and by `test_scheduled_span_cross_midnight_attributes_to_start_date` (`test_calculation.py:114`). This matches FR-ATT-005.

Two consequences worth stating plainly:

- **A punch outside every resolved window is silently orphaned.** It is stored, but no `attendance_day` will ever load it. Because `punch_time` is client-supplied and unvalidated, a timestamp of `2099-01-01` *(verified accepted)* creates exactly such an inert row.
- **There is no scheduled calculation job.** `core/celery_app.py` has four beat entries, all `leave.*`. No `attendance.*` task exists anywhere. `attendance_day` rows materialise **only** when someone calls `POST /attendance/days/calculate` or `/recompute`. Attendance is not computed nightly; it is computed when asked. This is an operational gap, not a timezone one, but it governs when any of the above actually runs.

---

## 10. Night Shift Handling

Driven entirely by the explicit `ShiftVersion.is_cross_midnight` boolean — **never inferred** from `end_time < start_time`.

For `22:00 → 06:00`, `is_cross_midnight=True`, `Asia/Kolkata`, attendance date 2026-09-15:

| Quantity | Value | Mechanism |
|---|---|---|
| Shift start date | 2026-09-15 | `_local_to_utc(attendance_date, 22:00, tz)` = `16:30Z` |
| Shift end date | 2026-09-16 | `_local_to_utc(attendance_date+1, 06:00, tz)` = `00:30Z` |
| **Attendance date** | **2026-09-15** | shift start date |
| Punch load window | `14:30Z 09-15` → `02:30Z 09-16` | ±2h padding |
| Late | `first_in − scheduled_start − grace_in` | UTC subtraction, `calculation.py:1146-1148` |
| Early departure | `scheduled_end − last_out − grace_out` | UTC subtraction, `calculation.py:1152-1155` |
| Checkout after midnight | correct | inside the padded window |
| Checkout after shift end | OT if `worked − scheduled ≥ min_ot_minutes` | duration-based |
| Next-day events | belong to the next attendance date's own window | |

Because both operands of every comparison are tz-aware UTC derived from the same conversion, night-shift late/early arithmetic is **correct**, including across DST.

**Two night-shift defects, both confirmed:**
- **Breaks whose window crosses midnight never match** — F-05 below.
- **`is_night` for OT classification is just `shift.is_cross_midnight`** (`calculation.py:1237`), not the configured night window — F-06 below.

---

## 11. Cross-Midnight Handling

| Case | Handled? | Evidence |
|---|---|---|
| Scheduled span `22:00→06:00` | ✔ | `scheduled_span_utc` + `is_cross_midnight` |
| `23:30→01:30` | ✔ | same |
| `20:00→04:00` | ✔ | same |
| `end <= start` without the flag | ✔ defensive `+1 day` | `calculation.py:344-345` — but added in **UTC**, so across a DST boundary the span is off by the offset change |
| SPLIT duty blocks crossing midnight | ✔ per-block `crosses_midnight` | `calculation.py:405-418` |
| Core hours crossing midnight | ✔ `if core_end_utc <= core_start_utc: +1 day` | `calculation.py:1097-1099` |
| **Break windows crossing midnight** | ✘ **BROKEN** | `calculation.py:588-601` — F-05 |

The `end <= start` fallback deserves a note: it is the only place a day is added in UTC rather than by re-converting the local wall time on the following local date. For a shift that both omits `is_cross_midnight` and spans a DST transition, the resulting span is wrong by the offset delta. In practice `is_cross_midnight` is always the real path, so this is latent, not active.

---

## 12. Shift / Roster Interaction

```
Employee → EmployeeAssignment (as-of target_date)
             ├── branch_id → Branch.timezone
             └── shift_id  (fallback only)
         → ShiftRoster (company, employee, roster_date) WHERE status='PUBLISHED'   ← WINS
         → resolve_shift_version_as_of(shift_id, target_date)
         → ShiftVersion.timezone / start_time / end_time / breaks / duty_blocks
         → local TIME values + IANA tz → UTC spans
```

`service.py:2758-2775`: a `PUBLISHED` `ShiftRoster` row outranks `EmployeeAssignment.shift_id`. `DRAFT` rosters are invisible to calculation.

| Situation | Actual behaviour |
|---|---|
| Roster changes | Next `calculate()`/`recompute` re-resolves by date; historical days unchanged until explicitly recomputed |
| Shift version changes | Re-resolved **by date** (`resolve_shift_version_as_of`); version FKs snapshotted on `attendance_day` for reproducibility (WD-11) |
| No roster | Falls back to `EmployeeAssignment.shift_id` |
| No shift at all | `calendar_day_window_utc` — plain local midnight-to-midnight; `missing_shift_behaviour` sets the status |
| Overlapping rosters | Impossible — unique `(company_id, employee_id, roster_date)` |
| Roster tz ≠ employee tz | **Not a distinct case** — roster carries no timezone; `ShiftVersion.timezone` of the rostered shift wins, so rostering a differently-zoned shift silently changes the day's timezone |

That last row is the notable one: rostering an employee onto a shift whose `ShiftVersion.timezone` differs from their branch's silently re-anchors their whole attendance day. This is a faithful consequence of WD-06's precedence, not a bug, but it is a sharp edge nobody has written down.

---

## 13. Leave / Holiday / Weekly-Off Interaction

All three are keyed on `DATE` columns compared against `attendance_day.attendance_date` — which is already the **local** attendance date resolved through §7. There is no UTC-date-vs-local-date mismatch on this path.

- `CalendarResolutionService` resolves `calendar_day_type` (`WORKING` / `WEEKLY_OFF` / `HOLIDAY` / `SPECIAL_WORKING` / `SHUTDOWN`) for `(employee, target_date)`.
- `ShiftRoster.is_week_off_override` / `is_holiday_working_override` alter the *expectation of presence* only — never `calendar_day_type` (WD-04/WD-07).
- `LeaveDayProjection` (`attendance_date DATE`, `status='APPROVED'` only) feeds `_apply_leave_overlay`.

**Assessment: correct.** Because the date is resolved locally *before* any calendar lookup, `UTC date ≠ local date` cannot corrupt holiday/leave matching. Calendar resolution also **fails closed** (`config_incomplete` → `CONFIG_ERROR`), never guessing a default.

---

## 14. Late / Early Calculation

`calculation.py:1141-1155` — the only implemented formulas:

```
late_minutes  = max(0, ⌊(first_in − scheduled_start)/60⌋ − grace_in_minutes)
early_minutes = max(0, ⌊(scheduled_end − last_out)/60⌋  − grace_out_minutes)
```

Both operands are **tz-aware UTC**. `first_in`/`last_out` come from the DB; `scheduled_start`/`scheduled_end` come from `_local_to_utc(attendance_date, shift_time, ZoneInfo(tz))`. Classification is by ordered non-overlapping bands (`lookup_band`).

Overrides that can supersede the band: unapproved early departure forced to the harshest configured band (WD-32 d5); cumulative lateness count → `HALF_DAY` (WD-32 d2); core-hours breach → `HALF_DAY`/`ABSENT` (WD-32 d1).

**Assessment: the arithmetic is correct and DST-safe.** Its input is not — `first_in` is a client-declared instant.

**Not applied:** `punch_rounding` / `rounding_minutes`. See F-04.

---

## 15. Overtime Calculation

OT is **duration-based, not wall-clock-based** (`detect_overtime`, `calculation.py:693-738`):

```
excess = max(0, worked_minutes − (scheduled_minutes or worked_minutes))
if excess < min_ot_minutes: → 0
apply rounding_minutes → daily_cap → remaining_weekly → remaining_monthly
day_class = HOLIDAY > WEEKLY_OFF > NIGHT > NORMAL
```

`OvertimeRecord` stores `minutes_detected` / `minutes_approved` and **has no start/end timestamp columns**. Therefore the brief's "OT start before midnight / OT end after midnight" question is structurally inapplicable: OT has no instants to straddle midnight. Cross-midnight OT is handled implicitly and correctly, because `worked_minutes` derives from UTC spans.

| OT kind | Implemented | Timezone handling |
|---|---|---|
| Normal | ✔ | duration only |
| Holiday | ✔ via `calendar_day_type` | local date |
| Weekly-off | ✔ | local date |
| **Night** | ✔ but see F-06 | **`is_night = shift.is_cross_midnight`, not the configured window** |
| Cross-midnight | ✔ implicit | UTC durations |
| Approval | ✔ `AUTO` / `MANAGER` / `MANAGER_THEN_HR` / `HR` | `reviewed_at` TIMESTAMPTZ |

---

## 16. Regularization

Applied only as synthetic `Punch` rows with `source='REGULARIZATION'` (`service.py:4116`) or, for `WRONG_SHIFT`, a `PUBLISHED ShiftRoster` row — then ordinary `calculate()`. Punches are never mutated (WD-11).

| Check | Implemented? | Evidence |
|---|---|---|
| Period lock | ✔ unconditional | `service.py:3516` `_ensure_date_open` |
| Future `attendance_date` | ✔ (except `EARLY_DEPARTURE_APPROVAL`) | `service.py:3502` — but uses **server-OS-local** `date.today()` |
| Backdating window | ✔ `max_backdated_days` | `service.py:3547` — same `date.today()` basis |
| Monthly request cap | ✔ | `service.py:3556-3562`, UTC month |
| Duplicate active request | ✔ | `get_active_for_date` |
| Day-level lock | ✔ if `blocked_when_locked` | `service.py:3579-3584` |
| Type allowed by policy | ✔ fail-closed | `service.py:3531-3534` |
| **`requested_time` within the attendance date** | ✘ **none** | `RegularizationRequestedPunchInput` has no validator |
| **`requested_time` within shift boundaries** | ✘ **none** | — |
| **`requested_time` not in the future** | ✘ **none** | — |

**Can users submit arbitrary times?** Yes — the *date* is bounded, the *times* are not. An employee may submit `attendance_date=2026-09-14` with `requested_time=2026-01-01T00:00:00Z`. **Can HR?** Yes, identically; on-behalf submission is gated by `allow_manager_request`/`allow_hr_request` but applies the same absent time validation. In practice an out-of-window requested time produces an inert orphan punch (§9), so the impact is corrupted data rather than inflated attendance — but nothing detects or rejects it.

---

## 17. Period Lock

`AttendancePeriod` — `period_start` / `period_end` as inclusive `DATE`s, company grain, `OPEN`/`CLOSED`, GiST no-overlap.

`_ensure_date_open` (`service.py:1915`) is called by **punch ingestion, roster writes, regularization submit, and OT approve/reject** — good coverage. `calculate()` additionally keeps its own `is_locked` row check (defence in depth).

**Which date basis?** For punches: **the UTC calendar date of `punch_time`** (`service.py:2347`, `(body.punch_time or now).date()`). For everything else: the supplied local `attendance_date`.

This is a **knowingly documented approximation** — `service.py:2338-2346` explains that the local attendance date is not knowable before shift resolution, which itself depends on the date. The stated backstop is that `calculate()` refuses a locked day outright, so a boundary-straddling punch is at worst an inert orphan row, never a silent rewrite of a locked fact. That reasoning holds.

Residual risk: for a `+05:30` tenant, `punch_time` between `18:30Z` and `24:00Z` has a UTC date one day *behind* the local date. That UTC range is local **00:00–05:29 IST**, so the exposure is **early-morning** punches, not late-evening ones: a punch at 05:00 IST on 1 Oct is `2026-09-30T23:30Z`, whose UTC date is 30 Sep — lock-checked against September, which may already be closed *(verified by boundary probe; see the test matrix)*. A punch at 23:00 IST is `17:30Z` the same day and does **not** diverge. It fails *closed*, which is the safe direction.

---

## 18. Mobile Behavior

> **No mobile application exists in this repository.** No `pubspec.yaml`, no Flutter/React Native/native source anywhere.

`'MOBILE'` and `'DEVICE'` are accepted values of `punch.source` (both the Pydantic enum and the DB CHECK), and the `idempotency_key` mechanism is documented as existing "chiefly for future device sources, W10" — so the schema anticipates mobile, but no client implements it. Every mobile-specific question below is answered against the web client, which is the only client that exists.

---

## 19. Device Clock Manipulation

Because the browser clock is the authoritative source (§3) and the web form exposes the value as an editable `datetime-local` input, no clock manipulation is even required — the user simply types a different time.

```
Device time:   2026-09-15 08:45 IST   (employee arrives late; or types anything)
Server time:   2026-09-15 09:47 IST   (datetime.now(UTC) at service.py:2337)
Difference:    any value, unbounded, in either direction
Behavior:      punch_time = 2026-09-15 03:15:00Z is stored and used verbatim.
               created_at = 2026-09-15 04:17:xxZ records the true receipt time.
               The two are NEVER compared. No warning, no flag, no rejection.
               late_minutes is computed from the fabricated value.
```

| Manipulation | Effect |
|---|---|
| Phone/PC date changed | Seeds the form with the false date; accepted |
| Phone/PC time changed | Seeds the form with the false time; accepted |
| Timezone changed | Changes the browser's UTC conversion; the *instant* shifts by the offset delta |
| Automatic time OFF | No effect — nothing requires synchronised time |
| Automatic timezone OFF | Same as timezone changed |
| **No manipulation at all** | The user edits the input directly — manipulation is a supported UI feature |

---

## 20. Network Delay

```
Employee taps at:      09:00:00   ← not captured; form was seeded earlier and may be stale
Form value:            09:00      ← THIS BECOMES punch_time (user-editable)
Request sent:          09:00:01   ← not captured
Server receives:       09:00:04   ← datetime.now(UTC) → punch.created_at
Database inserts:      09:00:04.2 ← server_default now(), always overridden
```

> **`punch_time` — the client-supplied form value — becomes the attendance timestamp.** Network delay is structurally irrelevant to attendance correctness, because the server's receipt time is recorded but never used for calculation. The stale-form case is the more realistic risk: the dialog seeds `punchTime` on open (`punch-entry-dialog.tsx:73`) and never refreshes it, so a dialog left open for twenty minutes submits a twenty-minute-old timestamp.

---

## 21. Offline Behavior

> **Offline attendance is not supported.**

No service worker, no IndexedDB/local queue, no sync/replay endpoint, no conflict resolution. `punch-entry-dialog.tsx:96-104` surfaces a network failure directly to the user as a toast; nothing is queued.

(Observation, not a design: the `idempotency_key` field and calculation-time duplicate collapsing are the two primitives an offline sync would need, and both already exist. No offline system is designed here, per the audit brief.)

---

## 22. Face Attendance Integration

> **Face attendance integration is not currently implemented.**

No facial recognition, face verification, liveness, or selfie capture exists anywhere in the codebase. The only adjacent feature is `Branch.geofence_radius_m` (`organisation/models.py:139`), which is **stored and editable in the branch UI but read by no punch code path** — geofencing is unenforced.

---

## 23. API Contracts

### `POST /v1/attendance/punches` — the only punch-creation endpoint

There is **no `/check-in` or `/check-out` endpoint**; direction is a body field.

**Request**
```json
{
  "employee_id": "uuid | null",
  "punch_time": "2026-09-15T09:00:00Z | null",
  "direction": "IN | OUT",
  "source": "WEB|MOBILE|DEVICE|IMPORT|ADMIN|API|REGULARIZATION | null",
  "reference": "string(200) | null",
  "idempotency_key": "string(100) | null"
}
```

**Response `201`**
```json
{
  "data": {
    "id": "uuid", "company_id": "uuid", "employee_id": "uuid",
    "punch_time": "2026-09-15T09:00:00Z",
    "direction": "IN", "source": "WEB",
    "idempotency_key": null, "recorded_by_user_id": "uuid",
    "reference": null,
    "created_at": "2026-09-15T09:00:04.201337Z"
  },
  "meta": { "request_id": "…" }
}
```

| Field | Format | Timezone | Required | Client-generated | Server-generated |
|---|---|---|---|---|---|
| `punch_time` (req) | ISO-8601 | **offset optional** | **no** | **yes — always, by the shipped UI** | only as unused fallback |
| `punch_time` (resp) | ISO-8601 `…Z` | UTC | yes | — | echoed |
| `created_at` (resp) | ISO-8601 `…Z` | UTC | yes | no | **yes** |

### Other time-bearing endpoints

| Endpoint | Time fields | Notes |
|---|---|---|
| `GET /attendance/punches` | `date_from`/`date_to` | **UTC** calendar-day bounds (documented, `repository.py:1006`) |
| `POST /attendance/days/calculate` | `date` query param | Local attendance date |
| `GET /attendance/days` | `attendance_date`, `timezone`, `scheduled_*`, `actual_*` | `…Z` instants + IANA tz string |
| `POST /regularizations` | `attendance_date`, `requested_punches[].requested_time` | Date bounded; **times unvalidated** |
| `POST /attendance-periods` | `period_start`/`period_end` | Plain dates |

---

## 24. Serialization

`schemas.py:88-92`:
```python
def _format_timestamp(value):
    if value is None: return None
    return str(value.isoformat()).replace("+00:00", "Z")
```

Responses return **`2026-09-15T03:35:12Z`** — UTC with an explicit `Z`. Offsets are preserved; the format is unambiguous. `_format_time` separately renders shift `TIME` values as `"HH:MM"` local wall time with no offset, which is correct for a civil-time field.

JS `new Date(iso)` parses `…Z` correctly. There is no Flutter parsing to check (§18).

**One conditional caveat:** `_format_timestamp` only produces a `Z` suffix if the value is tz-aware. A naive `punch_time` (F-07) is normalised to UTC by Postgres on write, so reads are tz-aware and this is safe in practice — but the serializer would silently emit an offset-less, ambiguous string if a naive value ever reached it directly.

---

## 25. UI Display

| Surface | Function | Display timezone | Format |
|---|---|---|---|
| Attendance dashboard | `formatClockTime` | **viewer's browser tz** | `toLocaleTimeString`, 2-digit h:m |
| Day detail | `formatDateTime` | **viewer's browser tz** | medium date + short time |
| Punch list | `formatDateTime` | **viewer's browser tz** | same |
| Overtime / regularizations / rosters | `formatMinutes` | n/a | `Xh Ym` |
| Default date filters | `todayIso()` | **UTC** | `YYYY-MM-DD` |
| Day detail subtitle | `${day.attendance_date} — ${day.timezone}` | — | the only place the tz is shown |

`format.ts:16,21` pass `undefined` as the locale, so **both the locale and the timezone come from the viewer's browser**. 12/24-hour format therefore varies by viewer locale, and no timezone label accompanies any rendered time.

**Does UI display match backend calculation? No.** The backend computes `late_minutes` against `attendance_day.timezone`; the UI renders `actual_first_in` in the viewer's zone. The API returns the correct zone and the day-detail page even *prints* it — but no formatter consumes it. An HR user in Dubai reviewing a Kerala employee sees every time shifted by 1h30m against the `late_minutes` shown beside it. See F-08.

`todayIso()` returns the **UTC** date, not the viewer's or the company's. For an IST user between 00:00 and 05:30 local, every default date filter is off by one day. See F-09.

---

## 26. Reporting

**No attendance report or export endpoint exists.** Grep for `csv` / `export` / `StreamingResponse` / `Content-Disposition` across `modules/attendance/` returns nothing.

What exists instead:
- `AttendancePeriodSummary` — per-period aggregates, keyed on `DATE` ranges.
- `GET /attendance-periods/{id}/summary`.
- `GET /attendance/days` with date filters (local `attendance_date`).
- Dashboard / day-detail screens, rendering as §25.

| Consumer | Date basis | Time display |
|---|---|---|
| Day list / detail | local `attendance_date` | **viewer browser tz** |
| Period summary | local `DATE` range | aggregates only |
| Punch list API | **UTC** `punch_time` date | **viewer browser tz** |
| Payroll export | **does not exist** | — |

**Inconsistency:** `GET /attendance/days` filters on local dates while `GET /attendance/punches` filters on UTC dates. Both are correct for their own entity and the latter is documented, but a caller reconciling the two at a month boundary will see mismatched sets.

---

## 27. Security

### Authorization — strong

`_ensure_employee_visible` (`service.py:1894`) validates the **target** employee against the caller's resolved `DataScope`, not merely that the caller holds the permission. Cross-tenant and out-of-scope ids both return `404` with identical shapes, so the response never reveals which case applies. Row-level security is enforced in Postgres (`ENABLE`/`FORCE ROW LEVEL SECURITY`, `app.company_id`).

Covered by `test_attendance_security.py`: forged `employee_id`, cross-company `employee_id`, forged `company_id` header, `SELF`/`REPORTEES`/`REPORTEE_TREE` scoping, on-behalf without permission, unauthenticated.

> **"Employee A cannot create attendance for Employee B" — VERIFIED SAFE.**

### Timestamp integrity — unsafe

| Attack | Prevented? | Evidence |
|---|---|---|
| Submit arbitrary `punch_time` | ✘ **no** | `service.py:2353` |
| Submit **future** `punch_time` | ✘ **no** — `2099-01-01` accepted *(verified)* | no validator |
| Submit **far-past** `punch_time` | ✘ only if the period is `CLOSED` | `service.py:2347` |
| Submit **naive** `punch_time` | ✘ **no** — accepted, silently coerced *(verified)* | F-07 |
| Forge `source` (e.g. claim `DEVICE`/`REGULARIZATION` from a web self-punch) | ✘ **no** | `service.py:2355`; all 7 values accepted *(verified)* |
| Forge `employee_id` | ✔ | `_ensure_employee_visible` |
| Forge `company_id` | ✔ | tenant context + RLS |
| Forge `shift_id` / `work_date` on a punch | ✔ n/a — punches carry neither | — |
| Manipulate device clock | ✘ **no** | §19 |
| Reorder punches by claiming times | ✘ **no** | pairing sorts by `punch_time` |

### §5 verdict — is client time trusted?

> ## **UNSAFE**

1. **Can the user modify the device clock?** Yes — and they need not: the web form exposes `punch_time` as an editable `datetime-local` field (`punch-entry-dialog.tsx:149`).
2. **Does the backend validate it?** **No.** The only guard is the period-lock check on its UTC date (`service.py:2347`). No bound of any kind against server time.
3. **Does the backend replace it with server time?** **No** — server time is a fallback used only when the field is omitted, which the shipped UI never does (`service.py:2353`).
4. **Is client time used for attendance calculations?** **Yes** — it is the sole basis for `late_minutes`, `early_departure_minutes`, `worked_minutes`, `ot_minutes_detected`, `attendance_status`, `paid_day_fraction`, and `lop_fraction`.
5. **Is client time only metadata?** No — the reverse. **Server time (`created_at`) is the metadata.**
6. **Can an attacker submit an arbitrary timestamp?** Yes — any authenticated user holding `ATTENDANCE.PUNCH` (the baseline self-service permission), for their own record, using only the shipped UI.
7. **Can this cause attendance manipulation?** Yes, directly: eliminate lateness, fabricate overtime, extend worked hours, backdate into any open period. These values flow into `paid_day_fraction` / `lop_fraction`, the documented payroll inputs.

---

## 28. Data Integrity

| Concern | Status |
|---|---|
| Duplicate check-ins | Partially — same-direction punches within `duplicate_punch_window_seconds` collapse **at calculation time**; no insert-time constraint. `idempotency_key` guards exact resubmission only when the client supplies one (the web UI never does). |
| Duplicate check-outs | Same mechanism |
| Overlapping attendance | Prevented — `UNIQUE (company_id, employee_id, attendance_date)` |
| Negative durations | Structurally impossible — pairs are built in `punch_time` order, so `out ≥ in` always |
| Impossible durations | ✘ **not prevented** — a 20-hour day is accepted if the timestamps say so |
| Checkout before check-in | Handled — becomes an orphan `OUT` via `pair_punches` |
| Cross-midnight errors | One confirmed: F-05 |
| Timezone conversion errors | One confirmed: F-07 |
| Null timestamps | Prevented — `punch_time NOT NULL` |
| Naive timestamps | ✘ **accepted at the API** — F-07 |
| Race conditions | Punches are append-only, so no lost-update risk; `AttendanceDay` recompute is full-row replacement inside one transaction |
| Concurrent recompute of the same day | ✘ **no row lock** — two simultaneous `calculate()` calls for one employee-date both read-then-write; the `UNIQUE` constraint prevents duplicate rows but not a last-writer-wins overwrite |
| Idempotency | Partial — `UNIQUE (company_id, idempotency_key) WHERE NOT NULL` |
| Tenant isolation | Strong — RLS forced on every table |

---

## 29. Test Coverage

62 unit tests in `test_calculation.py` plus 12 integration modules. Engine coverage is good; **boundary and timezone-edge coverage is the gap.**

| Scenario | Test exists | Type | Pass | Missing |
|---|---|---|---|---|
| Timezone precedence (shift > branch > company) | ✔ `test_calculation.py:83,94` | unit | ✔ | — |
| Cross-midnight scheduled span | ✔ `:114` | unit | ✔ | — |
| Calendar-day window | ✔ `:127` | unit | ✔ | — |
| Duplicate collapsing | ✔ `:138,146` | unit | ✔ | — |
| Punch pairing / orphans | ✔ `:158-187` | unit | ✔ | — |
| Late beyond grace | ✔ `:508` | unit | ✔ | day shift only |
| Bands | ✔ `:236,247` | unit | ✔ | — |
| OT detection / caps / classes | ✔ `:256-433` | unit | ✔ | — |
| Core hours | ✔ `:799-859` | unit | ✔ | — |
| Cumulative late / excess break | ✔ `:883-912` | unit | ✔ | — |
| Early-departure approval | ✔ `:958-1000` | unit | ✔ | — |
| On-duty | ✔ `:1022-1050` | unit | ✔ | — |
| Holiday / weekly-off / roster overrides | ✔ `:532-644` | unit | ✔ | — |
| Period lock | ✔ `test_attendance_period.py` | integration | ✔ | UTC-vs-local boundary |
| Regularization | ✔ `test_regularization.py` | integration | ✔ | `requested_time` bounds |
| Authorization / tenancy | ✔ `test_attendance_security.py` (13) | integration | ✔ | — |
| **DST transition** | ✘ | — | — | **no test uses a DST zone for evaluation** |
| **Night-shift late/early end-to-end** | ✘ | — | — | **cross-midnight span is tested; late/early on one is not** |
| **Cross-midnight break matching** | ✘ | — | — | **would fail — F-05** |
| **Client-supplied `punch_time` validation** | ✘ | — | — | **no test submits a future/past/naive time** |
| **Naive-datetime ingestion** | ✘ | — | — | **F-07** |
| **`source` forgery** | ✘ | — | — | — |
| **Punch rounding** | ✘ | — | — | **would reveal F-04 (dead code)** |
| **Night OT window** | ✘ | — | — | **would reveal F-06** |
| **Concurrent recompute** | ✘ | — | — | — |

Timezone strings used across the entire unit suite: `Asia/Kolkata`, `UTC`, and — only inside the precedence test's arguments, never for evaluation — `America/New_York` and `Europe/London`. **No test evaluates a day in a DST-observing zone.**

---

## 30. Findings

### P0 — Security / attendance-integrity blockers

**F-01 — Client-supplied `punch_time` is accepted verbatim with no validation.**
`service.py:2353` — `"punch_time": body.punch_time or now`. No upper bound, no lower bound, no skew tolerance against `datetime.now(UTC)` (which is computed 16 lines above and used only for `created_at`). Any user with the baseline `ATTENDANCE.PUNCH` permission controls their own attendance times. Flows into `paid_day_fraction` / `lop_fraction`. *(verified: `2099-01-01T00:00:00Z` and `1900-01-01T00:00:00Z` both accepted by the schema.)*

**F-02 — The only shipped client makes the attendance timestamp a user-editable form field.**
`punch-entry-dialog.tsx:94,149` — `punch_time` is always sent, seeded from the browser clock and exposed as an editable `<input type="datetime-local">`. No privilege distinguishes self-punch from on-behalf correction in this dialog; the same editable field serves both.

**F-03 — No future-timestamp validation on punches, at any layer.**
Absent in the web form, absent in `PunchCreate`, absent in `record_punch`, absent from the DB (no CHECK). Regularization *does* reject future dates (`service.py:3502`); punches do not. The asymmetry appears unintentional.

### P1 — Major correctness issues

**F-04 — `punch_rounding` / `rounding_minutes` are configurable but have no effect.**
`apply_rounding` (`calculation.py:637`) is **never called** — a repository-wide grep finds only its definition and one docstring mention. `AttendancePolicyVersion.punch_rounding` and `rounding_minutes` are exposed through the policy API and UI, validated at publish time, and silently ignored. An HR user configuring 15-minute rounding gets none. No test covers it.

**F-05 — Break windows crossing midnight never match; the gap is silently treated as unpaid.**
`calculation.py:588-601` compares local **time-of-day**: `start_time <= gap_start_local <= end_time`. For a night-shift break of `23:30–00:30`, `23:30 <= 23:45 <= 00:30` is `False`. *(verified: a 20-minute gap at 23:45 IST against a paid `23:30–00:30` break returns `shift_break_id=None, is_paid=False`; the identical check against a `13:00–14:00` break matches correctly.)* Night-shift employees lose paid break minutes from `worked_minutes`, which lowers `paid_day_fraction` and suppresses OT.

**F-06 — `night_window_start` / `night_window_end` are dead configuration.**
`calculation.py:1237` sets `is_night = shift.is_cross_midnight`. The configured window is loaded into `OvertimePolicyInputs` (`service.py:3048-3049`) and never read. `night_ot_mode="WINDOW"` therefore behaves identically to `"BOTH"`, and a day shift that runs into the night window is never classified `NIGHT` for OT rate purposes.

**F-07 — Naive `punch_time` is accepted and silently reinterpreted using the server's OS timezone.**
`PunchCreate.punch_time: datetime | None` accepts `"2026-09-15T09:00:00"` and yields a **naive** datetime *(verified)*. asyncpg then resolves it against the Python **process's** OS timezone — *(verified on this host: naive `09:00` → `03:30Z`, i.e. interpreted as IST, while `09:00Z` → `09:00Z`; the two differ)*. The API container sets no `TZ` and defaults to UTC, so **the same request stores a different instant in dev (IST) than in production (UTC)** — here, a 5h30m discrepancy. No validator requires an offset.

**F-08 — UI renders attendance times in the viewer's timezone, not the attendance day's.**
`format.ts:16,21` pass `undefined` as locale to `toLocaleTimeString`/`toLocaleString`, so both locale and zone come from the viewer's browser. The API returns `attendance_day.timezone` and the day-detail page even displays it as a subtitle (`attendance/[id]/page.tsx:110`), but no formatter uses it. Displayed times and the `late_minutes` shown beside them are computed in different zones for any non-colocated viewer.

**F-27 — Timezone changes are completely unguarded.**
`organisation/service.py:702-709` — `_assert_timezone_change_allowed` is an empty no-op whose docstring defers the guard *"until Payroll/Attendance modules exist (Domain Model §5.5)"*. Attendance exists. Worse, `update_branch` never calls the hook at all, so `Branch.timezone` — the middle link of the WD-06 precedence chain (§7) — can be changed with no check whatsoever. Because `attendance_day` stores the timezone it was computed in but `recompute` re-resolves it by date, editing a company or branch timezone silently re-anchors all future days and any historical day later recomputed, changing `late_minutes` and `worked_minutes` for already-reviewed attendance. No warning, no audit gate, no restriction to open periods.

### P2 — Significant technical debt

**F-09 — `todayIso()` returns the UTC date.**
`format.ts:28` — `new Date().toISOString().slice(0,10)`. Seeds default date filters on the attendance, overtime, rosters, and regularizations pages. For IST users between 00:00 and 05:30 local, every default filter is off by one day.

**F-10 — `date.today()` uses the server OS timezone in four places.**
`attendance/service.py:3502,3547`; `leave/service.py:1979,2597`. Governs regularization future-date rejection and backdating windows. Since the API container is UTC and the dev host is IST, these boundaries move between environments. Should be the company/attendance timezone, not the server's.

**F-11 — `source` is client-settable with no role check.**
`service.py:2355` — `body.source or default_source`. All 7 values including `DEVICE` and `REGULARIZATION` are accepted from an ordinary self-punch *(verified)*. `default_source` is only a fallback. Audit provenance is forgeable: a manual web punch can be recorded as a biometric device reading.

**F-12 — `requested_punches[].requested_time` is entirely unvalidated.**
No check that the instant falls within the `attendance_date`, within shift boundaries, or in the past. An out-of-window value produces an inert orphan punch rather than inflated attendance, but nothing rejects or flags it.

**F-13 — `app_timezone_default` is misleadingly named.**
`settings.py:32` defaults to `Asia/Kolkata` and reads like an application-wide timezone, but is consumed only by Celery beat (`celery_app.py:18`). No attendance code reads it. Invites a false assumption that the app has a configured timezone.

**F-14 — No scheduled attendance calculation job.**
`core/celery_app.py` defines four beat entries, all `leave.*`. `attendance_day` rows exist only where `POST /attendance/days/calculate` or `/recompute` was explicitly called. Operational rather than timezone-related, but it determines when any of the above logic actually runs.

**F-15 — No row lock on concurrent recompute.**
Two simultaneous `calculate()` calls for one employee-date both read-then-write. The `UNIQUE` constraint prevents duplicate rows but not last-writer-wins.

### P3 — Minor

**F-16 — `end <= start` fallback adds a day in UTC.** `calculation.py:344-345,362-363` — for a shift that both omits `is_cross_midnight` and spans a DST transition, the span is off by the offset delta. Latent: `is_cross_midnight` is the real path.

**F-17 — Nonexistent and ambiguous local times resolve silently.** *(verified: America/New_York `2026-03-08 02:30` — which does not exist — yields `07:30Z` = `03:30 EDT`; `2026-11-01 01:30`, which occurs twice, yields `05:30Z`, the first occurrence.)* `ZoneInfo`'s default `fold=0` is deterministic and defensible, but no warning is raised and no policy is recorded.

**F-18 — `punch.raw_payload` is never written.** Declared `models.py:464`; zero writes. No device metadata, IP, or GPS is captured on the punch row despite the column existing.

**F-19 — `Branch.geofence_radius_m` is unenforced.** Stored and editable in the branch UI; no punch path reads it.

**F-20 — Punch list filters on UTC dates while day list filters on local dates.** Documented (`repository.py:1006`) and correct per entity, but reconciling the two at a month boundary yields mismatched sets.

### INFO — Observations

**F-21 — DST is handled correctly.** *(verified: `Europe/London` `22:00→06:00` on 2026-10-24 spans **9 hours**; on 2026-03-28 spans **7 hours** — both the true elapsed times.)* `ZoneInfo` is used throughout; no fixed offsets are hardcoded.

**F-22 — IANA identifiers are used exclusively.** All timezone columns are validated against `zoneinfo.available_timezones()` at the schema layer (`organisation/schemas.py:108-112,256-260,691-695,728-730`). **No abbreviations (`IST`, `GMT`, `EST`, `PST`) appear anywhere in application code.** `"IST"` occurs only as OS output in this audit. The `Asia/Kolkata` literal appears as a *default value* in three places (`settings.py:32`, `identity.py:45`, `organisation/schemas.py:100`), never as hardcoded conversion logic.

**F-23 — Every attendance timestamp column is `TIMESTAMPTZ`.** No `timestamp without time zone` exists in the attendance schema.

**F-24 — The calculation engine is pure and side-effect-free.** All DB access is in `service.py`; `calculation.py` is directly unit-testable. This is why the engine's correctness could be verified empirically during this audit.

**F-25 — Reproducibility is designed in.** Every version FK used is stored on `attendance_day`, plus a `computation_snapshot` JSONB trace. Historical attendance does not drift when policies are edited later.

**F-26 — Authorization is genuinely strong.** See §27.

---

## 31. Risks

| # | Risk | Likelihood | Impact | Findings |
|---|---|---|---|---|
| R-1 | Employee eliminates lateness by editing the punch-time field | **Certain** — a supported UI affordance | High — corrupts `late_minutes`, `paid_day_fraction` | F-01, F-02 |
| R-2 | Fabricated overtime via extended `punch_time` | High | High — direct payroll cost | F-01, F-03 |
| R-3 | Dev/prod divergence from naive timestamps | Medium | **Critical** — 5h30m silent error, invisible until reconciliation | F-07 |
| R-4 | Night-shift staff underpaid on breaks | **Certain** where a break crosses midnight | Medium-High | F-05 |
| R-5 | HR configures rounding; nothing happens | High | Medium — silent policy failure, erodes trust | F-04 |
| R-6 | Multi-timezone viewers misread attendance | High once a second zone exists | Medium | F-08 |
| R-7 | Forged `source` defeats audit provenance | Medium | Medium — undermines investigation | F-11 |
| R-8 | Night OT paid at the wrong rate | Medium | Medium | F-06 |
| R-9 | Off-by-one date filters for early-morning IST users | High | Low-Medium | F-09, F-10 |
| R-10 | Attendance never computed because nothing schedules it | High | High operationally | F-14 |
| R-11 | Company/branch timezone edited; reviewed attendance silently re-anchored on recompute | Medium | High — changes already-approved figures | F-27 |

---

## 32. Recommended Remediation

Recommendations only — **nothing in this list was implemented.** Ordered by dependency: the client decision in §33 (DEC-TZ-01) governs the shape of items 1-2.

**Phase 1 — integrity boundary (blocks payroll)**
1. Decide DEC-TZ-01 first. Then either ignore `body.punch_time` for self-service punches and stamp `datetime.now(UTC)` server-side, or accept it within a bounded skew window (e.g. ±120s) and reject outside it. `created_at` is already recorded, so the comparison data exists today.
2. Reject future `punch_time` beyond the tolerance; reject naive `punch_time` outright (require an offset — an `AwareDatetime` annotation on `PunchCreate.punch_time` is the minimal change).
3. Restrict which `source` values a caller may assert, by permission.
4. Add a boundary test suite: future, far-past, naive, forged-source, skew-exceeded.

**Phase 2 — correctness defects**
5. F-05 — make `match_breaks` window comparison midnight-aware (compare against the UTC span, as `_core_hours_breached` already does, rather than time-of-day).
6. F-04 — either wire `apply_rounding` into the evaluation path or remove the policy fields and their UI.
7. F-06 — either use `night_window_start`/`night_window_end` in `classify_ot_day` or remove them.
8. F-07 — pin `TZ=UTC` in `apps/api/Dockerfile` and CI regardless, so the two environments agree.
9. F-27 — implement `_assert_timezone_change_allowed` (the hook's stated precondition is now met) and call it from `update_branch` as well as `update_company`; at minimum refuse a timezone change while any period is open with computed days, or require an explicit acknowledged recompute.

**Phase 3 — display and operations**
10. F-08 — format attendance times using `attendance_day.timezone`, with a visible timezone label.
11. F-09/F-10 — derive "today" from the company/attendance timezone, not UTC and not the server OS.
12. F-14 — add a scheduled calculation task.
13. F-13 — rename `app_timezone_default` to `celery_timezone`, or make attendance actually consult it.

**Phase 4 — depth**
14. DST-zone evaluation tests; night-shift late/early end-to-end tests.
15. Row lock on recompute (F-15).
16. Record a policy for ambiguous/nonexistent local times (F-17).

---

## 33. Client Decisions Required

Per §38 of the audit brief, implementation is reported separately from policy. **No document in this repository states whether client-supplied attendance timestamps are permitted.** The architecture is explicit about timezone resolution (WD-06, §6.4) and about UTC storage (ADR-0010, §249: *"UTC storage; business-day boundaries in an IANA timezone"*) — but it is **silent on the authoritative clock**. Greps for "server time", "client time", "device clock", "trusted", "clock skew", and "spoof" across `WORKFORCE_ATTENDANCE_ARCHITECTURE.md`, `WORKFORCE_ATTENDANCE_DECISION_LOG.md`, and all of `docs/business-rules/attendance/` return nothing on this question.

```
IMPLEMENTATION:
  The client's clock is the authoritative source of attendance time.
  Server time is recorded (punch.created_at) but never used for calculation
  and never compared against the claimed time.

DOCUMENTED POLICY:
  Policy not defined. The architecture specifies UTC storage and IANA
  business-day boundaries (both correctly implemented) but states nothing
  about which clock is authoritative or whether client time may be trusted.

CONFLICT:
  Cannot be assessed — there is no documented policy to conflict with.
  This is a genuine specification gap, not an implementation deviation.

CLIENT DECISION REQUIRED:
  YES — DEC-TZ-01 is a blocker.
```

Ten decisions are recorded in `ATTENDANCE_TIMEZONE_DECISION_REGISTER.md`. **DEC-TZ-01 (authoritative clock) is the blocker** — it determines the shape of the Phase-1 remediation. DEC-TZ-02 (skew tolerance), DEC-TZ-03 (future timestamps), and DEC-TZ-04 (naive timestamps) follow directly from it.

A separate contrast worth flagging: the codebase's *own* internal decision log is unusually disciplined (WD-06, WD-11, WD-26, WD-28 through WD-32 each record a deliberate trade-off with reasoning). The authoritative-clock question is conspicuous by its absence from that log — it appears never to have been asked, rather than to have been answered and set aside.

---

*Audit performed 2026-09-15. No application code was modified. All findings marked "(verified)" were reproduced by executing the shipped code read-only; all others are direct source citations with file and line references.*
