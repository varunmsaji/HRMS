# Attendance — India V1 Timezone & Punch-Integrity Implementation Plan

**Created:** 2026-09-15
**Status:** PLAN — awaiting review. **Nothing in this plan is implemented.**
**Product scope:** **India only.** Business timezone `Asia/Kolkata`.
**Stage:** `AUDITS → DECISIONS → ` **`IMPLEMENTATION PLAN (this document)`** ` → REVIEW → IMPLEMENTATION`

**Code changed: NO · Schema changed: NO · Migrations changed: NO · Tests changed: NO · Configuration changed: NO · CI changed: NO**

> The only artefact produced by this task is this document. Every code reference below was read
> from the working tree on 2026-09-15; every behavioural claim marked **VERIFIED** was reproduced
> by executing the shipped code read-only or by querying the running dev PostgreSQL.

---

## Source documents reconciled

| Document | Role here |
|---|---|
| [`ATTENDANCE_TIMEZONE_DECISION_AND_REMEDIATION.md`](./ATTENDANCE_TIMEZONE_DECISION_AND_REMEDIATION.md) | Canonical decision + backlog surface (`DEC-TZ-01…16`, `R-TZ-*`, `R-F-*`) |
| [`ATTENDANCE_TIMEZONE_AUDIT.md`](./ATTENDANCE_TIMEZONE_AUDIT.md) | Timezone findings `TZ-01…TZ-14` |
| [`ATTENDANCE_TIMEZONE_TEST_MATRIX.md`](./ATTENDANCE_TIMEZONE_TEST_MATRIX.md) | 68 scenarios, 4 automated — the test baseline (§17) |
| [`../business-rules/attendance/ATTENDANCE_TIME_TIMEZONE_IMPLEMENTATION_AUDIT.md`](../business-rules/attendance/ATTENDANCE_TIME_TIMEZONE_IMPLEMENTATION_AUDIT.md) | Ingestion findings `F-01…F-27` |
| [`../business-rules/attendance/ATTENDANCE_TIMEZONE_DECISION_REGISTER.md`](../business-rules/attendance/ATTENDANCE_TIMEZONE_DECISION_REGISTER.md) | Long-form `DEC-TZ-*` rationale |
| [`../modules/attendance/ATTENDANCE_MASTER_RULE_MATRIX.md`](../modules/attendance/ATTENDANCE_MASTER_RULE_MATRIX.md) | Rules `B2`, `C1`–`C4` |
| [`../adr/0010-utc-storage-company-timezone-render.md`](../adr/0010-utc-storage-company-timezone-render.md) | `DEC-010` — LOCKED |
| [`../architecture/WORKFORCE_ATTENDANCE_DECISION_LOG.md`](../architecture/WORKFORCE_ATTENDANCE_DECISION_LOG.md) | `WD-06`, `WD-11`, `WD-30` — LOCKED |
| [`TECHNICAL_DEBT_REGISTER.md`](./TECHNICAL_DEBT_REGISTER.md) | `TST-001`, `PAY-001`, `PAY-013`, `ATT-001/005/009`, `DAT-004/005`, `OPS-001/006`, `FE-1`, `TZ-1`, `DEAD-1` |

> **Missing source document.** The task brief names `docs/audits/ATTENDANCE_TIMEZONE_CLIENT_DECISION_REGISTER.md`.
> **That file does not exist.** The decision register lives at
> `docs/business-rules/attendance/ATTENDANCE_TIMEZONE_DECISION_REGISTER.md`, and §17 of
> `ATTENDANCE_TIMEZONE_DECISION_AND_REMEDIATION.md` supersedes it as the signing surface. This plan
> uses both. **Recorded as discrepancy `DOC-D7` (§2.9).**

---

# 1. EXECUTIVE SUMMARY

## 1.1 What this plan does

It converts the completed audits into an India-only V1 implementation roadmap: server-authoritative
punch time, an `Asia/Kolkata` business-timezone invariant, protected historical attendance, correct
India-local attendance dates, and the automated tests and CI gate that keep all of it true.

## 1.2 The single most important finding

**The attendance calculation engine does not need to change.** It is a pure, side-effect-free
function of `(punches, shift, policy, IANA string)` and it was proven correct by execution under
four server timezones and four DST transitions. Every P0 in this plan sits at a **boundary** —
ingestion, configuration mutability, scheduling, rendering, packaging — or is a missing test.

> Re-verified independently for this plan: a `22:00→06:00` shift spans **540** real minutes on the
> `Europe/London` fall-back night, **420** on spring-forward, **480** in `Asia/Kolkata`. **VERIFIED.**

The corollary matters for scoping: **do not open `calculation.py` except for `match_breaks`** (§10.4).

## 1.3 What is actually broken, in one paragraph

Attendance timestamps are self-declared. The API accepts a client-supplied `punch_time` with no
bound in either direction, no requirement that it carry a UTC offset, and no restriction on the
`source` label the caller attaches; the only shipped UI presents that timestamp as an editable
`<input type="datetime-local">`. Separately, `Company.timezone` and `Branch.timezone` are single
mutable columns that `recompute()` re-reads at calculation time, so editing either silently
rewrites historical attendance — and the guard written to prevent it is an empty stub that the
branch path never calls. Nothing schedules attendance calculation at all, so no `attendance_day`
row exists unless an endpoint was called by hand. Cross-midnight breaks never match, so night-shift
break minutes are silently unpaid. And 783 integration tests do not run in CI.

## 1.4 Six new findings this plan adds

These were found by inspecting code and data, not by reading the audits. Each is detailed in §2.9.

| ID | Finding | Severity |
|---|---|---|
| **NEW-01** | **`ShiftVersion.timezone` has no IANA validation at any layer** — create, update and publish all accept an arbitrary ≤64-char string. `'IST'` is accepted and then raises `ZoneInfoNotFoundError` inside `calculation.py`, an unhandled exception → **HTTP 500 on every calculate for that employee-date**. This is the *highest-precedence* link in the WD-06 chain. Contradicts audit finding F-22. | 🔴 **P0** |
| **NEW-02** | **`todayIso()` does reach a calculation input.** `employee-attendance-panel.tsx:78` posts `/attendance/days/calculate?date=${todayIso()}` — a **UTC** date. Between 00:00 and 05:29 IST the button computes *yesterday*. TZ-07/F-09 both state it is "display only — never reaches a calculation". | 🟠 **P1** |
| **NEW-03** | **3 companies in the dev database carry `Asia/Calcutta`**, not `Asia/Kolkata` — created through the real `/register` flow. Any India-lock guard written as `timezone == "Asia/Kolkata"` will reject or mis-handle them. | 🟠 **P1** |
| **NEW-04** | **The public `/register` page offers the full IANA timezone list.** `CompanyRegistrationRequest.timezone` accepts any valid zone with no country gate. A non-India company timezone is creatable today, by an anonymous visitor, with no admin involved. | 🟠 **P1** |
| **NEW-05** | **`todayIso()` is duplicated** as a private function in `policy-resolution/page.tsx:27`. Fixing the shared helper alone leaves this copy wrong. | 🔵 P2 |
| **NEW-06** | **CI has no frontend job at all.** `apps/web` has a working `vitest` suite (`npm test`) and existing `*.test.tsx` files; no workflow runs them. `TST-001` mentions this in passing; it is a distinct gate. | 🟠 **P1** |

## 1.5 Classification of the target V1 policy

| Target policy (task §3–§21) | Status |
|---|---|
| UTC / `TIMESTAMPTZ` storage of exact instants | ✅ **ALREADY IMPLEMENTED** — do not touch |
| Timezone-aware arithmetic, IANA only, no `utcnow()` | ✅ **ALREADY IMPLEMENTED** |
| Server-timezone independence of results | ✅ **ALREADY IMPLEMENTED** (untested — §17) |
| Attendance date = shift start date in resolved zone | ✅ **ALREADY IMPLEMENTED** |
| Holiday / weekly-off / leave on the local attendance date | ✅ **ALREADY IMPLEMENTED** |
| Raw punch never overwritten (append-only) | ✅ **ALREADY IMPLEMENTED** (WD-11) |
| Period close locks days (`is_locked`) | ✅ **ALREADY IMPLEMENTED** |
| Server-authoritative online punch time | 🔧 **REQUIRES CODE CHANGE** — Phase 1 |
| Naive timestamp rejection | 🔧 **REQUIRES CODE CHANGE** — Phase 1 |
| Server-assigned `source` | 🔧 **REQUIRES CODE CHANGE** — Phase 1 |
| `Asia/Kolkata` invariant + timezone-change guard | 🔧 **REQUIRES CODE CHANGE** — Phase 2 |
| India-local "today" for regularization/leave windows | 🔧 **REQUIRES CODE CHANGE** — Phase 3 |
| Cross-midnight break matching | 🔧 **REQUIRES CODE CHANGE** — Phase 4 |
| IST display timezone | 🔧 **REQUIRES CODE CHANGE** — Phase 5 |
| Scheduled calculation / reconciliation | 🔧 **REQUIRES CODE CHANGE** — Phase 6 |
| CI PostgreSQL + merge gate | 🔧 **REQUIRES CODE CHANGE** — Phase 7 |
| Period-lock date basis for punches | ⚖️ **REQUIRES CLIENT APPROVAL** — `OD-1` (§23) |
| Punch rounding (`DEC-TZ-06`) | ⚖️ **REQUIRES CLIENT APPROVAL** — do not implement |
| Night-OT window (`DEC-TZ-07` / `F-06` / `ATT-005`) | ⚖️ **REQUIRES CLIENT APPROVAL** — do not implement |
| ±2h punch pad width (`DEC-TZ-16`) | ⚖️ **REQUIRES CLIENT APPROVAL** — but the **orphan report** does not |
| Geofencing (`F-19`) | ⚖️ **REQUIRES CLIENT APPROVAL** — out of scope here |
| DST business policy (`DEC-TZ-11`, `DEC-TZ-14`) | ⏸️ **DEFERRED** — India has no DST |
| Employee-level timezone (`DEC-TZ-09`) | ⏸️ **DEFERRED** — would amend LOCKED `WD-06` |
| Offline / mobile queue (`DEC-TZ-15`) | ⏸️ **DEFERRED** — not supported in V1, must fail loudly |
| tzdata pinning (`TZ-05`) | ⏸️ **DEFERRED** to P2 — dormant for India; two cheap parts kept (§7.3) |

## 1.6 Production verdict

> # **NO-GO**

Seven P0s are open: `NEW-01`, `TZ-01`/`PAY-013`, `TZ-02`/`F-07`, `F-01`/`F-02`/`F-03`, `F-11`,
`F-05`, `F-14`/`PAY-001` — plus the `TST-001` CI prerequisite without which none of the above can
be proven. §21 is the hard checklist.

## 1.7 Effort

| Phase | Scope | Estimate |
|---|---|---|
| 0 | Baseline | 0.5 day |
| 7 *(pulled forward)* | CI + PostgreSQL + web job | 1.5–2 days |
| 1 | Timestamp authority | 3–4 days |
| 2 | India timezone invariant | 2–3 days |
| 3 | Attendance date / period lock | 2 days |
| 4 | Cross-midnight breaks | 1 day |
| 5 | UI timezone | 2 days |
| 6 | Calculation / reconciliation | 4–5 days |
| 8–9 | Staging + rollout | 3 days |
| **Total** | | **≈ 4 engineering weeks**, one engineer, sequential |

---

# 2. CURRENT ARCHITECTURE

## 2.1 The shipped time flow

```text
BROWSER                      punch-entry-dialog.tsx
  nowForDatetimeLocal()      seeds <input type="datetime-local"> from the BROWSER clock  :33,64
  user may edit it freely                                                                :147-153
  new Date(punchTime).toISOString()   browser tz -> UTC                                  :94
        │  POST /v1/attendance/punches  { employee_id, punch_time, direction, reference }
        ▼
ROUTER                       attendance/router.py::create_punch                          :753
  RBAC: ATTENDANCE.PUNCH (self) | ATTENDANCE.PUNCH_ON_BEHALF (other)                     :769-775
  default_source = "WEB" (self) | "ADMIN" (on-behalf)                                    :783
  captures request.client.host + User-Agent  ── already wired, used only for audit        :784-785
        ▼
SCHEMA                       attendance/schemas.py::PunchCreate                          :1220
  punch_time: datetime | None      ── NO offset requirement, NO bounds                   :1234
  source: str | None               ── all 7 values accepted from any caller              :1236
        ▼
SERVICE                      attendance/service.py::PunchService.record_punch            :2299
  _ensure_employee_visible(target)                          ── authorization, solid      :2326
  now = datetime.now(UTC)                                   ── computed...               :2336
  _ensure_date_open(company, (punch_time or now).date())    ── UTC civil date, WD-30     :2347
  "punch_time": body.punch_time or now                      ── ...and never compared     :2353
  "source":     body.source or default_source               ── client wins               :2355
  "created_at": now                                         ── true receipt, audit only  :2359
        ▼
DB                           punch.punch_time TIMESTAMPTZ, append-only, RLS by company_id
  naive value -> asyncpg resolves against the PROCESS OS TIMEZONE                        (TZ-02)
        ▼
   ( NOTHING SCHEDULES A CALCULATION — F-14 / PAY-001 )
        ▼
ENGINE                       attendance/service.py::AttendanceDayService.calculate       :2483
  _ensure_date_open(target_date)                            ── local date here           :2504
  existing.is_locked -> AttendanceDayLockedError                                         :2511
  _build_calculation_input                                                               :2711
     employment / assignment / company / branch / roster / shift version — SEPARATE SELECTs
     resolve_timezone(shift > branch > company)             calculation.py               :294
     resolve_schedule_window -> scheduled span + ±2h load window                         :314-345
  calc.evaluate_day(inputs)                                 ── PURE, UTC throughout      :757
        ▼
attendance_day  (UNIQUE company+employee+date)  stores `timezone` — WRITE-ONLY provenance
        ▼
API                          _format_timestamp -> "…Z"                                   schemas.py:89
        ▼
WEB                          format.ts formatClockTime / formatDateTime
  toLocaleTimeString(undefined, …)  -> renders in the VIEWER'S BROWSER TIMEZONE          :16,21
```

## 2.2 Storage model — correct, do not change

**VERIFIED.** Every attendance timestamp column is `TIMESTAMPTZ`; the live `punch` table confirms
it (`information_schema.columns`). No `timestamp without time zone` exists in the attendance
schema. The three-way split is deliberate and coherent:

| Type | Meaning | Examples |
|---|---|---|
| `TIMESTAMPTZ` | An instant | `punch.punch_time`, `punch.created_at`, `attendance_day.scheduled_*`, `actual_*` |
| `DATE` | A local business date | `attendance_day.attendance_date`, `attendance_period.period_start/_end`, `leave_day_projection.attendance_date` |
| `TIME` | Civil wall-clock, given meaning by a sibling `timezone` column | `shift_version.start_time/end_time/window_*/core_*`, `shift_break.*` |

