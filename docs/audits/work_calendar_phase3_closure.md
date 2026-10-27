# Work calendar - Phase 3 closure and verification report

Date: 2026-10-27. Scope: verify and close out the existing work-calendar implementation (guided
setup, admin calendar, employee calendar, change-impact preview/confirm). No feature was added.
Companion documents: `work_calendar_implementation_audit.md`, `work_calendar_phase2_employee_calendar.md`,
`work_calendar_phase3_change_impact.md`.

## 1. Repository state at verification

| Item | Value |
|---|---|
| Branch / HEAD | `main` / `436a2e5e35b97ae65b27f9553e2317e9b7f6f7b0` |
| Working tree | 338 changed paths at start (all uncommitted, including unrelated face, onboarding, observability, mobile work) |
| Commits / pushes / merges / deployments by this task | **None** |
| Work-calendar files | modified: `calendar_resolution.py`, 4 web pages, `work-calendar/types.ts`; new: `calendar_impact.py`, `calendar_overlay.py`, `calendar_setup.py`, `employee_calendar.py`, migration `20261029090000`, 3 integration + 1 unit test module, web `change-impact-dialog`, `day-grid`, `employee-calendar/*`, `me/calendar`, `work-calendars/setup` |

Code review of the points requested (all by reading the code, then confirming with tests, section 4):

* `GET /v1/employee-calendar/me` takes no employee/company parameter; the employee is the JWT's linked record.
* Preview (`CalendarImpactService.preview` -> `_compute`) contains only `SELECT`s; no `add/flush/commit/insert/update/delete` exists in `calendar_impact.py` or `calendar_overlay.py` outside `_apply`, which calls the existing `OrganisationService` methods.
* Confirm: per-company `pg_advisory_xact_lock` -> recompute impact -> compare SHA-256 digest -> acknowledgement check -> apply -> one `WORK_CALENDAR_CHANGE_CONFIRMED` audit row, all in the request transaction.
* Resolver and overlay: the overlay is applied in memory after rows are loaded; without an overlay the behaviour is unchanged.
* Permissions: both routes depend on `_require_calendar_change_permission` plus a per-change-type check (holiday edits `ORG.HOLIDAY.MANAGE`, the rest `ORG.CALENDAR.MANAGE`).

## 2. Reconciliation of the previous run's claims

Previous claim: 2,438 passed, 53 skipped, 7 failed; two scope-guard failures fixed; two residual rows removed; three attendance tests blocked by OpenCV.

| Claim | Finding |
|---|---|
| Two scope-guard failures fixed | Confirmed: `tests/unit/core/test_scope_enforcement_guard.py` passes in the unit tier. |
| Two residual rows | Not independently reproducible (new database). |
| Three attendance tests blocked by missing OpenCV | Confirmed, with cause below, and now **rerun and passing**. |
| 7 failed in total | Incomplete accounting. In this run, the current tree also had a **different real failure** (section 3, route authorization matrix) that the claim did not mention. |

### OpenCV
* Declared in `apps/api/pyproject.toml` as optional extra `liveness` (`opencv-python-headless>=4.10,<5`) and pinned in `uv.lock` (4.14.0.94). The Dockerfile installs it with `uv sync --frozen --no-dev --extra liveness`. The `dev` extra and `dependency-groups.dev` do not include it, and `.venv` (used by the QA runner) has neither `cv2` nor `numpy`.
* It is therefore an **optional runtime dependency that the documented test procedure (`.venv` + `stack.sh`) does not install**. Result: 3 tests fail with `ModuleNotFoundError: cv2` and 13 more skip via `importorskip`, so the face/liveness suite is silently weaker on a default developer setup.
* Not changed: no production dependency, `pyproject.toml` or `uv.lock` change was made. (`pyproject.toml`/`uv.lock` already carry unrelated uncommitted edits from earlier work.)
* How it was rerun, safely: wheels from the local uv cache (`uv pip install --offline --target <scratch>`: opencv-python-headless 4.14.0.94 as locked, numpy 2.5.4; the locked numpy 2.5.2 was not in the cache, so a newer patch release was used), copied into the disposable run's `/artifacts` mount, and exposed through the harness's `QA_EXTRA_ENV=PYTHONPATH=/artifacts/cvdeps`. Repo, shared `.venv` and lockfile untouched.
* Result: `tests/unit/modules/attendance` 320 passed (includes the 3); whole unit tier 1388 passed, 40 skipped.
* Recommendation (product/engineering decision, not made here): add `liveness` to the documented test setup (`uv sync --extra dev --extra liveness`) or make the QA runner install it, so these tests are not skipped.

