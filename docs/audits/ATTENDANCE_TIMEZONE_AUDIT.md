# Attendance — Deep Timezone & Time Handling Audit

**Audit date:** 2026-09-15
**Type:** AUDIT ONLY — no application code, schema, migration, or test was modified.
**Scope:** Timezone and time handling across the HRMS, focused on Attendance.

**Evidence standard.** Every claim carries one of these labels:

| Label | Meaning |
|---|---|
| **CODE-PROVEN** | Verified by executing the shipped code read-only during this audit, or by direct source citation of an unambiguous code path |
| **TEST-PROVEN** | An automated test in the repository asserts this and passes |
| **DOCUMENTED** | Stated in repository documentation |
| **DOCUMENTATION-ONLY** | Documentation claims it; no code or test proves it |
| **UNTESTED** | Behaviour observed in code but no automated test covers it |
| **NOT VERIFIED** | Cannot be determined from this repository |

Nothing is called PASS on the strength of documentation or a library's reputation.

**Companion documents.**
[`ATTENDANCE_TIMEZONE_TEST_MATRIX.md`](./ATTENDANCE_TIMEZONE_TEST_MATRIX.md) — concrete boundary scenarios, computed from the shipped code.
[`../business-rules/attendance/ATTENDANCE_TIME_TIMEZONE_IMPLEMENTATION_AUDIT.md`](../business-rules/attendance/ATTENDANCE_TIME_TIMEZONE_IMPLEMENTATION_AUDIT.md) — the ingestion-path/authoritative-clock audit (findings F-01…F-27) and its decision register. This document does not repeat those findings; it cross-references them and adds the timezone-specific findings TZ-01…TZ-14.

> **Superseded as the action surface (2026-09-15).** This audit remains the evidence of record for `TZ-01`…`TZ-14`. The **canonical** artefact for decisions, remediation sequencing and the test plan is now
> [`ATTENDANCE_TIMEZONE_DECISION_AND_REMEDIATION.md`](./ATTENDANCE_TIMEZONE_DECISION_AND_REMEDIATION.md).
> Read this document for *what was found*; read that one for *what to decide and what to build*. No finding was renamed.

---

## TIMEZONE AUDIT VERDICT

> # **READY WITH CONDITIONS**

**for the timezone dimension specifically** — and only for the timezone dimension. The companion ingestion audit rates the system HIGH RISK overall on the authoritative-clock question, which this verdict does not override.

The core finding is strongly positive and was proven, not assumed:

> **Server timezone does not affect attendance results.** Running the full calculation engine under `TZ=UTC`, `TZ=Asia/Kolkata`, `TZ=America/New_York`, and `TZ=Pacific/Kiritimati` (UTC+14) produced **byte-identical** output for day shifts, cross-midnight shifts, every scheduled span, and every DST span. The only value that differed was the naive-datetime coercion path — which no correctly-formed request exercises. **CODE-PROVEN.**

**DST is correct, and is no longer merely "presumed".** Every repository document that mentions DST calls it *"Presumed yes (stdlib)"* / *"untested, not proven"* (`ATTENDANCE_MASTER_RULE_MATRIX.md` C3, `TECHNICAL_DEBT_REGISTER.md` TZ-1). This audit executed the shipped code across four real transitions and confirms the arithmetic is right: a 22:00→06:00 shift spans **540 minutes** on a fall-back night and **420 minutes** on a spring-forward night, in both `Europe/London` and `America/New_York`. That upgrades C3 from DOCUMENTATION-ONLY to **CODE-PROVEN** — but **not** to TEST-PROVEN. No automated test exists. A refactor could silently regress it tomorrow.

The conditions are five, in order of severity:

1. **TZ-01 (P0)** — `Branch.timezone` and `Company.timezone` are **not effective-dated**, and `recompute` re-resolves timezone from the *current* row rather than the stored one. Editing either silently rewrites historical attendance. The guard designed to prevent exactly this is an empty stub, and the branch path never calls it at all.
2. **TZ-02 (P0)** — naive timestamps are resolved against the **Python process OS timezone**, the one place where server location does change results.
3. **TZ-03 (P1)** — `DEC-010`, a LOCKED architecture decision, mandates company-timezone rendering. The UI renders in the viewer's browser timezone. Direct conflict with a locked decision.
4. **TZ-04 (P1)** — DST correctness has **zero** automated test coverage.
5. **TZ-05 (P1)** — the container's system tzdata (**2026b**, frozen at image build) shadows the newer PyPI `tzdata` (**2026.3**) the lockfile installs, and nothing updates or pins either.

---

## 1. System-Wide Time Flow

Stage-by-stage. No stage is left as "probably UTC".

| # | Stage | Timestamp representation | Timezone | Source | Conversion | Label |
|---|---|---|---|---|---|---|
| 1 | Web device | `YYYY-MM-DDTHH:mm` string | **Browser local** | `new Date()`, user-editable (`punch-entry-dialog.tsx:33,149`) | none | CODE-PROVEN |
| 2 | Client → wire | ISO-8601 with `Z` | UTC | `new Date(s).toISOString()` (`:94`) | **browser tz** → UTC | CODE-PROVEN |
| 3 | HTTP request | JSON string | as encoded | — | none | CODE-PROVEN |
| 4 | FastAPI routing | raw body | — | `router.py:752` | none | CODE-PROVEN |
| 5 | Pydantic validation | `datetime \| None` | offset if present, else **naive** | `schemas.py:1234` | parse only; **no offset requirement** | CODE-PROVEN |
| 6 | Service layer | `datetime` | unchanged | `service.py:2353` `body.punch_time or now` | **none** | CODE-PROVEN |
| 7 | Repository | ORM attribute | unchanged | `PunchRepository.insert` | none | CODE-PROVEN |
| 8 | asyncpg → PG | binary timestamptz | UTC | driver | aware → UTC; **naive → process-OS-local** | CODE-PROVEN |
| 9 | PostgreSQL | `TIMESTAMPTZ` | UTC (`SHOW TimeZone` = `UTC`) | — | normalise | CODE-PROVEN |
| 10 | Punch load | `datetime` tz-aware | UTC | `repository.py:990` ordered by `punch_time` | none | CODE-PROVEN |
| 11 | TZ resolution | IANA string | — | `resolve_timezone` (`calculation.py:294`) | shift > branch > company | CODE-PROVEN, TEST-PROVEN |
| 12 | Shift resolution | `TIME` local wall | resolved IANA | `resolve_shift_version_as_of` (effective-dated) | — | CODE-PROVEN |
| 13 | Localization | `datetime` UTC | — | `_local_to_utc` (`calculation.py:306`) | local wall + `ZoneInfo` → UTC | CODE-PROVEN |
| 14 | Late/early | `int` minutes | — | `calculation.py:1146,1152` | UTC − UTC | CODE-PROVEN, TEST-PROVEN |
| 15 | Worked minutes | `int` minutes | — | `presence_span` | UTC − UTC | CODE-PROVEN, TEST-PROVEN |
| 16 | Breaks | `datetime` UTC pairs | resolved IANA | `match_breaks` (`:574`) | UTC → local **time-of-day** | CODE-PROVEN (defect F-05) |
| 17 | OT | `int` minutes | n/a | `detect_overtime` | duration only, no instants | CODE-PROVEN, TEST-PROVEN |
| 18 | Attendance day | `DATE` + `TIMESTAMPTZ` | stores IANA string | `AttendanceDay` | — | CODE-PROVEN |
| 19 | Leave overlay | `DATE` | local attendance date | `LeaveDayProjection` | none needed | CODE-PROVEN |
| 20 | Period lock | `DATE` | **UTC date of `punch_time`** for punches; local date elsewhere | `service.py:2347` | none | CODE-PROVEN |
| 21 | Payroll-facing | `Numeric` fractions | n/a | `paid_day_fraction` / `lop_fraction` | — | CODE-PROVEN |
| 22 | API response | ISO-8601 `…Z` | UTC | `_format_timestamp` (`schemas.py:88`) | `+00:00` → `Z` | CODE-PROVEN |
| 23 | UI display | localized string | **viewer's browser tz** | `format.ts:16,21` | UTC → browser | CODE-PROVEN (conflict TZ-03) |