`attendance_day.timezone` is `VARCHAR(64) NOT NULL`
(`alembic/versions/20260820100000_attendance_day.py:33`).

## 2.3 Timezone resolution (WD-06) — correct, keep

```python
# apps/api/src/hrms/modules/attendance/calculation.py:294-298
def resolve_timezone(*, shift_version_timezone, branch_timezone, company_timezone) -> str:
    """WD-06: `ShiftVersion.timezone` > `Branch.timezone` > `Company.timezone`."""
    return shift_version_timezone or branch_timezone or company_timezone
```

Resolved once per calculation at `service.py:2838-2842`; the result flows into every consumer.
`Company.timezone` is `NOT NULL DEFAULT 'Asia/Kolkata'`
(`core/db/models/identity.py:45`), so the chain can never fail open to the server OS.

## 2.4 Every write path that can set a timezone

Complete inventory — this is what §9 of the brief asks for and it is larger than the audits state.

| # | Path | Schema | Guard today | Effective-dated | Risk |
|---|---|---|---|---|---|
| 1 | `POST /register` (**public, anonymous**) | `CompanyRegistrationRequest.timezone`, `organisation/schemas.py:100` | IANA validator only, **no country gate** | n/a — creation | **NEW-04** |
| 2 | `PATCH /company/profile` | `CompanyProfileUpdate.timezone`, `:247` | IANA validator + `_assert_timezone_change_allowed` — **an empty stub** (`organisation/service.py:702-709`), called at `:659` | **NO** | **TZ-01** |
| 3 | `POST /branches` | `BranchCreate.timezone`, `:676` | IANA validator | n/a — creation | low |
| 4 | `PATCH /branches/{id}` | `BranchUpdate.timezone`, `:710` | IANA validator, **guard never called** (`update_branch`, `:1105-1186`) | **NO** | **TZ-01** |
| 5 | `POST /shifts/{id}/versions` (draft) | `ShiftVersionCreate.timezone`, `:1243` | **`max_length=64` ONLY — no IANA validation** | YES | **NEW-01** |
| 6 | `PATCH …/versions/{id}` (draft) | `ShiftVersionUpdate.timezone`, `:1280` | **none** | YES | **NEW-01** |
| 7 | `POST …/versions/{id}/publish` | — | `_validate_and_derive_for_publish` (`:2282-2330`) checks times, flex windows and `effective_from` — **never the timezone** | YES | **NEW-01** |

> **Paths 5–7 are the audit's blind spot.** F-22 states *"every timezone column is validated against
> `zoneinfo.available_timezones()` at the schema layer"*. It is true for company and branch. It is
> **false for `ShiftVersion`** — the top of the precedence chain.

## 2.5 Punch creation paths

| Path | Enters via | `punch_time` source | `source` | Affected by Phase 1? |
|---|---|---|---|---|
| Web self-punch | `PunchService.record_punch` | client, editable | client or `"WEB"` | **YES — becomes server-stamped** |
| Web on-behalf | `PunchService.record_punch` | client, editable | client or `"ADMIN"` | **YES — becomes explicit, bounded, permissioned** |
| Regularization apply | **direct** `self._punch_repo.insert` (`service.py:4108-4122`) | `requested.requested_time` | hard-coded `"REGULARIZATION"` | **NO — bypasses the schema entirely** |
| Device / import / API | **do not exist** | — | — | n/a |

> **This is load-bearing for the change map.** Restricting client-asserted `source` at the API
> boundary cannot break the regularization path, because that path never touches `PunchCreate`.
> `'REGULARIZATION'` is in the live DB `CHECK` (**VERIFIED** via `pg_constraint`) and the apply
> path writes it directly.

## 2.6 Scheduling — the gap

`core/celery_app.py` defines **four** beat entries, all `leave.*`. **No `attendance.*` task exists
anywhere.** `attendance_day` rows materialise only when someone calls
`POST /attendance/days/calculate` or `/recompute`.

Two assets already exist and should be reused rather than reinvented (§14):

- **Celery is already India-scheduled.** `timezone=settings.app_timezone_default` (= `Asia/Kolkata`)
  with `enable_utc=True` (`celery_app.py:18-19`). Beat crontabs already fire on IST wall-clock.
- **A two-tier per-tenant fan-out pattern is established and documented.**
  `modules/leave/tasks.py` — a no-arg Beat entrypoint enumerates active companies and dispatches
  one per-company task through `session_scope(company_id=…)`, keeping RLS intact.

## 2.7 Period lock

`_ensure_date_open` (`service.py:1915-1930`) is called by punch ingestion, roster writes,
regularization submit, and OT approve/reject. Closing a period sets `AttendanceDay.is_locked=true`
across its range via `AttendanceDayRepository.bulk_lock` (`repository.py:1222`) — **this is real
historical protection and it already works.** `calculate()` refuses a locked day
(`service.py:2511`).

The one deviation: the **punch** path checks the **UTC civil date** of `punch_time`
(`service.py:2347`), documented as WD-30. **VERIFIED:** `2026-10-01 05:00 IST` →
`2026-09-30T23:30Z` → lock-checked against **September**.

## 2.8 Test and CI state

| Item | State | Evidence |
|---|---|---|
| Unit tests | **362, all passing in 1.11 s** | **VERIFIED** — `.venv/bin/python -m pytest tests/unit -q` |
| Integration + security tests | **783** | count over `tests/integration` + `tests/security` |
| CI PostgreSQL / Redis | **none provisioned** | `.github/workflows/ci.yml` has no `services:` block |
| CI migrations | **never run** | no alembic step |
| CI frontend job | **none** | only one job, `api` — **NEW-06** |
| Web test runner | exists, unused by CI | `apps/web/package.json` → `"test": "vitest run"`; `*.test.tsx` present |
| DST tests | **zero** | `America/New_York`/`Europe/London` appear only as *arguments* to the precedence test |

`ci.yml` runs bare `uv run pytest` with `testpaths = ["tests"]`, pointing `DATABASE_URL` at
`localhost:5433` — a host that does not exist on the runner. There is **no skip guard** in any
`conftest.py`. The 783 integration tests therefore cannot pass in CI. **`TST-001` confirmed.**

## 2.9 Documentation-vs-code discrepancies

Reported, **not silently resolved**, per the brief.

| ID | Documentation says | Code / data says | Consequence |
|---|---|---|---|
| **DOC-D1** | TZ-07 / F-09: `todayIso()` is *"Display only — never reaches a calculation"* | `employee-attendance-panel.tsx:78` posts it as the `date` of `/attendance/days/calculate` | **Upgrades TZ-07 from P2 cosmetic to P1 functional.** Between 00:00–05:29 IST "Calculate today" computes yesterday. |
| **DOC-D2** | F-22: *"every timezone column is validated against `available_timezones()` at the schema layer"* | `ShiftVersionCreate`/`Update.timezone` have `max_length=64` only; publish validates times but not zone | **NEW-01.** `'IST'` accepted → `ZoneInfoNotFoundError` → HTTP 500. **VERIFIED both halves.** |
| **DOC-D3** | Remediation §13.1 lists the UTC month-start only at `leave/service.py:1990` | A second identical site at `attendance/service.py:3558` (regularization monthly cap) | Fixing only the listed site leaves the attendance cap counting by UTC month. |
| **DOC-D4** | *"every default is `Asia/Kolkata`"*; *"zero tenants today"* outside IST | Dev DB: **3 companies `Asia/Calcutta`** (real `/register` rows, 2026-09-12), **11 branches `UTC`**, **11 shift_versions `UTC`**, **all 10 `attendance_day` rows computed at `UTC`** | **NEW-03.** A naive `== "Asia/Kolkata"` invariant breaks on day one. |
| **DOC-D5** | TZ-07 names one `todayIso()` in `format.ts` | A second private copy at `policy-resolution/page.tsx:27` | **NEW-05.** Fixing the shared helper leaves this one wrong. |
| **DOC-D6** | Rule matrix C1/C2 cite `calculation.py:263-267` / `:275`; debt register `PAY-013` cites `service.py:601-608` | Actual: `calculation.py:294-298` / `:306`; `organisation/service.py:702-709` | Line drift only; cited symbols are correct. Fix in the doc pass (§15, `R-DOC-05`). |
| **DOC-D7** | Task brief names `docs/audits/ATTENDANCE_TIMEZONE_CLIENT_DECISION_REGISTER.md` | Does not exist; register is under `docs/business-rules/attendance/` | Either create the alias or correct the reference. |
| **DOC-D8** | Audits describe `/register` as an India product surface | `CompanyRegistrationRequest` accepts **any** IANA zone, anonymously | **NEW-04.** The India invariant has an open public door. |

---

# 3. TARGET ARCHITECTURE (INDIA V1)

```text
BROWSER                      punch-entry-dialog.tsx  (SELF-PUNCH MODE)
  NO time field. A "Punch In / Punch Out" button only.
  Body: { direction }                          ── no punch_time, no source, no timezone
        │
        │  (ADMIN MODE — separate, permission-gated surface)
        │  Body: { employee_id, direction, punch_time (offset REQUIRED), reference (REQUIRED) }
        ▼
SCHEMA     PunchCreateSelf   — extra="forbid"; punch_time and source are NOT fields at all
           PunchCreateOnBehalf — punch_time: AwareDatetime (REQUIRED), bounded, no source field
        ▼
SERVICE    request_time = datetime.now(UTC)          ── the single trust anchor
           SELF     : punch_time = request_time      ── client value cannot be supplied
           ON-BEHALF: punch_time = body.punch_time   ── must be aware; not future; within
                                                        backdating window; period OPEN
           source   = SERVER-ASSIGNED from the authenticated context, always
           raw_payload = { submitted_offset, user_agent, client_ip, client_version }
        ▼
DB         punch.punch_time TIMESTAMPTZ (event)  +  punch.created_at TIMESTAMPTZ (receipt)
           append-only, RLS, never mutated (WD-11)
        ▼
SCHEDULER  attendance.run_daily_calculation  (Celery Beat, IST crontab — already IST)
             └─ fan-out per company ─ attendance.calculate_company(company_id, trailing N days)
           + synchronous best-effort calculate on punch (non-blocking, failure-tolerant)
        ▼
ENGINE     UNCHANGED, except match_breaks becomes midnight-aware
           timezone resolution UNCHANGED — resolves to Asia/Kolkata for every India tenant
        ▼
GUARD      Company.timezone / Branch.timezone immutable once computed attendance exists
           (escape hatch: company.status == 'TRIAL' AND zero computed days)
           ShiftVersion.timezone validated as IANA at create / update / publish
        ▼
WEB        formatClockTime(iso, tz)  ->  "09:05 IST"     ── always labelled, never the browser
           businessToday(tz)         ->  IST civil date  ── replaces todayIso() everywhere
```

## 3.1 The three instants — modelled explicitly

| Concept | Meaning | Column | Change |
|---|---|---|---|
| **EVENT TIME** | When the human punched | `punch.punch_time` | Server-stamped for self-service; client-supplied and bounded for admin |
| **REQUEST TIME** | When the server received it — the trust anchor | `punch.created_at` (set explicitly at `service.py:2359`) | **Unchanged in V1.** See §3.2. |
| **RECORD CREATED** | When the row was written | DB `DEFAULT now()`, always overridden | **Unchanged in V1** |

## 3.2 A deliberate simplification for V1

The remediation spec (§10.1) argues REQUEST TIME and RECORD CREATED must become two distinct
columns. **This plan does not split them in V1.** Under server-authoritative self-punch,
`punch_time == created_at` by construction for the dominant path, so the pair carries no
information there; for the admin path the existing `created_at` already *is* the request time.

**What is required instead:** a code comment and a test asserting `created_at` is set by the
application and never by the DB default, so a future batch-import path cannot quietly overwrite the
anchor. Splitting the columns becomes necessary only when a device or offline ingestion path ships
(`DEC-TZ-15`) — **recorded as deferred, with the reason, so it is a choice and not an omission.**

---

# 4. APPROVED V1 POLICY

| # | Policy | Basis |
|---|---|---|
| P-01 | Business timezone is **`Asia/Kolkata`** for all attendance operations | Task §3 |
| P-02 | Online self-service punch time is **server-generated**; client clock is never authoritative | Task §3, `DEC-TZ-01` = A |
| P-03 | Client timezone is **never** authoritative; the backend resolves through WD-06, which terminates at `Asia/Kolkata` | Task §8 |
| P-04 | Naive (offset-less) timestamps are **rejected with 422** wherever the contract requires an instant | Task §6, `DEC-TZ-04` |
| P-05 | Future punch timestamps are **rejected** | `DEC-TZ-03` |
| P-06 | `punch.source` is **server-assigned** from the authenticated context | `DEC-TZ-05` |
| P-07 | Admin/on-behalf entry **keeps** an explicit supplied time, bounded, permissioned, audited, and reason-required | Task §7 |
| P-08 | Offline attendance is **not supported**; the UI fails loudly and records nothing | Task §4, `DEC-TZ-15` row 1 = (a) |
| P-09 | Storage stays UTC `TIMESTAMPTZ`; no naive local column is ever introduced | Task §5, `DEC-010` |
| P-10 | Company/branch timezone is **effectively locked** once computed attendance exists; the columns are retained, not removed | Task §9, `DEC-TZ-13` = A |
| P-11 | A configuration change **cannot** silently alter historical attendance | Task §10, `WD-11` |
| P-12 | Attendance date is the shift's start date in `Asia/Kolkata` | Task §11 — already true |
| P-13 | Attendance-period boundaries are India business dates | Task §12 — see `OD-1` |
| P-14 | Attendance times display in `Asia/Kolkata` with a visible `IST` label | Task §13, `DEC-TZ-08` = A |
| P-15 | The raw punch instant is never overwritten by a policy-adjusted value | Task §14, `WD-11` |
| P-16 | Punch rounding is **not** implemented in this workstream | Task §15, `DEC-TZ-06` open |
| P-17 | Cross-midnight breaks match correctly; the break engine is otherwise untouched | Task §16 |
| P-18 | Night-OT business policy is **not** invented here | Task §17, `DEC-TZ-07` open |
| P-19 | Immediate calculation + scheduled reconciliation, built on the existing Celery pattern | Task §18 |
| P-20 | Server OS timezone **cannot** change attendance results — a standing regression requirement | Task §21, `PC-01` |
| P-21 | DST policy, employee-level timezone, and multi-country rules are **deferred** | Task §2 |

---

# 5. CODE IMPACT ANALYSIS

## 5.1 Backend — files that change

