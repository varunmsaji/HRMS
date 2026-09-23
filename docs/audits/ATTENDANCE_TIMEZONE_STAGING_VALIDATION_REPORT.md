# Attendance Timezone Staging Validation Report

**Prepared:** 2026-09-17
**Validates:** [`ATTENDANCE_TIMEZONE_IMPLEMENTATION_COMPLETION_REPORT.md`](./ATTENDANCE_TIMEZONE_IMPLEMENTATION_COMPLETION_REPORT.md) (Phases 0–9)
**Acceptance criteria:** [`ATTENDANCE_TIMEZONE_FINAL_DECISION_AND_EXECUTION_GATE.md`](./ATTENDANCE_TIMEZONE_FINAL_DECISION_AND_EXECUTION_GATE.md) §0 decision register
**Type:** VALIDATION ARTEFACT — no application code, schema, migration, or shipped test was modified by this pass.
**Follow-up (2026-09-17, same day):** the `D1` defect this report originally found (§22) has been
**fixed and verified** — see the `D1` closure block in §22 and the updated gate in §25/§26.
Everything below this line is the original pass, unmodified, as the audit trail of record.

---

## 1. Executive Summary

> ## NOT READY FOR PRODUCTION *(as of the original pass — see the follow-up note above: `D1` is now closed; `B4`/`B5`/`B8` remain the only open blockers)*

Every behavioural claim in the completion report that can be tested from this repository was tested
and **reproduced**. The engine is provably server-timezone-independent; the cross-midnight break
defect (`F-05`) is fixed without regressing the after-midnight case the rejected Approach B would
have broken; the punch endpoint split, naive/epoch/future-timestamp rejection, timezone allow-list,
historical-integrity guard, period-lock basis change, concurrency lock and scheduled calculation all
behave exactly as `DEC-TZ-01` … `DEC-TZ-08` specify, verified through the **real HTTP API against a
real PostgreSQL 16**, not only through the shipped unit tests.

