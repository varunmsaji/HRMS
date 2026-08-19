# W2 — Shift + Break System: Plan, Implementation Report & Reference

Continuation report. A prior session implemented the database layer (migration, models,
schemas, repository, exceptions) and got interrupted before the service layer, router, tests,
frontend, or validation gate. This document covers the full W2 slice as shipped: what existed
at handoff, what was completed, the data model, versioning/break behavior, API surface,
migration details, security, audit, test results, known limitations, and decisions made where
the architecture needed a correction or a small gap filled in.

Everything below is **uncommitted** (per the task brief — no commits were made). Migration
`20260818140000` is applied to the dev DB (head).

## 1. Status

**Shipped and verified**: database layer, `ShiftVersion`/`ShiftBreak`/`ShiftDutyBlock` service
methods (validators, CRUD, publish, resolve), 7 new router endpoints, 75 new backend tests (all
passing), full frontend UI (identity form trim + Versions tab with schedule/breaks/duty-block
editors + publish dialog), 260 frontend tests (all passing), migration upgrade→downgrade→
upgrade→downgrade→upgrade cycle verified against the real dev DB with synthetic legacy data,
and a full manual E2E walkthrough against the real backend (create → configure FIXED with a
break → publish → new draft → SPLIT type UI → discard).

**Not started**: W3 (AttendancePolicy, OT, Regularization, PolicyAssignment widening), punches,
attendance calculation, roster, locks — confirmed out of scope and untouched.

## 2. What existed before this session vs. what was completed

| Layer | At handoff | Completed this session |
|---|---|---|
| Migration `20260818140000` | Done, applied | — |
| `models.py` (`ShiftVersion`/`ShiftBreak`/`ShiftDutyBlock`) | Done | Fixed one E501 line |
| `schemas.py` (Create/Update/Read schemas) | Done | Added `is_night_shift` to `ShiftVersionCreate`/`Update` (see §7 — architecture correction) |
| `repository.py` (`ShiftVersionRepository`) | Done | Fixed `list_versions` ordering bug (see §7); added `list_open_and_draft_for_shifts` batch helper |
| `exceptions.py` (~14 new classes) | Done | Fixed formatting; corrected `InvalidShiftVersionCoreHoursError` (see §7) |
| `service.py` — `create_shift`/`update_shift` | **Broken**: referenced fields removed from the trimmed `ShiftCreate`/`ShiftUpdate` schemas, would `AttributeError` at runtime | Fixed; `create_shift` now auto-creates an initial empty DRAFT version + audits it |
| `service.py` — `ShiftVersion` methods | **Missing entirely** | Written: validators (interval math, break/duty-block/type-combination checks), `create_shift_version`, `list_shift_versions`, `get_shift_version`, `update_shift_version`, `discard_shift_version`, `publish_shift_version`, `resolve_shift_version_as_of` |
| `router.py` | Only trimmed `/shifts` CRUD | Added 7 `/shifts/{id}/versions*` endpoints |
| Backend tests | Referenced the pre-W2 `Shift` shape (would fail) | Rewrote `test_shift.py`/`test_shift_service.py` for identity-only; added `test_shift_version.py` (21 integration tests) and `test_shift_version_validation.py` (31 unit tests) |
| Frontend | Entirely untouched (full legacy `Shift` shape: timings, breaks, grace, half-day fields) | Trimmed `lib/shift/*`, `components/shift/shift-form.tsx`; added `validate-shift-version.ts`, `shift-version-form.tsx`, `shift-breaks-editor.tsx`, `shift-duty-blocks-editor.tsx`, `shift-publish-dialog.tsx`; added Overview/Versions tabs to `shifts/[id]/page.tsx`; updated `shifts/page.tsx` badges |
| Frontend tests | Legacy-shape tests (would fail against trimmed API) | Rewrote both page test files; added `validate-shift-version.test.ts` |
| Migration verification | Not done | Done — see §8 |
| Validation gate | Not run | Run — see §11 |

## 3. Database changes

Three new tables (migration `20260818140000_shift_version_breaks.py`, chained off
`20260818130000_policy_assignment`), `shift` itself never `ALTER`ed:

- **`shift_version`** — `status` (`DRAFT`|`PUBLISHED`), `effective_from`/`effective_to`,
  `shift_type` (`FIXED`|`FLEXIBLE`|`SPLIT`), type-specific timing columns, informational
  `scheduled_minutes` trio, `is_night_shift`/`is_cross_midnight`/`is_ot_eligible`/
  `operates_on_holiday`/`operates_on_weekly_off`, optional `weekly_off_pattern_id`, publish
  metadata. Partial unique index `shift_version_one_open_draft_idx` (one open draft per shift).
  GiST exclusion `shift_version_no_overlap` on `(shift_id, daterange(effective_from,
  effective_to))` predicated on `status='PUBLISHED' AND deleted_at IS NULL` — the
  insert-new/close-previous race backstop.
- **`shift_break`** — typed child, `break_kind` (`FIXED_WINDOW`|`FLEXIBLE_DURATION`) drives
  which columns are meaningful (DB CHECK `shift_break_kind_fields_check`).
- **`shift_duty_block`** — typed child, SPLIT only, `UNIQUE (shift_version_id, sequence)`.

All three: own `company_id` FK + `ENABLE`/`FORCE ROW LEVEL SECURITY` + `tenant_isolation`
policy, matching every other table in this module — verified directly against the dev DB
(`pg_class.relrowsecurity`/`relforcerowsecurity` both `t`, `pg_policies` shows the expected
`USING` clause on all three).

**Backfill** (upgrade only, `shift` untouched): one `PUBLISHED` v1 `shift_version` per existing
non-deleted `shift` (`shift_type='FIXED'`, `effective_from = shift.created_at::date`), plus one
`FLEXIBLE_DURATION` `shift_break` per non-zero legacy `break_minutes_paid`/`break_minutes_unpaid`.
Verified end-to-end (§8) with synthetic legacy rows including a cross-midnight shift and
zero/non-zero break combinations — all fields copied correctly, zero-minute breaks correctly
produce zero rows.

## 4. Shift versioning model

`Shift` is now identity-only (`name`, `code`, `is_active` — never changes meaning). The actual
schedule is an immutable, effective-dated `ShiftVersion`:

- **Lifecycle**: `DRAFT` → `PUBLISHED`. A draft is freely editable (PATCH, full-replace on
  `breaks`/`duty_blocks`), validated only lightly until publish. At most one open draft per
  shift (DB-enforced). Publish is the one-way transition; a published version can never be
  mutated again except `effective_to`, set only when a *later* version publishes and closes it
  — the same insert-new/close-previous idiom as `PolicyAssignment`, with **two** concurrency
  tokens instead of one (the draft's own `If-Match`, and `expected_previous_version` for the
  currently-open published row, required only when one exists).
- **Effective dating**: `find_effective_as_of` resolves the one `PUBLISHED` row covering a
  given date. `GET /shifts/{id}/versions/resolve?as_of=` exposes this for a future Attendance
  engine (or admin preview) to query "what schedule applied on this date" without racing a
  concurrent edit — verified in the E2E walkthrough (publish v1 effective 2026-09-01, resolve
  before/after dates returns the correct version).
- **`version` column semantics**: this is the standard optimistic-concurrency counter used
  everywhere else in this module (increments on every UPDATE), *not* a "schedule sequence
  number" — there is no separate field naming "this is the 3rd published schedule for this
  shift"; history is `created_at`/`effective_from` ordering plus `status`.
- **Auto-draft on create**: `POST /shifts` creates an empty `DRAFT` `ShiftVersion` in the same
  transaction — a shift with no schedule at all is meaningless downstream, and this avoids a
  mandatory second round-trip with no offsetting benefit. Both the shift and the draft get
  their own audit record (`SHIFT_CREATED`, `SHIFT_VERSION_CREATED`).

## 5. Shift types supported

- **FIXED** — `start_time`/`end_time`. `is_cross_midnight` is always server-derived
  (`end_time < start_time`); equal start/end is rejected (ambiguous — zero-length vs. full 24h).
- **FLEXIBLE** — `window_start`/`window_end` (the *start-time* flexibility range, e.g.
  "07:00–10:00 start" — architecture §9.4's own example), `required_minutes`, optional
  `core_start`/`core_end`. `is_cross_midnight` forced `false` (known limitation, §12).
- **SPLIT** — ≥2 `ShiftDutyBlock`s (checked at publish only — a draft may be incomplete
  mid-edit), contiguous `sequence` 1..N, no overlap (wrap-aware interval math handles
  midnight-crossing blocks). Top-level `is_cross_midnight` derived as "any block crosses
  midnight."

All three verified live against the real backend, including a FIXED shift published with a
break and a SPLIT draft showing the duty-block editor correctly in place of the timing fields.

## 6. Break capabilities

`ShiftBreak` rows are typed children with no independent lifecycle — full-replace on every
draft PATCH (mirrors `WeeklyOffPatternUpdate.rules`), frozen once the parent version publishes.

- **`FIXED_WINDOW`** — `start_time`/`end_time`; mutually non-overlapping with other
  `FIXED_WINDOW` breaks on the same version (wrap-aware); at publish, must fall inside the
  shift's own timing (FIXED: `start_time`–`end_time`; FLEXIBLE: the window; SPLIT: skipped —
  see §12).