---

## 2. Database Audit

Every attendance-relevant column. **No `timestamp without time zone` exists anywhere in the attendance schema** — CODE-PROVEN from the migrations.

| Table | Column | PG type | Null | Default | TZ-aware | Stored tz | App type | Meaning | Used by |
|---|---|---|---|---|---|---|---|---|---|
| `punch` | `punch_time` | TIMESTAMPTZ | no | — | yes | UTC | `datetime` | **Claimed** event instant | engine, period lock |
| `punch` | `created_at` | TIMESTAMPTZ | no | `now()` | yes | UTC | `datetime` | Server receipt | audit only |
| `attendance_day` | `attendance_date` | DATE | no | — | n/a | — | `date` | Local attendance date | everything |
| `attendance_day` | `timezone` | VARCHAR(64) | no | — | n/a | IANA id | `str` | Zone used for this day | **response serialization only** |
| `attendance_day` | `scheduled_start`/`_end` | TIMESTAMPTZ | yes | — | yes | UTC | `datetime` | Shift span | late/early |
| `attendance_day` | `actual_first_in`/`actual_last_out` | TIMESTAMPTZ | yes | — | yes | UTC | `datetime` | Presence span | late/early/worked |
| `attendance_day` | `calculated_at`/`locked_at` | TIMESTAMPTZ | yes | — | yes | UTC | `datetime` | Provenance | display |
| `shift_version` | `timezone` | VARCHAR(64) | yes | — | n/a | IANA id | `str \| None` | **Meaning of the TIME cols** | `resolve_timezone` |
| `shift_version` | `start_time`/`end_time` | TIME | yes | — | **no** | **local wall** | `time` | Civil schedule | `_local_to_utc` |
| `shift_version` | `window_start`/`_end`, `core_start`/`_end` | TIME | yes | — | **no** | **local wall** | `time` | Flex/core bounds | engine |
| `shift_version` | `effective_from`/`effective_to` | DATE | yes | — | n/a | — | `date` | **Version validity** | as-of resolution |
| `shift_break` | `start_time`/`end_time`/`window_*` | TIME | yes | — | **no** | **local wall** | `time` | Break windows | `match_breaks` |
| `shift_roster` | `roster_date` | DATE | no | — | n/a | — | `date` | Override date | shift resolution |
| `branch` | `timezone` | VARCHAR(50) | **yes** | NULL | n/a | IANA id | `str \| None` | Work-location zone | `resolve_timezone` |
| `company` | `timezone` | VARCHAR(50) | **no** | `Asia/Kolkata` | n/a | IANA id | `str` | Tenant default zone | `resolve_timezone` |
| `attendance_regularization_requested_punch` | `requested_time` | TIMESTAMPTZ | no | — | yes | UTC | `datetime` | Requested instant | synthetic punch |
| `attendance_regularization_request` | `attendance_date` | DATE | no | — | n/a | — | `date` | Target day | resolution |
| `overtime_record` | `attendance_date` | DATE | no | — | n/a | — | `date` | OT day | reporting |
| `overtime_record` | `reviewed_at` | TIMESTAMPTZ | yes | — | yes | UTC | `datetime` | Approval instant | audit |
| `attendance_period` | `period_start`/`period_end` | DATE | no | — | n/a | — | `date` | Lock window | `_ensure_date_open` |
| `attendance_period` | `opened_at`/`closed_at`/`reopened_at` | TIMESTAMPTZ | no/yes | — | yes | UTC | `datetime` | Lifecycle | audit |
| `leave_day_projection` | `attendance_date` | DATE | no | — | n/a | — | `date` | Leave date | overlay |
| `leave_day_projection` | `synced_at`/`cancelled_at` | TIMESTAMPTZ | no/yes | — | yes | UTC | `datetime` | Provenance | audit |
| `audit_log` | `created_at` | TIMESTAMPTZ | no | `now()` | yes | UTC | `datetime` | Audit instant | audit |
| all `TimestampMixin` | `created_at`/`updated_at` | TIMESTAMPTZ | no | `now()` | yes | UTC | `datetime` | Row audit | — |

**Dangerous mixing: none found in storage.** The `DATE` / `TIMESTAMPTZ` / `TIME` split is deliberate and internally coherent:

- `TIMESTAMPTZ` — instants (punches, spans, audit)
- `DATE` — local business dates (attendance date, holiday, leave, period)
- `TIME` — civil wall-clock schedule, given meaning by a sibling `timezone` column

The one structural weakness is that `shift_break.start_time`/`end_time` are wall-clock `TIME` with **no cross-midnight flag** (unlike `shift_version.is_cross_midnight` and `shift_duty_block.crosses_midnight`), which is the root cause of F-05.

---

## 3. Canonical Storage Rule

> **Are all event timestamps stored in UTC? YES — with one ingestion-side qualification.**

**CODE-PROVEN** from four independent layers:

1. **Migrations** — every timestamp column is declared `TIMESTAMPTZ` (`20260820090000_punch.py:31`, `…_attendance_day.py`, etc.).
2. **ORM** — `DateTime(timezone=True)` on every timestamp mapping; `TimestampMixin` (`core/db/base.py`) uses it for `created_at`/`updated_at`.
3. **Database** — `SHOW TimeZone` returns `UTC` *(verified against the running dev Postgres)*; `TIMESTAMPTZ` stores a normalised instant regardless.
4. **Serialization** — `_format_timestamp` emits `…Z`.

| Timestamp | UTC? | Evidence |
|---|---|---|
| Punch-in / punch-out | ✔ stored UTC | `punch.punch_time TIMESTAMPTZ` |
| `created_at` / `updated_at` | ✔ | `TimestampMixin`, `server_default now()` |
| Approval timestamps (`reviewed_at`) | ✔ | `overtime_record`, regularization actions |
| Regularization `requested_time` | ✔ | TIMESTAMPTZ |
| OT timestamps | n/a | **OT stores no instants** — minutes only |
| Leave timestamps (`synced_at`) | ✔ | TIMESTAMPTZ |
| Audit timestamps | ✔ | `audit_log.created_at` |

**The qualification.** Storage is unconditionally UTC; what is *not* guaranteed is that the stored instant is the one the caller meant. A naive `punch_time` is resolved by asyncpg against the process OS timezone before it becomes UTC — see §5/TZ-02. The instant is correctly stored; it may be the wrong instant.

---

## 4. Server Time vs Database Time

| Location | Mechanism | Timezone | Safe? |
|---|---|---|---|
| `attendance/service.py:2337` | `datetime.now(UTC)` | UTC | ✔ safe |
| `attendance/service.py:3556` | `datetime.now(UTC)` | UTC | ✔ safe |
| `attendance/service.py:3502` | `date.today()` | **server OS local** | ✘ **unsafe** |
| `attendance/service.py:3547` | `date.today()` | **server OS local** | ✘ **unsafe** |
| `leave/service.py:1979` | `date.today()` | **server OS local** | ✘ **unsafe** |
| `leave/service.py:2597` | `date.today()` | **server OS local** | ✘ **unsafe** |
| `core/db/base.py` `TimestampMixin` | `func.now()` → PG | UTC | ✔ safe |
| `…_punch.py` migration | `DEFAULT now()` | UTC | ✔ safe (always overridden) |
| `organisation/service.py:668` | `datetime.now(UTC)` | UTC | ✔ safe |
| `format.ts:28` `todayIso()` | `new Date().toISOString()` | **UTC** | ✘ unsafe (§F-09) |