The backend suite reproduces the completion report's numbers **exactly**: 1228 passed, 19 failed.
All 19 failures were traced to a single unrelated helper (`_strip_permission`'s `scalar_one()`)
broken by the uncommitted RBAC default-roles work sharing this working tree. **No timezone
regression was found.**

Production remains blocked. Three blockers are the ones the completion report already named
(`B4`, `B5`, `B8`) and none is closable here. This pass adds one new defect found against an
approved acceptance criterion:

> **`D1` — the on-behalf punch dialog's time field is labelled "Punch time (IST)" but its value is
> interpreted in the viewer's browser timezone.** An HR admin on a non-IST browser typing `09:00`
> records `18:30 IST` (browser in `America/New_York`). Gate §13.2 requires "Admin mode: `IST`,
> labelled" — only the *labelled* half shipped. Not fixed by this pass, per the validation brief's
> stop-and-report rule. See §22.

Two further findings are documentation-level (`D2`, `D4`, `D5`) and one is a pre-existing,
out-of-approved-scope remnant of audit finding `TZ-06` (`D3`).

---

## 2. Environment

| Item | Value |
|---|---|
| Host | Linux 6.8.0-138-generic, host TZ `Asia/Kolkata` (+05:30) |
| Date of validation | 2026-09-17 |
| Python | 3.12.12 (`apps/api/.venv`) |
| pytest / mypy / ruff | 9.1.1 / 2.3.0 / 0.16.1 (0.16.1 is the version pinned in `uv.lock`) |
| PostgreSQL | 16-alpine, `hrms-postgres` container, host port 5433, healthy |
| Redis | 7-alpine, host port 6380, healthy |
| Alembic | at head — `20260922090000` |
| API under test | `uvicorn entrypoints.api:app` on port 8000, real HTTP |
| Web under test | `next dev` on port 3000, real browser |
| Node | 20 (`apps/web`) |

**Environment note (not a product defect).** `uv run <tool>` does not work on this checkout: the
project virtualenv was created at `/media/varun/varun6/...` and the repository now lives at
`/media/varun/varun8/...`, so every console-script shebang in `.venv/bin` is stale and `uv` silently
falls through to a conda Python 3.9 on `PATH`. All tooling in this report was therefore invoked as
`.venv/bin/python -m <tool>`, which resolves correctly. CI is unaffected (it builds a fresh env).

**Dev-database writes made by this pass.** 2 `tzprobe-*` companies (registration allow-list probes)
and 1 `UI TZ Check *` company with one employee and one calculated attendance day (live UI
verification). All other probe tenants were created and torn down inside test transactions. No
production system was contacted.

---

## 3. Commit / Git State

| Item | Value |
|---|---|
| Branch | `main` |
| HEAD | `e33fcdb8e3fad75ff030bc441ea03f26e6b7f338` — *feat(employee): confirmation workflow (PROBATION -> ACTIVE)*, 2026-09-06 |
| Working tree | **dirty — 96 changed/untracked entries** |
| Remote | `origin` → `https://github.com/varunmsaji/HRMS.git` |

> **The entire attendance/timezone remediation is uncommitted.** It exists only as working-tree
> modifications on top of `e33fcdb`. Nothing in this programme has a commit SHA, so nothing can be
> reverted by commit, cherry-picked to a release branch, or deployed by reference — contradicting
> the completion report's §11 rollback plan, which assumes "reverting the relevant commits".

**The working tree also contains substantial unrelated work**, interleaved in the same files:

| Unrelated workstream | Evidence |
|---|---|
| RBAC default roles (`HR_ADMIN`, `REPORTING_MANAGER`, `EMPLOYEE`) + `SETTINGS.USER.MANAGE`/`SETTINGS.ROLE.MANAGE` grants | `organisation/service.py`, new `alembic/versions/20260920090000_default_roles_backfill.py` |
| Account invite module | new `modules/account_invite/`, `20260921090000_account_invite.py` |
| Password reset | new `20260922090000_password_reset_token.py`, `identity/email_templates.py`, `tests/integration/auth/test_password_reset.py` |

This matters for two results below: **all 19 backend test failures** (§5) and **3 of the 15 ruff
errors** (§5) come from this unrelated work, not from the timezone programme. No user change was
reverted or modified by this pass.

---

## 4. Documentation Reviewed

All seven documents named in the validation brief exist and were read:

| Document | Size | Role in this validation |
|---|---|---|
| `ATTENDANCE_TIMEZONE_AUDIT.md` | 59 KB | Source of findings `TZ-01`…`TZ-12`, `F-xx` |
| `ATTENDANCE_TIMEZONE_TEST_MATRIX.md` | 17 KB | 68 scenarios, Groups A–J — used as the scenario source for §6–§9 |
| `ATTENDANCE_TIMEZONE_DECISION_AND_REMEDIATION.md` | 183 KB | Superseded by the gate; consulted for §19 test plan |
| `ATTENDANCE_TIMEZONE_IMPLEMENTATION_PLAN.md` | 114 KB | File-by-file remediation table (§1335–1337) — used to scope `TZ-06` |
| `ATTENDANCE_TIMEZONE_FINAL_PRE_IMPLEMENTATION_SPEC.md` | 170 KB | Consulted for `P-15`, `SR-xx` |
| **`ATTENDANCE_TIMEZONE_FINAL_DECISION_AND_EXECUTION_GATE.md`** | 197 KB | **Primary acceptance criteria** — §0 register, §3, §4, §8.2, §10, §12, §13, §16, §17 |
| **`ATTENDANCE_TIMEZONE_IMPLEMENTATION_COMPLETION_REPORT.md`** | 18 KB | **Primary claim set under test** |

An eighth, `ATTENDANCE_TIMEZONE_CLIENT_APPROVAL.md` (29 KB), was also read — see `D6` in §22.

---

## 5. Automated Test Results

### 5.1 Backend — full suite, `TZ=UTC` (CI's pinned value)

```
1228 passed, 19 failed, 0 skipped, 0 errors   in 243.20s (0:04:03)
```

| Metric | This run | Completion report | Match |
|---|---|---|---|
| Passed | 1228 | 1228 | ✅ |
| Failed | 19 | 19 | ✅ |
| Skipped / errors | 0 / 0 | not stated | — |

### 5.2 Failure classification — all 19

**Classification: `B. PRE-EXISTING FAILURE` (unrelated workstream).**

Root cause traced to one line, `tests/integration/modules/organisation/test_workforce_calendar.py:49`:

```python
role = (await session.execute(select(Role).where(Role.company_id == company_id))).scalar_one()
```

`scalar_one()` requires **exactly one** `Role` per company. The uncommitted RBAC work seeds **four**
(`COMPANY_ADMIN`, `HR_ADMIN`, `REPORTING_MANAGER`, `EMPLOYEE`) at registration, so the helper raises
`sqlalchemy.exc.MultipleResultsFound`. The test files themselves are unmodified (`git status` clean
for all of them) — the production change broke a test helper's assumption.

<details><summary>All 19 failing tests</summary>

```
tests/integration/modules/onboarding/test_onboarding_activation.py::test_activate_success_creates_full_employee_graph
tests/integration/modules/onboarding/test_onboarding_activation.py::test_activate_twice_rejected
tests/integration/modules/organisation/test_company_profile.py::test_get_company_profile_requires_permission
tests/integration/modules/organisation/test_permission_matrix.py::test_zero_permission_denied_org_manage[GET-/v1/companies/current]
tests/integration/modules/organisation/test_permission_matrix.py::test_zero_permission_denied_org_manage[GET-/v1/companies/current/setup-progress]
tests/integration/modules/organisation/test_permission_matrix.py::test_zero_permission_denied_org_manage[GET-/v1/companies/current/subscription]
tests/integration/modules/organisation/test_permission_matrix.py::test_zero_permission_denied_dashboard
tests/integration/modules/organisation/test_permission_matrix.py::test_patch_zero_permission_denied
tests/integration/modules/organisation/test_permission_matrix.py::test_legal_entity_zero_permission_denied
tests/integration/modules/organisation/test_permission_matrix.py::test_branch_zero_permission_denied
tests/integration/modules/organisation/test_permission_matrix.py::test_department_zero_permission_denied
tests/integration/modules/organisation/test_permission_matrix.py::test_designation_zero_permission_denied
tests/integration/modules/organisation/test_permission_matrix.py::test_grade_zero_permission_denied
tests/integration/modules/organisation/test_registration_flow.py::test_registration_success_full_row_graph
tests/integration/modules/organisation/test_setup_progress.py::test_get_setup_progress_requires_permission
tests/integration/modules/organisation/test_subscription_dashboard.py::test_get_subscription_requires_permission
tests/integration/modules/organisation/test_subscription_dashboard.py::test_get_dashboard_requires_dashboard_permission
tests/integration/modules/organisation/test_workforce_calendar.py::test_work_calendar_denied_without_org_calendar_manage
tests/integration/modules/organisation/test_workforce_calendar.py::test_holiday_calendar_denied_without_org_holiday_manage
```

**Zero** of the 19 is in `modules/attendance`, `modules/leave`, `shared/`, or any file this
programme changed. Not treated as a timezone regression.
</details>

### 5.3 Static analysis

| Gate | Result | Classification |
|---|---|---|
| `mypy src/hrms` | **`Success: no issues found in 134 source files`** | A. PASS — matches report |
| `lint-imports` | **`Contracts: 1 kept, 0 broken`** | A. PASS — matches report |
| `ruff check src tests entrypoints` | **`All checks passed!`** | A. PASS |
| **`ruff check .`** *(what CI runs)* | **15 errors, all `E501`** | **D4 — see §22** |
| `ruff format --check .` | 18 files would be reformatted | B. PRE-EXISTING |
| `npx tsc --noEmit` (web) | clean, exit 0 | A. PASS — matches report |

**On the 15 `ruff check .` errors.** All 15 are `E501 line-too-long`, all in `alembic/versions/`:
12 in **committed, untouched** migrations (present since `dbd3f43`, verified via `git show`), and
3 in the **new, unrelated** `20260920090000_default_roles_backfill.py`. None is in the timezone
diff. The completion report's "`ruff check` → All checks passed!" reproduces only when scoped to
`src tests entrypoints`; CI's actual command is `uv run ruff check .`, which fails. Pre-existing
and unrelated to timezone, but it means **the CI lint gate does not currently pass on this tree**.

**On the 18 `ruff format` files** (report said 7): all are in `alembic`, `identity`, `leave`,
`onboarding`, `account_invite`, `password_reset` — the unrelated workstreams. **No attendance,
`shared/timezone.py`, `shared/business_time.py`, organisation, or web timezone file appears.** The
count grew because the unrelated work grew, not because the timezone diff regressed.

### 5.4 Web

| Run | Result |
|---|---|
| `TZ=UTC npm test` | 46 files, **356 passed** |
| `TZ=Asia/Kolkata npm test` | 46 files, **356 passed** |
| `TZ=America/New_York npm test` | 46 files, **356 passed** |
| `TZ=Pacific/Kiritimati npm test` | 46 files, **356 passed** |

Matches the completion report's 46/356 exactly.

---

## 6. Server Timezone Independence

**Mandatory test — PASS at three independent levels.**

### 6.1 Engine level — business results byte-identical

A read-only harness (`tz_matrix.py`, archived in the session scratchpad) executed the shipped
`hrms.modules.attendance.calculation` over 40 fixed scenarios — scheduled spans, punch load windows,
calendar-day windows, `WD-06` timezone precedence, full `evaluate_day` for day and night shifts,
break matching, and `business_today` — under four process timezones. Outputs were diffed as JSON:

```
UTC vs Asia/Kolkata        -> IDENTICAL
UTC vs America/New_York    -> IDENTICAL
UTC vs Pacific/Kiritimati  -> IDENTICAL
```

Nothing differed — not the attendance date, shift matching, worked minutes, late minutes, early
minutes, overtime, break calculation, or attendance status. The only environment-varying value in
the harness output is the diagnostic `TZ` label itself.

### 6.2 Suite level — 610-test subset, four timezones

`tests/unit` + `tests/integration/modules/attendance` + the leave business-time, timezone-change-guard,
shift-version and company-profile suites:

| `TZ` | Result |
|---|---|
| `UTC` | 1 failed, 609 passed (84.0 s) |
| `Asia/Kolkata` | 1 failed, 609 passed (83.2 s) |
| `America/New_York` | 1 failed, 609 passed (84.3 s) |
| `Pacific/Kiritimati` | 1 failed, 609 passed (89.2 s) |

The single failure is the same `test_get_company_profile_requires_permission` from §5.2 in all four
runs — identical, and unrelated.

### 6.3 API level — identical HTTP outcomes, four timezones

The full API probe set (§10–§17 below) was executed four times under different process timezones.
Every HTTP status code and every business decision was **byte-identical** after normalising
generated UUIDs:

```
UTC vs Asia/Kolkata        -> IDENTICAL
UTC vs America/New_York    -> IDENTICAL
UTC vs Pacific/Kiritimati  -> IDENTICAL
```

**`G5`, the test matrix's sole server-TZ dependency, is closed.** `datetime.now().astimezone()` no
longer appears on any business-date path; `shared/business_time.py` derives every business date from
`datetime.now(UTC).astimezone(ZoneInfo(tz_name))`.

---

## 7. Normal Attendance

Shift `09:00–18:00 Asia/Kolkata`, attendance date `2026-09-15`, `TZ=UTC`.

| Scenario | Punches (IST wall) | Status | Worked | Late | Early | OT | Paid fraction |
|---|---|---|---|---|---|---|---|
| On time | 09:00 → 18:00 | `PRESENT` | 540 | 0 | 0 | 0 | 1.00 |
| Late in, early out | 09:32 → 17:15 | `PRESENT` | 463 | 22 | 35 | 0 | 1.00 |
| Overtime | 09:00 → 20:30 | `PRESENT` | 690 | 0 | 0 | **150** | 1.00 |

Resolved instants (matrix Group A): `scheduled_span_utc` = `2026-09-15T03:30Z … 12:30Z` (540 min);
`punch_window_utc` = `2026-09-15T01:30Z … 14:30Z` — exactly the ±2h pad, matching matrix rows
**A5** (07:00 IST opens) and **A9** (20:00 IST closes).

### 7.1 End-to-end through the real API and UI

Live tenant (`Asia/Kolkata` company, `Asia/Kolkata` branch, `Asia/Kolkata` shift), punches at
09:05 and 18:20 IST on 2026-09-15:

| Layer | Value |
|---|---|
| Raw wire input (on-behalf) | `2026-09-15T03:35:00Z` / `2026-09-15T12:50:00Z` |
| Stored (`punch.punch_time`, `timestamptz`) | `2026-09-15 03:35:00+00` / `2026-09-15 12:50:00+00` |
| `attendance_day.timezone` | `Asia/Kolkata` |
| `attendance_date` | `2026-09-15` |
| Computed | `PRESENT`, worked 555, late 5, paid 1.00 |
| **UI rendering** | `FIRST IN 15 Sept 2026, 09:05 IST` · `LAST OUT 15 Sept 2026, 18:20 IST` |

---

## 8. Night Shift

Shift `22:00 → 06:00 Asia/Kolkata`, `is_cross_midnight=True`, attendance date `2026-09-15`.
`scheduled_span_utc` = `2026-09-15T16:30Z … 2026-09-16T00:30Z` (480 min).

### 8.1 Punch ownership across midnight (matrix Group B, frozen)

Load window = `2026-09-15T14:30Z … 2026-09-16T02:30Z`.

| IST wall time | Owned by 2026-09-15? | Matrix row |
|---|---|---|
| 15th 19:59 | **no** — orphaned | B1 ✅ |
| 15th **20:00** | yes — window opens | B2 ✅ |
| 15th 22:00 / 23:30 | yes | B3/B4 ✅ |
| 16th **00:00** | **yes — midnight does not move the day** | B5 ✅ |
| 16th 00:30 / 01:00 / 01:30 / 03:00 | yes | B6 ✅ |
| 16th **05:00 / 05:29 / 05:30** | yes — **no step at the UTC-date rollover** | ✅ |
| 16th 06:00 | yes | B7 ✅ |
| 16th **08:00** | yes — window closes | B8 ✅ |
| 16th 08:01 | **no** — orphaned | B9 ✅ |

**The 00:00–05:29 IST band behaves identically to the rest of the shift.** The UTC calendar date is
never used to decide ownership.

### 8.2 Computed results

| Scenario | Punches | Status | Worked | Late | Early | OT |
|---|---|---|---|---|---|---|
| On time | 22:00 → 06:00 | `PRESENT` | 480 | 0 | 0 | 0 |
| Late in | 23:30 → 06:00 | `PRESENT` | 390 | 80 | 0 | 0 |
| Out 05:29 | 22:00 → 05:29 | `PRESENT` | 449 | 0 | 21 | 0 |
| Out 05:30 | 22:00 → 05:30 | `PRESENT` | 450 | 0 | 20 | 0 |
| Overtime | 22:00 → 08:00 | `PRESENT` | 600 | 0 | 0 | **120** |

The 05:29 → 05:30 pair differs by exactly **one minute** of worked/early time — arithmetically
correct, with no discontinuity at the UTC-date boundary.

### 8.3 Other cross-midnight shift shapes

| Shift | Span (UTC) | Minutes | Matrix |
|---|---|---|---|
| `23:00 → 07:00` | `17:30Z … +1d 01:30Z` | 480 | B10 ✅ |
| `18:00 → 02:00` | `12:30Z … 20:30Z` | 480 | B11 ✅ |

### 8.4 DST spans (matrix Group C, unchanged — the engine's central positive finding)

| Zone / date | Real minutes | Wall clock | Delta | Matrix |
|---|---|---|---|---|
| `America/New_York` 2026-03-07→08 (spring fwd) | **420** | 480 | −60 | C1 ✅ |
| `America/New_York` 2026-10-31→11-01 (fall back) | **540** | 480 | +60 | C2 ✅ |
| `Europe/London` 2026-03-28 (spring fwd) | **420** | 480 | −60 | C3 ✅ |
| `Europe/London` 2026-10-24 (fall back) | **540** | 480 | +60 | C4 ✅ |
| `Asia/Kolkata` 2026-09-15 (control) | 480 | 480 | 0 | C5 ✅ |

---

## 9. Cross-Midnight Breaks

**Mandatory regression group — PASS.** `_break_window_contains` (`calculation.py`) is wrap-aware.

### 9.1 `match_breaks` unit results

| # | Break window | Gap starts (IST) | `shift_break_id` | `is_paid` | Verdict |
|---|---|---|---|---|---|
| I1 | `13:00–14:00` | 13:15 same day | matched | **true** | ✅ unchanged (regression guard) |
| **I2** | **`23:30–00:30`** | **23:45** | **matched** | **true** | ✅ **`F-05` FIXED** (was `None`/unpaid) |
| I2b | `23:30–00:30` | 00:15 next day | matched | **true** | ✅ both legs of the wrap |
| **I5** | **`01:00–02:00`** | **01:30** | **matched** | **true** | ✅ **the previously-working case, NOT regressed** |
| I6 | `01:00–02:00` | 03:30 (outside) | `None` | false | ✅ correctly unmatched |
| I7 | `01:00`, `end=None` | 01:30 | `None` | false | ✅ point-in-time break is not a 24h window |

> **Row I5 is the load-bearing regression guard.** The gate's §1.2 rejected Approach B precisely
> because it was code-proven to break this case while fixing I2. Approach A fixes I2 **and** leaves
> I5 correct. Both are now verified.

### 9.2 Paid-minutes consequence — full `evaluate_day`, night shift `22:00→06:00`

| Scenario | Breaks configured | Worked | Paid break | Unpaid break |
|---|---|---|---|---|
| Midnight-crossing break, gap 23:45–00:15 | `23:30–00:30` paid | **480** | **30** | 0 |
| After-midnight break, gap 01:00–02:00 | `01:00–02:00` paid | **480** | **60** | 0 |
| Multiple breaks (one crossing, one not) | `23:30–00:30` paid + `03:00–03:30` unpaid | **450** | **30** | **30** |

`I2` was a paid-minutes defect, not a display defect: the unmatched gap previously defaulted unpaid,
dropping `worked_minutes` and suppressing OT. Both are now correct.

### 9.3 Shipped regression tests

`tests/integration/modules/attendance/test_break_cross_midnight.py` —
`test_break_spanning_midnight_matched_end_to_end` and
`test_break_after_midnight_regression_guard_end_to_end`. Both pass under all four timezones.

---

## 10. Timezone Validation

**PASS.** Verified through the **real HTTP API**, not the frontend.

### 10.1 Public, unauthenticated registration (`POST /v1/companies/register`)

| Submitted `timezone` | HTTP | Message | Stored |
|---|---|---|---|
| `Asia/Kolkata` | **201** | — | `Asia/Kolkata` |
| `Asia/Calcutta` | **201** | — | **`Asia/Kolkata`** — canonicalised ✅ |
| **`IST`** | **422** | *timezone must be a valid IANA time zone identifier* | — |
| `UTC+05:30` | **422** | same | — |
| `invalid-value` | **422** | same | — |
| `""` (empty) | **422** | same | — |
| `UTC` | **422** | *timezone must be one of ['Asia/Kolkata']* | — |
| `America/New_York` | **422** | same | — |

> **`IST` never reaches `ZoneInfo`.** It produces a controlled `422` validation error, not
> `HTTP 500` / `ZoneInfoNotFoundError`. This is the specific bug §4 of the gate names, and it is
> closed. Validator order is confirmed correct: IANA membership → alias canonicalisation →
> allow-list, so `Asia/Calcutta` is accepted rather than rejected for a spelling difference (§6.3).

`GET /v1/companies/registration-config` returns `{"allowed_company_timezones": ["Asia/Kolkata"]}` —
the frontend narrows its `<select>` from the API rather than from a duplicated TypeScript list.

### 10.2 Every other timezone-accepting surface

| Surface | `IST` | `UTC+05:30` | `invalid-value` | `Not/AZone` | `Asia/Dubai` |
|---|---|---|---|---|---|
| `PATCH /v1/companies/current` | 422 | 422 | 422 | — | 422 (allow-list) |
| `POST /v1/branches` | **422** | 422 | 422 | 422 | **201** ✅ by design |
| `POST /v1/shifts/{id}/versions` | **422** | 422 | 422 | — | — |

`Branch` and `ShiftVersion` stay a **fully general IANA surface** (gate §4.3, `ED-1`) — only
`Company` is India-gated. `ShiftVersion.timezone` previously had **no validator at all**; the `IST`
→ 500 path is now closed at the schema boundary.

### 10.3 Defence in depth at calculation time

`evaluate_day` calls `resolve_zoneinfo(inputs.timezone)` once, before any internal `ZoneInfo(...)`
construction, and degrades an unresolvable stored zone to a `CONFIG_ERROR` attendance day rather
than raising past the function (`ED-10`). Verified by code inspection; unreachable for any row
written after Phase 2 shipped.

---

## 11. Client Clock / Timestamp Security

**PASS.** All probes against the real API.

### 11.1 Self-service route — the clock is structurally unforgeable

`PunchCreateSelf` has **no** `punch_time`, `source`, or `employee_id` field, and
`model_config = ConfigDict(extra="forbid")`:

| Request to `POST /v1/attendance/punches/me` | HTTP |
|---|---|
| `{direction, punch_time: "2026-08-10T09:00:00Z"}` | **422** |
| `{direction, source: "DEVICE"}` | **422** |
| `{direction, source: "REGULARIZATION"}` | **422** |
| `{direction, employee_id: "<own id>"}` | **422** |

An old client fails loudly rather than having its timestamp silently discarded. The OpenAPI schema
confirms the field simply does not exist. **`DEC-TZ-01` verified: there is nothing left to forge.**

### 11.2 On-behalf route — client time accepted but bounded

| Input | HTTP | Error code |
|---|---|---|
| `"2026-08-10T09:00:00"` (**naive**) | **422** | `REQUEST_VALIDATION_ERROR` |
| `"2026-08-10"` (date-only) | **422** | same |
| `0` (epoch int) | **422** | same |
| `1789000000` (epoch int, plausible) | **422** | same |
| `1789000000.5` (epoch float) | **422** | same |
| `"2026-08-10T14:30:00+05:30"` | **201** | stored `2026-08-10T14:30:00+05:30` = `09:00Z` ✅ |
| missing `reference` (the reason) | **422** | `REQUEST_VALIDATION_ERROR` |
| `source` supplied | **422** | `extra="forbid"` |
| accepted punch | — | `source` = **`ADMIN`**, server-assigned |

**`AwareIsoDatetime` closes the epoch-integer hole** that bare `AwareDatetime` would have left open
(Pydantic v2 reads an `int` as epoch seconds and the result *is* tz-aware, so the annotation alone
has nothing to object to). Confirmed live.

### 11.3 Clock-manipulation matrix

| Scenario | Result |
|---|---|
| Correct client time (60 s in the past) | **201** accepted |
| Client clock **1 hour ahead** | **422** `PUNCH_TIME_IN_FUTURE` |
| Client clock behind (past instant) | **201** accepted — legitimate backdated correction |
| Forged `source` (`DEVICE`/`REGULARIZATION`) | **422** on both routes — server-assigned (`F-11` closed) |
| Forged `employee_id` (other tenant / outside scope) | 404, covered by `test_attendance_security.py` |
| Self-service device clock | **not readable at all** — no field |

**Self-punch clock authority.** The one self-service punch the probe could execute returned the
server's receipt instant with `source="WEB"`; the admin user in the probe tenant has
`employee_id = null`, so the route correctly returned
*"The caller has no linked employee record — use the on-behalf endpoint instead"* rather than
inventing a target. The DB-level evidence is stronger: across 26 punches, `source` is only ever
`ADMIN` (18) or `REGULARIZATION` (8) — **never a client-supplied value**.

---

## 12. Historical Integrity

**PASS.** `DEC-TZ-04` verified end-to-end.

| Step | Observation |
|---|---|
| Baseline computed day | `PRESENT`, worked 540, `timezone=UTC`, version 3, scheduled `2026-08-10T09:00Z…18:00Z` |
| `PATCH /v1/branches/{id}` → `Europe/London` | **HTTP 409 `TIMEZONE_CHANGE_BLOCKED`** — *"timezone cannot be changed — computed attendance already exists for this scope"* |
| Row after the attempted change | **byte-identical** (`identical=True`, all fields compared except `updated_at`) |
| **Recompute after the attempt** | `PRESENT`, worked 540, `timezone=UTC`, scheduled `09:00Z…18:00Z` — **unchanged** |
| `PATCH /v1/companies/current` → same value | HTTP 200 — an unchanged value is correctly not guarded |
| `PATCH /v1/companies/current` → any other zone | 422 (allow-list fires first) |

`_assert_timezone_change_allowed` is real (was a documented no-op stub) and wired into **both**
`update_company_profile` and `update_branch`. Branch scope resolves via full `EmployeeAssignment`
history, so an employee who has since transferred away still blocks the change (`ED-12`) — covered
by `test_branch_timezone_change_blocked_for_employee_who_has_since_transferred_away`.

The `CLOSED`-period check runs **first and unconditionally**, before the zero-attendance escape
hatch (`ED-12` point 3) — covered by
`test_company_timezone_change_blocked_by_closed_period_even_with_zero_attendance`.

**Zero-attendance escape hatch still open where it should be.** The three `Asia/Calcutta` `TRIAL`
companies in the dev DB have 0 computed attendance days and 0 closed periods, so they remain
correctable — matching the completion report's `DH-1` inventory exactly.

`calculate()` additionally refuses a locked day unconditionally
(`test_locked_day_refuses_recompute`). Two independent guards, defence in depth.

---

## 13. Leave Scheduled Jobs

**PASS for the three jobs that derive a business date.**

### 13.1 The defect, quantified at each job's real Beat instant

Celery config verified live: `Celery.conf.timezone = Asia/Kolkata`, `enable_utc = True`.

| Job | Beat crontab | Fires (UTC) | `as_of` OLD (UTC) | `as_of` NEW (IST) | Accrual window OLD → NEW |
|---|---|---|---|---|---|
| `leave.run_monthly_accrual` | `0 1 1 * *` = **01:00 IST, 1st** | `2026-09-30T19:30Z` | `2026-09-30` | **`2026-10-01`** | **August** → **September** |
| `leave.run_comp_off_expiry_sweep` | `30 1 * * *` = **01:30 IST** | `2026-09-30T20:00Z` | `2026-09-30` | **`2026-10-01`** | off-by-one day → correct |
| `leave.run_year_end_sweep` | `0 2 * * *` = **02:00 IST** | `2026-09-30T20:30Z` | `2026-09-30` | **`2026-10-01`** | off-by-one day → correct |
| Year boundary (accrual, 1 Jan) | `0 1 1 * *` | `2025-12-31T19:30Z` | `2025-12-31` | **`2026-01-01`** | **November** → **December** |

> **The monthly accrual was accruing the wrong month, every month, on every tenant.** The old
> UTC-derived `as_of` fed `_previous_month_bounds()`, which then returned August's window when
> September's was due. Both windows were computed directly from the shipped function and are shown
> above. This is now correct.

All three per-company wrappers (`_accrue_company_async`, `_sweep_comp_off_expiry_async`,
`_run_year_end_async`) call `business_today(company.timezone)`.

### 13.2 The fourth job — `leave.run_comp_off_credit_sweep`

**No fix was needed, and none was made.** `_credit_comp_off_async` calls
`LeaveCompOffService.credit_company(company_id)`, which takes **no `as_of` parameter** and derives
no "today": its ledger `effective_date` comes from `fact.attendance_date`, and its idempotency key
is `reference_id=overtime_record_id`. Verified against `HEAD` — it never had an `as_of` to fix.

See `D5` in §22: the gate's §3.3 says "the **four** call sites above" while its own §3.1 lists
three. The implementation matches the code, not the prose.

### 13.3 Shipped tests

`tests/integration/modules/leave/test_leave_tasks_business_time.py` — 4 tests asserting the
resolved `as_of` at the exact frozen instants each job is Beat-scheduled to fire, including the
month boundary. All pass under all four process timezones.

---

## 14. Attendance Scheduled Calculation

**PASS.**

| Requirement (`DEC-TZ-07`) | Verified |
|---|---|
| Schedule exists | `beat_schedule["attendance-run-daily-calculation"]` → `crontab: 30 9 * * *` under `timezone=Asia/Kolkata` = **09:30 IST** ✅ |
| Worker can execute it | `entrypoints/worker.py` imports the module; registry contains `attendance.run_daily_calculation` **and** `attendance.calculate_company` ✅ |
| Correct business dates | `business_today(company.timezone)`, never `datetime.now(UTC).date()`, with the reason documented in the task docstring ✅ |
| Trailing-day calculation | `TRAILING_DAYS = 3` — a run at 09:30 IST on 2026-08-10 produced rows for **2026-08-08, 08-09, 08-10** ✅ |
| Duplicate execution safe | Two consecutive runs: `run1_calculated=3`, `run2_calculated=3`, **rows identical across runs = `True`** ✅ |
| No attendance corruption | 3 rows, 3 distinct dates, no duplicates ✅ |
| Locked days / `CLOSED` periods skipped | `AttendanceDayLockedError`/`AttendancePeriodClosedError` caught per employee-date and treated as expected, not failure ✅ (`test_calculate_company_survives_a_locked_day`) |
| One employee's failure does not poison the batch | per-employee-date `SAVEPOINT` ✅ |
| Fan-out | one `calculate_company` task per active (`TRIAL`/`ACTIVE`) company, mirroring `leave/tasks.py` ✅ |

Observed rows from the scheduled run:

```
(2026-08-08, 'INCOMPLETE',   0, 0, 0, 0, 0.00, 0.00, 'UTC', 09:00Z, 18:00Z)
(2026-08-09, 'INCOMPLETE',   0, 0, 0, 0, 0.00, 0.00, 'UTC', 09:00Z, 18:00Z)
(2026-08-10, 'PRESENT',    540, 0, 0, 0, 1.00, 0.00, 'UTC', 09:00Z, 18:00Z)
```

### 14.1 Orphan-punch report (`SR-14`)

Covered by `test_attendance_orphan_report.py`, all passing under four timezones:

| Case | Behaviour |
|---|---|
| Employee **with** shift, punch outside the ±2h pad | **reported** as orphaned ✅ |
| Employee **without** shift, same local time | **not reported** — `calendar_day_window_utc`, the full local civil day, no pad (`SR-14`) ✅ |
| Punch on a date with no `AttendanceDay` row at all | **reported** ✅ |

`list_orphaned_punches` applies the no-shift window shape to `shift_id IS NULL` days specifically,
so unscheduled employees are not misreported. `FLEXIBLE`'s asymmetric `-2h/+12h` pad is not
distinguishable from `FIXED`/`SPLIT` using only what is stored on `AttendanceDay`, so the narrower
±2h shape is applied to every shift-bearing day — conservative in the safe direction for a report
(it can over-report for HR to dismiss, never under-report a genuinely missed punch). This is
documented in the method's own docstring and is a deliberate, stated limitation, not a defect.

---

## 15. Immediate Calculation

**PASS.**

| Property | Observation |
|---|---|
| Punch alone creates an `attendance_day` | 1 IN punch → **1 row**, `INCOMPLETE`, version 1, **no human action** ✅ |
| Second punch recomputes | + 1 OUT punch → **1 row**, `PRESENT`, worked 540, late 0, version 2 ✅ |
| Idempotent / full-row replacement | version increments monotonically; row count stays 1 ✅ |
| **A calculation failure never fails the punch** | `AttendanceDayService.calculate` forced to raise → punch returns **HTTP 201**; `punch_rows=1`, `attendance_day_rows=0` — **the fact is kept, only the derivation is skipped** ✅ |
| Scheduled reconciliation recovers it | trailing sweep afterwards → `attendance_day_rows=1` ✅ |

The hook is wrapped in `begin_nested()` (a `SAVEPOINT`) rather than a bare `try/except`, so an
exception that aborts the transaction at the Postgres level cannot poison the outer transaction the
punch insert and its audit row are still pending in. Verified by forcing a real exception through
the real API. This is exactly the non-blocking design gate §16.2 specifies.

---

## 16. Concurrency

**PASS.** Real concurrent HTTP requests via `asyncio.gather`, each opening its own
`AsyncSession`/transaction.

| Load | Status codes | `attendance_day` rows | `calculation_version` |
|---|---|---|---|
| **10 simultaneous** punches, same employee + date | `[201]` only | **1** | 10 |
| **20 simultaneous** punches, same employee + date | `[201]` only | **1** | 30 (cumulative) |

- **No duplicate `attendance_day` rows** — confirmed by direct SQL count.
- **No unhandled integrity errors** — no 500s, no 409s; every request returned 201.
- **Deterministic final state** — `calculation_version` equals the exact number of calculations run.
- **Correct calculation** — the surviving row is fully self-consistent, not stuck mid-race.

### 16.1 Mechanism inspection

`AttendanceDayService.calculate()` uses `get_by_employee_date_for_update` — a `SELECT … FOR UPDATE`
on the `(company_id, employee_id, attendance_date)` row — acquired **before**
`_build_calculation_input` re-resolves configuration, exactly as gate §17.3 constraint 1 requires.
Constraint 3 (a `FOR UPDATE` on a not-yet-existing row locks nothing) is handled by a `SAVEPOINT`
around the insert: on `IntegrityError` the loser rolls back to the savepoint, re-reads the winner's
row under `FOR UPDATE`, and falls through to the ordinary recompute branch.

**No broad table lock was introduced.** `with_for_update` appears only on this one row-scoped
query. Races #1 and #2 (simultaneous punches, double-clicked button) remain unlocked by design —
`punch` is append-only and `collapse_duplicate_punches` merges them at calculation time. Isolation
level is unchanged at `READ COMMITTED` (constraint 4).

Shipped tests: `test_attendance_concurrency.py` — first-ever-insert race and ordinary-recompute
race, both via genuinely concurrent HTTP requests. Both pass under four timezones.

---

## 17. Period Lock

**PASS.** `DEC-TZ-05`/`CD-1` verified against the real API.

The rule under test: *accept if **either** the local (IST) date **or** the previous local date is
not `CLOSED`; refuse only when **both** are closed.*

August 2026 `CLOSED`; September has no period row (never closed). Employment from 2026-01-01.

| IST wall time | UTC instant | UTC date | IST date | Prev IST | Old basis would | **Observed** |
|---|---|---|---|---|---|---|
| **00:30 IST, 1 Sep** | `2026-08-31T19:00Z` | **31 Aug (CLOSED)** | 1 Sep | 31 Aug | ❌ reject | **201 ACCEPTED** ✅ |
| **01:30 IST, 1 Sep** | `2026-08-31T20:00Z` | **31 Aug (CLOSED)** | 1 Sep | 31 Aug | ❌ reject | **201 ACCEPTED** ✅ |
| **03:00 IST, 1 Sep** | `2026-08-31T21:30Z` | **31 Aug (CLOSED)** | 1 Sep | 31 Aug | ❌ reject | **201 ACCEPTED** ✅ |
| **04:30 IST, 1 Sep** *(§10.3 mirror case)* | `2026-08-31T23:00Z` | **31 Aug (CLOSED)** | 1 Sep | 31 Aug | ❌ reject | **201 ACCEPTED** ✅ |
| **05:00 IST, 1 Sep** | `2026-08-31T23:30Z` | **31 Aug (CLOSED)** | 1 Sep | 31 Aug | ❌ reject | **201 ACCEPTED** ✅ |
| **05:29 IST, 1 Sep** | `2026-08-31T23:59Z` | **31 Aug (CLOSED)** | 1 Sep | 31 Aug | ❌ reject | **201 ACCEPTED** ✅ |
| **05:30 IST, 1 Sep** | `2026-09-01T00:00Z` | 1 Sep | 1 Sep | 31 Aug | accept | **201 ACCEPTED** ✅ |
| **06:00 IST, 1 Sep** | `2026-09-01T00:30Z` | 1 Sep | 1 Sep | 31 Aug | accept | **201 ACCEPTED** ✅ |
| 23:30 IST, 31 Jul | `2026-07-31T18:00Z` | 31 Jul | 31 Jul | 30 Jul | accept | **201 ACCEPTED** ✅ |
| **23:59 IST, 31 Aug** *(both closed)* | `2026-08-31T18:29Z` | 31 Aug | **31 Aug** | **30 Aug** | reject | **409 `ATTENDANCE_PERIOD_CLOSED`** ✅ |
| **10:00 IST, 15 Aug** *(both closed)* | `2026-08-15T04:30Z` | 15 Aug | **15 Aug** | **14 Aug** | reject | **409 `ATTENDANCE_PERIOD_CLOSED`** ✅ |

> **The 05:29 → 05:30 step is gone.** Under the old UTC-date basis the first six rows were
> *falsely rejected* — a permanently lost fact, with no orphan row to find and a regularization
> path that would also refuse. All six are now accepted, and the both-dates-closed cases still fail
> closed. This is exactly `DEC-TZ-05` as selected, and it ships together with the orphan-punch
> report (§14.1), as the decision requires.

**Scoping note.** `_ensure_punch_date_open` is used by **punch ingestion only**. Roster,
regularization and overtime writes keep the plain attendance-date `_ensure_date_open` check
unchanged, as specified. Verified by code inspection.

**Ordering note.** `FuturePunchTimeError` (`DEC-TZ-03`) is evaluated *before* the period-lock check.
Discovered while probing: the gate's §10.2 walk uses 30 Sep / 1 Oct 2026, which is in the future
relative to today (2026-09-17), so those instants return `PUNCH_TIME_IN_FUTURE` and never reach the
lock. The table above relocates the identical boundary walk onto the 31 Aug → 1 Sep boundary to
isolate the mechanism under test. This ordering is correct, not a defect.

---

## 18. UI Validation

**PASS with one defect — see `D1` in §22.**

The completion report listed live browser verification as **not possible** (ports occupied). It was
performed for this validation: both dev servers started cleanly, and the app was driven in a real
browser against the real API.

### 18.1 Live attendance day-detail page

Attendance day `2026-09-15` for an `Asia/Kolkata` tenant, stored `03:35Z` / `12:50Z`:

```
Attendance day
2026-09-15 — Asia/Kolkata (IST)          <- dual-zone header, gate §13.2
SCHEDULED      15 Sept 2026, 09:00 IST – 15 Sept 2026, 18:00 IST
FIRST IN       15 Sept 2026, 09:05 IST
LAST OUT       15 Sept 2026, 18:20 IST
CALCULATED AT  17 Sept 2026, 14:02 IST
```

**Every rendered attendance timestamp carries an explicit `IST` label**, and every conversion from
the stored UTC instant is correct.

### 18.2 Screen-by-screen coverage against gate §13.2

Every screen the gate lists was checked for formatter call sites missing the required `tz` argument:

| Screen | `formatClockTime`/`formatDateTime` calls | Missing `tz` | `businessToday` |
|---|---|---|---|
| Attendance day detail | 8 | **0** | — |
| Regularization detail | 7 | **0** | — |
| Leave application detail | 5 | **0** | — |
| Attendance period detail | 4 | **0** | — |
| Overtime detail | 3 | **0** | — |
| Employee attendance panel | 3 | **0** | 2 |
| Leave balances | 2 | **0** | — |
| Create-period dialog | — | — | 2 |
| Policy resolution | — | — | 2 (duplicate private helper deleted) |

`tz` is a **required** parameter, so TypeScript enforces this — `npx tsc --noEmit` is clean.
`todayIso()` is deleted; no production call site remains (only historical references in comments).
A repo-wide sweep found no surviving `toLocaleTimeString`/`toLocaleString` on an attendance path
without an explicit `timeZone`.

### 18.3 Viewer-timezone independence

`formatClockTime`/`formatDateTime`/`businessToday` all take the zone explicitly and never read
`Intl.DateTimeFormat().resolvedOptions().timeZone`. `format.test.ts` asserts this directly —
including `formatClockTime(instant, "Asia/Kolkata") === "09:05 am IST"` and
`businessToday("Asia/Kolkata") === "2026-10-01"` at `2026-09-30T19:00Z` — and the whole web suite
(356 tests) passes under `TZ=America/New_York` and `TZ=Pacific/Kiritimati`.

**Limitation, stated plainly.** The in-app browser inherits the host timezone (`Asia/Calcutta`), and
no timezone-override API is available on this surface, so the *viewer-physically-in-another-zone*
case could not be exercised in a live browser. It is covered by the vitest suite run under two
non-IST timezones and by the required-`tz` signature. The pages are `"use client"`, so rendering
happens in the browser with an explicit `timeZone` option.

---

## 19. Mobile Validation

**NOT APPLICABLE.** No mobile application exists in this product. `apps/` contains exactly two
workspaces, `api` and `web`; a repository-wide search for mobile/Android/iOS projects found none.
Mobile attendance is listed as **Deferred** in the gate's §0 category table. Nothing was introduced,
and no offline attendance was added.

---

## 20. Database Integrity

**PASS.** All queries read-only against the dev database; no production system was contacted and no
data was mutated by these checks.

| Check | Result |
|---|---|
| Timestamp column types across `punch`, `attendance_day`, `attendance_break`, `attendance_period`, `overtime_record` | **every instant column is `timestamp with time zone`** — 27/27 ✅ |
| Unexpected naive timestamps | **none possible** — no `timestamp without time zone` column on any attendance table ✅ |
| Duplicate `attendance_day` rows | **0 duplicate groups** ✅ |
| Uniqueness constraint | `attendance_day_unique UNIQUE (company_id, employee_id, attendance_date)` present ✅ |
| Stored timezone values valid | Only `Asia/Kolkata`, `Asia/Calcutta`, `UTC` — **all loadable IANA zones** ✅ |
| Historical rows intact | Byte-identical before/after the §12 timezone-change attempt ✅ |
| Punch instant sanity | earliest `2026-08-10T09:00Z`, latest `2026-09-15T12:50Z` — no `1900`/`2099` rows ✅ |
| `punch.source` distribution | `ADMIN` 18, `REGULARIZATION` 8 — **never a client-supplied value** ✅ |
| `punch.raw_payload` | **0 of 26 rows written** — confirms the `B8` deferral is real, not assumed ✅ |

### 20.1 Dev-database timezone inventory (this is **not** `B4`)

| Entity | Value | Count | Validity | Recommended action |
|---|---|---|---|---|
| `company` | `Asia/Kolkata` | 434 (2 ACTIVE, 432 TRIAL) | valid | none |
| `company` | `Asia/Calcutta` | 3 (all TRIAL) | valid legacy alias | canonicalise — safe: **0** attendance days, **0** closed periods each |
| `branch` | `NULL` (inherits) | 103 | valid | none |
| `branch` | `UTC` | 11 | valid | test fixtures |
| `branch` | `Asia/Kolkata` | 3 | valid | none |
| `shift_version` | `UTC` | 11 | valid | test fixtures |
| `shift_version` | `NULL` (inherits) | 7 | valid | none |
| `shift_version` | `Asia/Kolkata` | 1 | valid | none |
| `attendance_day` | `UTC` | 10 | valid | test fixtures |
| `attendance_day` | `Asia/Kolkata` | 1 | valid | none |

This matches the completion report's `DH-1` inventory. **It says nothing about production.**

---

## 21. Production Blockers

| ID | Blocker | Verifiable here? | Status |
|---|---|---|---|
| **`B4`** | Production timezone inventory | **No** | **G. EXTERNAL BLOCKER — OPEN** |
| **`B5`** | Old punch endpoint usage in production access logs | **No** | **G. EXTERNAL BLOCKER — OPEN** |
| **`B8`** | PII retention sign-off for `punch.raw_payload` | **No** | **G. EXTERNAL BLOCKER — OPEN** |

### `B4` — production timezone inventory

**Cannot be produced from this environment.** No production or staging connection string, deployment
manifest, or infrastructure-as-code exists in the repository — only `docker-compose.yml` and local
`.env` files pointing at `localhost:5433`. The inventory in §20.1 is the **dev** database and must
not be mistaken for production's state. No production timezone value was modified.

The query to run against production, read-only, when access is available:

```sql
SELECT 'company' AS entity, id::text, name, timezone, status FROM company
UNION ALL SELECT 'branch', id::text, name, timezone, NULL FROM branch WHERE timezone IS NOT NULL
UNION ALL SELECT 'shift_version', id::text, NULL, timezone, NULL FROM shift_version WHERE timezone IS NOT NULL
UNION ALL SELECT 'attendance_day', company_id::text, NULL, timezone, NULL FROM attendance_day
ORDER BY 1, 4;
```

### `B5` — old punch endpoint usage

**Cannot be checked from this environment.** No production access logs exist here; `.dev-logs/` holds
684 bytes of local development output from 2026-09-03 with **zero** punch requests.

What *is* established: **the only in-repository caller** is `punch-entry-dialog.tsx`, and it already
posts the new shapes (`/attendance/punches/me` for self, `/attendance/punches` for on-behalf). No
mobile app, SDK, or third-party integration exists in this repository. Any third-party caller of the
old single-endpoint shape would be external and invisible here.

**The breaking change is real and unchanged:** `POST /attendance/punches` still exists but now
requires `employee_id`, `punch_time`, **and** `reference`, forbids `source`, and is gated by
`ATTENDANCE.PUNCH_ON_BEHALF` instead of resolving the permission from the body. A caller holding
only `ATTENDANCE.PUNCH` now receives a clean 403.

### `B8` — PII retention sign-off

**BLOCKED — EXTERNAL APPROVAL REQUIRED.** No retention period was invented or selected by this pass.

- `punch.raw_payload` is declared in the schema and **never written** — verified twice: by `grep`
  across `modules/attendance/` (model declaration only) and by SQL (0 of 26 rows populated).
- `ATTENDANCE_TIMEZONE_CLIENT_APPROVAL.md` contains **no `B8` entry, no retention clause, and no
  mention of `raw_payload`** — there is no artefact in this repository recording the decision, in
  either direction.

---

## 22. Failures and Defects

### `D1` — On-behalf punch time field labelled IST but read in the viewer's browser timezone

```text
DEFECT FOUND

Location:      apps/web/src/components/attendance/punch-entry-dialog.tsx:34-39 (seeding),
               :119 (submission), :176 (the "(IST)" label)
Classification: C. NEW TIMEZONE REGRESSION (the misleading label is new in Phase 6;
               the browser-zone value interpretation is pre-existing)
Severity:      MEDIUM-HIGH — feeds worked_minutes / late_minutes / OT, therefore payroll
```

**Root cause.** The admin-mode field is an `<input type="datetime-local">`. Its value is a *bare
wall-clock string with no zone*, and `new Date(punchTime).toISOString()` (line 119) resolves it
against the **browser's** timezone. `nowForDatetimeLocal()` (lines 34-39) likewise seeds it from
`getTimezoneOffset()`, i.e. the viewer's clock. Phase 6 relabelled the field
**`"Punch time (IST)"`** without changing either.

**Failure scenario — measured, not derived.** An HR admin types `09:00` on `2026-09-15` under a
label that says IST:

| HR admin's browser timezone | Instant actually sent | Recorded as |
|---|---|---|
| `Asia/Kolkata` | `2026-09-15T03:30:00Z` | **09:00 IST** ✅ |
| `UTC` | `2026-09-15T09:00:00Z` | **14:30 IST** — 5h30m wrong |
| `America/New_York` | `2026-09-15T13:00:00Z` | **18:30 IST** — 9h30m wrong |
| `Pacific/Kiritimati` | `2026-09-14T19:00:00Z` | **00:30 IST** — wrong time **and** the punch lands on the previous IST date |

**Acceptance criterion violated.** Gate §13.2: *"Punch entry dialog … Admin mode: `IST`, labelled."*
Only the *labelled* half shipped. Gate §13.1's principle — *no attendance timestamp is interpreted
in the viewer's browser timezone* — is defeated on the one screen that **writes** an attendance
instant rather than reading one.

**Why this is not merely cosmetic.** Every other Phase 6 change made the viewer's zone irrelevant by
passing `tz` explicitly. This is the one remaining place where the viewer's zone still determines a
**stored, payroll-bearing** value — and it now does so *behind a label asserting otherwise*, which
is worse than the unlabelled pre-existing behaviour, because an admin who notices the label will
trust it.

**Proposed fix (not applied).** Treat the `datetime-local` value as an IST wall time and convert
explicitly, mirroring the read path's required-`tz` design rather than relying on the host clock:

```ts
// Convert an IST wall-clock string to the correct UTC instant, independent of the viewer's zone.
function istWallTimeToUtcIso(local: string, tz: string): string { /* … */ }
// and seed the field from businessToday(tz) + the current IST wall time, not getTimezoneOffset()
```

**Regression tests required.**
1. Unit: the converter maps `"2026-09-15T09:00"` + `Asia/Kolkata` → `2026-09-15T03:30:00.000Z`
   under `TZ=UTC`, `America/New_York` and `Pacific/Kiritimati` (mirrors `format.test.ts`'s own
   "never falls back to the viewer's timezone" pattern).
2. Unit: the seeded default equals the current **IST** wall time under a non-IST runner `TZ`.
3. Integration: an on-behalf punch submitted from a non-IST browser lands on the intended IST
   attendance date.

**Remediation required before production: YES** — it is inside the approved scope (gate §13.2 names
this exact file and requires IST in admin mode). **Not fixed by this pass**, per the validation
brief's stop-and-report rule; it needs an explicit go-ahead.

---

#### `D1` — CLOSED (2026-09-17, follow-up session)

```text
Original status:    FAILED (D1, above)
Fix implemented:    apps/web/src/lib/attendance/format.ts — two new exported functions:
                       wallTimeToUtcIso(datetimeLocal, tz)       — explicit-zone conversion
                       nowInZoneForDatetimeLocal(tz)             — explicit-zone seeding
                     apps/web/src/components/attendance/punch-entry-dialog.tsx —
                       replaced new Date(punchTime).toISOString() with
                       wallTimeToUtcIso(punchTime, punchTz), punchTz sourced from
                       user?.company_timezone ?? "Asia/Kolkata" (same pattern already used by
                       employee-attendance-panel.tsx); replaced the getTimezoneOffset()-based
                       nowForDatetimeLocal() seed with nowInZoneForDatetimeLocal(punchTz); label
                       changed from the hard-coded "Punch time (IST)" to
                       `Punch time (${zoneLabel(punchTz)})`, using the same zoneLabel() helper
                       Phase 6 already built, so the label can never again assert a zone the code
                       does not actually use.
Regression tests:   apps/web/src/lib/attendance/format.test.ts — 6 new tests: exact conversion
                       (09:00 IST -> 03:30:00.000Z UTC) identical under 4 process timezones
                       (Asia/Kolkata, UTC, America/New_York, Pacific/Kiritimati); the near-
                       midnight case (00:30 IST, 15 Sept) does not cross the IST calendar-date
                       boundary under any of the 4; round-trip through formatClockTime; rejects
                       a malformed value; nowInZoneForDatetimeLocal is TZ-independent.
                     apps/web/src/components/attendance/punch-entry-dialog.test.tsx — new file,
                       6 tests driving the REAL component (form input -> submit -> apiClient.post
                       payload), including an it.each over the same 4 process timezones proving
                       the exact same request body is sent regardless, the near-midnight case at
                       component level, and a self-mode test confirming no punch_time field is
                       sent on that path (unaffected by this change).
                     All 12 new tests pass. Full web suite: 368/368 pass (up from 356 — the 12
                       new tests), reproduced under all 4 process timezones (was 356/356 x4).
Backend regression: No backend file was touched (frontend-only fix). Re-ran the full timezone-
                       relevant backend subset (tests/unit + tests/integration/modules/attendance
                       + test_timezone_change_guard.py + tests/unit/shared) under TZ=UTC:
                       188/188 pass — identical to the pre-fix baseline. Naive-timestamp
                       rejection, invalid-timezone rejection, period-lock basis, and historical-
                       integrity guard are all unchanged (D1 was a client-side value-conversion
                       bug only; the backend already validated/bounded whatever instant it
                       received). Full backend suite re-run: 1228 passed / 19 failed — the exact
                       same 19 pre-existing, unrelated failures as the original validation pass
                       (§5.2), zero new failures.
Browser verification: Live end-to-end, real browser (Chromium) + real API + real Postgres, host
                       zone Asia/Kolkata (the in-app preview browser's real OS zone, confirmed via
                       Intl.DateTimeFormat().resolvedOptions().timeZone === "Asia/Calcutta"):
                       opened the on-behalf "Record punch" dialog on the seeded employee, entered
                       "2026-09-16T09:00" under the field labelled "Punch time (IST)", submitted,
                       and captured the actual POST /v1/attendance/punches response:
                       punch_time = "2026-09-16T03:30:00Z" — exactly 09:00 IST, byte-correct.
                       The resulting attendance_day row's scheduled_start (2026-09-16T03:30:00Z)
                       confirms the shift resolved against the same, correct instant.

                       LIMITATION, stated plainly: this preview surface has no timezone-override
                       capability (no OS-level TZ change, no CDP Emulation.setTimezoneOverride
                       exposed by the available tools) — the same limitation already documented
                       in the original validation report's UI section. A direct attempt to
                       simulate other "browser timezones" by monkey-patching
                       Date.prototype.getTimezoneOffset in the live page was tried and found NOT
                       to work: Chromium's internal Date-string parser does not consult that
                       method (it resolves against the process's own ICU-baked zone), so the
                       patch had no effect on either the old or new code path — confirmed
                       directly, recorded here rather than silently discarded. What DOES
                       genuinely honor a runtime-mutated zone, verified directly with `node -e`
                       against the exact old buggy expression before treating it as evidence, is
                       process.env.TZ under Node's V8 engine — the same engine family (and the
                       same explicit-Intl-timeZone / ambient-Date-parsing split) Chromium uses.
                       That is what the component test above already exercises, in the real
                       component tree, not just the pure function — the closest available
                       substitute for a genuine multi-timezone browser matrix on this surface,
                       and the reason the live-browser check above is a confirmation of the
                       real-zone case rather than a fourth redundant data point.
Final status:        CLOSED
```



```text
Location:      apps/api/src/hrms/modules/attendance/router.py:11-14
Classification: D. NEW UNRELATED FAILURE (documentation, inside the changed file)
Severity:      LOW — documentation only, zero behavioural impact
```

**Expected.** The module docstring should describe the current two-route design.
**Actual.** It still says:

> *"`POST /attendance/punches`'s gating permission depends on whether the caller is punching for
> themselves or on behalf of someone else, so … it cannot be a static
> `Depends(require_permission(CODE))` and instead calls `rbac.resolve_data_scope()` directly."*

That is precisely the behaviour Phase 1 **removed** (`ED-4`). Both punch routes now use static
`Depends(require_permission(...))`, as their own function docstrings 740 lines below correctly
explain. A reader of the file header is told the opposite of what the code does — on a security
control.

**Remediation required: recommended, not blocking.** Trivial text edit; not applied by this pass.

---

### `D3` — `TZ-06` partially remediated: two of four named call sites remain

```text
Location:      apps/api/src/hrms/modules/leave/service.py:1979, :2597
Classification: B. PRE-EXISTING FAILURE — outside the approved remediation scope
Severity:      LOW-MODERATE
```

The audit's `TZ-06` finding names **four** `date.today()` call sites:
`attendance/service.py:3502`, `:3547`, `leave/service.py:1979`, `:2597`. The implementation plan's
own file-by-file table (lines 1335-1337) scopes only the **two attendance** sites, and gate §3.3
restricts the leave work to *"exclusively … the scheduled job call sites"* with *"no leave policy
changes."* Both attendance sites were correctly fixed. The two leave sites were not.

| Site | Use | Impact under `TZ=UTC` |
|---|---|---|
| `leave/service.py:1979` | `max_backdated_days` window on leave-application submit | Between 00:00 and 05:29 IST the window is computed one day behind |
| `leave/service.py:2597` | `effective_date` of the reversal ledger entry when an approved leave is cancelled | Same band → the ledger entry carries yesterday's business date |

**This is correctly classified as pre-existing and out of scope, not a regression** — the
implementation did exactly what the plan scoped. But `TZ-06` should not be recorded as *closed*:
half of it is still open. Recommend tracking it as leave-module debt with the same
`business_today(company.timezone)` fix.

---

### `D4` — Completion report's `ruff check` claim does not reproduce under CI's own command

```text
Location:      docs/audits/ATTENDANCE_TIMEZONE_IMPLEMENTATION_COMPLETION_REPORT.md §8
Classification: F. REQUIREMENT AMBIGUITY / reporting inaccuracy
Severity:      LOW for timezone correctness; MEDIUM for CI trust
```

**Expected** (report §8): *"Backend `ruff check` → All checks passed!"*
**Actual:** `ruff check .` — the exact command in `ci.yml` — reports **15 `E501` errors**.
`ruff check src tests entrypoints` does pass, which is evidently what was measured.

All 15 are in `alembic/versions/`: 12 in committed migrations untouched since `dbd3f43` (verified),
3 in the new unrelated RBAC migration. **None is in the timezone diff.** The consequence is not a
timezone regression but a CI one: **the lint gate does not currently pass on this tree**, and the
report states that it does. Likewise, the report's "7 files need reformatting" is now 18 — again
entirely from the unrelated workstreams.

**Remediation required: not for timezone.** The report's §8 numbers should be corrected, and the
`alembic` lint debt resolved (or `alembic/versions` explicitly excluded in `pyproject.toml`) before
CI is treated as a green gate.

---

### `D5` — Gate §3 is internally inconsistent about the number of leave call sites

```text
Location:      ATTENDANCE_TIMEZONE_FINAL_DECISION_AND_EXECUTION_GATE.md §3.1 vs §3.3
Classification: F. REQUIREMENT AMBIGUITY — no code defect
Severity:      INFORMATIONAL
```

§3.1 lists **three** call sites (`leave/tasks.py:36, 85, 110`); §3.2's table adds a fourth row for
`leave.run_comp_off_credit_sweep`; §3.3 then says *"the **four** call sites above."* The credit
sweep has **no `as_of` parameter** — `credit_company(company_id)` takes none, and never did
(verified against `HEAD`). The implementation fixed the three that exist. **The code is right and
the prose is wrong**; recorded so a future reader does not mistake this for an omission.

---

### `D6` — Client approval form is unsigned in-repository

```text
Location:      docs/audits/ATTENDANCE_TIMEZONE_CLIENT_APPROVAL.md
Classification: G. EXTERNAL BLOCKER (governance)
Severity:      MEDIUM for the production gate
```

The gate's §0 register records every `DEC-TZ-` decision as **SELECTED** with client approval
*"granted."* The signable artefact in the repository has **every checkbox unticked** (lines 100,
139, 179, 231, 327, 371, 403, 519-528), a blank signature line (548), and an unticked overall status
(580-582: *"☐ All required decisions approved / ☐ Approval pending"*).

The approval may well have been recorded outside the repository (email, meeting minutes). This pass
can only report what is in the repository: **no signed approval artefact exists here.** For a
production gate that depends on eight client decisions, that should be reconciled before deployment.

---

### Failures classified as PASS or otherwise resolved

| Observation | Classification |
|---|---|
| 19 backend test failures | **B. PRE-EXISTING** — unrelated RBAC workstream (§5.2) |
| 15 `ruff check .` errors | **B. PRE-EXISTING** (12) + **D. NEW UNRELATED** (3) — see `D4` |
| 18 `ruff format` files | **B. PRE-EXISTING** — unrelated modules only |
| `uv run` resolving to conda Python 3.9 | **E. ENVIRONMENT** — stale venv path after repo move (§2) |
| §10.2's own boundary instants returning `PUNCH_TIME_IN_FUTURE` | **A. PASS** — correct precedence; probe relocated (§17) |

---

## 23. Evidence

All artefacts are in the session scratchpad
(`/tmp/claude-1000/-media-varun-varun8-work-staff-spectrum-HRMS/.../scratchpad/`):

| File | Contents |
|---|---|
| `full_utc.txt` | Full backend suite, `TZ=UTC` — 1228 passed / 19 failed, with failure list |
| `tz_matrix.py` | Read-only server-TZ-independence harness (40 scenarios) |
| `out_UTC.json`, `out_Asia_Kolkata.json`, `out_America_New_York.json`, `out_Pacific_Kiritimati.json` | Harness output per timezone — diffed identical |
| `tzsuite_{TZ}.txt` | 610-test subset under four timezones |
| `probe_{TZ}.txt` | API probe suite under four timezones, with `[EVIDENCE]` lines |
| `probe.txt`, `probe2.txt`, `probe3.txt`, `probe4.txt` | Individual probe runs (timezone security, clock policy, period lock, concurrency, scheduled task, non-blocking calculation) |
| `web_{TZ}.txt` | Vitest under four timezones |
| `validation_probe_archived.py` | The probe test module, archived |
| `ui_seed.py`, `ui_seed_out.json` | Live-UI tenant seed and its computed attendance day |

**The probe test module was written under `tests/integration/modules/attendance/`, executed, and
then deleted.** It is not part of the repository; `git status` confirms `tests/` is back to its
pre-validation state. No shipped test was modified, relaxed, or deleted to make anything pass.

---

## 24. Regression Assessment

**No timezone regression was introduced.**

| Dimension | Finding |
|---|---|
| Backend test count | 1228 passed / 19 failed — **identical** to the documented baseline; no growth in the failure count |
| Failure attribution | 19/19 traced to an unrelated workstream's helper assumption; 0/19 in any file this programme touched |
| Web test count | 356 passed (up from the 342 baseline, from `format.test.ts` expansion) — **no regressions**, under four timezones |
| Type safety | `mypy` clean on 134 files; `tsc` clean |
| Module boundaries | import-linter 1 kept, 0 broken |
| Engine determinism | Business results byte-identical across four server timezones |
| **Previously-correct break case (I5)** | `01:00–02:00` after-midnight break still matched and paid — **the rejected Approach B would have broken this; Approach A does not** |
| Period-lock direction of change | Only ever *loosens* at the 00:00–05:29 IST boundary; every case the UTC basis accepted is still accepted; both-dates-closed still fails closed |
| Historical rows | Byte-identical before and after an attempted timezone change, and after recompute |
| Schema | No migration added by this programme; no attendance column altered |

**One new defect (`D1`) was found in Phase 6's own diff**, on the punch-entry *write* path. It is a
gap in the remediation, not a regression of previously-correct behaviour — the value has always been
read in the browser's zone; Phase 6 added a label that now asserts otherwise.

> **Update, 2026-09-17 follow-up session: `D1` is now CLOSED.** See §22's `D1` closure block for
> the fix, the 12 new regression tests (6 unit + 6 real-component), the unchanged backend baseline
> (188/188 timezone-relevant, 1228/19 full suite — identical to this report's original numbers),
> and the live-browser confirmation. §24's paragraph above and the gate/recommendation below are
> left as originally written, with this note and the updated checklist as the record of what
> changed and when — the audit trail is additive, not rewritten.

---

## 25. Final Gate

```text
[x] Automated tests completed              1228 passed / 19 failed (all pre-existing, unrelated)
[x] No new timezone regression             verified across 4 server timezones, 3 levels
[x] Server timezone independence verified  engine, suite and API — byte-identical
[x] Normal attendance verified             day shift, late/early, overtime, end-to-end + live UI
[x] Night shift verified                   22:00-06:00, full 00:00-05:29 IST boundary walk
[x] Cross-midnight breaks verified         F-05 fixed; the 01:00-02:00 regression guard holds
[x] Timezone validation verified           IST -> 422, not 500; allow-list enforced server-side
[x] Client timestamp policy verified       self route has no punch_time/source/employee_id field
[x] Naive datetime handling verified       naive, date-only, epoch int and epoch float all 422
[x] Future punch handling verified         +1s / +90s / +1h / 2099 all 422; no tolerance window
[x] Historical integrity verified          409 TIMEZONE_CHANGE_BLOCKED; rows byte-identical
[x] Leave scheduled jobs verified          3 jobs fixed at their real Beat instants; 4th needs none
[x] Attendance scheduled calculation verified  09:30 IST, trailing 3 days, duplicate-safe
[x] Immediate calculation verified         non-blocking; sweep recovers a failed attempt
[x] Concurrency verified                   10 and 20 concurrent requests -> exactly 1 row, no 500s
[x] Period lock verified                   DEC-TZ-05 boundary table reproduced exactly
[x] UI timezone verified                   READ path PASS; WRITE path FIXED 2026-09-17 -- D1 CLOSED
[x] Database integrity verified            all timestamptz; 0 duplicates; all zones valid IANA
[ ] Production timezone inventory closed   B4 -- OPEN, requires production access
[ ] Old endpoint usage verified            B5 -- OPEN, requires production access logs
[ ] PII retention approved                 B8 -- BLOCKED, EXTERNAL APPROVAL REQUIRED
[ ] UAT complete                           not performed; client approval form unsigned (D6)
```

**19 of 22 gates closed (was 18/22 — `D1` closed 2026-09-17). Three remain open: `B4`, `B5`, `B8`
— plus UAT — all external/governance blockers, none closable by a code change in this repository.**

---

## 26. Recommendation

> # NOT READY FOR PRODUCTION

The engineering work this programme set out to do is, on the evidence gathered here, **correct and
substantially verified**. Every acceptance criterion in the execution gate's §0 decision register
that is testable from this repository was tested against the running application and passed, most of
them through the real HTTP API rather than through unit tests alone. The claims in the completion
report reproduce.

**`D1` — CLOSED 2026-09-17.** The on-behalf punch dialog's IST handling was fixed (§22 `D1` closure
block): a small, scoped change to two files (`format.ts`, `punch-entry-dialog.tsx`), 12 new
regression tests (all passing, including the real component's form-to-payload path under four
process timezones), zero backend changes, zero regression in either the timezone-relevant subset
(188/188) or the full backend suite (1228 passed / 19 pre-existing failures, unchanged), and a live
end-to-end confirmation against the real API and database. It was the only item on the original list
engineering could close unilaterally, and it is now closed.

Production remains blocked on three items, all genuinely external to this repository:

1. **`B4` — run the production timezone inventory.** A read-only measurement task; the query is in
   §21. Do not modify production timezone values automatically.
2. **`B5` — check production access logs for third-party callers of the old punch endpoint.** If any
   exist, Phase 1's breaking change needs a deprecation window, not a same-day cutover.
3. **`B8` — obtain the PII retention sign-off** before `punch.raw_payload` is ever wired. It is
   currently never written, so nothing is presently at risk; the approval gates the follow-up change,
   not this one.

Two further items should be resolved before treating CI as a green gate, though neither is a
timezone question: the 15 `ruff check .` failures (`D4`) and the 19 unrelated backend test failures
introduced by the RBAC workstream sharing this tree — both unchanged by the `D1` fix, since it
touched no Python file.

Finally, and separately from correctness: **the entire programme, including the `D1` fix, remains
uncommitted on `main`.** It should be committed before any deployment, so that the completion
report's own rollback plan ("revert the relevant commits") is actually executable. A file-by-file and
hunk-by-hunk separation of the timezone programme from the unrelated RBAC/account-invite/password-
reset work sharing this working tree was performed as part of this follow-up session — every file
examined was found separable (most are wholly owned by one workstream; a handful mix cleanly
separable hunks) — but no commit was created; execution requires an explicit go-ahead, consistent
with this session's standing instruction not to commit without being asked.

**READY FOR UAT.** Nothing found in this validation, at either pass, blocks staging/UAT (Phase 10).
`D1` was exactly the kind of defect a UAT pass with a non-IST reviewer would have been expected to
surface — it is now closed ahead of that pass rather than by it.

**Production remains: NOT READY FOR PRODUCTION**, gated on `B4`, `B5`, `B8`, and UAT sign-off —
none of which a code change can close.

---

*Prepared 2026-09-17. Every number, status code and computed value in this report was measured
during this session by executing the shipped code — against a live PostgreSQL 16, a live API on port
8000, and a live browser on port 3000 — not carried forward from the completion report. No
application code, schema, migration, or shipped test was modified.*

*Follow-up session, same day: `D1` fixed and verified by the same methodology (real API, real
browser, real database, four process timezones). See §22's `D1` closure block for full evidence.
Still no application code was modified beyond the two files the fix required, and no shipped test
was weakened — 12 tests were added, none removed or relaxed.*