## 3. Regression results (disposable stack `cal3-20261027a`)

Stack: `stack.sh up` -> `guard` (ISOLATION PROVED) -> `migrate` (single head `20261029090000`).

A single `pytest tests` process was **OOM-killed (exit 137) at ~39 %** because the harness caps the runner at 1,536 MB. That was a resource limit, not a test failure; the harness was not changed. The suite was therefore run in 15 per-directory chunks, each in a fresh runner (`pytest <dir> -q -p no:cacheprovider -rfEs`):

| Chunk | Result |
|---|---|
| `tests/unit` (no OpenCV) | 1372 passed, 53 skipped, **3 failed** (OpenCV) |
| `tests/unit` (with OpenCV) | **1388 passed, 40 skipped, 0 failed** |
| `tests/security` | first run 38 passed, 22 errors (FK on deleting `plan` rows referenced by `subscription`); **rerun 38 passed, 0 errors** |
| `tests/integration/auth` | 60 passed |
| `tests/integration/core` | 107 passed, 1 skipped |
| `tests/integration/migrations` | 7 passed |
| top-level integration (6 files) | first run **1 failed** (route authorization matrix); final run **31 passed** |
| `modules/account_invite` | 91 passed |
| `modules/attendance` | 395 passed |
| `modules/employee` | 398 passed |
| `modules/employee_import` | 17 passed |
| `modules/leave` | 259 passed |
| `modules/onboarding` | 156 passed |
| `modules/organisation` | first 344 passed; **final 345 passed** (after the new test) |
| `modules/payroll` | 72 passed |
| `modules/platform` | 28 passed |

Final tally on the final tree (best result per chunk, no chunk failing): 1388 + 38 + 60 + 107 + 7 + 31 + 91 + 395 + 398 + 17 + 259 + 156 + 345 + 72 + 28 = **3,392 passed, 41 skipped, 0 failed, 0 errors**. All of it was assembled from chunked runs on different moments of the working tree; it is **not one single uninterrupted run**. Chunks other than organisation, security and top-level were run before the two small edits below (a `typing.cast` and a test file), which cannot change their behaviour.

Skips: 18 `test_host_monitor.py` (needs bash and jq) and others in the unit/core tiers; none are calendar tests.