**`datetime.utcnow()` — zero occurrences.** A repository-wide grep finds none. This is the single most common timezone bug in Python codebases and the team has avoided it entirely. **CODE-PROVEN.**

**Naive datetimes in business logic.** The only naive values that can reach business logic are:
- `date.today()` — four call sites above, all date-only, all server-OS-dependent.
- A client-supplied naive `punch_time` — §5/TZ-02.

Everything else uses `datetime.now(UTC)` or `func.now()`.

---

## 5. Can Server Timezone Change Attendance Results?

> ## **NO — for every correctly-formed request. YES — for one specific malformed input and two date-only boundaries.**

### The proof

The pure engine and its helpers were executed under four server timezones spanning UTC−4 to UTC+14, with identical inputs. **CODE-PROVEN.**

```
TZ=UTC   vs   TZ=Asia/Kolkata   vs   TZ=America/New_York   vs   TZ=Pacific/Kiritimati
```

| Output | UTC | Asia/Kolkata | America/New_York | Pacific/Kiritimati |
|---|---|---|---|---|
| Day-shift status / late / early / worked / paid | `PRESENT` / 2 / 0 / 533 / 1.00 | **identical** | **identical** | **identical** |
| Night-shift status / late / worked / paid | `PRESENT` / 0 / 480 / 1.00 | **identical** | **identical** | **identical** |
| `scheduled_span_utc` × 5 zones | 5 values | **identical** | **identical** | **identical** |
| DST spans × 4 transitions | 4 values | **identical** | **identical** | **identical** |
| `datetime(2026,9,15,9,0).astimezone(UTC)` | `09:00Z` | **`03:30Z`** | **`13:00Z`** | **`2026-09-14T19:00Z`** |

The diff between the `TZ=UTC` and `TZ=Asia/Kolkata` runs is exactly two lines: the `TZ` label itself, and the naive-coercion probe.

### Why it holds

`_local_to_utc` (`calculation.py:306`) is the single conversion point:

```python
def _local_to_utc(local_date: date, local_time: time, tz: ZoneInfo) -> datetime:
    return datetime.combine(local_date, local_time, tzinfo=tz).astimezone(UTC)
```

`tzinfo=tz` is supplied **explicitly** from the resolved IANA identifier. `datetime.combine` with an explicit `tzinfo` never consults the process timezone. Every downstream comparison is UTC-aware minus UTC-aware. The engine is a pure function of (punches, shift, policy, IANA string).

### The three exceptions

**TZ-02 (P0) — naive client timestamp.** The one genuine server-location dependency. `PunchCreate.punch_time` accepts an offset-less string; asyncpg then resolves it against the **Python process OS timezone**. *(Verified: naive `09:00` → `03:30Z` on the IST dev host, `09:00Z` in a UTC container — a 5h30m divergence from the same request.)* The API `Dockerfile` sets no `TZ`; `python:3.12-slim` defaults to UTC *(verified by running the actual base image)*; the dev host is `Asia/Kolkata` *(verified)*.

**TZ-06 (P2) — `date.today()` × 4.** Server-OS-local date. Governs regularization future-date rejection and backdating windows. Structurally TZ-dependent; the four probe runs happened to agree only because the current instant maps to the same calendar date in all four zones.

**TZ-07 (P3) — `todayIso()`.** Client-side, UTC-based; affects default filters only, never a calculation.

### Answer

> Server timezone = UTC and server timezone = Asia/Kolkata produce **identical attendance results** for the same employee/company/shift, provided every submitted timestamp carries an explicit UTC offset. Pinning `TZ=UTC` in the Dockerfile and CI would close the remaining gap at zero behavioural cost.

---

## 6. Timezone Precedence

**Implemented exactly as documented (WD-06).** CODE-PROVEN and TEST-PROVEN.

```python
# calculation.py:294-298
def resolve_timezone(*, shift_version_timezone, branch_timezone, company_timezone) -> str:
    """WD-06: `ShiftVersion.timezone` > `Branch.timezone` > `Company.timezone`."""
    return shift_version_timezone or branch_timezone or company_timezone
```

Called once per calculation in `service.py:2746-2786`; the result flows into `AttendanceCalculationInput.timezone` and is used by **every** consumer.

| Consumer | Uses the same resolved timezone? | Evidence |
|---|---|---|
| Attendance date / schedule window | ✔ | `resolve_schedule_window(tz_name=…)` |
| Late / early | ✔ | via `scheduled_start`/`scheduled_end` |
| Worked minutes | ✔ | UTC instants from the same conversion |
| Breaks | ✔ | `match_breaks(tz_name=inputs.timezone)` |
| Core hours | ✔ | `_core_hours_breached(tz_name=inputs.timezone)` |
| OT | ✔ | duration-derived; no independent zone |
| Night OT | ✔ *but* | `is_night = shift.is_cross_midnight` — no zone needed because the window is never read (F-06) |
| Holiday / weekly-off | ✔ | keyed on the local `attendance_date` |
| Leave | ✔ | keyed on the local `attendance_date` |
| Regularization | ✔ | applies synthetic punches, then re-runs the same engine |
| Period lock (punch path) | ✘ | **UTC date of `punch_time`** — documented deviation, WD-30 |

**Employee-level timezone: does not exist.** No `Employee.timezone` or `EmployeeAssignment.timezone` column anywhere in the schema. This is **NOT "STORED BUT NOT USED"** — it is genuinely absent. The nearest thing is `Branch.timezone`, reached through `EmployeeAssignment.branch_id`, which is effective-dated at the *assignment* level even though the branch's timezone value is not.

### Precedence matrix (§32)

| Priority | Source | Applies when | Overrides | Effective-dated? | Historical safety |
|---|---|---|---|---|---|
| 1 | `ShiftVersion.timezone` | non-NULL on the version resolved for that date | Branch, Company | **YES** — `effective_from`/`effective_to`, insert-new/close-previous | ✔ **Safe.** A new version cannot alter past days |
| 2 | `Branch.timezone` | Shift NULL and branch has one | Company | **NO** — single mutable column | ✘ **Unsafe.** Edit rewrites history on recompute |
| 3 | `Company.timezone` | both above NULL | — | **NO** — single mutable column | ✘ **Unsafe.** Same |
| — | *all three missing* | **cannot occur** | — | — | `Company.timezone` is `NOT NULL DEFAULT 'Asia/Kolkata'`, so resolution never fails and never falls back to the server |

That asymmetry is TZ-01, the audit's most serious timezone finding.

---

## 7. Shift, Branch and Company Timezone — Worked Examples

**CODE-PROVEN.** A `09:00`–`18:00` shift, attendance date 2026-09-15:

| Company | Branch | Shift | Resolved | `scheduled_start` (UTC) | `scheduled_end` (UTC) |
|---|---|---|---|---|---|
| `Asia/Kolkata` | `Asia/Dubai` | NULL | **`Asia/Dubai`** | `2026-09-15T05:00Z` | `2026-09-15T14:00Z` |
| `Asia/Kolkata` | `Asia/Dubai` | `Asia/Kolkata` | **`Asia/Kolkata`** | `2026-09-15T03:30Z` | `2026-09-15T12:30Z` |
| `Asia/Kolkata` | NULL | NULL | **`Asia/Kolkata`** | `2026-09-15T03:30Z` | `2026-09-15T12:30Z` |
| `Asia/Kolkata` | NULL | `Europe/London` | **`Europe/London`** | `2026-09-15T08:00Z` | `2026-09-15T17:00Z` |
| `Asia/Kolkata` | `Pacific/Kiritimati` | NULL | **`Pacific/Kiritimati`** | `2026-09-14T19:00Z` | `2026-09-15T04:00Z` |

Note the last row: at UTC+14 the *entire local working day* falls on the **previous UTC date**. The engine handles this correctly — which is exactly why `attendance_date` must never be derived from a UTC date.