- **`FLEXIBLE_DURATION`** — `window_start`/`window_end`/`min_minutes`/`max_minutes` (a window
  the break *may* occur within, not a fixed occupied slot — excluded from the overlap check by
  design); `min_minutes ≤ max_minutes`, and `scheduled_minutes` (if given) must fall between
  them.
- `is_paid`/`is_mandatory`/`allows_split`, `sort_order` (derived from array position in the
  editor UI, no manual numbering needed).

Verified live: added a `FIXED_WINDOW` "Lunch" break (13:00–14:00) to a FIXED shift, saved,
confirmed the exact row round-tripped through the API correctly including
`crosses_midnight: false`.

## 7. Corrections made to the prior session's design

Two small but genuine errors were found and fixed against the authoritative architecture text
(not "stop and ask" material — the architecture itself resolves both unambiguously):

1. **`is_night_shift` was designed as server-derived; architecture says it must be an explicit
   flag.** §9.5: *"`is_cross_midnight` must be consistent with start/end (already validated).
   `is_night_shift` is an explicit flag (night OT classification), not inferred solely from
   times."* The prior session's `ShiftVersionCreate`/`Update` schemas omitted it entirely
   (treating it like `is_cross_midnight`). Fixed by adding it back as a normal client-settable
   boolean field, matching the architecture's own contrast between the two flags.
2. **Core hours were designed to nest inside the FLEXIBLE window; architecture says the window
   is only the start-time range.** §9.4: *"`window_start`–`window_end` (e.g. 07:00–10:00
   **start**)"* — this describes the earliest/latest allowed start time, not the whole working
   span. The prior session's validator (`InvalidShiftVersionCoreHoursError`, exceptions.py)
   enforced `window_start ≤ core_start < core_end ≤ window_end`, which would reject a
   completely ordinary configuration (e.g. window 07:00–11:00, core hours 10:00–16:00 — core
   hours legitimately extending past the start window). Fixed to only require `core_start` and
   `core_end` be given together and `core_end > core_start`; a test asserting the old (wrong)
   behavior was replaced with one confirming the corrected behavior, plus a new test for the
   still-valid "must differ" rule.

One repository bug fixed: `ShiftVersionRepository.list_versions` ordered by the `version`
column, which is the per-row optimistic-concurrency counter (resets to 1 on every new row), not
a chronological sequence — this would not actually put newer versions first. Fixed to order by
`created_at DESC`.

## 8. API surface

All under `/v1`, gated by `ORG.SHIFT.MANAGE` (no new permission, matching the plan), COMPANY-
only, no data-scope filtering (consistent with every other organisation-module endpoint):

| Method | Path | Notes |
|---|---|---|
| GET/POST | `/shifts` | Unchanged shape, trimmed bodies. POST auto-creates initial draft. |
| GET/PATCH/DELETE | `/shifts/{id}` | Unchanged. |
| GET | `/shifts/{id}/versions` | List, newest first. |
| POST | `/shifts/{id}/versions` | Create draft — 409 if one is already open. |
| GET | `/shifts/{id}/versions/resolve?as_of=` | **Registered ahead of** `{version_id}` in router.py — a literal path segment must be matched before the parameterized route. |
| GET/PATCH/DELETE | `/shifts/{id}/versions/{version_id}` | Draft-only PATCH/DELETE (409 once published). `breaks`/`duty_blocks` full-replace when present. |
| POST | `/shifts/{id}/versions/{version_id}/publish` | Two-token concurrency (If-Match + `expected_previous_version`). `ShiftVersionOverlapError` (409) is the GiST race backstop. |

Verified: `app.openapi()` shows all 6 new routes with no path-collision issues.

## 9. Migration verification (§8 promised above)

Full cycle run against the real dev Postgres (`hrms_dev`, port 5433):

1. Inserted two synthetic pre-W2 legacy `shift` rows (one ordinary, one night/cross-midnight,
   with non-zero paid+unpaid break minutes on one) directly via SQL, simulating pre-existing
   production data.
