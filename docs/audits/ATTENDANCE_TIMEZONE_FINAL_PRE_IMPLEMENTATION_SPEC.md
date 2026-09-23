# Attendance — India V1 Final Pre-Implementation Specification

**Created:** 2026-09-15
**Status:** FINAL PRE-IMPLEMENTATION REVIEW — **nothing in this document is implemented.**
**Baseline commit:** `e33fcdb` · branch `main`
**Product scope:** India only · business timezone `Asia/Kolkata`
**Stage:** `AUDITS → DECISIONS → PLAN → ` **`PRE-IMPLEMENTATION REVIEW (this document)`** ` → IMPLEMENTATION`

**Code changed: NO · Schema changed: NO · Migrations changed: NO · Tests changed: NO · CI changed: NO · Configuration changed: NO · Data changed: NO**

---

## What this document is, and what it is not

It is the execution-ready technical specification derived from
[`ATTENDANCE_TIMEZONE_IMPLEMENTATION_PLAN.md`](./ATTENDANCE_TIMEZONE_IMPLEMENTATION_PLAN.md),
**reconciled line-by-line against the working tree and the running dev database.** Every planned
change was re-verified against actual code; where the plan and the code disagree, the code wins and
the disagreement is recorded.

It is **not** a second audit. It does not re-litigate settled findings. Its only new content is:

1. Verification verdicts on every planned change (§3).
2. **Fourteen findings this review adds** (`SR-01`…`SR-14`, §2) — including **one that would cause
   the approved plan to introduce a regression** (`SR-01`) and **one that makes a planned Phase-1
   design impossible as written** (`SR-02`).
3. Resolution of `OD-1` by derivation rather than assumption (§9–§10).
4. The final decision split: what the client must decide vs. what engineering may decide (§22–§23).

### Verification method

Every claim labelled **VERIFIED** below was reproduced on 2026-09-15 by one of:

| Method | Command / target |
|---|---|
| Executing shipped code read-only | `apps/api/.venv/bin/python` against `src/` |
| Querying the running dev PostgreSQL | `psql -h localhost -p 5433 -U hrms -d hrms_dev`, read-only |
| Running the test suite | `.venv/bin/python -m pytest` |
| Reading the working tree | exact file + line, re-read at this commit |

Claims the repository **cannot** answer are labelled **NOT VERIFIABLE HERE** and are escalated, never
guessed.

---

# 1. EXECUTIVE SUMMARY

## 1.1 The plan is substantially correct

Of 38 discrete planned changes reconciled in §3, **31 are confirmed exactly as written**, 5 require
correction, and 2 cannot be implemented as specified. The plan's central judgement — *the calculation
engine is sound and must not be touched except for `match_breaks`* — is **re-confirmed by execution**
and this document endorses it without qualification.

## 1.2 The two things that must change before any code is written