### Branch behaviour

| Situation | Actual behaviour | Label |
|---|---|---|
| `Branch.timezone` is NULL | Falls through to `Company.timezone` | CODE-PROVEN |
| Employee transfers branch | `EmployeeAssignment` is resolved **as-of the date**, so past days keep the old branch's zone and future days use the new one | CODE-PROVEN |
| Branch **timezone value** edited | **All** days recomputed after the edit adopt the new zone, including historical ones | CODE-PROVEN — **TZ-01** |
| Branch changes mid-period | Assignment as-of handles it correctly; the period lock does not need to care | CODE-PROVEN |

The distinction matters: **changing which branch an employee belongs to is safe** (effective-dated assignment). **Changing a branch's timezone is not** (mutable column).

---

## 8. Timezone Change Scenarios and Effective Dating

### Is timezone configuration effective-dated?

| Source | Effective-dated | Mechanism |
|---|---|---|
| `ShiftVersion.timezone` | **YES** | `effective_from`/`effective_to`, GiST no-overlap on published rows, `resolve_shift_version_as_of` |
| `Branch.timezone` | **NO** | single mutable column; `version` is optimistic locking only |
| `Company.timezone` | **NO** | single mutable column |

### Does historical attendance change?

The decisive fact: **`recompute` discards the stored timezone.**

```python
# service.py:2631-2652
async def recompute(self, company_id, attendance_day_id, ...):
    row = await self._day_repo.get(...)
    return await self.calculate(company_id, row.employee_id, row.attendance_date, ...)
```

It passes only `employee_id` and `attendance_date`. `calculate()` then re-runs `_build_calculation_input`, which calls `resolve_timezone()` against the **current** `Branch` and `Company` rows. `attendance_day.timezone` is read in exactly **one** place in the entire codebase — `schemas.py:1391`, to populate the API response. It is **write-only provenance and never an input**. **CODE-PROVEN** (grep over all `.timezone` reads in the attendance module).

| Scenario | Historical rows on disk | On recompute | Future calculation | Display |
|---|---|---|---|---|
| **Company** `Asia/Kolkata` → `Asia/Dubai` | unchanged until recomputed | **CHANGES** — new zone applied to old dates | new zone | viewer's browser tz (unchanged) |
| **Branch** `Asia/Kolkata` → `Asia/Singapore` | unchanged until recomputed | **CHANGES** | new zone | same |
| **Shift** `Asia/Kolkata` → `Europe/London` | unchanged | **SAFE** — a new `ShiftVersion` has its own `effective_from`; `resolve_shift_version_as_of` returns the *old* version for old dates | new zone from `effective_from` | same |

### Worked example (the brief's §10 case)

```
Company timezone: Asia/Kolkata
Employee works:   2026-09-15, shift 09:00-18:00, punches 09:05 and 18:02 IST
                  → attendance_day: timezone='Asia/Kolkata', late=0, worked=537

Company timezone later changed to Europe/London     (no guard fires — TZ-01)

Historical row on disk:  UNCHANGED (still says Asia/Kolkata, late=0)
Anyone calls recompute:  scheduled_start becomes 2026-09-15T08:00Z (London 09:00)
                         actual_first_in is still 2026-09-15T03:35Z
                         late = max(0, 03:35Z − 08:00Z) = 0, but
                         early_departure = 08:00Z+9h − 12:32Z = 264 minutes
                         → the day flips from PRESENT to a large early departure
```

The row does not change *spontaneously* — but every mechanism that triggers a recompute (an approved regularization, an OT re-detection, a backdated policy publish, an admin clicking recompute) will rewrite it. **This is the P0.**

### The guard that should prevent it

```python
# organisation/service.py:702-709
def _assert_timezone_change_allowed(self, company_id, current_timezone, new_timezone) -> None:
    """Documented no-op hook until Payroll/Attendance modules exist (Domain Model §5.5)."""
    _ = (company_id, current_timezone, new_timezone)
```

An empty stub whose stated precondition — *"until Attendance exists"* — **has been met**. Worse, `update_company` at least calls it (`:659`); **`update_branch` never calls it at all**, so the middle link of the precedence chain has no guard even in stub form. **CODE-PROVEN.**

This corroborates `PAY-013` in the existing pre-payroll audit from an independent direction.

---

## 9. Attendance Date Resolution

**The attendance date is an input, not a derivation.** `calculate(company_id, employee_id, target_date)` receives the date and works backwards to the UTC window that date's punches must occupy. **CODE-PROVEN.**

```python
# calculation.py:334-346
start    = _local_to_utc(attendance_date, start_time, tz)
end_date = attendance_date + timedelta(days=1) if is_cross_midnight else attendance_date
end      = _local_to_utc(end_date, end_time, tz)
if end <= start: end += timedelta(days=1)
# then padded ±2h by punch_window_utc
```

So the rule is: **attendance date = the shift's local start date**, and a punch belongs to whichever date's padded window contains it. Not the UTC date, not the local calendar date of the punch.

### Which attendance date owns a punch? (day shift 09:00–18:00 `Asia/Kolkata`)

**CODE-PROVEN** — computed by running `punch_window_utc` over candidate dates:

| Local wall time | UTC instant | Owning attendance date |
|---|---|---|
| 00:00 | `2026-09-14T18:30Z` | **none — orphaned** |
| 00:01 | `2026-09-14T18:31Z` | **none — orphaned** |
| 05:00 | `2026-09-14T23:30Z` | **none — orphaned** |
| 06:59 | `2026-09-15T01:29Z` | **none — orphaned** |
| **07:00** | `2026-09-15T01:30Z` | `2026-09-15` ← window opens |
| 08:59 | `2026-09-15T03:29Z` | `2026-09-15` |
| 09:00 | `2026-09-15T03:30Z` | `2026-09-15` |
| 18:00 | `2026-09-15T12:30Z` | `2026-09-15` |
| **20:00** | `2026-09-15T14:30Z` | `2026-09-15` ← window closes |
| 20:01 | `2026-09-15T14:31Z` | **none — orphaned** |
| 23:59 | `2026-09-15T18:29Z` | **none — orphaned** |

**TZ-08 (P2).** For a day shift, only `07:00`–`20:00` local is loadable. A punch outside that band is stored but no `attendance_day` will ever read it — it is silently inert. The ±2h padding is not configurable.

### Cross-midnight (22:00–06:00 `Asia/Kolkata`, attendance date 2026-09-15)

| Local wall | UTC instant | Owning attendance date |
|---|---|---|
| 15th 19:59 | `2026-09-15T14:29Z` | none |
| **15th 20:00** | `2026-09-15T14:30Z` | `2026-09-15` |
| 15th 22:00 | `2026-09-15T16:30Z` | `2026-09-15` |
| 15th 23:59 | `2026-09-15T18:29Z` | `2026-09-15` |
| **16th 00:00** | `2026-09-15T18:30Z` | `2026-09-15` ← still the 15th |
| 16th 06:00 | `2026-09-16T00:30Z` | `2026-09-15` |
| **16th 08:00** | `2026-09-16T02:30Z` | `2026-09-15` |
| 16th 08:01 | `2026-09-16T02:31Z` | none |

Clean, unambiguous, no overlap. The whole 20:00→08:00 local band maps to the shift's **start** date, matching FR-ATT-005. **CODE-PROVEN**; partially TEST-PROVEN (`test_scheduled_span_cross_midnight_attributes_to_start_date`).

---

## 10. Cross-Midnight Shifts

| Shift | Handled | Attendance date | Evidence |
|---|---|---|---|
| `22:00 → 06:00` | ✔ | start date | CODE-PROVEN + TEST-PROVEN |
| `23:00 → 07:00` | ✔ | start date | CODE-PROVEN |
| `18:00 → 02:00` | ✔ | start date | CODE-PROVEN |