| File | LOC | Nature of change | Phase |
|---|---|---|---|
| `apps/api/src/hrms/modules/attendance/schemas.py` | 2038 | Split `PunchCreate`; `AwareDatetime`; drop client `source`; bound `requested_time` | 1 |
| `apps/api/src/hrms/modules/attendance/service.py` | 5480 | `record_punch` rewrite; `business_today()` adoption; lock-date basis; sync calculate hook | 1, 3, 6 |
| `apps/api/src/hrms/modules/attendance/router.py` | 1556 | Two punch endpoints; pass `raw_payload` context | 1 |
| `apps/api/src/hrms/modules/attendance/calculation.py` | 1519 | **`match_breaks` only** | 4 |
| `apps/api/src/hrms/modules/attendance/repository.py` | 2017 | Orphan-punch query; `SELECT … FOR UPDATE` on recompute | 6 |
| `apps/api/src/hrms/modules/attendance/exceptions.py` | 643 | New typed errors | 1, 2 |
| `apps/api/src/hrms/modules/attendance/tasks.py` | **new** | Beat entrypoint + per-company task | 6 |
| `apps/api/src/hrms/modules/organisation/service.py` | — | Implement the guard; call it from `update_branch` | 2 |
| `apps/api/src/hrms/modules/organisation/schemas.py` | — | IANA validator on `ShiftVersionCreate`/`Update`; India gate on registration | 2 |
| `apps/api/src/hrms/modules/organisation/exceptions.py` | — | `TimezoneChangeNotAllowedError`, `InvalidTimezoneError` | 2 |
| `apps/api/src/hrms/modules/leave/service.py` | — | `business_today()` at 3 sites | 3 |
| `apps/api/src/hrms/shared/business_time.py` | **new** | `business_today()`, `business_month_start()` | 3 |
| `apps/api/src/hrms/core/celery_app.py` | — | One beat entry | 6 |
| `apps/api/Dockerfile` | 27 | `ENV TZ=UTC` | 1 |

## 5.2 Backend — files that must NOT change

| File / area | Why |
|---|---|
| `calculation.py` outside `match_breaks` | Proven correct under 4 server timezones and 4 DST transitions; every change is pure regression risk |
| `resolve_timezone` | LOCKED WD-06; TEST-PROVEN; India resolves to `Asia/Kolkata` through it already |
| `_local_to_utc`, `scheduled_span_utc`, `punch_window_utc` | The single conversion point. Correct. |
| `_format_timestamp` (`schemas.py:89`) | Already emits `…Z` |
| All `TIMESTAMPTZ` columns and `TimestampMixin` | `DEC-010`, correct |
| Regularization apply punch insert (`service.py:4108-4122`) | Already server-assigns `source="REGULARIZATION"` |
| `AttendancePeriodService` / `bulk_lock` | Real historical protection, already working |

## 5.3 Frontend

| File | Change | Phase |
|---|---|---|
| `apps/web/src/lib/attendance/format.ts` | `formatClockTime(iso, tz)`, `formatDateTime(iso, tz)`, `businessToday(tz)`; delete `todayIso()` | 3, 5 |
| `apps/web/src/lib/company/company-context.tsx` *(new or extend auth context)* | Carry `company.timezone` client-side | 5 |
| `apps/web/src/components/attendance/punch-entry-dialog.tsx` | Split into self (no time field) and admin (time + reason) modes | 1 |
| `apps/web/src/app/app/attendance/page.tsx` | Self-punch button; `businessToday` | 1, 3 |
| `apps/web/src/components/attendance/employee-attendance-panel.tsx` | **`:78` — stop sending a UTC date to calculate (NEW-02)**; formatter args | 3, 5 |
| `apps/web/src/app/app/attendance/[id]/page.tsx` | 8 `formatDateTime` calls + dual-zone header | 5 |
| `apps/web/src/app/app/regularizations/[id]/page.tsx` | 6 calls | 5 |
| `apps/web/src/app/app/attendance-periods/[id]/page.tsx` | 3 calls | 5 |
| `apps/web/src/app/app/overtime/[id]/page.tsx` | 2 calls | 5 |
| `apps/web/src/app/app/leave-applications/[id]/page.tsx` | 4 calls | 5 |
| `apps/web/src/app/app/leave-balances/page.tsx` | 1 call | 5 |
| `apps/web/src/app/app/overtime/page.tsx`, `regularizations/page.tsx`, `rosters/page.tsx`, `leave-applications/page.tsx`, `attendance/page.tsx` | `todayIso()` → `businessToday(tz)` | 3 |
| `apps/web/src/components/attendance-period/create-period-dialog.tsx` | 4 `todayIso()` calls | 3 |
| `apps/web/src/app/app/policy-resolution/page.tsx` | **`:27` — remove the duplicate local `todayIso()` (NEW-05)** | 3 |
| `apps/web/src/app/register/page.tsx` + `apps/web/src/lib/timezones.ts` | India gate on the timezone selector (**NEW-04**) | 2 |

**Total frontend formatter call sites: 24 across 9 files. `todayIso()` call sites: 14 across 7 files
(including the duplicate).**

---

# 6. DATABASE IMPACT ANALYSIS

## 6.1 Existing data — inspected, not assumed

Queried read-only against the running dev PostgreSQL on 2026-09-15. **VERIFIED.**

| Table | Column | Values found |
|---|---|---|
| `company` | `timezone` | `Asia/Kolkata` × 403, **`Asia/Calcutta` × 3** |
| `branch` | `timezone` | `NULL` × 79, **`UTC` × 11** |
| `shift_version` | `timezone` | **`UTC` × 11**, `NULL` × 7 |
| `attendance_day` | `timezone` | **`UTC` × 10** (every existing row) |
| `punch` | — | 24 rows, `2026-08-10T09:00Z` … `2026-08-10T19:00Z` |
| `attendance_day` | `attendance_date` | 10 rows, all `2026-08-10` |
| `attendance_period` | — | 7 rows |

Two distinct populations:

- **The `UTC` branches and shift versions are integration-test fixture rows** (all named `HQ`,
  under companies whose own timezone is `Asia/Kolkata`). They are not a production signal — but
  they *are* what a naive backfill would hit, and they prove the WD-06 chain is exercised with a
  non-IST value in every test run.
- **The three `Asia/Calcutta` companies are real registrations** (`TRIAL`, 2026-09-12), produced by
  `resolveDefaultTimezone()` in `apps/web/src/lib/timezones.ts`, which deliberately accepts
  whichever alias the browser's ICU reports. **This will recur in production.**

> **Production data state: NOT VERIFIED.** No production database is reachable from this
> repository. §13.1 makes inspecting it a hard precondition of Phase 2.

## 6.2 Migration verdict

> ### **No database migration is required for Phases 0–5.**

Nothing in the target policy needs a new column, a widened type, or a changed constraint. In
particular:

- Do **not** add a `CHECK (timezone = 'Asia/Kolkata')`. It would fail immediately on the three
  `Asia/Calcutta` rows and on every test fixture, and it would have to be dropped for
  international expansion, which the brief explicitly says to keep possible.
- Do **not** add a `punch_time <= now()` CHECK. Postgres forbids non-immutable functions in a
  CHECK, and validation belongs at the API boundary where a typed 422 can be returned (§7.2).
- Do **not** backfill `attendance_day.timezone`. Under P-11 historical rows are evidence, not
  inputs.

## 6.3 Data-hygiene tasks (not migrations)

| ID | Task | Phase | Reversible |
|---|---|---|---|
| `DH-1` | **Report** (do not mutate) every `company`/`branch`/`shift_version` row whose timezone is not `Asia/Kolkata`, per environment. A read-only script under `apps/api/scripts/`. | 2 — **precondition** | n/a |
| `DH-2` | Normalise `Asia/Calcutta` → `Asia/Kolkata` **only** for companies with **zero** computed `attendance_day` rows, one-off, audited, reversible from the audit log. Companies with attendance are left alone and flagged for manual review. | 2 — after `DH-1` | **YES** — old value in `audit_log` |
| `DH-3` | Decide per-row what to do with non-IST `branch`/`shift_version` timezones found by `DH-1` in a real environment. **No blanket rewrite.** | 2 | — |

## 6.4 Optional later migration

| Migration | Trigger | Not now because |
|---|---|---|
| `shift_break.crosses_midnight BOOLEAN NOT NULL DEFAULT false` (`R-SB-01`) | After Phase 4 ships and is stable | Phase 4's fix works without it; the column makes the roll *declared* rather than inferred, matching `shift_version.is_cross_midnight`. Additive, safe, P2. |
| Split `punch.request_time` from `created_at` | First device/offline ingestion path | §3.2 |

---

# 7. API IMPACT ANALYSIS

## 7.1 Endpoint-by-endpoint client-timestamp audit

Exactly the table the brief's §7 asks for. Every attendance endpoint that accepts a client time.

| Endpoint | Client time accepted today | Should remain? | New behaviour |
|---|---|---|---|
| `POST /v1/attendance/punches` — **self** | ✔ `punch_time`, unbounded, offset optional | **NO** | `punch_time` is **not a field**; `extra="forbid"` → 422 if sent. Server stamps `datetime.now(UTC)`. |
| `POST /v1/attendance/punches` — **on-behalf** | ✔ same field, same laxity | **YES — this is the workflow's purpose** | `punch_time` **required** and `AwareDatetime`; rejected if future, outside the backdating window, or in a `CLOSED` period. Requires `ATTENDANCE.PUNCH_ON_BEHALF`. `reference` becomes required (the reason). |
| `POST /v1/attendance/punches` — `source` | ✔ any of 7 values from any caller | **NO** | Field removed from the request schema. Server assigns `WEB` \| `MOBILE` \| `ADMIN` from the authenticated context. |
| `POST /v1/attendance/punches` — `idempotency_key` | ✔ | **YES** | Unchanged. Replay safety; the web UI still never sends one. |
| `POST /regularizations` — `requested_punches[].requested_time` | ✔ **entirely unvalidated** (`schemas.py:1475`) | **YES — it is a historical assertion** | `AwareDatetime`; must fall inside the shift's padded window for `attendance_date`; must not be future. (`F-12`) |
| `POST /regularizations` — `attendance_date` | ✔ | **YES** | Future-date check moves to India-local `business_today()` (`TZ-06`). |
| `POST /attendance/days/calculate?date=` | ✔ date param | **YES** | Unchanged server-side. **The web caller stops passing a UTC date** (**NEW-02**). |
| `GET /attendance/punches?date_from&date_to` | ✔ | **YES** | Unchanged — documented UTC filter (`F-20`). Document it client-facing. |
| `GET /attendance/days?…` | ✔ | **YES** | Unchanged — local dates. |
| `POST /attendance-periods` — `period_start`/`_end` | ✔ plain `DATE` | **YES** | Unchanged; already India business dates by construction. |
| `PATCH /company/profile` — `timezone` | ✔ | **YES, guarded** | 409 `TIMEZONE_CHANGE_NOT_ALLOWED` once computed attendance exists. |
| `PATCH /branches/{id}` — `timezone` | ✔ **unguarded** | **YES, guarded** | Same guard, now actually called. |
| `POST /shifts/{id}/versions` — `timezone` | ✔ **no IANA validation** | **YES, validated** | 422 on a non-IANA identifier (**NEW-01**). |
| `POST /register` — `timezone` | ✔ any IANA zone, anonymous | **Narrowed** | India-only allow-list for V1 (**NEW-04**), configurable so expansion needs no code change. |

## 7.2 Validation bounds

| Bound | Rule | Status | Value |
|---|---|---|---|
| Offset required | Naive `punch_time` / `requested_time` → **422** | **Implement** | n/a |
| Future | `punch_time > request_time + T` → **422** | **Implement** | `T = 120s` |
| Far past | Before the later of employment start and the earliest `OPEN` period → **422** | **Implement** | derived |
| Closed period | Period `CLOSED` → **409** | Exists | see `OD-1` |
| Backdating window | On-behalf beyond the configured window → **422** | **Implement** | policy-driven |
| Skew | Self-service clock skew | **Not applicable** — no client time is accepted | — |
| `source` | Server-assigned | **Implement** | — |

> Under P-02 the skew tolerance (`DEC-TZ-02`) becomes **moot for self-service**, which is the whole
> point of choosing Option A: the control is structural rather than numeric. It returns only if a
> device ingestion path is ever built.

## 7.3 Non-API infrastructure changes bundled into Phase 1

| Change | Why now |
|---|---|
| `ENV TZ=UTC` in `apps/api/Dockerfile` | Costs nothing (PC-01), makes dev and prod agree, defence in depth behind the naive-rejection fix |
| `TZ: UTC` in the CI job env | Same |

`tzdata` pinning and base-image digest pinning (`TZ-05`) are **deferred** — dormant for India.
Two cheap parts are kept: declare `tzdata` as a direct dependency in `pyproject.toml` (one line,
removes an undeclared transitive dependency on a correctness input) and log the resolved tzdata
version at startup.

---

# 8. FRONTEND / MOBILE IMPACT ANALYSIS

## 8.1 Mobile

**There is no mobile application in this repository.** `apps/` contains `api` and `web` only; no
`pubspec.yaml`, no React Native, no native project. `'MOBILE'` and `'DEVICE'` are accepted
`punch.source` values and `idempotency_key` exists, so the schema anticipates one.

**Therefore:** this plan defines the **backend contract a future mobile client must satisfy**, and
builds nothing mobile.

## 8.2 The three attendance surfaces

| Surface | Auth | Punch time | Timezone | Status |
|---|---|---|---|---|
| **Web — self-service** | Employee, `ATTENDANCE.PUNCH` | **Server-stamped.** No time field. | Display IST | 🔧 Phase 1 |
| **Web — admin / on-behalf** | `ATTENDANCE.PUNCH_ON_BEHALF` | **Supplied, aware, bounded, reason required** | Input and display IST | 🔧 Phase 1 |
| **Mobile — future** | Employee | **Server-stamped**, online only; fails loudly offline | Display IST | ⏸️ Deferred; contract fixed here |

## 8.3 The dialog split

`punch-entry-dialog.tsx` today is **one component serving both acts** — it shows an employee picker
when `employeeId` is absent (admin, from `attendance/page.tsx:307`) and locks it when present
(self, from `employee-attendance-panel.tsx:198`) — and both get the same editable
`<input type="datetime-local">`. That conflation is `F-02`.

- **Self mode** — no time input at all. One `Punch In` / `Punch Out` action. On network failure:
  an explicit, non-dismissible error saying the punch was **not** recorded (P-08). The existing
  toast at `:101-106` already fails loudly and nothing is queued — **preserve that**, do not
  "improve" it into a retry queue.
- **Admin mode** — keeps the time input, adds a **required** reason, and labels the field
  `Punch time (IST)`.

## 8.4 Display

`formatClockTime` / `formatDateTime` gain a required timezone argument; every call site passes the
attendance timezone (`attendance_day.timezone`, already on the wire at `schemas.py:1391` and
already shown as a subtitle at `attendance/[id]/page.tsx:110`) or, for non-attendance timestamps
such as `created_at` and audit entries, the company timezone.

Per `DEC-TZ-08`'s recommendation, **dual-zone rendering is applied to the day-detail page only**;
dense lists and grids stay single-zone with an `IST` label.

---

# 9. ATTENDANCE-ENGINE IMPACT ANALYSIS

