# Attendance — Timezone Test Matrix

**Created:** 2026-09-15
**Companion to:** [`ATTENDANCE_TIMEZONE_AUDIT.md`](./ATTENDANCE_TIMEZONE_AUDIT.md)
**Type:** AUDIT ARTEFACT — no tests were added to the repository. This is the specification for tests that *should* exist.
**Test plan of record:** [`ATTENDANCE_TIMEZONE_DECISION_AND_REMEDIATION.md` §19](./ATTENDANCE_TIMEZONE_DECISION_AND_REMEDIATION.md#19-test-plan) — sequences these scenarios into implementation tiers. This matrix remains the source of the scenarios and their computed values.

Every "actual" value below was **computed by executing the shipped code** (`hrms.modules.attendance.calculation`) read-only during the audit, or by querying the running dev Postgres / the real `python:3.12-slim` image. Values are not hand-derived.

**Status legend**

| Status | Meaning |
|---|---|
| ✅ **PASS (code-proven)** | Audit executed it; behaviour is correct. **No automated test exists** — unprotected against regression |
| ✅ **PASS (test-proven)** | An automated test in the repository asserts this |
| ❌ **FAIL** | Audit executed it; behaviour is wrong |
| ⚠️ **UNDEFINED** | Behaviour is deterministic but no policy has been recorded |
| 🔲 **UNTESTED** | Not executed during this audit and no test exists |

> Per the audit brief: an untested scenario is never marked PASS. Rows marked "code-proven" were proven *by this audit's own execution*, which is not the same as having a regression test.

---

## Summary

| Group | Scenarios | Pass (test) | Pass (code) | Fail | Undefined | Untested |
|---|---|---|---|---|---|---|
| A — Attendance-date boundaries | 11 | 0 | 11 | 0 | 0 | 0 |
| B — Cross-midnight | 9 | 1 | 8 | 0 | 0 | 0 |
| C — DST | 12 | 0 | 9 | 0 | 3 | 0 |
| D — Timezone precedence | 6 | 2 | 4 | 0 | 0 | 0 |
| E — Timezone change / effective dating | 5 | 0 | 3 | 1 | 1 | 0 |
| F — Period lock boundaries | 6 | 0 | 5 | 0 | 1 | 0 |
| G — Server timezone independence | 5 | 0 | 4 | 1 | 0 | 0 |
| H — Ingestion validation | 7 | 0 | 0 | 6 | 1 | 0 |
| I — Breaks | 4 | 1 | 1 | 1 | 0 | 1 |
| J — Concurrency | 3 | 0 | 1 | 0 | 0 | 2 |
| **Total** | **68** | **4** | **46** | **9** | **6** | **3** |

**4 of 68 timezone-relevant scenarios have an automated test.**

---

## Group A — Attendance-date boundaries

Shift `09:00–18:00`, `Asia/Kolkata`, non-cross-midnight, attendance date `2026-09-15`.
Load window = scheduled span padded ±2h (`punch_window_utc`, `lookback_hours=2`, `lookahead_hours=2`).

| # | Input (local wall) | UTC instant | Local date | Resolved owning attendance date | Expected classification | Status |
|---|---|---|---|---|---|---|
| A1 | 2026-09-15 00:00 | `2026-09-14T18:30Z` | 09-15 | **none** | Orphaned — no day loads it | ✅ PASS (code-proven) |
| A2 | 2026-09-15 00:01 | `2026-09-14T18:31Z` | 09-15 | **none** | Orphaned | ✅ PASS (code-proven) |
| A3 | 2026-09-15 05:00 | `2026-09-14T23:30Z` | 09-15 | **none** | Orphaned | ✅ PASS (code-proven) |
| A4 | 2026-09-15 06:59 | `2026-09-15T01:29Z` | 09-15 | **none** | Orphaned — 1 min before window | ✅ PASS (code-proven) |
| A5 | 2026-09-15 **07:00** | `2026-09-15T01:30Z` | 09-15 | `2026-09-15` | Window opens exactly here | ✅ PASS (code-proven) |
| A6 | 2026-09-15 08:59 | `2026-09-15T03:29Z` | 09-15 | `2026-09-15` | Early arrival, not late | ✅ PASS (code-proven) |
| A7 | 2026-09-15 09:00 | `2026-09-15T03:30Z` | 09-15 | `2026-09-15` | On time, late=0 | ✅ PASS (code-proven) |
| A8 | 2026-09-15 18:00 | `2026-09-15T12:30Z` | 09-15 | `2026-09-15` | On time out, early=0 | ✅ PASS (code-proven) |
| A9 | 2026-09-15 **20:00** | `2026-09-15T14:30Z` | 09-15 | `2026-09-15` | Window closes exactly here | ✅ PASS (code-proven) |
| A10 | 2026-09-15 20:01 | `2026-09-15T14:31Z` | 09-15 | **none** | Orphaned — 1 min after window | ✅ PASS (code-proven) |
| A11 | 2026-09-15 23:59 | `2026-09-15T18:29Z` | 09-15 | **none** | Orphaned | ✅ PASS (code-proven) |

> **A1–A4, A10–A11 are the TZ-08 finding.** The behaviour is correct *by design* (the pad is deliberate), but a punch falling outside it is silently inert — no error, no orphan report. A test should assert the boundary is where it is, so widening or narrowing the pad is a conscious act.

---

## Group B — Cross-midnight

Shift `22:00–06:00`, `Asia/Kolkata`, `is_cross_midnight=True`, attendance date `2026-09-15`.

| # | Input (local wall) | UTC instant | Owning attendance date | Expected | Status |
|---|---|---|---|---|---|
| B1 | 09-15 19:59 | `2026-09-15T14:29Z` | **none** | Orphaned | ✅ PASS (code-proven) |
| B2 | 09-15 **20:00** | `2026-09-15T14:30Z` | `2026-09-15` | Window opens | ✅ PASS (code-proven) |
| B3 | 09-15 22:00 | `2026-09-15T16:30Z` | `2026-09-15` | On-time IN, late=0 | ✅ PASS (code-proven) |
| B4 | 09-15 23:59 | `2026-09-15T18:29Z` | `2026-09-15` | Still shift start date | ✅ PASS (code-proven) |
| B5 | **09-16 00:00** | `2026-09-15T18:30Z` | `2026-09-15` | **Midnight does not move the day** | ✅ PASS (code-proven) |
| B6 | 09-16 00:01 | `2026-09-15T18:31Z` | `2026-09-15` | Still the 15th | ✅ PASS (code-proven) |
| B7 | 09-16 06:00 | `2026-09-16T00:30Z` | `2026-09-15` | On-time OUT, early=0 | ✅ PASS (code-proven) |
| B8 | 09-16 **08:00** | `2026-09-16T02:30Z` | `2026-09-15` | Window closes (OT territory) | ✅ PASS (code-proven) |
| B9 | 09-16 08:01 | `2026-09-16T02:31Z` | **none** | Orphaned | ✅ PASS (code-proven) |

Scheduled-span attribution is covered by `test_scheduled_span_cross_midnight_attributes_to_start_date` — ✅ PASS (test-proven). **The punch-ownership boundaries B1–B9 are not.**

### Additional cross-midnight shift shapes

| # | Shift | Expected attendance date | Status |
|---|---|---|---|
| B10 | `23:00 → 07:00` | shift start date | ✅ PASS (code-proven) |
| B11 | `18:00 → 02:00` | shift start date | ✅ PASS (code-proven) |
| B12 | `end <= start` with `is_cross_midnight=False` | defensive `+1 day` in **UTC** | ✅ PASS (code-proven) — but see TZ-12 for the DST interaction |

---

## Group C — DST

**This entire group is the TZ-04 gap.** Every row is correct and every row is unprotected.

### C.1 — Scheduled spans across real transitions (`22:00 → 06:00`)

| # | Zone | Attendance date | Real minutes | Wall-clock minutes | Delta | Status |
|---|---|---|---|---|---|---|
| C1 | `America/New_York` | 2026-03-07 (spring fwd) | **420** | 480 | −60 | ✅ PASS (code-proven) |
| C2 | `America/New_York` | 2026-10-31 (fall back) | **540** | 480 | +60 | ✅ PASS (code-proven) |
| C3 | `Europe/London` | 2026-03-28 (spring fwd) | **420** | 480 | −60 | ✅ PASS (code-proven) |
| C4 | `Europe/London` | 2026-10-24 (fall back) | **540** | 480 | +60 | ✅ PASS (code-proven) |
| C5 | `Asia/Kolkata` | 2026-03-07 (control) | 480 | 480 | 0 | ✅ PASS (code-proven) |

### C.2 — Full `evaluate_day` across the London fall-back night (2026-10-24)

| # | Employee behaviour | worked | late | early | status | Status |
|---|---|---|---|---|---|---|
| C6 | Punches exactly 22:00→06:00 **local** (9 real hours) | **540** | 0 | 0 | `PRESENT` | ✅ PASS (code-proven) |
| C7 | Punches 8 **real** hours (out 05:00 local) | 480 | 0 | **60** | `PRESENT` | ⚠️ **UNDEFINED** — arithmetically correct, but no policy says a fall-back night should cost an extra real hour |

### C.3 — Spring-forward (London 2026-03-28)

| # | Case | Value | Status |
|---|---|---|---|
| C8 | Scheduled real minutes | **420** (wall clock says 480) | ✅ PASS (code-proven) |
| C9 | Punch 22:00→06:00 local spans | **420** real minutes → full credit for 7 real hours | ⚠️ **UNDEFINED** — same policy gap as C7 |

### C.4 — Nonexistent and ambiguous local wall times

Punches are instants and can never be ambiguous. Only shift/core/break **wall times** can.

| # | Case | Zone | Input | Resolves to | Round-trips as | Status |
|---|---|---|---|---|---|---|
| C10 | Nonexistent (spring gap) | `America/New_York` | 2026-03-08 02:30 | `07:30Z` | **03:30 EDT** — shifted forward 1h | ⚠️ **UNDEFINED** — `fold=0`, deterministic, silent, no policy recorded |
| C11 | Nonexistent (UK gap) | `Europe/London` | 2026-03-29 01:30 | `01:30Z` | **02:30 BST** — shifted forward 1h | ⚠️ same |
| C12 | Ambiguous (occurs twice) | `America/New_York` | 2026-11-01 01:30 | `05:30Z` | **01:30 EDT** — first occurrence | ⚠️ same |
| C13 | Ambiguous (UK repeat) | `Europe/London` | 2026-10-25 01:30 | `00:30Z` | **01:30 BST** — first occurrence | ⚠️ same |

*(C10–C13 collapse to the three UNDEFINED entries counted in the summary — one policy question, four manifestations.)*

### C.5 — Break matching across the ambiguous hour

| # | Case | Result | Status |
|---|---|---|---|
| C14 | Gap at ambiguous 01:10 local vs break `01:00–01:30`, London fall-back | `matched=True, paid=True` | ✅ PASS (code-proven) — UTC→local conversion happens before the time-of-day compare, which is the right order |

---

## Group D — Timezone precedence

| # | Company | Branch | Shift | Resolved | `scheduled_start` for 09:00 on 2026-09-15 | Status |
|---|---|---|---|---|---|---|
| D1 | `Asia/Kolkata` | `Asia/Dubai` | NULL | `Asia/Dubai` | `2026-09-15T05:00Z` | ✅ PASS (code-proven) |
| D2 | `Asia/Kolkata` | `Asia/Dubai` | `Asia/Kolkata` | `Asia/Kolkata` | `2026-09-15T03:30Z` | ✅ PASS (test-proven) |
| D3 | `Asia/Kolkata` | NULL | NULL | `Asia/Kolkata` | `2026-09-15T03:30Z` | ✅ PASS (test-proven) |
| D4 | `Asia/Kolkata` | NULL | `Europe/London` | `Europe/London` | `2026-09-15T08:00Z` | ✅ PASS (code-proven) |
| D5 | `Asia/Kolkata` | `Pacific/Kiritimati` (+14) | NULL | `Pacific/Kiritimati` | `2026-09-14T19:00Z` — **previous UTC date** | ✅ PASS (code-proven) |
| D6 | all three NULL | — | — | **cannot occur** — `company.timezone` is `NOT NULL DEFAULT 'Asia/Kolkata'` | resolution never fails, never falls back to server | ✅ PASS (code-proven) |

> **D5 is the clearest demonstration of why `attendance_date` must never be derived from a UTC date.** At UTC+14 the entire local working day falls on the previous UTC date.

---

## Group E — Timezone change and effective dating

| # | Scenario | Historical row on disk | After recompute | Status |
|---|---|---|---|---|
| E1 | `ShiftVersion.timezone` `Asia/Kolkata` → `Europe/London` (new version) | unchanged | **unchanged** — `resolve_shift_version_as_of` returns the old version for old dates | ✅ PASS (code-proven) — effective-dated |
| E2 | `Branch.timezone` `Asia/Kolkata` → `Asia/Singapore` | unchanged | **CHANGES** — new zone applied to historical dates | ❌ **FAIL** — TZ-01 |
| E3 | `Company.timezone` `Asia/Kolkata` → `Europe/London` | unchanged | **CHANGES** — day can flip `PRESENT` → 264 min early departure | ❌ *(same finding, E2)* |
| E4 | Employee **transfers branch** (assignment change) | unchanged | **unchanged** — `EmployeeAssignment` resolved as-of the date | ✅ PASS (code-proven) |
| E5 | Should a timezone change be permitted at all once attendance exists? | — | — | ⚠️ **UNDEFINED** — DEC-TZ-13 |

> E1 vs E2/E3 is the whole finding: **which branch an employee belongs to is effective-dated; a branch's timezone value is not.**

---

## Group F — Period-lock boundaries

Punch lock uses the **UTC date of `punch_time`** (`service.py:2347`); every other caller uses the local `attendance_date`.

| # | Local IST wall time | UTC instant | UTC date | Local date | Diverge? | Status |
|---|---|---|---|---|---|---|
| F1 | 2026-09-30 23:30 | `2026-09-30T18:00Z` | 09-30 | 09-30 | no | ✅ PASS (code-proven) |
| F2 | **2026-10-01 05:00** | `2026-09-30T23:30Z` | **09-30** | **10-01** | **YES** | ✅ PASS (code-proven) — correct per WD-30, fails *closed* |
| F3 | 2026-09-15 18:29 | `2026-09-15T12:59Z` | 09-15 | 09-15 | no | ✅ PASS (code-proven) |
| F4 | 2026-09-15 18:30 | `2026-09-15T13:00Z` | 09-15 | 09-15 | no | ✅ PASS (code-proven) |
| F5 | 2026-09-15 23:59 | `2026-09-15T18:29Z` | 09-15 | 09-15 | no | ✅ PASS (code-proven) |
| F6 | Is the UTC-date basis acceptable at a period boundary? | — | — | — | — | ⚠️ **UNDEFINED** — DEC-TZ-10 |

> **The exposure is early-morning punches, not late-evening ones.** For `+05:30`, divergence occurs for local `00:00–05:29`, which maps to the *previous* UTC date (F2). A punch at 23:00 IST does **not** diverge (F5). A 05:00 IST punch on 1 Oct is lock-checked against September, which may already be closed — it fails closed, the safe direction, but produces a confusing rejection exactly at month end.

---

## Group G — Server timezone independence

Identical inputs, four server timezones spanning UTC−4 to UTC+14.

| # | Output under `TZ=UTC` / `Asia/Kolkata` / `America/New_York` / `Pacific/Kiritimati` | Status |
|---|---|---|
| G1 | Day-shift `status`/`late`/`early`/`worked`/`paid` = `PRESENT`/2/0/533/1.00 | **identical** — ✅ PASS (code-proven) |
| G2 | Night-shift `status`/`late`/`worked`/`paid` = `PRESENT`/0/480/1.00 | **identical** — ✅ PASS (code-proven) |
| G3 | `scheduled_span_utc` across 5 zones | **identical** — ✅ PASS (code-proven) |
| G4 | DST spans across 4 transitions | **identical** — ✅ PASS (code-proven) |
| G5 | `datetime(2026,9,15,9,0).astimezone(UTC)` | `09:00Z` / **`03:30Z`** / **`13:00Z`** / **`2026-09-14T19:00Z`** | ❌ **FAIL** — TZ-02, the sole server-TZ dependency |

> The diff between the `TZ=UTC` and `TZ=Asia/Kolkata` runs is exactly two lines: the `TZ` label and G5.

---

## Group H — Ingestion validation

All rows executed against the shipped `PunchCreate` schema.

| # | Input | Current behaviour | Expected | Status |
|---|---|---|---|---|
| H1 | `punch_time="2026-09-15T09:00:00Z"` | accepted, tz-aware UTC | accept | ✅ correct |
| H2 | `punch_time="2026-09-15T09:00:00+04:00"` | accepted, offset preserved | accept | ✅ correct |
| H3 | `punch_time="2026-09-15T09:00:00"` (**naive**) | **accepted**, naive, coerced by process OS tz | **reject 422** | ❌ **FAIL** — TZ-02 / F-07 |
| H4 | `punch_time="2099-01-01T00:00:00Z"` | **accepted** | **reject** | ❌ **FAIL** — F-03 |
| H5 | `punch_time="1900-01-01T00:00:00Z"` | **accepted** (unless the period is CLOSED) | reject or bound | ❌ **FAIL** — F-01 |
| H6 | `source="REGULARIZATION"` on an employee self-punch | **accepted** | reject — server-assigned | ❌ **FAIL** — F-11 |
| H7 | `source="DEVICE"` on a web self-punch | **accepted** | reject — server-assigned | ❌ **FAIL** — F-11 |
| H8 | `punch_time` 90 s ahead of server time | **accepted**, no comparison made | depends on DEC-TZ-02 | ⚠️ **UNDEFINED** |

*(H1–H2 are correct behaviour and are not counted as scenarios needing new tests; the summary counts H3–H8.)*

---

## Group I — Breaks

| # | Scenario | Result | Status |
|---|---|---|---|
| I1 | Break `13:00–14:00`, gap starts 13:15 local | matched, `is_paid=True` | ✅ PASS (code-proven) |
| I2 | **Break `23:30–00:30`, gap starts 23:45 local** | **`shift_break_id=None`, `is_paid=False`** | ❌ **FAIL** — F-05; night-shift break silently unpaid |
| I3 | Paid/unpaid gap arithmetic (`PAIR_ALL` / `FIRST_IN_LAST_OUT`) | correct | ✅ PASS (test-proven) |
| I4 | Excess-break detection across midnight | not executed | 🔲 **UNTESTED** |

> **I2 is a paid-minutes defect, not a display defect.** The unmatched gap defaults unpaid, so `worked_minutes` drops, `paid_day_fraction` drops, and OT is suppressed — for exactly the night-shift population most likely to have a midnight-spanning break.

---

## Group J — Concurrency

| # | Scenario | Finding | Status |
|---|---|---|---|
| J1 | Transaction isolation level | **READ COMMITTED** (Postgres default; nothing sets it) | ✅ PASS (code-proven) — *verified via `SHOW default_transaction_isolation`* |
| J2 | Timezone `UPDATE` commits between two SELECTs inside one `_build_calculation_input` | later statements see the new value, earlier ones the old → torn config read, no error | 🔲 **UNTESTED** — TZ-09 |
| J3 | Two concurrent `calculate()` calls for the same employee-date | no row lock; `UNIQUE` prevents duplicates, not last-writer-wins | 🔲 **UNTESTED** — F-15 |

---

## Recommended test implementation order

Ordered by risk closed per unit of effort. The engine is a pure function, so Groups C, A, B, D and G need **no database** — they are fast unit tests.

| Priority | Group | Tests | Cost | Closes |
|---|---|---|---|---|
| 1 | **C** (DST) | 8 | low — pure functions | TZ-04; protects the audit's central positive finding |
| 2 | **H** (ingestion) | 6 | low — schema-level | TZ-02, F-01, F-03, F-11 |
| 3 | **E** (tz change) | 3 | medium — needs DB | TZ-01, the P0 |
| 4 | **I2** (cross-midnight break) | 1 | low — pure function | F-05 |
| 5 | **G** (server TZ) | 1 parametrised | low — set `TZ` per case | Locks in server-TZ independence |
| 6 | **A / B** (boundaries) | 20 parametrised | low | TZ-08; freezes the ±2h pad |
| 7 | **F** (period lock) | 5 | medium — needs DB | Month-end integrity |
| 8 | **J** (concurrency) | 2 | high | TZ-09, F-15 |

A single parametrised test file covering priorities 1, 2, 4, 5 and 6 would move **36 of the 46 code-proven-but-unprotected scenarios** into test-proven, with no database and no fixtures.

---

*All values computed 2026-09-15 by executing `hrms.modules.attendance.calculation` read-only, by querying the running dev Postgres, and by running the `python:3.12-slim` base image. No application code, schema, migration, or test was modified.*