Driven by the explicit `ShiftVersion.is_cross_midnight` boolean — **never inferred** from `end_time < start_time`. There is a defensive `if end <= start: end += timedelta(days=1)` fallback, but it adds the day in **UTC**, so a shift that both omits the flag *and* spans a DST transition would be off by the offset delta (TZ-12, P3, latent).

| Dimension | Cross-midnight correct? | Note |
|---|---|---|
| Attendance date | ✔ | start date |
| Worked minutes | ✔ | UTC instants |
| Late / early | ✔ | UTC − UTC against a correctly-spanning schedule |
| **Breaks** | ✘ **BROKEN** | F-05 — window `23:30–00:30` never matches |
| OT | ✔ | duration-based |
| Leave / holiday / weekly-off | ✔ | keyed on the start date |

---

## 11. DST Audit

**Previously DOCUMENTATION-ONLY across the whole repository. Now CODE-PROVEN, still UNTESTED.**

### Scheduled spans across four real transitions (22:00→06:00)

| Transition | Zone | Real minutes | Wall-clock minutes | Delta |
|---|---|---|---|---|
| Spring-forward, night 7→8 Mar 2026 | `America/New_York` | **420** | 480 | −60 |
| Fall-back, night 31 Oct→1 Nov 2026 | `America/New_York` | **540** | 480 | +60 |
| Spring-forward, night 28→29 Mar 2026 | `Europe/London` | **420** | 480 | −60 |
| Fall-back, night 24→25 Oct 2026 | `Europe/London` | **540** | 480 | +60 |
| Control, no DST | `Asia/Kolkata` | 480 | 480 | 0 |

The arithmetic is exactly right: the spans are **true elapsed time**, not naive wall-clock subtraction.

### Full `evaluate_day` across the London fall-back night

| Employee behaviour | worked | late | early | status |
|---|---|---|---|---|
| Punches exactly 22:00→06:00 **local** (9 real hours) | **540** | 0 | 0 | `PRESENT` |
| Punches 8 **real** hours (out at 05:00 local) | 480 | 0 | **60** | `PRESENT` |

Internally consistent and defensible — the shift is defined in wall-clock terms, so working it costs 9 real hours on that night. But note the consequence: **`scheduled_minutes` varies by ±60 across DST nights, so OT detection (`worked − scheduled`) varies with it.** An employee who works the full wall-clock shift on a fall-back night earns **zero OT** despite nine real hours. That is a *policy* outcome nobody has recorded a decision on — flagged as a decision, not a defect.

### Nonexistent and ambiguous local wall times

Punches are instants and can never be ambiguous. Only **local wall times** — shift start/end, core hours, break windows — can be. **CODE-PROVEN:**

| Case | Zone | Input | Resolves to | Round-trips as |
|---|---|---|---|---|
| Nonexistent (spring gap) | `America/New_York` | `2026-03-08 02:30` | `07:30Z` | **03:30 EDT** — shifted forward 1h |
| Nonexistent (UK gap) | `Europe/London` | `2026-03-29 01:30` | `01:30Z` | **02:30 BST** — shifted forward 1h |
| Ambiguous (occurs twice) | `America/New_York` | `2026-11-01 01:30` | `05:30Z` | **01:30 EDT** — first occurrence |
| Ambiguous (UK repeat) | `Europe/London` | `2026-10-25 01:30` | `00:30Z` | **01:30 BST** — first occurrence |

`ZoneInfo`'s default `fold=0`: deterministic, conventional, and silent. A shift configured to start at 02:30 on a spring-forward date **actually starts at 03:30** with no warning at publish time or calculation time. **TZ-11 (P3).**

### Break matching across the ambiguous hour

A gap at the ambiguous `01:10` local matched its `01:00–01:30` break correctly (`matched=True, paid=True`) — because `match_breaks` converts UTC→local before comparing time-of-day, which is the right order. **CODE-PROVEN.** (Its separate cross-midnight defect, F-05, is unrelated to DST.)

### DST coverage summary

| Dimension | Status |
|---|---|
| Scheduled span arithmetic | **CODE-PROVEN correct**, UNTESTED |
| Worked minutes | **CODE-PROVEN correct**, UNTESTED |
| Late / early | **CODE-PROVEN correct**, UNTESTED |
| Breaks across a transition | **CODE-PROVEN correct**, UNTESTED |
| OT (duration-derived) | **CODE-PROVEN correct**, UNTESTED |
| Night OT | n/a — window never read (F-06) |
| Attendance date | **CODE-PROVEN correct**, UNTESTED |
| Cross-midnight across a transition | **CODE-PROVEN correct**, UNTESTED |
| Nonexistent / ambiguous local times | **CODE-PROVEN behaviour**, no policy recorded, UNTESTED |

> **Every row above is UNTESTED.** Zero automated tests exercise a DST date. Timezone strings across the entire unit suite are `Asia/Kolkata`, `UTC`, and — only as *arguments to the precedence test*, never for evaluation — `America/New_York` and `Europe/London`. **TZ-04 (P1).**

---

## 12. tzdata / Timezone Database

**CODE-PROVEN** by running the actual production base image.

| Question | Answer |
|---|---|
| Library | Python stdlib `zoneinfo` (`calculation.py:47`) |
| IANA support | ✔ full; validated against `zoneinfo.available_timezones()` at the schema layer |
| `pytz` | **not used anywhere** |
| System tzdata in `python:3.12-slim` | **2026b-0+deb13u1** (Debian 13) |
| PyPI `tzdata` in the base image | **NOT INSTALLED** |
| PyPI `tzdata` in the app image | **2026.3** — pulled transitively by `kombu`, `psycopg`, `tzlocal` |
| Declared as a direct dependency | **NO** — absent from `pyproject.toml` |
| `zoneinfo.TZPATH` | `('/usr/share/zoneinfo', '/usr/lib/zoneinfo', '/usr/share/lib/zoneinfo', '/etc/zoneinfo')` |
| Which wins | **`/usr/share/zoneinfo` (system, 2026b)** — `zoneinfo` only falls back to the PyPI package when every TZPATH entry misses |
| Update strategy | **none** — the Dockerfile runs no `apt-get`, the base tag is not digest-pinned, no rebuild cadence is documented |

**TZ-05 (P1).** Three compounding problems:

1. **The newer tzdata is installed but never used.** The lockfile pins `tzdata 2026.3`; the container resolves zones from system **2026b**. A fix shipped in 2026.3 would not take effect.
2. **System tzdata is frozen at image build.** No update path. A long-lived image accumulates stale rules.
3. **tzdata is an undeclared transitive dependency.** If `kombu`, `psycopg`, or `tzlocal` ever drops it, the fallback silently disappears with no lockfile signal.

Real-world impact: timezone rules change several times a year by government decree. India is unaffected (no DST, stable offset since 1945), so this is dormant for the current tenant base — and becomes live the moment a DST-observing or recently-reformed jurisdiction is onboarded.

---

## 13. Clock / NTP / Server Time Infrastructure

| Item | Finding | Label |
|---|---|---|
| Clock source | Container system clock (host kernel) | inferred from absence of config |
| Clock synchronisation | **No NTP, chrony, or timesyncd configuration anywhere** | **NOT VERIFIED** |
| Expected drift | **Not documented** | **NOT VERIFIED** |
| Failure behaviour | **Not documented** | **NOT VERIFIED** |
| Database clock | Postgres container, `SHOW TimeZone` = `UTC` | CODE-PROVEN |
| App vs DB clock agreement | **Never compared anywhere in code** | CODE-PROVEN (by absence) |
| Deployment manifests | **None in the repository** — `docker-compose.yml` covers postgres/redis/minio only; no API service, no Kubernetes, no Terraform | CODE-PROVEN |