| Engine concern | Impact | Change |
|---|---|---|
| `resolve_timezone` (WD-06) | none | **none** |
| `_local_to_utc` | none | **none** |
| `scheduled_span_utc` / `punch_window_utc` | none | **none** |
| `calendar_day_window_utc` | none | **none** |
| `evaluate_day` | none | **none** |
| `pair_punches` / `collapse_duplicate_punches` | none | **none** |
| `presence_span` / `worked_minutes_from_gross` | none | **none** |
| `detect_overtime` / `classify_ot_day` | none | **none** — night-OT is `DEC-TZ-07`, deferred |
| `apply_rounding` | none | **none** — `DEC-TZ-06`, deferred, stays dead and documented |
| `lookup_band` / core hours | none | **none** |
| **`match_breaks`** | **the only engine change** | §10.4 |

Downstream of Phase 4, computed values change **only** for days that have a punched gap inside a
midnight-spanning break window. Nothing else in the engine moves.

---

# 10. THE FIVE CORE REMEDIATIONS IN DETAIL

## 10.1 Timestamp authority (P-02, P-04, P-06, P-07)

**Current — VERIFIED by executing the shipped `PunchCreate`:**

```text
PunchCreate(direction="IN", punch_time="2026-09-15T09:00:00")        -> ACCEPTED, tzinfo=None
PunchCreate(direction="IN", punch_time="2099-01-01T00:00:00Z",
            source="DEVICE")                                          -> ACCEPTED
PunchCreate(direction="IN", punch_time="1900-01-01T00:00:00Z",
            source="REGULARIZATION")                                  -> ACCEPTED
```

**Target:**

```python
# schemas.py — two schemas, not one
class PunchCreateSelf(BaseModel):
    model_config = ConfigDict(extra="forbid")   # punch_time / source / timezone -> 422
    direction: str
    reference: str | None = Field(default=None, max_length=200)
    idempotency_key: str | None = Field(default=None, max_length=100)

class PunchCreateOnBehalf(BaseModel):
    model_config = ConfigDict(extra="forbid")
    employee_id: UUID
    direction: str
    punch_time: AwareDatetime            # REQUIRED; naive -> 422
    reference: str = Field(min_length=1, max_length=200)   # the reason
    idempotency_key: str | None = Field(default=None, max_length=100)
```

Two schemas beat one with conditional validators: the *permission* already decides which act is
taking place (`router.py:769-775`), so the request shape should follow it rather than being
re-derived inside a validator. `extra="forbid"` is already on `PunchCreate` (`schemas.py:1231`), so
a client that keeps sending `punch_time` on the self path gets a clean 422, not a silent ignore.

**`source` is the linchpin.** Without server-assignment, every per-path rule above is advisory — a
caller simply asserts a different `source` and takes the permissive branch. **It must ship in the
same change, not after.**

## 10.2 India timezone invariant (P-01, P-03, P-10)

Four parts, in dependency order:

1. **Validate `ShiftVersion.timezone`** (**NEW-01**). An IANA validator on `ShiftVersionCreate` /
   `ShiftVersionUpdate` mirroring `BranchCreate`'s (`organisation/schemas.py:691-695`), plus a
   publish-time check in `_validate_and_derive_for_publish`. **Independent of everything else and
   the cheapest P0 in the plan.**
2. **Implement `_assert_timezone_change_allowed`** and **call it from `update_branch`**:
   ```text
   refuse when  any computed attendance_day exists for the affected scope
   permit when  company.status == 'TRIAL'  OR  zero computed attendance days
   refuse always when any affected attendance_period is CLOSED   (non-negotiable)
   ```
   The `TRIAL` escape hatch reuses the **existing currency-lock precedent**
   (`organisation/service.py:654-656`) rather than inventing a new concept.
3. **Gate the registration timezone** (**NEW-04**) behind a settings-driven allow-list
   (`allowed_company_timezones: list[str] = ["Asia/Kolkata"]`), so expansion is configuration, not
   a code change. `Asia/Calcutta` must be in the allow-list or canonicalised on input — see 4.
4. **Canonicalise aliases** (**NEW-03**). `zoneinfo` treats `Asia/Calcutta` and `Asia/Kolkata` as
   the same zone, so calculations are unaffected — but string equality is not. Normalise on write,
   and **never write an invariant as `tz == "Asia/Kolkata"`**; compare resolved offsets or use an
   explicit alias set.

> **Explicitly not done:** removing `Branch.timezone` / `ShiftVersion.timezone`, or hard-coding
> `Asia/Kolkata` in the engine. The brief forbids the first and the second would delete the one
> property (P-20) that makes international expansion possible without rewriting the engine.

## 10.3 Historical protection (P-11)

Five independent mechanisms. Three already exist.

| # | Mechanism | State |
|---|---|---|
| 1 | Punches are append-only; corrections are new rows (WD-11) | ✅ exists |
| 2 | Version FKs + `computation_snapshot` on every `attendance_day` | ✅ exists |
| 3 | `CLOSED` period → `bulk_lock` → `calculate()` refuses the day | ✅ exists |
| 4 | **Timezone cannot change once computed attendance exists** | 🔧 Phase 2 |
| 5 | **No torn configuration read** (`TZ-09`) | 🔧 closed as a side effect of 4 |

**The residual gap after Phase 2:** a day that is computed and reviewed but whose period is still
`OPEN` can still legitimately change on recompute — by design (an approved regularization *should*
change it). Mechanism 4 removes timezone from the set of inputs that can move underneath it.

**What this plan deliberately does not build:** effective-dated timezone columns (`DEC-TZ-13`
Option B). For a single-timezone India V1 there is no relocation case to model, and the
`ShiftVersion` pattern remains in the codebase to copy from if a tenant ever genuinely relocates.
**Recorded as a deferral with its trigger, not an omission.**

## 10.4 Cross-midnight breaks (P-17)

**Reproduced for this plan. VERIFIED:**

```text
break 23:30–00:30 (paid, max 30m), gap 23:45–00:05 IST
  -> MatchedBreak(minutes=20, is_paid=False, is_excess=False, shift_break_id=None)   ← WRONG
break 13:00–14:00 (paid), gap 13:15 IST
  -> MatchedBreak(minutes=20, is_paid=True,  shift_break_id=<uuid>)                  ← correct
```

**Root cause** (`calculation.py:588-601`): a chained inequality on a `time` value,
`start_time <= gap_start_local <= end_time`, which assumes `start <= end`. For `23:30–00:30`,
`23:30 <= 23:45` is `True` and `23:45 <= 00:30` is `False`. Structurally, `shift_break` is the one
place in the schema with no cross-midnight flag — unlike `shift_version.is_cross_midnight` and
`shift_duty_block.crosses_midnight`.

**Fix — approach B from the remediation spec (§12.6): compare UTC instants, not time-of-day.**
Build the break's UTC span from the attendance date, rolling the end forward when it precedes the
start, and compare `gap_start` directly. This is how `_core_hours_breached` already solves the same
problem in the same module (`calculation.py:1097-1099`).

**Two constraints on the fix:**

- **Preserve the `UTC → local` conversion order** (`calculation.py:586`). That order is `PC-15` and
  it is correct; a gap at the ambiguous `01:10` local on a fall-back night matches its `01:00–01:30`
  break. Re-run that scenario as a guard even though India has no DST — it protects the *order*.
- **Do not bundle `ATT-009`.** `match_breaks` compares only the gap's **start**, so a gap that
  starts outside a window and ends inside it is unmatched even on a day shift. That is a separate,
  pre-existing P3 limitation. Fixing it here would change computed attendance for **day** shifts
  too, widening the blast radius of a night-shift fix. **Out of scope; keep it as `ATT-009`.**

**Blast radius:** days with a punched gap inside a midnight-spanning break window. `worked_minutes`
rises, `paid_day_fraction` rises, OT may appear. Always **in the employee's favour** — the current
bug only ever under-credits. Still a computed-attendance change: recompute affected open days
deliberately and with notice (§18).

## 10.5 Calculation and reconciliation (P-19)

**Current:** no `attendance.*` task exists. An employee who punches in and out has **no attendance
row** until something asks for one, so a period cannot be finalized and Payroll has no input
(`F-14` / `PAY-001`, 🔴 P0).

**Target — build on what exists, invent nothing:**

```text
1. IMMEDIATE (Phase 6a)
   After a successful punch insert, best-effort calculate for the resolved attendance date.
   - Non-blocking: wrapped so a calculation failure NEVER fails the punch write.
     A punch is a fact; a calculation is a derivation. Losing the fact is unacceptable.
   - Idempotent by construction — calculate() is full-row replacement (WD-10).

2. RECONCILIATION (Phase 6b)   modules/attendance/tasks.py  ← NEW FILE
   attendance.run_daily_calculation        Beat entrypoint, no args
     └─ enumerates active companies (the leave/tasks.py pattern, verbatim)
        └─ attendance.calculate_company(company_id)
             for each employee with an active employment,
             for each date in [business_today - N, business_today], N = 3:
                 calculate(...)   skipping locked days and CLOSED periods

3. SCHEDULE
   crontab(minute=30, hour=9) under the existing celery timezone = Asia/Kolkata
   -> 09:30 IST daily. After the latest cross-midnight shift completes (08:00 IST is the
      outer edge of a 22:00-06:00 shift's +2h pad) and before the working day's reviews begin.
```

**Why a trailing 3-day window:** it absorbs late punches, approved regularizations, and
cross-midnight days that were incomplete at the previous run — all of which `WD-11` expects to
trigger a recompute. Every run is idempotent, so a repeated or missed run costs nothing.

**Concurrency (§19 of the brief, `F-15`).** Introducing a scheduled recompute is exactly what makes
the missing row lock matter: the nightly job and an interactive recompute can now collide on one
employee-date. Add `SELECT … FOR UPDATE` on `attendance_day` **in Phase 6, with the job, not
before** — the brief is right that a lock should not be added before a concurrency path exists.
**Requires a lock-ordering review against the period-lock path to avoid deadlocks.**

**`OPS-006` — Celery Beat has no leader election.** Duplicate firing is possible by design. The
job's idempotency makes this survivable; it must be stated in the runbook, not discovered.

---

# 11. SECURITY IMPACT

## 11.1 What Phase 1 closes

| Attack | Today | After Phase 1 |
|---|---|---|
| Employee types an earlier punch time to erase lateness | **Works** — a supported UI affordance (`R-1`, likelihood *certain*) | **Structurally impossible** — no field to type into |
| Employee fabricates overtime with a later punch-out | **Works** (`R-2`) | **Impossible** on the self path |
| Device/browser clock manipulation | **Works** | **Irrelevant** — the client clock is never consulted |
| Timezone manipulation from the client | **Works** — a naive timestamp shifts the stored instant | **Rejected** — offset required, resolution is server-side |
| Forged `source` (`"DEVICE"` on a hand-typed punch) | **Works** (`F-11`) | **Rejected** — server-assigned |
| Backdating into any open period | **Works** | **Requires `PUNCH_ON_BEHALF`**, bounded, reasoned, audited |
| Punch for another employee | **Already prevented** — `_ensure_employee_visible` validates the *target* against the caller's `DataScope` | unchanged |
| Cross-tenant access | **Already prevented** — RLS forced + 404-on-cross-tenant | unchanged |

## 11.2 What Phase 1 does NOT close — state this plainly

> **Timestamp integrity is not identity integrity.**

| Residual risk | Why it survives | Owner |
|---|---|---|
| **Buddy punching** — A logs in as B, or punches from B's session | Server-stamped time proves *when*, never *who was physically present* | Biometric / face / device attestation — a **separate workstream**, explicitly out of scope (task §28) |
| **Remote punching** — punching from home for an on-site shift | No location check; `Branch.geofence_radius_m` is stored, editable, and read by **no punch path** (`F-19`) | `DEC-TZ-16`-shaped product decision; out of scope |
| **On-behalf abuse** — an admin backdates punches | Legitimate workflow, cannot be removed | Mitigated by permission + required reason + audit + a divergence report |
| **Replay** | `idempotency_key` guards exact resubmission only when the client supplies one; the web UI never does. Calculation-time duplicate collapsing is the load-bearing mechanism | Unchanged; adequate for V1 |
| **Session theft** | Out of scope | Identity workstream |

Face recognition and biometrics are **not** mixed into this workstream, per the brief.

## 11.3 Audit trail

Already strong and unchanged: `PUNCH_CREATED` audit entries with actor, IP and user-agent
(`router.py:786-787` → `service.py:2367-2383`); `punch` is append-only; `attendance_day` changes are
audited.

**One addition (Phase 1):** write `punch.raw_payload` — declared at `models.py:464` and
**never written by any code path** (`F-18`). Capture `submitted_offset` (when one was supplied),
`user_agent`, `client_ip` and client version. Without it, an on-behalf dispute has nothing to
review. **Coordinate with the PII retention policy (`PII-2`) — this captures identifying data.**

---

# 12. TEST IMPACT

## 12.1 Baseline — measured, not assumed

| Suite | Count | Runtime | Needs DB |
|---|---|---|---|
| `tests/unit` | **362, all passing** | **1.11 s** | no |
| `tests/integration` + `tests/security` | **783** | — | **yes** |
| `apps/web` vitest | present, **not run by CI** | — | no |

**VERIFIED:** `apps/api/.venv/bin/python -m pytest tests/unit -q` → `362 passed in 1.11s`.

> **Local-environment note.** `uv run pytest` in this working tree resolves a stale interpreter
> from a different checkout path and fails at import. Use the in-tree `.venv` directly, or repair
> the `uv` cache, before Phase 0. This is an environment defect, not a code defect.

## 12.2 Regression policy

**No existing test is deleted.** Where a Phase-1 contract change makes an existing test assert the
old behaviour, the test is **rewritten to assert the new contract in the same commit**, with the
old assertion preserved as a comment naming the phase that changed it. Any integration test that
posts a `punch_time` on the self path must move to the admin path or drop the field.

**Pre-audit required in Phase 0:** enumerate every test that sends `punch_time` or `source`, so the
Phase-1 blast radius is known before a line changes.

## 12.3 Coverage targets

| Group | Matrix scenarios | Today | Target |
|---|---|---|---|
| A — attendance-date boundaries | 11 | 0 | 11 |
| B — cross-midnight | 9 (+3 shapes) | 1 | 12 |
| C — DST | 12 | 0 | 9 (3 stay policy-undefined, deferred) |
| D — precedence | 6 | 2 | 6 |
| E — timezone change | 5 | 0 | 5 |
| F — period lock | 6 | 0 | 5 (1 is `OD-1`) |
| G — server TZ independence | 5 | 0 | 5 |
| H — ingestion validation | 7 | 0 | 12 (expanded, §17.3) |
| I — breaks | 4 | 1 | 4 |
| J — concurrency | 3 | 0 | 3 |
| **Total** | **68** | **4** | **≈ 72** |

---

# 13. CI IMPACT

## 13.1 Current state — audited

`.github/workflows/ci.yml`, one job (`api`): checkout → uv → Python 3.12 → `uv sync --all-groups`
→ ruff check → ruff format → mypy → `lint-imports` → `uv run pytest`.

