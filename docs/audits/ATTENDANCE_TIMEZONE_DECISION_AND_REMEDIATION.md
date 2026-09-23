# Attendance — Timezone Decision & Remediation Specification

**Created:** 2026-09-15
**Status:** SPECIFICATION — awaiting client/product decisions. **Nothing here is implemented.**
**Stage:** `AUDIT → FACTS → RISKS → BUSINESS DECISIONS → ` **`CLIENT APPROVAL / IMPLEMENTATION PLANNING`** ` → IMPLEMENTATION`

**Code changed: NO · Schema changed: NO · Migrations changed: NO · Tests changed: NO · Configuration changed: NO**

---

## What this document is

This is the **canonical** timezone artefact. It converts three completed audits into one register of
facts, one register of decisions the client must make, and one implementation backlog that may not be
started until those decisions are recorded.

| Source | Role |
|---|---|
| [`ATTENDANCE_TIMEZONE_AUDIT.md`](./ATTENDANCE_TIMEZONE_AUDIT.md) | Timezone findings `TZ-01…TZ-14`; the system-wide time flow, DB audit, DST proof |
| [`ATTENDANCE_TIMEZONE_TEST_MATRIX.md`](./ATTENDANCE_TIMEZONE_TEST_MATRIX.md) | 68 boundary scenarios computed from the shipped code; 4 have an automated test |
| [`../business-rules/attendance/ATTENDANCE_TIME_TIMEZONE_IMPLEMENTATION_AUDIT.md`](../business-rules/attendance/ATTENDANCE_TIME_TIMEZONE_IMPLEMENTATION_AUDIT.md) | Ingestion/authoritative-clock findings `F-01…F-27` |
| [`../business-rules/attendance/ATTENDANCE_TIMEZONE_DECISION_REGISTER.md`](../business-rules/attendance/ATTENDANCE_TIMEZONE_DECISION_REGISTER.md) | `DEC-TZ-01…DEC-TZ-14`, all OPEN — **superseded as the decision surface by §17 here** |
| [`TECHNICAL_DEBT_REGISTER.md`](./TECHNICAL_DEBT_REGISTER.md) | `PAY-013`, `ATT-001…005`, `TZ-1`, `FE-1`, `DAT-004/005` |
| [`../adr/0010-utc-storage-company-timezone-render.md`](../adr/0010-utc-storage-company-timezone-render.md) · `DEC-010` | LOCKED: UTC storage, company-timezone rendering, company-timezone business-day boundaries |
| [`../architecture/WORKFORCE_ATTENDANCE_DECISION_LOG.md`](../architecture/WORKFORCE_ATTENDANCE_DECISION_LOG.md) | `WD-06` (timezone precedence), `WD-11` (reproducibility), `WD-30` (period lock) |
| [`../modules/attendance/ATTENDANCE_MASTER_RULE_MATRIX.md`](../modules/attendance/ATTENDANCE_MASTER_RULE_MATRIX.md) | Rules `B2`, `C1`–`C4` |

**Evidence labels used throughout**

| Label | Meaning |
|---|---|
| **CODE-PROVEN** | Reproduced by executing the shipped code read-only, or an unambiguous single-path source citation |
| **TEST-PROVEN** | An automated test in the repository asserts it |
| **DOCUMENTED** | Stated in repository documentation |
| **UNTESTED** | Observed in code; no automated test covers it |
| **NOT VERIFIED** | Cannot be determined from this repository |

Every source citation in this document was re-verified against the working tree on 2026-09-15.

---

# 2. PROVEN CORRECT — DO NOT CHANGE UNLESS REQUIRED

Fifteen behaviours were **proven**, not assumed. None of them is a candidate for redesign. Several of
them are the reason the rest of this document could be written by execution rather than by opinion.

> **Reading rule for this section.** "Regression tests exist: NO" is *not* a defect and does not
> create remediation work by itself — it creates **test** work, tracked in §19. The implementation is
> to remain unchanged in every row below.

| # | Behaviour | What is proven | Evidence | Regression tests exist | Implementation should change? |
|---|---|---|---|---|---|
| **PC-01** | **Server timezone independence** | The full engine produced **byte-identical** output for day shifts, cross-midnight shifts, all scheduled spans and all DST spans under `TZ=UTC`, `TZ=Asia/Kolkata`, `TZ=America/New_York` and `TZ=Pacific/Kiritimati` (UTC−4 → UTC+14). The only differing line was the naive-coercion probe, which no correctly-formed request exercises. | CODE-PROVEN — four-way execution diff (audit §5; matrix G1–G4) | **NO** | **NO.** Add a parametrised `TZ` test (§19) and pin `TZ=UTC` as defence in depth (TZ-02) — no logic change. |
| **PC-02** | **UTC timestamp storage** | Every attendance timestamp column is `TIMESTAMPTZ`. **No `timestamp without time zone` exists anywhere in the attendance schema.** Proven from four independent layers: migrations, ORM `DateTime(timezone=True)`, live `SHOW TimeZone` = `UTC`, and `_format_timestamp` emitting `…Z`. | CODE-PROVEN (audit §2, §3); implicitly TEST-PROVEN across the suite | Implicit only | **NO.** This satisfies DEC-010's storage clause exactly. |
| **PC-03** | **Timezone precedence (WD-06)** | `resolve_timezone()` is `shift_version_timezone or branch_timezone or company_timezone` — a single 2-line function (`calculation.py:294-298`), called once per calculation, whose result flows into **every** consumer: schedule window, late/early, worked minutes, breaks, core hours, holiday, weekly-off, leave, regularization. | CODE-PROVEN + **TEST-PROVEN** (`test_resolve_timezone_prefers_shift_version`, `…falls_back_to_branch_then_company`) | **YES** (resolution only) | **NO.** Matrix D1–D6 should be added to protect the *consequences* of resolution, not the function. |
| **PC-04** | **Resolution can never fail open to the server** | `company.timezone` is `NOT NULL DEFAULT 'Asia/Kolkata'`, so the chain always terminates in a real IANA id. There is no code path where a missing timezone falls back to the process OS zone. | CODE-PROVEN (`core/db/models/identity.py:45`; matrix D6) | NO | **NO.** This is a deliberate and correct fail-safe. |
| **PC-05** | **Cross-midnight attendance-date attribution** | A `22:00→06:00` shift attributes the entire `20:00`→`08:00` local band to the **shift's start date**. Midnight does not move the day. Driven by the explicit `ShiftVersion.is_cross_midnight` boolean — **never inferred** from `end_time < start_time`. Verified for `22:00→06:00`, `23:00→07:00`, `18:00→02:00`. Clean, unambiguous, no overlap with the adjacent day. | CODE-PROVEN (matrix B1–B11); span attribution **TEST-PROVEN** (`test_scheduled_span_cross_midnight_attributes_to_start_date`) | **PARTIAL** — span only, not the 9 ownership boundaries | **NO.** Matches FR-ATT-005. |
| **PC-06** | **DST arithmetic** | A `22:00→06:00` shift spans **540 real minutes** on a fall-back night and **420** on a spring-forward night, in both `Europe/London` and `America/New_York`; `Asia/Kolkata` gives 480 as a control. Scheduled spans, worked minutes, late, early, OT and cross-midnight all remain correct across a transition. This is **true elapsed time**, not naive wall-clock subtraction. | CODE-PROVEN across four real transitions (audit §11; matrix C1–C9, C14) | **NO — zero DST tests exist** | **NO.** The arithmetic is right. **What it *means* for pay is an open decision (DEC-TZ-14), not a defect.** This upgrades `ATTENDANCE_MASTER_RULE_MATRIX.md` **C3** from *"presumed yes (stdlib)"* to CODE-PROVEN. |
| **PC-07** | **Holiday date handling** | Holidays are resolved by `calendar_service.resolve_for_employee(company_id, employee_id, target_date)` where `target_date` is the **local attendance date**. No UTC date ever reaches holiday matching. | CODE-PROVEN (`attendance/service.py:2854-2864`) | Indirect | **NO.** |
| **PC-08** | **Weekly-off date handling** | Same call, same local `target_date`; `holiday_on_weekly_off` and `operates_on_weekly_off` are derived from it. No UTC-date contamination. | CODE-PROVEN (`attendance/service.py:2803, 2859-2864`) | Indirect | **NO.** |
| **PC-09** | **Leave date handling** | `LeaveDayProjection` is keyed on `attendance_date` (a `DATE` column holding the local business date) and overlaid on the same local date the engine computed. | CODE-PROVEN (audit §1 stage 19, §15) | Indirect | **NO.** |
| **PC-10** | **Shift-level effective dating** | `ShiftVersion.timezone` is versioned by `effective_from`/`effective_to` with a GiST no-overlap constraint on published rows, and `resolve_shift_version_as_of` returns the **old** version for old dates. A shift timezone edit therefore **cannot** rewrite history. | CODE-PROVEN (matrix E1) | **NO** | **NO.** This is the model the Branch/Company columns should have followed — see TZ-01. |
| **PC-11** | **Branch *assignment* is effective-dated** | An employee who transfers branch keeps the old branch's zone for past dates, because `EmployeeAssignment` is resolved as-of the date. **Changing which branch an employee belongs to is safe.** (Changing a branch's *timezone value* is not — that is TZ-01, a different thing.) | CODE-PROVEN (matrix E4) | **NO** | **NO.** |
| **PC-12** | **Calculation-engine purity** | `calculation.py` performs no I/O; all DB access lives in `service.py`. The engine is a pure function of `(punches, shift, policy, IANA string)`. | CODE-PROVEN (F-24) | Extensively (~60 unit tests) | **NO.** This is precisely why every claim above could be proven by execution. It is the codebase's single most valuable structural property. |
| **PC-13** | **`datetime.utcnow()` appears zero times** | A repository-wide grep finds none. The most common timezone bug in Python codebases is entirely absent; every server instant is `datetime.now(UTC)` or PG `func.now()`. | CODE-PROVEN (audit §4) | n/a | **NO.** Worth a lint rule to keep it that way (P3). |
| **PC-14** | **IANA identifiers only** | No `IST`/`EST`/`GMT`/`PST` abbreviation appears anywhere in application code. Every timezone column is validated against `zoneinfo.available_timezones()` at the schema layer. `Asia/Kolkata` appears only as a *default value*, never as hardcoded conversion logic. `pytz` is not used. | CODE-PROVEN (F-22) | Schema-level | **NO.** |
| **PC-15** | **Break matching converts before comparing** | `match_breaks` converts the UTC gap to local **before** the time-of-day comparison (`calculation.py:583`), which is the correct order. A gap at the *ambiguous* `01:10` local on a London fall-back night matched its `01:00–01:30` break with `matched=True, paid=True`. | CODE-PROVEN (matrix C14) | **NO** | **NO — for the DST dimension.** Its *separate* cross-midnight defect (F-05, §12) is unrelated to this and is real. |

### Two properties that are proven and are load-bearing for everything below

1. **The engine is a pure function.** Groups A, B, C, D and G of the test matrix — 46 of the 68
   scenarios — need **no database**. They are fast unit tests. This makes the test backlog in §19
   unusually cheap relative to the risk it closes.
2. **Reproducibility is designed in.** Every version FK used is stored on `attendance_day` alongside a
   `computation_snapshot` JSONB trace (WD-11, F-25). Historical attendance does not drift when
   *policies* are edited later. **Timezone is the one input that escaped this design** — it is stored
   on `attendance_day.timezone` but never read back as an input. That single asymmetry is TZ-01.

---

# 3. FINDING REGISTER

All findings that bear on time, timestamps or timezones, in **one** register. IDs are the originals —
`TZ-nn` from the timezone audit, `F-nn` from the ingestion audit. **No ID has been renamed.** Where the
two audits describe the same defect from different angles, the relationship is stated rather than
merged, so cross-references from either source document still resolve.

**Severity:** 🔴 BLOCKER · 🟠 CRITICAL · 🟡 HIGH · 🔵 MEDIUM · 🟢 LOW

## 3.1 Timezone findings (`TZ-nn`)

| ID | Sev | Finding | Evidence | Actual Impact | Production Blocking? | Fix Required? | Decision Required? |
|---|---|---|---|---|---|---|---|
| **TZ-01** | 🔴 P0 | `Branch.timezone` / `Company.timezone` are single mutable columns, not effective-dated, and `recompute()` re-resolves the zone from the **current** row. The stored `attendance_day.timezone` is write-only provenance, read in exactly one place (`schemas.py:1391`) — for the API response, never as an input. The guard `_assert_timezone_change_allowed` (`organisation/service.py:702-709`) is an empty stub whose stated precondition (*"until Payroll/Attendance modules exist"*) **has been met**, and `update_branch` (`:1106`) never calls it at all. | CODE-PROVEN. Verified: `recompute` (`service.py:2631-2652`) passes only `(employee_id, attendance_date)`; guard body is `_ = (company_id, current_timezone, new_timezone)`; grep confirms `update_branch` has no guard call. | Editing a company or branch timezone silently rewrites **already-reviewed, already-approved** historical attendance on the next recompute. Worked example: day flips `PRESENT` → **264 minutes early departure**. Directly upstream of `paid_day_fraction` / `lop_fraction`. Every routine event triggers recompute: an approved regularization, OT re-detection, a backdated policy publish, an admin clicking Recompute. | **YES** | **YES** | **YES — DEC-TZ-13 (§5)** determines *what* the guard enforces |
| **TZ-02** | 🔴 P0 | Naive `punch_time` is accepted and resolved by asyncpg against the **Python process OS timezone**. `PunchCreate.punch_time: datetime \| None` (`schemas.py:1234`) has no offset requirement; `apps/api/Dockerfile` sets no `TZ`. | CODE-PROVEN. Verified: naive `09:00` → `03:30Z` on the IST dev host, `09:00Z` in a UTC container — 5h30m divergence from the identical request. `python:3.12-slim` reports local tz `UTC` (verified by running the real base image); dev host is `Asia/Kolkata` (verified). Dockerfile re-read 2026-09-15: no `ENV TZ`. | **The only place server location changes attendance results.** Silent, environment-dependent data corruption. Self-consistent in each environment, so testing will never reveal it; it surfaces only at reconciliation or when a third-party client omits the offset. | **YES** | **YES** (two independent parts: reject naive input **and** pin `TZ=UTC`) | **YES — DEC-TZ-04**, though every option except "keep current" fixes it |
| **TZ-03** | 🟠 P1 | UI renders every attendance time in the **viewer's browser timezone**. `format.ts:16,21` pass `undefined` as locale to `toLocaleTimeString`/`toLocaleString`, taking both locale **and zone** from the browser. This contradicts **LOCKED** decision `DEC-010`. | CODE-PROVEN — source re-read 2026-09-15. The API *does* return `attendance_day.timezone`; `attendance/[id]/page.tsx:110` even prints it as a subtitle; **no formatter consumes it**. No timezone label accompanies any rendered time. | An HR user in Dubai reviewing a Kerala employee sees every time shifted 1h30m from the zone its `late_minutes` was computed in, with no indication. Misread attendance → disputes → erosion of trust in figures that are actually correct. | **YES — at the moment a second timezone goes live.** Not before. | **YES** | **YES — DEC-TZ-08 (§9)**: confirm DEC-010 or amend it |
| **TZ-04** | 🟠 P1 | **Zero automated tests exercise a DST date.** `America/New_York` and `Europe/London` appear in the suite only as *arguments to the precedence test*, never for evaluation. All other tests use `Asia/Kolkata` or `UTC` — neither has DST. | CODE-PROVEN by grep, re-verified 2026-09-15: 4 hits total across `apps/api/tests/`, all in `test_calculation.py:86-99`. | PC-06 — the audit's central positive finding — is **completely unprotected**. A refactor of `_local_to_utc`, `scheduled_span_utc` or `match_breaks` could silently regress DST correctness tomorrow, and nothing would fail. | **Conditionally** — blocking before any DST-observing tenant | **YES — this finding *is* the missing test** | NO |
| **TZ-05** | 🟠 P1 | tzdata is stale-by-construction and the newer copy is **shadowed**. System tzdata **2026b** (Debian 13, frozen at image build) wins over PyPI `tzdata` **2026.3** because `TZPATH[0] = /usr/share/zoneinfo`. `tzdata` is an **undeclared transitive** dependency (via `kombu`/`psycopg`/`tzlocal`), absent from `pyproject.toml`. The Dockerfile runs no `apt-get`; `python:3.12-slim` is not digest-pinned; no rebuild cadence documented. | CODE-PROVEN by running the actual base image. `uv.lock:2148` pins `tzdata 2026.3`; `pyproject.toml` has no `tzdata` entry (re-verified 2026-09-15). | The newer tzdata is installed but never consulted; the older one never updates. **Dormant for India** (no DST, stable offset since 1945). Live the moment a DST-observing or recently-reformed jurisdiction is onboarded — timezone rules change several times a year by government decree. | **Conditionally** — blocking before any non-IST tenant | **YES** | NO — engineering policy, not client policy |
| **TZ-06** | 🔵 P2 | `date.today()` (= server-OS-local date) at four call sites governs regularization future-date rejection and backdating windows. | CODE-PROVEN — re-verified 2026-09-15: `attendance/service.py:3502,3547`; `leave/service.py:1979,2597`. A fifth related site: `leave/service.py:1990` counts `max_requests_per_month` from a **UTC** month start. | A regularization request valid at 23:00 IST may be rejected as future-dated in a UTC container, or vice versa. Boundaries move between dev and production. Contradicts DEC-010's *"never server-local time"*. | NO | **YES** | NO |
| **TZ-07** | 🔵 P2 | `todayIso()` (`format.ts:28`) returns the **UTC** date (`new Date().toISOString().slice(0,10)`). Seeds default date filters on the attendance, overtime, rosters and regularizations pages. | CODE-PROVEN — source re-read 2026-09-15. | For IST users between 00:00 and 05:30 local, **every default filter is off by one day**. Display only — never reaches a calculation. Contradicts DEC-010's *"never UTC midnight"*. | NO | **YES** | NO |
| **TZ-08** | 🔵 P2 | The punch load window is a **fixed ±2h pad** around the scheduled span (`lookback_hours: int = 2`, `lookahead_hours: int = 2`, `calculation.py:314-330`). Both are defaulted and **never overridden by any caller**. Not policy-configurable. | CODE-PROVEN — signature re-read 2026-09-15; matrix A1–A11, B1–B9. For a `09:00–18:00` `Asia/Kolkata` shift, only `07:00`–`20:00` local is loadable. | A punch at `06:59` or `20:01` local is **stored but belongs to no attendance date** — silently inert, no error, no orphan report. Under-counts genuinely early-arriving or late-departing workers. (Same mechanism makes an out-of-range fabricated timestamp harmless — the one place it helps.) | NO | **Conditionally** — only if §15's decision changes the pad | **YES — DEC-TZ-16 (§15)** |
| **TZ-09** | 🔵 P2 | Timezone configuration can be read **torn** under READ COMMITTED. `_build_calculation_input` issues separate `SELECT`s for employment, assignment, company, branch, roster and shift version; a `Company.timezone`/`Branch.timezone` `UPDATE` committing between two of them is visible to the later statements but not the earlier ones. | CODE-PROVEN — `SHOW default_transaction_isolation` → `read committed` on the running dev Postgres; nothing in `core/db/session.py` sets `isolation_level` or `execution_options`. | One `attendance_day` can mix pre-change and post-change configuration, with **no error raised**. Window is milliseconds; trigger is rare. | NO | **YES** (or closed as a side effect of TZ-01) | NO |
| **TZ-10** | 🔵 P2 / **DECISION** | A DST transition changes `scheduled_minutes` (540 on a fall-back night, 420 on spring-forward), and `detect_overtime` computes `worked − scheduled`. | CODE-PROVEN by execution (audit §11). | An employee working the **full wall-clock shift** on a fall-back night earns **zero OT for nine real hours**; one working eight real hours that night is flagged **60 minutes early departure**; on a spring-forward night a full shift earns a **full day's credit for seven real hours**. Arithmetically correct, internally consistent, and **undocumented**. | **Conditionally** — blocking before any DST-observing tenant | **NOT A BUG** — behaviour change only if the client chooses it | **YES — DEC-TZ-14 (§7)** |
| **TZ-11** | 🟢 P3 / **DECISION** | Nonexistent and ambiguous local wall times resolve **silently** via `ZoneInfo`'s default `fold=0`. | CODE-PROVEN. Verified: `America/New_York 2026-03-08 02:30` (does not exist) → `07:30Z` = `03:30 EDT`; `2026-11-01 01:30` (occurs twice) → `05:30Z`, the first occurrence. Same pattern for `Europe/London`. | A shift configured to start at `02:30` on a spring-forward date **actually starts at 03:30**, with no warning at publish time or calculation time. Deterministic and conventional — but unchosen and unrecorded. | **Conditionally** — before any DST-observing tenant | **Documentation + publish-time warning**, not a resolution change | **YES — DEC-TZ-11 (§8)** |
| **TZ-12** | 🟢 P3 | The defensive `if end <= start: end += timedelta(days=1)` fallback (`calculation.py:344-345, 362-363`) adds a day in **UTC**, not in local time. | CODE-PROVEN — re-read 2026-09-15 in both `punch_window_utc` and `scheduled_span_utc`. | For a shift that **both** omits `is_cross_midnight` **and** spans a DST transition, the span is off by the offset delta. **Latent** — `is_cross_midnight` is the real path and is always set by the shift UI. | NO | **YES** (cheap, defensive) | NO |
| **TZ-13** | 🟢 P3 | `app_timezone_default` (`settings.py:32`, default `Asia/Kolkata`) reads like an application-wide timezone but is consumed **only** by Celery beat (`celery_app.py:18`). No attendance code reads it. | CODE-PROVEN by grep. | Invites a false assumption that the application has a configured timezone — the kind of misreading that produces a wrong "fix" later. | NO | **Rename or document** | NO |
| **TZ-14** | 🟢 P3 / **NOT VERIFIED** | No NTP, chrony or timesyncd configuration or documentation anywhere. No deployment manifest for the API service exists in the repository (`docker-compose.yml` covers postgres/redis/minio only). App and DB clocks are **never compared** in code. | CODE-PROVEN by absence (greps for `ntp`, `chrony`, `timesyncd`, `clock skew` across all YAML, Dockerfiles, scripts and docs return nothing relevant). Expected drift and failure behaviour: **NOT VERIFIED**. | **Harmless today**, because `created_at` is advisory and never used for calculation. Becomes **load-bearing the instant DEC-TZ-01 is decided in favour of server-stamped punches or a bounded-skew check** — both of which compare against the server clock. | **Conditionally** — blocking *iff* DEC-TZ-01 resolves to Option A or B | **YES**, conditional on DEC-TZ-01 | NO (engineering), but **gated by DEC-TZ-01** |