Greps for `ntp`, `chrony`, `timesyncd`, `clock skew` across all YAML, Dockerfiles, shell scripts and docs return nothing relevant.

**No infrastructure is invented here.** The honest statement is: there is no deployment configuration in this repository, so clock synchronisation is **NOT VERIFIED** and is presumably inherited from whatever host platform runs the container. Because the app's own `created_at` is currently advisory rather than authoritative (see the companion audit), clock drift has no *current* effect on attendance — but it becomes load-bearing the moment DEC-TZ-01 is decided in favour of server-stamped punches.

---

## 14. Concurrency and Transaction Consistency

| Property | Finding | Label |
|---|---|---|
| Session scope | One request-scoped `AsyncSession`, commit at the end (`core/db/session.py`) | CODE-PROVEN |
| Isolation level | **READ COMMITTED** — Postgres default; nothing sets `isolation_level` or `execution_options` anywhere | CODE-PROVEN (`SHOW default_transaction_isolation` → `read committed`) |
| Timezone resolution and calculation in one transaction? | Yes, same session | CODE-PROVEN |
| Snapshot consistency within that transaction? | **No** — READ COMMITTED gives each *statement* a fresh snapshot | CODE-PROVEN |

**TZ-09 (P2) — torn configuration read.** `_build_calculation_input` issues separate `SELECT`s for employment, assignment, company, branch, roster and shift version. Under READ COMMITTED, a `Company.timezone` or `Branch.timezone` `UPDATE` that commits *between* two of those statements is visible to the later ones but not the earlier ones. A single calculation can therefore mix pre-change and post-change configuration.

The window is narrow (milliseconds) and the trigger is rare (a timezone edit concurrent with a calculation), but the consequence is a silently inconsistent `attendance_day` with no error raised. `REPEATABLE READ` would close it; so would TZ-01's guard, by making the concurrent edit impossible in the first place.

**Not found:** any row-level lock on `attendance_day` during recompute. Two concurrent `calculate()` calls for the same employee-date both read-then-write; the `UNIQUE` constraint prevents duplicate rows but not last-writer-wins (F-15 in the companion audit).

---

## 15. Timezone Truth Table (§31)

| Input | Stored as | Calculation timezone | Display timezone | Source of the calculation timezone |
|---|---|---|---|---|
| Punch | `TIMESTAMPTZ` (UTC instant) | UTC arithmetic, localized via resolved IANA | **viewer's browser** | shift > branch > company |
| Shift start | `TIME` (local wall) + `timezone` col | resolved IANA → UTC | not displayed directly | `ShiftVersion.timezone` |
| Shift end | `TIME` (local wall) + `timezone` col | resolved IANA → UTC | not displayed directly | `ShiftVersion.timezone` |
| Attendance date | `DATE` (local) | resolved IANA (shift start date) | as-is, no conversion | shift > branch > company |
| Holiday | `DATE` | matched to local `attendance_date` | as-is | via `attendance_date` |
| Weekly off | `DATE` / pattern | matched to local `attendance_date` | as-is | via `attendance_date` |
| Leave | `DATE` | matched to local `attendance_date` | as-is | via `attendance_date` |
| OT | `int` minutes | none needed (duration) | n/a | inherited from worked/scheduled |
| Night OT | `bool` `is_cross_midnight` | **none — window never read (F-06)** | n/a | n/a |
| Regularization | `TIMESTAMPTZ` + `DATE` | resolved IANA via re-run engine | **viewer's browser** | shift > branch > company |
| Break | derived UTC gap pair | resolved IANA → local time-of-day | not displayed directly | `inputs.timezone` |
| Period lock (punch) | `DATE` range | **UTC date of `punch_time`** | as-is | **none — deliberate deviation (WD-30)** |
| Period lock (all others) | `DATE` range | local `attendance_date` | as-is | shift > branch > company |
| `created_at` / audit | `TIMESTAMPTZ` | UTC | **viewer's browser** | n/a |

---

## 16. Documentation Consistency (§35)

| Claim | Source | Reality | Label |
|---|---|---|---|
| "All timestamps stored in UTC" | DEC-010 (LOCKED) | ✔ true | **CODE-PROVEN** |
| "`company.timezone` is the single source of truth for **computing business-day boundaries**" | DEC-010 (LOCKED) | Superseded by WD-06 (shift > branch > company) — an *explicit, documented* extension, not a drift | **DOCUMENTED, consistent** |
| "`company.timezone` is the single source of truth for **rendering**" | DEC-010 (LOCKED) | ✘ **false** — UI renders in the viewer's browser timezone | **CONFLICT — TZ-03** |
| "ShiftVersion > Branch > Company" | WD-06 (LOCKED) | ✔ implemented exactly | **CODE-PROVEN + TEST-PROVEN** |
| "never UTC midnight, never server-local time" | DEC-010 | ✔ for calculation; ✘ for `date.today()` × 4 and `todayIso()` | **PARTIAL — TZ-06, TZ-07** |
| "DST: presumed yes (stdlib) … not independently proven" | `ATTENDANCE_MASTER_RULE_MATRIX.md` C3 | ✔ now proven correct by this audit | **upgraded DOCUMENTATION-ONLY → CODE-PROVEN** |
| "No DST-transition test" | `TECHNICAL_DEBT_REGISTER.md` TZ-1 | ✔ still true | **CODE-PROVEN — TZ-04** |
| "No company-timezone renderer despite ADR-0010" | `TECHNICAL_DEBT_REGISTER.md` FE-1 | ✔ still true | **CODE-PROVEN — TZ-03** |
| "`_assert_timezone_change_allowed` is an empty placeholder" | `PAY-013`, pre-payroll audit | ✔ still true, **and** `update_branch` never calls it at all | **CODE-PROVEN — TZ-01, worse than documented** |
| "Punch storage remains UTC" | WD-06 | ✔ true | **CODE-PROVEN** |
| "attendance-day resolution … never UTC midnight" | DEC-010 | ✔ for the engine; the **period lock** on punches does use the UTC date, documented as WD-30 | **DOCUMENTED deviation, consistent** |

**No undocumented contradictions found in the calculation path.** WD-06 openly supersedes part of DEC-010 and says so. The one genuine, unacknowledged conflict is DEC-010's *rendering* clause (TZ-03) — and even that is already logged as debt item FE-1, so it is known, not hidden.

---

## 17. Timezone Findings

Findings are numbered `TZ-nn` and are **distinct from** the companion audit's `F-nn` series. Cross-references are given where they overlap.

---

### TZ-01 — Branch/Company timezone is not effective-dated, and recompute rewrites history · **P0**

**Location:** `organisation/models.py:136` (branch), `core/db/models/identity.py:45` (company), `organisation/service.py:702-709` (stub guard), `attendance/service.py:2631-2652` (recompute).

**Evidence.** `Branch.timezone` and `Company.timezone` are single mutable columns with no `effective_from`. `recompute()` passes only `(employee_id, attendance_date)` to `calculate()`, which re-resolves the timezone from current rows. `attendance_day.timezone` is read in exactly one place — `schemas.py:1391`, for the API response — and is never an input. `_assert_timezone_change_allowed` is an empty stub; `update_branch` never calls it.

**Current behaviour.** Editing a company or branch timezone silently changes the computed result of every historical day that is subsequently recomputed.

**Expected.** Either historical days pin their stored `attendance_day.timezone` on recompute, or timezone configuration becomes effective-dated (as `ShiftVersion` already is), or the change is refused while computed days exist in an open period.

**Impact.** Already-reviewed and approved attendance silently changes. Directly upstream of `paid_day_fraction` / `lop_fraction`.

**Reproduction.** Compute a day; change `Company.timezone` from `Asia/Kolkata` to `Europe/London`; approve any regularization on that day (which triggers recompute); observe `early_departure_minutes` jump from 0 to 264.