| Question | Answer |
|---|---|
| Unit tests run? | ✔ yes |
| Integration tests run? | ✔ invoked — ✘ **cannot pass**: no PostgreSQL service, no skip guard |
| PostgreSQL provisioned? | ✘ **no** |
| Redis provisioned? | ✘ **no** |
| Migrations run? | ✘ **no** |
| Attendance tests gate merges? | ✘ unit only, in effect |
| Timezone tests gate merges? | ✘ none exist |
| Frontend job? | ✘ **none — NEW-06** |

## 13.2 Required changes (Phase 7 — but see §15)

```yaml
# .github/workflows/ci.yml — sketch, not final
jobs:
  api:
    services:
      postgres:
        image: postgres:16-alpine
        env: { POSTGRES_USER: hrms, POSTGRES_PASSWORD: hrms_dev_password, POSTGRES_DB: hrms_dev }
        ports: ["5433:5432"]
        options: >-
          --health-cmd "pg_isready -U hrms -d hrms_dev"
          --health-interval 5s --health-timeout 5s --health-retries 10
      redis:
        image: redis:7-alpine
        ports: ["6380:6379"]
        options: --health-cmd "redis-cli ping" --health-interval 5s --health-retries 10
    env:
      TZ: UTC                       # R-TZ-02b — pin the runner, not just the image
    steps:
      # ... existing steps ...
      - name: Apply RLS roles + init SQL
        run: ./infra/docker/postgres/init          # must mirror docker-compose exactly
      - name: Run migrations
        run: uv run alembic upgrade head
      - name: Tests
        run: uv run pytest                          # now genuinely runs all 1145

  web:                                              # NEW-06 — no such job exists today
    steps: [checkout, setup-node, npm ci, npm run lint, npm test]
```

**Two things the naive version gets wrong:**

1. **RLS role provisioning.** `docker-compose.yml` mounts `./infra/docker/postgres/init` as
   `docker-entrypoint-initdb.d`. A GitHub `services:` container does **not** run that. The RLS
   roles must be applied as an explicit step or the RLS tests will pass for the wrong reason.
   `TST-001` already flags that the CI role is a `BYPASSRLS` superuser — **do not reproduce that**;
   tests must run as the non-superuser application role, or tenant-isolation tests prove nothing.
2. **Branch protection.** Adding the jobs is not the gate. Both `api` and `web` must be **required
   status checks** on `main`, or the tests run and merges proceed anyway.

## 13.3 Sequencing consequence

> **`TST-001` is the true week-1 prerequisite for this entire plan.** Every integration test in §17
> — the timezone guard, period lock, concurrency, historical protection — is worthless as a
> *gate* until CI can run it. **Phase 7 is therefore pulled forward to run immediately after
> Phase 0**, before any behavioural change lands. The phase numbering is kept for traceability;
> the execution order in §15 is what governs.

---

# 14. MIGRATION PLAN

> ## **No database migration is required.**

Stated explicitly per the brief's §26. The audits mention migrations; the schema does not need one
for any Phase 0–5 change. §6.2 gives the reasoning per candidate.

**What replaces a migration:**

| Step | Type | Phase | Reversible |
|---|---|---|---|
| `DH-1` — read-only timezone inventory per environment | Script, no writes | 2, **precondition** | n/a |
| `DH-2` — `Asia/Calcutta` → `Asia/Kolkata`, zero-attendance companies only | One-off, audited | 2 | **YES** — audit log |
| `DH-3` — per-row decision on non-IST branch/shift rows | Manual review | 2 | n/a |
| **Post-Phase-4 recompute** — affected open days only | Data operation | 4 | **NO** — see §19.4 |
| Post-Phase-6 backfill — create missing `attendance_day` rows for the trailing window | Data operation | 6 | Additive; deletable |

**The Phase-4 recompute is the one genuinely irreversible data operation in this plan.**
`attendance_day` has no history table; a recompute overwrites `worked_minutes`,
`paid_day_fraction` and `late_minutes` in place. §19.4 defines the snapshot that makes it
recoverable.

---

# 15. BACKWARD COMPATIBILITY

## 15.1 Clients

| Client | Exists | Breaks on Phase 1? | Mitigation |
|---|---|---|---|
| Next.js web app | ✔ the only client | **YES** — sends `punch_time` unconditionally (`punch-entry-dialog.tsx:94`); `extra="forbid"` → 422 | **Ship API and web in the same release.** Non-negotiable. |
| Mobile app | ✘ | n/a | Contract fixed here before it is built |
| Third-party integrations | **NOT VERIFIED** — none in this repository | unknown | §15.3 |
| CSV / bulk import | ✘ for punches — `employee_import` imports employees only (**VERIFIED** by grep) | no | — |
| Background jobs | ✘ no attendance job exists | no | — |
| Regularization apply | ✔ internal | **no** — bypasses `PunchCreate` entirely (§2.5) | none needed |
| `ingestion/routes.py` | 8-line health-check stub, `DEAD-1` | no | — |

## 15.2 API contract changes

| Change | Breaking | Version strategy |
|---|---|---|
| `punch_time` forbidden on self-punch | **YES** | Coordinated release; 422 carries an explicit message naming the new behaviour |
| `punch_time` required on on-behalf | **YES** | Same |
| `source` removed from the request | **YES** | 422; server-assigned value is still returned in the response |
| Naive timestamps rejected | **YES** for malformed callers | Announce before release |
| `reference` required on on-behalf | **YES** | Same release |
| `requested_time` bounded | **YES** for out-of-window values | Same release |
| Timezone change refused | **YES** for a live tenant | New typed 409, documented |
| Response shapes | **NO** | Unchanged throughout |

## 15.3 Open compatibility question

**Are there integration partners posting to `/v1/attendance/punches` today?** The repository cannot
answer this. **Phase 0 must answer it from production access logs.** If any exist, Phase 1 needs a
deprecation window with both shapes accepted behind a feature flag — **not** a same-day cutover.

---

# 16. PHASE-BY-PHASE IMPLEMENTATION PLAN

**Execution order — this governs, not the numbering:**

```text
Phase 0  ──►  Phase 7  ──►  Phase 1  ──►  Phase 2  ──►  Phase 3
                 │                                         │
                 └── CI must gate before behaviour moves    ├──►  Phase 4
                                                            ├──►  Phase 5
                                                            └──►  Phase 6  ──►  Phase 8  ──►  Phase 9
```

## Phase 0 — Baseline (0.5 day)

| # | Action | Output |
|---|---|---|
| 0.1 | Record the git commit; tag `pre-tz-remediation` | Immutable reference |
| 0.2 | Repair the local `uv`/venv resolution (§12.1) | Runnable suite |
| 0.3 | Run `tests/unit` — expect **362 passed** | Baseline |
| 0.4 | Run `tests/integration` + `tests/security` against a local DB; record pass/fail per file | Baseline — **some may already fail; that must be known now** |
| 0.5 | Run `npm test` in `apps/web`; record | Baseline |
| 0.6 | `DH-1` inventory on **every** environment including production | Timezone data reality |
| 0.7 | Capture 10 golden attendance scenarios (day, night, cross-midnight, holiday, weekly-off, leave, half-day, OT, incomplete, config-error) with full `attendance_day` JSON | Before/after comparison set |
| 0.8 | Enumerate every test sending `punch_time` or `source` | Phase-1 blast radius |
| 0.9 | Check production access logs for non-web callers of `/attendance/punches` | Resolves §15.3 |

**Exit:** baselines recorded; no code changed.

## Phase 7 *(pulled forward)* — CI and production gates (1.5–2 days)

| # | Action |
|---|---|
| 7.1 | Add PostgreSQL 16 + Redis 7 services to `ci.yml` |
| 7.2 | Apply `infra/docker/postgres/init` RLS roles explicitly; **run tests as the non-superuser app role** |
| 7.3 | Add `alembic upgrade head` as a CI step |
| 7.4 | Add `TZ: UTC` to the job env |
| 7.5 | Add the `web` job: lint + `vitest run` (**NEW-06**) |
| 7.6 | Make `api` and `web` **required status checks** on `main` |
| 7.7 | Fix whatever the 783 integration tests reveal on first honest run |

**Exit:** all 1145 backend tests plus the web suite run and gate merges. **This is the hard
prerequisite for every phase below.**

## Phase 1 — Timestamp authority (3–4 days)

| # | Action | Finding |
|---|---|---|
| 1.1 | Split `PunchCreate` into `PunchCreateSelf` / `PunchCreateOnBehalf` | `F-01`, `F-02` |
| 1.2 | `AwareDatetime` on every supplied instant | `TZ-02`, `F-07` |
| 1.3 | `record_punch`: server-stamp self; validate + bound on-behalf | `F-01`, `F-03` |
| 1.4 | Server-assign `source` from the authenticated context | `F-11` — **must ship with 1.3** |
| 1.5 | Future / far-past bounds with typed errors | `F-03` |
| 1.6 | Write `punch.raw_payload` | `F-18` |
| 1.7 | `ENV TZ=UTC` in the Dockerfile | `TZ-02` |
| 1.8 | Split the punch dialog into self and admin modes | `F-02` |
| 1.9 | Structured rejection logging (§20) | new |
| 1.10 | Tests: §17.3 + §17.7 | `H1–H12`, `G1–G5` |

**Exit:** no client can set its own attendance timestamp on the self path. **API and web release
together.**

## Phase 2 — India timezone invariant (2–3 days)

| # | Action | Finding |
|---|---|---|
| 2.1 | IANA validator on `ShiftVersionCreate`/`Update` + publish-time check | **NEW-01** |
| 2.2 | `DH-1` review complete before any guard lands | **NEW-03** |
| 2.3 | Implement `_assert_timezone_change_allowed`; `TRIAL`/zero-days escape hatch; `CLOSED`-period refusal | `TZ-01`, `PAY-013` |
| 2.4 | **Call the guard from `update_branch`** | `TZ-01` |
| 2.5 | India allow-list on registration timezone | **NEW-04** |
| 2.6 | Alias canonicalisation; forbid `== "Asia/Kolkata"` invariants | **NEW-03** |
| 2.7 | `DH-2` normalisation for zero-attendance companies | **NEW-03** |
| 2.8 | Tests: §17.5 | `E1–E7` |

**Exit:** timezone configuration cannot change under computed attendance; the top of the WD-06
chain is validated. `TZ-09` closes as a side effect.

## Phase 3 — Attendance date and period lock (2 days)

| # | Action | Finding |
|---|---|---|
| 3.1 | `shared/business_time.py`: `business_today(tz)`, `business_month_start(tz)` | `TZ-06` |
| 3.2 | Replace `date.today()` at `attendance/service.py:3502`, `:3547` | `TZ-06`, `F-10` |
| 3.3 | Replace `date.today()` at `leave/service.py:1979`, `:2597` | `DAT-004/005` |
| 3.4 | Replace the UTC month start at `leave/service.py:1990` **and `attendance/service.py:3558`** | **DOC-D3** |
| 3.5 | Return the company timezone in the session/bootstrap payload | `TZ-03`, `TZ-07` |
| 3.6 | `todayIso()` → `businessToday(tz)` at all 14 call sites | `TZ-07` |
| 3.7 | **Remove the duplicate `todayIso()`** in `policy-resolution/page.tsx:27` | **NEW-05** |
| 3.8 | **Stop posting a UTC date to `/days/calculate`** (`employee-attendance-panel.tsx:78`) | **NEW-02** |
| 3.9 | Period-lock date basis — **only after `OD-1` is decided** | `OD-1` |
| 3.10 | Tests: §17.4, §17.6 | `A1–A11`, `F1–F5` |

**Exit:** every business-date derivation is India-local. No `date.today()` remains in a business
rule.

## Phase 4 — Cross-midnight breaks (1 day)

| # | Action |
|---|---|
| 4.1 | Rewrite `match_breaks` to compare UTC instants (§10.4 approach B) |
| 4.2 | Preserve the `UTC → local` conversion order; keep `ATT-009` out of scope |
| 4.3 | The 8 tests from remediation §12.7 plus `I4` and the `C14` order guard |
| 4.4 | Identify affected tenants and days; recompute **open** days deliberately, with notice |

**Exit:** a configured paid break is paid, whatever hour it spans.

## Phase 5 — UI timezone (2 days)

| # | Action |
|---|---|
| 5.1 | `formatClockTime(iso, tz)` / `formatDateTime(iso, tz)` — timezone argument **required** |
| 5.2 | Always render a visible `IST` label |
| 5.3 | Update all 24 call sites across 9 files |
| 5.4 | Dual-zone rendering on the day-detail page only |
| 5.5 | Component tests asserting a fixed instant renders in IST under a non-IST `TZ` runner |
| 5.6 | Amend `DEC-010`'s rendering clause to name the WD-06-resolved zone (**needs client sign-off**) |

**Exit:** no attendance time renders in the viewer's browser timezone.

## Phase 6 — Calculation and reconciliation (4–5 days)

| # | Action | Finding |
|---|---|---|
| 6.1 | Synchronous best-effort calculate after a punch, failure-tolerant | `F-14` |
| 6.2 | `modules/attendance/tasks.py` on the `leave/tasks.py` pattern | `F-14`, `PAY-001` |
| 6.3 | Beat entry at `09:30` IST | `DEC-TZ-12` |
| 6.4 | Trailing-3-day window; skip locked days and `CLOSED` periods | `WD-11` |
| 6.5 | `SELECT … FOR UPDATE` on `attendance_day` during recompute + deadlock review | `F-15` |
| 6.6 | **Orphan-punch report** — punches owned by no `attendance_day` | `TZ-08`, `R-TZ-16a` |
| 6.7 | Document `OPS-006` (no Beat leader election) in the runbook | `OPS-006` |
| 6.8 | Tests: §17.8 | `J1–J3` |

**Exit:** attendance exists without anyone asking for it; a period can be finalized.

## Phase 8 — Staging (2 days)

Deploy the full stack; replay the 10 golden scenarios from 0.7 and diff against baseline; run the
punch-integrity matrix by hand (naive / future / far-past / forged-source / self with
`punch_time`); verify the 09:30 IST job fires and is idempotent across two runs; verify the
timezone guard on a real tenant; verify IST rendering from a non-IST browser (set the OS to
`America/New_York`); HR/UAT sign-off on a night-shift week including a midnight break.

## Phase 9 — Production rollout (1 day + monitoring)

Off-hours deploy (after 22:00 IST, before 05:00 IST — outside every shift boundary and the 09:30
job). API and web **together**. Monitor for 48 h: punch rejection rate by reason, punch volume vs.
the prior week, `attendance_day` creation rate, orphan-punch count, timezone-guard 409s, 500 rate
on `/attendance/*`. Rollback readiness per §19.

---

# 17. TEST PLAN

**No tests are written by this document.** The engine is pure (`PC-12`), so tiers 1–3 need no
database — which is what makes this plan cheap relative to the risk it closes.

## 17.1 Tiers