## 3.2 Ingestion / clock-trust findings (`F-nn`) that bear on time

| ID | Sev | Finding | Evidence | Actual Impact | Production Blocking? | Fix Required? | Decision Required? |
|---|---|---|---|---|---|---|---|
| **F-01** | 🔴 P0 | Client-supplied `punch_time` is accepted **verbatim, with no validation of any kind**. `service.py:2353` — `"punch_time": body.punch_time or now`. The server computes `datetime.now(UTC)` sixteen lines earlier (`:2337`) and uses it **only** for `created_at`; the two are **never compared**. | CODE-PROVEN — re-read 2026-09-15. Verified: `2099-01-01T00:00:00Z` and `1900-01-01T00:00:00Z` both accepted by the schema. No upper bound, no lower bound, no skew tolerance, no DB CHECK. | **Any user holding the baseline `ATTENDANCE.PUNCH` permission controls their own `late_minutes`, `worked_minutes`, `ot_minutes_detected`, `paid_day_fraction` and `lop_fraction`** — the documented payroll inputs. | **YES** | **YES** | **YES — DEC-TZ-01 (§6) is the blocker** |
| **F-02** | 🔴 P0 | The only shipped client makes the attendance timestamp a **user-editable form field**. `punch-entry-dialog.tsx:94,149` — `punch_time` is always sent, seeded from the browser clock and exposed as an editable `<input type="datetime-local">`. The same editable field serves both self-punch and on-behalf correction; no privilege distinguishes them in the dialog. | CODE-PROVEN | **No clock manipulation is even required** — the user simply types a different time. Manipulation is a supported UI affordance. Likelihood of exploitation: **certain**. | **YES** | **YES** | **YES — DEC-TZ-01** |
| **F-03** | 🔴 P0 | **No future-timestamp validation at any layer** — absent in the web form, in `PunchCreate`, in `record_punch`, and in the database. | CODE-PROVEN. Regularization **does** reject future dates (`service.py:3502`, with a deliberate `EARLY_DEPARTURE_APPROVAL` carve-out per WD-32); punches do not. **The asymmetry appears unintentional.** | Fabricated future overtime. Mitigated only accidentally: a far-future punch falls outside every ±2h window (TZ-08) and becomes an inert orphan. A *near*-future punch does not. | **YES** | **YES** | **YES — DEC-TZ-03**, bounded by DEC-TZ-02 |
| **F-05** | 🟠 P1 | **Break windows crossing midnight never match.** `calculation.py:588-601` compares local **time-of-day**: `start_time <= gap_start_local <= end_time`. For a `23:30–00:30` break, `23:30 <= 23:45 <= 00:30` is `False`. `shift_break` has **no cross-midnight flag** — unlike `shift_version.is_cross_midnight` and `shift_duty_block.crosses_midnight`. | CODE-PROVEN. Verified: a 20-minute gap at 23:45 IST against a paid `23:30–00:30` break returns `shift_break_id=None, is_paid=False`; the identical check against `13:00–14:00` matches correctly. Source re-read 2026-09-15. | **A paid-minutes defect, not a display defect.** The unmatched gap defaults unpaid → `worked_minutes` drops → `paid_day_fraction` drops → OT is suppressed. Hits exactly the night-shift population most likely to have a midnight-spanning break. Likelihood: **certain** wherever such a break is configured. | **YES** | **YES** | NO — unambiguous defect, see §12 |
| **F-06** | 🟠 P1 | `night_window_start`/`night_window_end` are **dead configuration**. `calculation.py:1237` sets `is_night = shift.is_cross_midnight` and never reads the window, though it is loaded into `OvertimePolicyInputs` (`service.py:3048-3049`). | CODE-PROVEN | `night_ot_mode="WINDOW"` behaves identically to `"BOTH"`. A day shift extending into the configured night window is **never** classified `NIGHT` for rate lookup → wrong OT multiplier → wrong money. Also `ATT-005` in the debt register. | **YES** (payroll correctness) | **YES** | **YES — DEC-TZ-07** |
| **F-11** | 🟡 P2 | `source` is client-settable with **no role check**. `service.py:2355` — `body.source or default_source`; the router's `default_source` is only a fallback. All 7 values, including `DEVICE` and `REGULARIZATION`, are accepted from an ordinary self-punch. | CODE-PROVEN — verified against the shipped `PunchCreate`. The DB CHECK permits all seven. | **Audit provenance is forgeable.** A hand-typed web punch can be recorded as a biometric device reading — destroying the distinction an investigator would rely on precisely when it matters. | **YES** (audit integrity) | **YES** | **YES — DEC-TZ-05** |
| **F-12** | 🟡 P2 | `requested_punches[].requested_time` on a regularization is **entirely unvalidated** — no check that the instant falls within the `attendance_date`, within shift boundaries, or in the past. | CODE-PROVEN | An out-of-window value produces an inert orphan punch (TZ-08) rather than inflated attendance, so impact is currently bounded — but nothing rejects or flags it, and that bound is an accident of TZ-08's pad, not a control. | NO | **YES** | NO |
| **F-04** | 🟠 P1 | `punch_rounding` / `rounding_minutes` are configurable, validated at publish, exposed in the policy UI — and **completely inert**. `apply_rounding` (`calculation.py:637`) has **zero call sites**. | CODE-PROVEN by repository-wide grep (definition + one docstring mention only). Also `ATT-001`/`DEAD-1`. | An HR user who configures 15-minute rounding gets none, and believes they got it. **Silent no-op configuration is worse than absent configuration.** Fixing it *changes computed attendance* for every tenant that configured a value — so it cannot be treated as a routine bug fix. | **YES** (policy credibility) | **YES** | **YES — DEC-TZ-06** (wire in vs. withdraw; and a communicated recompute if wired in) |
| **F-14** | 🟡 P2 | **No scheduled attendance calculation job.** `core/celery_app.py` defines four beat entries, all `leave.*`. `attendance_day` rows exist only where `POST /attendance/days/calculate` or `/recompute` was explicitly called. | CODE-PROVEN. Also `PAY-001` (🔴 P0 in the debt register). | An employee who punches in and out **has no attendance row** until something asks for one. A period cannot be finalized, so Payroll has no input at all. **Timezone-relevant because the schedule is timezone-dependent**: a nightly job must run after the last shift ends *in the latest zone the tenant operates in*, and cross-midnight shifts are not complete until the following morning. | **YES** | **YES** | **YES — DEC-TZ-12** (*when*, and whose midnight) |
| **F-15** | 🔵 P2 | **No row lock on concurrent recompute.** Two simultaneous `calculate()` calls for one employee-date both read-then-write. | CODE-PROVEN by absence. | The `UNIQUE` constraint prevents duplicate rows but **not last-writer-wins**. Combined with TZ-09, two concurrent recomputes straddling a config edit can persist either result non-deterministically. | NO | **YES** | NO |
| **F-18** | 🔵 P2 | `punch.raw_payload` is **declared and never written** (`models.py:464`; zero writes). No device metadata, IP or GPS is captured on the punch row. | CODE-PROVEN by grep | Removes the evidence an investigator would need to adjudicate a disputed punch — directly weakens whatever DEC-TZ-01 decides, because a bounded-skew or flag-and-review posture needs somewhere to record *what* was received. | NO | **Conditional on DEC-TZ-01** | Gated by **DEC-TZ-01** |
| **F-19** | 🔵 P2 | `Branch.geofence_radius_m` is **stored, editable in the branch UI, and read by no punch code path.** | CODE-PROVEN (`organisation/models.py:139`) | Geofencing is unenforced while appearing configured — the same silent-no-op pattern as F-04 and F-06. Out of timezone scope; listed because it is part of the same punch-trust surface. | NO | **YES** (wire in or withdraw) | **YES** (same shape as DEC-TZ-06) |
| **F-20** | 🟢 P3 | Punch list filters on **UTC** dates while day list filters on **local** dates. | CODE-PROVEN, and **documented** (`repository.py:1006`) | Correct per entity, but reconciling the two at a month boundary yields mismatched sets. Documentation issue, not a defect. | NO | NO | NO |

## 3.3 Findings closed by this specification

| ID | Was | Now |
|---|---|---|
| `TECHNICAL_DEBT_REGISTER.md` **TZ-1** — *"No DST-transition test"* | 🟢 LOW, P4 | **Re-rated 🟠 P1 (TZ-04).** It was rated LOW on the reasoning *"India has no DST"*. That reasoning holds for the **tenant base**, not for the **codebase**: DST correctness is now CODE-PROVEN and is the audit's central positive finding, and it is unprotected. |
| `ATTENDANCE_MASTER_RULE_MATRIX.md` **C3** — *"Presumed yes (stdlib) … not independently proven"* | DOCUMENTATION GAP | **CODE-PROVEN correct** by the 2026-09-15 audit across four real transitions. Still **UNTESTED** (TZ-04). §18 carries the doc update. |
| `TECHNICAL_DEBT_REGISTER.md` **PAY-013** — *"`_assert_timezone_change_allowed` is a no-op"* | 🟠 P0 | **Confirmed and worse than documented** (TZ-01): `update_branch` has no guard call at all, and `recompute` actively re-resolves rather than merely failing to pin. |
| `TECHNICAL_DEBT_REGISTER.md` **FE-1** — *"no company-timezone renderer despite ADR-0010"* | 🔵 P4 | **Confirmed; elevated to 🟠 P1 (TZ-03)** because it conflicts with a **LOCKED** decision, not merely with a nice-to-have. |

---

# 4. CLASSIFICATION — BUGS vs. BUSINESS DECISIONS

Every finding is assigned **exactly one** class. The purpose of this section is to stop three specific
mistakes: fixing a policy question as though it were a bug, deferring a bug as though it were a policy
question, and creating work for something that is already correct.

> **The rule applied.** A finding is a **CODE BUG** only where an *already-approved* rule — a LOCKED
> `DEC-nnn`, a LOCKED `WD-nn`, or an explicit configuration contract the product exposes to the user —
> says one thing and the code does another. Where no approved rule exists, the finding is a
> **BUSINESS POLICY DECISION**, however obvious the "right" answer looks from an engineering seat.

## 4.1 CODE BUG — the implementation violates an already-approved rule

| ID | The approved rule it violates | The deviation |
|---|---|---|
| **TZ-01** | **WD-11 (LOCKED)** — *"Each AttendanceDay stores the version IDs actually used plus a `computation_snapshot`"*; historical attendance does not drift when configuration is edited later. | Timezone is the **one** calculation input that is stored on `attendance_day` but never read back. Every other input is pinned by a version FK. Additionally: a guard function exists, its own documented precondition is met, and one of the two mutation paths (`update_branch`) does not call it at all. **Those two facts are defects regardless of which option §5 selects.** |
| **TZ-02** | **DEC-010 (LOCKED)** — *"never server-local time"*. | A naive `punch_time` is resolved against server-local time, producing a different stored instant in dev than in production. |
| **TZ-03** | **DEC-010 (LOCKED)** — *"`company.timezone` is the single source of truth for **rendering**"*. | The UI renders in the viewer's browser timezone. **This is the clearest CODE BUG in the register** — a locked decision states the requirement, the data is already on the wire, and no formatter uses it. §9 offers the client the option to *amend the locked decision instead*, which is the only reason a decision is attached. |
| **TZ-06** | **DEC-010 (LOCKED)** — *"never server-local time"*. | `date.today()` at 4 sites (+ a UTC-month count at `leave/service.py:1990`). |
| **TZ-07** | **DEC-010 (LOCKED)** — *"never UTC midnight"*. | `todayIso()` derives the default filter date from UTC midnight. |
| **TZ-09** | **WD-11 (LOCKED)** — reproducibility. | A single calculation can mix pre- and post-change configuration, so it is not reproducible from its own inputs. |
| **TZ-12** | The engine's own cross-midnight contract (`is_cross_midnight` drives the day roll). | The defensive fallback rolls the day in UTC rather than local time. Latent. |
| **F-05** | The product's own break configuration contract — a configured paid break is paid. | A `23:30–00:30` break never matches; the gap silently defaults unpaid. |
| **F-06** | The `night_ot_mode` enum contract — `SHIFT_FLAG` / `WINDOW` / `BOTH` are all selectable in the UI. | Only `SHIFT_FLAG` behaviour exists; `WINDOW` silently behaves as `BOTH`. |
| **F-04** | The policy configuration contract — `punch_rounding` / `rounding_minutes` are exposed, validated and persisted. | `apply_rounding` has zero call sites. |
| **F-12** | The regularization contract — a requested punch is a punch for *that* attendance date. | `requested_time` is unvalidated against the date or the shift. |
| **F-15** | **WD-11** — recomputation must be deterministic. | No row lock; last-writer-wins between concurrent recomputes. |
| **F-18** | The schema's own declaration — `punch.raw_payload` exists to hold submission evidence. | Never written. |
| **F-19** | The branch configuration contract — `geofence_radius_m` is exposed and editable. | Read by no punch path. |

> **On F-04, F-06 and F-19 specifically.** These are bugs *of the same family*: **configuration the
> product exposes, validates and persists, which the engine silently ignores.** The debt register
> already names this pattern as the reason `ATT-001…007` are findings rather than deferrals, and the
> reasoning is right — the codebase's normal, admirable habit is to *refuse to invent* behaviour a
> policy does not describe. These three are the inverse: the policy **does** describe it. Each carries
> an attached decision only because the *remedy* is a genuine fork — wire it in (which changes computed
> attendance for tenants who configured it, and requires a communicated recompute) or withdraw the
> field and its UI. Both are legitimate; neither is free.

## 4.2 SECURITY ISSUE — the implementation permits manipulation or unsafe behaviour

| ID | What is permitted | Why this is security, not a bug |
|---|---|---|
| **F-01** | Any holder of the baseline `ATTENDANCE.PUNCH` permission sets their own attendance timestamp, unbounded in both directions. | There is no approved rule being violated — **the repository is silent on which clock is authoritative** (greps for *"server time"*, *"client time"*, *"device clock"*, *"trusted"*, *"clock skew"*, *"spoof"* across the architecture, the decision log and all of `docs/business-rules/attendance/` return nothing). This is a **specification gap that happens to be exploitable**, which is why F-01 is a security issue gated on DEC-TZ-01 rather than a bug with an obvious fix. |
| **F-02** | The shipped UI makes the timestamp an editable field, so no manipulation is required — typing is the attack. | Same gap; this is its user-facing expression. |
| **F-03** | Arbitrarily future-dated punches → fabricated overtime. | The regularization path already rejects future dates; the punch path's omission is an inconsistency with an existing control. |
| **F-11** | An employee labels a hand-typed web punch as `source="DEVICE"` or `"REGULARIZATION"`. | Defeats audit provenance — the field an investigator would rely on to distinguish a biometric reading from a manual entry. |

> **These four are one risk, not four.** Together they mean: *the attendance timestamp is a
> self-declared number, submitted through a field designed to be edited, labelled with a provenance
> string the submitter chooses, with no bound in either direction and no comparison to any trusted
> clock.* §6 (DEC-TZ-01) is the decision that closes all four.

## 4.3 BUSINESS POLICY DECISION — the correct behaviour cannot be determined technically

| ID | The question | Why engineering cannot answer it |
|---|---|---|
| **TZ-10** | Should a DST transition change scheduled/paid minutes and therefore OT eligibility? | Nine real hours worked for zero OT is *arithmetically correct* and may be *legally wrong*, depending on jurisdiction. This is a compensation question, and in some jurisdictions a statutory one. **See §7.** |
| **TZ-11** | How should a local time that does not exist, or occurs twice, resolve? | `fold=0` is conventional and deterministic — but "conventional" is not "approved", and a shift silently starting an hour later than configured is a business outcome. **See §8.** |
| **TZ-08** | Is the ±2h punch load pad a business policy or a technical constant? | Whether a 06:45 arrival for a 09:00 shift *should count* is an attendance-policy question. **See §15.** |
| **F-14** | When should attendance be calculated, and in whose midnight? | An operational/product question whose answer is timezone-dependent. |
| **F-04 / F-06 / F-19** | Wire the dead configuration in, or withdraw it? | Wiring in **changes computed attendance or pay** for existing tenants. That is a client decision with a migration attached, not a bug fix. |

## 4.4 TEST GAP — the implementation appears correct but has insufficient automated proof

| ID | What is unproven-by-test |
|---|---|
| **TZ-04** | **All** DST behaviour (matrix group C — 12 scenarios). Zero tests touch a DST date. |
| — | 46 of 68 matrix scenarios are **code-proven but untested**: attendance-date ownership boundaries (A1–A11), cross-midnight punch ownership (B1–B11), server-TZ independence (G1–G4), timezone precedence *consequences* (D1, D4, D5, D6), timezone-change-then-recompute (E1, E4), period-lock boundaries (F1–F5). |
| — | **Only 4 of 68** timezone-relevant scenarios have an automated test today. |

## 4.5 INFRASTRUCTURE ISSUE — the application depends on deployment/runtime configuration

| ID | The dependency |
|---|---|
| **TZ-05** | Which tzdata copy wins is decided by the **image build**, not by the application. The newer, locked, installed copy is shadowed by the older system copy. |
| **TZ-02** *(second half)* | The interpretation of a naive timestamp is decided by the **container's `TZ`**, which the Dockerfile does not set. Pinning `TZ=UTC` is defence in depth and is worth doing **regardless of which option §6 selects**, because it costs nothing and makes dev and production agree. |
| **TZ-14** | Clock synchronisation is inherited from an unspecified host platform. No NTP/chrony config, no deployment manifest for the API service, no documented drift tolerance or failure behaviour. **NOT VERIFIED.** |

## 4.6 DOCUMENTATION ISSUE — the implementation is correct but documentation is wrong or incomplete

| ID | What needs to change |
|---|---|
| **TZ-13** | `app_timezone_default` should be renamed `celery_timezone`, or its Celery-only scope documented at the definition. |
| **F-20** | The punch-list-filters-UTC / day-list-filters-local split is correct per entity and already documented at `repository.py:1006`; it needs to reach **client-facing** reporting documentation so a month-boundary mismatch is expected rather than reported as a bug. |
| — | `ATTENDANCE_MASTER_RULE_MATRIX.md` **C3** must move from *"Presumed yes (stdlib)"* to *"CODE-PROVEN 2026-09-15; no automated test (TZ-04)"*. |
| — | The ±2h punch pad (TZ-08) must be documented as a stated constraint wherever attendance policy is described to the client, whatever §15 decides. |
| — | `fold=0` must be recorded as the stated policy for ambiguous/nonexistent times (§8). |

## 4.7 ACCEPTABLE CURRENT BEHAVIOUR — no change required

| Item | Why it is acceptable |
|---|---|
| **Period lock uses the UTC date of `punch_time`** (`service.py:2347`) | Documented as **WD-30**, with the reasoning stated in the code itself: the local attendance date is not knowable before shift resolution, which itself depends on the date. The stated backstop holds — `calculate()` refuses a locked day outright, so a boundary-straddling punch is at worst an inert orphan, never a silent rewrite. **It fails closed**, the safe direction. The only cost is a confusing rejection at a month boundary (matrix F2), and that is a documentation and support-script matter. **Confirm via DEC-TZ-10; expect "accept as documented".** |
| **No employee-level timezone** | Not "stored but unused" — **genuinely absent** from the schema. Architecture §6.4 specifies exactly three tiers and the code matches exactly. Adding a fourth tier would amend a LOCKED decision (WD-06) for a requirement nobody has confirmed. **Do not pre-build it** (DEC-TZ-09). |
| **Punches are instants and can never be ambiguous** | Only *wall-clock configuration* (shift/core/break times) can be. This correctly bounds §8's scope to configuration, not to attendance data. |
| **`end <= start` fallback exists at all** | Defensive depth behind `is_cross_midnight`. Its *UTC-vs-local* detail is TZ-12; its existence is correct. |

---

# 5. DECISION `DEC-TZ-13` — TIMEZONE CHANGE AFTER ATTENDANCE EXISTS

> **May `Company.timezone` or `Branch.timezone` be changed after attendance records already exist?**

**Finding:** TZ-01 (🔴 P0) · **Also:** `PAY-013`, `F-27` · **Status:** OPEN

## 5.1 Why this is a decision and not just a fix

Two different real-world events arrive through the same UPDATE statement, and they want **opposite**
treatments:

| Event | What actually happened | What the business wants |
|---|---|---|
| **Correction** | The branch was configured `Asia/Kolkata` on day one and should always have been `Asia/Dubai`. Every attendance day computed so far is wrong. | **Recompute everything.** The historical figures are the error. |
| **Relocation** | The office genuinely moved, or the legal entity's working-hours basis changed, effective 1 October. | **Preserve history.** Days before 1 October were correct in the old zone and must stay that way. |