**Recommendation.** Implement the guard — its stated precondition is met — and call it from `update_branch` too. Decide DEC-TZ-13 in the companion register first.

**Test required.** Change company tz → recompute a historical day → assert the result is unchanged (or changed deliberately, per the decision).

---

### TZ-02 — Naive timestamps resolve against the process OS timezone · **P0**

**Location:** `attendance/schemas.py:1234`; `apps/api/Dockerfile` (no `TZ`).

**Evidence.** *(verified)* `PunchCreate(punch_time="2026-09-15T09:00:00")` yields a naive datetime. asyncpg resolves naive → timestamptz using the process OS zone: `03:30Z` on the IST dev host, `09:00Z` in a UTC container. The base image `python:3.12-slim` reports local tz `UTC` *(verified by running it)*; the dev host is `Asia/Kolkata` *(verified)*.

**Current behaviour.** The same request stores instants 5h30m apart depending on where the API runs. Self-consistent in each environment, so testing will not reveal it.

**Expected.** Reject offset-less timestamps, or define one explicit interpretation.

**Impact.** Silent, environment-dependent data corruption. The **only** place server location changes attendance results.

**Reproduction.** `POST /attendance/punches {"direction":"IN","punch_time":"2026-09-15T09:00:00"}` against a UTC container and an IST host; compare stored `punch_time`.

**Recommendation.** `AwareDatetime` on the field; independently pin `TZ=UTC` in the Dockerfile and CI.

**Test required.** Assert a naive `punch_time` is rejected with 422.

*(Same defect as companion F-07, restated here because it is the sole server-TZ dependency.)*

---

### TZ-03 — UI rendering violates LOCKED decision DEC-010 · **P1**

**Location:** `apps/web/src/lib/attendance/format.ts:16,21`.

**Evidence.** `toLocaleTimeString(undefined, …)` / `toLocaleString(undefined, …)` — `undefined` locale means both locale *and* timezone come from the viewer's browser. DEC-010 (LOCKED): *"`company.timezone` is the single source of truth for rendering."* The API returns `attendance_day.timezone`; `attendance/[id]/page.tsx:110` even prints it as a subtitle; no formatter consumes it.

**Current behaviour.** An HR user in Dubai reviewing a Kerala employee sees every time shifted 1h30m from the zone its `late_minutes` was computed in. No timezone label is shown.

**Expected.** Render in the resolved attendance timezone with an explicit label.

**Impact.** Misread attendance; disputes; erodes trust in the numbers.

**Recommendation.** Consume `attendance_day.timezone` in the formatters. Already logged as debt FE-1.

**Test required.** Component test asserting a fixed instant renders in the day's zone, not the runner's.

*(= companion F-08; elevated here because it conflicts with a LOCKED decision.)*

---

### TZ-04 — DST correctness has zero automated coverage · **P1**

**Location:** `apps/api/tests/unit/modules/attendance/test_calculation.py`.

**Evidence.** No test uses a DST-observing zone for *evaluation*. `America/New_York` and `Europe/London` appear only as arguments to `test_resolve_timezone_prefers_shift_version` / `…falls_back_to_branch_then_company`. All 60 other tests use `Asia/Kolkata` or `UTC`, neither of which has DST.

**Current behaviour.** DST is **CODE-PROVEN correct by this audit** but nothing guards it. A refactor of `_local_to_utc`, `scheduled_span_utc`, or `match_breaks` could regress it silently.

**Impact.** The correctness demonstrated in §11 is unprotected.

**Recommendation.** Add the eight scenarios in the companion test matrix. Cheap — the engine is pure, so these are fast unit tests with no DB.

**Test required.** Yes — this finding *is* the missing test.

---

### TZ-05 — tzdata is stale-by-construction and the newer copy is shadowed · **P1**

**Location:** `apps/api/Dockerfile`; `pyproject.toml`; `uv.lock:2148`.

**Evidence.** *(verified in the real base image)* system tzdata **2026b**, PyPI tzdata **2026.3** (transitive via kombu/psycopg/tzlocal, not declared), `TZPATH[0] = /usr/share/zoneinfo` wins. The Dockerfile runs no `apt-get`; `python:3.12-slim` is not digest-pinned; no rebuild cadence is documented.

**Current behaviour.** The newer tzdata is installed but never consulted; the older one never updates.

**Impact.** Dormant for India (no DST, stable offset). Live the moment a DST-observing or recently-reformed jurisdiction is onboarded.

**Recommendation.** Declare `tzdata` explicitly; decide deliberately whether system or PyPI data is authoritative; document a rebuild cadence.

**Test required.** A startup assertion that the loaded tzdata version is within N months.

---

### TZ-06 — `date.today()` uses the server OS timezone · **P2**

**Location:** `attendance/service.py:3502,3547`; `leave/service.py:1979,2597`.

**Evidence.** `date.today()` is `datetime.now().date()` — process-OS-local. Governs regularization future-date rejection and backdating windows.

**Current behaviour.** Boundaries move between dev (IST) and production (UTC).

**Expected.** Company/attendance-timezone "today".

**Impact.** Low-moderate — a request valid at 23:00 IST may be rejected as future-dated, or vice versa, depending on deployment.

**Recommendation.** Derive from the resolved timezone. *(= companion F-10.)*

---

### TZ-07 — `todayIso()` returns the UTC date · **P2**

`format.ts:28`. Seeds default filters on four pages. For IST users between 00:00 and 05:30 local, every default filter is off by one day. Display only — never reaches a calculation. *(= companion F-09.)*

---

### TZ-08 — Punch load window is a fixed ±2h and silently orphans outliers · **P2**

**Location:** `calculation.py:314-330` (`lookback_hours=2`, `lookahead_hours=2`, both defaulted and never overridden).

**Evidence.** *(verified)* For a 09:00–18:00 `Asia/Kolkata` shift, only `07:00`–`20:00` local is loadable; `06:59` and `20:01` belong to no attendance date.

**Current behaviour.** An early arrival or very late departure outside the pad is stored but never read. No warning, no orphan report.

**Impact.** Silent under-counting for genuinely early/late workers; also the mechanism by which an out-of-range regularization or fabricated timestamp becomes inert.

**Recommendation.** Make the pad policy-configurable, or surface an orphaned-punch report.

---

### TZ-09 — Timezone configuration can be read torn under READ COMMITTED · **P2**

**Location:** `core/db/session.py`; `attendance/service.py:2711`.

**Evidence.** Isolation is Postgres-default READ COMMITTED *(verified: `SHOW default_transaction_isolation` → `read committed`)*; nothing sets it. `_build_calculation_input` issues many separate SELECTs.

**Current behaviour.** A timezone `UPDATE` committing mid-calculation is visible to later statements but not earlier ones, so one `attendance_day` can mix pre- and post-change config. No error raised.

**Impact.** Narrow window, rare trigger, silent inconsistency.

**Recommendation.** `REPEATABLE READ` for the calculation transaction, or close the door via TZ-01's guard.

---

### TZ-10 — DST changes `scheduled_minutes`, silently changing OT eligibility · **P2 / DECISION**

**Evidence.** *(verified)* On the London fall-back night, `scheduled_minutes` = 540; on spring-forward, 420. `detect_overtime` computes `worked − scheduled`, so an employee working the full wall-clock shift earns **zero OT** despite nine real hours, and is credited a full day for seven real hours in spring.

**Current behaviour.** Internally consistent, arithmetically correct, and **undocumented**.

**Expected.** Unknown — this is a compensation-policy question, not a bug.

**Recommendation.** Record a decision before onboarding any DST tenant. Do not "fix" without one.

---

### TZ-11 — Nonexistent and ambiguous local wall times resolve silently · **P3**

*(verified)* `fold=0`: nonexistent times shift forward 1h (`02:30` → `03:30 EDT`); ambiguous times take the first occurrence. Deterministic and conventional, but a shift configured at 02:30 on a spring-forward date silently starts at 03:30, with no warning at publish or calculation time. **Recommendation:** document the policy; warn at shift-publish time if a shift time falls in a transition window for its zone.