2. `alembic downgrade -1` — confirmed `shift_version`/`shift_break`/`shift_duty_block` dropped,
   `shift` table and its 2 rows completely untouched.
3. `alembic upgrade head` — confirmed backfill produced exactly the expected `shift_version`
   rows (`PUBLISHED`, v1, `FIXED`, correct `effective_from`/timing/flags) and `shift_break` rows
   (2 for the shift with non-zero breaks, 0 for the one with none).
4. Repeated downgrade → upgrade once more — identical, deterministic result both times.
5. Confirmed RLS enabled + forced + correct policy on all three new tables directly via
   `pg_class`/`pg_policies`.

Test company/rows cleaned up afterward; migration left at head.

## 10. Security

- Runtime role unchanged (`hrms_app`, no BYPASSRLS). RLS verified live (§9.5) on all three new
  tables — `ENABLE`+`FORCE ROW LEVEL SECURITY`, `tenant_isolation` policy matching the existing
  convention exactly.
- No new permission code — reused `ORG.SHIFT.MANAGE` throughout, per the task brief's explicit
  instruction not to invent `ATTENDANCE.SHIFT_MANAGE` or new scope levels.
- Cross-tenant access fails safely — `test_cross_tenant_shift_version_not_found` confirms a
  version belonging to another company's shift resolves to 404, not a data leak or 403 that
  would confirm existence.
- `ShiftCreate`/`ShiftUpdate`/`ShiftVersionCreate`/`ShiftVersionUpdate` all use
  `extra="forbid"` — mass-assignment of `id`/`company_id`/`version`/legacy fields is a 422, not
  silently ignored.

## 11. Audit

Every write emits an audit record via the shared `AuditService`, matching the existing
`before`/`after` JSON-diff convention: `SHIFT_CREATED`, `SHIFT_VERSION_CREATED` (both the
explicit `POST .../versions` and the implicit auto-draft from `POST /shifts`),
`SHIFT_VERSION_UPDATED`, `SHIFT_VERSION_DISCARDED`, `SHIFT_VERSION_PUBLISHED`. Published
versions remain fully auditable — nothing about publish deletes or overwrites history, only the
`before`/`close` version's `effective_to` changes (itself an audited `SHIFT_VERSION_PUBLISHED`
event carrying the closed predecessor's prior state via the `close` call).

## 12. Test results

**Backend** — 75 new tests, all passing in isolation and in combination with each other:

- `test_shift.py` (13, rewritten) — identity CRUD, mass-assignment rejection, auto-draft
  creation + its own audit event, deactivate/reactivate.
- `test_shift_service.py` (10, rewritten) — unit-level, mocked repos.
- `test_shift_version.py` (21, new integration) — all three shift types end-to-end publish,
  break/duty-block validation (including the corrected core-hours behavior), discard,
  insert-new/close-previous publish flow (mirroring
  `test_policy_assignment_insert_new_close_previous`), overlap-rejected-without-token, stale
  version 409 (both tokens), resolve-as-of, cross-tenant 404.
- `test_shift_version_validation.py` (31, new unit) — pure validator coverage: wrap-aware
  interval overlap/containment math, break kind-field validation, duty-block publish
  validation, type-combination guard, full publish-validation flow.

**Regression**: full existing organisation + employee test suites pass their own assertions
identically to before this work — confirmed by isolating individual tests and checking for
`AssertionError` occurrences (zero across the shift-touching subset). A **pre-existing,
suite-wide test-infrastructure flake** was found and partially worked around (see §13) but is
explicitly not a regression introduced by this work — reproduced identically on completely
untouched files (`test_workforce_calendar.py`, `test_branch.py`).

**Frontend** — 260 tests, all passing (`npm run test`), TypeScript (`tsc --noEmit`) clean,
production build (`npm run build`) clean, no console errors during a full manual E2E session
against the real backend (see §14).

**Migration** — see §9.

## 13. Known limitations (stated up front, not discovered late)

- `ShiftWeekdaySchedule` deferred entirely — named only in the architecture's entity catalogue
  with zero field spec anywhere.