| Tier | Needs | Groups | ~Count | Cost |
|---|---|---|---|---|
| 1 — pure unit | nothing | A, B, C, D, I | ~45 | low — ms each |
| 2 — schema | Pydantic | H | 12 | low |
| 3 — process env | `TZ` per case | G | 5 | low |
| 4 — integration | PostgreSQL | E, F | 12 | medium — **blocked on `TST-001`** |
| 5 — concurrency | PostgreSQL + 2 sessions | J | 3 | high |
| 6 — component | vitest + jsdom | UI | ~8 | low — **blocked on NEW-06** |

## 17.2 Timezone set

| Zone | Why it stays in an India-only product |
|---|---|
| `Asia/Kolkata` | **Every tenant.** The `:30` offset catches half-hour bugs |
| `UTC` | Control; the degenerate case where local == UTC — **and the value 11 fixture branches actually carry** |
| `America/New_York` | Negative offset + DST — **as a server-`TZ` regression guard (P-20), not as a tenant** |
| `Europe/London` | DST where standard time *is* UTC — same purpose |
| `Pacific/Kiritimati` (+14) | The extreme: the whole local day falls on the previous UTC date. Proves `attendance_date` is never derived from a UTC date |

> These are **engine regression zones**, not product scope. They exist so the India behaviour stays
> correct for the reason it is correct, and so expansion does not require re-proving the engine.

## 17.3 Ingestion validation (tier 2 — 12 cases)

| # | Input | Today | Required |
|---|---|---|---|
| H1 | `"2026-09-15T09:00:00Z"` on admin path | accepted | accepted *(guard)* |
| H2 | `"…+05:30"` on admin path | accepted | accepted — **half-hour offset preserved exactly** |
| H3 | `"2026-09-15T09:00:00"` naive | **accepted** | **422** |
| H4 | `"2099-01-01T00:00:00Z"` | **accepted** *(VERIFIED)* | **422** |
| H5 | `"1900-01-01T00:00:00Z"` | **accepted** *(VERIFIED)* | **422** |
| H6 | `source="REGULARIZATION"` on a self-punch | **accepted** *(VERIFIED)* | **422** |
| H7 | `source="DEVICE"` on a web self-punch | **accepted** *(VERIFIED)* | **422** |
| H8 | `punch_time` present on the **self** path | accepted | **422 — the headline case** |
| H9 | `punch_time` absent on the **admin** path | accepted (server-stamps) | **422 — required there** |
| H10 | `"2026-09-15T09:00:00 Asia/Kolkata"` | rejected (not ISO) | **422** *(guard)* |
| H11 | Admin punch, no `reference` | accepted | **422** |
| H12 | Admin punch beyond the backdating window | accepted | **422** |

## 17.4 Boundaries (tier 1)

Groups A1–A11 and B1–B12 exactly as the test matrix computes them — including the orphan edges
`06:59` / `07:00` / `20:00` / `20:01` local, which **freeze the ±2h pad so changing it is a
conscious act** (`DEC-TZ-16`), and B5's `00:00` proving midnight does not move the day.

## 17.5 Timezone change and recompute (tier 4)

| # | Scenario | Assert |
|---|---|---|
| E1 | New `ShiftVersion` with a different timezone → recompute a historical day | **unchanged** — `PC-10` guard |
| E2 | `Branch.timezone` changed → recompute | **refused** — and `update_branch` **is** guarded |
| E3 | `Company.timezone` changed → recompute | **refused** |
| E4 | Employee transfers branch → recompute historical | **unchanged** — `PC-11` guard |
| E5 | Timezone change while `TRIAL` / zero computed days | **permitted** |
| E6 | Timezone change with any affected period `CLOSED` | **refused under every option** |
| E7 | **`ShiftVersion.timezone = "IST"`** | **422 at create — never a 500 at calculate** (**NEW-01**) |

## 17.6 Period lock (tier 4)

`F1`–`F5` from the matrix, asserting whichever basis `OD-1` selects — **including the 05:00 IST
month-boundary case, so the choice is frozen in a test rather than in a comment.**

## 17.7 Server-timezone independence (tier 3)

**One parametrised module**, `TZ` ∈ {`UTC`, `Asia/Kolkata`, `America/New_York`, `Pacific/Kiritimati`}:
day-shift `evaluate_day`, night-shift `evaluate_day`, `scheduled_span_utc` × 5 zones, DST spans × 4
transitions — **identical business output in all four**. Plus `G5`: naive ingestion **rejected in
all four**, closing the single historical divergence.

> Compare **attendance outputs**, never the `TZ` label itself (task §23).
> This module is the regression guard for `PC-01`, the property everything else rests on.

## 17.8 Concurrency (tier 5)

| # | Scenario | Assert |
|---|---|---|
| J1 | Isolation level | `SHOW default_transaction_isolation` is what the code expects — **fails loudly if a deploy changes it** |
| J2 | Timezone `UPDATE` commits between two SELECTs in one `_build_calculation_input` | Guard refuses the update, **or** the calculation is internally consistent — never torn |
| J3 | Nightly job and an interactive recompute collide on one employee-date | Deterministic result; no lost update; no duplicate row |

## 17.9 Breaks (tier 1)

The eight tests from remediation §12.7, plus `I4` (excess break across midnight — closes the one
never-executed break scenario) and `C14` (ambiguous `01:10` local still matches — the
conversion-order guard).

## 17.10 Frontend (tier 6)

Fixed instant renders as `09:05 IST` under `TZ=America/New_York`; the `IST` label is present;
`businessToday()` at 02:00 IST returns the **IST** date; the self-punch dialog renders **no** time
input; the admin dialog requires a reason; a network failure shows a non-dismissible "not
recorded" error.

## 17.11 Implementation order

| Priority | Group | Cost | Closes |
|---|---|---|---|
| 1 | Ingestion (§17.3) | low | `F-01`, `F-03`, `F-11`, `TZ-02` — **the P0s** |
| 2 | Breaks (§17.9) | low | `F-05` |
| 3 | Server TZ (§17.7) | low | **Locks in `PC-01`** |
| 4 | Boundaries (§17.4) | low | `TZ-08`; freezes the pad |
| 5 | DST (§17.2 zones) | low | `TZ-04`; protects `PC-06` |
| 6 | Timezone change (§17.5) | medium | `TZ-01` + **NEW-01** |
| 7 | Period lock (§17.6) | medium | Month-end integrity |
| 8 | Frontend (§17.10) | low | `TZ-03`, `TZ-07`, **NEW-02** |
| 9 | Concurrency (§17.8) | high | `TZ-09`, `F-15` |

> Priorities 1–5 need no database and no fixtures. A single parametrised file covering them moves
> **~36 of the 46 code-proven-but-unprotected scenarios into test-proven** — the best
> risk-per-hour available anywhere in this plan.

---

# 18. FILE / MODULE-LEVEL CHANGE MAP

Actual repository paths and actual symbols, per the brief's §35.

## 18.1 Phase 1 — Timestamp authority