### Failures found and what was done
1. **`test_route_authorization_matrix.py::test_only_known_routes_pick_permissions_imperatively` failed on the current tree**: the two new `work-calendar-changes` routes enforce permissions through a dependency the matrix cannot discover, so it reported them as "authenticated-but-ungated". They are gated (proven by `test_only_calendar_managers_can_preview_or_confirm`). Fixed in the **test registry only** (the matrix's own documented mechanism for imperative routes): the two routes were added to the known set, and a dedicated assertion was added to `test_imperatively_gated_routes` (zero-permission user gets 403 on both; either calendar permission passes the gate). No application behaviour changed.
2. **Security-tier errors (22)** appeared only in the run after the OOM kill. They did not reproduce (38 passed on rerun; no `subscription` rows remain). Cause is attributed to rows left by the killed process; I did not prove the mechanism.
3. **mypy defect in this feature**: `calendar_resolution.py:416` (`tuple[object, str]` from the memo dict). Fixed with a type-only `cast("PolicyAssignment | None", ...)`; no runtime change; the organisation chunk was rerun afterwards.

### Static checks
| Check | Result |
|---|---|
| `ruff format --check` (src, tests, alembic) | 693 files already formatted |
| `ruff check` (src, tests, alembic) | 5 `E501` in five **older, untouched** migrations (`20261007090000`, `20261008090000`, `20261019090000`); none in work-calendar files |
| `mypy` (strict, `packages = hrms`) | Before: 7 errors. With OpenCV on the path: 3; after the `cast`: **2, both in `attendance/service.py` (lines 6143-6144, `_PeriodScope` vs `DataScope` reuse of the variable `scope`)**. Not calendar code; not changed. The 5 `cv2`/`numpy` import errors are the same missing optional dependency. |
| `lint-imports` | 1 contract kept, 0 broken |
| `tsc --noEmit` | exit 0 |
| `vitest run` | 71 files, **570 passed** |
| `eslint` on the whole web app | exit 1, **112 errors**. The 11 in the calendar screens are the same `react-hooks/set-state-in-effect` pattern (`useEffect(() => { void load(); }, [load])`) as ~100 other pre-existing screens; plus `react/no-unescaped-entities` elsewhere and two in `Krewoxa landing page system/support.js`. The feature did not introduce a new class of lint error, but lint is **not clean** and this report does not claim it is. |
| Migration `20261029090000` | Disposable-DB round trip: 14 HR_ADMIN grants (7 system roles x 2 codes) -> downgrade 0 -> upgrade 14 -> second `upgrade head` no-op; single head. No automated test covers this data migration. |

### New regression test added
`test_confirmed_change_leaves_leave_locked_attendance_and_payroll_untouched` (in `test_calendar_impact.py`). Seeds an approved leave application, an `attendance_day` locked into a `CLOSED` attendance period and a `FINALISED` pay run; takes a full-row md5 of every column of `leave_application`, `leave_application_day`, `leave_ledger`, `attendance_day`, `attendance_period` and `pay_run`; asserts it is identical after **preview** and after an **acknowledged confirm** of a holiday on that date, and that the new holiday is live. It exists because the earlier tests compared only counts for `attendance_day` and hashes for the period/pay run, and never re-hashed leave days after a confirm.

## 4. Change-impact invariants

| # | Invariant | Evidence |
|---|---|---|
| 1 | Preview performs no business-data writes | Code: only `SELECT`s. Tests: `test_holiday_preview_..._writes_nothing`, `test_..._reported_and_not_modified` and the new hash test (state identical after preview). |
| 2 | Confirm rechecks the digest, rejects stale previews | `test_stale_preview_is_rejected_and_a_forged_digest_is_not_accepted`, `test_stale_entity_version_is_rejected` (409 `CALENDAR_PREVIEW_STALE` / `STALE_RESOURCE`). |
| 3 | Concurrent confirm cannot apply twice | `test_concurrent_confirmations_apply_exactly_once` (4 simultaneous: exactly one 201, one holiday, one audit row), `test_confirm_applies_once_audits_once_and_repeats_are_refused`. |
| 4 | Failed confirm rolls back, no misleading success audit | `test_failure_after_apply_rolls_back_the_whole_change`: audit recording is forced to fail; asserts the holiday and `HOLIDAY_CREATED` audit rolled back, no `WORK_CALENDAR_CHANGE_CONFIRMED`, and the same preview still confirms afterwards. |
| 5 | Tenant and permission checks on both | `test_other_tenants_records_are_not_visible_or_usable`, `test_only_calendar_managers_can_preview_or_confirm`, request bodies reject `company_id` (422), and the new matrix assertions. |
| 6 | Approved leave-day snapshots unchanged | New hash test (full-row hash, after acknowledged confirm). Impact is *reported* (`LEAVE_NOT_RECALCULATED`), never recalculated. |
| 7 | Locked attendance unchanged | New hash test (locked `attendance_day` + closed period). |
| 8 | Closed payroll unchanged | New hash test and `test_protected_attendance_and_payroll_..._not_modified` (`FINALISED` pay run). |
| 9 | Protected-period impacts displayed and enforced per implemented policy | Implemented policy: **allowed with explicit acknowledgement**, not blocked. `CLOSED` attendance periods and pay runs from `INPUTS_LOCKED` through `PAID` are listed; an unacknowledged confirm is refused 422 `CALENDAR_IMPACT_ACKNOWLEDGEMENT_REQUIRED`, an acknowledged one applies the configuration only. Test: `test_protected_attendance_and_payroll_...`; UI: dialog test "requires acknowledgement". |
| 10 | Preview does not silently pick unresolved semantics | `test_holiday_on_weekly_off_stays_weekly_off_with_a_warning`, `test_weekly_off_rule_change_and_half_day_warning` (`HALF_DAY_WEEKLY_OFF`), warnings `HOLIDAY_IS_WORKING_IGNORED` / `HOLIDAY_CALENDAR_VALIDITY_IGNORED`. |

Frontend wiring checked statically: holiday create / update / activate-deactivate -> `HOLIDAY_CREATE` / `HOLIDAY_UPDATE`; work-calendar settings and links -> `WORK_CALENDAR_UPDATE`; exceptions -> `EXCEPTION_CREATE` / `EXCEPTION_UPDATE`; weekly-off pattern rules -> `WEEKLY_OFF_PATTERN_UPDATE`; `WORK_CALENDAR` / `WEEKLY_OFF` assignments -> `ASSIGNMENT_CREATE`. Direct (un-previewed) calls remain only for deactivating or reactivating a **whole** calendar / pattern and for holiday-calendar metadata, which the resolver does not read (it filters `is_active` only on holidays, exceptions and assignments); this is the documented limitation, now also listed as decision D7 below.

## 5. Browser verification - **NOT performed**

Claim withheld deliberately. Reasons:

* The repository has no browser-test harness (no Playwright/Cypress dependency, script or document).
* The disposable stack is, by design, network-less (holder container with `--network none`; nothing published), so neither the host browser nor a host-run Next.js server can reach an API/DB inside it. Making it reachable would defeat the isolation model the harness proves.
* The only running web/API (`:3000`, `:8000`) use the shared development database. Logging in, previewing and especially confirming a holiday there would write to shared development data, which this task forbids.

What was verified instead (this is **not** a browser run):
* jsdom component tests: impact dialog (preview shows previous vs proposed in text; confirm sends digest and window; acknowledgement required for leave/locked periods; stale preview shows a message and offers refresh; validation errors block confirm; lower-bound wording when the population is capped; Back closes without confirming; window change re-previews) and the employee-calendar page (month grid request, next/previous month ranges, approved/pending/half-day leave, incomplete, partial, error with retry, no-employee-record empty state, leave unavailable).
* The calendar web tests (31) were additionally run under `TZ=Pacific/Kiritimati` (UTC+14), `America/Los_Angeles`, `Asia/Kolkata` and `UTC`: all 31 pass in each, supporting "date-only values do not shift".
* Not covered by any automated test: the four admin screens dispatching the right `change_type` end to end (checked by reading the code only), loading/empty visuals of the admin calendar, and "unauthorised users cannot see admin controls" in a real browser (the API refuses them: tested).

To close this gap the owner needs to choose one: (a) a dedicated, loopback-published disposable stack for browser runs (a change to the harness isolation model), or (b) explicit approval to run the web app against a throw-away database. Until then, treat the UI as unit-tested but not browser-verified.

## 6. Product-decision register

Policies below are what the code does today, with evidence. **None is a new rule invented by this task.** "Decision needed" is for the product owner.

| # | Topic | Current behaviour (evidence) | Regression test | Decision needed |
|---|---|---|---|---|
| D1 | Half-day weekly off, leave vs attendance | Classifier returns `WEEKLY_OFF` plus `weekly_off_fraction` (0.50). Attendance uses the fraction (`attendance/calculation.py` 1054-1088: worked = full paid day, skipped = half paid / half LOP). Leave treats any `WEEKLY_OFF` as non-working (`leave/service.py` 2302-2335, only `WORKING`/`SPECIAL_WORKING` consume leave) - so leave never consumes the working half. Preview shows the fraction and warns `HALF_DAY_WEEKLY_OFF`. | `test_weekly_off_rule_change_and_half_day_warning`; attendance half-weekly-off unit tests | **Does leave on a half-day weekly off consume 0.5 day, or 0?** Until decided, leave and attendance disagree. |
| D2 | Holiday on a weekly off | Day stays `WEEKLY_OFF` with `holiday_on_weekly_off=true`; only an explicit `SUBSTITUTE_HOLIDAY` exception creates a day off. Preview mirrors it with `HOLIDAY_ON_WEEKLY_OFF`; nothing proposed. | `test_holiday_on_weekly_off_stays_weekly_off_with_a_warning`; `test_calendar_range_and_setup` | **Is a substitute day ever automatic, or always an HR-created exception?** |
| D3 | `Holiday.is_working` | Stored and editable; read by no resolver or service (the only readers are the preview's warning). A working holiday is `holiday_type = WORKING_HOLIDAY`. Preview warns `HOLIDAY_IS_WORKING_IGNORED`. | warning covered in impact tests | **Remove the column, or define it (and how it relates to `holiday_type`).** |
| D4 | Holiday-calendar `valid_from` / `valid_to` | Stored; no code in `modules/organisation` reads them for resolution; every holiday of a linked calendar applies regardless of date. Preview warns `HOLIDAY_CALENDAR_VALIDITY_IGNORED`. | warning only | **Should validity constrain resolution?** |
| D5 | Change affecting locked / closed periods | Allowed, never rewrites history, listed and requires `acknowledge_protected_impact`. No block. | protected-period test + new hash test | **Keep "allow with acknowledgement", or block edits that change dates inside closed attendance periods / finalised pay runs?** |
| D6 | Optional / restricted holidays | Working days unless the work calendar's `restricted_holidays_are_off_by_default` (PD-CAL-1); labelled in preview. | `test_optional_holiday_stays_a_working_day...`, `test_range_keeps_optional_holiday_a_working_day` | None (implemented; confirm it matches policy). |
| D7 | Deactivating a whole calendar / pattern | Not previewed and does not change resolution (inactive calendars still resolve). | none | **Should deactivation take a calendar out of resolution? If yes it needs impact preview.** |

## 7. Cleanup

* Disposable stack `cal3-20261027a` created for this task; torn down with the documented command (`stack.sh down cal3-20261027a --confirm`). Result in section 8 of the final message.
* Earlier stack `cal2-20261027a` (created by the previous task) and the shared `hrms-postgres` / `hrms-redis` / `hrms-minio` and the running dev API/web were **not touched**.
* No commit, push, merge or deployment occurred. Files changed by this task:
  * `apps/api/src/hrms/modules/organisation/calendar_resolution.py` (type-only `cast`)
  * `apps/api/tests/integration/test_route_authorization_matrix.py` (registry + assertion)
  * `apps/api/tests/integration/modules/organisation/test_calendar_impact.py` (new test)
  * this document.

## 8. Readiness for the next phase

Backend work-calendar logic: **ready**. Evidence: all backend chunks pass on the final tree, invariants 1-10 each have a test, migration round-trips.

Not ready to be called *closed*:
1. **Browser verification not done** (section 5).
2. **Lint is not clean** web-wide (112 pre-existing-pattern errors, 11 in calendar screens); mypy has 2 errors in `attendance/service.py`.
3. Decisions D1-D5 and D7 are open; D1 is a live inconsistency between leave and attendance.
4. OpenCV is not part of the default test setup, so face/liveness tests fail or skip by default.
5. The full suite was not run as one process (memory cap), and 7 leftover "Acme" companies remain in the (now removed) disposable DB from tests whose teardown I did not trace.

Mobile work can start on the **API contract** (`/employee-calendar/me`, the preview/confirm error codes), but should not assume D1, D2 or D4 are settled.