---

### TZ-12 — `end <= start` fallback adds a day in UTC · **P3**

`calculation.py:344-345,362-363`. For a shift that both omits `is_cross_midnight` *and* spans a DST transition, the span is off by the offset delta. Latent — `is_cross_midnight` is the real path. *(= companion F-16.)*

---

### TZ-13 — `app_timezone_default` is consumed only by Celery · **P3**

`settings.py:32` defaults to `Asia/Kolkata` and reads like an application-wide timezone; `celery_app.py:18` is its only consumer. No attendance code reads it. Invites a false assumption. *(= companion F-13.)*

---

### TZ-14 — No clock-synchronisation configuration or documentation · **P3 / NOT VERIFIED**

No NTP/chrony/timesyncd config or documentation anywhere; no deployment manifest for the API service exists in the repository. Harmless today because `created_at` is advisory — becomes load-bearing the moment punches are server-stamped.

---

## 18. Final Verdict

### What is correct

- **UTC storage throughout.** Every attendance timestamp column is `TIMESTAMPTZ`; no `timestamp without time zone` exists in the schema. CODE-PROVEN.
- **Server-timezone independence.** Identical output under four server timezones spanning UTC−4 to UTC+14. CODE-PROVEN.
- **`datetime.utcnow()` appears zero times.** The single most common Python timezone bug is entirely absent.
- **WD-06 precedence** implemented exactly as documented. CODE-PROVEN + TEST-PROVEN.
- **DST arithmetic.** Real elapsed time across all four transitions tested. CODE-PROVEN.
- **IANA identifiers only.** No `IST`/`EST`/`GMT` abbreviations anywhere; validated against `available_timezones()` at the schema layer.
- **Cross-midnight attendance-date attribution.** Clean, unambiguous, no overlap. CODE-PROVEN.
- **Holiday / weekly-off / leave** all key on the local attendance date — no UTC-date contamination.
- **Shift timezone is effective-dated**, so shift-level timezone edits cannot rewrite history.
- **The calculation engine is pure**, which is precisely why this audit could prove the above by execution rather than inspection.

### What is proven

TEST-PROVEN: timezone precedence, cross-midnight span attribution, pairing, duplicate collapsing, late-beyond-grace (day shift), OT caps and day classes, bands.

CODE-PROVEN by this audit: server-TZ independence, DST across four transitions, naive-timestamp coercion, cross-midnight break failure, attendance-date ownership boundaries, UTC-vs-local period-lock divergence, tzdata versions in the real image, READ COMMITTED isolation, Postgres `UTC`.

### What is untested

**Everything in §11.** All DST behaviour is CODE-PROVEN but has zero automated coverage. Also untested: night-shift late/early end-to-end, cross-midnight break matching, naive-timestamp ingestion, timezone-change-then-recompute, concurrent recompute, period-lock UTC boundary.

### What is incorrect

- **TZ-03** — UI rendering violates LOCKED decision DEC-010.
- **F-05** (companion) — cross-midnight break windows never match; night-shift break minutes are silently unpaid.
- **F-06** (companion) — `night_window_start`/`_end` are dead configuration.
- **F-04** (companion) — punch rounding is configurable and inert.

### What is dangerous

- **TZ-01** — a company or branch timezone edit silently rewrites historical attendance on the next recompute, with the guard designed to prevent it left as an empty stub and never called at all on the branch path.
- **TZ-02** — naive timestamps resolve differently in dev and production; self-consistent in each, so testing will not catch it.
- **F-01/F-02** (companion) — the authoritative clock is the client's, and the timestamp is a user-editable form field.

### What must be fixed before production

1. **TZ-01** — implement and wire the timezone-change guard (both `update_company` and `update_branch`).
2. **TZ-02** — reject naive timestamps; pin `TZ=UTC` in the Dockerfile and CI.
3. **F-01/F-02/F-03** (companion) — close the punch-ingestion validation gap, per DEC-TZ-01.
4. **F-05** — fix cross-midnight break matching.

### What should be tested before production

1. The eight DST scenarios in the test matrix (**TZ-04**).
2. Timezone-change-then-recompute (**TZ-01**).
3. Naive / future / far-past `punch_time` rejection (**TZ-02**).
4. Night-shift late/early and break matching end-to-end (**F-05**).
5. Period-lock UTC-vs-local boundary at a month end (**§9**).

### What requires a product/business decision

| Decision | Register entry |
|---|---|
| Is the client clock authoritative? | **DEC-TZ-01 — blocker** |
| May a company/branch timezone change once attendance exists? | **DEC-TZ-13** |
| Should DST change `scheduled_minutes` and therefore OT eligibility? | **DEC-TZ-14** (raised by this audit) |
| Which timezone should the UI display? | DEC-TZ-08 (and DEC-010 already answers it — confirm or amend the locked decision) |
| Nonexistent / ambiguous local-time policy | DEC-TZ-11 |

### What requires only documentation

- **TZ-13** — rename `app_timezone_default` or document its Celery-only scope.
- **TZ-11** — record `fold=0` as the stated policy.
- Upgrade `ATTENDANCE_MASTER_RULE_MATRIX.md` **C3** from *"presumed yes, untested"* to *"CODE-PROVEN by the 2026-09-15 timezone audit; still no automated test (TZ-04)"*.
- Document the ±2h punch load pad (**TZ-08**) as a known constraint.

---

## Final Question

> **If an employee in India, an employee in Dubai, and an employee in London all punch at exactly the same real-world instant, will the HRMS calculate each employee's attendance correctly according to their applicable shift/branch/company timezone, regardless of where the API server is physically located?**

# YES — with two stated conditions.

**CODE-PROVEN.** One real instant, `2026-09-15T04:00:00Z`, three employees each on an 09:00 local shift:

| Employee | Branch timezone | Local wall time | Their 09:00 in UTC | Late |
|---|---|---|---|---|
| India | `Asia/Kolkata` | 2026-09-15 **09:30 IST** | `03:30Z` | **+30 min late** |
| Dubai | `Asia/Dubai` | 2026-09-15 **08:00 +04** | `05:00Z` | **60 min early** |
| London | `Europe/London` | 2026-09-15 **05:00 BST** | `08:00Z` | **240 min early** |

Three different, correct answers from one instant — each judged against its own zone's schedule. The London figure also proves DST is applied: `05:00 BST` is UTC+1, not UTC.

**And the server's location is irrelevant.** The same computation under `TZ=UTC`, `TZ=Asia/Kolkata`, `TZ=America/New_York` and `TZ=Pacific/Kiritimati` produced byte-identical output.

**The two conditions:**

1. **Every submitted timestamp must carry an explicit UTC offset.** An offset-less `punch_time` is resolved against the server's OS timezone, and that is the one path where server location changes the answer (TZ-02).
2. **Nobody may edit a branch or company timezone after attendance exists.** Those values are not effective-dated and `recompute` re-resolves from the current row, so an edit silently rewrites history (TZ-01).

Both conditions are currently enforced by nothing but convention.

A narrower caveat worth stating plainly: this answer is about the **conversion** being right. It says nothing about the **timestamp** being right. If all three employees typed their own punch times into an editable form — which is what the shipped UI offers — the system will convert three self-declared numbers with complete timezone correctness. That is the subject of the companion audit, and it is why the overall posture there is HIGH RISK while the timezone posture here is READY WITH CONDITIONS.

---

*Audit performed 2026-09-15. No application code, schema, migration, or test was modified. Findings labelled "(verified)" or CODE-PROVEN were reproduced by executing the shipped code read-only, by querying the running dev Postgres, or by running the actual `python:3.12-slim` base image. All other claims are direct source citations with file and line references.*