The code today cannot tell them apart, and does the same thing for both: leaves history alone until
something triggers a recompute, then silently rewrites it. That is the worst of both — it is neither a
clean recompute nor a preserved history, and **which you get depends on whether anyone happens to
approve a regularization on that day.**

## 5.2 What is unambiguously broken regardless of which option is chosen

These two are **CODE BUGs** (§4.1) and are not part of the decision:

1. `_assert_timezone_change_allowed` is an empty stub whose own docstring defers it *"until
   Payroll/Attendance modules exist"*. **Attendance exists.** The precondition is met.
2. `update_branch` (`organisation/service.py:1106`) **never calls the hook at all**, so the middle link
   of the WD-06 precedence chain is unguarded even in stub form.

Whichever option is selected, the guard must be implemented **and called from both paths**.

## 5.3 The options

### Option A — Prohibit the change

Once any computed `attendance_day` exists for the company (or for the branch's employees),
`Company.timezone` / `Branch.timezone` become immutable.

| Dimension | Assessment |
|---|---|
| **Correctness** | **Highest.** The failure mode is eliminated rather than managed. Nothing can rewrite history because nothing can change the input. |
| **Auditability** | **Highest.** The value that computed every historical day is provably still the value on the row. No reconciliation question can arise. |
| **HR implications** | **Traps genuine errors.** A tenant who misconfigures a branch on day one and discovers it in week three has no supported path out — they would need a support/DBA intervention, or a new branch and an employee re-assignment. This is the option's real cost and it is not hypothetical: day-one misconfiguration is the *most likely* way this UPDATE ever gets issued. |
| **Payroll implications** | **Safest.** Approved attendance cannot change under a finalized or in-flight pay run. |
| **Complexity** | **Lowest.** One existence query in an existing hook, plus wiring the hook into `update_branch`. Realistically **one day**, and it is already scoped in the debt register's Week-1 sequencing as `PAY-013`. |
| **Reversibility** | High — a later move to Option B or C is purely additive. |

### Option B — Effective-date the change

`Branch.timezone` and `Company.timezone` become versioned rows with `effective_from`/`effective_to`.
Historical attendance resolves the timezone **as of the attendance date**; future attendance uses the
new value.

| Dimension | Assessment |
|---|---|
| **Correctness** | **Highest, and the only option that models reality.** A relocation genuinely *is* effective-dated. This is also the shape the codebase already uses successfully for `ShiftVersion.timezone` (PC-10) and for `EmployeeAssignment` (PC-11) — **the precedent, the pattern and the working example all exist in this repository.** |
| **Auditability** | **Highest.** Every historical day can be re-derived from first principles at any time, because the resolution is a function of the date. This restores timezone to the same footing as every other calculation input under WD-11. |
| **HR implications** | **Best.** Both real-world events are expressible: a correction is an edit to the *current* version's `effective_from` (or a backdated version), a relocation is a new version. HR states the intent explicitly rather than having it inferred. |
| **Payroll implications** | **Best.** A recompute after a relocation reproduces historical figures exactly and applies the new zone only from its effective date — the same guarantee `ShiftVersion` already gives. |
| **Complexity** | **Highest.** Two new versioned tables (or effective-dated columns) + migration + backfill of existing rows + `resolve_timezone` becomes date-aware + `_build_calculation_input` gains two as-of resolutions + the branch and company settings UI gain an effective-date control + RLS policies + tests. Realistically **1.5–2 engineering weeks**, and it amends the shape of WD-06. |
| **Reversibility** | Low — a schema change with a data migration. |

### Option C — Allow the change with explicit acknowledged historical recomputation

The administrator may change the timezone, but the API refuses unless an explicit acknowledgement flag
is supplied; the system then recomputes every affected open day and records an audit entry naming the
old zone, the new zone, the actor, and the count of days rewritten.

| Dimension | Assessment |
|---|---|
| **Correctness** | **Adequate for a correction, wrong for a relocation.** It has exactly one semantic — "history was wrong, redo it" — and silently applies that semantic to the relocation case too. |
| **Auditability** | **Good, if the audit entry is complete.** Worse than A or B in one specific way: the old figures are **gone**. `attendance_day` has no history table, so a recompute overwrites `late_minutes`/`worked_minutes`/`paid_day_fraction` in place. An auditor asking *"what did this day say when it was approved?"* has only the audit log's before/after JSON to work from — and **only if the recompute path writes one**, which the current `calculate()` path does (`AttendanceDayService` records an audit entry) but which has never been exercised at this scale. |
| **HR implications** | Acceptable for correction. **Dangerous for relocation** — an HR manager who moves an office and clicks through an acknowledgement dialog has just rewritten six months of approved attendance, and the dialog's wording is the only thing that told them so. |
| **Payroll implications** | **Requires a hard precondition: the change must be refused outright if any affected period is `CLOSED`, or if any pay run has consumed the period.** Without that, this option can silently change the inputs behind an issued payslip. Locked days are already protected (`calculate()` refuses a locked day), so the mechanism exists — but it must be an explicit, tested precondition, not an accident of the lock check. |
| **Complexity** | **Moderate.** Guard + acknowledgement flag in the API and UI + a bulk recompute job (which needs `PAY-001`'s batch machinery, currently unbuilt) + audit entry + a preview of how many days would change. Realistically **3–5 days**, *plus* its dependency on batch recompute. |
| **Reversibility** | **Poor in the data.** The recompute is destructive to the prior figures. |

## 5.4 Option comparison

| | A — Prohibit | B — Effective-date | C — Allow + recompute |
|---|---|---|---|
| Fixes the P0 | ✔ | ✔ | ✔ |
| Handles day-one **correction** | ✘ (no path) | ✔ | ✔ |
| Handles genuine **relocation** | ✘ (no path) | ✔ | ✘ (rewrites history) |
| Historical figures preserved | ✔ | ✔ | ✘ **destructive** |
| Consistent with WD-11 reproducibility | ✔ | ✔ **fully** | ✘ |
| Follows an existing repo pattern | — | ✔ `ShiftVersion` | — |
| Amends a LOCKED decision | No | **Yes — WD-06 shape** | No |
| Effort | ~1 day | ~1.5–2 weeks | ~3–5 days + depends on `PAY-001` |
| Blocks the P0 today | **No** | Yes | Partly |

## 5.5 Recommendation

> ## AI RECOMMENDATION — CLIENT MUST APPROVE
>
> **Adopt Option A now. Adopt Option B as the target state, on the trigger below.**
>
> **Now (P0, ~1 day):** implement `_assert_timezone_change_allowed` to **refuse** a
> `Company.timezone` / `Branch.timezone` change whenever any computed `attendance_day` exists for the
> affected scope, and **call it from `update_branch` as well as `update_company`**. This closes the P0
> at the lowest cost, is fully reversible, needs no schema change, and does not pre-commit the client to
> an architecture.
>
> **Escape hatch for the correction case (ship with A):** permit the change while the company is still
> in `TRIAL` status, or when **zero** computed attendance days exist. The company profile already
> distinguishes `TRIAL` for exactly this class of "still being set up" edit — `update_company_profile`
> uses it today to gate the currency change (`organisation/service.py:654-656`). **Reuse that precedent
> rather than inventing a new one.** Day-one misconfiguration — the most likely reason this UPDATE is
> ever issued — is then handled without weakening the guard for live tenants.
>
> **Trigger for Option B:** the first tenant who (a) operates in more than one timezone, **or** (b)
> genuinely relocates a branch. At that moment Option A has no answer and Option C gives the wrong one,
> and the `ShiftVersion` pattern is already sitting in the codebase waiting to be copied.
>
> **Do not adopt Option C as the primary posture.** It is destructive to historical figures, it is
> semantically wrong for the relocation case, and it depends on batch recompute (`PAY-001`) which does
> not exist yet. Its *acknowledgement-and-audit* mechanism is worth keeping as the UI treatment of
> Option A's TRIAL/zero-days escape hatch.

**Precondition on any option chosen:** the change must be refused outright if any affected
`attendance_period` is `CLOSED`. That is not negotiable under any of the three and is the one rule the
client does not need to decide.

---

# 6. DECISION `DEC-TZ-01` — THE AUTHORITATIVE PUNCH CLOCK

> **Who is authoritative for the time of an attendance punch?**

**Findings:** F-01, F-02, F-03, F-11 (all 🔴/🟡) · **Status:** OPEN · **This is the blocker.** It determines the shape of DEC-TZ-02, DEC-TZ-03 and DEC-TZ-04.

## 6.1 The specification gap, stated precisely

```text
IMPLEMENTATION:
  The client's clock is the authoritative source of attendance time.
  `service.py:2353` — "punch_time": body.punch_time or now
  The server computes datetime.now(UTC) at :2337 and uses it only for created_at.
  The two are NEVER compared. The server-time fallback is dead in every shipped flow,
  because punch-entry-dialog.tsx:94 always sends punch_time.

DOCUMENTED POLICY:
  None. ADR-0010 / DEC-010 specifies UTC storage and IANA business-day boundaries —
  both correctly implemented (PC-02, PC-03) — and says nothing about which clock is
  authoritative. Greps for "server time", "client time", "device clock", "trusted",
  "clock skew" and "spoof" across WORKFORCE_ATTENDANCE_ARCHITECTURE.md,
  WORKFORCE_ATTENDANCE_DECISION_LOG.md and all of docs/business-rules/attendance/
  return nothing on this question.

CONFLICT:
  Cannot be assessed — there is no documented policy to conflict with.
  This is a genuine specification gap, not an implementation deviation.
```

Worth stating plainly: this codebase's internal decision log is unusually disciplined — WD-06, WD-11,
WD-26 and WD-28…WD-32 each record a deliberate trade-off with its reasoning, and several record
*rejected* alternatives. The authoritative-clock question is conspicuous by its absence from that log.
It reads as a question that was **never asked**, not one that was answered and set aside.

## 6.2 What the current default actually grants

```text
Device time:   2026-09-15 08:45 IST   (employee arrives late; or types anything)
Server time:   2026-09-15 09:47 IST   (datetime.now(UTC), service.py:2337)
Difference:    any value, unbounded, either direction
Behaviour:     punch_time = 2026-09-15 03:15:00Z stored and used verbatim.
               created_at = 2026-09-15 04:17:xxZ records the true receipt time.
               The two are NEVER compared. No warning, no flag, no rejection.
               late_minutes is computed from the fabricated value.
```

Any holder of the baseline `ATTENDANCE.PUNCH` permission controls their own `late_minutes`,
`worked_minutes`, `ot_minutes_detected`, `paid_day_fraction` and `lop_fraction` — **the documented
payroll inputs**. No clock manipulation is required: the shipped dialog exposes the value as an
editable `<input type="datetime-local">`, so typing is the attack.

## 6.3 The two acts the one endpoint serves

This matters more than the option labels, because the right answer differs between them:

| Act | Who | What a supplied time means | Right answer |
|---|---|---|---|
| **Self-service punch** | Employee marking their own arrival, now | Nothing legitimate — the event is *happening*, so the server knows when | **Server stamp.** A supplied time can only be a claim about a moment the server is already witnessing. |
| **On-behalf / correction entry** | Admin entering last Tuesday's missed punch | **The whole point** — the admin is asserting a historical fact | **Supplied time, permissioned and bounded.** |
| **Device / biometric ingestion** | A terminal reporting a batch of reads | The device's own capture time, possibly minutes or hours old | **Supplied time, with device identity and a bounded upload lag.** |
| **Offline mobile capture** | Employee's phone, no connectivity at capture | The device's capture time, submitted later | **Supplied time, but see §11 — this is a separate product decision.** |

The mechanism to distinguish the first two **already exists**: `default_source` is `WEB` for self and
`ADMIN` for on-behalf at `router.py:783`, and `ATTENDANCE.PUNCH_ON_BEHALF` is already a separate
permission. The current code simply lets the body override it (F-11).

## 6.4 The options

### Option A — Server/database authoritative

`punch_time` is ignored on the self-service path; the server stamps `datetime.now(UTC)`. Corrections go
exclusively through regularization, which has an approval chain.

| Dimension | Assessment |
|---|---|
| **Security** | **Strongest.** Removes the attack surface rather than bounding it. Phone clock, browser clock, timezone setting and "automatic time OFF" all become irrelevant — none of them is consulted. |
| **HR** | **Cleanest audit story.** "The system recorded when it received your punch" is defensible in a dispute without further evidence. |
| **Payroll disputes** | **Strongest position.** The figure derives from a clock the employee cannot touch. |
| **Network delay** | Becomes a real, if small, source of error: the stamp is receipt time, not tap time. Typically sub-second; seconds under poor connectivity. Immaterial against a grace period measured in minutes. |
| **Offline mobile** | **Incompatible.** A punch captured offline at 09:00 and uploaded at 13:00 would be stamped 13:00. If offline attendance is ever required, Option A alone cannot serve it — see §11. |
| **Device/biometric ingestion** | **Also incompatible** for batch uploads, for the same reason. A separate ingestion contract is required. |
| **UX change** | The time field on the self-punch dialog becomes read-only or disappears. |
| **Complexity** | **Lowest.** Ignore `body.punch_time` when the caller is punching for themselves. A few lines, plus the UI change. |

### Option B — Client timestamp accepted within a small bounded skew

`punch_time` is accepted but rejected (or flagged) when `|punch_time − server_now|` exceeds a tolerance.
Both values are stored.

| Dimension | Assessment |
|---|---|
| **Security** | **Good, and bounded rather than eliminated.** At ±120s an employee can shave two minutes off lateness — usually immaterial against a grace period, and *always* material if the tolerance is set carelessly (a ±15min tolerance is a 15-minute lateness window). **The tolerance *is* the control**, which is exactly why DEC-TZ-02 must be answered with a number, not a shrug. |
| **HR** | Defensible, *provided divergence is recorded*. "Accepted within tolerance, recorded at X, received at Y" is a complete audit sentence. "Accepted" alone is not. |
| **Payroll disputes** | Adequate. The stored pair `(punch_time, created_at)` lets an investigator reconstruct what happened — but **only if `raw_payload` or an equivalent captures the submission context (F-18), which today it does not.** |
| **Network delay** | Handled naturally — it is the reason a tolerance exists. |
| **Offline mobile** | **Still incompatible** under a small tolerance. A 4-hour upload lag exceeds any sane skew window. Offline needs its own contract, not a wider tolerance. |
| **Device/biometric** | Workable with a **larger, separately-configured** tolerance on the permissioned ingestion path. |
| **Clock drift** | **Introduces a real dependency on server clock accuracy** (TZ-14). If the server clock drifts, legitimate punches are rejected across the board. NTP moves from "presumably fine" to "load-bearing". |
| **Complexity** | **Moderate.** A validator plus the tolerance as configuration, plus a rejection message users will actually encounter, plus support tooling for the "my phone clock is wrong" ticket. |

### Option C — Client timestamp accepted without validation *(current behaviour)*

| Dimension | Assessment |
|---|---|
| **Security** | **None.** Documented risk `R-1`, likelihood **certain** — it is a supported UI affordance, not an exploit. |
| **HR** | Indefensible in a dispute. An employee contesting a lateness deduction can point out that the number was theirs to type — and be right. |
| **Payroll disputes** | **Reverses the burden of proof onto the employer**, in a system whose whole purpose is to establish the facts. |
| **Complexity** | Zero — it already ships. |
| **When it could be acceptable** | Only as a **consciously accepted** business risk with compensating **detective** controls: an alert when `\|punch_time − created_at\|` exceeds a threshold, a report of divergent punches, and a documented statement that attendance times are self-declared. The comparison data (`created_at`) already exists, so detection is cheap. **This is a legitimate choice for a trust-based, salaried, non-deduction population — and an unacceptable one wherever attendance drives pay.** |

## 6.5 What each option requires of the rest of the system

| | A — Server | B — Bounded skew | C — Unvalidated |
|---|---|---|---|
| Needs reliable server clock / NTP (**TZ-14**) | ✔ **yes** | ✔ **yes** | No |
| Needs `raw_payload` / submission evidence (**F-18**) | Helpful | ✔ **yes** | ✔ **yes** (for detection) |
| Needs server-assigned `source` (**F-11**) | ✔ **yes** | ✔ **yes** | ✔ **yes** |
| Needs a future-time bound (**F-03**) | Not applicable | ✔ **yes** (= the tolerance) | ✔ **yes** |
| Needs naive-timestamp rejection (**TZ-02/DEC-TZ-04**) | Not applicable to self-punch; **yes** for every other path | ✔ **yes** | ✔ **yes** |
| Needs a separate offline contract (**§11**) | ✔ **yes** | ✔ **yes** | No (it accepts anything) |
| Changes the self-punch UX | ✔ **yes** | Minor | No |

## 6.6 Recommendation

> ## AI RECOMMENDATION — CLIENT MUST APPROVE
>
> **Option A for self-service punches; Option B semantics for every other path — never Option C.**
>
> The safest practical architecture is **per-path**, not global, because the endpoint serves genuinely
> different acts (§6.3):
>
> | Path | Clock | Bound | Permission |
> |---|---|---|---|
> | **Self-service web/mobile punch** (`source=WEB`/`MOBILE`) | **Server.** `body.punch_time` is ignored — accepted-and-discarded, or rejected as `extra="forbid"` | n/a | `ATTENDANCE.PUNCH` |
> | **On-behalf / admin entry** (`source=ADMIN`) | **Client-supplied**, required | Not in the future; not in a `CLOSED` period; within the backdating window | `ATTENDANCE.PUNCH_ON_BEHALF` |
> | **Device / biometric ingestion** (`source=DEVICE`) | **Device-supplied** | Bounded *upload lag* measured against `created_at`, configured per integration | A dedicated integration permission |
> | **Regularization apply** (`source=REGULARIZATION`) | **Server-assigned by the apply path only** | Already approval-gated | Server-internal (`service.py:4116`) |
> | **CSV / bulk import** (`source=IMPORT`) | **File-supplied** | Not in the future; within the import window | Import permission |
>
> **Three things are true regardless of which option is selected**, and should be treated as
> unconditional:
>
> 1. **`source` must be server-assigned from the authenticated context** (F-11). Without it, every
>    per-path rule above is advisory — a caller simply asserts a different `source` and gets the
>    permissive branch. **This is the linchpin: it must land in the same change as the clock decision,
>    not after it.**
> 2. **Naive timestamps must be rejected** (TZ-02 / DEC-TZ-04), and `TZ=UTC` pinned in the Dockerfile
>    and CI. These are independent of the clock decision and are worth doing either way.
> 3. **Record both instants, always.** `punch_time` (event) and `created_at` (receipt) both persist on
>    every punch, and their divergence is reportable. That single pair is what makes any future dispute
>    answerable, and it already exists on the row today.
>
> **If the client chooses Option C** (accept self-declared times), it should be recorded as an explicit,
> signed business-risk acceptance naming `R-1` and `R-2`, paired with the detective controls in §6.4 —
> **not left as the current silent default.** The difference between "we decided to trust employees"
> and "nobody checked" is invisible in the code and decisive in a dispute.

---

# 7. DECISION `DEC-TZ-14` — DST AND OVERTIME

> **Should a DST transition change scheduled/paid minutes, and therefore OT eligibility?**

**Finding:** TZ-10 · **Status:** OPEN · **Not applicable to India** (no DST, stable offset since 1945). **Blocking before any DST-observing tenant.**

## 7.1 The two policies

| | **Wall-clock policy** | **Real elapsed-time policy** *(current behaviour)* |
|---|---|---|
| Principle | A `22:00–06:00` shift is **8 hours, always**, because that is what the schedule says. | A `22:00–06:00` shift is **however long it actually takes**, because that is what the employee experiences. |
| `scheduled_minutes` | Fixed at 480 every night of the year. | 420 / 480 / 540 depending on the date. |
| Mental model | *"Your shift is eight hours."* | *"Your shift is 22:00 to 06:00."* |
| Implementation | `scheduled_minutes` = naive wall-clock subtraction, decoupled from the UTC span. | `scheduled_end − scheduled_start` in UTC. |

**The current implementation is real elapsed time, and its arithmetic is correct** (PC-06, CODE-PROVEN
across four transitions). This decision is **not** about fixing a bug. It is about whether a correct
arithmetic consequence is the intended compensation outcome.

## 7.2 Worked examples — `22:00 → 06:00`, `Europe/London`

All figures CODE-PROVEN by executing the shipped engine.

### Normal night — 2026-09-15, no transition

| | Wall-clock policy | Real elapsed *(current)* |
|---|---|---|
| Scheduled | 480 | **480** |
| Employee works 22:00→06:00 local (8 real hours) | worked 480 | **worked 480** |
| Late / Early | 0 / 0 | **0 / 0** |
| OT (`worked − scheduled`) | 0 | **0** |
| Status | `PRESENT` | **`PRESENT`** |

**The two policies are identical on ~363 nights a year.** The entire decision concerns two nights.

### Fall-back night — 2026-10-24→25 (clocks go back; the night is 9 real hours)

| | Wall-clock policy | Real elapsed *(current)* |
|---|---|---|
| Scheduled | 480 | **540** |
| **Employee works the full wall-clock shift** (22:00→06:00 local = **9 real hours**) | worked 540, scheduled 480 → **60 min OT** | worked **540**, scheduled **540** → **0 OT** |
| **Employee works 8 real hours** (leaves 05:00 local) | worked 480 → on time, 0 OT | worked **480**, early departure **60 min** |
| Night OT | Classified `NIGHT` (cross-midnight flag) in both | Same |
| Payroll effect | One extra paid hour, at the night-OT premium | **No extra pay for a ninth real hour** |

### Spring-forward night — 2026-03-28→29 (clocks go forward; the night is 7 real hours)

| | Wall-clock policy | Real elapsed *(current)* |
|---|---|---|
| Scheduled | 480 | **420** |
| **Employee works the full wall-clock shift** (22:00→06:00 local = **7 real hours**) | worked 420 vs scheduled 480 → **60 min short**; depending on hour bands, possibly `HALF_DAY` or an early-departure flag | worked **420**, scheduled **420** → on time, **full day's credit for 7 real hours** |
| Payroll effect | Employee loses an hour, or is flagged | **Employee gains an hour** |

## 7.3 Consequences, dimension by dimension

| Dimension | Under real elapsed *(current)* | Under wall-clock |
|---|---|---|
| **Worked minutes** | True elapsed time. Unambiguous, matches a stopwatch. | Same — worked minutes are measured from punches either way. **This dimension does not change.** |
| **Scheduled minutes** | Varies ±60 on two nights a year. | Constant. |
| **Late** | Unaffected — computed as `first_in − scheduled_start`, both UTC instants, and `scheduled_start` is a wall time that exists in both policies. | Unaffected. |
| **Early departure** | An employee leaving at their usual *real* hour on a fall-back night is flagged **60 min early**. | Not flagged. |
| **OT** | `worked − scheduled`. Suppressed on fall-back, trivially earned on spring-forward (an employee staying to their usual *real* hour earns 60 min OT). | Earned on fall-back, lost on spring-forward. |
| **Night OT** | Unaffected by this decision — `is_night = shift.is_cross_midnight` (and note F-06: the configured window is never read at all). | Same. |
| **Payroll** | Employer pays for 8 scheduled hours on a 9-hour night; employee is paid a full day for a 7-hour night. **Over a year the two transitions cancel** — for an employee who works both. They do not cancel for someone hired in June, who leaves in September, or who works only one of the two nights. | The reverse asymmetry, in the employee's favour on fall-back. |

## 7.4 What makes this genuinely undecidable from an engineering seat

1. **Both are internally consistent.** The current behaviour is not sloppy; it is the faithful
   consequence of defining a shift in wall-clock terms and measuring in real time.
2. **In some jurisdictions this is a legal question, not a policy one.** Working-time and overtime
   statutes in DST-observing countries differ on whether the transition hour is compensable. Engineering
   cannot choose a jurisdiction's answer.
3. **The failure mode is a grievance, not a bug report.** An employee who works nine real hours on a
   Sunday night in October and sees zero overtime will raise it with HR, not with support — and HR will
   need an answer that was decided in advance.
4. **The averaging argument is only true in the aggregate.** "It cancels out over a year" is true for a
   full-year employee and false for everyone else — and it is never a satisfying answer to the person
   who worked the ninth hour.

## 7.5 Recommendation

> ## AI RECOMMENDATION — CLIENT MUST APPROVE
>
> **Keep the current real-elapsed behaviour. Document it explicitly before onboarding any DST-observing
> tenant. Do not change code for this decision until a tenant or a jurisdiction requires it.**
>
> Reasons, in order of weight:
>
> 1. **Wall-clock shift definition + real-elapsed measurement is the conventional interpretation**, and
>    it is the one the schedule literally says: the shift is *22:00 to 06:00*, not *eight hours*.
> 2. **It is already correct and proven.** Changing it means decoupling `scheduled_minutes` from the
>    UTC span — introducing a second, naive notion of duration into an engine whose correctness rests on
>    there being exactly one. That is a real regression risk taken for two nights a year.
> 3. **India is unaffected**, so there is no cost to deferring the *code* while recording the *policy*.
> 4. **The early-departure flag is the sharper edge, not the OT.** An employee who works their normal
>    real hours on a fall-back night being flagged 60 minutes early is more likely to surface, and more
>    corrosive, than the missing overtime. Whatever the client decides about OT, **the fall-back
>    early-departure flag should be suppressed or annotated** — it reports a fact ("you left an hour
>    before your scheduled end") that is technically true and practically misleading.
>
> **If the client wants the wall-clock policy**, implement it as a **per-tenant policy flag**
> (`dst_scheduled_minutes_basis: REAL_ELAPSED | WALL_CLOCK`, default `REAL_ELAPSED`) rather than a global
> behaviour change. Multi-jurisdiction tenants will eventually need both, and retrofitting a flag after
> the fact means a recompute of every DST night already computed.
>
> **Whatever is decided, record it in `ATTENDANCE_MASTER_RULE_MATRIX.md` alongside C3**, so that the
> next person to read "540 minutes" in a test fixture knows it was chosen.

---

# 8. DECISION `DEC-TZ-11` — AMBIGUOUS AND NONEXISTENT LOCAL TIMES

**Finding:** TZ-11 / F-17 · **Status:** OPEN · **Scope: shift and break *configuration* only.**

## 8.1 Scope — what can and cannot be ambiguous

> **A punch can never be ambiguous.** A punch is an *instant*, stored as `TIMESTAMPTZ`, and an instant
> has exactly one UTC value. **Only wall-clock configuration can be ambiguous**: `shift_version.start_time`
> / `end_time` / `window_start` / `window_end` / `core_start` / `core_end`, and `shift_break.start_time`
> / `end_time` / `window_*` — all stored as `TIME` and given meaning by a sibling `timezone` column.

This bounds the problem to a handful of `TIME` columns, all of which are set by an administrator at
shift-publish time, in a UI, where a warning can be shown.

## 8.2 Current behaviour — CODE-PROVEN

`ZoneInfo`'s default `fold=0`, applied silently at `_local_to_utc` (`calculation.py:306`):

| Case | Zone | Configured local time | Resolves to | Round-trips as | What the administrator gets |
|---|---|---|---|---|---|
| **Nonexistent** (spring gap) | `America/New_York` | 2026-03-08 **02:30** | `07:30Z` | **03:30 EDT** | A shift that **starts an hour later than configured** |
| **Nonexistent** (UK gap) | `Europe/London` | 2026-03-29 **01:30** | `01:30Z` | **02:30 BST** | Same |
| **Ambiguous** (occurs twice) | `America/New_York` | 2026-11-01 **01:30** | `05:30Z` | **01:30 EDT** — first occurrence | The **earlier** of the two instants |
| **Ambiguous** (UK repeat) | `Europe/London` | 2026-10-25 **01:30** | `00:30Z` | **01:30 BST** — first occurrence | Same |

No warning is raised at publish time or at calculation time.

### The asymmetry worth naming

`fold=0` is not neutral — it means different things depending on which end of the shift it lands on:

| Ambiguous time is the… | `fold=0` picks | Effect on the span |
|---|---|---|
| **start** time | the **earlier** instant | span is **one hour longer** |
| **end** time | the **earlier** instant | span is **one hour shorter** |

So a shift whose *start* falls in the repeated hour is scheduled an hour longer, and one whose *end*
falls there an hour shorter. Both are defensible; neither was chosen. **This asymmetry is the strongest
argument for warning at publish time rather than picking a cleverer default** — no single `fold` value
is right for both ends.

## 8.3 Policy proposal

> **Proposal — not a decision. Requires approval.**
>
> **P1. Resolution behaviour: keep `fold=0`. Do not change it.**
> It is deterministic, conventional, matches CPython's documented default, and matches what every other
> `zoneinfo`-based system in the ecosystem does. Changing it would make this system's answer differ from
> every neighbouring tool's for no gain. **Record it as the stated policy**, in
> `ATTENDANCE_MASTER_RULE_MATRIX.md` and in the client-facing shift documentation:
>
> > *A local time that does not exist because clocks moved forward resolves to the same instant as the
> > equivalent time after the change — a shift configured for 02:30 on a spring-forward date begins at
> > 03:30 local. A local time that occurs twice because clocks moved back resolves to the **first**
> > occurrence.*
>
> **P2. Warn — do not reject — at shift-publish time.**
> When a `ShiftVersion` or `ShiftBreak` is published with a timezone that observes DST, check each
> configured `TIME` against the transition windows for the next N years (N = 2 is sufficient; `zoneinfo`
> exposes the transitions). If any configured time falls in a gap or a repeated hour, return a
> **warning** naming the date, the configured time, and the instant it will actually resolve to.
>
> **P3. Reject only one narrow case — and confirm this with the client.**
> A *nonexistent* start time is arguably a configuration error rather than a preference: the
> administrator asked for a time that will not occur. **Recommendation: still warn rather than reject**,
> because the shift is valid on all 364 other days and rejecting it would prevent a legitimate schedule
> over a once-a-year edge. An *ambiguous* time must never be rejected — it is a perfectly valid time
> that simply happens twice.
>
> **P4. Do not add per-shift `fold` configuration.** It would expose a concept no HR administrator
> should need to learn, to control an outcome that differs by one hour on one day a year. If a tenant
> genuinely needs the second occurrence, a roster override for that single date is the right tool and
> already exists (`shift_roster.roster_date`).

**Impact if approved:** documentation + one publish-time validator. No change to the calculation engine,
no schema change, no recompute.

**Applicability:** zero tenants today — every default is `Asia/Kolkata`, which has no DST. **Rises to P1
before any DST-zone client is onboarded**, alongside DEC-TZ-14.

---

# 9. DECISION `DEC-TZ-08` — UI TIMEZONE

**Finding:** TZ-03 / F-08 / `FE-1` · **Status:** OPEN · **This is a conflict with a LOCKED decision.**

## 9.1 Existing decision — what DEC-010 requires

**`DEC-010` · Status: LOCKED · Source: ADR-0010**

> All timestamps stored in UTC. **`company.timezone` is the single source of truth for rendering** and
> for computing business-day boundaries (attendance-day resolution, payroll-period cutoffs) — never UTC
> midnight, never server-local time.
>
> *Scope: Attendance and Payroll modules specifically; any timestamp anywhere in the system generally.*

ADR-0010's own Consequences section reinforces it: *"Rendering any timestamp to a human in that
company"* is named as the first of the two things `company.timezone` is the single source of truth for.

## 9.2 Actual implementation — what the UI does

```ts
// apps/web/src/lib/attendance/format.ts:14-25
export function formatClockTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}
```

`undefined` as the first argument to `toLocaleTimeString` / `toLocaleString` means **both the locale and
the timezone come from the viewer's browser**. Every attendance time in the product renders in the
viewer's device zone. **No timezone label accompanies any rendered time.**

The data needed to do it correctly is **already on the wire**: the API returns
`attendance_day.timezone` (`schemas.py:1391`), and `attendance/[id]/page.tsx:110` already prints it as
a page subtitle. **No formatter consumes it.**

## 9.3 The conflict, precisely

| | DEC-010 requires | The code does |
|---|---|---|
| **Storage** | UTC | ✔ UTC — `TIMESTAMPTZ` throughout (PC-02) |
| **Business-day boundaries** | Company timezone, never UTC midnight, never server-local | ✔ — and **extended** by WD-06 to `Shift > Branch > Company`, which is an *explicit, documented* supersession, not drift |
| **Rendering** | **Company timezone** | ✘ **Viewer's browser timezone** |

So: two of DEC-010's three clauses are implemented, one is not. And there is a **second, subtler
divergence** that the client should be told about, because it affects how the conflict is best resolved:

> **DEC-010 says `company.timezone`. WD-06 already superseded that for computation** — the resolved
> zone is `ShiftVersion > Branch > Company`. A day computed in `Asia/Dubai` (branch) under a company
> whose timezone is `Asia/Kolkata` is **correctly** computed in Dubai time. Rendering it in *company*
> time — literal compliance with DEC-010 — would show times in a zone the figures were **not** computed
> in. **Literal compliance with DEC-010 would be a second bug.**

This is why the fix and the decision are entangled: the locked decision names a source of truth that
another locked decision has already replaced.

## 9.4 Impact today and at rollout

| Situation | Effect |
|---|---|
| **Today — all users in one zone** | Nothing is visibly wrong. The browser zone and the attendance zone coincide. **This is why it has not been reported.** |
| **An HR user in Dubai reviews a Kerala employee** | Every time is shifted **1h30m** from the zone its own `late_minutes` was computed in. A `09:05` arrival displays as `07:35` next to a `late_minutes: 5`. No label explains it. |
| **A remote reviewer, or a manager travelling** | The same record renders differently in the same account depending on where the laptop is. |
| **A screenshot in a dispute** | Not reproducible — it depends on the device that took it. |

## 9.5 Options

### Option A — Company / attendance timezone

Render every attendance time in the **resolved attendance timezone** (`attendance_day.timezone`), with
an explicit label: `09:05 IST`.

- **For:** the displayed time and the figure beside it are in the same zone — the only arrangement in
  which `late_minutes: 5` next to `09:05` is self-consistent. Reproducible across devices. Matches
  DEC-010's intent. Data already on the wire.
- **Against:** a viewer in another zone must translate to their own wall clock to answer *"is this
  person in the office right now?"*. Requires a decision about surfaces with **no** attendance day —
  audit timestamps, `created_at`, notification times — which have no resolved zone of their own.

### Option B — Viewer / device timezone *(current behaviour)*

- **For:** it already ships; matches the viewer's intuition for "now"; zero work.
- **Against:** violates a LOCKED decision; times and their computed figures disagree with no
  indication; not reproducible; **silently wrong exactly when a second location goes live**, which is
  the worst possible timing for a display bug.

### Option C — Show both

`09:05 IST (10:35 your time)`, or the attendance zone primary with a hover/secondary line.

- **For:** unambiguous for everyone; answers both questions at once; strongest for a cross-zone reviewer.
- **Against:** visual noise on dense tables (an attendance grid can carry 4 timestamps per row × 31
  rows); needs a design pass; doubles the width of every time cell.

### Option D — Per-user preference, defaulting to the attendance timezone

- **For:** accommodates both populations.
- **Against:** a preference is a *setting nobody sets*; it makes screenshots and support conversations
  ambiguous ("what does *your* screen say?"); and it defers a product decision into a toggle.

## 9.6 Recommendation

> ## AI RECOMMENDATION — CLIENT / PRODUCT MUST APPROVE
>
> **Option A, with two amendments to DEC-010 and a targeted use of Option C.**
>
> 1. **Render in `attendance_day.timezone` with an always-visible label** (`09:05 IST`). Never render a
>    time computed in one zone without naming that zone.
> 2. **Amend DEC-010's rendering clause** to read *"the resolved attendance timezone (WD-06:
>    `ShiftVersion > Branch > Company`) is the source of truth for rendering attendance timestamps"*,
>    bringing rendering into line with the computation rule WD-06 already established. Leave it as
>    `company.timezone` for **non-attendance** timestamps, which have no resolved zone —
>    audit-log entries, `created_at`, notification times. **This amendment is the substance of the
>    client's decision**; it is a change to a LOCKED decision and cannot be made by engineering.
> 3. **Apply Option C on the one surface that needs it**: the day-detail page, where a reviewer is
>    actively adjudicating a single record and a `(10:35 your time)` secondary is worth the space. Keep
>    the dense list and grid views single-zone.
>
> **Priority: P1, rising to P0 on the day a second timezone goes live.** It is worth fixing before then
> anyway, because the fix is cheap — the data is already on the wire and the change is confined to two
> formatter functions and their call sites — and because a display bug discovered *during* a
> multi-location rollout will be read by the client as a correctness bug in the attendance engine,
> which it is not.

---

# 10. PUNCH TIMESTAMP CONTRACT (REQUIRED FUTURE STATE)

**Specification only. Not implemented. Its enforcement posture depends on DEC-TZ-01 (§6).**

## 10.1 The three times — currently two, conflated

The single most useful clarification in this whole document is that a punch has **three** distinct
times, and the system currently models **two**, one of which is doing double duty.

| Concept | Definition | Who asserts it | Today | Required |
|---|---|---|---|---|
| **EVENT TIME** | The instant the human physically punched. *The only time attendance may be computed from.* | Client (today), or server (Option A) | `punch.punch_time` | `punch.punch_time` — unchanged |
| **REQUEST TIME** | The instant the server received the HTTP request. *The trust anchor for every skew, future and upload-lag check.* | Server, always | `punch.created_at` — **conflated with record-created time** | A **distinct, immutable, server-assigned** value |
| **RECORD CREATED TIME** | The instant the row was durably written. *Audit and forensics only; never a business input.* | Database | `punch.created_at` (server-set, overriding `DEFAULT now()`) | The DB's own `now()`, not overridden |

```text
  09:00:00  Employee taps                      ← not captured today; only knowable on a device-side path
  09:00:00  EVENT TIME       = punch_time      ← what attendance is computed from
  09:00:04  REQUEST TIME     = server receipt  ← the trust anchor
  09:00:04  RECORD CREATED   = DB write        ← audit only
```

> **Why the conflation matters.** Every check in §10.3 compares EVENT TIME against **REQUEST TIME**.
> Today `created_at` is set by the application (`service.py:2359` — `"created_at": now`) and overrides
> the column's `DEFAULT now()`, so it is *in practice* the request time — but nothing says so, nothing
> prevents a future refactor from letting the DB default win, and a batch-import path that sets
> `created_at` from file data would silently destroy the anchor. **Separating the two is cheap now and
> expensive later.**
>
> **The stale-form case is why event time and request time must both exist even under Option A.** The
> punch dialog seeds `punchTime` when it opens (`punch-entry-dialog.tsx:73`) and **never refreshes it**,
> so a dialog left open for twenty minutes submits a twenty-minute-old timestamp — with no malice at
> all. Under Option C this is silently recorded as fact. Under Option B it is caught by the tolerance.
> Under Option A it is discarded. **All three outcomes are only distinguishable because two times exist.**

## 10.2 Wire format

| Rule | Requirement | Enforcement | Rationale |
|---|---|---|---|
| **Timezone-aware** | `punch_time` **must** be timezone-aware | `AwareDatetime` on `PunchCreate.punch_time` | Closes TZ-02 / F-07 |
| **ISO-8601** | `YYYY-MM-DDTHH:MM:SS[.ffffff]±HH:MM` or `…Z` | Pydantic | Already the de-facto format |
| **Explicit offset — required** | `Z` or `±HH:MM`. **No default, no inference.** | Schema-level reject → **422** | An inferred offset on a payroll input is indefensible |
| **Naive timestamp — rejected** | `"2026-09-15T09:00:00"` → **422**, with a message naming the missing offset | Schema | The same request must not store different instants in dev and production |
| **UTC normalization** | Normalized to UTC on receipt; stored `TIMESTAMPTZ` | Existing (PC-02) | Already correct — **do not change** |
| **Named zones — rejected** | `"2026-09-15T09:00:00 Asia/Kolkata"` is not accepted | Schema | Offset is unambiguous; a zone name at ingestion is not (§8) |
| **Response format** | Always `…Z` | `_format_timestamp` (`schemas.py:88`) | Already correct |

## 10.3 Validation bounds

Each bound's **value** is a client decision; the **existence** of the bound is not.

| Bound | Rule | Response | Decision | Recommended starting value |
|---|---|---|---|---|
| **Future tolerance** | `punch_time > REQUEST_TIME + T_future` → reject | **422** | **DEC-TZ-03**, bounded by **DEC-TZ-02** | `T_future = 120s` — covers ordinary device drift, nothing more. There is no legitimate reason to record a punch that has not happened. |
| **Past / skew tolerance** *(self-service only)* | `punch_time < REQUEST_TIME − T_past` → reject or flag | **422** or accept-and-flag | **DEC-TZ-02** | `T_past = 120s` for self-service. **Not applicable** to on-behalf, import or regularization paths, which are legitimately historical. |
| **Far-past floor** | `punch_time` before the **later of** the employment start date and the earliest `OPEN` period → reject | **422** | Derived, not a new decision | `1900-01-01T00:00:00Z` is accepted today (verified). A punch before the employee existed is never valid on any path. |
| **Closed period** | `punch_time` in a `CLOSED` period → reject | **409** | **DEC-TZ-10** (which *date basis*) | Existing behaviour (`service.py:2347`), fails closed |
| **Upload lag** *(device/offline paths only)* | `REQUEST_TIME − punch_time > T_lag` → reject | **422** | **DEC-TZ-15 (§11)** | Per-integration; typically hours, not seconds |
| **Source assertion** | `source` is **server-assigned** from the authenticated context; a client-supplied value is rejected or ignored | **422** | **DEC-TZ-05** | Server-assign. This is the linchpin (§6.6) |

## 10.4 Evidence to record on every punch

Whatever DEC-TZ-01 decides, these make a dispute answerable. The column already exists and is never
written (**F-18**).

| Field | Purpose |
|---|---|
| `punch_time` (EVENT) + REQUEST TIME | The pair whose divergence *is* the audit signal |
| Divergence, derived | Reportable: *"punches where `\|event − request\| > threshold`"* — buildable today from the two existing columns, under **any** option |
| `source`, server-assigned | Provenance that cannot be forged (F-11) |
| `recorded_by_user_id` | Already captured. Distinguishes self from on-behalf |
| `raw_payload` — **currently never written** (F-18) | Submitted offset, user-agent, client version, device id, IP. Without it, a bounded-skew or flag-and-review posture has nothing to review |
| `idempotency_key` | Already present. Required by any offline/device replay (§11) |

## 10.5 Invariants that must survive any decision

1. **Punches are append-only** (WD-11). A correction is a new punch or a regularization row — **never**
   an UPDATE or DELETE of an existing punch. Every bound above is an *ingestion* control; none may be
   retrofitted as a mutation.
2. **Storage stays UTC `TIMESTAMPTZ`** (PC-02, DEC-010). Nothing in this contract touches storage.
3. **Attendance is computed from EVENT TIME only.** REQUEST TIME is a validation and audit input — it
   must never leak into `late_minutes`, `worked_minutes` or OT.
4. **Validation is at the schema boundary**, so every caller — web, future mobile, device, import,
   third-party — is bound by the same rules without each path re-implementing them.

---

# 11. MOBILE / OFFLINE ATTENDANCE

> **Current state, CODE-PROVEN: no mobile application exists in this repository, and offline attendance
> is not supported.**

## 11.1 What actually exists

| Question | Finding |
|---|---|
| Mobile app in the repo? | **No.** `apps/` contains exactly `api` and `web`. No `pubspec.yaml`, no React Native, no native project (re-verified 2026-09-15). |
| Offline queue? | **No.** No service worker, no IndexedDB queue, no sync/replay endpoint, no conflict resolution. `punch-entry-dialog.tsx:96-104` surfaces a network failure directly to the user as a toast; **nothing is queued and the punch is lost.** |
| Does the schema anticipate mobile? | **Yes.** `'MOBILE'` and `'DEVICE'` are accepted `punch.source` values in both the Pydantic enum and the DB CHECK, and `idempotency_key` is documented as existing *"chiefly for future device sources, W10"*. |
| Primitives an offline sync would need | **Two of them already exist**: `idempotency_key` (replay safety) and calculation-time duplicate collapsing (TEST-PROVEN). |

**So the question is premature as an implementation matter and urgent as a specification matter** — the
schema is already shaped for it, and the decisions below determine whether that shape is right.

## 11.2 Why this must be decided before a mobile client is built, not after

An offline punch **breaks the core assumption of both DEC-TZ-01 Option A and Option B**:

```text
Employee punches IN  at 09:00 local, phone in airplane mode      ← EVENT TIME, device clock, unverifiable
Employee punches OUT at 18:00 local, still offline               ← EVENT TIME, device clock, unverifiable
Phone regains connectivity at 21:30, uploads both                ← REQUEST TIME, 12.5h after the first event
```

- **Option A (server stamp) cannot serve this at all** — it would stamp both punches 21:30.
- **Option B's ±120s tolerance rejects both** — the lag is four orders of magnitude larger.
- **Option C accepts both without question**, which is the current behaviour and the current risk.

**An offline path is therefore not a variation on the online contract. It is a second contract**, and
pretending otherwise is how a "±2 minute skew tolerance" quietly becomes "±24 hours" and the control
evaporates.

## 11.3 Required policy — **PRODUCT DECISION, NOT DEFINED IN CURRENT REQUIREMENTS**

Recorded as **`DEC-TZ-15`**. Every row is open.

| # | Question | Options | Note |
|---|---|---|---|
| **1** | **Is offline attendance a requirement at all?** | (a) No — the app requires connectivity to punch, and says so · (b) Yes — capture offline, sync later | **Decide this first.** (a) closes every row below and is a legitimate answer for office populations. (b) is near-unavoidable for field, construction, retail or logistics staff. |
| **2** | **Offline timestamp** | (a) Device clock at capture · (b) Device **monotonic** clock anchored to the last server-synced instant · (c) Server receipt at upload | (b) is materially stronger than (a): a monotonic offset from a known-good server time survives a user changing the wall clock, because the elapsed interval is what is recorded. **Not free** — the app must persist an anchor and the elapsed reading. |
| **3** | **Maximum upload delay** | e.g. 4h / 12h / 24h / until end of shift / unbounded | Beyond it: reject, or accept-and-flag for approval. Must be **shorter than the period-close cycle**, or a punch can arrive after its period is `CLOSED` and be silently dropped. |
| **4** | **Device clock manipulation** | (a) Trust it · (b) Record the device↔server offset at every sync and flag drift · (c) Require monotonic anchoring (row 2b) · (d) Require corroboration — geofence (F-19), device attestation, biometric | Offline is **where clock trust matters most and can be verified least.** |
| **5** | **Server receipt time** | Always recorded, non-negotiable | REQUEST TIME (§10.1). The upload-lag check has no anchor without it. |
| **6** | **Original event time** | Preserved as `punch_time` | Otherwise offline attendance is meaningless — the whole point is the earlier instant. |
| **7** | **Conflict resolution** | Duplicate on replay · offline punch contradicting an online one for the same shift · a punch arriving for a **locked** day · out-of-order arrival (OUT before IN) | `idempotency_key` covers *replay*. It does **not** cover contradiction or late arrival. A punch for a `CLOSED` period must be **rejected with a distinguishable error**, not silently dropped — today the period check would reject it, and the employee would have no idea their day was never recorded. |
| **8** | **Failure visibility** | What the employee sees when a queued punch is finally rejected | **The gap most likely to produce a grievance.** An employee who punched, saw a confirmation, and whose punch was rejected four hours later at sync must be told — in the app, and ideally to their manager. |

## 11.4 Recommendation

> ## AI RECOMMENDATION — PRODUCT MUST APPROVE
>
> 1. **Answer row 1 before any mobile work begins.** If offline is not required, say so in writing and
>    make the app fail loudly and visibly when offline — never silently queue, never silently drop.
>    Today's web client already fails loudly, which is the correct behaviour for a client with no queue.
> 2. **If offline is required, treat it as a separate, permissioned ingestion contract**
>    (`source=MOBILE_OFFLINE`), with its own upload-lag bound (§10.3), **never** by widening the
>    self-service skew tolerance. The two must be independently configurable, or the online control is
>    lost.
> 3. **Prefer monotonic anchoring (row 2b) over a raw device clock.** It is the single highest-value
>    control available on an offline path and is far cheaper to build into a new app than to retrofit.
> 4. **Require an explicit reconciliation surface**: every offline punch shows both its event time and
>    its upload time to the employee and the approver, and any punch exceeding the lag bound enters an
>    approval queue rather than being silently accepted or silently dropped.
> 5. **Do not build any of it yet.** No mobile client exists; these are the constraints its
>    specification must satisfy, recorded now so the schema decisions already made (`MOBILE` source,
>    `idempotency_key`) are validated rather than assumed.

---

# 12. CROSS-MIDNIGHT BREAKS — `F-05`

**Classification: CODE BUG.** No decision required. **Do not fix yet** — this document is the
specification, and the fix is scheduled in §18 (P0).

## 12.1 Current behaviour

```python
# calculation.py:583-601 (re-read 2026-09-15)
gap_start_local = gap_start.astimezone(tz).time()          # ← correct: UTC → local, then time-of-day
for shift_break in shift_breaks:
    if shift_break.break_kind == "FIXED_WINDOW" and shift_break.start_time is not None:
        if (shift_break.start_time
                <= gap_start_local
                <= (shift_break.end_time or shift_break.start_time)):
            best = shift_break
            break
    elif shift_break.break_kind == "FLEXIBLE_DURATION" and shift_break.window_start is not None:
        window_end = shift_break.window_end or shift_break.window_start
        if shift_break.window_start <= gap_start_local <= window_end:
            best = shift_break
            break
is_paid = best.is_paid if best is not None else False       # ← unmatched ⇒ UNPAID
```

## 12.2 Why it fails

The comparison is a **chained inequality on a `time` value**, which assumes `start_time <= end_time`.
For a break that crosses midnight, it does not:

```text
Break configured:  23:30 – 00:30   (a perfectly ordinary night-shift meal break)
Actual gap:        23:45 – 00:05 local

Test evaluated:    time(23,30) <= time(23,45) <= time(0,30)
                   └── True ──────────────────┘ └── False ──┘
Result:            False  →  best = None  →  is_paid = False
```

**The root cause is structural, not arithmetic:** `shift_break.start_time` / `end_time` are wall-clock
`TIME` columns with **no cross-midnight flag** — unlike `shift_version.is_cross_midnight` and
`shift_duty_block.crosses_midnight`, both of which exist and are honoured. The break table is the one
place in the schema where the midnight problem was not modelled.

Note what is **not** wrong: the `UTC → local → time-of-day` conversion order is **correct**, and is
PC-15 — a gap at the *ambiguous* `01:10` local on a London fall-back night matches its `01:00–01:30`
break correctly. **This defect is about midnight, not about DST.** A fix must preserve the conversion
order.

## 12.3 Expected behaviour

A punched gap falling inside a configured break window is matched to that break and inherits its
`is_paid` and `max_minutes`, **regardless of whether the window crosses midnight.**

## 12.4 Affected scenarios

| # | Break window | Gap starts | Today | Expected |
|---|---|---|---|---|
| 1 | `13:00 – 14:00` (day shift) | 13:15 | ✔ matched, paid | matched, paid |
| 2 | **`23:30 – 00:30`** (night shift) | 23:45 | ✘ **unmatched, unpaid** | matched, paid |
| 3 | **`23:30 – 00:30`** | 00:05 | ✘ **unmatched, unpaid** | matched, paid |
| 4 | `22:00 – 23:00` (night shift, no midnight cross) | 22:15 | ✔ matched | matched |
| 5 | `FLEXIBLE_DURATION` window `23:00 – 01:00` | 23:30 | ✘ **unmatched, unpaid** | matched |
| 6 | Excess-break detection across midnight | — | 🔲 **not executed during the audit** (matrix I4) | `max_minutes` honoured |

Also relevant and **separate** (`ATT-009`, P3): `match_breaks` compares only the gap's **start**
time-of-day. A gap that *starts* outside a window and *ends* inside it is unmatched even on a day
shift. That is a pre-existing limitation, not part of F-05, and should not be silently bundled into
this fix.

## 12.5 Production impact

> **This is a paid-minutes defect, not a display defect.**

```text
unmatched gap  →  is_paid = False
               →  break minutes excluded from worked_minutes
               →  worked_minutes drops
               →  paid_day_fraction drops
               →  OT (worked − scheduled) suppressed
```

- **Population:** exactly the night-shift employees most likely to have a midnight-spanning break.
- **Likelihood:** **certain**, wherever such a break is configured. Not probabilistic — the comparison
  is always `False`.
- **Direction:** always against the employee. It never over-credits.
- **Visibility:** silent. No error, no flag. It surfaces as an unexplained shortfall in a payslip.
- **Risk register:** `R-4`, likelihood *certain*, impact *Medium-High*.

## 12.6 Required fix

**Compare against the UTC span, not the local time-of-day** — the approach `_core_hours_breached`
already uses successfully in the same module for the same class of problem. Two candidate shapes:

| Approach | Change | Assessment |
|---|---|---|
| **A — Wrap-aware time-of-day comparison** | When `end_time < start_time`, test `gap_start_local >= start_time OR gap_start_local <= end_time` | Minimal diff; no schema change; **infers** the midnight cross from the column values — the exact inference pattern `is_cross_midnight` exists to avoid (PC-05). Acceptable for a break, where there is no legitimate 24-hour window, but it is an inference. |
| **B — Build the break's UTC span from the attendance date and compare instants** | Convert `start_time`/`end_time` to UTC instants on the day's date, rolling the end forward when it precedes the start; compare `gap_start` directly | **Consistent with how the rest of the engine works** (`scheduled_span_utc`, `_core_hours_breached`). Handles DST inside the break window for free. Slightly larger diff. |

**Recommended: B**, with a `crosses_midnight` boolean added to `shift_break` in a follow-up so the roll
is *declared* rather than inferred — matching `shift_version` and `shift_duty_block`. Ship B's logic
first (P0); the column is P2 hardening.

**Whichever is chosen, preserve the `UTC → local` conversion order (PC-15) and re-run matrix C14.**

## 12.7 Required tests

| # | Test | Type |
|---|---|---|
| 1 | Gap at `23:45` vs break `23:30–00:30` → `matched, is_paid=True` | unit, pure |
| 2 | Gap at `00:05` vs break `23:30–00:30` → `matched, is_paid=True` | unit, pure |
| 3 | Gap at `13:15` vs break `13:00–14:00` → still matches *(regression guard)* | unit, pure |
| 4 | Gap at `22:15` vs break `23:30–00:30` → correctly **unmatched** *(no over-matching)* | unit, pure |
| 5 | `FLEXIBLE_DURATION` window `23:00–01:00`, gap at `23:30` → matched | unit, pure |
| 6 | Excess break across midnight: 45-minute gap vs `23:30–00:30` with `max_minutes=30` → `is_excess=True` | unit, pure — **closes matrix I4** |
| 7 | End-to-end night shift `22:00–06:00` with a `23:30–00:30` paid break → `worked_minutes` includes the break; `paid_day_fraction = 1.00` | unit, engine-level |
| 8 | Matrix C14 re-run: ambiguous `01:10` local vs break `01:00–01:30`, London fall-back → still `matched, paid` *(PC-15 regression guard)* | unit, pure |

All eight are **pure-function tests with no database** — the engine's purity (PC-12) makes this fix
unusually cheap to prove.

---

# 13. TODAY / CURRENT-DATE LOGIC

Every server- or UTC-dependent date derivation, re-verified by grep against the working tree on
2026-09-15. `DEC-010` (LOCKED) requires *"never UTC midnight, never server-local time"* — the second
column is measured against that.

## 13.1 Unsafe — server-OS-local or UTC where a business date is meant

| Location | Current Source | Correct Source | Risk |
|---|---|---|---|
| [`attendance/service.py:3502`](../../apps/api/src/hrms/modules/attendance/service.py#L3502) | `date.today()` — **server OS local** | Resolved attendance timezone for the employee-date | **Regularization future-date rejection.** A request valid at 23:00 IST is rejected as future-dated in a UTC container; the reverse in an IST deployment. Moves between dev and production. **TZ-06 / F-10** |
| [`attendance/service.py:3547`](../../apps/api/src/hrms/modules/attendance/service.py#L3547) | `date.today()` — **server OS local** | Same | **Regularization backdating window.** `(date.today() - attendance_date).days` shifts by one at the boundary, so a request is accepted in one environment and rejected in the other. **TZ-06 / F-10** |
| [`leave/service.py:1979`](../../apps/api/src/hrms/modules/leave/service.py#L1979) | `date.today()` — **server OS local** | Company timezone | **Leave backdating window** (`max_backdated_days`). Same off-by-one. **TZ-06 / `DAT-005`** |
| [`leave/service.py:1990`](../../apps/api/src/hrms/modules/leave/service.py#L1990) | `datetime(now.year, now.month, 1, tzinfo=UTC)` — **UTC month start** | Company-timezone month start | **`max_requests_per_month` counts by UTC month.** For IST, applications submitted between 00:00 and 05:29 on the 1st count against the *previous* month, and the same window on the 1st of the next month double-counts. **`DAT-005`** |
| [`leave/service.py:2597`](../../apps/api/src/hrms/modules/leave/service.py#L2597) | `date.today()` — **server OS local** | Company timezone | **Reversal ledger `effective_date`** on cancel-after-approval. A ledger entry can land in the wrong accrual period at a month boundary. **`DAT-004`** |
| [`web/src/lib/attendance/format.ts:28`](../../apps/web/src/lib/attendance/format.ts#L28) `todayIso()` | `new Date().toISOString().slice(0,10)` — **UTC date** | Attendance/company timezone date | **Default date filters** on the attendance, overtime, rosters and regularizations pages. For IST users between 00:00 and 05:30 local, **every default filter is off by one day**. Display only — never reaches a calculation. **TZ-07 / F-09** |

## 13.2 Deliberate deviation — documented, fails closed

| Location | Current Source | Correct Source | Risk |
|---|---|---|---|
| [`attendance/service.py:2347`](../../apps/api/src/hrms/modules/attendance/service.py#L2347) | **UTC date of `punch_time`** for the period-lock check | Local attendance date — *but it is not knowable before shift resolution, which itself depends on the date* | **Documented as WD-30 in the code itself.** For `Asia/Kolkata`, local `00:00–05:29` maps to the *previous* UTC date, so a 05:00 IST punch on 1 Oct is lock-checked against September (matrix F2). **Fails closed** — the safe direction — and `calculate()` refuses a locked day unconditionally as the backstop. The exposure is **early-morning** punches; a 23:00 IST punch does **not** diverge (matrix F5). **DEC-TZ-10 — expect "accept as documented".** |

## 13.3 Safe — no change required

| Location | Source | Why it is correct |
|---|---|---|
| `attendance/service.py:2337`, `:3556` | `datetime.now(UTC)` | Explicit UTC instant, not a business date |
| `organisation/service.py:668` | `datetime.now(UTC)` | Same |
| `core/db/base.py` `TimestampMixin` | PG `func.now()` | Database UTC |
| `…_punch.py` migration | `DEFAULT now()` | Database UTC (always overridden by the application today — see §10.1) |
| **Repository-wide** | **`datetime.utcnow()` — zero occurrences** | PC-13 |

## 13.4 The remediation pattern

All six unsafe sites need the same thing and should be fixed **together, once**:

> A helper — `business_today(company_id, employee_id=None) -> date` — that resolves the applicable
> timezone through the existing WD-06 chain and returns `datetime.now(UTC).astimezone(ZoneInfo(tz)).date()`.
> Every `date.today()` and every UTC-month boundary in a business rule calls it.

Two notes that keep this honest:

- **The leave sites resolve at company level; the attendance sites resolve at employee level** (through
  branch/shift). One helper, two entry points — do not force leave through an employee resolution it
  does not have.
- **`todayIso()` needs the company timezone on the client.** It is not currently on the wire for the
  *user*, only per attendance day. The simplest correct fix is to return the company timezone in the
  session/bootstrap payload and have `todayIso()` take it as an argument — which is also what §9's
  formatter change needs. **Fix TZ-03 and TZ-07 in the same change.**

---

# 14. TZDATA

**Finding:** TZ-05 (🟠 P1) · **Classification: INFRASTRUCTURE ISSUE** · **No dependency change is made here.**

## 14.1 Facts — CODE-PROVEN by running the actual production base image

| Question | Answer |
|---|---|
| Library | Python stdlib `zoneinfo` (`calculation.py:47`). **`pytz` is not used anywhere.** |
| IANA support | ✔ Full; every timezone column is validated against `zoneinfo.available_timezones()` at the schema layer |
| **System tzdata** in `python:3.12-slim` | **2026b-0+deb13u1** (Debian 13) |
| PyPI `tzdata` in the base image | **NOT INSTALLED** |
| **PyPI `tzdata` in the app image** | **2026.3** — `uv.lock:2148`, pulled **transitively** by `kombu`, `psycopg` and `tzlocal` |
| Declared as a direct dependency | **NO** — absent from `pyproject.toml` (re-verified 2026-09-15) |
| `zoneinfo.TZPATH` | `('/usr/share/zoneinfo', '/usr/lib/zoneinfo', '/usr/share/lib/zoneinfo', '/etc/zoneinfo')` |
| **Which one actually wins** | **`/usr/share/zoneinfo` — the system copy, 2026b.** `zoneinfo` searches `TZPATH` in order and falls back to the PyPI `tzdata` package **only when every `TZPATH` entry misses.** In this image none of them misses. |
| Update strategy | **None.** The Dockerfile runs no `apt-get`; `python:3.12-slim` is **not digest-pinned**; no rebuild cadence is documented; no deployment manifest for the API service exists in the repository. |

## 14.2 Three compounding problems

1. **The newer tzdata is installed but never consulted.** The lockfile pins 2026.3; the container
   resolves zones from 2026b. **A fix shipped in 2026.3 would not take effect** — and nothing anywhere
   would indicate that.
2. **The system tzdata is frozen at image build.** There is no update path at all. A long-lived image
   accumulates increasingly stale rules with no signal.
3. **`tzdata` is an undeclared transitive dependency.** If `kombu`, `psycopg` or `tzlocal` ever drops
   it, the fallback silently disappears with **no lockfile signal** — a dependency bump would remove a
   correctness input, and the diff would show only an unrelated package's version change.

## 14.3 Production implications

Timezone rules change several times a year by government decree — DST adoption or abolition, permanent
offset changes, new zones. Two independent failure modes:

| Failure | What happens | Detectability |
|---|---|---|
| **Stale rules** | A jurisdiction changes its DST dates; the frozen image computes the old transition. Attendance in that zone is off by an hour for the window between the real and the believed transition. | **Silent.** No error. Surfaces as disputed attendance, weeks later. |
| **Version skew between processes** | The API, the Celery worker and the Beat scheduler are separate containers. If they are built at different times from an unpinned base tag, they can carry **different tzdata**. A scheduled recompute could then disagree with an interactive one. | **Silent**, and intermittent — the worst diagnostic profile in the document. |

### Jurisdictions affected

| Tenant zone | Exposure |
|---|---|
| `Asia/Kolkata` — **all tenants today** | **None.** India has no DST and a stable offset (unchanged since 1945). |
| `Europe/London`, `America/New_York`, EU zones | Stable rules, but subject to active legislative proposals to abolish DST |
| `Asia/Dubai`, Gulf states | No DST; low exposure |
| Recently-reformed jurisdictions (e.g. Mexico 2022, Jordan/Syria 2022, Chile, Morocco, Iran, Fiji) | **High.** These are exactly the changes tzdata releases exist to carry |

> **This is dormant, not absent.** It is worth zero attention for the current tenant base and becomes a
> live correctness risk on the day a DST-observing or recently-reformed jurisdiction is onboarded.

## 14.4 Recommended deployment policy — **engineering decision, not a client decision**

> **Recommendation. No dependency change is made by this document.**
>
> 1. **Choose one authoritative source and make it win deliberately.** Two coherent answers:
>    - **(a) System tzdata authoritative** — add `apt-get install -y --no-install-recommends tzdata` to
>      the Dockerfile and **digest-pin** `python:3.12-slim`. Simple; ties tzdata freshness to the image
>      rebuild cadence.
>    - **(b) PyPI tzdata authoritative** — declare `tzdata` as a **direct** dependency in
>      `pyproject.toml` and ensure it wins. **Recommended.** It puts timezone data under the same
>      lockfile, review and dependency-bump discipline as every other correctness-relevant input, and it
>      makes a tzdata change appear in a PR diff instead of in an image rebuild nobody reviews. Note it
>      requires making the PyPI copy actually take precedence — `zoneinfo` prefers `TZPATH`, so this
>      means either removing the system copy or setting `PYTHONTZPATH`/`TZPATH` explicitly. **Verify the
>      resolution order in the built image, do not assume it.**
> 2. **Declare `tzdata` explicitly regardless of (a) or (b).** Relying on a transitive dependency for a
>    payroll-correctness input is indefensible, and the declaration costs one line.
> 3. **Digest-pin the base image.** Unrelated to tzdata and independently worth doing — `python:3.12-slim`
>    is a moving tag, so today's build and next month's are different images.
> 4. **Assert the loaded tzdata version at startup** and log it; fail readiness (or emit a loud warning)
>    if it is older than N months. Cheap, and it converts the silent failure mode above into a visible
>    one. **This is the single highest-value item in this section.**
> 5. **Document a rebuild cadence** — quarterly at minimum, and on demand when a tenant's jurisdiction
>    changes its rules.
> 6. **Build all three service images (API, worker, beat) from one pinned base in one pipeline run**, so
>    version skew between processes cannot arise.

**Priority: P1 before any non-`Asia/Kolkata` tenant. P2 otherwise** — items 2, 3 and 4 are cheap enough
to do now regardless.

---

# 15. THE ±2 HOUR PUNCH LOAD WINDOW

**Finding:** TZ-08 (🔵 P2) · **New decision: `DEC-TZ-16`** · **Classification: BUSINESS POLICY DECISION**

## 15.1 What exists

```python
# calculation.py:310-330 (re-read 2026-09-15)
def punch_window_utc(*, attendance_date, tz_name, start_time, end_time,
                     is_cross_midnight,
                     lookback_hours: int = 2,
                     lookahead_hours: int = 2) -> tuple[datetime, datetime]:
    """... the scheduled span padded by `lookback_hours`/`lookahead_hours` so an early-arriving
    or auto-closed-late punch is still attributed to this date, not silently dropped."""
    ...
    return start - timedelta(hours=lookback_hours), end + timedelta(hours=lookahead_hours)
```

Both parameters are **defaulted and never overridden by any caller**. The pad is not exposed in any
policy, not configurable per tenant, shift or branch, and not documented in any client-facing material.

The docstring shows the intent is right — the pad exists *precisely so that* early and late punches are
**not** silently dropped. The finding is that the chosen width has a hard edge, and past that edge the
outcome is the very thing the pad was written to prevent.

## 15.2 How a legitimate punch is orphaned

For a `09:00–18:00` shift in `Asia/Kolkata` (matrix A1–A11, CODE-PROVEN), **only `07:00`–`20:00` local
is loadable**:

| Local wall time | UTC instant | Owning attendance date |
|---|---|---|
| 06:59 | `2026-09-15T01:29Z` | **none — orphaned** |
| **07:00** | `2026-09-15T01:30Z` | `2026-09-15` ← window opens |
| 09:00 | `2026-09-15T03:30Z` | `2026-09-15` |
| 18:00 | `2026-09-15T12:30Z` | `2026-09-15` |
| **20:00** | `2026-09-15T14:30Z` | `2026-09-15` ← window closes |
| 20:01 | `2026-09-15T14:31Z` | **none — orphaned** |

> **Worked example.** A factory supervisor on a `09:00–18:00` shift arrives at **06:45** to open the
> floor and punches IN. A machine breakdown keeps them until **20:30**, and they punch OUT.
>
> **Both punches are stored. Neither is loaded by any attendance day.** The employee shows as
> **ABSENT** — or `INCOMPLETE` if one of the two happened to fall inside the window — for a day on which
> they worked nearly fourteen hours. No error is raised at punch time (the punch succeeded), no warning
> appears on the attendance day, and no report lists orphaned punches. The first signal is the employee
> querying their payslip.

The same mechanism is the reason an out-of-range regularization (F-12) or a wildly fabricated timestamp
(F-01/F-03) is currently harmless — **the one place this behaviour helps.** That is an accident, not a
control, and it must not be relied on as one.

## 15.3 Is this a business policy or a technical limitation?

**Both, and separating them is the point of this section.**

| Aspect | Nature |
|---|---|
| **That a bounded window exists at all** | **Technical necessity.** Without a bound, resolving which day owns a punch would require scanning unbounded punch history, and adjacent days' windows would overlap ambiguously. A bound is not optional. |
| **That the bound is ±2 hours** | **Business policy, currently set by a Python default argument.** It encodes an unstated answer to *"how early may someone arrive, or how late leave, and still have it count?"* |
| **That exceeding it is silent** | **Defect, under any policy.** Whatever width is chosen, a punch belonging to no day should be visible. Nobody would choose silence if asked. |

The second row is the decision. **The third row should be fixed regardless of the second.**

## 15.4 Options

| | Option | For | Against |
|---|---|---|---|
| **A** | **Keep ±2h fixed; add an orphaned-punch report** | Zero behavioural change — no recompute, no policy migration. Converts a silent failure into a visible one, which is the actual harm. Cheapest by a wide margin. | The supervisor above is still ABSENT until someone reads the report and files a regularization. |
| **B** | **Make the pad policy-configurable** (per `AttendancePolicyVersion`, effective-dated like every other policy field) | Expresses a genuine business difference — a factory with early openers wants ±4h; a call centre wants ±1h. Fits the existing versioned-policy machinery exactly. | New policy field + UI + validation + migration. **Widening the pad changes computed attendance** for any day recomputed afterwards, so it needs the same care as F-04. Overlapping windows on adjacent days become possible past ~±6h for an 8-hour shift — the policy must be validated against the shift length, not accepted blindly. |
| **C** | **Derive the pad from the shift** (e.g. half the gap to the adjacent shift, capped) | No configuration for the administrator to get wrong; naturally prevents overlap. | Implicit and hard to explain; a rostered back-to-back shift would shrink the pad invisibly. **Not recommended** — it trades a visible constant for an invisible formula. |
| **D** | **Widen the default to ±4h and keep it fixed** | One-line change; covers the common early-opener and late-closer cases. | Still arbitrary, still unstated, and it **silently changes computed attendance** on any subsequent recompute — a policy change disguised as a constant change. **Not recommended on its own.** |

## 15.5 Recommendation

> ## AI RECOMMENDATION — CLIENT / PRODUCT MUST APPROVE **if the pad changes**
>
> **Option A now, unconditionally and without needing approval, because it changes no computed value:**
> add an **orphaned-punch report** — punches with no owning `attendance_day` — surfaced to HR and
> included in the period-close checklist. Silence is the real defect here; **±2h may well be the right
> number, and nobody can tell while the failure is invisible.**
>
> **Then Option B, if and only if the client confirms the policy question.** Ask them directly:
>
> > *How early may an employee arrive before their shift, and how late may they leave after it, and
> > still have those punches count toward that day's attendance? Currently: two hours either side, and
> > anything outside is silently not counted.*
>
> If the answer is "two hours is fine", **record it as a decision and document it client-facing** — the
> constant stays, but it stops being an accident. If the answer differs by site or shift type, implement
> Option B on the existing `AttendancePolicyVersion` machinery, **validated against shift length so
> adjacent days' windows cannot overlap.**
>
> **Do not widen the default silently (Option D).** Any pad change alters computed attendance on the
> next recompute for every affected day, and that is a communicated policy change, not a constant tweak.

---

# 16. CONCURRENCY — READ COMMITTED AND THE TORN CONFIGURATION READ

**Finding:** TZ-09 (🔵 P2), with **F-15** · **Classification: CODE BUG** (latent)

## 16.1 Current state — CODE-PROVEN

| Property | Finding | Evidence |
|---|---|---|
| Session scope | One request-scoped `AsyncSession`, commit at the end | `core/db/session.py` |
| **Isolation level** | **READ COMMITTED** — the PostgreSQL default. **Nothing anywhere sets `isolation_level` or `execution_options`.** | `SHOW default_transaction_isolation` → `read committed` on the running dev Postgres; grep confirms no override |
| Timezone resolution and calculation in one transaction? | **Yes** — same session | CODE-PROVEN |
| **Snapshot consistency within that transaction?** | **No.** READ COMMITTED gives each **statement** a fresh snapshot, not the transaction | PostgreSQL semantics |
| Row lock on `attendance_day` during recompute? | **None** | CODE-PROVEN by absence (**F-15**) |

## 16.2 Number of reads per calculation

`_build_calculation_input` (`attendance/service.py:2711…`) issues **separate `SELECT` statements** for,
at minimum: employment, employee assignment, **company**, **branch**, shift roster, shift version,
shift breaks, attendance policy resolution, overtime policy resolution, work-calendar/holiday
resolution, leave-day projection, punches, and sibling-day counts for the trailing late/excess-break
windows.

**Two of those — company and branch — carry the timezone.** Under READ COMMITTED each one sees whatever
was committed at the moment *that statement* ran.

## 16.3 The race

```text
T0  calculate() begins its transaction
T1  SELECT company  →  timezone = 'Asia/Kolkata'        ← statement snapshot A
T2  ────────  a concurrent UPDATE branch SET timezone='Asia/Dubai' COMMITS  ────────
T3  SELECT branch   →  timezone = 'Asia/Dubai'          ← statement snapshot B
T4  resolve_timezone(None, 'Asia/Dubai', 'Asia/Kolkata') → 'Asia/Dubai'
T5  … the rest of the calculation proceeds on a configuration that never existed atomically
```

The stored `attendance_day` mixes pre-change and post-change configuration. **No error is raised.** The
row looks entirely normal and is silently not reproducible from any single consistent view of the
database — which is a direct violation of WD-11's reproducibility posture.

A second, related race (**F-15**): two concurrent `calculate()` calls for the same employee-date both
read-then-write. The `UNIQUE` constraint prevents duplicate *rows*; it does **not** prevent
last-writer-wins. Combined with the above, two concurrent recomputes straddling a config edit can
persist either result, non-deterministically.

## 16.4 Practical likelihood and impact

| Dimension | Assessment |
|---|---|
| **Window** | Milliseconds — between two `SELECT`s in one request |
| **Trigger** | A timezone `UPDATE` committing *during* a calculation. Timezone edits are rare (approximately: once, at setup) and calculations are frequent, so the *joint* probability is **low** |
| **Impact if it fires** | One `attendance_day` computed against a configuration that never existed. Feeds `paid_day_fraction`. **Silent** |
| **Detectability** | **Effectively zero.** No error, no log, no flag. The row is indistinguishable from a correct one |
| **Honest summary** | **Low likelihood, high silence.** It should be closed, but it is not what is keeping this subsystem from production — **TZ-01 is**, and TZ-01's guard closes this as a side effect |

## 16.5 Remediation options

| | Option | Assessment |
|---|---|---|
| **A** | **Close it via TZ-01's guard** — if a timezone cannot be changed while computed attendance exists (§5 Option A), the concurrent `UPDATE` cannot happen | **Recommended.** Zero additional cost; it is a free consequence of work that is already P0. **Closes the timezone-specific race entirely.** Does **not** close the race for other mutable configuration read across the same statements, nor F-15 |
| **B** | **`REPEATABLE READ` for the calculation transaction only** | Closes it properly and generally — one transaction-level snapshot for all reads. Costs: PostgreSQL may raise serialization failures that the application must retry, and applying it narrowly to one code path in a shared request-scoped session is more intrusive than it sounds. **Worth doing, after A, and only with retry handling** |
| **C** | **`SELECT … FOR UPDATE` on `attendance_day`** during recompute (**F-15**) | Closes last-writer-wins. Orthogonal to the torn read — **do both or neither is complete** |
| **D** | **Re-read the timezone once, at the start, and pass it through** | Does not help — the first read is already one statement; the problem is the *second* read of a different table |

> **`SERIALIZABLE` is not recommended.** It would close both races, but it imposes serialization-failure
> retries across the *entire* application for a narrow, low-likelihood window in one code path, and
> nothing in this audit justifies that cost. **Option A + Option C is the proportionate answer**, with
> Option B reserved for if the configuration surface later grows mutable inputs that Option A's guard
> does not cover.

## 16.6 Required tests

| # | Test | Type |
|---|---|---|
| 1 | Timezone `UPDATE` committing between two reads in one calculation → either rejected by the guard, or the calculation is internally consistent | integration, **needs DB + two sessions** |
| 2 | Two concurrent `calculate()` calls for one employee-date → deterministic result, no lost update | integration, **needs DB** |
| 3 | Connection-pool reuse: successive requests on a recycled connection see no leaked session state (`SET TIME ZONE`, `SET SESSION …`) | integration |

All three are in the **high-cost** tier of §19 and are correctly sequenced last.

---

# 17. FINAL CLIENT DECISION REGISTER

**This table is the decision surface.** It supersedes
[`ATTENDANCE_TIMEZONE_DECISION_REGISTER.md`](../business-rules/attendance/ATTENDANCE_TIMEZONE_DECISION_REGISTER.md)
as the thing to be signed; that register remains the long-form rationale for `DEC-TZ-01`…`DEC-TZ-14`.

**Included here only where the decision genuinely requires client or product approval.** Findings with
an unambiguous correct answer — TZ-02's naive rejection, TZ-06, TZ-07, TZ-09, TZ-12, F-05, F-12, F-15 —
are **not** decisions. They are in the backlog (§18) and need no signature.

**`Client Decision` is left blank by design.**

| Decision ID | Question | Why It Matters | Options | AI Recommendation | Client Decision | Blocks Production? |
|---|---|---|---|---|---|---|
| **DEC-TZ-01** ⭐ | **Who is authoritative for the time of a punch?** (§6) | Any holder of the baseline `ATTENDANCE.PUNCH` permission currently controls their own `late_minutes`, `worked_minutes`, `ot_minutes_detected`, `paid_day_fraction` and `lop_fraction` — the documented payroll inputs. The shipped UI exposes the timestamp as an editable field, so no manipulation is required. | **A** Server-authoritative · **B** Client within bounded skew · **C** Client, unvalidated *(current)* | **A for self-service punches; B semantics for on-behalf, device and import paths; never C.** Server-assign `source` in the same change — without it the per-path rules are advisory. If C is chosen, record it as a **signed risk acceptance** of `R-1`/`R-2` with detective controls. | | **YES — this is the blocker.** Determines DEC-TZ-02/03/04. |
| **DEC-TZ-02** | **What clock-skew tolerance is acceptable?** | Unbounded in both directions today. Legitimate skew (unsynchronised devices, a stale open dialog, latency) is indistinguishable from fabrication without a threshold. The tolerance **is** the control. | ±30s · **±120s** · ±5min · ±15min · accept-but-flag | **±120s, rejecting outside it**, for self-service only. Generous for ordinary drift, tight enough that meaningful manipulation is impossible. Separate, larger bounds for device/import paths. `created_at` already records the comparison point — no schema change. | | **YES**, if DEC-TZ-01 = B |
| **DEC-TZ-03** | **May a punch be dated in the future?** | Accepted without limit today (`2099-01-01T00:00:00Z` verified accepted). Fabricated future overtime. Regularization already rejects future dates — **the punch path's omission looks unintentional.** | Reject beyond tolerance · small forward window · admin-only · accept-but-flag | **Reject beyond the DEC-TZ-02 tolerance**, mirroring the regularization precedent. Add a carve-out only if a genuine forward-dated use case is identified. | | **YES** |
| **DEC-TZ-04** | **How should an offset-less timestamp be interpreted?** | The same request stores instants **5h30m apart** in dev (IST host) and production (UTC container). Silent, environment-dependent data corruption that testing cannot reveal, because each environment is self-consistent. | **Reject** · interpret as UTC · interpret as company tz · keep current | **Reject naive timestamps** (`AwareDatetime` on `PunchCreate.punch_time`) — explicit beats inferred for a payroll input. **Independently pin `TZ=UTC` in the Dockerfile and CI regardless of the answer**, so the two environments agree either way. | | **YES** |
| **DEC-TZ-05** | **May a caller assert an arbitrary punch `source`?** | All 7 values — including `DEVICE` and `REGULARIZATION` — are accepted from an ordinary self-punch. A hand-typed web punch can be recorded as a biometric device reading, destroying the field an investigator relies on. **This is the linchpin of any per-path rule under DEC-TZ-01.** | Server-assign from auth context · restrict by permission · separate `ingestion_channel` column · keep as-is | **Server-assign from the authenticated context.** `REGULARIZATION` settable only by the apply path; `DEVICE`/`IMPORT`/`API` only with the corresponding integration permission. **Must ship with DEC-TZ-01, not after.** | | **YES** |
| **DEC-TZ-06** | **Should punch rounding work, or be withdrawn?** | `punch_rounding` / `rounding_minutes` are configurable, validated and exposed in the UI, and `apply_rounding` has **zero call sites**. An HR user who configures 15-minute rounding gets none and believes otherwise. **Fixing it changes computed attendance** for every tenant with a value set. | Wire in · remove field + UI · leave inert + document · wire in behind per-tenant opt-in | **Wire it in**, applied to a *copy* of the punch for evaluation only — exactly what the function's own docstring specifies (*"the raw punch timestamp is never mutated (WD-11)"*). **Audit which tenants have non-`NONE` values first; recompute affected open periods deliberately and with notice, never silently.** | | **YES** (policy credibility) |
| **DEC-TZ-07** | **Night-OT: configured window or shift flag?** | `night_window_start`/`_end` are loaded and never read; `is_night = shift.is_cross_midnight`. `night_ot_mode="WINDOW"` behaves identically to `"BOTH"`. Night OT usually carries a premium — **the two give different pay.** | Honour `night_ot_mode` as designed · remove the window fields · document `WINDOW` as unimplemented | **Honour `night_ot_mode` as designed** — `SHIFT_FLAG` / `WINDOW` / `BOTH`. The three-valued enum already encodes the intent; only the engine's implementation is missing. | | **YES** (payroll correctness) |
| **DEC-TZ-08** | **Which timezone should the UI display?** (§9) | LOCKED `DEC-010` mandates company-timezone rendering; the UI renders in the **viewer's browser** zone. Today nothing looks wrong because everyone is in one zone. **The data is already on the wire and unused.** | **A** Attendance timezone + label · **B** Viewer *(current)* · **C** Both · **D** Per-user preference | **A, plus C on the day-detail page only.** Also **amend DEC-010's rendering clause** to name the *resolved* attendance timezone (WD-06) rather than `company.timezone` — literal compliance would render times in a zone the figures were not computed in. **The amendment to a LOCKED decision is the client's call.** | | **YES — at the moment a second timezone goes live** |
| **DEC-TZ-09** | **Does an employee need a timezone independent of their branch?** | A Kerala employee working remotely from Dubai is judged against Kerala hours. There is **no** employee-level timezone column; adding one amends LOCKED `WD-06`. | Keep 3-tier chain · add `Employee.timezone` · per-date override · require a branch transfer | **Keep the current chain for V1** and document explicitly that attendance is judged in the **work-location's** timezone regardless of physical presence. **Do not pre-build a fourth tier** for a requirement nobody has confirmed. | | NO — P2, rises to P0 if a multi-timezone client is onboarded |
| **DEC-TZ-10** | **Which date basis governs the period lock?** | The punch path locks on the **UTC date** of `punch_time`; every other caller uses the local attendance date. For IST, local `00:00–05:29` maps to the previous UTC date — a 05:00 IST punch on 1 Oct is checked against September. | Accept as documented · resolve the date at ingestion · widen ±1 day · require both dates open | **Accept the current approximation and document it client-facing.** The reasoning is sound (WD-30), it **fails closed**, and resolving it properly needs shift resolution during ingestion — a significant change for a narrow edge. Confirm the client accepts an occasional month-boundary rejection, and give support a script for it. | | NO |
| **DEC-TZ-11** | **How should ambiguous / nonexistent local times resolve?** (§8) | `fold=0`, silently. A shift configured for 02:30 on a spring-forward date **actually starts at 03:30**, with no warning. Scope is shift/break **configuration** only — a punch is an instant and can never be ambiguous. | Document `fold=0` + publish-time warning · reject nonexistent at publish · `fold=1` for ambiguous · per-shift config | **Keep `fold=0`, record it as stated policy, and warn (not reject) at shift-publish time** when a configured time falls in a transition window. No engine change, no schema change, no recompute. | | NO today — **YES before any DST-observing tenant** |
| **DEC-TZ-12** | **When should attendance be calculated, and in whose midnight?** | Nothing computes attendance automatically — `attendance_day` rows exist only where an endpoint was explicitly called. A period cannot be finalized, so Payroll has **no input at all** (`PAY-001`). Timezone-relevant: a nightly job must run after the last shift ends *in the latest zone the tenant operates in*, and cross-midnight shifts are not complete until the next morning. | Scheduled per-tenant trailing-N-day recompute · sync on each punch · lazy on read · only at period finalization | **Scheduled per-tenant recompute of the trailing N days (N ≈ 3)**, to absorb late punches, approved regularizations and cross-midnight completion — **scheduled in each tenant's own attendance timezone.** Keep the on-demand endpoints for interactive use. | | **YES** |
| **DEC-TZ-13** ⭐ | **May a company/branch timezone change once attendance exists?** (§5) | Editing either silently rewrites already-approved historical attendance on the next recompute (`PRESENT` → 264 min early departure, worked example). The guard is an empty stub whose precondition is met, and `update_branch` never calls it at all. | **A** Prohibit · **B** Effective-date · **C** Allow + acknowledged recompute | **A now** (~1 day: implement the guard, call it from **both** paths, permit the change only while `TRIAL` or zero computed days — reusing the existing currency-lock precedent). **B as the target state**, triggered by the first genuine relocation or multi-timezone tenant. **Not C as the primary posture** — it is destructive to historical figures. Refusing the change while any period is `CLOSED` is **not negotiable** under any option. | | **YES** |
| **DEC-TZ-14** | **Should a DST transition change scheduled minutes, and therefore OT?** (§7) | An employee working the full wall-clock shift on a fall-back night earns **zero OT for nine real hours**; one working eight real hours that night is flagged **60 min early departure**; a spring-forward night pays a full day for seven real hours. Arithmetically correct, internally consistent, **unchosen and undocumented**. In some jurisdictions this is a legal question. | Keep real-elapsed *(current)* · cap scheduled at nominal wall-clock · separate transition-hour allowance · per-tenant policy flag | **Keep the current real-elapsed behaviour and document it explicitly** before onboarding any DST tenant. **Separately: suppress or annotate the fall-back early-departure flag** — it reports something technically true and practically misleading. If wall-clock is wanted, implement it as a **per-tenant flag**, never a global change. | | NO today (India has no DST) — **YES before any DST-observing tenant** |
| **DEC-TZ-15** 🆕 | **What is the offline / deferred-submission attendance policy?** (§11) | **No mobile app exists and offline attendance is unsupported** — yet the schema already anticipates it (`MOBILE`/`DEVICE` sources, `idempotency_key`). An offline punch **breaks both DEC-TZ-01 Option A and Option B**: Option A would stamp the upload time; Option B's ±120s rejects a 4-hour lag. | Not required at all · device clock · **monotonic anchored** · server-receipt-only · + independent choices on lag bound, manipulation controls, conflict resolution and failure visibility | **Answer "is offline required?" first.** If yes, treat it as a **separate permissioned ingestion contract** with its own upload-lag bound — **never** by widening the self-service skew tolerance. Prefer **monotonic anchoring** over a raw device clock. Require an explicit reconciliation surface so a rejected queued punch is visible to the employee. **Build nothing yet.** | | NO today — **YES before any mobile client ships** |
| **DEC-TZ-16** 🆕 | **How early/late may a punch fall and still count?** (§15) | The ±2h pad is a Python **default argument**, never overridden, not configurable, not documented. A 06:45 arrival and 20:30 departure on a `09:00–18:00` shift are **both stored and both orphaned** — the employee shows ABSENT for a 14-hour day, silently. | **A** Keep ±2h + orphan report · **B** Policy-configurable · **C** Derive from shift · **D** Widen default | **A now, without needing approval** (it changes no computed value) — **silence is the real defect, and nobody can judge ±2h while the failure is invisible.** Then **B only if the client confirms the policy differs by site or shift type**, validated against shift length so adjacent windows cannot overlap. **Never D silently** — any pad change alters computed attendance on the next recompute. | | NO — but the **orphan report** is P1 |

⭐ = blocker · 🆕 = raised by this specification

## 17.1 Decision dependency order

```text
DEC-TZ-01  (authoritative clock)  ⭐ BLOCKER — decide first
    ├── DEC-TZ-02  (skew tolerance)          ← only meaningful if client time is permitted
    ├── DEC-TZ-03  (future timestamps)       ← bounded by DEC-TZ-02
    ├── DEC-TZ-04  (naive timestamps)        ← TZ=UTC pin applies regardless of the answer
    ├── DEC-TZ-05  (source assertion)        ← the LINCHPIN: without it the per-path rules are advisory
    └── DEC-TZ-15  (offline attendance)      ← a SECOND contract, not a wider tolerance

DEC-TZ-13  (timezone change guard) ⭐ BLOCKER — independent of DEC-TZ-01, decide in parallel
    └── closes TZ-09 (torn config read) as a side effect

DEC-TZ-06  (rounding)        ── independent · CHANGES COMPUTED ATTENDANCE · needs a communicated recompute
DEC-TZ-07  (night OT window) ── independent · CHANGES OT RATES
DEC-TZ-12  (when to compute) ── needs DEC-TZ-08/09 to settle "whose midnight"
DEC-TZ-08  (display tz)      ── independent · amends LOCKED DEC-010
    └── DEC-TZ-09  (employee timezone)  ← only if multi-timezone is real; amends LOCKED WD-06
DEC-TZ-10  (period-lock basis) ── independent · expect "accept as documented"
DEC-TZ-16  (punch window)      ── independent · orphan report needs no decision

── DST-zone gate: none of these applies to India; all become P1 before a DST tenant ──
DEC-TZ-11  (ambiguous/nonexistent times)
DEC-TZ-14  (DST scheduled minutes / OT)
```

## 17.2 The minimum set to unblock production

If the client can only make a few decisions now, these four are the ones:

| Order | Decision | Why it cannot wait |
|---|---|---|
| 1 | **DEC-TZ-01** (+ **05** in the same change) | Governs whether attendance figures mean anything. Shapes 02, 03, 04, 15. |
| 2 | **DEC-TZ-13** | The guard is one day of work and closes a silent-history-rewrite hole that is already `PAY-013` P0. |
| 3 | **DEC-TZ-04** | Independent of everything, cheap, and closes a 5h30m silent dev/prod divergence. |
| 4 | **DEC-TZ-12** | Without it no attendance is computed at all, so nothing downstream can be verified. |

---

# 18. REMEDIATION BACKLOG

> **Nothing in this backlog is implemented. Nothing may be started before its `Depends On` column is
> satisfied** — several items would produce the *wrong* fix if built before the decision that shapes
> them.

**Risk column:** the risk of *making the change*, not the risk of leaving it.

## P0 — Must fix before production

| ID | Change | Reason | Depends On | Tests Required | Risk |
|---|---|---|---|---|---|
| **R-TZ-01** | Implement `_assert_timezone_change_allowed` — refuse a `Company.timezone` / `Branch.timezone` change when computed `attendance_day` rows exist; permit while `TRIAL` or zero days. **Call it from `update_branch` as well as `update_company`.** | TZ-01 · `PAY-013` · `F-27`. Editing either silently rewrites already-approved historical attendance on the next recompute. The guard's own precondition is met; the branch path has no guard at all. | **DEC-TZ-13** | Matrix E2, E3: change company tz → recompute a historical day → assert **unchanged** (or refused). Same for branch. Assert `update_branch` is guarded. Assert the `TRIAL`/zero-days path still permits the change. | **Low.** One existence query in an existing hook. Reuses the `TRIAL` currency-lock precedent. Fully reversible. |
| **R-TZ-02a** | `AwareDatetime` on `PunchCreate.punch_time` — reject offset-less timestamps with **422**. | TZ-02 · F-07. The same request stores instants 5h30m apart in dev and production. Silent, environment-dependent corruption. | **DEC-TZ-04** | Matrix H3: naive `punch_time` → 422. H1/H2: `Z` and `+04:00` still accepted *(regression guard)*. | **Low.** Schema-level; breaks only clients that were already ambiguous. **Announce to any integration partner first.** |
| **R-TZ-02b** | Pin `ENV TZ=UTC` in `apps/api/Dockerfile` **and** in CI. | TZ-02. Makes dev and production agree regardless of which option DEC-TZ-04 selects. | **None — do this regardless** | The §19 parametrised `TZ` suite (matrix G1–G5). | **Very low.** One line. Zero behavioural cost given PC-01. |
| **R-F-01** | Punch ingestion validation per the DEC-TZ-01 outcome: server-stamp self-service punches, and/or enforce skew (`DEC-TZ-02`), future (`DEC-TZ-03`) and far-past bounds. | F-01, F-02, F-03. Any `ATTENDANCE.PUNCH` holder controls their own payroll inputs through an editable form field. | **DEC-TZ-01, 02, 03** ⛔ **Do not build before the decision — the three options produce different code.** | Matrix H4 (future → reject), H5 (far-past → reject), H8 (skew). Regression: on-behalf and regularization paths still accept historical times. | **Medium.** Changes the self-punch UX and the API contract. **Needs a user-facing communication plan.** |
| **R-F-11** | Server-assign `source` from the authenticated context; reject or ignore a client-supplied value. | F-11 · DEC-TZ-05. **Without this, every per-path rule in R-F-01 is advisory** — a caller asserts a different `source` and takes the permissive branch. | **DEC-TZ-05** · **must ship with R-F-01** | Matrix H6, H7: `source="REGULARIZATION"` / `"DEVICE"` on a self-punch → rejected. Regression: the regularization apply path can still set `REGULARIZATION`. | **Low-medium.** May break an undocumented integration that sets `source`. |
| **R-F-05** | Make `match_breaks` midnight-aware — build the break's UTC span and compare instants (§12.6 Approach B). **Preserve the `UTC → local` conversion order (PC-15).** | F-05 · `R-4`. Night-shift break minutes are silently unpaid: `worked_minutes` ↓ → `paid_day_fraction` ↓ → OT suppressed. Likelihood **certain**, always against the employee. | **None — unambiguous defect** | The 8 tests in §12.7, including the C14 DST regression guard. | **Low.** Pure function, 8 pure tests, no DB. **Changes computed attendance for affected days — recompute deliberately and with notice.** |
| **R-F-14** | Scheduled per-tenant attendance calculation (trailing N ≈ 3 days), scheduled in each tenant's own attendance timezone. | F-14 · `PAY-001` (🔴 P0). Without it no `attendance_day` exists unless an endpoint was called, so a period cannot be finalized and Payroll has no input. | **DEC-TZ-12** (and DEC-TZ-08/09 for "whose midnight") | Job fires in the tenant's zone; trailing window absorbs late punches and approved regularizations; cross-midnight days complete the following morning; idempotent on re-run. | **Medium-high.** The largest item. Interacts with Beat's lack of leader election (`OPS-006`). |

## P1 — Must fix before production / UAT

| ID | Change | Reason | Depends On | Tests Required | Risk |
|---|---|---|---|---|---|
| **R-TZ-04** | Add the DST test suite — matrix group C (8+ scenarios) across `Europe/London` and `America/New_York`, spring-forward and fall-back. | TZ-04. DST is CODE-PROVEN correct (PC-06) and **completely unprotected**. A refactor of `_local_to_utc`, `scheduled_span_utc` or `match_breaks` regresses it silently. | **None** | *This item is the test.* | **None** — tests only. **Highest risk closed per unit of effort in the entire backlog.** |
| **R-TZ-03** | Render attendance times in `attendance_day.timezone` with an explicit label; amend DEC-010's rendering clause to name the WD-06-resolved zone. | TZ-03 · F-08 · `FE-1`. Violates a LOCKED decision. Times and the figures beside them are computed in different zones with no indication. | **DEC-TZ-08** (it amends a LOCKED decision) | Component test: a fixed instant renders in the day's zone, **not the test runner's**. Label present. Day-detail dual-zone rendering. | **Low.** Two formatter functions and their call sites. Data already on the wire. |
| **R-TZ-05** | Declare `tzdata` as a direct dependency; digest-pin `python:3.12-slim`; decide deliberately whether system or PyPI tzdata wins and **verify it in the built image**; assert the loaded version at startup; document a rebuild cadence; build all three service images from one pinned base in one run. | TZ-05. The newer locked tzdata is installed and **shadowed**; the system copy never updates; tzdata is an undeclared transitive dependency. | **None — engineering decision** | Startup assertion test. Container test asserting which tzdata actually resolves. | **Low-medium.** A dependency and image change; **verify resolution order rather than assuming it.** |
| **R-TZ-16a** | **Orphaned-punch report** — punches belonging to no `attendance_day` — surfaced to HR and added to the period-close checklist. | TZ-08 · DEC-TZ-16. A 06:45 arrival and 20:30 departure are both stored and both silently inert; the employee shows ABSENT for a 14-hour day. **Silence is the defect.** | **None — changes no computed value** | Punch outside the ±2h pad appears in the report; punch inside does not. | **Very low.** Read-only report. |
| **R-F-06** | Honour `night_ot_mode` — implement `WINDOW` and `BOTH` using `night_window_start`/`_end`. | F-06 · `ATT-005`. `WINDOW` silently behaves as `BOTH`; a day shift running into the night window never earns the night rate. **Wrong multiplier → wrong money.** | **DEC-TZ-07** | `SHIFT_FLAG` / `WINDOW` / `BOTH` each classify correctly; day shift extending into the window under `WINDOW` → `NIGHT`; cross-midnight under `WINDOW` with OT outside the window → not `NIGHT`. | **Medium.** **Changes OT classification and therefore pay.** Audit affected tenants; recompute with notice. |
| **R-F-04** | Wire `apply_rounding` into evaluation, applied to a **copy** of the punch instant (never mutating the stored punch — WD-11). | F-04 · `ATT-001` · `DEAD-1`. Configurable, validated, UI-exposed, **zero call sites**. An HR user configuring 15-minute rounding gets none. | **DEC-TZ-06** | Rounding applied for each mode; **raw `punch.punch_time` unchanged in the DB** *(WD-11 guard)*; `NONE` is a no-op. | **Medium.** **Changes computed attendance for every tenant with a value set.** Audit first; recompute deliberately. |
| **R-TZ-06** | `business_today()` helper resolving through the WD-06 chain; replace `date.today()` at 4 sites and the UTC-month boundary at `leave/service.py:1990`. | TZ-06 · F-10 · `DAT-004` · `DAT-005`. Contradicts DEC-010's *"never server-local time"*; boundaries move between dev and production. | **None** | Regularization future-date and backdating boundaries under `TZ=UTC` and `TZ=Asia/Kolkata` → identical. `max_requests_per_month` counts by company-tz month. | **Low.** Behaviour-preserving where server tz == company tz. |
| **R-TZ-07** | Return the company timezone in the session/bootstrap payload; make `todayIso()` take it. **Ship with R-TZ-03.** | TZ-07 · F-09. Default filters off by one day for IST users between 00:00 and 05:30. | **None** | `todayIso()` under a mocked UTC clock at 02:00 IST returns the IST date. | **Very low.** Display only. |

## P2 — Important hardening

| ID | Change | Reason | Depends On | Tests Required | Risk |
|---|---|---|---|---|---|
| **R-TZ-09** | Close the torn configuration read — primarily via **R-TZ-01**'s guard; `REPEATABLE READ` for the calculation transaction **only with retry handling** if the mutable-config surface grows. | TZ-09. One `attendance_day` can mix pre- and post-change configuration, silently, violating WD-11. | **R-TZ-01** | §16.6 test 1 *(integration, two sessions)*. | **Low** via the guard. **Medium** if isolation is changed — serialization failures need retry handling. |
| **R-F-15** | `SELECT … FOR UPDATE` on `attendance_day` during recompute. | F-15. `UNIQUE` prevents duplicate rows, not last-writer-wins. Orthogonal to R-TZ-09 — **both are needed for completeness.** | **None** | §16.6 test 2 *(integration)*. | **Low-medium.** Lock-ordering review needed to avoid deadlocks with the period-lock path. |
| **R-F-18** | Write `punch.raw_payload` — submitted offset, user-agent, client version, device id, IP. | F-18. The column is declared and never written. **Any bounded-skew or flag-and-review posture has nothing to review without it.** | **DEC-TZ-01** (shapes what to capture) | Payload persisted and redacted per `PII-2`. | **Low.** **Coordinate with the PII retention policy — this captures identifying data.** |
| **R-F-12** | Validate regularization `requested_time` against the attendance date and shift bounds. | F-12. Unvalidated; currently harmless only because TZ-08's pad makes it inert — **an accident, not a control.** | **None** | Out-of-window `requested_time` → 422. In-window → accepted. | **Low.** |
| **R-TZ-12** | Roll the `end <= start` fallback day in **local** time, not UTC. | TZ-12 · F-16. Latent: a shift omitting `is_cross_midnight` *and* spanning a DST transition is off by the offset delta. | **None** | Matrix B12 across a DST transition. | **Very low.** Defensive path only; `is_cross_midnight` is the real path. |
| **R-TZ-14** | Document the clock-synchronisation requirement, expected drift tolerance and failure behaviour; add NTP/chrony to the deployment manifest. **Conditional on DEC-TZ-01 = A or B.** | TZ-14. Harmless while `created_at` is advisory; **load-bearing the moment the server clock validates or stamps punches.** | **DEC-TZ-01** · `OPS-001` (no deployment config exists at all) | Startup check comparing the app clock to the DB clock; alert beyond a threshold. | **Low.** Documentation + deployment config. |
| **R-F-19** | Enforce `Branch.geofence_radius_m` on the punch path, or withdraw the field and its UI. | F-19. Stored, editable, read by nothing — the same silent-no-op pattern as F-04 and F-06. | **Product decision** (same shape as DEC-TZ-06) | Punch outside the radius rejected or flagged; inside accepted. | **Medium** if enforced — needs GPS capture, a privacy review, and an indoor-accuracy tolerance. |
| **R-TZ-16b** | Make the punch pad policy-configurable on `AttendancePolicyVersion`, **validated against shift length** so adjacent windows cannot overlap. **Only if DEC-TZ-16 requires it.** | TZ-08. The pad encodes an unstated attendance policy in a default argument. | **DEC-TZ-16** | Configured pad honoured; overlap validation rejects an over-wide pad; default `2` preserves current behaviour. | **Medium.** **Widening the pad changes computed attendance on any subsequent recompute.** |
| **R-SB-01** | Add `crosses_midnight` to `shift_break`, so the roll is **declared** rather than inferred — matching `shift_version` and `shift_duty_block`. | Structural root cause of F-05 (§12.2). | **R-F-05** *(ship the logic first)* | Migration + backfill; declared flag honoured. | **Low.** Additive column. |

## P3 — Documentation / future improvement

| ID | Change | Reason | Depends On | Tests Required | Risk |
|---|---|---|---|---|---|
| **R-TZ-13** | Rename `app_timezone_default` → `celery_timezone`, or document its Celery-only scope at the definition. | TZ-13 · F-13. Reads like an application-wide timezone; no attendance code reads it. **Invites a wrong "fix" later.** | None | Existing Celery config tests. | Very low. |
| **R-TZ-11** | Record `fold=0` as stated policy; warn at shift-publish time when a configured `TIME` falls in a DST transition window. | TZ-11 · F-17 · DEC-TZ-11. A shift configured for 02:30 on a spring-forward date silently starts at 03:30. | **DEC-TZ-11** | Publish a shift with a nonexistent local time → warning naming the resolved instant. Ambiguous → warning, never rejected. | Low. Warning only; no resolution change. |
| **R-DOC-01** | Update `ATTENDANCE_MASTER_RULE_MATRIX.md` **C3**: *"Presumed yes (stdlib)"* → *"CODE-PROVEN 2026-09-15 across four real transitions; no automated test (TZ-04)"*. | §3.3. The matrix understates what is known. | **None** | n/a | None. |
| **R-DOC-02** | Re-rate `TECHNICAL_DEBT_REGISTER.md` **TZ-1** from 🟢 P4 to 🟠 P1; re-rate **FE-1** to 🟠 P1. | §3.3. Both were rated on reasoning that no longer holds. | **None** | n/a | None. |
| **R-DOC-03** | Document client-facing: the ±2h punch pad (TZ-08), the WD-30 UTC period-lock basis and its month-boundary rejection (DEC-TZ-10), and the punch-UTC / day-local list-filter split (F-20). | §4.6. Each is correct and each will be reported as a bug by someone who was not told. | **DEC-TZ-10, 16** | n/a | None. |
| **R-DOC-04** | Record the DST/OT policy (DEC-TZ-14) in the rule matrix beside C3, whichever way it is decided. | §7.5. So that "540 minutes" in a fixture is legibly a **choice**. | **DEC-TZ-14** | n/a | None. |
| **R-LINT-01** | Lint rule banning `datetime.utcnow()` and bare `date.today()` in `modules/`. | PC-13 · TZ-06. The codebase currently has **zero** `utcnow()` occurrences — protect that. | **R-TZ-06** *(so existing sites pass)* | CI catches a reintroduction. | Very low. |

## 18.1 Sequencing

```text
── Decisions first ──────────────────────────────────────────────────────
   DEC-TZ-01 (+05, 02, 03, 04) and DEC-TZ-13 in parallel.
   Nothing in the F-01 / F-11 family may be coded before DEC-TZ-01 lands.

── Week 1 · no decision needed, high value ──────────────────────────────
   R-TZ-04   DST test suite            ← highest risk closed per unit of effort
   R-TZ-02b  TZ=UTC pin
   R-F-05    cross-midnight breaks     ← unambiguous defect, 8 pure tests
   R-TZ-16a  orphaned-punch report     ← turns a silent failure visible
   R-DOC-01/02  doc corrections

── Week 2 · needs DEC-TZ-13 ─────────────────────────────────────────────
   R-TZ-01   timezone-change guard     ← ~1 day; also closes R-TZ-09
   R-TZ-06 + R-TZ-07 + R-TZ-03         ← one "business today / company tz on the wire" change

── Week 3+ · needs DEC-TZ-01 ────────────────────────────────────────────
   R-F-01 + R-F-11 together            ← source assignment is the linchpin
   R-F-18                              ← the evidence R-F-01 needs
   R-TZ-14                             ← only if DEC-TZ-01 = A or B

── Parallel track ───────────────────────────────────────────────────────
   R-F-14 (scheduled calculation)      ← largest item; overlaps PAY-001
   R-TZ-05 (tzdata + image pinning)    ← infrastructure, independent
```

**Note:** `TST-001` in the debt register — CI provisions no PostgreSQL, so **783 integration tests never
run as a merge gate** — is not a timezone finding, but every integration test in §19 is worthless until
it is fixed. **It is the true week-1 prerequisite for this entire backlog.**

---

# 19. TEST PLAN

**No tests are written by this document.** This is the specification for tests that must exist.

**Current coverage: 4 of 68 timezone-relevant scenarios have an automated test.** 46 are *code-proven by
the audit* — which is not the same thing, because an audit does not run in CI.

**The engine is a pure function (PC-12)**, so tiers 1–3 below need **no database**. That is what makes
this plan cheap relative to the risk it closes.

## 19.1 Test tiers, by cost

| Tier | Needs | Matrix groups | Scenarios | Cost |
|---|---|---|---|---|
| **1 — Pure unit** | Nothing | A, B, C, D, I | ~45 | **Low.** Milliseconds each. |
| **2 — Schema** | Pydantic only | H | 6 | **Low.** |
| **3 — Process-env** | `TZ` env var per case | G | 5 | **Low.** One parametrised module. |
| **4 — Integration** | PostgreSQL | E, F | 11 | **Medium.** Blocked on `TST-001`. |
| **5 — Concurrency** | PostgreSQL + 2 sessions | J | 3 | **High.** |

## 19.2 Timezone matrix

Every evaluation test runs against this set. Today the suite uses `Asia/Kolkata` and `UTC` for
evaluation, and `America/New_York` / `Europe/London` **only** as arguments to the precedence test.

| Zone | Offset | DST? | Why it is in the set |
|---|---|---|---|
| `UTC` | +00:00 | No | Control; the degenerate case where local == UTC |
| `Asia/Kolkata` | +05:30 | No | **Every current tenant.** The `:30` offset catches half-hour bugs |
| `Asia/Dubai` | +04:00 | No | Multi-branch scenarios against an IST company |
| `Europe/London` | +00:00 / +01:00 | **Yes** | DST where standard time **is** UTC — catches "UTC and local are the same" assumptions |
| `America/New_York` | −05:00 / −04:00 | **Yes** | **Negative** offset + DST; transitions on different dates from London |
| `Pacific/Kiritimati` | **+14:00** | No | The extreme. **The entire local working day falls on the previous UTC date** — the strongest proof that `attendance_date` is never derived from a UTC date |

## 19.3 Boundaries

| Boundary | Scenarios | Assert | Tier |
|---|---|---|---|
| **Midnight** | Cross-midnight shift, punch at 23:59 / 00:00 / 00:01 local | All three own the **shift start date** (matrix B4–B6) | 1 |
| **Month-end** | Punch at 05:00 IST on 1 Oct with September `CLOSED` | Lock check uses the **UTC** date → rejected (matrix F2, WD-30). **Assert the documented behaviour, so a future change is deliberate** | 4 |
| **Month-end, no divergence** | Punch at 23:00 IST on 30 Sep | Does **not** diverge (matrix F5) — the exposure is early-morning, not late-evening | 4 |
| **Year-end** | 31 Dec → 1 Jan across a cross-midnight shift, in `Pacific/Kiritimati` and `America/New_York` | Attendance date is the shift start date; no year rollover artefact | 1 |
| **Holiday** | Holiday on the local date; punch whose **UTC** date is the previous day (IST 05:00) | Holiday matched on the **local** attendance date (PC-07) | 4 |
| **Weekly-off** | Same shape; plus `holiday_on_weekly_off` and `operates_on_weekly_off` | Matched on the local date (PC-08) | 4 |
| **Leave** | `LeaveDayProjection` on the local date; cross-midnight shift starting that date | Overlay applies to the shift start date (PC-09) | 4 |
| **Punch-window edges** | 06:59 / **07:00** / **20:00** / 20:01 local, day shift | Orphan / owned / owned / orphan (matrix A4, A5, A9, A10). **Freezes the ±2h pad so changing it is a conscious act** | 1 |
| **Cross-midnight window edges** | 19:59 / **20:00** / **08:00** / 08:01 local | Orphan / owned / owned / orphan (matrix B1, B2, B8, B9) | 1 |
| **UTC+14 date inversion** | `Pacific/Kiritimati`, 09:00 local shift | `scheduled_start` is the **previous UTC date** (matrix D5) | 1 |

## 19.4 Shifts

| Shift type | Scenarios | Assert | Tier |
|---|---|---|---|
| **Normal day** | `09:00–18:00`, all 6 zones | `scheduled_start`/`_end` correct per zone; late/early/worked correct | 1 |
| **Cross-midnight** | `22:00–06:00`, `23:00–07:00`, `18:00–02:00` | Attendance date = **start** date; span correct; midnight does not move the day (matrix B10–B12) | 1 |
| **DST spring-forward** | `22:00–06:00` on 2026-03-07/08 (`America/New_York`) and 2026-03-28/29 (`Europe/London`) | Scheduled span = **420** real minutes, not 480 (matrix C1, C3, C8) | 1 |
| **DST fall-back** | Same shifts on 2026-10-31/11-01 and 2026-10-24/25 | Scheduled span = **540** real minutes (matrix C2, C4) | 1 |
| **DST control** | `Asia/Kolkata`, same dates | **480**, unchanged (matrix C5) | 1 |
| **DST full evaluation** | `evaluate_day` across the London fall-back night: (a) full wall-clock shift, (b) 8 real hours | (a) worked 540, late 0, early 0, `PRESENT`; (b) worked 480, **early 60** (matrix C6, C7) | 1 |
| **DST day-shift** | `09:00–18:00` on a transition date | Span correct; **late/early unaffected** | 1 |
| **Flexible / split** | Cross-midnight and DST dates | Window math consistent with FIXED; split blocks attribute to the right date | 1 |
| **`end <= start` fallback** | `is_cross_midnight=False`, `end < start`, across a DST transition | Currently rolls in UTC (TZ-12) — **assert whichever behaviour is chosen** after R-TZ-12 | 1 |

## 19.5 Input validation

All tier 2, against the shipped `PunchCreate`.

| # | Input | Current | Required after R-TZ-02a / R-F-01 |
|---|---|---|---|
| 1 | `"2026-09-15T09:00:00Z"` | accepted | accepted *(regression guard)* |
| 2 | `"2026-09-15T09:00:00+04:00"` | accepted, offset preserved | accepted *(regression guard)* |
| 3 | `"2026-09-15T09:00:00+05:30"` | accepted | accepted — **half-hour offset preserved exactly** |
| 4 | `"2026-09-15T09:00:00-05:00"` | accepted | accepted — **negative offset** |
| 5 | `"2026-09-15T09:00:00"` **naive** | **accepted**, coerced by process OS tz | **422** |
| 6 | `"2099-01-01T00:00:00Z"` **future** | **accepted** | **422** (per DEC-TZ-03) |
| 7 | `"1900-01-01T00:00:00Z"` **far past** | **accepted** | **422** (before employment start) |
| 8 | 90s ahead of server time | **accepted**, never compared | per DEC-TZ-02 tolerance |
| 9 | 90s **behind** server time | accepted | accepted — within tolerance |
| 10 | `source="REGULARIZATION"` on a self-punch | **accepted** | **422** — server-assigned (DEC-TZ-05) |
| 11 | `source="DEVICE"` on a web self-punch | **accepted** | **422** — server-assigned |
| 12 | `"2026-09-15T09:00:00 Asia/Kolkata"` | rejected (not ISO) | **422** *(regression guard — §10.2)* |

## 19.6 Configuration change and recompute

Tier 4 — needs a database.

| # | Scenario | Assert | Matrix |
|---|---|---|---|
| 1 | **Company timezone** changed after a day is computed → recompute | **Refused** by the guard (or unchanged, per DEC-TZ-13) — **never silently re-anchored** | E3 |
| 2 | **Branch timezone** changed → recompute | Same. **`update_branch` must be guarded** — today it is not | E2 |
| 3 | **Shift timezone** changed (new `ShiftVersion`) → recompute historical | **Unchanged** — old version resolved as-of the date *(PC-10 regression guard)* | E1 |
| 4 | **Employee transfers branch** → recompute historical | **Unchanged** — assignment resolved as-of the date *(PC-11 regression guard)* | E4 |
| 5 | Timezone change while the company is `TRIAL` / zero computed days | **Permitted** — the escape hatch works | — |
| 6 | Timezone change while any affected period is `CLOSED` | **Refused** under every option | — |
| 7 | Recompute after a backdated policy publish | Uses the version effective for the date, not the newest (WD-11) | — |

## 19.7 Server-timezone independence

Tier 3 — **one parametrised module**, `TZ` set per case.

| # | Under `TZ` ∈ {`UTC`, `Asia/Kolkata`, `America/New_York`, `Pacific/Kiritimati`} | Assert | Matrix |
|---|---|---|---|
| 1 | Day-shift `evaluate_day` | `PRESENT` / late 2 / early 0 / worked 533 / paid 1.00 — **identical in all four** | G1 |
| 2 | Night-shift `evaluate_day` | `PRESENT` / late 0 / worked 480 / paid 1.00 — **identical** | G2 |
| 3 | `scheduled_span_utc` × 5 zones | **Identical** | G3 |
| 4 | DST spans × 4 transitions | **Identical** | G4 |
| 5 | Naive-datetime ingestion | **Rejected in all four** — closing the one divergence (G5) | G5 |

> This module is the regression guard for **PC-01**, the audit's central positive finding. It is cheap
> and it protects the property everything else rests on.

## 19.8 Breaks

Tier 1. The eight tests in §12.7, plus:

| # | Scenario | Assert | Matrix |
|---|---|---|---|
| 9 | Gap at ambiguous 01:10 local vs break `01:00–01:30`, London fall-back | `matched=True, paid=True` — **PC-15 regression guard** | C14 |
| 10 | Excess break across midnight, `max_minutes` exceeded | `is_excess=True` — **closes the one UNTESTED break scenario** | I4 |

## 19.9 Concurrency

Tier 5 — highest cost, correctly sequenced last. **Blocked on `TST-001`.**

| # | Scenario | Assert | Matrix |
|---|---|---|---|
| 1 | Timezone `UPDATE` commits between two SELECTs in one `_build_calculation_input` | Guard refuses the update, **or** the calculation is internally consistent — never a torn read | J2 |
| 2 | Two concurrent `calculate()` for one employee-date | Deterministic result; no lost update; no duplicate row | J3 |
| 3 | Connection-pool reuse across requests | No leaked session state (`SET TIME ZONE`, `SET SESSION …`) between requests on a recycled connection | — |
| 4 | Isolation level assertion | `SHOW default_transaction_isolation` is what the code expects — **fails loudly if a deploy changes it** | J1 |

## 19.10 Implementation order

| Priority | Group | Tests | Cost | Closes |
|---|---|---|---|---|
| **1** | **DST** (§19.4) | 8 | Low — pure | **TZ-04.** Protects PC-06, the audit's central positive finding |
| **2** | **Input validation** (§19.5) | 12 | Low — schema | TZ-02, F-01, F-03, F-11 |
| **3** | **Breaks** (§19.8) | 10 | Low — pure | **F-05** + PC-15 guard + matrix I4 |
| **4** | **Server TZ** (§19.7) | 1 parametrised | Low — env | **Locks in PC-01** |
| **5** | **Boundaries** (§19.3) | ~20 parametrised | Low — pure | TZ-08; **freezes the ±2h pad** |
| **6** | **Config change** (§19.6) | 7 | Medium — DB | **TZ-01**, the P0 |
| **7** | **Period lock** (§19.3 month-end) | 5 | Medium — DB | Month-end integrity |
| **8** | **Concurrency** (§19.9) | 4 | High — DB + sessions | TZ-09, F-15 |

> **Priorities 1–5 need no database and no fixtures.** A single parametrised test file covering them
> moves **36 of the 46 code-proven-but-unprotected scenarios into test-proven.** That is the best
> risk-per-hour available anywhere in this document.

---

# 20. FINAL ARCHITECTURAL VERDICT

## 20.1 The six answers

| # | Question | Verdict |
|---|---|---|
| 1 | **Is the timezone calculation engine fundamentally sound?** | # **YES** |
| 2 | **Is timestamp ingestion secure?** | # **NO** |
| 3 | **Is historical attendance protected?** | # **NO** |
| 4 | **Is UI timezone behaviour compliant with approved architecture?** | # **NO** |
| 5 | **Is DST production-safe?** | # **NOT PROVEN** |
| 6 | **Is the timezone subsystem production-ready?** | # **READY WITH CONDITIONS** |

---

### 1 — Is the timezone calculation engine fundamentally sound? · **YES**

**Not "probably", and not on the strength of `zoneinfo`'s reputation.** It was executed under four
server timezones spanning UTC−4 to UTC+14 and produced **byte-identical** output for day shifts,
cross-midnight shifts, every scheduled span and every DST span.

The soundness has a single structural cause. `_local_to_utc` is the **one** conversion point in the
engine:

```python
def _local_to_utc(local_date: date, local_time: time, tz: ZoneInfo) -> datetime:
    return datetime.combine(local_date, local_time, tzinfo=tz).astimezone(UTC)
```

`tzinfo=tz` is supplied **explicitly** from the resolved IANA identifier, so `datetime.combine` never
consults the process timezone; every downstream comparison is UTC-aware minus UTC-aware. The engine is
a pure function of `(punches, shift, policy, IANA string)` — which is *why* this audit could prove its
behaviour by execution instead of by reading it.

Around that core: `TIMESTAMPTZ` everywhere with no naive timestamp column in the schema; zero
occurrences of `datetime.utcnow()`; IANA identifiers exclusively, validated at the schema layer; a
timezone chain that cannot fail open because `company.timezone` is `NOT NULL DEFAULT`; cross-midnight
attribution driven by an explicit flag rather than inferred; and holiday, weekly-off and leave all keyed
on the local attendance date.

**Nothing in this document asks for the engine to be redesigned.** Every P0 and P1 item is at the
boundaries — ingestion, configuration mutability, rendering, packaging — or is a test. That distinction
is the most important single fact in this report: **the hard part is right.**

### 2 — Is timestamp ingestion secure? · **NO**

Not "not proven" — **no**. Four findings, one risk:

- The client's clock is authoritative and is **never compared** to the server's, though the server
  computes its own instant sixteen lines earlier and stores it in `created_at` (**F-01**).
- The only shipped client exposes the timestamp as an **editable form field** (**F-02**). No
  manipulation is required — typing is the attack.
- **No future bound at any layer** — `2099-01-01T00:00:00Z` is accepted (**F-03**) — while the
  regularization path *does* reject future dates, an asymmetry that looks unintentional.
- `source` is client-settable, so a hand-typed web punch can be labelled a biometric device reading
  (**F-11**) — forging the exact field an investigator would rely on.

Any holder of the baseline `ATTENDANCE.PUNCH` permission therefore controls their own `late_minutes`,
`worked_minutes`, `ot_minutes_detected`, `paid_day_fraction` and `lop_fraction`. Risk `R-1`'s likelihood
is **certain**, because it is a supported UI affordance rather than an exploit.

**The honest framing:** this is a **specification gap that happens to be exploitable**, not a
regression. The repository is silent on which clock is authoritative — and that silence is conspicuous
in a decision log that otherwise records rejected alternatives for WD-06, WD-11, WD-26 and
WD-28…WD-32. It reads as a question never asked. **DEC-TZ-01 is the blocker.**

### 3 — Is historical attendance protected? · **NO**

Protected against **policy** edits: yes, and by design. Every version FK used is stored on
`attendance_day` alongside a `computation_snapshot` (WD-11). Shift timezone edits are safe because
`ShiftVersion` is effective-dated. Branch *transfers* are safe because assignments resolve as-of the
date.

**Timezone is the one calculation input that escaped that design.** `Branch.timezone` and
`Company.timezone` are single mutable columns; `recompute()` passes only `(employee_id,
attendance_date)` and re-resolves the zone from the **current** rows; and `attendance_day.timezone` —
which records the zone the day was computed in — is read in exactly one place, to populate an API
response. **It is write-only provenance and never an input.**

The guard written to prevent precisely this is an **empty stub** whose own docstring defers it *"until
Payroll/Attendance modules exist"* — a precondition that has been met — and `update_branch` does not
call it at all. A company-timezone edit followed by any routine recompute can flip a day from `PRESENT`
to **264 minutes of early departure**.

The row does not change *spontaneously*. It changes the next time anyone approves a regularization,
re-detects OT, publishes a backdated policy, or clicks Recompute. **That is not protection; it is a
timing accident.**

### 4 — Is UI timezone behaviour compliant with approved architecture? · **NO**

`DEC-010` is **LOCKED** and states that `company.timezone` is the single source of truth for rendering.
`format.ts:16,21` pass `undefined` to `toLocaleTimeString`/`toLocaleString`, taking both locale **and
zone** from the viewer's browser. Two of DEC-010's three clauses are implemented; the rendering clause
is not.

Two qualifications that matter for how it should be fixed:

- **It is known, not hidden** — already logged as `FE-1`.
- **Literal compliance would be a second bug.** WD-06 superseded `company.timezone` for *computation*;
  rendering a Dubai-branch day in the Kerala company's zone would show times in a zone the figures were
  not computed in. The fix must follow the WD-06 chain, which means **amending the locked decision** —
  and that is the client's call, not engineering's.

Impact is currently zero-visible, because every user is in one zone. It becomes visible on the **first
day of a multi-location rollout** — the worst possible moment for a display bug, because it will be read
as a correctness bug in an engine that is actually right.

### 5 — Is DST production-safe? · **NOT PROVEN**

**Correct: proven. Safe: not proven.** The two are different and the distinction is the whole answer.

*Correct* — this audit executed the shipped code across four real transitions. A `22:00→06:00` shift
spans **540 real minutes** on a fall-back night and **420** on a spring-forward night in both
`Europe/London` and `America/New_York`, with `Asia/Kolkata` at 480 as a control. Scheduled spans, worked
minutes, late, early, OT, cross-midnight and break matching are all right. This **upgrades every
repository document that called DST *"presumed yes (stdlib)"*** to CODE-PROVEN.

*Not safe*, for three independent reasons:

1. **Zero automated tests touch a DST date** (TZ-04). The proof lives in an audit, not in CI. A
   refactor of `_local_to_utc`, `scheduled_span_utc` or `match_breaks` regresses it silently tomorrow.
2. **The tzdata that actually resolves is the frozen system copy (2026b)**, shadowing the newer locked
   PyPI copy (2026.3) that the lockfile installs, with no update path and no declared dependency
   (TZ-05). Correct arithmetic over stale rules is still the wrong answer.
3. **The pay consequences are undecided** (TZ-10 / DEC-TZ-14). Nine real hours worked for zero
   overtime, and a 60-minute early-departure flag for an employee who worked their normal real hours,
   are *arithmetically correct outcomes nobody chose*.

**Dormant for India** — no DST, stable offset since 1945. Every one of these becomes live and P1 the day
a DST-observing tenant is onboarded.

### 6 — Is the timezone subsystem production-ready? · **READY WITH CONDITIONS**

**For the timezone dimension specifically.** The companion ingestion audit rates the system HIGH RISK
overall on the authoritative-clock question, and **this verdict does not override that.**

**Conditions, in order:**

| # | Condition | Item |
|---|---|---|
| 1 | Decide **DEC-TZ-01** and implement the punch-ingestion boundary, **with server-assigned `source` in the same change** | R-F-01 + R-F-11 |
| 2 | Decide **DEC-TZ-13**; implement the timezone-change guard and **call it from `update_branch`** | R-TZ-01 |
| 3 | Reject naive timestamps; pin `TZ=UTC` in the Dockerfile and CI | R-TZ-02a + R-TZ-02b |
| 4 | Fix cross-midnight break matching | R-F-05 |
| 5 | Add the DST test suite, the input-validation suite, and the server-TZ parametrised module | R-TZ-04 + §19 priorities 1–4 |
| 6 | Decide **DEC-TZ-12** and schedule attendance calculation — **without it, attendance is invisible until someone asks for it** | R-F-14 |

**Additionally, before any non-`Asia/Kolkata` tenant:** DEC-TZ-11, DEC-TZ-14, R-TZ-05 (tzdata) and
R-TZ-03 (display timezone) all move to blocking.

---

## 20.2 The closing question

> **If an employee in India, an employee in Dubai and an employee in London all punch at exactly the
> same real-world instant, will the HRMS calculate each employee's attendance correctly according to
> their applicable shift/branch/company timezone, regardless of where the API server is physically
> located?**

# YES — with two stated conditions.

**CODE-PROVEN.** One real instant, `2026-09-15T04:00:00Z`, three employees each on an `09:00` local
shift:

| Employee | Branch timezone | Local wall time | Their 09:00 in UTC | Result |
|---|---|---|---|---|
| India | `Asia/Kolkata` | 2026-09-15 **09:30 IST** | `03:30Z` | **30 min late** |
| Dubai | `Asia/Dubai` | 2026-09-15 **08:00 +04** | `05:00Z` | **60 min early** |
| London | `Europe/London` | 2026-09-15 **05:00 BST** | `08:00Z` | **240 min early** |

Three different, correct answers from one instant — each judged against its own zone's schedule. The
London row also proves DST is applied: `05:00 BST` is UTC+1, not UTC. And the server's location is
irrelevant: the same computation under four server timezones produced byte-identical output.

**The two conditions:**

1. **Every submitted timestamp must carry an explicit UTC offset.** An offset-less `punch_time`
   resolves against the server's OS timezone — the one path where server location changes the answer
   (TZ-02).
2. **Nobody may edit a branch or company timezone after attendance exists.** Those values are not
   effective-dated and `recompute` re-resolves from the current row, so an edit silently rewrites
   history (TZ-01).

**Both conditions are currently enforced by nothing but convention.**

### The caveat that must be stated plainly

This answer is about the **conversion** being right. It says **nothing** about the **timestamp** being
right.

If all three employees typed their own punch times into an editable form — which is exactly what the
shipped UI offers — the system will convert three self-declared numbers with complete timezone
correctness.

> **The timezone subsystem is a well-built instrument reading an untrusted input.** Fixing the input is
> `DEC-TZ-01`. Protecting the instrument's history is `DEC-TZ-13`. **Neither requires rebuilding the
> instrument, and this document recommends that nobody try.**

---

*Specification prepared 2026-09-15 from the three completed audits. **No application code, database
schema, migration, test, or configuration was modified.** Every source citation was re-verified against
the working tree on this date. Claims labelled CODE-PROVEN were reproduced during the source audits by
executing the shipped code read-only, by querying the running dev Postgres, or by running the actual
`python:3.12-slim` base image. Recommendations marked **AI RECOMMENDATION** are the author's opinion and
carry no authority — they exist so each decision has a starting point, not so it can be skipped.*