| Phase | File | Function / Class | Current behaviour | Required change | Reason | Tests |
|---|---|---|---|---|---|---|
| 1 | [`attendance/schemas.py:1220`](../../apps/api/src/hrms/modules/attendance/schemas.py#L1220) | `PunchCreate` | One schema; `punch_time` optional and offset-free; `source` client-settable | Split into `PunchCreateSelf` (no `punch_time`, no `source`) and `PunchCreateOnBehalf` (`punch_time: AwareDatetime` required, `reference` required) | `F-01`, `F-02`, `F-11`, `TZ-02` | H1–H12 |
| 1 | [`attendance/schemas.py:1234`](../../apps/api/src/hrms/modules/attendance/schemas.py#L1234) | `PunchCreate.punch_time` | `datetime \| None`, naive accepted | Removed from self; `AwareDatetime` on on-behalf | `TZ-02`, `F-07` | H3, H8, H9 |
| 1 | [`attendance/schemas.py:1236`](../../apps/api/src/hrms/modules/attendance/schemas.py#L1236) | `PunchCreate.source` + `validate_source` | All 7 values accepted from any caller | Field removed from both request schemas; validator deleted | `F-11`, `DEC-TZ-05` | H6, H7 |
| 1 | [`attendance/service.py:2353`](../../apps/api/src/hrms/modules/attendance/service.py#L2353) | `PunchService.record_punch` | `"punch_time": body.punch_time or now` | Self: `punch_time = now` unconditionally. On-behalf: validated `body.punch_time` | `F-01`, P-02 | H4, H5, H8, H12 |
| 1 | [`attendance/service.py:2355`](../../apps/api/src/hrms/modules/attendance/service.py#L2355) | same | `"source": body.source or default_source` | `"source": default_source` — server-assigned, always | `F-11` | H6, H7 |
| 1 | [`attendance/service.py:2337`](../../apps/api/src/hrms/modules/attendance/service.py#L2337) | same | `now` computed, used only for `created_at` | Becomes the explicit **REQUEST TIME** anchor for every bound; comment that `created_at` must never fall back to the DB default | §3.2 | unit |
| 1 | [`attendance/service.py:2349-2360`](../../apps/api/src/hrms/modules/attendance/service.py#L2349) | same, `data` dict | `raw_payload` never written | Write `{submitted_offset, user_agent, client_ip, client_version}` | `F-18` | integration |
| 1 | [`attendance/router.py:753`](../../apps/api/src/hrms/modules/attendance/router.py#L753) | `create_punch` | One endpoint; body decides self vs on-behalf | Two handlers (or one with a discriminated body); `ip_address`/`user_agent` — **already captured at `:786-787`** — also flow into `raw_payload` | `F-02`, `F-18` | API contract |
| 1 | [`attendance/exceptions.py`](../../apps/api/src/hrms/modules/attendance/exceptions.py) | — | No punch-validation errors | Add `FuturePunchTimeError`, `PunchTimeOutOfRangeError`, `NaivePunchTimeError`, `ClientPunchTimeNotAllowedError` | typed 422s | H3–H12 |
| 1 | [`apps/api/Dockerfile:5`](../../apps/api/Dockerfile#L5) | `ENV` block | No `TZ` | `ENV TZ=UTC` | `TZ-02`, `R-TZ-02b` | G1–G5 |
| 1 | [`web/components/attendance/punch-entry-dialog.tsx:33,64,94,147-153`](../../apps/web/src/components/attendance/punch-entry-dialog.tsx#L33) | `nowForDatetimeLocal`, `punchTime` state, `handleSubmit`, the time `FormField` | Browser clock seeds an editable `datetime-local` that is always sent | Self mode: delete the state, the field and `punch_time` from the body. Admin mode: keep the field, add a required reason, label it `(IST)` | `F-02` | §17.10 |
| 1 | [`web/app/app/attendance/page.tsx:307`](../../apps/web/src/app/app/attendance/page.tsx#L307) | `PunchEntryDialog` usage | Admin dialog with a picker | Admin mode explicitly | `F-02` | §17.10 |
| 1 | [`web/components/attendance/employee-attendance-panel.tsx:198`](../../apps/web/src/components/attendance/employee-attendance-panel.tsx#L198) | `PunchEntryDialog` usage | Self dialog, locked employee | Self mode explicitly | `F-02` | §17.10 |

## 18.2 Phase 2 — India timezone invariant

| Phase | File | Function / Class | Current behaviour | Required change | Reason | Tests |
|---|---|---|---|---|---|---|
| 2 | [`organisation/schemas.py:1243`](../../apps/api/src/hrms/modules/organisation/schemas.py#L1243) | `ShiftVersionCreate.timezone` | `max_length=64` only — **no IANA validation** | Add the `available_timezones()` validator used at `:691-695` | **NEW-01** | E7 |
| 2 | [`organisation/schemas.py:1280`](../../apps/api/src/hrms/modules/organisation/schemas.py#L1280) | `ShiftVersionUpdate.timezone` | same | same | **NEW-01** | E7 |
| 2 | [`organisation/service.py:2282`](../../apps/api/src/hrms/modules/organisation/service.py#L2282) | `_validate_and_derive_for_publish` | Validates times, flex windows, `effective_from`; never the timezone | Reject a non-IANA `timezone` at publish | **NEW-01** | E7 |
| 2 | [`organisation/service.py:702-709`](../../apps/api/src/hrms/modules/organisation/service.py#L702) | `_assert_timezone_change_allowed` | `_ = (company_id, current_timezone, new_timezone)` — empty stub | Async; refuse when any computed `attendance_day` exists for the scope; permit while `TRIAL` or zero days; **always** refuse when an affected period is `CLOSED` | `TZ-01`, `PAY-013`, `DEC-TZ-13`=A | E2, E3, E5, E6 |
| 2 | [`organisation/service.py:659`](../../apps/api/src/hrms/modules/organisation/service.py#L659) | `update_company_profile` | Calls the stub | Await the real guard | `TZ-01` | E3 |
| 2 | [`organisation/service.py:1105-1186`](../../apps/api/src/hrms/modules/organisation/service.py#L1105) | `update_branch` | **No guard call at all** | Call the guard when `patch.timezone` differs | `TZ-01` | E2 |
| 2 | [`organisation/schemas.py:100`](../../apps/api/src/hrms/modules/organisation/schemas.py#L100) | `CompanyRegistrationRequest.timezone` | Any IANA zone, anonymous | Validate against `settings.allowed_company_timezones` (default `["Asia/Kolkata","Asia/Calcutta"]`) | **NEW-04** | API contract |
| 2 | [`core/config/settings.py`](../../apps/api/src/hrms/core/config/settings.py) | `Settings` | No allow-list | Add `allowed_company_timezones` | **NEW-04** | unit |
| 2 | [`organisation/exceptions.py`](../../apps/api/src/hrms/modules/organisation/exceptions.py) | — | — | `TimezoneChangeNotAllowedError` (409), `InvalidTimezoneError` (422) | typed errors | E2, E3, E7 |
| 2 | [`web/lib/timezones.ts:18-24`](../../apps/web/src/lib/timezones.ts#L18) | `listTimezones`, `resolveDefaultTimezone` | Full ICU list; alias-tolerant default | Filter to the India allow-list for V1; keep the alias resolution | **NEW-03**, **NEW-04** | vitest |
| 2 | [`web/app/register/page.tsx:163-170`](../../apps/web/src/app/register/page.tsx#L163) | timezone `FormField` | Free selector | Show the allow-list (a single fixed value in V1) | **NEW-04** | vitest |
| 2 | `apps/api/scripts/tz_inventory.py` | **new** | — | Read-only `DH-1` report | **NEW-03** | n/a |

## 18.3 Phase 3 — Attendance date and period lock

| Phase | File | Function / Class | Current behaviour | Required change | Reason | Tests |
|---|---|---|---|---|---|---|
| 3 | `apps/api/src/hrms/shared/business_time.py` | **new** | — | `business_today(tz)`, `business_month_start(tz)` over `datetime.now(UTC).astimezone(ZoneInfo(tz))` | `TZ-06` | unit |
| 3 | [`attendance/service.py:3502`](../../apps/api/src/hrms/modules/attendance/service.py#L3502) | `submit` (regularization) | `body.attendance_date > date.today()` — **server OS local** | Compare against `business_today(company_tz)` | `TZ-06`, `F-10` | integration |
| 3 | [`attendance/service.py:3547`](../../apps/api/src/hrms/modules/attendance/service.py#L3547) | same | `(date.today() - attendance_date).days` | same | `TZ-06` | integration |
| 3 | [`attendance/service.py:3558`](../../apps/api/src/hrms/modules/attendance/service.py#L3558) | same | `datetime(now.year, now.month, 1, tzinfo=UTC)` | India-local month start | **DOC-D3** | integration |
| 3 | [`leave/service.py:1979`](../../apps/api/src/hrms/modules/leave/service.py#L1979) | leave apply | `date.today()` | `business_today(company_tz)` | `DAT-005` | integration |
| 3 | [`leave/service.py:1990`](../../apps/api/src/hrms/modules/leave/service.py#L1990) | same | UTC month start | India-local month start | `DAT-005` | integration |
| 3 | [`leave/service.py:2597`](../../apps/api/src/hrms/modules/leave/service.py#L2597) | `_reverse_approval` | `"effective_date": date.today()` | `business_today(company_tz)` | `DAT-004` | integration |
| 3 | [`attendance/service.py:2347`](../../apps/api/src/hrms/modules/attendance/service.py#L2347) | `record_punch` lock check | `(body.punch_time or now).date()` — **UTC civil date** | **Per `OD-1`.** Whichever basis is chosen, replace the WD-30 comment with the decided rule | `OD-1`, `DEC-TZ-10` | F1–F5 |
| 3 | [`web/lib/attendance/format.ts:27-29`](../../apps/web/src/lib/attendance/format.ts#L27) | `todayIso` | `new Date().toISOString().slice(0,10)` — **UTC** | Replace with `businessToday(tz)` | `TZ-07` | vitest |
| 3 | [`web/app/app/policy-resolution/page.tsx:27`](../../apps/web/src/app/app/policy-resolution/page.tsx#L27) | private `todayIso` | **Duplicate** UTC helper | Delete; use the shared one | **NEW-05** | vitest |
| 3 | [`web/components/attendance/employee-attendance-panel.tsx:78`](../../apps/web/src/components/attendance/employee-attendance-panel.tsx#L78) | `handleCalculateToday` | Posts `date=${todayIso()}` — a **UTC** date into a calculation | `businessToday(companyTz)` | **NEW-02** | vitest |
| 3 | `overtime/page.tsx:62-63`, `regularizations/page.tsx:64-65`, `rosters/page.tsx:72-73`, `leave-applications/page.tsx:62-63`, `attendance/page.tsx:66`, `create-period-dialog.tsx:33,34,40,41`, `employee-attendance-panel.tsx:43` | default filters | `todayIso()` | `businessToday(tz)` | `TZ-07` | vitest |
| 3 | identity/session bootstrap response | — | Company timezone not on the wire for the user | Include `company.timezone` | `TZ-03`, `TZ-07` | integration |

## 18.4 Phase 4 — Cross-midnight breaks

| Phase | File | Function / Class | Current behaviour | Required change | Reason | Tests |
|---|---|---|---|---|---|---|
| 4 | [`attendance/calculation.py:574-617`](../../apps/api/src/hrms/modules/attendance/calculation.py#L574) | `match_breaks` | Chained time-of-day inequality; `23:30–00:30` never matches | Build the break's UTC span from the attendance date (rolling the end forward when it precedes the start) and compare instants — mirroring `_core_hours_breached` (`:1097-1099`) | `F-05`, `R-4` | §17.9 ×10 |
| 4 | [`attendance/calculation.py:586`](../../apps/api/src/hrms/modules/attendance/calculation.py#L586) | `gap_start_local` | `gap_start.astimezone(tz).time()` — **correct order** | **Preserve.** This is `PC-15` | `PC-15` | C14 |
| 4 | [`attendance/calculation.py:1119,1322`](../../apps/api/src/hrms/modules/attendance/calculation.py#L1119) | `evaluate_day`, `_evaluate_split` | `match_breaks(gaps, shift.breaks, tz_name=…)` | Pass the attendance date through | `F-05` | §17.9 |
| 4 | [`attendance/calculation.py:62-72`](../../apps/api/src/hrms/modules/attendance/calculation.py#L62) | `ShiftBreakData` | No cross-midnight flag | **Unchanged in Phase 4.** `R-SB-01` adds the declared column later (§6.4) | `R-SB-01` | — |

## 18.5 Phase 5 — UI timezone

| Phase | File | Function / Class | Current behaviour | Required change | Reason | Tests |
|---|---|---|---|---|---|---|
| 5 | [`web/lib/attendance/format.ts:14-25`](../../apps/web/src/lib/attendance/format.ts#L14) | `formatClockTime`, `formatDateTime` | `toLocaleTimeString(undefined, …)` → **viewer's browser zone** | Required `tz` argument → `timeZone: tz`; append the zone label | `TZ-03`, `F-08`, `FE-1`, `DEC-010` | §17.10 |
| 5 | `attendance/[id]/page.tsx` ×8, `regularizations/[id]/page.tsx` ×6, `leave-applications/[id]/page.tsx` ×4, `attendance-periods/[id]/page.tsx` ×3, `overtime/[id]/page.tsx` ×2, `leave-balances/page.tsx` ×1 | `formatDateTime` call sites | No zone passed | Pass `day.timezone` for attendance instants, company timezone for `created_at` / audit | `TZ-03` | §17.10 |
| 5 | `employee-attendance-panel.tsx:169,173` | `formatClockTime` ×4 | No zone | Pass `day.timezone` | `TZ-03` | §17.10 |
| 5 | [`attendance/[id]/page.tsx:110`](../../apps/web/src/app/app/attendance/[id]/page.tsx#L110) | page header | Already prints `— ${day.timezone}` | Keep; add the `(your time)` secondary — **day detail only** | `DEC-TZ-08` | §17.10 |

## 18.6 Phase 6 — Calculation and reconciliation

| Phase | File | Function / Class | Current behaviour | Required change | Reason | Tests |
|---|---|---|---|---|---|---|
| 6 | `apps/api/src/hrms/modules/attendance/tasks.py` | **new** | No attendance task exists | `run_daily_calculation` (Beat entrypoint) + `calculate_company(company_id)`, on the `leave/tasks.py` two-tier pattern with `session_scope(company_id=…)` | `F-14`, `PAY-001` | integration |
| 6 | [`core/celery_app.py:24-49`](../../apps/api/src/hrms/core/celery_app.py#L24) | `beat_schedule` | Four `leave.*` entries | Add `attendance-run-daily-calculation`, `crontab(minute=30, hour=9)` — the app's timezone is **already** `Asia/Kolkata` | `DEC-TZ-12` | unit |
| 6 | [`attendance/service.py:2362-2365`](../../apps/api/src/hrms/modules/attendance/service.py#L2362) | `record_punch`, post-insert | No calculation triggered | Best-effort calculate, wrapped so failure never fails the punch | `F-14` | integration |
| 6 | [`attendance/service.py:2504-2512`](../../apps/api/src/hrms/modules/attendance/service.py#L2504) | `calculate` | `get_by_employee_date` then write — no lock | `SELECT … FOR UPDATE`; review lock ordering against the period-lock path | `F-15` | J3 |
| 6 | [`attendance/repository.py`](../../apps/api/src/hrms/modules/attendance/repository.py) | `PunchRepository` | No orphan query | Add "punches with no owning `attendance_day`" | `TZ-08`, `R-TZ-16a` | integration |
| 6 | `attendance/router.py`, `schemas.py` | — | — | `GET /attendance/punches/orphaned`; add to the period-close checklist | `R-TZ-16a` | API contract |

## 18.7 Phase 7 — CI

| Phase | File | Change | Reason |
|---|---|---|---|
| 7 | [`.github/workflows/ci.yml`](../../.github/workflows/ci.yml) | PostgreSQL 16 + Redis 7 services; RLS-role init step; `alembic upgrade head`; `TZ: UTC`; new `web` job | `TST-001`, **NEW-06**, `R-TZ-02b` |
| 7 | [`apps/api/pyproject.toml`](../../apps/api/pyproject.toml) | Declare `tzdata` as a direct dependency | `TZ-05` (partial) |
| 7 | Repository settings | `api` and `web` as required status checks on `main` | `TST-001` |

## 18.8 Documentation changes

| ID | Document | Change |
|---|---|---|
| `R-DOC-01` | `ATTENDANCE_MASTER_RULE_MATRIX.md` **C3** | *"Presumed yes (stdlib)"* → *"CODE-PROVEN 2026-09-15 across four real transitions; automated from Phase 1 (§17.7)"* |
| `R-DOC-02` | `TECHNICAL_DEBT_REGISTER.md` | Re-rate `TZ-1` 🟢 P4 → 🟠 P1; `FE-1` 🔵 P4 → 🟠 P1; add **NEW-01…06** |
| `R-DOC-03` | `WORKFORCE_ATTENDANCE_DECISION_LOG.md` | Record `WD-33` (authoritative clock), `WD-34` (India timezone invariant); amend `WD-30` per `OD-1` |
| `R-DOC-04` | `adr/0010-…md` | Amend the rendering clause to name the WD-06-resolved zone — **needs client sign-off** |
| `R-DOC-05` | Rule matrix C1/C2, debt register `PAY-013` | Correct the drifted line numbers (**DOC-D6**) |
| `R-DOC-06` | Client-facing attendance documentation | Document the ±2h pad, the period-lock basis, and the punch-UTC / day-local filter split (`F-20`) |
| `R-DOC-07` | `core/config/settings.py:32` | Rename `app_timezone_default` → `celery_timezone`, or document the Celery-only scope at the definition (`TZ-13`) |

---

# 19. ROLLBACK PLAN

> **Code rollback does not roll back attendance data.** Every phase below is assessed on that basis.

| Phase | Change | Potential failure | Detection | Rollback mechanism | Data recovery |
|---|---|---|---|---|---|
| 0 | None | — | — | — | — |
| 7 | CI | CI red on unrelated pre-existing failures | First honest run | Revert the workflow; keep services, drop the required check | **None needed** — no production data touched |
| 1 | Server-stamped punches | Employees cannot punch; punch volume collapses | Punch volume vs. prior week; 422 rate by reason | Revert API **and** web together | **Punches created during the window are correct** — server-stamped. Nothing to undo. Punches *blocked* are lost and must be entered on-behalf. |
| 1 | `source` server-assigned | An undocumented integration breaks | 422 rate with `source` in the payload | Same revert | None — rejected requests wrote nothing |
| 1 | `TZ=UTC` in the image | None expected (`PC-01`) | §17.7 suite | Revert the Dockerfile line | None |
| 2 | Timezone guard | A legitimate correction is blocked for a live tenant | 409 rate; support tickets | Revert the guard; `TRIAL`/zero-days hatch usually suffices | **None** — the guard only ever *refuses* a write |
| 2 | `DH-2` alias normalisation | A company's timezone is changed unexpectedly | `DH-1` re-run | **Restore from `audit_log` before/after JSON** | ✔ recoverable |
| 2 | Registration allow-list | A legitimate non-India signup is blocked | Registration failure rate | Widen the setting — **configuration, no deploy** | None |
| 3 | `business_today()` | A boundary shifts by a day; a request is wrongly accepted or rejected | Regularization/leave rejection rate | Revert the helper adoption | **Requests submitted in the window persist.** Review manually; no automatic reversal. |
| 3 | Period-lock basis (`OD-1`) | Punches accepted into, or rejected from, the wrong period at a month boundary | Orphan-punch report; `ATTENDANCE_PERIOD_CLOSED` rate | Revert to the UTC basis | **Punches written are facts and stay.** The lock check is advisory; `calculate()` is the real backstop. |
| 4 | Cross-midnight breaks | Paid minutes change on night shifts | Diff of recomputed days vs. snapshot | Revert `match_breaks` **and recompute again** | ⚠️ **`attendance_day` has no history table.** Recovery depends on the §19.4 snapshot. |
| 5 | IST rendering | Times display wrongly; users lose trust | Visual QA; support tickets | Revert the web bundle | **None** — display only, no data written |
| 6 | Scheduled calculation | Mass incorrect `attendance_day` creation; DB load spike | Row-creation rate; job duration; error rate | **Disable the Beat entry first** (config, no deploy), then revert | ⚠️ Rows created are recomputable; rows **overwritten** need the §19.4 snapshot |
| 6 | `FOR UPDATE` lock | Deadlock or timeout against the period-lock path | Lock-wait metrics; 500 rate | Revert the lock | None |

## 19.4 The mandatory pre-recompute snapshot

**Before Phase 4's recompute and before Phase 6's first scheduled run:**

```sql
CREATE TABLE attendance_day_snapshot_<phase>_<yyyymmdd> AS
  SELECT * FROM attendance_day WHERE <affected scope>;
```

A plain `CREATE TABLE AS`, retained for 90 days, dropped only after HR sign-off. It is the **only**
mechanism that makes a recompute reversible, because `attendance_day` is replaced in place (WD-10)
and has no history table. **Skipping it makes Phase 4 and Phase 6 one-way doors.**

## 19.5 Rollback drill

**Phase 8 must actually execute one rollback on staging** — revert Phase 4, restore from the
snapshot, verify the golden scenarios return to baseline. An untested rollback procedure is not a
rollback procedure (task §31).

---

# 20. OBSERVABILITY

## 20.1 Log on every rejected punch

| Field | Include | Note |
|---|---|---|
| `request_id` | ✔ | Correlation — `build_meta(current_request_id())` already exists |
| `company_id` | ✔ | |
| `employee_id` (target) | ✔ | |
| `actor_user_id` | ✔ | Distinguishes self from on-behalf |
| `endpoint` | ✔ | |
| `rejection_reason` | ✔ | Typed code, not free text — `NAIVE_TIMESTAMP`, `FUTURE_PUNCH_TIME`, `CLIENT_TIME_NOT_ALLOWED`, `SOURCE_NOT_ALLOWED`, `PERIOD_CLOSED` |
| `server_timestamp` | ✔ | The REQUEST TIME anchor |
| `supplied_timestamp` | ✔ **when supplied** | The evidence |
| `divergence_seconds` | ✔ when both exist | The signal worth alerting on |
| `source_requested` vs `source_assigned` | ✔ | Detects clients still asserting a source |
| Biometric / face data | ✘ | Not collected; never logged |
| Unnecessary PII (name, email, phone) | ✘ | Ids only — resolvable, not embedded |

## 20.2 Metrics

| Metric | Why | Alert |
|---|---|---|
| `punch_rejections_total{reason}` | Phase-1 rollout health | Spike in `CLIENT_TIME_NOT_ALLOWED` = a client not updated |
| `punch_created_total{source}` | Volume regression | Drop > 20% vs. prior week |
| `punch_event_receipt_divergence_seconds` (on-behalf) | Backdating abuse signal | p99 beyond the backdating window |
| `attendance_day_created_total` | Phase-6 health | Zero after 09:30 IST = the job did not run |
| `attendance_calculation_duration_seconds` | Job health | — |
| `orphaned_punches_total` | `TZ-08` visibility | Any non-zero value is worth a look |
| `timezone_change_refused_total` | Phase-2 health | Spike = a legitimate workflow is blocked |
| `attendance_5xx_total` | **NEW-01** regression canary | Any `ZoneInfoNotFoundError` |

## 20.3 Retention

Rejection logs: 90 days. `raw_payload`: per the existing PII retention policy (`PII-2`) —
**coordinate before Phase 1 ships, since it captures IP and user-agent.**

---

# 21. ACCEPTANCE CRITERIA

## 21.1 Time

- [ ] `TZ=UTC`, `TZ=Asia/Kolkata`, `TZ=America/New_York`, `TZ=Pacific/Kiritimati` produce **identical attendance outputs** — comparing results, never the environment label
- [ ] Every attendance operation resolves to `Asia/Kolkata` for every India tenant
- [ ] Every stored timestamp is timezone-aware `TIMESTAMPTZ`
- [ ] A naive timestamp is rejected with 422 at every endpoint that requires an instant
- [ ] A self-service caller **cannot** supply a punch time — the field does not exist
- [ ] A caller **cannot** assert `source`
- [ ] A client-asserted timezone is never trusted anywhere

## 21.2 Attendance

- [ ] Cross-midnight shifts attribute to the shift **start** date (`B1–B12`)
- [ ] A `23:30–00:30` paid break **matches and is paid** (`I2`)
- [ ] Attendance date is correct for every 00:00–05:29 IST punch
- [ ] Holiday lookup uses the local attendance date
- [ ] Weekly-off lookup uses the local attendance date
- [ ] Leave overlay uses the local attendance date
- [ ] Attendance rows exist **without anyone calling an endpoint**

## 21.3 Historical integrity

- [ ] Changing `Company.timezone` cannot silently rewrite historical attendance
- [ ] Changing `Branch.timezone` cannot either — **and `update_branch` is guarded**
- [ ] A `CLOSED` period refuses a timezone change under every code path
- [ ] Locked days remain unchanged through every recompute path
- [ ] A shift-version timezone edit still cannot rewrite history (`PC-10` regression)
- [ ] A branch transfer still cannot rewrite history (`PC-11` regression)
- [ ] **An invalid `ShiftVersion.timezone` is rejected at create — never a 500 at calculate**

## 21.4 UI

- [ ] Every attendance timestamp displays in `Asia/Kolkata` with a visible `IST` label
- [ ] The browser timezone cannot change a displayed attendance date or time
- [ ] No `todayIso()` remains — **including the duplicate**
- [ ] "Calculate today" sends the **India-local** date
- [ ] The self-punch dialog has **no** time input
- [ ] An offline punch attempt fails visibly and records nothing

## 21.5 Testing and CI

- [ ] All timezone tests pass
- [ ] All attendance tests pass
- [ ] 783 integration tests run against a real PostgreSQL **in CI**
- [ ] Migrations run in CI
- [ ] The frontend suite runs in CI
- [ ] CI is a **required status check** — merges are blocked on failure
- [ ] Tests run as the non-superuser application role, not `BYPASSRLS`
- [ ] Matrix coverage ≥ 65 of 68 (the 3 exclusions are the deferred DST policy scenarios)

---

# 22. PRODUCTION CHECKLIST

```text
[ ]  Client policy approved                      §23 OD-1 … OD-5 signed
[ ]  Server timestamp authority implemented       Phase 1  ── F-01/F-02/F-03
[ ]  Naive timestamp validation implemented       Phase 1  ── TZ-02/F-07
[ ]  source server-assigned                       Phase 1  ── F-11
[ ]  Client timezone cannot override India tz     Phase 2  ── P-03
[ ]  ShiftVersion.timezone validated              Phase 2  ── NEW-01
[ ]  Registration timezone gated                  Phase 2  ── NEW-04
[ ]  Historical timezone protection implemented   Phase 2  ── TZ-01/PAY-013
[ ]  Attendance date verified                     Phase 3  ── TZ-06/NEW-02
[ ]  Period lock verified                         Phase 3  ── OD-1
[ ]  Cross-midnight break fixed                   Phase 4  ── F-05
[ ]  UI timezone fixed                            Phase 5  ── TZ-03/FE-1
[ ]  Scheduled calculation live                   Phase 6  ── F-14/PAY-001
[ ]  Concurrency protection                       Phase 6  ── F-15
[ ]  Orphan-punch report live                     Phase 6  ── TZ-08
[ ]  Automated timezone tests added               §17 priorities 1-5
[ ]  Integration tests run against PostgreSQL     Phase 7  ── TST-001
[ ]  CI gates integration tests                   Phase 7  ── required checks
[ ]  Frontend job in CI                           Phase 7  ── NEW-06
[ ]  Pre-recompute snapshots taken                §19.4  ── MANDATORY
[ ]  Staging tests passed                         Phase 8
[ ]  HR / UAT approved                            Phase 8  ── incl. a night-shift week
[ ]  Rollback procedure TESTED (not just written) Phase 8  ── §19.5
[ ]  Observability + alerts live                  §20
[ ]  PII review of raw_payload complete           §20.3
```

> **Production remains NO-GO while any P0 is unresolved.**
> Open P0s: `NEW-01`, `TZ-01`, `TZ-02`, `F-01`/`F-02`/`F-03`, `F-11`, `F-05`, `F-14`, `TST-001`.

---

# 23. RISKS AND OPEN DECISIONS

## 23.1 Implementation risks

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| IR-1 | **Phase 1 breaks the web app** — it unconditionally sends `punch_time` | **Certain** if released separately | Attendance stops | Single coordinated release; §15.1 |
| IR-2 | An undiscovered integration posts punches | Unknown — **NOT VERIFIED** | Silent ingestion failure | Phase 0.9 resolves it from production logs; feature-flag fallback if any exist |
| IR-3 | Phase 4's recompute changes pay in an open period | **Certain** where a midnight break is configured | Payroll dispute | Snapshot (§19.4); notice; recompute open days only; the change is always in the employee's favour |
| IR-4 | Phase 6's job overloads the DB on first run | Medium | Outage | Trailing 3-day window; per-company fan-out; run once manually on staging at production scale first |
| IR-5 | `OPS-006` — Beat duplicate firing | Medium | Duplicate work | Idempotent by construction; documented in the runbook |
| IR-6 | The timezone guard blocks a legitimate correction | Medium | Support burden | `TRIAL`/zero-days hatch; clear 409; documented support path |
| IR-7 | CI turns red on pre-existing integration failures | **High** | Phase 7 slips | Phase 0.4 measures it **before** the gate is required |
| IR-8 | `business_today()` shifts a boundary and rejects a valid request | Medium | User friction | Tested at both boundaries; the change is behaviour-preserving when server tz == IST |
| IR-9 | A naive India-lock written as `tz == "Asia/Kolkata"` rejects the 3 `Asia/Calcutta` tenants | **High if unguarded** | Tenant lockout | **NEW-03**; alias set mandated in §10.2 step 4; `DH-1` first |
| IR-10 | Deadlock between the new `FOR UPDATE` and the period-lock path | Low-Medium | Failed recomputes | Explicit lock-ordering review in 6.5; J3 test |

## 23.2 Open decisions

| ID | Decision | Why it cannot be made by engineering | Blocks | Recommendation |
|---|---|---|---|---|
| **OD-1** ⭐ | **Which date basis governs the punch period-lock check?** | For IST, local `00:00–05:29` maps to the **previous** UTC date. §12 of the brief says use the India business date — but for a `22:00→06:00` night shift the *UTC* date is actually **closer** to the true attendance date in that band, and the IST date is further from it. **Neither civil date is the attendance date**, and which error is acceptable depends on whether the tenant runs night shifts. | Phase 3.9 | **Option B:** accept the punch when **either** the IST civil date **or** the previous IST civil date sits in an `OPEN` period; refuse only when both are closed. Strictly safer than today, satisfies §12's intent, and does not regress night shifts. `calculate()` remains the real backstop, and the orphan report (6.6) makes any inert punch visible. **Option A** (plain IST civil date) is simpler and acceptable for a tenant with no cross-midnight shifts. |
| **OD-2** | **Punch rounding — wire in, or withdraw?** (`DEC-TZ-06`) | Wiring it in **changes computed attendance** for every tenant with a non-`NONE` value. Withdrawing removes a configured feature. | Nothing — deferred | Audit which tenants have non-`NONE` values first. **Do not implement in this workstream.** |
| **OD-3** | **Night-OT window — honour `night_ot_mode`, or remove it?** (`DEC-TZ-07`) | Changes OT classification and therefore **pay**. | Nothing — deferred | Separate HR policy decision. **Do not invent the rule** (task §17). |
| **OD-4** | **Is the ±2h punch pad correct?** (`DEC-TZ-16`) | *"How early may someone arrive and still have it count?"* is an attendance-policy question. | Nothing — the **orphan report** needs no decision | Ship the report (6.6) first. Nobody can judge ±2h while the failure is invisible. |
| **OD-5** | **Amend `DEC-010`'s rendering clause?** | It is a **LOCKED** decision. Literal compliance (`company.timezone`) would be a second bug, since WD-06 already superseded it for computation. | Phase 5.6 | Amend it to name the WD-06-resolved zone. For India V1 the two coincide, so the amendment is free now and correct later. |
| **OD-6** | **Are there third-party punch integrations?** | The repository cannot answer it. | Phase 1 release strategy | Resolve in Phase 0.9 from production access logs. |

## 23.3 Explicitly deferred — with triggers

| Item | Trigger that reopens it |
|---|---|
| DST scheduled-minutes / OT policy (`DEC-TZ-14`) | First DST-observing tenant |
| Ambiguous / nonexistent local times (`DEC-TZ-11`) | First DST-observing tenant |
| tzdata pinning and image digest pinning (`TZ-05`) | First non-`Asia/Kolkata` tenant |
| Effective-dated timezone columns (`DEC-TZ-13` Option B) | First genuine branch relocation, or first multi-timezone tenant |
| Employee-level timezone (`DEC-TZ-09`) | A confirmed remote-work requirement — amends LOCKED `WD-06` |
| Offline / mobile queue (`DEC-TZ-15`) | A mobile client entering development |
| `punch.request_time` column split (§3.2) | First device or offline ingestion path |
| `shift_break.crosses_midnight` column (`R-SB-01`) | After Phase 4 is stable |
| `ATT-009` — gap end-time break matching | Separate P3; must not be bundled into Phase 4 |
| Geofencing (`F-19`) | Product decision; a separate workstream |
| Face / biometric attendance | A separate workstream — **never** mixed into this one |

---

# 24. FINAL EXECUTIVE VERDICT

## Recommended V1

```text
Business timezone:              Asia/Kolkata
Authoritative online punch:     Backend / server
Offline attendance:             Disabled
Client clock:                   Not authoritative
Client timezone:                Not authoritative
Stored timestamp:               Exact timezone-aware instant (UTC TIMESTAMPTZ)
Display timezone:               Asia/Kolkata, always labelled IST
Period / attendance date:       India local business date
Timezone changes:               Locked once computed attendance exists
DST:                            Deferred
Employee-specific timezone:     Deferred
Night OT:                       Separate HR policy decision
Rounding:                       Separate attendance policy decision
Calculation:                    Immediate + scheduled reconciliation (09:30 IST)
Production:                     NO-GO until P0 fixes and the CI / staging gates pass
```

## Status of every element

### ✅ ALREADY IMPLEMENTED — do not rebuild

UTC `TIMESTAMPTZ` storage throughout · timezone-aware arithmetic with a single conversion point ·
IANA identifiers only · zero `datetime.utcnow()` · WD-06 precedence (TEST-PROVEN) · a timezone
chain that cannot fail open · cross-midnight attendance-date attribution · DST arithmetic
(CODE-PROVEN, re-verified for this plan) · holiday / weekly-off / leave on the local date ·
append-only punches (WD-11) · version FKs + `computation_snapshot` · effective-dated shift versions
and employee assignments · period close → `bulk_lock` → locked days refused · strong authorization
and RLS · a pure, independently testable calculation engine.

### 🔧 REQUIRES CODE CHANGE

Server-authoritative self-punch · naive-timestamp rejection · future and far-past bounds ·
server-assigned `source` · `raw_payload` capture · **`ShiftVersion.timezone` IANA validation
(NEW-01)** · the timezone-change guard, called from **both** paths · registration timezone gate
(**NEW-04**) · alias handling (**NEW-03**) · `business_today()` at 6 sites · **the UTC date reaching
`/days/calculate` (NEW-02)** · the duplicate `todayIso()` (**NEW-05**) · cross-midnight break
matching · IST rendering at 24 call sites · scheduled calculation + reconciliation · row lock on
recompute · orphan-punch report · CI PostgreSQL + migrations + **web job (NEW-06)** + required
checks · `TZ=UTC` pinning.

### ⚖️ REQUIRES CLIENT APPROVAL

`OD-1` period-lock basis (**blocks Phase 3.9**) · `OD-2` punch rounding · `OD-3` night-OT window ·
`OD-4` ±2h pad width · `OD-5` amending LOCKED `DEC-010` · `OD-6` third-party integrations.

### ⏸️ DEFERRED

DST business policy · ambiguous/nonexistent local times · tzdata pinning · effective-dated timezone
columns · employee-level timezone · offline and mobile · `request_time` column split ·
`shift_break.crosses_midnight` · `ATT-009` · geofencing · biometric identity.

---

## The closing statement

The timezone **engine** is sound and was proven so by execution, not asserted from documentation.
Nothing in this plan asks anyone to rebuild it, and §5.2 lists explicitly what must not be touched.

What is not sound is everything around it: the attendance timestamp is a self-declared number
submitted through a field designed to be edited, labelled with a provenance string the submitter
chooses; the timezone that anchors every calculation is a mutable column that `recompute()` re-reads
and that one of its two write paths does not guard at all — and whose highest-precedence link is not
even validated as a real timezone; nothing computes attendance unless a human asks; night-shift
breaks that cross midnight are silently unpaid; and 783 integration tests do not run in CI.

> **The timezone subsystem is a well-built instrument reading an untrusted input.**
> This plan fixes the input, protects the instrument's history, gives it a schedule and a test
> harness — and changes the instrument itself in exactly one function.

**Recommendations in this document carry no authority.** They exist so that each decision has a
starting point, not so that it can be skipped. Nothing here may be implemented until this plan is
reviewed and approved, and nothing gated on `OD-1`…`OD-6` may be implemented until those decisions
are recorded.

---

*Plan prepared 2026-09-15 against the working tree at branch `main`. **No application code,
database schema, migration, test, or CI configuration was modified.** Claims marked **VERIFIED**
were reproduced by executing the shipped code read-only (`apps/api/.venv/bin/python`), by running
`pytest tests/unit`, or by read-only queries against the running dev PostgreSQL on port 5433. Every
file and line citation was read from the working tree on this date. Production data and production
deployment configuration are **NOT VERIFIED** — no production environment is reachable from this
repository, and §13.1 and §16 Phase 0 make inspecting them explicit preconditions.*