> ### `SR-01` — The approved cross-midnight break fix would introduce a regression.
>
> The plan (§10.4) adopts "Approach B": build the break's UTC span from the attendance date, rolling
> the end forward when it precedes the start. **CODE-PROVEN:** a break configured `01:00–02:00` on a
> `22:00→06:00` shift **matches correctly today** and would **stop matching** under Approach B,
> because its *start* is also on the next local day and rolling only the end does not reach it. Such
> a break is legal and publishable — `_interval_contains`
> ([`organisation/service.py:2055-2067`](../../apps/api/src/hrms/modules/organisation/service.py#L2055))
> is wrap-aware and accepts it. **Approach A (wrap-aware time-of-day comparison) passes all six
> scenarios; Approach B fails one.** See §14.

> ### `SR-02` — The Phase-1 schema split cannot be selected by FastAPI as designed.
>
> The plan (§10.1) proposes `PunchCreateSelf` and `PunchCreateOnBehalf` on one endpoint. The
> discriminator between them is `body.employee_id != user.employee_id`
> ([`attendance/router.py:772`](../../apps/api/src/hrms/modules/attendance/router.py#L772)) — a value
> **inside the body being parsed**. A request model cannot be chosen by a condition that requires the
> model to already be parsed. The plan is also internally inconsistent here: §5.1 says "Two punch
> endpoints", §7.1 presents one endpoint with two behaviours. **This must be resolved to two
> endpoints before Phase 1 begins.** See §11.

## 1.3 `OD-1` is resolved by derivation, not by choosing

`OD-1` (which date basis governs the punch period-lock check) is presented in the plan as an open
client decision. **It is not a business question.** §9 derives the answer from the shipped window
functions:

- For **every day shift**, the IST civil date and the UTC date of a loadable punch are **identical**
  — the ±2h pad opens at 07:00 IST, and UTC/IST dates only diverge below 05:30 IST. **There is no
  decision to make for the overwhelming majority of the tenant base.**
- Divergence exists **only** for shifts whose padded window opens before 05:30 IST — in practice,
  night shifts. In exactly that band, the **UTC date is closer to the true attendance date than the
  IST date is**, because a `22:00→06:00` shift starting on day *D* owns punches that are on *D+1* in
  IST but still on *D* in UTC.
- Therefore the brief's §12 instruction *"use the India business date"*, applied literally, would make
  night shifts **worse**, and the plan's recommended Option B is **more permissive** than today, not
  "strictly safer" as §23.2 states.

**What remains is a genuine business question, but a much smaller one** — stated precisely in §22 as
`CD-1`.

## 1.4 Production verdict

> # **NO-GO** — unchanged.

Open P0s, re-verified: `NEW-01`, `TZ-01`/`PAY-013`, `TZ-02`/`F-07`, `F-01`/`F-02`/`F-03`, `F-11`,
`F-05`, `F-14`/`PAY-001`, `TST-001`. `SR-01` and `SR-02` are added as **plan-blocking**, not
production-blocking: they must be resolved before code is written, not before release.

## 1.5 Corrected baselines

The plan's measured baselines have drifted with the working tree. **VERIFIED at `e33fcdb`:**

| Metric | Plan says | **Actual** | Note |
|---|---|---|---|
| Total tests collected | 1145 | **1164** | Working tree has uncommitted `account_invite` work |
| `tests/unit` | 362 passed | **362 passed in 1.13 s** | ✅ matches |
| `tests/integration` + `tests/security` | 783 | **802** | |
| `todayIso()` invocations | 14 across 7 files | **16 across 8 files** | §5 |
| Formatter call sites | 24 across 9 files | **25 across 7 files** | §15 |
| Tests posting `punch_time` | not counted | **11, across 3 files** | §12.1 of the plan asked for this |
| Tests **setting** `source` in a request | implied non-zero | **ZERO** | `F-11` breaks no existing test |

---

# 2. FINDINGS THIS REVIEW ADDS

IDs are prefixed `SR-` (Spec Review) so they never collide with the plan's `NEW-01…06` or the audits'
`TZ-nn` / `F-nn`.

| ID | Finding | Severity | Affects |
|---|---|---|---|
| **SR-01** | **The approved break fix (Approach B) regresses a case that works today.** A `01:00–02:00` break on a `22:00→06:00` shift matches now and would stop matching. Approach A passes all six scenarios. **CODE-PROVEN.** | 🔴 **Plan-blocking** | Phase 4 |
| **SR-02** | **`PunchCreateSelf`/`PunchCreateOnBehalf` cannot be selected on one endpoint** — the discriminator is inside the body. Plan §5.1 and §7.1 contradict each other. | 🔴 **Plan-blocking** | Phase 1 |
| **SR-03** | **`AwareDatetime` does not enforce "ISO-8601 with explicit offset".** It rejects naive and date-only inputs but **accepts epoch integers and numeric strings** (`punch_time: 0` → `1970-01-01T00:00:00Z`). The plan's §10.2 wire-format contract is not achieved by the planned validator. **CODE-PROVEN.** | 🟠 P1 | Phase 1 |
| **SR-04** | **The on-behalf backdating bound has no configuration source.** Plan §7.2 mandates a "policy-driven" window; `AttendancePolicyVersion` has no such field (`max_backdated_days` belongs to `RegularizationPolicyVersion`, [`models.py:339`](../../apps/api/src/hrms/modules/attendance/models.py#L339)); plan §14 states no migration is required. **Three-way contradiction.** | 🟠 P1 | Phase 1 |
| **SR-05** | **All three Beat-scheduled leave jobs compute the wrong India date.** Beat fires on IST wall-clock (`timezone=Asia/Kolkata`) at 01:00 / 01:30 / 02:00 IST, but the tasks derive `as_of=datetime.now(UTC).date()` ([`leave/tasks.py:36,85,110`](../../apps/api/src/hrms/modules/leave/tasks.py#L36)) — which in that band is **always the previous India day**. The monthly accrual scheduled for the 1st runs with `as_of` = the **last day of the previous month**. **CODE-PROVEN.** | 🟠 P1 | Phase 3 |
| **SR-06** | **A second `todayIso()` path reaches persisted business data.** `create-period-dialog.tsx:33,34,40,41` seeds `period_start`/`period_end` — the boundaries that govern period lock and payroll cutoff — from the **UTC** date. The plan's `NEW-02` names only `employee-attendance-panel.tsx:78`. | 🟠 P1 | Phase 3 |
| **SR-07** | **`NEW-02`'s fix is under-specified.** `date` is a **required** query parameter on `POST /attendance/days/calculate` ([`router.py:865`](../../apps/api/src/hrms/modules/attendance/router.py#L865)). "Stop sending a UTC date" does not say what to send instead. | 🔵 P2 | Phase 3 |
| **SR-08** | **`_assert_timezone_change_allowed` is a synchronous method** ([`organisation/service.py:702`](../../apps/api/src/hrms/modules/organisation/service.py#L702)). Implementing it requires a DB query, so it and its single call site at `:659` must become `async`. | 🟢 P3 | Phase 2 |
| **SR-09** | **`NEW-01` is reachable from the ordinary HR UI, not just the API.** `shift-version-form.tsx:66-72` and `branch-form.tsx:93-99` render timezone as a **free-text `<Input>`** with no client-side validation — unlike `/register`, which uses a select. Branch is caught by the backend validator; **ShiftVersion is not.** An HR user typing `IST` produces a 500. | 🟠 **raises NEW-01's likelihood** | Phase 2 |
| **SR-10** | **CI connects as the schema-owner role, not the application role.** `ci.yml` sets `DATABASE_URL=postgresql://hrms:...`; the app uses `hrms_app`, the only `NOBYPASSRLS` role ([`infra/docker/postgres/init/002_app_role.sql:19-20`](../../infra/docker/postgres/init/002_app_role.sql#L19)). Provisioning PostgreSQL without fixing this makes every RLS test pass for the wrong reason. | 🟠 P1 | Phase 7 |
| **SR-11** | **A backdated shift-version publish is legal and unguarded.** Publish requires only `draft.effective_from > current.effective_from` ([`organisation/service.py:2794`](../../apps/api/src/hrms/modules/organisation/service.py#L2794)) — **not** `> today` — and **no configuration publish path consults `AttendancePeriod` at all**. The model's own docstring ([`attendance/models.py:483-484`](../../apps/api/src/hrms/modules/attendance/models.py#L483)) names this as the one act that can change an unlocked historical day. | 🔵 P2 | §13 |
| **SR-12** | **Baselines and call-site counts corrected** (§1.5). | 🟢 P3 | Phase 0 |
| **SR-13** | **`OD-1`'s divergence band is narrower than stated, and inverted.** IST and UTC date bases are identical for every day shift; they diverge only below 05:30 IST, where **UTC is the more correct basis**. | 🟠 **changes OD-1's answer** | §9, Phase 3 |
| **SR-14** | **A fourth punch-window shape exists and is uncovered.** When no shift resolves, `calendar_day_window_utc` ([`calculation.py:352-358`](../../apps/api/src/hrms/modules/attendance/calculation.py#L352)) uses the **full local civil day with no ±2h pad**. Neither the audits, the test matrix (groups A/B), nor the plan covers it. | 🔵 P2 | §18, tests |

---

# 3. RECONCILIATION — EVERY PLANNED CHANGE vs. ACTUAL CODE

Confidence key: **CONFIRMED** = the plan matches the code exactly · **CORRECTED** = the plan is
broadly right but a detail is wrong · **BLOCKED** = cannot be implemented as written.

## 3.1 Phase 1 — Timestamp authority

| Change ID | Planned Change | Actual Code Location | Current Behaviour | Required Behaviour | Confidence | Blocking Question |
|---|---|---|---|---|---|---|
| **P1-01** | Split `PunchCreate` into `PunchCreateSelf` / `PunchCreateOnBehalf` | [`attendance/schemas.py:1222-1240`](../../apps/api/src/hrms/modules/attendance/schemas.py#L1222) `PunchCreate`; [`router.py:752-788`](../../apps/api/src/hrms/modules/attendance/router.py#L752) `create_punch` | One schema, `extra="forbid"`, `employee_id`/`punch_time`/`source` all optional. Self vs. on-behalf decided at `router.py:772` from `body.employee_id != user.employee_id` | Two request shapes | **BLOCKED — `SR-02`** | **Two endpoints, or one endpoint with a single union schema? §11 recommends two endpoints.** |
| **P1-02** | `AwareDatetime` on `punch_time` | `schemas.py:1234` `punch_time: datetime \| None = None` | **VERIFIED accepted:** naive `"2026-09-15T09:00:00"` (tzinfo `None`), date-only `"2026-09-15"`, epoch int `0` | Reject naive **and** non-ISO forms | **CORRECTED — `SR-03`** | **Is the contract "tz-aware" or "ISO-8601 string with offset"? They differ: `AwareDatetime` alone still accepts epoch ints.** |
| **P1-03** | Drop client `source`; server-assign | `schemas.py:1236` + `validate_source`; [`service.py:2355`](../../apps/api/src/hrms/modules/attendance/service.py#L2355) `"source": body.source or default_source` | **VERIFIED:** `source="DEVICE"` and `source="REGULARIZATION"` accepted on a self-punch | `"source": default_source` unconditionally | **CONFIRMED** | None. **Breaks zero existing tests** — no test sets `source` in a request body (`SR-12`). |
| **P1-04** | Server-stamp self-punch | `service.py:2353` `"punch_time": body.punch_time or now` | Client value wins; server `now` at `:2337` used only for `created_at` at `:2359` | Self: `punch_time = request_time`. On-behalf: validated body value | **CONFIRMED** | Depends on P1-01's resolution. |
| **P1-05** | Future / far-past bounds | none at any layer | **VERIFIED:** `2099-01-01T00:00:00Z` and `1900-01-01T00:00:00Z` both accepted | 422 outside bounds | **CONFIRMED** | Far-past floor needs the employment start date — already loaded by `_build_calculation_input`, **not** by `record_punch`. An extra query. |
| **P1-06** | Backdating window on on-behalf | — | No such configuration exists | Bounded | **CORRECTED — `SR-04`** | **Where does the bound come from? No `AttendancePolicyVersion` field exists and plan §14 forbids a migration.** |
| **P1-07** | Write `punch.raw_payload` | [`attendance/models.py:464`](../../apps/api/src/hrms/modules/attendance/models.py#L464); `service.py:2349-2360` `data` dict | Column declared, **never written**. IP + User-Agent already captured at `router.py:784-785` and passed to the audit record only | Populate on every punch | **CONFIRMED** | PII retention sign-off (`PII-2`). |
| **P1-08** | `ENV TZ=UTC` in Dockerfile | [`apps/api/Dockerfile`](../../apps/api/Dockerfile) | **VERIFIED:** no `ENV TZ`. Dev host is `Asia/Kolkata`; `python:3.12-slim` reports `UTC` | `ENV TZ=UTC` | **CONFIRMED** | None. Do this unconditionally. |
| **P1-09** | Split the punch dialog | [`punch-entry-dialog.tsx:33-37, 64, 94, 147-153`](../../apps/web/src/components/attendance/punch-entry-dialog.tsx#L33) | One component, editable `<input type="datetime-local">`, seeded once at open and **never refreshed**; **always sends `employee_id` and `punch_time`** | Self mode: no time field | **CONFIRMED** | Follows P1-01. |
| **P1-10** | Bound regularization `requested_time` | `schemas.py:1475` `requested_time: datetime`; applied verbatim at [`service.py:4108-4122`](../../apps/api/src/hrms/modules/attendance/service.py#L4108) | Unvalidated; naive accepted; becomes `punch.punch_time` verbatim with hard-coded `source="REGULARIZATION"` | `AwareDatetime` + window bound | **CONFIRMED** | Bounds must differ from punch bounds — this path is **legitimately historical**. |

## 3.2 Phase 2 — India timezone invariant

| Change ID | Planned Change | Actual Code Location | Current Behaviour | Required Behaviour | Confidence | Blocking Question |
|---|---|---|---|---|---|---|
| **P2-01** | IANA validator on `ShiftVersionCreate`/`Update` | [`organisation/schemas.py:1243`](../../apps/api/src/hrms/modules/organisation/schemas.py#L1243) and `:1280` — `timezone: str \| None = Field(default=None, max_length=64)` | **VERIFIED: no validator.** Compare `:111`, `:259`, `:694`, `:729`, which all check `available_timezones()` | 422 on non-IANA | **CONFIRMED + amplified by `SR-09`** | None. **Cheapest P0 in the programme.** |
| **P2-02** | Publish-time timezone check | [`organisation/service.py:2282-2345`](../../apps/api/src/hrms/modules/organisation/service.py#L2282) `_validate_and_derive_for_publish` | Validates `shift_type`, `effective_from`, times, flex windows, breaks, duty blocks — **never the timezone** | Validate | **CONFIRMED** | None. |
| **P2-03** | Implement `_assert_timezone_change_allowed` | `organisation/service.py:702-709` | Body is `_ = (company_id, current_timezone, new_timezone)`. **Synchronous method.** Called only at `:659` | Refuse when computed attendance exists | **CORRECTED — `SR-08`** | Must become `async`; `:659` becomes `await`. |
| **P2-04** | Call the guard from `update_branch` | `organisation/service.py:1106-1186` | **VERIFIED by grep:** only one call site exists in the file, `:659`. `update_branch` has none | Guarded | **CONFIRMED** | None. |
| **P2-05** | `TRIAL` / zero-days escape hatch | `organisation/service.py:654-656` — `if company.status != "TRIAL": raise CurrencyLockedError()` | Precedent exists and is in use for currency | Reuse the shape | **CONFIRMED** | None. **All 3 `Asia/Calcutta` companies are `TRIAL` with 0 attendance days — the hatch covers 100 % of real cases.** |
| **P2-06** | India allow-list on `/register` | [`organisation/schemas.py:100,108-113`](../../apps/api/src/hrms/modules/organisation/schemas.py#L100) `CompanyRegistrationRequest.timezone`; [`register/page.tsx:35,163-170`](../../apps/web/src/app/register/page.tsx#L163) | IANA validator only, no country gate. UI offers the whole `Intl.supportedValuesOf("timeZone")` list | Settings-driven allow-list | **CONFIRMED** | See `CD-2` (§22) — this is a product decision, not purely technical. |
| **P2-07** | Alias canonicalisation, never `== "Asia/Kolkata"` | [`timezones.ts:19-25`](../../apps/web/src/lib/timezones.ts#L19) `resolveDefaultTimezone` | **VERIFIED:** `Asia/Calcutta` **is** in `available_timezones()`, so the existing validator accepts it; `ZoneInfo("Asia/Calcutta").key` stays `"Asia/Calcutta"` — no auto-canonicalisation | Normalise on write | **CONFIRMED** | None. |
| **P2-08** | `DH-2` normalisation | dev DB | **VERIFIED:** 3 companies, all `TRIAL`, all `days=0`, all `punches=0` | Normalise | **CONFIRMED** | §21. |

## 3.3 Phase 3 — Attendance date and period lock

| Change ID | Planned Change | Actual Code Location | Current Behaviour | Required Behaviour | Confidence | Blocking Question |
|---|---|---|---|---|---|---|
| **P3-01** | `shared/business_time.py` | does not exist | — | `business_today(tz)`, `business_month_start(tz)` | **CONFIRMED** | None. |
| **P3-02** | Replace `date.today()` — 4 sites | **VERIFIED by grep, exactly 4:** [`attendance/service.py:3502`](../../apps/api/src/hrms/modules/attendance/service.py#L3502), `:3547`, [`leave/service.py:1979`](../../apps/api/src/hrms/modules/leave/service.py#L1979), `:2597` | Server-OS-local date | India business date | **CONFIRMED** | None. |
| **P3-03** | Replace UTC month start — 2 sites | **VERIFIED, exactly 2:** `attendance/service.py:3558`, `leave/service.py:1990` | `datetime(now.year, now.month, 1, tzinfo=UTC)` | IST month start | **CONFIRMED** (plan's `DOC-D3` was right to add the attendance site) | None. |
| **P3-04** | *(not in the plan)* Fix `as_of` in Beat tasks | `leave/tasks.py:36`, `:85`, `:110` | `datetime.now(UTC).date()` while Beat fires 00:00–02:00 IST → **always the previous India day** | `business_today(company_tz)` | **NEW — `SR-05`** | None — same helper, same phase. **Must be added to Phase 3.** |
| **P3-05** | Company timezone on the wire | not present in the session/bootstrap payload | Client has no company timezone | Add it | **CONFIRMED** | Also required by Phase 5. Ship together. |
| **P3-06** | `todayIso()` → `businessToday(tz)` | **VERIFIED: 16 invocations across 8 files** (§5) | UTC date | IST date | **CORRECTED — `SR-12`** | None. |
| **P3-07** | Remove the duplicate `todayIso()` | [`policy-resolution/page.tsx:27`](../../apps/web/src/app/app/policy-resolution/page.tsx#L27) | Private copy, identical body | Delete, import the shared one | **CONFIRMED (`NEW-05`)** | None. |
| **P3-08** | Stop posting a UTC date to `/days/calculate` | [`employee-attendance-panel.tsx:78`](../../apps/web/src/components/attendance/employee-attendance-panel.tsx#L78) | Posts `date=${todayIso()}` — a UTC date — to a calculation endpoint | Post the IST business date | **CORRECTED — `SR-07`** | **The `date` query param is REQUIRED (`router.py:865`). What replaces it? §5 recommends making it optional server-side.** |
| **P3-09** | *(not in the plan)* Period dialog UTC default | `create-period-dialog.tsx:33,34,40,41` | Seeds persisted `period_start`/`period_end` from the UTC date | IST date | **NEW — `SR-06`** | None. |
| **P3-10** | Period-lock date basis | `attendance/service.py:2347` | UTC civil date of `punch_time` (WD-30) | See §9 | **CORRECTED — `SR-13`** | **`CD-1` (§22) — but a much narrower question than the plan states.** |

## 3.4 Phases 4–7

| Change ID | Planned Change | Actual Code Location | Current Behaviour | Required Behaviour | Confidence | Blocking Question |
|---|---|---|---|---|---|---|
| **P4-01** | `match_breaks` → compare UTC instants (Approach B) | [`calculation.py:574-617`](../../apps/api/src/hrms/modules/attendance/calculation.py#L574) | Chained time-of-day inequality; fails for `end_time < start_time` | Match midnight-spanning breaks | **BLOCKED — `SR-01`** | **Approach B regresses after-midnight breaks. §14 specifies Approach A instead.** |
| **P4-02** | *(not in the plan)* `match_breaks` signature | called at `calculation.py:1119` and `:1322`; **neither passes `attendance_date`** | `(gaps, shift_breaks, *, tz_name)` | Approach A needs **no** signature change; Approach B needs one at **both** call sites | **NEW** | Resolved by choosing Approach A. |
| **P5-01** | `formatClockTime(iso, tz)` / `formatDateTime(iso, tz)` | [`format.ts:14-25`](../../apps/web/src/lib/attendance/format.ts#L14) | `toLocaleTimeString(undefined, …)` → viewer's browser zone | IST, always labelled | **CONFIRMED** | `CD-3` (§22) — amends LOCKED `DEC-010`. |
| **P5-02** | Update all call sites | **VERIFIED: 25 across 7 files** (§15) | — | — | **CORRECTED — `SR-12`** | None. |
| **P6-01** | `modules/attendance/tasks.py` | **VERIFIED: no such file**; `celery_app.py` beat_schedule has 4 entries, all `leave.*` | No attendance ever computed automatically | Beat + per-company fan-out | **CONFIRMED** | `CD-4` (§22) — the trailing window N. |
| **P6-02** | Beat at 09:30 IST | `celery_app.py:18-19` `timezone=Asia/Kolkata`, `enable_utc=True` | Beat already fires on IST wall-clock | 09:30 IST | **CONFIRMED — and correct for a reason the plan does not state:** 09:30 IST is above the 05:30 boundary, so `SR-05`'s UTC-date skew cannot affect it |  |
| **P6-03** | `SELECT … FOR UPDATE` on `attendance_day` | **VERIFIED by grep: `with_for_update` appears nowhere in `src/`** | Last-writer-wins | Row lock | **CONFIRMED** | §19. |
| **P6-04** | Orphan-punch report | no such query | Silently inert punches | Report | **CONFIRMED** | Must cover `SR-14`'s fourth window shape. |
| **P7-01** | PostgreSQL + Redis services in CI | [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml) | **VERIFIED: one job `api`, no `services:`, no alembic step, no `TZ`, no web job.** `pyproject.toml:67` `testpaths=["tests"]`; **no skip guard in `tests/conftest.py`** | Provision both | **CONFIRMED (`TST-001`, `NEW-06`)** | None. |
| **P7-02** | *(not in the plan)* CI DB role | `ci.yml` uses `postgresql://hrms:hrms_dev_password@…`; the app uses `hrms_app` | CI would connect as the schema owner | Connect as `hrms_app` | **NEW — `SR-10`** | None. **Non-negotiable or RLS tests are theatre.** |

---

# 4. `NEW-01` — INVALID IANA TIMEZONE ON `ShiftVersion`

## 4.1 Lifecycle trace — VERIFIED at every stage

```text
CREATE    POST /shifts/{id}/versions
          ShiftVersionCreate.timezone : str | None = Field(default=None, max_length=64)
          organisation/schemas.py:1243          ── NO IANA VALIDATOR
          service.create_shift_version :2411    ── "timezone": body.timezone, stored verbatim
   ↓
UPDATE    PATCH /shifts/{id}/versions/{vid}     (DRAFT only)
          ShiftVersionUpdate.timezone           ── NO IANA VALIDATOR   schemas.py:1280
   ↓
PUBLISH   POST /shifts/{id}/versions/{vid}/publish
          _validate_and_derive_for_publish      organisation/service.py:2282-2345
          validates shift_type, effective_from, start/end, flex window, core hours,
          duty blocks, break containment                     ── NEVER THE TIMEZONE
   ↓
RESOLVE   resolve_shift_version_as_of(company, shift, date)
          attendance/service.py:2777            ── returns the row, no validation
          calc.resolve_timezone(shift_tz, branch_tz, company_tz)   calculation.py:294-298
          ── the shift value is FIRST in the WD-06 precedence chain, so it WINS
   ↓
CALCULATE ZoneInfo(tz_name)                     ── 8 call sites in calculation.py
          :324 :343 :355 :364 :398 :582 :1095 :1332
          ZoneInfoNotFoundError  (a subclass of KeyError — VERIFIED)
   ↓
HANDLER   @app.exception_handler(Exception)     core/errors/handlers.py:74-81
          -> HTTP 500  {"code": "INTERNAL_ERROR"}
```

**VERIFIED by execution:**

```text
'IST'            in zoneinfo.available_timezones()  ->  False
ZoneInfo('IST')                                     ->  ZoneInfoNotFoundError
'Asia/Calcutta'  in available_timezones()           ->  True    (see §6)
'EST'            in available_timezones()           ->  True    (legacy zone, resolves)
```

## 4.2 `SR-09` — this is an HR-user path, not an API-only path

`shift-version-form.tsx:66-72` and `branch-form.tsx:93-99` render the timezone as a **free-text
`<Input>` with placeholder `Asia/Kolkata`** — not a dropdown. `validate-shift-version.ts:228` sends
`values.timezone.trim()` with **no client-side validation**.

| Surface | Widget | Frontend validation | Backend validation | Outcome of typing `IST` |
|---|---|---|---|---|
| `/register` | `<select>` from `Intl.supportedValuesOf` | n/a — cannot type | ✔ `schemas.py:111` | not reachable |
| Branch create / update | **free-text `<Input>`** | **none** | ✔ `schemas.py:694` / `:729` | clean **422** |
| **Shift version create / update** | **free-text `<Input>`** | **none** | **✘ none** | **persisted → HTTP 500 at every calculate for every employee on that shift** |

This raises `NEW-01` from *"an API caller could"* to *"an HR administrator will, by typing the
abbreviation every Indian uses for their own timezone."* **`IST` is the single most likely wrong
value a real Indian HR user would enter.**

## 4.3 Option A vs. Option B for India V1

### Option A — restrict `ShiftVersion.timezone` to `Asia/Kolkata`

| Dimension | Assessment |
|---|---|
| Correctness | Eliminates the failure. |
| Compatibility | **Breaks the existing test suite immediately** — 11 `shift_version` rows and 15 test-fixture literals carry `"UTC"` (§21). Every affected test would need rewriting in the same change. |
| Future | Contradicts the brief's own instruction *"do not destroy existing timezone-aware architecture unnecessarily."* Re-opening it for expansion means touching the engine's most load-bearing input. |
| Engine property | **Destroys `P-20` / `PC-01` testability.** The server-timezone-independence suite (§17.7 of the plan) relies on evaluating with non-IST zones. A schema-level India lock on the *shift* tier removes the ability to prove the engine is zone-agnostic. |

### Option B — keep IANA, validate strictly *(recommended)*

| Dimension | Assessment |
|---|---|
| Correctness | Eliminates the failure at the same boundary the other three timezone columns already use. |
| Compatibility | **Zero breakage.** `UTC` is a valid IANA identifier; the 11 fixture rows and 15 test literals remain valid. |
| Future | The India invariant is enforced where it belongs — at **company registration** (`NEW-04`), the only tier an external party can set. Branch and shift remain internal, admin-only, and IANA-constrained. |
| Effort | **One validator, copied verbatim from `BranchCreate` (`schemas.py:691-696`), applied to two schemas plus one publish check.** |

> ## RECOMMENDATION — ENGINEERING DECISION (`ED-1`, §23)
>
> **Option B.** Validate `ShiftVersion.timezone` against `zoneinfo.available_timezones()` at create,
> at update, **and** at publish — three layers, because a draft may be created with a valid zone,
> patched to an invalid one, and published; and because publish is the point at which the value
> becomes load-bearing for real calculations.
>
> **Reason:** the India invariant does not need to be enforced at the shift tier to hold. WD-06
> resolves `Shift > Branch > Company`; if `/register` is gated (`NEW-04`) and branch/shift are
> admin-only surfaces, every India tenant resolves to `Asia/Kolkata` without a schema lock.
> Option A would buy nothing and cost the engine's provable zone-independence.
>
> **Compatibility implications:** none. `UTC` stays valid.
> **Migration implications:** none. No existing row becomes invalid — **VERIFIED**: every
> `shift_version.timezone` value in the dev database is `UTC` or `NULL`, both acceptable.
> **`NULL` must remain acceptable** — it is the "inherit from branch/company" signal that WD-06
> depends on, and 7 rows use it.

## 4.4 Exact validation layer

| Layer | Change | File |
|---|---|---|
| **Schema (primary)** | `@field_validator("timezone")` rejecting anything outside `available_timezones()`, mirroring `BranchCreate.validate_timezone` verbatim | `organisation/schemas.py` — `ShiftVersionCreate` (`:1243`) and `ShiftVersionUpdate` (`:1280`) |
| **Publish (defence in depth)** | Timezone check inside `_validate_and_derive_for_publish` | `organisation/service.py:2282` |
| **Engine (fail-safe, not validation)** | Wrap `ZoneInfo(tz_name)` construction so an unresolvable zone raises a typed `ConfigurationError` → **422/409 with the offending value named**, never a bare 500. The status is a `CONFIG_ERROR` attendance day, which the engine already models | `calculation.py` / `attendance/service.py` |
| **Frontend (usability, not enforcement)** | Replace the free-text `<Input>` with the same `listTimezones()` select `/register` uses, on **both** the shift-version and branch forms | `shift-version-form.tsx:66`, `branch-form.tsx:93` |

> The engine-layer item is **not** redundant. `attendance_day` already has a `CONFIG_ERROR` status
> for exactly this class of problem. Turning an unresolvable zone into a `CONFIG_ERROR` day rather
> than a 500 means one misconfigured shift degrades one employee-date instead of taking out every
> calculate call — which matters because Phase 6 introduces a **scheduled job** that will hit it
> repeatedly and silently.

## 4.5 Tests required

| # | Test | Tier |
|---|---|---|
| 1 | `POST /shifts/{id}/versions` with `timezone="IST"` → **422**, never 500 | integration |
| 2 | `PATCH …/versions/{vid}` with `timezone="IST"` → **422** | integration |
| 3 | `POST …/publish` on a draft whose timezone was made invalid → **422** | integration |
| 4 | `timezone=None` on create → accepted; WD-06 falls through to branch, then company | integration |
| 5 | `timezone="UTC"` → accepted *(regression guard for the 11 existing rows and 15 test literals)* | integration |
| 6 | `timezone="Asia/Calcutta"` → accepted *(alias guard, §6)* | integration |
| 7 | A pre-existing row with an unresolvable zone → `CONFIG_ERROR` day, **not** HTTP 500 | integration |
| 8 | **`E7` from the plan's §17.5** — the end-to-end guard: invalid zone never reaches `calculate` | integration |

---

# 5. `NEW-02` — `todayIso()` ON THE CALCULATION PATH

## 5.1 The full flow — VERIFIED

```text
BROWSER   new Date()                                    ── the viewer's device clock
   ↓      .toISOString()                                ── converted to UTC
          .slice(0,10)                                  ── the UTC CIVIL DATE
          format.ts:28  todayIso()
   ↓
CALLER    employee-attendance-panel.tsx:78
          apiClient.post(`/attendance/days/calculate?employee_id=${id}&date=${todayIso()}`)
   ↓
API       router.py:858-866  calculate_attendance_day
          date_param: Annotated[date, Query(alias="date")]      ── REQUIRED, no default
          guarded by require_permission(ATTENDANCE_VIEW_ALL)
   ↓
SERVICE   AttendanceDayService.calculate(company, employee, target_date)   service.py:2483
          target_date IS the attendance_date — an INPUT, never derived      (§10)
   ↓
DB        attendance_day.attendance_date = that value
          UNIQUE (company_id, employee_id, attendance_date)
```

**Consequence, VERIFIED:** for IST, `new Date().toISOString().slice(0,10)` returns the **previous**
calendar day whenever local time is between `00:00` and `05:29`. Pressing "Calculate today" in that
window computes **yesterday's** attendance day and reports success.

## 5.2 Classification

| Candidate | Verdict |
|---|---|
| A genuine bug | **Partly.** The date is wrong for 5h30m of every day. |
| An intentional workflow | **No.** `format.ts`'s own header comment says these helpers are *"never used for calculation, only for rendering values the backend already computed"* — **and `todayIso()` sits in that same file.** The comment documents an intent the code violates. |
| A legacy implementation | **Yes, in origin.** `todayIso()` was written as a display-filter seed (its other 15 uses are all filter defaults) and was reused for a calculation parameter without the contract being re-read. |
| **An API contract problem** | **Yes — and this is the root cause.** `POST /attendance/days/calculate` **requires** a `date` and offers **no** "today" semantics, so every caller must independently derive the India business date. There is exactly one caller today and it gets it wrong. A second caller would have the same 50/50 chance. |

> **It is an API contract problem expressed as a frontend bug.** Fixing only the frontend leaves the
> next caller free to repeat it.

## 5.3 `SR-06` — the second, unreported path

`create-period-dialog.tsx` seeds **persisted business-date boundaries** from the same UTC helper:

```text
create-period-dialog.tsx:33,34   useState(todayIso())        periodStart / periodEnd
                        :40,41   reset() -> todayIso()
                        :48-51   POST /attendance-periods { period_start, period_end, label }
```

`attendance_period.period_start` / `period_end` govern `_ensure_date_open` and therefore **every
period-lock decision and every payroll cutoff**. Between 00:00 and 05:29 IST the dialog pre-fills
*yesterday* for both.

**Mitigating:** the value is shown in an editable date field, so a user *can* correct it. **Not
mitigating:** nobody checks a pre-filled date that looks plausible, and the window in which it is
wrong is exactly the window in which a night-shift supervisor would be creating one.

**Severity is lower than `NEW-02` (visible and editable vs. invisible and automatic) but the blast
radius is higher (a period boundary vs. one day's recompute).** Both must be fixed in Phase 3.

## 5.4 The safest India V1 design

> ## RECOMMENDATION
>
> **Fix the contract first, then the callers. Three changes, in this order:**
>
> **1. Make `date` optional server-side, defaulting to the India business date.** *(`ED-2`, §23)*
> ```text
> date_param: Annotated[date | None, Query(alias="date")] = None
>     ↓
> target_date = date_param or business_today(company_timezone)
> ```
> This is **backward compatible** (an explicit date still works, so no existing test or caller
> breaks), it removes the client's ability to be wrong, and it puts the India business date where
> the company timezone already lives — on the server. **It is the smallest change that closes the
> class of defect rather than one instance.**
>
> **2. Stop sending the parameter from `employee-attendance-panel.tsx:78`.** The button means
> "calculate today"; with change 1, omitting the parameter *is* "today", resolved correctly.
>
> **3. Replace `todayIso()` with `businessToday(tz)` at all 16 invocations**, delete the duplicate at
> `policy-resolution/page.tsx:27` (`NEW-05`), and delete `todayIso()` itself so the wrong helper
> cannot be reintroduced by autocomplete.
>
> **Do not** fix this by computing an IST date in the browser and continuing to send it. That keeps
> the client authoritative for a business date — the same category of mistake as a client-authoritative
> punch time, which Phase 1 exists to remove. It also requires shipping the company timezone to the
> browser *before* the fix can land, needlessly coupling Phase 3 to Phase 5.

**`todayIso()` call-site inventory — VERIFIED, 16 invocations across 8 files** (`SR-12` corrects the
plan's 14 / 7):

| File | Invocations | Reaches persisted data? |
|---|---|---|
| `components/attendance-period/create-period-dialog.tsx` | 4 (`:33,34,40,41`) | **YES — `SR-06`** |
| `components/attendance/employee-attendance-panel.tsx` | 2 (`:43,78`) | **YES at `:78` — `NEW-02`** |
| `app/app/overtime/page.tsx` | 2 (`:62,63`) | no — filter |
| `app/app/regularizations/page.tsx` | 2 (`:64,65`) | no — filter |
| `app/app/leave-applications/page.tsx` | 2 (`:62,63`) | no — filter |
| `app/app/rosters/page.tsx` | 2 (`:72,73`) | no — filter |
| `app/app/attendance/page.tsx` | 1 (`:66`) | no — filter |
| `app/app/policy-resolution/page.tsx` | 1 (`:37`, using the **duplicate** at `:27`) | no — filter |

---

# 6. `NEW-03` — `Asia/Calcutta`

## 6.1 What was inspected — VERIFIED, read-only

```sql
-- SELECT timezone, count(*) ... GROUP BY timezone     (no writes performed)
company        Asia/Kolkata  403     Asia/Calcutta  3
branch         NULL           79     UTC           11
shift_version  NULL            7     UTC           11
attendance_day UTC            10
```

```text
id                                    name              timezone       status  days  punches
31e98bd8-6732-44c5-9eeb-8269a97d73d1  technobeala       Asia/Calcutta  TRIAL   0     0
12906c1e-fc32-43e1-9398-b1e0b2717993  Phase1 Test Co    Asia/Calcutta  TRIAL   0     0
f6fd16bd-6d6e-41aa-bfde-b4253d04d8c0  Demo Staffing Co  Asia/Calcutta  TRIAL   0     0
```

**All three are `TRIAL` with zero attendance days and zero punches.** The plan's `DH-2` escape hatch
therefore covers **100 %** of the affected rows in this environment, with no judgement calls.

## 6.2 Layer-by-layer inspection

| Layer | Behaviour with `Asia/Calcutta` | VERIFIED |
|---|---|---|
| **Database** | Plain `VARCHAR`; no constraint, no normalisation | ✔ |
| **API validation** | **ACCEPTED** — `'Asia/Calcutta' in available_timezones()` is `True`, so all four existing validators pass it | ✔ by execution |
| **Calculation** | **Identical results.** `ZoneInfo('Asia/Calcutta')` and `ZoneInfo('Asia/Kolkata')` are the same rules; India has had a stable `+05:30` offset since 1945 | ✔ |
| **`.key` round-trip** | `ZoneInfo('Asia/Calcutta').key == 'Asia/Calcutta'` — **`zoneinfo` does NOT canonicalise** | ✔ by execution |
| **Reports / API responses** | The raw string is echoed — `attendance_day.timezone` at `schemas.py:1391`, rendered as a page subtitle at `attendance/[id]/page.tsx:109` | ✔ |
| **Frontend** | [`timezones.ts:22`](../../apps/web/src/lib/timezones.ts#L22) `preferred = ["Asia/Kolkata", "Asia/Calcutta"]` — prefers the canonical name and falls back to the alias **only when the browser's ICU does not list the canonical one**. This is the exact production mechanism | ✔ |
| **Tests** | Zero references to `Asia/Calcutta` anywhere in `tests/` | ✔ by grep |
| **Imports** | `employee_import` imports employees only; it never sets a timezone | ✔ by grep |

> **This will recur in production.** It is not dev residue — it is produced by the real `/register`
> flow on browsers whose ICU reports the legacy alias. Normalising the three rows fixes the past;
> only normalising **on write** fixes the future.

## 6.3 The four candidate treatments

| Treatment | Verdict |
|---|---|
| **Reject `Asia/Calcutta`** | **No.** It is a valid IANA identifier and the browsers that send it are not wrong. Rejection turns a cosmetic inconsistency into a registration failure for a subset of real users. |
| **Accept as an alias, store as-is** | **Insufficient alone.** Calculations are already correct; the risk is *string comparison* — any invariant, report grouping, or allow-list written as `tz == "Asia/Kolkata"` silently mis-handles them. `IR-9` in the plan is right about this. |
| **Normalize automatically on write** | **Yes — this is the fix.** |
| **Migrate existing rows** | **Yes, and trivially safe here** — all three are `TRIAL`/zero-attendance. |

> ## RECOMMENDATION — ENGINEERING DECISION (`ED-3`, §23)
>
> **Canonical representation: `Asia/Kolkata`. Enforce it by normalising on write, at the schema
> layer, for every timezone field.**
>
> 1. **Normalise on write.** Extend the existing `validate_timezone` validators (`schemas.py:108`,
>    `:256`, `:691`, `:726`, and the two new `ShiftVersion` ones from §4) to map a small explicit
>    alias set to its canonical name **after** the `available_timezones()` check. Start with
>    `{"Asia/Calcutta": "Asia/Kolkata"}`. **Do not** attempt general IANA alias resolution —
>    `zoneinfo` does not expose one, and a hand-rolled table for 600 zones is a liability for an
>    India-only product.
> 2. **Never write `tz == "Asia/Kolkata"` anywhere.** With normalisation on write the comparison
>    becomes safe for *new* rows, but pre-normalisation rows may still exist in environments not yet
>    cleaned. Use a module-level `INDIA_TIMEZONES = frozenset({"Asia/Kolkata", "Asia/Calcutta"})` for
>    every invariant check and allow-list, in the same change. **This is a lint-able rule.**
> 3. **`DH-2` migration** — see §21. Guarded, audited, reversible, and in this environment it touches
>    three `TRIAL` rows with no attendance.

---

# 7. `NEW-04` — PUBLIC REGISTRATION TIMEZONE

## 7.1 Where the timezone is displayed, selected, submitted, stored, consumed

| Stage | Location | Behaviour — VERIFIED |
|---|---|---|
| **Displayed** | [`register/page.tsx:163-170`](../../apps/web/src/app/register/page.tsx#L163) | A `<select>` populated from `listTimezones()` |
| **Sourced** | [`timezones.ts:5-15`](../../apps/web/src/lib/timezones.ts#L5) | `Intl.supportedValuesOf("timeZone")` — **the browser's entire IANA list**, ~600 entries |
| **Defaulted** | `register/page.tsx:39` → `resolveDefaultTimezone(timezones)` | `Asia/Kolkata`, falling back to `Asia/Calcutta` (§6) |
| **Submitted** | `POST /v1/auth/register` | Free choice from the list |
| **Validated** | [`organisation/schemas.py:100,108-113`](../../apps/api/src/hrms/modules/organisation/schemas.py#L100) | `timezone: str = Field(default="Asia/Kolkata")` + IANA check. **No country gate.** |
| **Stored** | [`core/db/models/identity.py:45`](../../apps/api/src/hrms/core/db/models/identity.py#L45) | `Company.timezone`, `String(50)`, Python-side `default="Asia/Kolkata"` |
| **Consumed** | `calculation.py:294-298` | The **terminal** link of the WD-06 chain — the value every calculation falls back to |

**So:** an anonymous visitor can create a company whose every attendance calculation runs in
`America/Los_Angeles`, with no administrator involved, on an India-only product.

## 7.2 Why hiding the field is not sufficient

The brief states this and it is correct. Concretely:

- `CompanyRegistrationRequest.timezone` has a **Python-side default**, not a server default. A
  client that simply omits the field gets `Asia/Kolkata` — so hiding the field *would* produce
  correct data for the shipped web client. **But** `POST /v1/auth/register` is a public, unauthenticated
  endpoint; anyone can post any valid IANA zone directly. Hiding the widget changes nothing about
  what the API accepts.
- The India invariant is a **product** rule. Product rules that live only in a React component are
  not rules.

## 7.3 The safest V1 behaviour

> ## RECOMMENDATION — CLIENT DECISION ON SCOPE (`CD-2`, §22) · ENGINEERING ON MECHANISM
>
> **Enforce server-side with a settings-driven allow-list; make the frontend match it rather than
> define it.**
>
> **Backend (the enforcement):**
> ```text
> settings.allowed_company_timezones: list[str] = ["Asia/Kolkata"]
>     ↓
> CompanyRegistrationRequest.validate_timezone:
>     1. reject if not in available_timezones()          (existing)
>     2. canonicalise via the alias map                  (§6, so Asia/Calcutta normalises IN,
>                                                         it does not get rejected OUT)
>     3. reject if not in settings.allowed_company_timezones  -> 422, naming the allowed set
> ```
> Order matters. Canonicalisation **must** precede the allow-list check, or every browser reporting
> the legacy alias is locked out of registration — which is `IR-9` arriving through the front door.
>
> **Why a settings list rather than a hard-coded constant:** expansion becomes a configuration
> change, not a code change and release. The brief explicitly requires not foreclosing
> international expansion.
>
> **Frontend:** filter the `<select>` to `settings.allowed_company_timezones` **fetched from the API**,
> not a second hard-coded list in TypeScript. Two independently-maintained lists is how they drift.
> If exactly one zone is allowed, render it as static text, not a one-option dropdown.
>
> **Also gate `PATCH /company/profile`.** `CompanyProfileUpdate.timezone` (`schemas.py:247,256-261`)
> is the same field reached by an authenticated admin. The allow-list belongs on **both**, or the
> invariant holds only until the first admin edits their profile. **The plan does not mention this
> path in its `NEW-04` remediation** — it covers it under `TZ-01`'s change guard, which is a different
> control answering a different question (*may it change?* vs. *to what?*).

---

# 8. `NEW-05` / `NEW-06`

## 8.1 `NEW-05` — the duplicate `todayIso()`

**VERIFIED:** [`policy-resolution/page.tsx:27`](../../apps/web/src/app/app/policy-resolution/page.tsx#L27)
defines a private `todayIso()`; `:37` calls it to seed a date filter.

| Question | Answer |
|---|---|
| Is the body identical? | Yes — the same `new Date().toISOString().slice(0,10)`. |
| **Behavioural impact today** | **None beyond the shared helper's own defect.** It seeds one display filter on one page. |
| **Behavioural impact after Phase 3** | **This is where it matters.** Once the shared `todayIso()` is replaced by `businessToday(tz)`, this page keeps the UTC behaviour **and no test or type error reveals it.** It becomes the single surviving instance of a defect everyone believes is fixed. |
| Verdict | **Not a bug. A remediation trap.** Delete it in the same commit that changes the shared helper, and delete `todayIso()` itself so the name cannot be re-imported. |

## 8.2 `NEW-06` — CI has no frontend job

### What CI runs today — VERIFIED

```text
.github/workflows/ci.yml   ── ONE job: `api`
  checkout → setup-uv → setup-python 3.12 → uv sync --all-groups
  → ruff check → ruff format --check → mypy src/hrms → lint-imports
  → "Unit tests":  uv run pytest          ← the step NAME says unit; pytest collects EVERYTHING
                                            (pyproject.toml:67  testpaths = ["tests"])
  env: DATABASE_URL=postgresql://hrms:hrms_dev_password@localhost:5433/hrms_dev
       REDIS_URL=redis://localhost:6380/0
```

| Gate | Runs? | Evidence |
|---|---|---|
| Backend lint / format / mypy / import boundaries | ✔ | 4 steps |
| Backend **unit** tests (362) | ✔ | collected and pass without a DB |
| Backend **integration + security** tests (**802**) | ✘ **invoked but cannot pass** | no `services:` block; **no skip guard in `tests/conftest.py`**; `localhost:5433` does not exist on the runner |
| PostgreSQL / Redis provisioned | ✘ | no `services:` |
| Migrations applied | ✘ | no `alembic` step |
| RLS roles provisioned | ✘ | `infra/docker/postgres/init` is mounted only by `docker-compose` |
| **Runs as the non-BYPASSRLS app role** | ✘ **`SR-10`** | `ci.yml` uses `hrms` (schema owner); the app uses `hrms_app` |
| `TZ` pinned | ✘ | no `TZ` in the job env |
| **Frontend job** | ✘ **`NEW-06`** | one job only |
| Frontend tests exist | ✔ **45 `*.test.ts(x)` files**, `"test": "vitest run"` | `apps/web/package.json:10` |
| Attendance / timezone tests gate merges | ✘ | unit-only in effect; **zero DST tests exist** |

> **Because there is no skip guard, `uv run pytest` must currently fail on `main`.** Either CI is red
> and tolerated, or the checks are not required for merge. **Both readings are equally disqualifying
> for a payroll-input remediation programme, and Phase 0 must establish which it is** — the answer
> changes how much of Phase 7 is "add jobs" versus "fix a suite nobody has run honestly."

### Minimum CI gate before remediation begins

The bar is: **a PR that breaks an attendance or timezone rule must fail to merge.** That requires all
seven of the following. Fewer than seven is not a gate.

| # | Requirement | Why it is minimum, not nice-to-have |
|---|---|---|
| 1 | PostgreSQL 16 + Redis 7 as `services:`, health-checked | Without it, 802 tests are decoration |
| 2 | `infra/docker/postgres/init/*.sql` applied explicitly | A `services:` container does **not** run `docker-entrypoint-initdb.d`. Without it the `hrms_app` role does not exist |
| 3 | **`DATABASE_URL` points at `hrms_app`, not `hrms`** (`SR-10`) | The owner role is not `NOBYPASSRLS`. Running tenant-isolation tests as the owner proves nothing, and proves it *green* |
| 4 | `alembic upgrade head` as a step | The schema under test must be the schema that ships |
| 5 | `TZ: UTC` in the job env | `R-TZ-02b`; also the control arm of the `PC-01` regression suite |
| 6 | A `web` job: `npm ci` → `npm run lint` → `npm test` | 45 test files currently gate nothing |
| 7 | **Both jobs required status checks on `main`** | Adding a job is not a gate. This is a repository setting, not a file |

> Requirement 3 is the one most likely to be skipped and the most damaging if it is. **It must be
> verified by a test that asserts RLS actually denies a cross-tenant read in CI** — otherwise the
> only evidence that the gate works is that it is green, which is exactly the failure mode.

---

# 9. `OD-1` — PERIOD LOCK vs. ATTENDANCE DATE

> **This section derives its answers by executing the shipped window functions. Nothing here is
> assumed.** Where the existing system genuinely does not define an answer, the row is marked
> **CLIENT DECISION REQUIRED**.

## 9.1 The four date concepts, defined from the code

| Concept | Definition in this system | Where it lives | Derived or asserted? |
|---|---|---|---|
| **Civil date** | The calendar date in some named zone. Two are in play: the **IST civil date** and the **UTC civil date** of the same instant | not stored | Derived from an instant + a zone |
| **Shift date** | The local date on which a shift *instance* starts. For `22:00→06:00` on 30 Sep, the instance runs 30 Sep 22:00 → 1 Oct 06:00 IST, and its shift date is **30 Sep** | `shift_version.start_time` + the date it is resolved for | Derived |
| **Attendance date** | **Identical to the shift date.** `AttendanceDay.attendance_date` — *"One row per employee per attendance date (the shift's start date for overnight shifts, FR-ATT-005)"* ([`attendance/models.py:476-477`](../../apps/api/src/hrms/modules/attendance/models.py#L476)) | `attendance_day.attendance_date` (`DATE`) | **ASSERTED by the caller** — see §10 |
| **Payroll period date** | The `[period_start, period_end]` range of an `attendance_period`, compared against a single date | `attendance_period.period_start/_end` (`DATE`) | Asserted at period creation |

## 9.2 The mechanism under test

```python
# attendance/service.py:2347 — the punch path
await _ensure_date_open(self._session, company_id, (body.punch_time or now).date())
#                                                   └─ a UTC civil date (WD-30)

# attendance/service.py:1915-1929 — what it does
closed_period = await period_repo.get_covering(session, company_id=..., target_date=..., status="CLOSED")
if closed_period is not None: raise AttendancePeriodClosedError()
```

Two properties that bound the whole discussion:

1. **It only rejects `CLOSED`.** A date covered by an `OPEN` period, or by **no period at all**, is
   accepted. So the failure mode is confined to genuine period boundaries.
2. **`calculate()` is the real backstop** and is unconditional — `_ensure_date_open(target_date)` at
   `:2504` plus `existing.is_locked` at `:2511`. **A punch that slips past the ingestion check can
   never rewrite a locked day; it becomes an inert row.** This is why every option below fails
   *closed* on the thing that matters.

## 9.3 Scenario table — DERIVED BY EXECUTION

**Setup.** Night shift `22:00→06:00`, `Asia/Kolkata`, attendance date **2026-09-30**.
Scheduled span **`2026-09-30T16:30Z` → `2026-10-01T00:30Z`**; ±2h punch window **`2026-09-30T14:30Z`
→ `2026-10-01T02:30Z`** = **20:00 IST 30 Sep → 08:00 IST 1 Oct**. September is **CLOSED**, October is
**OPEN**. All punches occur on **1 Oct IST**.

| Scenario | Event | UTC instant | IST time | Civil date (IST) | Civil date (UTC) | Shift date | **Attendance date** | Payroll period | Period-lock decision **today** (UTC basis) | **Correct** decision |
|---|---|---|---|---|---|---|---|---|---|---|
| **A** | Works the full shift `22:00→06:00` | `16:30Z` 30 Sep → `00:30Z` 1 Oct | 22:00 → 06:00 | 30 Sep → 1 Oct | 30 Sep → 1 Oct | 30 Sep | **2026-09-30** | September (CLOSED) | IN rejected, OUT **accepted** | both rejected |
| **B** | Punch `00:30 IST` | `2026-09-30T19:00Z` | 00:30 | **1 Oct** | **30 Sep** | 30 Sep | **2026-09-30** | September | **REJECTED** ✅ | REJECTED |
| **C** | Punch `05:00 IST` | `2026-09-30T23:30Z` | 05:00 | **1 Oct** | **30 Sep** | 30 Sep | **2026-09-30** | September | **REJECTED** ✅ | REJECTED |
| **D** | Punch `05:29 IST` | `2026-09-30T23:59Z` | 05:29 | **1 Oct** | **30 Sep** | 30 Sep | **2026-09-30** | September | **REJECTED** ✅ | REJECTED |
| **E** | Punch `05:30 IST` | `2026-10-01T00:00Z` | 05:30 | 1 Oct | **1 Oct** | 30 Sep | **2026-09-30** | September | **ACCEPTED** ❌ | REJECTED |
| **F** | Punch `06:00 IST` | `2026-10-01T00:30Z` | 06:00 | 1 Oct | **1 Oct** | 30 Sep | **2026-09-30** | September | **ACCEPTED** ❌ | REJECTED |

**The `05:29 → 05:30` step at scenarios D→E is the entire defect.** It is the UTC-offset boundary,
and it has nothing to do with the shift, the attendance date, or the period — which is exactly why it
is wrong.

### The mirror case — where the UTC basis *falsely rejects*

| Scenario | Setup | Result |
|---|---|---|
| **G** | **Early day shift** `06:00→14:00` on **1 Oct**, padded window **04:00–16:00 IST**. September CLOSED. Punch at `04:30 IST` 1 Oct → `2026-09-30T23:00Z` | Attendance date is **1 Oct** (October, OPEN) but the UTC date is **30 Sep** → **FALSELY REJECTED** |

**This is the complete divergence rule, derived:**

```text
For Asia/Kolkata (+05:30, no DST):
    UTC civil date  ==  IST civil date - 1   if and only if   IST time < 05:30
    UTC civil date  ==  IST civil date       otherwise

Therefore the two bases can only disagree for a punch whose IST wall time is < 05:30,
which requires the shift's PADDED window to open before 05:30 IST — i.e. a shift
starting before 07:30 IST, or any cross-midnight shift.
```

> ## `SR-13` — For **every ordinary day shift, there is no decision to make.**
> A `09:00–18:00` shift loads punches only between **07:00 and 20:00 IST**. Every one of those has
> `UTC date == IST date`. **The UTC basis and the IST basis produce byte-identical results for the
> entire mainstream tenant population.** `OD-1` is not a system-wide question; it is a **night-shift
> and early-shift** question.

## 9.4 Evaluating the four candidate bases against the derived table

| Basis | B/C/D (00:00–05:29, night) | E/F (05:30–08:00, night) | G (early day shift) | Ordinary day shift |
|---|---|---|---|---|
| **UTC civil date** *(today, WD-30)* | ✅ correct | ❌ false accept | ❌ false reject | ✅ correct |
| **IST civil date** *(the brief's §12 literal reading)* | ❌ false accept | ❌ false accept | ✅ correct | ✅ correct |
| **Plan's Option B** — accept if **either** the IST date **or** the previous IST date is open | ❌ false accept | ❌ false accept | ✅ correct | ✅ correct |
| **Resolved attendance date** — run shift resolution during ingestion | ✅ | ✅ | ✅ | ✅ |

### Two corrections to the plan's `OD-1` framing

> **1. "Strictly safer than today" is not accurate.** The plan (§23.2) describes Option B that way.
> Option B is **strictly more permissive** than today in the night-shift band: it converts today's
> three correct rejections (B, C, D) into acceptances. It eliminates false *rejections* at the cost of
> additional false *acceptances*. That may well be the right trade — but it must be chosen as a trade,
> not adopted under a description that hides one side of it.
>
> **2. The brief's §12 instruction, applied literally, is the worst of the three practical options.**
> Switching to the plain IST civil date would make night shifts strictly worse than today (0/5 correct
> vs. 3/5) while fixing only scenario G. **This is the clearest example in the whole programme of why
> "use the India business date everywhere" must not be applied mechanically.**

## 9.5 What is actually at stake

Because `calculate()` refuses locked days unconditionally (§9.2 property 2), the two error types have
**asymmetric consequences**:

| Error | Consequence | Severity |
|---|---|---|
| **False rejection** | The employee's punch is **refused at the API**. The physical fact of their attendance is **never recorded anywhere**. There is no orphan row to find later, no report that can surface it. The only remedy is a regularization — which itself checks the period and would also be refused | **HIGH — an unrecoverable loss of a fact.** WD-11's whole posture is that punches are facts and facts are append-only |
| **False acceptance** | The punch is stored. `calculate()` then refuses the locked day, so it changes nothing. It appears in the **orphan-punch report** (Phase 6.6) and can be reconciled deliberately | **LOW — a recoverable, visible inconsistency** |

> **This asymmetry, not the error count, should decide `OD-1`.** A basis that never falsely rejects is
> preferable to one that is right more often but occasionally destroys a fact.

## 9.6 Recommendation

> ## RECOMMENDATION — narrow `CD-1` (§22)
>
> **Adopt the plan's Option B semantics, but state the trade honestly and add the compensating
> control. Do not adopt the plain IST civil date.**
>
> ```text
> Accept the punch when EITHER the IST civil date of punch_time
>                       OR the PREVIOUS IST civil date
>                       is not covered by a CLOSED period.
> Refuse only when BOTH are closed.
> ```
>
> **Why:** it eliminates every false rejection (the unrecoverable error) in all four scenario
> families, at the price of false acceptances that are inert, visible, and recoverable.
>
> **The compensating control is not optional.** Option B is only acceptable **shipped together with
> the orphan-punch report (Phase 6.6)**, which is the mechanism that makes a false acceptance
> recoverable rather than silent. Shipping Option B without it converts a loud failure into a quiet
> one. **Sequence Phase 3.10 after Phase 6.6, or ship them together.**
>
> **Why not resolve the true attendance date at ingestion** (the only fully correct option): it
> requires shift resolution — roster lookup, assignment as-of, shift version as-of — **inside the
> punch write path**, for a check whose backstop already exists. It converts a two-statement guard
> into six queries on the hottest write path in the module, and it is circular at the margin (the
> date determines the shift; the shift determines the date). **Revisit only if the orphan report
> shows this is a real operational problem.**
>
> **What the client must actually decide (`CD-1`):** not the algorithm — *whether an employee's
> punch may ever be refused because a period closed.* If the answer is "never refuse a punch, always
> record the fact and reconcile", the guard reduces to a warning and Option B is trivially right. If
> the answer is "a closed period must refuse writes", Option B is the best available approximation.
> **Both are legitimate; they are different businesses.**

---

# 10. ATTENDANCE DATE IS NOT A UTC DATE — AND IS NOT DERIVED AT ALL

## 10.1 The definitive answer

> ### `attendance_date` is **the shift instance's start date, expressed in the WD-06-resolved timezone.**
> ### It is an **input asserted by the caller**, never derived from a punch.

**Evidence, all VERIFIED:**

| Source | Statement |
|---|---|
| [`attendance/models.py:476-477`](../../apps/api/src/hrms/modules/attendance/models.py#L476) | *"One row per employee per **attendance date** (the shift's start date for overnight shifts, FR-ATT-005)"* |
| [`attendance/service.py:2483-2504`](../../apps/api/src/hrms/modules/attendance/service.py#L2483) | `calculate(company_id, employee_id, target_date)` — `target_date` **is** the attendance date; it is a parameter |
| [`router.py:865`](../../apps/api/src/hrms/modules/attendance/router.py#L865) | `date_param: Annotated[date, Query(alias="date")]` — **required**, supplied by the caller |
| [`service.py:2645-2649`](../../apps/api/src/hrms/modules/attendance/service.py#L2645) | `recompute()` reads `row.attendance_date` off the existing row and passes it back in |
| `calculation.py:314-345` | `punch_window_utc(attendance_date=…)` — the date **determines which punches are pulled**; punches do not determine the date |

## 10.2 Which of the candidate meanings it is

| Candidate meaning | Verdict |
|---|---|
| Local calendar date | **Only coincidentally**, for non-cross-midnight shifts, and only in the resolved zone |
| **Shift-start date** | ✅ **This is it.** `is_cross_midnight` rolls the *end*, never the date |
| Shift-end date | ✘ Explicitly not — that is what `is_cross_midnight` exists to prevent |
| Roster date | Adjacent but distinct: `shift_roster.roster_date` is resolved **for** `target_date` ([`service.py:2758-2760`](../../apps/api/src/hrms/modules/attendance/service.py#L2758)), so they coincide by construction. The roster is *looked up by* the attendance date; it does not define it |
| Payroll date | ✘ `attendance_period` ranges are compared **against** it |
| **UTC date** | ✘ **Never.** No code path derives `attendance_date` from a UTC instant |

## 10.3 The consequence that governs Phase 3

**Because the attendance date is asserted, not derived, the correctness of every `attendance_day` row
depends entirely on the caller passing the right date.** There are exactly three callers, and
**VERIFIED**, two of them are currently wrong or absent:

| Caller | Date it asserts | Status |
|---|---|---|
| `POST /attendance/days/calculate` from `employee-attendance-panel.tsx:78` | **The browser's UTC date** | ❌ **`NEW-02`** — wrong for 5h30m a day |
| `POST /attendance/days/{id}/recompute` | `row.attendance_date` | ✅ correct by construction |
| **A scheduled job** | — | ❌ **`F-14` — does not exist.** Phase 6 creates it, and it will become the **dominant** asserter of attendance dates |

> **This is the strongest argument for the §5.3 recommendation.** Phase 6's job must iterate
> `[business_today(IST) - N, business_today(IST)]`. If the business date lives on the server as a
> shared helper, the job and the API default use the same one and cannot disagree. If it lives in the
> browser, the two most important asserters of attendance dates derive it independently — which is
> precisely how `NEW-02` happened in the first place.

## 10.4 The window shapes — including one the audits missed

`resolve_schedule_window` ([`calculation.py:375-420`](../../apps/api/src/hrms/modules/attendance/calculation.py#L375))
produces **four** shapes, not the one the ±2h analysis assumes:

| Shift type | Load window | Pad |
|---|---|---|
| `FIXED` | `scheduled_span_utc` ± 2h | ±2h |
| `FLEXIBLE` | the start window `window_start`–`window_end` ± 2h | ±2h |
| `SPLIT` | first block start → last block end, ±2h | ±2h |
| **No shift resolves** | **`calendar_day_window_utc` — the full local civil day, `00:00`–`24:00` IST** | **NONE** — `SR-14` |

> **`SR-14`:** the no-shift case is the only window with **no pad and a civil-day boundary**, and it is
> covered by neither the audits, nor test-matrix groups A/B, nor the plan. It matters for two things:
> the **orphan-punch report** must not flag punches under this shape as orphans by applying ±2h logic
> to them, and `DEC-TZ-16`'s "how early may someone arrive" question **does not apply** to
> unscheduled employees at all. Add it to the boundary test group.

## 10.5 Requirement before Phase 3.10 may begin

> **`attendance_date` must be defined in writing, in `ATTENDANCE_MASTER_RULE_MATRIX.md`, as
> "the shift instance's start date in the WD-06-resolved timezone; an asserted input, never derived
> from a punch instant," before any period-lock code changes.** The definition currently exists only
> in a model docstring. Every `OD-1` option above is a *proxy* for this date; a proxy cannot be
> evaluated against a definition that is not written down.

---

# 11. AUTHORITATIVE TIME

## 11.1 Target for ordinary online employee attendance

```text
Employee taps "Punch In"
   ↓  POST /v1/attendance/punches/me     { direction }        ── no time, no source, no employee_id
   ↓
Router     resolves the caller's own employee_id from the session
           captures request.client.host + User-Agent          (already wired, router.py:784-785)
   ↓
Service    request_time = datetime.now(UTC)                   ── THE trust anchor
           punch_time   = request_time                        ── EVENT TIME == REQUEST TIME
           source       = "WEB" | "MOBILE", server-assigned from the authenticated context
           created_at   = request_time                        ── set by the app, never the DB default
           raw_payload  = { user_agent, client_ip, client_version }
   ↓
DB         punch.punch_time TIMESTAMPTZ, append-only, RLS by company_id
```

**The client clock is never read, never compared, never stored.** This is `DEC-TZ-01` Option A, and
it is the reason the skew tolerance `DEC-TZ-02` becomes moot for self-service: the control is
structural rather than numeric.

## 11.2 Every attendance endpoint that accepts a client time — VERIFIED

| Endpoint | User | Workflow | Client time accepted today? | Target authority |
|---|---|---|---|---|
| `POST /attendance/punches` **(self)** [`router.py:752`](../../apps/api/src/hrms/modules/attendance/router.py#L752) | Employee, `ATTENDANCE.PUNCH` | Mark own arrival/departure now | ✔ **yes, unbounded, offset optional** (`service.py:2353`) | **SERVER.** Field removed |
| `POST /attendance/punches` **(on-behalf)** same route, `on_behalf` at `:772` | `ATTENDANCE.PUNCH_ON_BEHALF` | HR enters a missed punch | ✔ same field, same laxity | **CLIENT — required, aware, bounded, reasoned, audited.** This is the workflow's purpose |
| `POST /attendance/punches` — `source` | any | — | ✔ **all 7 values from any caller** (`schemas.py:1236`) | **SERVER-ASSIGNED.** Field removed. **The linchpin** |
| `POST /attendance/punches` — `idempotency_key` | any | replay safety | ✔ | **CLIENT — unchanged.** Not a time |
| `POST /regularizations` — `requested_punches[].requested_time` [`schemas.py:1475`](../../apps/api/src/hrms/modules/attendance/schemas.py#L1475) | Employee / HR | Assert a historical punch | ✔ **entirely unvalidated**; becomes `punch.punch_time` verbatim at [`service.py:4108-4122`](../../apps/api/src/hrms/modules/attendance/service.py#L4108) | **CLIENT — aware, in the past, inside the padded window for `attendance_date`.** Approval-gated |
| `POST /regularizations` — `attendance_date` | Employee / HR | — | ✔ | **CLIENT**, future-checked against **`business_today(IST)`**, not `date.today()` (`TZ-06`) |
| `POST /attendance/days/calculate?date=` [`router.py:865`](../../apps/api/src/hrms/modules/attendance/router.py#L865) | `ATTENDANCE.VIEW_ALL` | Compute one employee-date | ✔ **required** query param | **SERVER-DEFAULTED** when omitted (§5.3); explicit still honoured |
| `POST /attendance-periods` — `period_start`/`_end` | HR | Define a period | ✔ | **CLIENT — correct.** But the UI default must be IST (`SR-06`) |
| `GET /attendance/punches?date_from&date_to` | any | List | ✔ **UTC day bounds** — documented at [`repository.py:1006-1008`](../../apps/api/src/hrms/modules/attendance/repository.py#L1006) | **CLIENT — unchanged.** Document the UTC/local split client-facing (`F-20`) |
| **Device / biometric** | — | — | **endpoint does not exist** | Contract fixed here, built later |
| **CSV / bulk import of punches** | — | — | **does not exist** — `employee_import` imports employees only (**VERIFIED by grep**) | Contract fixed here, built later |
| **Mobile** | — | — | **does not exist** (§12) | Server-stamped, online-only |

## 11.3 `SR-02` — the blocking design problem, and its resolution

The plan proposes two request schemas on one endpoint. **That cannot work.** The router decides which
act is occurring at [`router.py:772`](../../apps/api/src/hrms/modules/attendance/router.py#L772):

```python
on_behalf = body.employee_id is not None and body.employee_id != user.employee_id
```

The discriminator is **a field of the body being parsed**, compared against **session state**. FastAPI
must bind a request model before any of that is available. Compounding it: the shipped dialog
**always** sends `employee_id`, even for a self-punch
([`punch-entry-dialog.tsx:93`](../../apps/web/src/components/attendance/punch-entry-dialog.tsx#L93)) —
so "field present" is not a usable discriminator either.

### Options

| Option | Assessment |
|---|---|
| **A — Two endpoints** *(recommended)*: `POST /attendance/punches/me` (self) and `POST /attendance/punches` (on-behalf) | Each binds exactly one schema with `extra="forbid"`. **The permission becomes static** — `Depends(require_permission(ATTENDANCE_PUNCH))` and `Depends(require_permission(ATTENDANCE_PUNCH_ON_BEHALF))` — replacing the body-dependent `rbac.resolve_data_scope()` dance at `:773-779`. That is independently better RBAC hygiene: today a caller's permission requirement is chosen by data the caller controls. A self-punch can no longer be *mistaken* for an on-behalf punch, or vice versa, by any value in the body |
| **B — One endpoint, one union schema**, validated in the service after the act is determined | Keeps the URL. But `extra="forbid"` can no longer distinguish the two shapes, so `punch_time` on a self-punch must be rejected by a hand-written service check rather than by the schema — exactly the "conditional validators" the plan's §10.1 rejects, and it re-creates the `F-11` shape where a body field steers the code path |
| **C — Keep one endpoint, forbid `punch_time` unconditionally** | Removes the legitimate on-behalf workflow. Forbidden by the brief's §11 |

> ## RECOMMENDATION — ENGINEERING DECISION (`ED-4`, §23)
>
> **Option A — two endpoints.** The web client is changing in the same release regardless
> (`IR-1`), so the URL change costs nothing extra. **Make the router emit a typed 409 with an
> explicit message when a caller posts someone else's `employee_id` to `/me`**, rather than a bare
> 403 — the difference between "you lack permission" and "you used the wrong endpoint" is the whole
> support burden of this change.
>
> **Resolve the plan's internal contradiction in the same stroke:** §5.1 ("Two punch endpoints") is
> correct; §7.1's single-endpoint presentation must be amended.

## 11.4 `SR-03` — `AwareDatetime` does not deliver the stated wire contract

**VERIFIED by execution** against `pydantic.AwareDatetime`:

| Input | `AwareDatetime` verdict | Plan §10.2 contract wants |
|---|---|---|
| `"2026-09-15T09:00:00Z"` | ACCEPTED | accepted |
| `"2026-09-15T09:00:00+05:30"` | ACCEPTED, offset preserved | accepted |
| `"2026-09-15T09:00:00"` (naive) | **REJECTED** ✅ | rejected |
| `"2026-09-15"` (date only) | **REJECTED** ✅ | rejected |
| **`0`** (int) | **ACCEPTED → `1970-01-01T00:00:00Z`** ❌ | **rejected** |
| **`1789000000`** (int or numeric string) | **ACCEPTED → `2026-09-10T00:26:40Z`** ❌ | **rejected** |

Pydantic v2 coerces integers and numeric strings as Unix epoch seconds, and an epoch value **is**
timezone-aware, so `AwareDatetime` passes it.

> **Consequence:** `AwareDatetime` alone satisfies `P-04` (naive rejection) but **not** the plan's
> §10.2 rule *"ISO-8601 … explicit offset … no default, no inference."* An epoch integer is exactly
> an inference.
>
> **Resolution (`ED-5`, §23):** pair `AwareDatetime` with a string-type guard — a `BeforeValidator`
> that rejects non-`str` input before parsing. Two lines. **Decide deliberately:** if epoch input is
> genuinely wanted for a future device integration, say so and document it; do not let it survive
> because nobody tested an integer.

## 11.5 `SR-04` — the on-behalf backdating bound has no home

Plan §7.2 requires *"Backdating window: On-behalf beyond the configured window → 422, **policy-driven**."*

**VERIFIED:**

| Fact | Evidence |
|---|---|
| `AttendancePolicyVersion` has **no** backdating field | Full column list read at [`models.py:77-113`](../../apps/api/src/hrms/modules/attendance/models.py#L77) |
| `max_backdated_days` exists only on `RegularizationPolicyVersion` | [`models.py:339`](../../apps/api/src/hrms/modules/attendance/models.py#L339) and `LeavePolicyVersion` (`leave/models.py:131`) |
| Plan §14 states **"No database migration is required"** | plan §14 |

**Three-way contradiction.** One must give:

| Resolution | Assessment |
|---|---|
| **Add `max_backdated_punch_days` to `AttendancePolicyVersion`** | Correct modelling, effective-dated, per-tenant. **But it is a migration**, contradicting §14, and it introduces a new configurable whose default value is itself a client decision |
| **Reuse `RegularizationPolicyVersion.max_backdated_days`** | Zero schema change. **Semantically wrong** — it is the window for *requesting a correction*, not for *an admin entering a punch*. Conflating them means a tenant cannot tighten one without tightening the other |
| **Bound to the open period only** *(recommended for V1)* | **No new configuration at all.** The bound becomes: *not in the future, and not in a `CLOSED` period.* The `CLOSED`-period refusal is already non-negotiable under every `DEC-TZ-13` option, so the control already exists and is already tested |

> ## RECOMMENDATION — `ED-6` (§23), with `CD-5` as the escalation (§22)
>
> **Ship V1 with the period-only bound.** Future-rejection plus `CLOSED`-period refusal is a real,
> enforceable, already-existing control that needs no migration and no new default nobody has chosen.
> **Amend plan §7.2 to say so** rather than leaving "policy-driven" pointing at a field that does not
> exist.
>
> **Escalate to the client (`CD-5`) only this:** *"May an HR administrator enter a punch for any past
> date inside an open period — including one three months old — or should there be a tighter limit?"*
> If the answer is "there must be a tighter limit," it is a migration and belongs in a later phase,
> **and plan §14's no-migration claim must be corrected.**

## 11.6 Three unconditional requirements

Independent of every option above:

1. **`source` must be server-assigned** (`F-11`, `DEC-TZ-05`). Without it every per-path rule is
   advisory. **Cost: VERIFIED as zero test breakage** — no test in the repository sets `source` in a
   request body (`SR-12`). It must ship in the same change as the clock decision.
2. **Naive timestamps rejected + `ENV TZ=UTC`** in the Dockerfile and CI. Independent of everything;
   do both regardless.
3. **Record both instants, always.** `punch_time` (event) and `created_at` (receipt). The plan's §3.2
   decision **not** to split `request_time` from `created_at` in V1 is **endorsed** — under
   server-authoritative self-punch they are equal by construction, and the admin path's `created_at`
   already *is* the receipt time. **Its stated condition must be honoured:** a code comment and a test
   asserting `created_at` is set by the application (`service.py:2359`) and never falls back to the
   column's `server_default=func.now()` ([`models.py:466`](../../apps/api/src/hrms/modules/attendance/models.py#L466)).

---

# 12. OFFLINE / MOBILE ATTENDANCE — VERIFICATION RESULT

> ## **NO CONFLICT. V1's "no offline attendance" is already the shipped behaviour and requires no code change.**

**VERIFIED by exhaustive search of `apps/`:**

| Check | Result |
|---|---|
| Mobile application in the repository | **None.** `apps/` contains exactly `api` and `web`. No `pubspec.yaml`, no `metro.config.js`, no `*.xcodeproj` |
| Service worker / Workbox | **None** — no match in `apps/web/src` or `apps/web/public` |
| IndexedDB / local queue | **None** |
| `navigator.onLine` / offline detection | **None** |
| Does anything queue an attendance event? | **No** |
| Does anything fabricate a timestamp when offline? | **No** — the browser clock seeds a *visible, editable* field ([`punch-entry-dialog.tsx:33-37,64`](../../apps/web/src/components/attendance/punch-entry-dialog.tsx#L33)), which is `F-02`, an **online** integrity problem, not an offline one |
| Does anything replay a stale event? | **No.** On network failure `:101-106` surfaces a toast and the punch is **lost** — the correct behaviour for a client with no queue |
| Does the schema anticipate one? | **Yes** — `'MOBILE'` and `'DEVICE'` are accepted `punch.source` values (**VERIFIED in the live DB `CHECK`**), and `idempotency_key` exists |

## 12.1 The one real risk, and it is a process risk

There is **no mechanism** preventing a future contributor from adding a retry queue to
`punch-entry-dialog.tsx` as a well-meaning UX improvement. It would look like a bug fix and would
silently violate `P-08`.

> **Requirement (Phase 1):** when the dialog is split (§11), the self-mode failure path must carry an
> explicit code comment naming `P-08` and `DEC-TZ-15` row 1 — *"do not queue; a punch that did not
> reach the server did not happen"* — plus a component test asserting that a failed POST leaves **no**
> persisted state. **Preserve the existing loud failure; do not 'improve' it.**

## 12.2 The contract a future mobile client must satisfy

Recorded here so the deferral is a choice, not an omission. **Build none of it now.**

| # | Requirement |
|---|---|
| 1 | Punch time is **server-stamped**; the app sends `{ direction }` and nothing else |
| 2 | Offline punching is **not supported**; the app fails loudly and persists nothing |
| 3 | If offline is ever required it is a **separate permissioned ingestion contract** (`source=MOBILE_OFFLINE`) with its own upload-lag bound — **never** by widening a self-service tolerance |
| 4 | `source` remains server-assigned from the authenticated context |
| 5 | Display is `Asia/Kolkata`, always labelled, never the device zone |
| 6 | `punch.request_time` splits from `created_at` **at that point**, not before (plan §3.2) |

---

# 13. HISTORICAL INTEGRITY

## 13.1 The complete trace — how a historical attendance result can change

```text
Company.timezone ──┐
Branch.timezone  ──┤  resolve_timezone()  calculation.py:294-298   (WD-06: Shift > Branch > Company)
Shift.timezone   ──┘        │
                            ▼
                   _build_calculation_input(company_id, employee_id, target_date)
                            service.py:2711-2900
                   ┌────────┴─────────────────────────────────────────────────────┐
                   │  RE-RESOLVES EVERY INPUT FROM target_date, EVERY TIME:       │
                   │    employment as-of · assignment as-of · company · branch    │
                   │    roster for date · shift version as-of · policies as-of    │
                   │  READS BACK **NOTHING** from the existing attendance_day row │
                   └──────────────────────────────────────────────────────────────┘
                            ▼
                   calc.evaluate_day()   ── pure
                            ▼
                   attendance_day  ── FULL ROW REPLACEMENT (WD-10), no history table
                            ▼
                   OT record · paid_day_fraction · lop_fraction  ──►  PAYROLL
```

**VERIFIED:** `_build_calculation_input` never reads `attendance_day.shift_version_id`,
`.attendance_policy_version_id`, or `.timezone`. `recompute()`
([`service.py:2631-2652`](../../apps/api/src/hrms/modules/attendance/service.py#L2631)) passes only
`(employee_id, attendance_date)` back into `calculate()`.

> ## The precise statement of WD-11
>
> **The stored version FKs and `computation_snapshot` are *provenance*, not *pinning*.** They record
> what was used; they do not force it to be used again. Effective dating limits **which historical
> days** a configuration change can reach — it does not prevent the change from reaching them.
>
> The codebase states this itself, at [`attendance/models.py:483-484`](../../apps/api/src/hrms/modules/attendance/models.py#L483):
> *"recompute always re-resolves versions by date, so **only a backdated version publish (a privileged
> act) can change an unlocked historical day**."*

## 13.2 Every way a historical result can change, measured against that contract

| # | Mechanism | Effective-dated? | Guarded? | Verdict |
|---|---|---|---|---|
| 1 | A new punch, or an approved regularization, on an open day | n/a | `_ensure_date_open` + `is_locked` | ✅ **Intended.** This is what recompute is *for* |
| 2 | A **forward-dated** shift / policy / calendar version publish | ✔ | — | ✅ **Safe.** Cannot reach a past date |
| 3 | A **backdated** shift / policy version publish | ✔ | **nothing** — `SR-11` | ⚠️ **The docstring's named exception.** Legal: publish requires only `effective_from > current.effective_from` ([`organisation/service.py:2794`](../../apps/api/src/hrms/modules/organisation/service.py#L2794)), **not** `> today`. **VERIFIED: no configuration publish path anywhere consults `AttendancePeriod`** |
| 4 | **`Company.timezone` / `Branch.timezone` UPDATE** | **✘ NOT VERSIONED** | **`_assert_timezone_change_allowed` is an empty stub** (`:702-709`) and **`update_branch` never calls it** | 🔴 **`TZ-01` — the violation.** A plain `UPDATE` achieves what the model contract says only a *"privileged backdated version publish"* can do |
| 5 | An employee branch transfer | ✔ `EmployeeAssignment` as-of | — | ✅ Safe (`PC-11`) |
| 6 | Period close → `bulk_lock` → `calculate()` refuses | n/a | ✔ | ✅ **Real, working protection** |
| 7 | Torn configuration read under READ COMMITTED | — | none (`TZ-09`) | ⚠️ Closed as a side effect of fixing #4 |
| 8 | Concurrent recompute, last-writer-wins | — | **no `with_for_update` anywhere in `src/` (VERIFIED)** | ⚠️ `F-15` — §19 |

**#4 is the only one that is a defect.** #3 is a documented, privileged act; #1 is the design.

## 13.3 The guarantee to build

> **Once an attendance day is finalized or locked, no subsequent configuration change can alter its
> historical result.**

| Layer | Mechanism | State |
|---|---|---|
| L1 | Punches append-only; a correction is a new row (WD-11) | ✅ exists |
| L2 | Version FKs + `computation_snapshot` — **provenance for reconstruction, not enforcement** | ✅ exists, correctly understood |
| L3 | `CLOSED` period → `bulk_lock` → `calculate()` refuses | ✅ exists and works |
| L4 | **Timezone immutable once computed attendance exists** | 🔧 **Phase 2 — the gap** |
| L5 | **No torn configuration read** | 🔧 closes with L4 |
| L6 | **Refuse a backdated config publish that reaches a `CLOSED` period** | 🔧 **`SR-11` — not in the plan.** §13.5 |

**Residual, by design:** an unlocked day in an `OPEN` period can still change — an approved
regularization *should* change it. **That is the boundary between "protected" and "live", and the
period lock is the boundary marker.** Phase 2 removes timezone from the set of inputs that can move
underneath a live day; it does not, and should not, freeze the day itself.

## 13.4 Is the simplest India V1 solution "`Asia/Kolkata`, immutable"?

| Approach | Assessment |
|---|---|
| **Hard-code `Asia/Kolkata`; delete the columns** | **No.** The brief forbids it (*"do not destroy existing timezone-aware architecture unnecessarily"*), and it deletes `P-20`/`PC-01` — the property that lets the engine be proven zone-independent, and the only reason expansion would not require re-proving it. **VERIFIED cost:** 11 branches, 11 shift versions, 15 test literals and every server-TZ regression test carry non-IST values today |
| **Keep the columns; make them immutable once computed attendance exists** *(the plan's `DEC-TZ-13` Option A)* | **Yes.** Same guarantee, zero architectural loss, ~1 day of work, fully reversible, reuses the `TRIAL` currency-lock precedent (`organisation/service.py:654-656`) |
| **Effective-date the timezone columns** (Option B) | **Correctly deferred.** There is no relocation case in a single-timezone India V1, and the `ShiftVersion` pattern remains in the codebase to copy when one appears |

> ## RECOMMENDATION — endorses the plan
>
> **Option A, unchanged**, with three specifications the plan leaves implicit:
>
> 1. **`_assert_timezone_change_allowed` must become `async`** (`SR-08`) — it needs an existence
>    query. Its one call site at `:659` becomes `await`.
> 2. **The predicate is "any computed `attendance_day` exists for the affected scope" — not "the
>    company is live."** For a **branch** timezone change the scope is *the branch's currently- and
>    previously-assigned employees*, which requires walking `EmployeeAssignment` history, not just the
>    current roster. **An employee who has since transferred away still has historical days computed
>    in that branch's zone.** Getting this wrong makes the branch guard leaky in exactly the case it
>    exists for.
> 3. **The `CLOSED`-period refusal is absolute** and is checked **before** the `TRIAL` hatch, not
>    after. A `TRIAL` company with a closed period is not a contradiction — it is a trial that ran a
>    payroll cycle.

## 13.5 `SR-11` — the gap the plan does not close

A backdated shift-version publish carrying a **different timezone** rewrites the resolved zone for
every day from its `effective_from` onward, on the next recompute. Nothing checks whether that range
overlaps a `CLOSED` period.

| Dimension | Assessment |
|---|---|
| **Impact in India V1** | **Low.** Every India tenant resolves to the same zone, so a timezone *change* via this route is near-hypothetical. The mechanism is identical for **every other** versioned input, though — and a backdated *policy* publish changing `grace_in_minutes` over a closed period is entirely plausible |
| **Is it in scope?** | **The timezone aspect, yes. The general aspect, no** — it belongs to the policy-versioning workstream |
| **Cheapest correct control** | Refuse a version publish whose `effective_from` falls inside a `CLOSED` period, by calling `_ensure_date_open` (which already exists, `attendance/service.py:1915`) from the publish paths. One call, one error code |

> **Recommendation:** add the `CLOSED`-period check to shift-version publish **in Phase 2, alongside
> the timezone validator**, since both touch `_validate_and_derive_for_publish` and both are about
> the same invariant. **Record the general case as debt** (`SR-11-GEN`) against the policy-versioning
> workstream; do not expand this programme to cover it.

---

# 14. CROSS-MIDNIGHT BREAKS — `F-05`

## 14.1 Root cause — VERIFIED

```python
# calculation.py:582-601
tz = ZoneInfo(tz_name)
...
gap_start_local = gap_start.astimezone(tz).time()        # ← UTC → local FIRST. This order is CORRECT (PC-15)
for shift_break in shift_breaks:
    if shift_break.break_kind == "FIXED_WINDOW" and shift_break.start_time is not None:
        if (shift_break.start_time <= gap_start_local <= (shift_break.end_time or shift_break.start_time)):
            best = shift_break; break
    elif shift_break.break_kind == "FLEXIBLE_DURATION" and shift_break.window_start is not None:
        window_end = shift_break.window_end or shift_break.window_start
        if shift_break.window_start <= gap_start_local <= window_end:
            best = shift_break; break
is_paid = best.is_paid if best is not None else False     # ← unmatched ⇒ UNPAID
```

**A chained inequality on a `time` value assumes `start_time <= end_time`.** For `23:30–00:30`:

```text
time(23,30) <= time(23,45) <= time(0,30)
└──── True ────┘ └──── False ────┘        →  False  →  best = None  →  is_paid = False
```

**Structural cause:** `shift_break` is the one table in the schema with **no cross-midnight flag** —
unlike `shift_version.is_cross_midnight` and `shift_duty_block.crosses_midnight`, both of which exist
and are honoured.

## 14.2 `SR-01` — the plan's chosen fix regresses a working case

**Executed against the shipped `match_breaks`, `Asia/Kolkata`, 2026-09-15:**

| # | Break window | Gap starts | **Today** | Approach A<br>*(wrap-aware time-of-day)* | Approach B<br>*(UTC span from attendance date, roll end forward)* |
|---|---|---|---|---|---|
| 1 | `13:00–14:00` day | 13:15 | ✅ matched, paid | ✅ matched | ✅ matched |
| 2 | `23:30–00:30` | 23:45 | ❌ **unmatched** | ✅ matched | ✅ matched |
| 3 | `23:30–00:30` | 00:05 (D+1) | ❌ **unmatched** | ✅ matched | ✅ matched |
| 4 | **`01:00–02:00`** on a `22:00→06:00` shift | 01:15 (D+1) | ✅ **matched, paid** | ✅ matched | 🔴 **REGRESSES to unmatched** |
| 5 | `FLEXIBLE` window `23:00–01:00` | 23:30 | ❌ **unmatched** | ✅ matched | ✅ matched |
| 6 | `23:30–00:30`, gap at 22:15 | 22:15 | ✅ correctly unmatched | ✅ unmatched | ✅ unmatched |

### Why case 4 breaks under Approach B

A `01:00–02:00` break belongs to the **next** local day of a `22:00→06:00` shift. Approach B builds
`_local_to_utc(attendance_date, 01:00)` = **`D` 01:00 IST** — twenty-one hours *before* the shift
starts. Rolling the **end** forward does not help, because the **start** is the field on the wrong
day. The current time-of-day comparison gets case 4 right precisely *because* it is date-agnostic.

### Why case 4 is a real configuration, not a contrived one

`_interval_contains` ([`organisation/service.py:2055-2067`](../../apps/api/src/hrms/modules/organisation/service.py#L2055))
validates break containment by **projecting onto a 1440-minute clock with the shift's `start_time` as
the origin** — it is explicitly wrap-aware. For a `22:00→06:00` shift, a `01:00–02:00` break projects
to offset 180, duration 60, against an outer duration of 480: **valid and publishable.** A 01:00 meal
break on a night shift is the most ordinary night-shift configuration there is.

### The remediation spec's objection to Approach A does not hold for this codebase

`ATTENDANCE_TIMEZONE_DECISION_AND_REMEDIATION.md` §12.6 rejects Approach A because it *"infers the
midnight cross from the column values — the exact inference pattern `is_cross_midnight` exists to
avoid."* **VERIFIED, that is not what `is_cross_midnight` is:**

```python
# organisation/service.py:2069-2087  _derive_cross_midnight
if shift_type == "FIXED":
    if start_time is None or end_time is None or start_time == end_time: return False
    return end_time < start_time          # ← the flag IS exactly this inference, computed once
```

The flag is that inference, evaluated at publish and stored. And `_interval_contains` performs the
same wrap inference on break times **already, in production, today.** Approach A is consistent with
**two** existing precedents; Approach B is consistent with neither and breaks a working case.

## 14.3 The minimal fix

> ## RECOMMENDATION — **overrides the plan's §10.4 and remediation §12.6**
>
> **Approach A: make the comparison wrap-aware. Do not rebuild it around UTC spans.**
>
> ```text
> For each window (start, end) — FIXED_WINDOW (start_time, end_time)
>                              or FLEXIBLE_DURATION (window_start, window_end):
>
>     if end is None or end == start:   match only start == gap_start_local   (a point, not 24h)
>     elif start <= end:                match start <= gap_start_local <= end        (unchanged)
>     else:                             match gap_start_local >= start
>                                        OR  gap_start_local <= end                 (the wrap)
> ```
>
> **Properties:**
>
> | | Approach A | Approach B (the plan's) |
> |---|---|---|
> | Passes all six scenarios | **✔** | ✘ — fails case 4 |
> | Signature change to `match_breaks` | **none** | required at **both** call sites (`:1119`, `:1322`) |
> | Preserves the `UTC → local` order (`PC-15`) | **✔ untouched** — line 586 is not modified | ✔ but rewritten |
> | Lines changed | **~6, in one function** | ~25 plus two call sites |
> | Handles DST inside a break window | Irrelevant for India; unchanged from today | Handled "for free" — **a benefit with no India tenant** |
> | Consistent with existing code | **✔ `_interval_contains`, `_derive_cross_midnight`** | ✘ |
>
> **Two constraints carried over from the plan and endorsed:**
>
> 1. **Do not touch line 586** (`gap_start.astimezone(tz).time()`). That is `PC-15`; keep the C14
>    regression guard even though India has no DST — it protects the **order**, which is what is
>    actually at risk.
> 2. **Do not bundle `ATT-009`** (a gap that *starts* outside a window and *ends* inside it is
>    unmatched even on a day shift). Fixing it would change computed attendance for **day** shifts,
>    widening the blast radius of a night-shift fix. Out of scope; keep it as `ATT-009`.
>
> **`R-SB-01` — adding `shift_break.crosses_midnight`** to make the roll *declared* rather than
> inferred: **still worth doing, still P2, still after Phase 4 is stable.** Approach A makes it
> optional hardening rather than a prerequisite.

## 14.4 Side effects and blast radius

| Dimension | Assessment |
|---|---|
| **Direction** | **Always in the employee's favour.** The bug only ever under-credits: unmatched → unpaid → `worked_minutes` ↓ → `paid_day_fraction` ↓ → OT suppressed |
| **Population** | Only days with a punched gap starting inside a **midnight-spanning** break window. Day shifts are untouched — case 1 is a regression guard, not a change |
| **Over-matching risk** | The wrap branch is reachable **only** when `end < start`, so no currently-matching gap can start matching a *different* break. Case 6 is the guard |
| **`is_excess`** | Once matched, `max_minutes` applies — a 45-minute gap against a `max_minutes=30` break becomes `is_excess=True` where it previously was not. **This is the one sub-case that can move a result against the employee**, and it is correct: an excess break was always meant to be flagged. Call it out in the change notice |
| **Recompute** | Computed attendance changes for affected days. Recompute **open** days only, deliberately, with notice, after the §19.4 snapshot |

## 14.5 Regression tests

| # | Scenario | Assert | Tier |
|---|---|---|---|
| 1 | `23:30–00:30`, gap 23:45 | matched, `is_paid=True` | 1 — pure |
| 2 | `23:30–00:30`, gap 00:05 | matched, `is_paid=True` | 1 |
| 3 | `13:00–14:00`, gap 13:15 | still matched — **day-shift regression guard** | 1 |
| 4 | **`01:00–02:00` on a `22:00→06:00` shift, gap 01:15** | **still matched — `SR-01` guard. Mandatory.** | 1 |
| 5 | `FLEXIBLE` `23:00–01:00`, gap 23:30 | matched | 1 |
| 6 | `23:30–00:30`, gap 22:15 | **unmatched — no over-matching** | 1 |
| 7 | `23:30–00:30`, `max_minutes=30`, 45-min gap | `is_excess=True` — **closes matrix `I4`** | 1 |
| 8 | `start_time == end_time` | point match only; **never a 24-hour window** | 1 |
| 9 | End-to-end `22:00–06:00` with a paid `23:30–00:30` break | `worked_minutes` includes the break; `paid_day_fraction = 1.00` | 1 |
| 10 | Matrix `C14` — ambiguous `01:10` local vs. `01:00–01:30`, London fall-back | still matched, paid — **`PC-15` conversion-order guard** | 1 |

**All ten are pure-function tests with no database.** The engine's purity (`PC-12`) makes this the
cheapest P0 in the programme to prove.

---

# 15. UI TIMEZONE

## 15.1 Every attendance-related surface — VERIFIED audit

**Formatter call sites: 25 across 7 files** (`SR-12` corrects the plan's 24 / 9).

| Screen | File | Calls | Current timezone | Correct timezone (V1) | Required change |
|---|---|---|---|---|---|
| Attendance day detail | `app/app/attendance/[id]/page.tsx` | **7** | **Viewer's browser** | `Asia/Kolkata` | Pass tz; label `IST`; **dual-zone header** (`DEC-TZ-08` Option C, this page only). The zone is **already displayed** as a subtitle at `:109` — `{day.attendance_date} — {day.timezone}` — and no formatter uses it |
| Regularization detail | `app/app/regularizations/[id]/page.tsx` | **6** | Viewer's browser | `Asia/Kolkata` | Pass tz; label |
| Leave application detail | `app/app/leave-applications/[id]/page.tsx` | **4** | Viewer's browser | `Asia/Kolkata` | Pass tz; label |
| Attendance period detail | `app/app/attendance-periods/[id]/page.tsx` | **3** | Viewer's browser | `Asia/Kolkata` | Pass tz; label |
| Overtime detail | `app/app/overtime/[id]/page.tsx` | **2** | Viewer's browser | `Asia/Kolkata` | Pass tz; label |
| Employee attendance panel | `components/attendance/employee-attendance-panel.tsx` | **2** | Viewer's browser | `Asia/Kolkata` | Pass tz; label. **Also `NEW-02` at `:78`** |
| Leave balances | `app/app/leave-balances/page.tsx` | **1** | Viewer's browser | `Asia/Kolkata` | Pass tz; label |
| Attendance list / overtime / regularizations / rosters / leave-applications **list** pages | 5 files | — | — | `Asia/Kolkata` | **`todayIso()` → `businessToday(tz)`** — 9 invocations (§5.4) |
| Create-period dialog | `components/attendance-period/create-period-dialog.tsx` | — | **UTC date → persisted** | `Asia/Kolkata` | **`SR-06`** — 4 invocations |
| Policy resolution | `app/app/policy-resolution/page.tsx` | — | UTC date, via a **duplicate** helper at `:27` | `Asia/Kolkata` | **`NEW-05`** — delete the duplicate |
| Punch entry dialog | `components/attendance/punch-entry-dialog.tsx` | — | `nowForDatetimeLocal()` at `:33-37` — **browser clock into an editable field** | n/a (self) / `IST` (admin) | **`F-02`** — Phase 1 split (§11) |

## 15.2 The mechanism

```ts
// format.ts:14-25 — VERIFIED
export function formatClockTime(iso) { return new Date(iso).toLocaleTimeString(undefined, {...}); }
export function formatDateTime(iso)  { return new Date(iso).toLocaleString(undefined, {...}); }
//                                                          ^^^^^^^^^
//                     `undefined` locale ⇒ BOTH locale AND timezone come from the browser.
```

`format.ts`'s own header states these helpers are *"never used for calculation, only for rendering
values the backend already computed"* — **and `todayIso()` sits in the same file and is used for a
calculation** (§5). The comment should be corrected in the same change, or it will mislead the next
reader exactly as it misled `TZ-07`/`F-09`.

## 15.3 Target for V1

> **No viewer-specific timezone rendering for attendance. `Asia/Kolkata`, always labelled `IST`.**

| Item | Specification |
|---|---|
| Signature | `formatClockTime(iso, tz)` / `formatDateTime(iso, tz)` — **`tz` required, not optional with a default.** An optional parameter is a call site nobody updates |
| Source of `tz` | `attendance_day.timezone` where an attendance day exists (**already on the wire**, `schemas.py:1391`); the **company** timezone for non-attendance timestamps — `created_at`, audit entries, notification times — which have no resolved zone of their own |
| Label | Always visible. `09:05 IST`. **Never render a time computed in one zone without naming that zone** |
| Dual-zone | **Day-detail page only.** Dense lists and grids stay single-zone |
| Company timezone on the client | Returned in the session/bootstrap payload (Phase 3.5). **Required by both `businessToday()` and the formatters — ship once, use twice** |
| `todayIso()` | **Deleted**, not deprecated, so it cannot be re-imported by autocomplete |

## 15.4 Why literal compliance with `DEC-010` would be a second bug

`DEC-010` (**LOCKED**) names `company.timezone` as the single source of truth for rendering. `WD-06`
(**also LOCKED**) already superseded that for *computation* with `ShiftVersion > Branch > Company`.
Rendering a Dubai-branch day in a Kerala company's zone would display times in a zone the figures were
**not** computed in.

> **For India V1 the two coincide**, so the amendment is free today and correct later. But it is an
> amendment to a **LOCKED** decision and engineering may not make it — **`CD-3`** (§22).

## 15.5 Tests

| # | Test | Tier |
|---|---|---|
| 1 | A fixed instant renders as `09:05 IST` with the runner at `TZ=America/New_York` | 6 — vitest |
| 2 | The `IST` label is present on every attendance time | 6 |
| 3 | `businessToday()` at 02:00 IST returns the **IST** date, not the UTC one | 6 |
| 4 | Self-punch dialog renders **no** time input | 6 |
| 5 | Admin dialog requires a reason | 6 |
| 6 | A failed punch POST shows a non-dismissible "not recorded" error and persists **nothing** (`P-08`) | 6 |
| 7 | `create-period-dialog` pre-fills the **IST** date at 02:00 IST (`SR-06`) | 6 |

**All seven are blocked on `NEW-06`** — there is no CI job running vitest. §20.

---

# 16. RAW PUNCH vs. CALCULATED ATTENDANCE

## 16.1 The model as shipped — VERIFIED

```text
RAW EVENT                        punch                         append-only, never UPDATEd (WD-11)
  punch_time     TIMESTAMPTZ     the instant                   models.py:456
  created_at     TIMESTAMPTZ     receipt; set by the app at service.py:2359,
                                 overriding server_default=func.now()   models.py:466
  direction / source / recorded_by_user_id / idempotency_key / reference
  raw_payload    JSONB           DECLARED, NEVER WRITTEN       models.py:464  ← F-18
        │
        ▼  pulled by attendance_date's window — the date selects the punches,
           never the reverse (§10)
CALCULATION                      calc.evaluate_day()           PURE — no I/O (PC-12)
        │
        ▼
POLICY-ADJUSTED RESULT           attendance_day                FULL replacement (WD-10)
  attendance_date DATE · timezone VARCHAR(64) NOT NULL
  scheduled_start/_end, actual_first_in/_last_out  TIMESTAMPTZ
  worked/late/early/ot minutes · status · paid_day_fraction · lop_fraction
  shift_version_id, attendance_policy_version_id, … FK   ── PROVENANCE (§13.1)
  computation_snapshot  JSONB                            ── the input/intermediate trace
```

## 16.2 Does the schema preserve enough information?

| Question | Answer |
|---|---|
| Is the raw instant recoverable after calculation? | **Yes.** `punch` is append-only and is never rewritten. `calculate()` replaces only `attendance_day` |
| Is a policy-adjusted value ever written back over a raw punch? | **No.** `apply_rounding` ([`calculation.py:637`](../../apps/api/src/hrms/modules/attendance/calculation.py#L637)) has **zero call sites** (`F-04`), and its own docstring requires operating on a *copy*. When `DEC-TZ-06` is eventually decided, **`P-15` must be enforced by a test asserting `punch.punch_time` is byte-identical in the DB before and after**, not by a comment |
| Can a computed day be reconstructed? | **Partly.** The snapshot + FKs allow reconstruction; but because recompute **re-resolves** rather than **re-reads** (§13.1), reconstruction is a manual forensic act, not a system capability |
| Is the receipt instant distinguishable from the event instant? | **Today: by convention only.** `created_at` is the request time because `service.py:2359` sets it, and for nothing else |
| Is submission evidence captured? | **No.** `raw_payload` is never written, though IP and User-Agent are already available at `router.py:784-785` and already flow to the audit record |

## 16.3 What must change, and what must not

> **No new column is required for V1.** Two changes, both using existing columns:

| # | Change | Why it is not a new column |
|---|---|---|
| 1 | **Write `punch.raw_payload`** — `{user_agent, client_ip, client_version, submitted_offset}` | The column exists (`models.py:464`). `submitted_offset` is only meaningful on the **on-behalf** path, where a client time is still accepted; on the self path it is absent by construction |
| 2 | **Make `created_at`'s role explicit** — a code comment plus a test asserting the application sets it and the DB default never wins | The column exists. Plan §3.2's deferral of a separate `request_time` is **endorsed**; this test is the condition that makes the deferral safe |

**Deliberately NOT added:**

| Candidate | Why not |
|---|---|
| `punch.request_time` | Under server-authoritative self-punch it equals `punch_time` by construction. Split it when a device or offline path ships (`DEC-TZ-15`) — the trigger is recorded |
| `attendance_day_history` | A real answer to *"what did this day say when it was approved?"*, but **out of scope**, and the period lock is the V1 answer |
| A rounded-punch column | `DEC-TZ-06` is open. Adding storage for an undecided policy pre-commits it |

## 16.4 One PII condition

`raw_payload` captures IP and user-agent — **identifying data, on every punch, for every employee,
indefinitely.** `PII-2` retention sign-off is a **precondition** of Phase 1.6, not a follow-up. The
retention period must be stated before the first row is written, because retro-actively shortening
retention on a column that already has a year of data is a deletion project.

---

# 17. NIGHT OT — SEPARATING TIMEZONE FROM BUSINESS RULE

## 17.1 The two concerns, kept apart

| Concern | Status |
|---|---|
| **Timezone conversion** — does the engine convert a night shift's punches to the right instants? | ✅ **Correct and CODE-PROVEN.** Not in question. Cross-midnight attribution, spans and DST arithmetic are all proven |
| **Night-OT business rule** — *which* overtime minutes earn the night premium | ⚖️ **Open. `DEC-TZ-07` / `F-06` / `ATT-005`. Not invented here** |

## 17.2 Exactly what the code does today — VERIFIED

```python
# calculation.py:1237
is_night = shift.is_cross_midnight
```

```python
# attendance/service.py:3048-3049
# night_window_start / night_window_end ARE loaded into OvertimePolicyInputs …
# … and calculation.py NEVER READS THEM.
```

| Configuration | Documented intent | Actual behaviour |
|---|---|---|
| `night_ot_mode = "SHIFT_FLAG"` | Night OT iff the shift is flagged cross-midnight | ✅ implemented |
| `night_ot_mode = "WINDOW"` | Night OT iff OT minutes fall inside `night_window_start`–`night_window_end` | ❌ **not implemented — behaves identically to `BOTH`** |
| `night_ot_mode = "BOTH"` | Either condition | ❌ collapses to `SHIFT_FLAG` |

**Consequence:** a **day** shift extending into the configured night window is **never** classified
`NIGHT`, so it never earns the night multiplier. A three-valued enum is selectable in the UI and two
of its values are inert. **Wrong multiplier → wrong money.**

## 17.3 What requires client approval

| Item | Owner |
|---|---|
| Should `night_ot_mode` be honoured as designed, or should `WINDOW`/`BOTH` and the two window fields be **withdrawn** from the UI? | **CLIENT — `CD-6`** (§22) |
| If honoured: does a **day** shift running into the night window earn the night rate for those minutes only, or for the whole OT block? | **CLIENT** — this is a pay rule, not an implementation detail |
| If honoured: recompute already-computed open days for affected tenants? | **CLIENT** — it changes pay |

## 17.4 Instruction for this programme

> **Do not implement, do not withdraw, do not "tidy up" `night_ot_mode` in Phases 0–7.**
> `calculation.py:1237` is inside the file §5.2 of the plan protects. Touching `detect_overtime` or
> `classify_ot_day` while fixing `match_breaks` would blend a **proven-correct** change with an
> **undecided pay policy** in one diff, and make the Phase-4 recompute impossible to attribute.
>
> **One thing is safe and worth doing now:** document in `ATTENDANCE_MASTER_RULE_MATRIX.md` that
> `night_window_start`/`_end` are **currently inert**, so an HR user configuring them is not silently
> misled while the decision is pending. **That is a documentation change, and it needs no approval.**

---

# 18. RECONCILIATION — WHY ATTENDANCE ROWS DO NOT EXIST

## 18.1 The trace — VERIFIED

```text
PUNCH CREATED      PunchService.record_punch      service.py:2299-2383
                   inserts the punch, writes an audit entry, returns
                          │
                          ▼
                   ( N O T H I N G )          ← no calculation is triggered, in-process or queued
                          │
CALCULATION        AttendanceDayService.calculate  service.py:2483
                   reachable ONLY from:
                     POST /attendance/days/calculate        router.py:858   (ATTENDANCE.VIEW_ALL)
                     POST /attendance/days/{id}/recompute   router.py:891   (ATTENDANCE.RECOMPUTE)
                          │
BACKGROUND JOBS    core/celery_app.py beat_schedule — 4 entries, ALL leave.*
                   VERIFIED: no attendance.* task exists anywhere in src/
                          │
RECONCILIATION     none          RETRIES none          FAILURE HANDLING none
```

**Therefore:** an employee who punches in and out has **no `attendance_day` row** until a human with
`ATTENDANCE.VIEW_ALL` presses a button. A period cannot be finalized. **Payroll has no input at all.**
(`F-14` / `PAY-001`, 🔴 P0.)

## 18.2 The two assets to reuse — do not invent

| Asset | Evidence |
|---|---|
| **Celery already runs on IST wall-clock** | `celery_app.py:18-19` — `timezone=settings.app_timezone_default` (= `Asia/Kolkata`), `enable_utc=True`. Beat crontabs already fire on India local time |
| **A two-tier per-tenant fan-out pattern is established** | [`modules/leave/tasks.py`](../../apps/api/src/hrms/modules/leave/tasks.py) — a no-arg Beat entrypoint enumerates active companies (`status in ('TRIAL','ACTIVE')`) and dispatches one per-company task through `session_scope(company_id=…)`, keeping RLS intact |

## 18.3 `SR-05` — a defect in that pattern that must be fixed first

**VERIFIED by execution.** All three Beat-scheduled leave entrypoints fire between 00:00 and 02:00 IST
and then compute `as_of = datetime.now(UTC).date()`:

| Beat entry | Fires (IST) | = UTC instant | `now(UTC).date()` | IST date | Skew |
|---|---|---|---|---|---|
| `leave-run-monthly-accrual` (1st of month) | **01:00** 1 Oct | `2026-09-30T19:30Z` | **2026-09-30** | 2026-10-01 | **YES** |
| `leave-run-comp-off-expiry-sweep` | **01:30** | `…T20:00Z` | previous day | today | **YES** |
| `leave-run-year-end-sweep` | **02:00** | `…T20:30Z` | previous day | today | **YES** |
| `leave-run-comp-off-credit-sweep` (hourly) | 00:00–05:00 runs | — | previous day | today | **YES for 6 of 24 runs** |
| **Proposed `attendance.run_daily_calculation`** | **09:30** | `2026-10-01T04:00Z` | 2026-10-01 | 2026-10-01 | **no** ✅ |

> **The monthly accrual scheduled for the 1st of the month actually runs with `as_of` = the last day
> of the previous month.** `leave/tasks.py:36`, `:85`, `:110`.
>
> **This is the same `business_today()` defect as `TZ-06`, in the one place where it is guaranteed to
> fire in the wrong band every time** — because the schedule deliberately puts it there.
> **It must be added to Phase 3** (`P3-04`), and it must land **before** Phase 6 copies the pattern.
>
> **The plan's 09:30 IST choice is correct and is above the 05:30 boundary** — but for a reason the
> plan does not state, and therefore for a reason a future maintainer could unknowingly discard by
> moving the job earlier "so results are ready by 09:00."  **Record the constraint in the task
> docstring: any attendance job scheduled before 05:30 IST must use `business_today()`, never
> `datetime.now(UTC).date()`.**

## 18.4 The smallest production-safe architecture

> ## RECOMMENDATION — endorses the plan, with three additions
>
> ```text
> 1. IMMEDIATE — after a successful punch insert, best-effort calculate for the resolved date.
>    - Non-blocking and failure-tolerant: a calculation failure must NEVER fail the punch write.
>      A punch is a FACT; a calculation is a DERIVATION. Losing the fact is unacceptable.
>    - Idempotent by construction — calculate() is full-row replacement (WD-10).
>
> 2. RECONCILIATION — modules/attendance/tasks.py  (NEW FILE, on the leave/tasks.py pattern verbatim)
>    attendance.run_daily_calculation           Beat entrypoint, no args
>      └─ enumerate active companies
>         └─ attendance.calculate_company(company_id)
>              for each employee with an active employment,
>              for each date in [business_today(IST) - N, business_today(IST)]:
>                  calculate(...)  — skipping locked days and CLOSED periods
>
> 3. SCHEDULE — crontab(minute=30, hour=9) under the existing Asia/Kolkata celery timezone.
>    09:30 IST: after the outer edge of a 22:00-06:00 shift's +2h pad (08:00 IST),
>    before the working day's reviews begin, and above the 05:30 UTC-date boundary (SR-05).
> ```
>
> **Addition 1 — the job must use `business_today()` from day one** (`SR-05`), and its docstring must
> say why.
>
> **Addition 2 — the immediate calculate must not become a second `NEW-02`.** It must derive the
> attendance date **server-side** from the punch and the resolved shift, never from a client-supplied
> value. Note the circularity flagged in §9.6: resolving the true attendance date requires shift
> resolution. **For the immediate path, using the punch's IST civil date is acceptable** — the nightly
> trailing-window job corrects any cross-midnight mis-attribution within hours, which is precisely why
> the trailing window exists.
>
> **Addition 3 — the orphan-punch report must handle `SR-14`.** Four window shapes exist, not one
> (§10.4). A punch belonging to an employee with **no resolved shift** falls under
> `calendar_day_window_utc` — a full local civil day with **no pad** — and must not be flagged as an
> orphan by ±2h logic.
>
> **Do not build:** a new job framework, a message bus, or per-punch queueing. The `leave/tasks.py`
> pattern is sufficient, proven in production, and already RLS-correct.
>
> **`OPS-006` — Celery Beat has no leader election.** Duplicate firing is possible by design. The
> job's idempotency makes it survivable. **It must be in the runbook, not discovered.**

---

# 19. CONCURRENCY

## 19.1 Verified state

| Property | Finding | Evidence |
|---|---|---|
| Isolation level | **READ COMMITTED** — the PostgreSQL default | `SHOW default_transaction_isolation` → `read committed`. **No `isolation_level` or `execution_options` anywhere in `core/db/session.py`** (VERIFIED by grep) |
| Session `TimeZone` | `UTC` | `SHOW TimeZone` → `UTC` |
| Row lock on `attendance_day` | **NONE** | **`with_for_update` appears nowhere in `src/`** (VERIFIED by grep) |
| `attendance_day` uniqueness | `UNIQUE (company_id, employee_id, attendance_date)` | `pg_constraint`, VERIFIED |
| `punch.source` DB CHECK | 7 values incl. `REGULARIZATION`, `DEVICE` | `pg_constraint`, VERIFIED |
| Punch idempotency | Partial unique index on `idempotency_key`, **only when the client supplies one** — the web UI never does | `service.py:2332-2338` |
| Duplicate collapsing | `calculation.collapse_duplicate_punches`, `duplicate_punch_window_seconds` default 60 | `models.py:109` — **the load-bearing dedup mechanism**, TEST-PROVEN |

## 19.2 The four candidate races, evaluated against real trigger paths

| # | Race | Real today? | After Phase 6? | Verdict |
|---|---|---|---|---|
| **1** | **Simultaneous punches** — two `POST`s for one employee arriving together | **Not a correctness problem.** `punch` is append-only with no uniqueness on `(employee, time)`; both rows are inserted and `collapse_duplicate_punches` merges them at calculation time. **This is the designed behaviour** | unchanged | **No lock. Do not add one** |
| **2** | **Duplicate request** — a double-clicked button | Same as 1, plus `idempotency_key` when supplied | unchanged | **No lock.** *(Worth a UI-level submit guard; not a data problem)* |
| **3** | **Concurrent recompute** on one employee-date | **Latent.** Two humans pressing Recompute. Rare | 🔴 **REAL** — the nightly job and an interactive recompute collide by construction. **Phase 6 creates this race** | **`SELECT … FOR UPDATE` — required, in Phase 6, with the job** |
| **4** | **Torn configuration read** (`TZ-09`) — a timezone `UPDATE` commits between two `SELECT`s inside one `_build_calculation_input` | Latent, millisecond window, silent | unchanged | **Closed as a free side effect of Phase 2's guard**: if the timezone cannot change while computed attendance exists, the concurrent `UPDATE` cannot occur |

> **The plan is right that a lock must not precede the concurrency path.** Race 3 does not meaningfully
> exist until the scheduled job does. Adding `FOR UPDATE` in Phase 1 or 2 would be locking against a
> collision that cannot happen yet, while adding deadlock surface immediately.

## 19.3 Recommendation

> **Exactly one lock, added in exactly one place, in Phase 6, with the job that creates the need.**
>
> ```text
> AttendanceDayService.calculate():
>     SELECT ... FROM attendance_day
>      WHERE company_id = :c AND employee_id = :e AND attendance_date = :d
>        FOR UPDATE                                   ← acquired BEFORE _build_calculation_input
> ```
>
> **Four constraints:**
>
> 1. **Acquire before reading configuration, not after.** Taking it after `_build_calculation_input`
>    serialises the write but not the read, leaving race 4 open for inputs the Phase-2 guard does not
>    cover.
> 2. **Lock ordering must be reviewed against `AttendanceDayRepository.bulk_lock`**
>    ([`repository.py:1222`](../../apps/api/src/hrms/modules/attendance/repository.py#L1222)), which
>    period close uses to lock a whole range. A range lock and a single-row lock taken in opposite
>    orders is the classic deadlock. **`IR-10` in the plan; this is the concrete target.**
> 3. **`FOR UPDATE` on a row that does not exist locks nothing.** The first calculation for an
>    employee-date has no row. The `UNIQUE` constraint remains the backstop for that case — the
>    insert path must handle `IntegrityError` as a retry, not as an error.
> 4. **Do not raise the isolation level.** `REPEATABLE READ` would close race 4 generally, but it
>    imposes serialization-failure retries and this session is request-scoped and shared. **Phase 2's
>    guard closes race 4 at zero cost.** Revisit only if the mutable-configuration surface grows.
>
> **Do not add locking anywhere else.** Races 1 and 2 are handled by design and adding locks there
> would serialise the hottest write path in the module to solve a problem that does not exist.

## 19.4 Tests

| # | Test | Tier |
|---|---|---|
| `J1` | `SHOW default_transaction_isolation` matches what the code assumes — **fails loudly if a deploy changes it** | 5 |
| `J2` | A timezone `UPDATE` committing between two `SELECT`s in one `_build_calculation_input` → **refused by the guard**, or the calculation is internally consistent. Never torn | 5 |
| `J3` | The nightly job and an interactive recompute collide on one employee-date → deterministic result, no lost update, no duplicate row | 5 |
| `J4` | **First-ever calculation under concurrency** — two callers, no existing row → exactly one row, no `IntegrityError` escaping to the client | 5 |

`J4` is **not in the plan** and is the case constraint 3 above describes.

---

# 20. CI GATE

## 20.1 Current state

Established in §8.2. In one line: **one job, no database, no migrations, no frontend, no `TZ`, and
`pytest` collects 802 tests that cannot pass because there is no skip guard.**

## 20.2 The minimum gate

Restated as an acceptance checklist. **Fewer than all nine is not a gate.**

```text
[ ] 1  postgres:16-alpine + redis:7-alpine as `services:`, health-checked
[ ] 2  infra/docker/postgres/init/*.sql applied EXPLICITLY
         (a services: container does NOT run docker-entrypoint-initdb.d)
[ ] 3  DATABASE_URL points at hrms_app — the NOBYPASSRLS role — NOT hrms   ← SR-10
[ ] 4  alembic upgrade head runs before the tests
[ ] 5  TZ: UTC in the job env                                              ← R-TZ-02b
[ ] 6  a `web` job: npm ci -> npm run lint -> npm test                     ← NEW-06
[ ] 7  BOTH jobs are REQUIRED STATUS CHECKS on main  (a repo setting, not a file)
[ ] 8  a test that PROVES the gate works: a deliberate cross-tenant read is DENIED in CI
[ ] 9  the "Unit tests" step is renamed, or split, so the name matches what it runs
```

## 20.3 Why items 3 and 8 are non-negotiable

`infra/docker/postgres/init/002_app_role.sql:19-20` creates `hrms_app` as
`NOSUPERUSER … NOBYPASSRLS`. `ci.yml` connects as `hrms` — the schema **owner**. A table owner is not
subject to its own RLS policies unless `FORCE ROW LEVEL SECURITY` is set on every table.

> **Provisioning PostgreSQL while leaving `DATABASE_URL` at `hrms` would make every tenant-isolation
> test pass for the wrong reason — and pass *green*.** That is strictly worse than today, because
> today the tests visibly cannot run. **Item 8 exists because the only way to know item 3 was done is
> a test that fails when it was not.**

## 20.4 Sequencing consequence

> **`TST-001` is the true week-1 prerequisite for the entire programme.**
>
> Every integration test specified anywhere in this document — the timezone guard, period lock,
> concurrency, historical protection, `NEW-01`'s `E7` — is worthless **as a gate** until CI can run
> it. **Phase 7 must execute immediately after Phase 0, before any behavioural change lands.** The
> plan already says this (§13.3) and it is correct.
>
> **`IR-7` is the risk to plan for:** the first honest run will be red, and nobody knows how red.
> **Phase 0.4 must measure it before Phase 7 makes it a gate**, or Phase 7 becomes an open-ended
> bug-fixing project discovered mid-flight.

---

# 21. DATA CLEANUP

> **No data was modified. All figures below are read-only queries against the dev database on
> 2026-09-15.**

## 21.1 Inventory — VERIFIED

| Record type | Count (dev) | Risk | Migration required? | Repair strategy | Verification |
|---|---|---|---|---|---|
| **`company.timezone = 'Asia/Calcutta'`** | **3** — all `TRIAL`, **0** attendance days, **0** punches | 🟠 **A string invariant written as `== "Asia/Kolkata"` locks them out** (`IR-9`). Calculations are unaffected — the zones are identical | **No.** A guarded one-off `UPDATE`, not an Alembic revision | `DH-2`: `UPDATE company SET timezone='Asia/Kolkata' WHERE timezone='Asia/Calcutta' AND NOT EXISTS (SELECT 1 FROM attendance_day WHERE company_id=company.id)` — audited, old value in `audit_log` | Re-run the inventory: 0 rows. Confirm the 3 companies still authenticate and their setup progress is unchanged |
| **`company.timezone` outside `{Asia/Kolkata, Asia/Calcutta}`** | **0** | — | No | none | inventory |
| **`branch.timezone = 'UTC'`** | **11** — all named `HQ`, all under `Asia/Kolkata` companies named `W7/W8/W9 Live Demo/Verify`, `Acme …` | 🔵 **Dev/test residue.** Also the rows that prove WD-06 is exercised with a non-IST value | **No** | `DH-3`: **per-row decision, no blanket rewrite.** In **dev**: leave them — they are the non-IST arm of the `PC-01` regression surface. In **production**: each one is a genuine misconfiguration and must be reviewed individually **before** Phase 2's guard makes them immutable | Inventory per environment; sign-off on each production row |
| **`branch.timezone IS NULL`** | **79** | ✅ **Correct and intended.** `NULL` is the WD-06 "inherit from company" signal | **No** | none — **`NULL` must remain valid** | A test asserting `NULL` still falls through to company |
| **`shift_version.timezone = 'UTC'`** | **11** | 🔵 Same as branch, same reasoning | **No** | `DH-3` | as above |
| **`shift_version.timezone IS NULL`** | **7** | ✅ Correct — inherit | **No** | none | as above |
| **Invalid (non-IANA) timezone values** | **0 in dev** | 🔴 **`NEW-01` — but nothing currently validates `shift_version`, so this count is an accident of history, not of a control.** It can become non-zero at any time until §4 ships | **No** | `DH-1` must include `SELECT ... WHERE timezone IS NOT NULL AND timezone NOT IN (<available_timezones()>)` against **every** environment | The inventory script itself |
| **`attendance_day.timezone = 'UTC'`** | **10** — every existing row, all `attendance_date = 2026-08-10` | ✅ **Provenance. Do NOT backfill** — under `P-11` historical rows are evidence, not inputs | **No** | **none** | A test asserting no code path writes `attendance_day.timezone` except `calculate()` |
| **Naive timestamps in the DB** | **0 — structurally impossible** | ✅ Every attendance timestamp column is `TIMESTAMPTZ`; **no `timestamp without time zone` exists in the attendance schema** | **No** | none | Schema assertion test |
| **Punches** | **24**, `2026-08-10T09:00Z` … `T19:00Z` | 🔵 Test data | **No** | none | — |
| **Historical attendance affected by mutable timezone config** | **10 rows** — all computed at `UTC` under branches that could still be edited today | 🟠 **Exactly the `TZ-01` exposure.** Small in dev; **unknown in production** | **No** — the fix is the Phase-2 guard, not a data change | Inventory + freeze | `E2`/`E3` integration tests |
| **PRODUCTION data, all of the above** | **NOT VERIFIABLE HERE** | 🔴 **Unknown** | — | **`DH-1` against production is a hard precondition of Phase 2** | — |

## 21.2 Test-fixture coupling — the constraint on any India lock

**VERIFIED by grep over `apps/api/tests/`:**

| Literal | Occurrences | Consequence |
|---|---|---|
| `"UTC"` as a timezone | **15** — `test_calculation.py` ×11, `test_attendance_day.py` ×2, `test_shift_roster.py` ×1, `test_regularization.py` ×1 | **An India allow-list applied to `branch` or `shift_version` breaks 15 assertions across 4 files** |
| `"Asia/Kolkata"` | 5 | — |
| `"America/New_York"` / `"Europe/London"` | 1 each — **both only as arguments to `resolve_timezone`**, `test_calculation.py:86-99` | **Confirms `TZ-04`: zero DST evaluation tests exist** |
| `"Not/AZone"` | 1 — `test_registration_flow.py:452` | The **only** invalid-timezone test, and it covers **registration**, not `ShiftVersion` |
| `Asia/Calcutta` | **0** | The alias is untested anywhere |

> **This is the decisive argument for §4's Option B.** Restricting `ShiftVersion.timezone` to
> `Asia/Kolkata` (Option A) would require rewriting 15 fixtures in the same change, and would delete
> the non-IST arm the `PC-01` server-timezone-independence suite depends on. **Validating strictly
> while keeping IANA costs nothing and breaks nothing.**

## 21.3 Order of operations

```text
DH-1  read-only inventory, EVERY environment incl. production      ← Phase 0.6, hard precondition
   ↓
DH-3  per-row human decision on non-IST branch/shift rows in prod  ← Phase 2, before the guard
   ↓
§4    ShiftVersion IANA validator + alias canonicalisation on write
   ↓
DH-2  Asia/Calcutta → Asia/Kolkata, zero-attendance companies only ← audited, reversible
   ↓
§13   the timezone-change guard                                    ← LAST. It makes everything above
                                                                     immutable; anything not cleaned
                                                                     first stays wrong forever
```

> **The ordering is load-bearing.** Landing the guard before `DH-3` freezes every production
> misconfiguration permanently, and the only escape is the `TRIAL`/zero-days hatch, which a live
> tenant does not qualify for.

---

# 22. FINAL CLIENT DECISION LIST

**Only decisions that change business behaviour.** Everything that is purely an implementation choice
has been moved to §23. Six items. The plan listed six (`OD-1`…`OD-6`); this list **removes two that
are not business questions, adds two that are, and narrows `OD-1` substantially.**

| ID | Question | Why it matters | Recommended answer | Consequence if rejected |
|---|---|---|---|---|
| **`CD-1`** ⭐ | **May an employee's punch ever be refused because a payroll period has closed — or must the fact always be recorded and reconciled afterwards?** *(replaces and narrows `OD-1`)* | This is the only genuine business question inside `OD-1`. §9 proves the algorithm is derivable once this is answered: today's UTC basis **falsely rejects** an early-shift punch (destroying the fact, unrecoverably) and **falsely accepts** a late night-shift punch (inert, visible, recoverable). The two errors are **not** symmetric | **"Never refuse; always record and reconcile."** Implement the plan's Option B — accept when **either** the IST civil date or the previous IST civil date is open — **shipped together with the orphan-punch report**, which is what makes a false acceptance recoverable rather than silent. `calculate()` remains the unconditional backstop | If a closed period must hard-refuse writes, Option B is still the best approximation, but accept that **some genuine punches will be permanently lost at month boundaries** and give support a documented manual path. **Do NOT adopt the plain IST civil date — §9.4 proves it is worse than today for night shifts** |
| **`CD-2`** | **Should company registration accept only Indian timezones, and should an existing company admin be able to change theirs to a non-Indian one?** | `/register` is **public and anonymous** and currently accepts any of ~600 IANA zones with no country gate (`NEW-04`). The company timezone is the terminal fallback of WD-06 — the value every calculation lands on | **Yes to both.** A settings-driven allow-list of `["Asia/Kolkata"]`, applied at `/register` **and** `PATCH /company/profile`, canonicalising `Asia/Calcutta` **before** the check. Expansion becomes a configuration change, not a release | A non-India company is creatable by an anonymous visitor on an India-only product, and the India invariant holds only until someone edits their profile |
| **`CD-3`** | **May `DEC-010`'s rendering clause be amended to name the WD-06-resolved zone rather than `company.timezone`?** | `DEC-010` is **LOCKED**. Literal compliance would be a **second bug** — WD-06 already superseded `company.timezone` for computation, so rendering a branch-zone day in the company zone would show times in a zone the figures were not computed in | **Amend it.** For India V1 the two coincide, so the amendment is **free today and correct later** | Phase 5 either violates a locked decision or implements a knowingly wrong rendering rule. **Neither is acceptable; this cannot be deferred past Phase 5** |
| **`CD-4`** | **When should attendance be calculated automatically, and how many trailing days should each run re-check?** | **Nothing computes attendance today** (`F-14`/`PAY-001`). A period cannot be finalized and Payroll has no input at all. The trailing window is what absorbs late punches, approved regularizations, and cross-midnight days incomplete at the previous run | **09:30 IST daily, trailing 3 days.** 09:30 is after the outer edge of a `22:00→06:00` shift's pad (08:00 IST) and before reviews begin. Every run is idempotent, so a repeated or missed run costs nothing | Without it, no attendance exists unless a human presses a button, and **no downstream payroll work can be verified at all.** A shorter window risks missing late regularizations; a longer one costs only compute |
| **`CD-5`** | **May an HR administrator enter an on-behalf punch for any past date inside an open period — including one three months old — or must there be a tighter limit?** *(new — raised by `SR-04`)* | The plan mandates a "policy-driven" backdating window for on-behalf punches. **No such configuration field exists** (`AttendancePolicyVersion` has none; `max_backdated_days` belongs to the regularization policy), and the plan separately states no migration is required | **No tighter limit in V1.** Bound it to "not in the future, and not in a `CLOSED` period" — an already-existing, already-tested control that needs no new field and no default nobody has chosen | A tighter limit means **a schema migration**, a new per-tenant default, and a correction to the plan's "no migration required" claim. It is a legitimate requirement — but it must be recognised as a later phase, not smuggled into Phase 1 |
| **`CD-6`** | **Should `night_ot_mode`'s `WINDOW` and `BOTH` values be implemented, or withdrawn from the product?** | `night_window_start`/`_end` are configurable, validated, persisted and **read by nothing**; `is_night = shift.is_cross_midnight` is the only rule implemented. A **day** shift running into the configured night window never earns the night premium. **Wrong multiplier → wrong money** | **Decide separately from this programme; implement neither here.** Until then, **document the fields as inert in the rule matrix** so an HR user configuring them is not silently misled | HR continues to configure a setting that does nothing, and believes it works. **Silent no-op configuration is worse than absent configuration** |

## 22.1 Decisions the plan escalated that this review does **not**

| Plan ID | Why it is not a client decision |
|---|---|
| **`OD-2` punch rounding** (`DEC-TZ-06`) | **Not a decision for *this* programme.** It is deferred with a trigger, nothing in Phases 0–7 touches `apply_rounding`, and asking now invites a "yes" that pulls an attendance-changing recompute into a timezone remediation. **Revisit as its own workstream.** The only thing needed now is the documentation note in `CD-6`'s shape |
| **`OD-4` the ±2h punch pad** (`DEC-TZ-16`) | **Premature.** The pad's failure is currently **invisible** — an orphaned punch produces no error, no flag, no report. **Nobody, client included, can judge whether ±2h is right while the failure cannot be observed.** Ship the orphan report (which changes no computed value and needs no approval), collect three months of data, **then** ask |
| **`OD-6` third-party punch integrations** | **Not a decision — a fact to establish.** §15.3 of the plan is right that the repository cannot answer it. It is a **Phase 0.9 task** against production access logs, not a question for a decision register |

## 22.2 Dependency order

```text
CD-1  (period-lock basis)   ──►  blocks Phase 3.10 only. Everything else in Phase 3 proceeds.
CD-2  (registration gate)   ──►  blocks Phase 2.5 / 2.6.
CD-3  (amend DEC-010)       ──►  blocks Phase 5.6. Phases 5.1–5.5 proceed regardless —
                                 for India V1 both readings resolve to Asia/Kolkata.
CD-4  (schedule + window)   ──►  blocks Phase 6.2 / 6.3.
CD-5  (on-behalf backdating)──►  blocks NOTHING if the recommendation is accepted;
                                 becomes a MIGRATION + a later phase if rejected.
CD-6  (night OT)            ──►  blocks NOTHING. Deferred with a trigger.

NOT blocking anything:  punch rounding · ±2h pad width · geofencing ·
                        DST policy · employee-level timezone · offline/mobile
```

> **Four decisions gate work: `CD-1`, `CD-2`, `CD-3`, `CD-4`.** Phases 0, 1, 4 and 7 — which contain
> **five of the eight open P0s** — need **no client decision at all** and can begin the moment this
> document is approved.

---

# 23. FINAL ENGINEERING DECISION LIST

**Decisions engineering may make without client approval.** Each changes *how*, never *what the
business gets*. Recorded so they are made deliberately and once.

| ID | Decision | Resolution | Rationale |
|---|---|---|---|
| **`ED-1`** | `ShiftVersion.timezone` — India-lock or strict IANA? | **Strict IANA (§4.3 Option B)** at create, update **and** publish | Zero breakage (15 test literals and 22 live rows carry `UTC`); preserves `P-20`/`PC-01`; the India invariant is enforced at registration, the only tier an external party can set. `NULL` stays valid — it is WD-06's inherit signal |
| **`ED-2`** | How to fix `NEW-02` | **Make `date` optional server-side, defaulting to `business_today(company_tz)`**; the caller stops sending it | Backward compatible; closes the defect *class*, not one instance; keeps the business date on the server, where the timezone already lives |
| **`ED-3`** | `Asia/Calcutta` handling | **Canonicalise on write** via an explicit two-entry alias map, applied **after** the `available_timezones()` check and **before** any allow-list. **Never** write `tz == "Asia/Kolkata"` — use a module-level `INDIA_TIMEZONES` frozenset | Accepts what real browsers send; fixes the future as well as the past; `IR-9`-proof. **Do not** attempt general IANA alias resolution — `zoneinfo` exposes none |
| **`ED-4`** | One punch endpoint or two? | **Two** — `POST /attendance/punches/me` (self) and `POST /attendance/punches` (on-behalf) | **`SR-02`: one endpoint cannot select between two schemas** when the discriminator is inside the body. Two endpoints also make the permission **static** rather than chosen by caller-controlled data — independently better RBAC hygiene. The web client changes in the same release regardless |
| **`ED-5`** | Timestamp wire format | **`AwareDatetime` + a `BeforeValidator` rejecting non-`str` input** | **`SR-03`: `AwareDatetime` alone accepts epoch integers** (`0` → `1970-01-01T00:00:00Z`). The stated contract is "ISO-8601 with an explicit offset"; an epoch integer is an inference, which that contract forbids |
| **`ED-6`** | On-behalf backdating bound, absent configuration | **Period-only bound for V1** — not future, not in a `CLOSED` period | Uses controls that already exist and are already tested. Escalates the real question as `CD-5` rather than inventing a default |
| **`ED-7`** | Cross-midnight break fix approach | **Approach A — wrap-aware time-of-day comparison. NOT Approach B** | **`SR-01`: Approach B regresses a working case** (a `01:00–02:00` break on a `22:00→06:00` shift). Approach A passes all six scenarios, needs no signature change, touches ~6 lines in one function, and matches two existing precedents (`_interval_contains`, `_derive_cross_midnight`) |
| **`ED-8`** | Locking strategy | **Exactly one `SELECT … FOR UPDATE` on `attendance_day`, in `calculate()`, acquired before `_build_calculation_input`, added in Phase 6 with the job** | Races 1 and 2 are handled by design (append-only + `collapse_duplicate_punches`) and must not be locked. Race 4 closes free with Phase 2's guard. **Do not raise the isolation level** |
| **`ED-9`** | Where validation lives | **The Pydantic schema boundary**, so every caller — web, future mobile, device, import, third-party — is bound identically without re-implementing it. Service-layer checks only for rules needing DB state (period, employment start) | Plan §10.5 invariant 4; matches the existing `validate_timezone` pattern |
| **`ED-10`** | Error handling for an unresolvable timezone reaching the engine | **Typed `ConfigurationError` → a `CONFIG_ERROR` attendance day, never a bare 500** | `attendance_day` already models `CONFIG_ERROR`. One misconfigured shift degrades one employee-date instead of taking out every calculate call — which matters once Phase 6's job hits it repeatedly and silently |
| **`ED-11`** | `_assert_timezone_change_allowed` signature | **Make it `async`**; `organisation/service.py:659` becomes `await` | `SR-08` — it needs an existence query |
| **`ED-12`** | Branch-guard scope | **Walk `EmployeeAssignment` history, not the current roster** | An employee who has since transferred away still has historical days computed in that branch's zone. A current-roster check is leaky in exactly the case the guard exists for |
| **`ED-13`** | CI database role | **`hrms_app`, the `NOBYPASSRLS` role — never `hrms`** — plus a test that proves a cross-tenant read is denied **in CI** | `SR-10`. Running RLS tests as the schema owner makes them pass for the wrong reason, **and pass green** |
| **`ED-14`** | `todayIso()` | **Delete it**, do not deprecate it; delete the duplicate at `policy-resolution/page.tsx:27` in the same commit | `NEW-05` is a remediation trap: after Phase 3 it would be the single surviving instance of a defect everyone believes is fixed, with no test or type error to reveal it |
| **`ED-15`** | Test framework and tiers | **Unchanged** — pytest + `.venv` for the API, vitest for the web. Tiers 1–3 need no database | No reason to change anything; the engine's purity (`PC-12`) is what makes the plan cheap |
| **`ED-16`** | `punch.request_time` column split | **Deferred** (plan §3.2, endorsed), **conditional on** a code comment plus a test asserting the application sets `created_at` and the DB `server_default` never wins | Under server-authoritative self-punch the two are equal by construction. The test is what keeps the deferral safe against a future import path |

---

# 24. FINAL IMPLEMENTATION ORDER

**Execution order — this governs, not the numbering:**

```text
Phase 0 ──► Phase 7 ──► Phase 1 ──► Phase 2 ──► Phase 3 ──► Phase 4 ──► Phase 5 ──► Phase 6 ──► Phase 8
             │                                       │                                  │
             └─ CI must gate before behaviour moves   └─ 3.10 waits on CD-1              └─ ships 6.6 with 3.10
```

---

## Phase 0 — Baseline and fact-finding · 1 day

**Objective.** Establish every number this programme will be measured against, and answer the two
questions the repository cannot.

**Dependencies.** None. **Begin on approval of this document.**

| # | Action | Output |
|---|---|---|
| 0.1 | Tag `pre-tz-remediation` at `e33fcdb` | Immutable reference |
| 0.2 | Repair the local `uv`/venv resolution — `uv run pytest` resolves a stale interpreter; `.venv/bin/python` works | Runnable suite |
| 0.3 | `pytest tests/unit` — **expect 362 passed in ~1.1 s** | Baseline |
| 0.4 | `pytest tests/integration tests/security` against a local DB — **802 collected.** Record pass/fail **per file** | **`IR-7`'s actual size, before Phase 7 makes it a gate** |
| 0.5 | `npm test` in `apps/web` — 45 test files | Baseline |
| 0.6 | **`DH-1`** read-only timezone inventory on **every** environment, **including production** | §21. **Hard precondition of Phase 2** |
| 0.7 | Capture 10 golden attendance scenarios with full `attendance_day` JSON — day, night, cross-midnight, holiday, weekly-off, leave, half-day, OT, incomplete, config-error | Before/after comparison set |
| 0.8 | Enumerate every test sending `punch_time` or `source` — **expect 11 `punch_time` across 3 files; ZERO setting `source`** | Phase-1 blast radius |
| 0.9 | Production access logs: **are there non-web callers of `/attendance/punches`?** | Resolves the `IR-2` release strategy |
| 0.10 | **Establish whether CI is currently red on `main`, and whether the `api` check is required for merge** | Determines Phase 7's true size (§8.2) |

**Acceptance.** Every number above recorded in the tracking issue. **No code changed.**
**Rollback.** N/A — read-only.

---

## Phase 7 *(pulled forward)* — CI and production gates · 2–3 days

**Objective.** Make a PR that breaks an attendance or timezone rule fail to merge.

**Dependencies.** Phase 0.4, 0.10.

**Files.** `.github/workflows/ci.yml` · repository branch-protection settings.

**Changes.** The nine-item checklist in §20.2, in full. Specifically: PostgreSQL 16 + Redis 7 services;
explicit application of `infra/docker/postgres/init/*.sql`; **`DATABASE_URL` → `hrms_app`** (`ED-13`);
`alembic upgrade head`; `TZ: UTC`; a `web` job (`npm ci` / `npm run lint` / `npm test`); both jobs as
required status checks; and the "Unit tests" step renamed to match what it runs.

**Tests.** A deliberate cross-tenant read **denied in CI** — the test that proves item 3 was done.

**Acceptance.** All 1164 backend tests plus the web suite run and gate merges; a PR containing a
knowingly-broken attendance assertion cannot be merged.
**Rollback.** Revert the workflow; un-require the checks. **No product risk — nothing behavioural
changes.**

---

## Phase 1 — Timestamp authority · 4–5 days

**Objective.** No client can set its own attendance timestamp or provenance on the self path.

**Dependencies.** Phase 7. `ED-4`, `ED-5`, `ED-6`. **`CD-5` only if the recommendation is rejected.**

**Files.**
`attendance/schemas.py` (`PunchCreate` `:1222-1240`; `RegularizationPunchRequest.requested_time`
`:1475`) · `attendance/router.py` (`create_punch` `:752-788` → two endpoints) ·
`attendance/service.py` (`record_punch` `:2299-2383`) · `attendance/exceptions.py` ·
`apps/api/Dockerfile` · `web/src/components/attendance/punch-entry-dialog.tsx` ·
`web/src/app/app/attendance/page.tsx` · `web/src/components/attendance/employee-attendance-panel.tsx`.

**Changes.** Two endpoints with one schema each, `extra="forbid"` (`ED-4`). `AwareDatetime` + a
string-type guard on every supplied instant (`ED-5`). Self: `punch_time = request_time`
unconditionally. On-behalf: required, aware, not future, not in a `CLOSED` period, `reference`
required. **`"source": default_source` unconditionally** — the validator at `schemas.py:1236-1240` is
deleted. Future / far-past bounds with typed errors. Write `punch.raw_payload`. `ENV TZ=UTC`. Split
the dialog: self mode has **no time field**; the failure path carries the `P-08` comment and test
(§12.1). Structured rejection logging.

**Tests.** The 12-case ingestion matrix (§11.2, `H1`–`H12`) **plus** the epoch-integer case from
`SR-03`; the 5-case server-TZ parametrised module (`G1`–`G5`); component tests for both dialog modes.
Rewrite the 11 existing `punch_time` posts to the admin path in the same commit, old assertions
preserved as comments naming the phase.

**Acceptance.** `punch_time` on the self endpoint → **422**. `source` from any caller → **422**. A
naive or epoch timestamp → **422**. `2099-01-01Z` → **422**. On-behalf without a reason → **422**.
Regularization apply still writes `source="REGULARIZATION"` (it bypasses `PunchCreate` entirely —
**VERIFIED**, so it cannot break).

**Rollback.** Single revert; API and web **must** ship together (`IR-1`). **No data migration, so
rollback is clean.** Punches written during the window remain valid — they are simply
server-stamped. If Phase 0.9 found third-party callers, land behind a feature flag accepting both
shapes, with a deprecation window.

---

## Phase 2 — India timezone invariant and historical protection · 3 days

**Objective.** Timezone configuration cannot be invalid, cannot be non-Indian, and cannot change under
computed attendance.

**Dependencies.** Phase 1. **`DH-1` reviewed and `DH-3` decided for production.** `CD-2`. `ED-1`,
`ED-3`, `ED-11`, `ED-12`.

**Files.** `organisation/schemas.py` (`ShiftVersionCreate.timezone` `:1243`, `ShiftVersionUpdate`
`:1280`, `CompanyRegistrationRequest` `:100`, `CompanyProfileUpdate` `:247`) ·
`organisation/service.py` (`_assert_timezone_change_allowed` `:702`, its call site `:659`,
`update_branch` `:1106`, `_validate_and_derive_for_publish` `:2282`) · `organisation/exceptions.py` ·
`core/config/settings.py` · `web/src/components/shift/shift-version-form.tsx:66` ·
`web/src/components/branch/branch-form.tsx:93` · `web/src/app/register/page.tsx` ·
`apps/api/scripts/` (the `DH-1` inventory script).

**Changes.** IANA validator on both `ShiftVersion` schemas **and** at publish (`NEW-01`). Alias
canonicalisation on write, plus the `INDIA_TIMEZONES` frozenset (`ED-3`). `allowed_company_timezones`
setting, enforced at `/register` **and** `PATCH /company/profile` (`NEW-04`, §7.3).
`_assert_timezone_change_allowed` implemented and **`async`**, called from **both**
`update_company_profile` and `update_branch`; `CLOSED`-period refusal checked **before** the
`TRIAL`/zero-days hatch; branch scope walks assignment history (`ED-12`). **`CLOSED`-period check on
shift-version publish** (`SR-11`). Replace the free-text timezone `<Input>`s with the same select
`/register` uses. Then **`DH-2`**.

**Tests.** `E1`–`E7` (§17.5 of the plan) plus the eight `NEW-01` cases (§4.5) — including
`timezone="UTC"` and `timezone="Asia/Calcutta"` still accepted, and `NULL` still falling through.

**Acceptance.** `ShiftVersion.timezone="IST"` → **422 at create, never a 500 at calculate.** A company
or branch timezone change with computed attendance → **409**, from **both** paths. `TRIAL`/zero-days →
permitted. Any affected period `CLOSED` → refused **unconditionally**. `TZ-09` closes as a side effect.

**Rollback.** Revert the code. **`DH-2` is separately reversible from the audit log.** The guard is
additive — reverting restores permissiveness and loses nothing.

---

## Phase 3 — India business dates · 2–3 days

**Objective.** No business-date derivation uses the server OS date or the UTC date.

**Dependencies.** Phase 2. `ED-2`, `ED-14`. **3.10 additionally waits on `CD-1`.**

**Files.** `shared/business_time.py` **(new)** · `attendance/service.py:3502, 3547, 3558` ·
`leave/service.py:1979, 1990, 2597` · **`leave/tasks.py:36, 85, 110`** · `attendance/router.py:865` ·
the session/bootstrap payload · `web/src/lib/attendance/format.ts` · **8 web files, 16 `todayIso()`
invocations** (§5.4) · `web/src/app/app/policy-resolution/page.tsx:27`.

**Changes.** `business_today(tz)` / `business_month_start(tz)`. Replace **4** `date.today()` and **2**
UTC month-starts. **Fix `as_of` in all three Beat leave tasks (`SR-05`)** and record the <05:30 IST
constraint in their docstrings. Make `/days/calculate`'s `date` optional, defaulting server-side
(`ED-2`). Ship the company timezone in the session payload. `todayIso()` → `businessToday(tz)`
everywhere; **delete** `todayIso()` and the duplicate (`ED-14`). Fix `create-period-dialog`'s persisted
defaults (`SR-06`). **3.10:** the period-lock basis, per `CD-1`.

**Tests.** `A1`–`A11` boundaries; `F1`–`F5` period lock asserting whichever basis `CD-1` selects —
**including the 05:00 IST month-boundary case, frozen in a test rather than a comment.** A test that
the monthly accrual fires with `as_of` = the **1st**, not the 30th. `businessToday()` at 02:00 IST
returns the IST date.

**Acceptance.** Identical regularization and leave boundary behaviour under `TZ=UTC` and
`TZ=Asia/Kolkata`. `max_requests_per_month` counts by the IST month. **No `date.today()` and no
`datetime.now(UTC).date()` remains in any business rule.** `grep -r "todayIso" apps/web/src` returns
nothing.

**Rollback.** Per-site revert; each change is independent. **Behaviour-preserving wherever the server
TZ already equals IST**, which is the dev host — so the blast radius in dev is zero and only
containerised environments move.

---

## Phase 4 — Cross-midnight breaks · 1 day

**Objective.** A configured paid break is paid, whatever hour it spans — **without regressing any
break that matches today.**

**Dependencies.** Phase 7 only. **No client decision.** `ED-7`.

**Files.** `attendance/calculation.py` — **`match_breaks` (`:574-617`) ONLY.** No signature change, no
call-site change, **line 586 untouched.**

**Changes.** Approach A (§14.3): wrap-aware window comparison for both `FIXED_WINDOW` and
`FLEXIBLE_DURATION`, with `start == end` treated as a point.

**Tests.** The ten in §14.5. **Test 4 — the `01:00–02:00` break on a `22:00→06:00` shift — is
mandatory and is the `SR-01` guard.** All ten are pure functions, no database.

**Acceptance.** All six §14.2 scenarios behave as the "Approach A" column states. **Case 1 and case 4
are unchanged from today** — the regression guards. The ten golden scenarios from 0.7 are byte-identical
except where a midnight-spanning break exists.

**Rollback.** One-function revert. **The code is trivially reversible; the recompute is not** —
`attendance_day` has no history table. **Snapshot every affected day's full JSON before recomputing**
and recompute **open** days only. The change is almost always in the employee's favour; the one
exception is `is_excess` newly firing on an over-long midnight break, which must be named in the
change notice.

---

## Phase 5 — UI timezone · 2 days

**Objective.** No attendance time renders in the viewer's browser timezone.

**Dependencies.** Phase 3 (the company timezone must already be on the wire). **5.6 waits on `CD-3`.**

**Files.** `web/src/lib/attendance/format.ts` · **25 call sites across 7 files** (§15.1) · the
day-detail page for dual-zone.

**Changes.** `formatClockTime(iso, tz)` / `formatDateTime(iso, tz)` with **`tz` required**. Always
render an `IST` label. Dual-zone on the day-detail page only. Correct `format.ts`'s misleading header
comment. **5.6:** amend `DEC-010`'s rendering clause (`CD-3`).

**Tests.** The seven in §15.5 — all blocked on Phase 7's `web` job.

**Acceptance.** A fixed instant renders as `09:05 IST` with the runner at `TZ=America/New_York`. Every
attendance time carries a zone label. `grep` finds no `toLocaleTimeString(undefined` or
`toLocaleString(undefined` in attendance surfaces.

**Rollback.** Display-only; revert freely. **No data, no API, no computed value changes.**

---

## Phase 6 — Calculation and reconciliation · 5 days

**Objective.** Attendance exists without anyone asking for it, and a period can be finalized.

**Dependencies.** Phases 1–3. `CD-4`. `ED-8`. **Phase 3.10 ships with 6.6 (§9.6).**

**Files.** `attendance/tasks.py` **(new)** · `core/celery_app.py` (one beat entry) ·
`attendance/service.py` (`record_punch` sync hook; `calculate` row lock) ·
`attendance/repository.py` (orphan query) · the runbook.

**Changes.** Best-effort synchronous calculate after a punch insert, **wrapped so a calculation
failure never fails the punch write**. `modules/attendance/tasks.py` on the `leave/tasks.py` pattern
verbatim, **using `business_today()` from the first line** (`SR-05`). Beat at 09:30 IST. Trailing-3-day
window, skipping locked days and `CLOSED` periods. **One `SELECT … FOR UPDATE` on `attendance_day`,
acquired before `_build_calculation_input`, with a lock-ordering review against `bulk_lock`** (`ED-8`).
Orphan-punch report **handling all four window shapes** (`SR-14`). Document `OPS-006` in the runbook.

**Tests.** `J1`–`J4` (§19.4, including the first-ever-calculation race). Job idempotency across two
runs. A punch outside the pad appears in the orphan report; one inside does not; **a punch for an
employee with no shift does not appear**.

**Acceptance.** An employee who punches in and out has an `attendance_day` row without human
intervention. Two consecutive job runs produce identical rows. A period can be finalized.

**Rollback.** Disable the beat entry — the largest and safest lever. The sync hook is behind a
try/except and can be reverted independently. **`IR-4`: run once manually on staging at production
scale before enabling the schedule.**

---

## Phase 8 — Staging and UAT · 2 days

Deploy the full stack. Replay the 10 golden scenarios from 0.7 and **diff against baseline**. Run the
punch-integrity matrix by hand: naive · epoch integer · future · far-past · forged `source` · self
with `punch_time` · admin without a reason. Verify the 09:30 IST job fires and is idempotent across two
runs. Verify the timezone guard on a real tenant, **and that the `TRIAL` hatch still permits a genuine
day-one correction**. Verify IST rendering from a browser with the OS set to `America/New_York`.
**HR/UAT sign-off on a full night-shift week including a midnight-spanning break** — the one scenario
that exercises Phase 4, Phase 3.10 and Phase 6 together.

**Rollback drill is part of this phase, not a document** (`§19.5` of the plan).

---

## Phase 9 — Production rollout · 1 day + 48 h monitoring

Off-hours deploy (after 22:00 IST, before 05:00 IST — outside every shift boundary and the 09:30 job).
**API and web together — non-negotiable** (`IR-1`). Monitor for 48 h: punch rejection rate by reason ·
punch volume vs. the prior week · `attendance_day` creation rate · orphan-punch count · timezone-guard
409s · 500 rate on `/attendance/*`.

> **The single most important production signal is the punch rejection rate by reason.** If Phase 0.9
> missed an integration, this is where it surfaces — as a spike in 422s, within minutes, before a
> payroll cycle absorbs it.

---

# 25. NO CODE CHANGED

This task produced exactly one artefact: this document.

```text
Application code    unchanged
Frontend code       unchanged
Database schema     unchanged
Migrations          unchanged
Tests               unchanged
CI configuration    unchanged
Runtime config      unchanged
Database DATA       unchanged  (every query was a read-only SELECT / SHOW)
```

`git status` shows no modification to any file under `apps/`, `alembic/`, `.github/` or `infra/`
attributable to this task.

---

# 26. FINAL VERDICT

## GREEN — Ready to implement

**No unresolved business ambiguity. May begin the moment this document is approved.**

| Item | Phase | Why it is green |
|---|---|---|
| **`NEW-01` — IANA validation on `ShiftVersion.timezone`** (create / update / publish) | 2 | `ED-1` settles it. Zero breakage, one validator copied from `BranchCreate`. **The cheapest P0 in the programme, and — per `SR-09` — the one an ordinary HR user is most likely to trigger by typing `IST`** |
| **`F-05` — cross-midnight breaks, via Approach A** | 4 | Unambiguous defect. `ED-7` settles the approach. Ten pure tests, no database, ~6 lines, no signature change |
| **`TZ-02` — naive-timestamp rejection + `ENV TZ=UTC`** | 1 | `DEC-TZ-04`; independent of every other decision; correct under all options |
| **`F-11` — server-assigned `source`** | 1 | `DEC-TZ-05`. **VERIFIED to break zero existing tests** |
| **`F-01`/`F-02`/`F-03` — server-authoritative self-punch** | 1 | `DEC-TZ-01` = A is already approved in the plan's `P-02`. Only the *endpoint shape* was open, and `ED-4` settles it |
| **`TZ-06` — `business_today()` at 4 `date.today()` + 2 UTC-month sites** | 3 | `DEC-010` already requires it |
| **`SR-05` — `as_of` in the three Beat leave tasks** | 3 | Same helper, same phase. **An existing, demonstrable defect: monthly accrual runs with `as_of` = the last day of the previous month** |
| **`NEW-05` — delete the duplicate `todayIso()`** | 3 | `ED-14` |
| **`SR-06` — IST default in `create-period-dialog`** | 3 | Same fix, same phase |
| **`TZ-01` — the timezone-change guard, called from both paths** | 2 | `DEC-TZ-13` = A is approved. `ED-11`/`ED-12` settle the mechanics |
| **`TZ-09` — torn configuration read** | 2 | Closes free as a side effect |
| **`F-18` — write `punch.raw_payload`** | 1 | Column exists. **Gated on PII sign-off, not on a decision** |
| **`TST-001`/`NEW-06`/`SR-10` — the CI gate** | 7 | Purely engineering. `ED-13` settles the role question |
| **`R-TZ-16a` — the orphan-punch report** | 6 | **Changes no computed value; needs no approval** |
| **Documentation:** `attendance_date`'s definition (§10.5) · `night_ot_mode` inertness (§17.4) · the ±2h pad · the WD-30 basis · the punch-UTC / day-local list split | 0–3 | Documentation only |

## YELLOW — Requires explicit technical confirmation

**Engineering judgement calls where this document states a recommendation that should be confirmed
before code is written, not discovered during review.**

| Item | The confirmation needed | Ref |
|---|---|---|
| **`SR-02` / `ED-4` — two punch endpoints** | Confirm the URL change (`POST /attendance/punches/me`) is acceptable. **The plan is internally contradictory here (§5.1 vs §7.1) and must be amended either way** | §11.3 |
| **`SR-03` / `ED-5` — epoch-integer timestamps** | Confirm the contract is "ISO-8601 string with offset", not merely "tz-aware". If epoch input is wanted for a future device path, say so and document it | §11.4 |
| **`SR-01` / `ED-7` — Approach A over Approach B** | Confirm the override of both the plan (§10.4) and the remediation spec (§12.6). **The evidence is CODE-PROVEN and reproducible in one command** | §14 |
| **`ED-2` — `/days/calculate?date=` becomes optional** | Confirm an API default is preferred to a client-computed IST date | §5.3 |
| **`ED-8` — one `FOR UPDATE`, in Phase 6** | Confirm the lock-ordering review against `bulk_lock` is scheduled as work, not assumed | §19.3 |
| **`ED-12` — branch-guard scope walks assignment history** | Confirm the query cost is acceptable on a large tenant | §13.4 |
| **`SR-11` — `CLOSED`-period check on shift-version publish** | Confirm this narrow control is in scope for Phase 2, and that the general case is recorded as debt against the policy-versioning workstream rather than absorbed here | §13.5 |
| **`SR-14` — the fourth window shape** | Confirm the orphan report excludes no-shift employees rather than flagging them | §10.4, §18.4 |
| **Plan §14's "no migration required"** | Confirm it survives `CD-5`. **If a tighter on-behalf backdating limit is required, it does not** | §11.5 |
| **Phase-4 recompute snapshot** | Confirm the pre-recompute snapshot mechanism exists and has been tested **before** Phase 4, not after. It is the only irreversible data operation in the programme | §24 Phase 4 |

## RED — Requires client decision

**Business-policy decisions. Engineering may not make these.**

| ID | Decision | Blocks |
|---|---|---|
| **`CD-1`** ⭐ | May an employee's punch ever be refused because a period closed — or must the fact always be recorded and reconciled? | **Phase 3.10 only.** All other Phase-3 work proceeds |
| **`CD-2`** | India-only allow-list on company registration **and** on `PATCH /company/profile`? | **Phases 2.5, 2.6** |
| **`CD-3`** | May `DEC-010`'s **LOCKED** rendering clause be amended to name the WD-06-resolved zone? | **Phase 5.6.** Phases 5.1–5.5 proceed regardless |
| **`CD-4`** | Automatic calculation schedule (09:30 IST) and trailing-window size (3 days)? | **Phases 6.2, 6.3** |
| **`CD-5`** | May an admin enter an on-behalf punch for any past date inside an open period? | **Nothing, if the recommendation is accepted.** Becomes a **migration + later phase** if rejected |
| **`CD-6`** | Implement or withdraw `night_ot_mode`'s `WINDOW`/`BOTH`? | **Nothing.** Deferred with a trigger |

**Deliberately not escalated** (§22.1): punch rounding · the ±2h pad width · third-party integrations
(a Phase-0 fact, not a decision) · DST policy · employee-level timezone · offline/mobile · geofencing ·
biometric identity.

## BLOCKED — Must be resolved before the first production code change

| # | Blocker | Owner | Why it blocks |
|---|---|---|---|
| **B1** | **`SR-01` — the break-fix approach.** The approved plan would ship a regression | Engineering — `ED-7` | Phase 4 cannot be written until this is settled. **One command reproduces the evidence** |
| **B2** | **`SR-02` — the punch endpoint shape.** The approved design cannot be implemented as written, and the plan contradicts itself | Engineering — `ED-4` | Phase 1 cannot be written |
| **B3** | **`TST-001` + `SR-10` — the CI gate, running as `hrms_app`** | Engineering | **Every** integration test in this document is worthless *as a gate* until CI runs it. Phase 7 precedes all behavioural work |
| **B4** | **`DH-1` inventory against PRODUCTION** | Ops / Engineering | **NOT VERIFIABLE HERE.** Phase 2's guard makes every timezone value permanent. Landing it before production is inventoried freezes every misconfiguration forever, with no escape for a live tenant |
| **B5** | **Phase 0.9 — are there third-party callers of `/attendance/punches`?** | Ops | **NOT VERIFIABLE HERE.** Determines whether Phase 1 is a same-day cutover or needs a feature-flagged deprecation window (`IR-2`) |
| **B6** | **Phase 0.10 — is CI currently red on `main`, and is the check required?** | Engineering | Determines whether Phase 7 is "add jobs" or "fix a suite nobody has run honestly" (`IR-7`) |
| **B7** | **`CD-1` … `CD-4`** | **CLIENT** | Gate Phases 2.5–2.6, 3.10, 5.6, 6.2–6.3 |
| **B8** | **PII retention sign-off for `punch.raw_payload`** | Client / Legal | It captures IP and user-agent on every punch for every employee. Retro-actively shortening retention on a populated column is a deletion project |
| **B9** | **Pre-recompute snapshot, tested** | Engineering | Phase 4's recompute is the **one irreversible data operation** in the programme. `attendance_day` has no history table |

---

## The closing statement

The reconciliation changed the plan in two places and confirmed it in thirty-one. Both changes are of
the same kind, and it is worth naming the kind: **each is a case where a fix designed from the audit
documents does not survive contact with the code it would touch.**

The break fix was chosen for its consistency with how the rest of the engine reasons about time —
UTC spans, not wall-clock comparisons — and that reasoning is sound. It simply happens to be wrong
here, because a break window is anchored to a *shift*, not to a *date*, and the shipped time-of-day
comparison already gets the after-midnight case right by being date-agnostic. The schema split was
chosen because the permission genuinely does decide which act is occurring — but the permission is
itself decided by the body, and a request model cannot be selected by its own contents.

Neither was findable by reading the audits. Both were findable in one command.

> **What stands unchanged is the plan's central judgement, and this review reinforces it.** The
> calculation engine is sound; every P0 sits at a boundary — ingestion, configuration mutability,
> scheduling, rendering, packaging — or is a missing test. **Nothing in this document asks anyone to
> rebuild the instrument.** It asks for one function to be corrected, four boundaries to be closed, a
> schedule to be added, and a test harness that makes all of it provable.
>
> **The timezone subsystem is a well-built instrument reading an untrusted input.** The plan fixes the
> input. This review fixes two of the plan's tools before they are used on it.

**Recommendations in this document carry no authority.** They exist so each decision has a starting
point, not so it can be skipped. Nothing here may be implemented until this document is reviewed and
approved, and nothing gated on `CD-1`…`CD-6` or `B1`…`B9` may be implemented until those are recorded.

---

*Prepared 2026-09-15 against the working tree at `e33fcdb`, branch `main`. **No application code,
database schema, migration, test, CI configuration, or database row was modified.** Claims marked
**VERIFIED** were reproduced by executing the shipped code read-only (`apps/api/.venv/bin/python`), by
running `pytest`, or by read-only `SELECT`/`SHOW` queries against the dev PostgreSQL on port 5433.
Every file and line citation was re-read from the working tree on this date. Production data and
production deployment configuration are **NOT VERIFIABLE HERE** — no production environment is
reachable from this repository, which is why `B4` and `B5` are blockers rather than assumptions.*