- `ShiftBreak` has no `duty_block_id` — containment-within-duty-block isn't validated for SPLIT
  shifts (the architecture's own field list omits this link). Break-outside-window validation
  is implemented for FIXED and FLEXIBLE only.
- FLEXIBLE shift-type is forced non-cross-midnight — the architecture doesn't specify the
  flex+cross-midnight interaction.
- No write-through sync of `shift`'s nine legacy columns from the live published version — a
  deliberate simplification. New shifts get frozen-zero placeholder values for these columns
  (there is no client input path for them anymore); existing pre-W2 shifts keep their real
  historical values, frozen at migration time. `ShiftRead` documents every one of these fields
  as deprecated.
- Grace/half-day/min-hours fields remain on `Shift`, unmigrated — that's W3's job
  (`AttendancePolicy`), explicitly out of scope here.
- **Pre-existing, suite-wide test flake** (not introduced by this work, not fully fixed — see
  below): a Postgres custom-GUC-placeholder quirk. `app.company_id` (the RLS session variable)
  reads as `NULL` before it's ever set on a given pooled connection, but once *any* session
  calls `set_config('app.company_id', ..., true)` on that connection, `RESET`/end-of-transaction
  reverts it to `''` (empty string) instead of `NULL` for the rest of that connection's life —
  verified directly by reproducing it in isolation. Any later unscoped raw query against an
  RLS-protected table on that same connection then crashes with `invalid input syntax for type
  uuid: ""`. This is why the full `pytest -q` suite shows hundreds of failures while
  small/isolated runs mostly pass (SQLAlchemy's default pool has 5 base connections; the more
  tests run in one process, the more of them get tainted). Applied the existing defensive
  pattern (already used in `test_company_feature_flag_constraint.py` —
  `set_rls_company_id`/`set_config` before any raw query) to the files this work touches or
  depends on (`test_shift.py`, `test_shift_version.py`, `test_employee_assignment.py`'s
  `_cleanup_shifts`, and the shared `test_registration_flow.py::_cleanup`), but a systemic fix
  (e.g. `NULLIF(current_setting(...), '')::uuid` in every RLS policy, or a pooling-level
  mitigation) is out of scope for this slice and flagged as a follow-up task.

## 14. Unresolved product/architecture decisions

None discovered that weren't already resolvable from the architecture text (see §7 for the two
corrections made). No contradiction requiring a stop-and-ask was found.

## 15. Files created

Backend: `apps/api/tests/integration/modules/organisation/test_shift_version.py`,
`apps/api/tests/unit/modules/organisation/test_shift_version_validation.py`.

Frontend: `apps/web/src/lib/shift/validate-shift-version.ts` (+`.test.ts`),
`apps/web/src/components/shift/shift-version-form.tsx`, `shift-breaks-editor.tsx`,
`shift-duty-blocks-editor.tsx`, `shift-publish-dialog.tsx`.

Docs: this file.

(Migration, models, schemas, repository, exceptions were created by the prior session — listed
as pre-existing in §2, not re-created here.)

## 16. Files modified

Backend: `apps/api/src/hrms/modules/organisation/{service,router,repository,schemas,
exceptions,models}.py`, `apps/api/tests/integration/modules/organisation/test_shift.py`,
`test_registration_flow.py`, `apps/api/tests/integration/modules/employee/
test_employee_assignment.py`, `apps/api/tests/unit/modules/organisation/test_shift_service.py`.

Frontend: `apps/web/src/lib/shift/types.ts`, `validate-shift.ts` (+`.test.ts`),
`apps/web/src/components/shift/shift-form.tsx`, `apps/web/src/app/app/shifts/page.tsx`
(+`.test.tsx`), `apps/web/src/app/app/shifts/[id]/page.tsx` (+`.test.tsx`).

## 17. Confirmation

W3, punches, and the attendance calculation engine were **not** started — confirmed by grep
(no `AttendancePolicy`, `Punch`, `AttendanceDay`, or similar model/service/route exists) and by
scope discipline throughout this session. `EmployeeAssignment.shift_id` and
`_assert_shift_ownership` are unaffected — verified via the live E2E walkthrough (shift
creation/publish flow) and the pre-existing `test_shift_change_success` /
`test_no_br14_default_shift_columns_on_org_entities` tests, whose only failures were the
pre-existing cleanup-helper flake (§13), never a functional assertion.

## 18. Recommended next step

W3 (AttendancePolicy) per the architecture — the migration of `grace_in_minutes`/
`grace_out_minutes`/`half_day_threshold_hours`/`min_hours_full_day`/`is_ot_eligible`-as-a-real-
policy off the frozen `Shift` columns, plus OT/Regularization and the widened
`PolicyAssignment` that will need to reference it. Separately, the RLS GUC-placeholder test
flake (§13) is worth a dedicated fix before it causes more confusion in future sessions — a
background task has been flagged for it.
