# W3 — Attendance Policy System: Plan, Implementation Report & Reference

**Status:** Implemented, uncommitted (per task brief — see "Files created/modified" for the exact
diff; nothing was committed to git). Migrations `20260819090000` through `20260819120000` are
applied to the dev DB (head).

**Companion:** `docs/architecture/WORKFORCE_ATTENDANCE_ARCHITECTURE.md`,
`docs/architecture/WORKFORCE_ATTENDANCE_DECISION_LOG.md` (see new **WD-25** for W3-specific
decisions not already covered by an existing WD entry).

## 1. Status

**Shipped and verified**: full database layer (4 migrations, verified upgrade→downgrade→upgrade→
downgrade→upgrade against the real dev DB), a new `hrms.modules.attendance` package (models,
schemas, exceptions, repository, service, resolution, router, permissions, dependencies),
`PolicyAssignment` widened in `organisation` (CHECK constraint + cross-module existence
validation + router permission dispatch + registration-time permission grant), 25 new backend
tests (10 unit + 15 integration, all passing), full backend regression suite (768 tests, all
passing), a complete frontend admin UI for all three policy families plus a shared Policy
Assignment screen and a Policy Resolution preview screen (TypeScript clean, production build
clean, existing 260 frontend tests unaffected), and a manual E2E walkthrough against the real
backend (register → create Attendance Policy → configure hour bands on a draft → publish →
create a COMPANY-scope PolicyAssignment → resolve it for an employee → zero console errors).

**Not started (explicitly out of scope per the task brief §39)**: punches, attendance
calculation engine, `AttendanceDay`, roster, locks, period summaries, regularization/OT
*workflow* (only the policy *contract* they'll read), Leave, Payroll.

## 2. Architecture audit findings (Phase 1)

Read completely before writing code: the full `WORKFORCE_ATTENDANCE_ARCHITECTURE.md` (1864
lines) and `WORKFORCE_ATTENDANCE_DECISION_LOG.md`, plus a live-code audit (not doc-trust) of:
`PolicyAssignment` (model, migration, service, router, schemas), `WorkCalendar`/`HolidayCalendar`/
`WeeklyOffPattern`/`CalendarResolutionService`, `Shift`/`ShiftVersion`/`ShiftBreak`/
`ShiftDutyBlock` (the exact versioning template W3 copies), the effective-dating/insert-new-
close-previous pattern, RBAC (`DataScope`, `require_permission`, the post-F4/F8/F9 "consume the
resolved scope" fix), RLS migration boilerplate, audit pattern, module-layout/cross-module-import
convention, test conventions (including the documented GUC-placeholder flake and its
`set_rls_company_id` workaround), and frontend conventions (`apiClient`, `ApiError`, `usePermissions`,
the Shift/ShiftVersion list+detail+tabs+publish-dialog screens, shared UI primitives).

**Confirmed as of this session (git status)**: the entire W1 (Calendar/PolicyAssignment) + W2
(Shift+Break) implementation was uncommitted working-tree state on top of commit `7a8ff30`, with
migration `20260818130000_policy_assignment.py`'s own comment explicitly instructing W3 to widen
its `policy_kind` CHECK rather than build a new table. This is followed literally (§5.4).

**No architectural contradiction was found.** Every decision below is either a direct
application of an already-LOCKED WD entry, or a new choice recorded in the new **WD-25** entry
(decision log) rather than invented silently in code, per the task brief's stop-and-document
rule.

## 3. Policy model

Three independent versioned policy identities (WD-03, locked — not one mega-policy),
each following `Shift`/`ShiftVersion`'s exact shape: a mutable **identity** row (name/code/
active — never carries evaluation fields) plus an immutable, effective-dated **version** row
(`status` DRAFT→PUBLISHED, insert-new/close-previous, one open draft per identity, GiST
no-overlap on published rows per parent).

- **`AttendancePolicy` / `AttendancePolicyVersion`** — grace, punch rounding, missing-punch/
  missing-shift behaviour, half-day split, multi-punch pairing, flex core-hours-breach
  behaviour, split-shift missed-block behaviour, WFH/on-duty punch rules, work-on-leave overlay,
  excess-break behaviour, late-count window/cap, incomplete-at-lock default — 26 typed columns,
  no JSONB. Three typed child tables: `AttendancePolicyHourBand` (worked-minutes →
  PRESENT/HALF_DAY/ABSENT), `AttendancePolicyLateBand`, `AttendancePolicyEarlyDepartureBand`
  (minutes-after-grace → classification, with a `counts_toward_cap` flag).
- **`OvertimePolicy` / `OvertimePolicyVersion`** — eligibility, min-OT-minutes, rounding,
  pre/post-approval flags, daily/weekly/monthly caps, comp-off contract, night-OT mode/window,
  approval chain. Child table `OvertimePolicyRateRow` (day_class → classification_code +
  informational `multiplier_decimal`, unique per version — no money computed, ADR-0006/WD-12).
- **`RegularizationPolicy` / `RegularizationPolicyVersion`** — who may request (employee/
  manager/HR flags), max backdated days, max requests/month, reason/attachment requirements,
  approval chain, auto-approve window, lock behaviour. Child table
  `RegularizationPolicyAllowedType` (typed enum of which exception types this policy allows
  regularizing, unique per version).

No generic JSON rules engine anywhere (WD-20). The only JSONB in this slice's tables is none at
all — every field is a typed column, every multi-valued rule is a typed child table.

## 4. Versioning

Identical mechanics to `ShiftVersion` (W2), reused deliberately rather than reinvented:

- `status` DRAFT|PUBLISHED, DB CHECK `..._published_required_check` exempts DRAFT rows from
  requiring `effective_from` (a draft may be incomplete mid-edit).
- Partial unique index `..._one_open_draft_idx` — at most one open draft per policy identity.
- GiST exclusion `..._no_overlap` on `(policy_id, daterange(effective_from, COALESCE
  (effective_to, 'infinity'), '[]'))`, predicated on `status='PUBLISHED' AND deleted_at IS NULL`
  — the race-condition backstop for insert-new/close-previous, exact same idiom as
  `shift_version_no_overlap`/`policy_assignment_no_overlap`.
- Publish is insert-new/close-previous with **two concurrency tokens**: the draft's own
  `If-Match`, and `expected_previous_version` for the currently-open published row (required
  only when one exists) — verified in `test_publish_second_version_insert_new_close_previous`.
- Published versions are never mutated again; a correction always publishes a new draft.

## 5. Data model / precedence / resolution — implementation specifics

### 5.1 PolicyAssignment widening (not a new table)

Migration `20260819090000` does exactly what the W1 migration comment said W3 would do:
```sql
ALTER TABLE policy_assignment DROP CONSTRAINT policy_assignment_policy_kind_check;
ALTER TABLE policy_assignment ADD CONSTRAINT policy_assignment_policy_kind_check
  CHECK (policy_kind IN ('WORK_CALENDAR','WEEKLY_OFF','ATTENDANCE_POLICY','OVERTIME_POLICY',
  'REGULARIZATION_POLICY'));
```
The GiST exclusion (`policy_assignment_no_overlap`) already included `policy_kind WITH =` in its
column list from W1 — the three new kinds automatically get correct no-overlap semantics with
zero additional migration work.

### 5.2 Precedence

WD-09's 8-level chain (`EMPLOYEE > SHIFT > DESIGNATION > GRADE > DEPARTMENT > BRANCH >
LEGAL_ENTITY > COMPANY`) is **not reimplemented**. `organisation.calendar_resolution.
CalendarResolutionService.resolve_policy_assignment(company_id, policy_kind, employee_id=,
target_date=)` was already generic over `policy_kind` in W1 — only the DB CHECK, never the Python
code, restricted it. `attendance.resolution.PolicyResolutionService` calls it directly.

### 5.3 Resolution

`PolicyResolutionService.resolve(company_id, policy_kind, employee_id=, target_date=)`:
1. Calls the precedence walk above; `None` → `config_incomplete=True` (fail closed, WD-21 —
   never a default policy).
2. On a match, looks up the specific policy identity + `find_effective_as_of(policy_id, date)`
   in the matched family's own repository.
3. Missing policy row or no published version covering the date → also `config_incomplete=True`.
4. Otherwise returns `resolved_policy_id/name/code`, `resolved_version_id`, and
   `resolved_through` (the matched scope type) — the exact "resolved through: SHIFT" explain
   view the architecture brief's §35 example describes.

Exposed at `GET /attendance-policy-resolution?employee_id=&date=&policy_kind=`, mirroring W1's
`GET /calendar-resolution` (same admin-preview pattern, same permission-gated posture).

### 5.4 Cross-module wiring

`AttendancePolicy`/`OvertimePolicy`/`RegularizationPolicy` identities live in the new
`hrms.modules.attendance` package (DEC-023); `PolicyAssignment` stays in `organisation` (WD-24).
Two places need to reach across that boundary — both use the pre-existing, function-scoped
local-import convention (see WD-25 point 2 for the full rationale):

- `organisation.service._validate_policy_reference` → local import of
  `attendance.service.AttendanceService.policy_exists(...)` for the three new kinds.
- `attendance.resolution.PolicyResolutionService` → local import of
  `organisation.calendar_resolution.CalendarResolutionService`.
- `organisation.service.register_company` → local import of `attendance.permissions.
  ATTENDANCE_PERMISSIONS` to grant `ATTENDANCE.POLICY_MANAGE` to every newly registered
  company's `COMPANY_ADMIN` role (mirrors the existing `calendar_permission_rows` pattern one
  entry down — without this, a freshly registered company's own admin would have zero
  Attendance access, exactly the bug this pattern already exists to avoid for Employee/Calendar).

## 6. Database

4 new Alembic migrations, chained off `20260818140000` (the W2 head):

| Migration | Contents |
|---|---|
| `20260819090000_widen_policy_assignment_kinds` | `ALTER ... CHECK` only, no new table |
| `20260819100000_attendance_policy` | `attendance_policy`, `attendance_policy_version`, 3 band tables |
| `20260819110000_overtime_policy` | `overtime_policy`, `overtime_policy_version`, `overtime_policy_rate_row` |
| `20260819120000_regularization_policy` | `regularization_policy`, `regularization_policy_version`, `regularization_policy_allowed_type` |

Every new table: `company_id NOT NULL` FK, `ENABLE`/`FORCE ROW LEVEL SECURITY`, `tenant_isolation`
policy identical to every other table in the codebase — verified directly via `pg_class.
relrowsecurity`/`relforcerowsecurity` (both `t` on all 11 new tables) and `pg_policies` after
`alembic upgrade head`.

**Migration verification**: `alembic upgrade head` → `downgrade -4` → `upgrade head` → `downgrade
-4` → `upgrade head`, twice through, no errors, `alembic current` confirms head each time.

Indexes: `(company_id)` on every table, `(policy_id)`/`(policy_version_id)` on child rows,
partial unique `..._company_code_idx` for optional identity `code` uniqueness, partial unique
`..._one_open_draft_idx`, GiST `..._no_overlap`. No index added without a concrete query pattern
behind it (§38 of the task brief).

## 7. API

All under `/v1`, `DataEnvelope`/`ListEnvelope` conventions, `If-Match` on every mutating call,
`extra="forbid"` on every Pydantic input model:

```
GET/POST      /attendance-policies
GET/PATCH     /attendance-policies/{id}
GET/POST      /attendance-policies/{id}/versions
GET           /attendance-policies/{id}/versions/resolve?as_of=
GET/PATCH/DEL /attendance-policies/{id}/versions/{version_id}
POST          /attendance-policies/{id}/versions/{version_id}/publish

(identical shape for /overtime-policies and /regularization-policies)

GET/POST      /policy-assignments                 (widened, not new — WD-24/WD-25)
GET           /attendance-policy-resolution?employee_id=&date=&policy_kind=
```

`GET .../versions/resolve` is registered **ahead of** `.../versions/{version_id}` in
`router.py` — same literal-before-parameterized ordering requirement W2 already documented for
`/shifts/{id}/versions/resolve`.

## 8. Frontend

Full admin UI under `apps/web/src/app/app/`, mirroring the Shift/ShiftVersion list+detail+tabs+
publish-dialog pattern established in W2 (identical `apiClient`/`ApiError`/`usePermissions`/
`ConcurrencyConflictBanner` idioms, manual tab implementation, no diffing on draft PATCHes):

- **`/app/attendance-policies` (+ `[id]`)** — list, identity form, Overview/Versions tabs, a
  full typed rule form (grace/rounding/missing-punch/half-day/multi-punch/flex/split/WFH/leave/
  break/lock sections), a shared `PolicyBandsEditor` reused three times (hour/late/early
  bands — one component, not three near-duplicates), publish dialog, discard/deactivate
  confirmations, version history.
- **`/app/overtime-policies` (+ `[id]`)** — same shape, leaner form (eligibility/caps/approval/
  night-OT), `OvertimePolicyRateRowsEditor` for day-class → classification rows.
- **`/app/regularization-policies` (+ `[id]`)** — same shape, checkbox-toggle allowed-types
  picker instead of a row editor (the child table has no numeric fields, just a type + sort
  order derived from toggle order).
- **`/app/policy-assignments`** — single screen spanning all 5 `policy_kind` values (not
  duplicated per kind), with a kind-driven policy picker and a scope-type-driven scope picker
  (NativeSelect populated from the relevant org-master list; a plain UUID input for EMPLOYEE
  scope, since no employee-typeahead component exists in this codebase).
- **`/app/policy-resolution`** — the "resolved through: X" preview screen the architecture brief
  names explicitly (§35's worked example), for the three W3 policy kinds.
- A new shared `PolicyVersionPublishDialog<T>` generic component (`components/common/`)
  replaces what would otherwise be three near-identical publish dialogs.

**Verified**: `tsc --noEmit` clean, `next build` clean (all new routes present in the build
manifest), existing 260 Vitest tests unaffected (no new frontend unit tests were written — see
§13 Known limitations), and a full manual E2E walkthrough via a headless-Chromium Playwright
script against the real running dev servers: register → create employee → create Attendance
Policy → create+configure a draft with an hour band → save → publish → create a COMPANY-scope
`PolicyAssignment` pointing at it → open the Resolution Preview screen → resolve for that
employee → **"Resolved policy: Company Default", "Resolved through: COMPANY"** rendered
correctly, zero browser console errors across every screen (`/app/attendance-policies`,
`/app/overtime-policies`, `/app/regularization-policies`, `/app/policy-assignments`,
`/app/policy-resolution`). Test companies created during this walkthrough were deleted from the
dev DB afterward.

## 9. RBAC

New permission `ATTENDANCE.POLICY_MANAGE` (WD-19 already named this code; WD-25 point 5 locks it
as one code covering all three families, not three separate ones), COMPANY-scoped, no new
`DataScopeLevel`. Granted to every newly-registered company's `COMPANY_ADMIN` role at live
registration (not just the demo seed — same pattern as `ORG.CALENDAR.MANAGE`/`ORG.HOLIDAY.
MANAGE`). `/policy-assignments` dispatches between `ORG.CALENDAR.MANAGE` and `ATTENDANCE.
POLICY_MANAGE` by `policy_kind` at the router layer (WD-25 point 4) rather than gating the whole
shared endpoint on one code. All config endpoints are COMPANY-scoped only (no `DataScope`
filtering needed — consistent with every other Organisation config endpoint) since Attendance
policy administration is never self-service (architecture §23.2).

## 10. RLS

Every new table: `company_id` FK + `FORCE ROW LEVEL SECURITY` + `tenant_isolation` policy
comparing `company_id` to `current_setting('app.company_id', true)::uuid` — verified directly
against the dev DB (`pg_class`/`pg_policies`), not assumed from the migration source. Cross-tenant
`GET /attendance-policies/{id}` from a different company returns 404, verified in
`test_cross_tenant_policy_not_found` (DEC-028).

## 11. Audit

Every mutation calls `AuditService.record()` in the same session as the write: `*_CREATED`,
`*_UPDATED`, `*_VERSION_CREATED`, `*_VERSION_UPDATED`, `*_VERSION_DISCARDED`,
`*_VERSION_PUBLISHED` for all three families (18 distinct action codes total), plus the existing
`POLICY_ASSIGNMENT_CHANGED` action (unmodified, already covers the widened kinds since it isn't
kind-specific).

## 12. Tests

**Unit** (`tests/unit/modules/attendance/test_policy_validation.py`, 10 tests, no DB): hour-band
require/allow-empty, ordered-non-overlapping acceptance, overlap rejection, "only the last band
may be open-ended" rejection, out-of-order input handling, duplicate `day_class`/
`regularization_type` rejection and acceptance.

**Integration** (`tests/integration/modules/attendance/`, 15 tests, real Postgres + HTTP):
- `test_attendance_policy.py` (9) — no-auto-draft-on-create, second-open-draft 409, publish
  without hour bands 422, publish with overlapping bands 422, publish success + `resolve?as_of=`
  round-trip (before/after the effective date), insert-new/close-previous two-token publish flow
  (missing-token 422, correct-token 200, `effective_to` set correctly on the closed version),
  published-version-immutable (PATCH/DELETE both 409), cross-tenant 404, unauthenticated 401.
- `test_overtime_regularization_policy.py` (3) — duplicate `day_class`/`regularization_type`
  rejected at draft-creation time (not deferred to publish — see note below), full lifecycle
  including publish, invalid-enum-value 422.
- `test_policy_resolution.py` (3) — `config_incomplete=True` with no assignment,
  EMPLOYEE-scope-beats-COMPANY-scope precedence (mirrors `test_calendar_resolution_branch_
  scope_beats_company` from W1), invalid `policy_kind` query param 422.

One correction made mid-testing, not a design change: the initial test comment assumed rate-row/
allowed-type duplicate validation was deferred to publish time; the actual implementation (both
intentional) validates at **draft creation** too (`_validate_rate_rows`/`_validate_allowed_types`
run unconditionally in `create_*_version`, not only in `publish_*_version`) — stricter and more
helpful than the comment assumed, so the tests were corrected to match the real (better)
behaviour rather than the code being weakened to match a wrong test assumption.

**Regression**: full existing suite — `tests/integration/modules/organisation/`,
`tests/unit/modules/organisation/`, `tests/integration/modules/employee/`,
`tests/unit/modules/employee/`, `tests/security/` — all pass identically to before this work.
One pre-existing test (`test_registration_success_full_row_graph`) needed its expected-permission-
set assertion updated to include the new `ATTENDANCE.POLICY_MANAGE` code, exactly as its own
comment already anticipated for the next module to grant a permission at registration; not a
regression, an expected consequence documented at the point of change.

**Full backend suite**: 768 passed, 0 failed (`pytest tests/ -q`), in a single run with no
isolation tricks — the suite-wide GUC-placeholder flake documented in the W2 report was not
encountered in the runs performed for this work, consistent with it being order-dependent rather
than deterministic.

**Frontend**: `tsc --noEmit` clean, `next build` clean, existing 260 Vitest tests pass unchanged.

## 13. Validation

Backend-enforced (never silently normalized, per task brief §36):
- Hour/late/early-departure bands: non-negative `min_minutes`, `max_minutes >= min_minutes` at
  the Pydantic layer; non-overlap and "only the last band may be open-ended" at publish time
  (`InvalidPolicyBandError`, 422); at least one hour band required to publish.
- Rate rows: unique `day_class` per version, both at draft-save time and backed by a DB `UNIQUE`
  constraint.
- Allowed types: unique `regularization_type` per version, both at draft-save time and backed by
  a DB `UNIQUE` constraint.
- `effective_from` required to publish; must be strictly after the currently-published version's
  `effective_from` when one exists.
- Publishing over an existing published version without `expected_previous_version` → 422
  (`POLICY_VERSION_PREVIOUS_VERSION_REQUIRED`).
- Concurrent conflicting publishes → 409 via the GiST exclusion backstop
  (`POLICY_VERSION_OVERLAP`).
- Every enum field (punch rounding, missing-punch behaviour, half-day split, etc.) validated
  against a closed set at the Pydantic layer.
- `extra="forbid"` on every input schema — mass-assignment of `id`/`company_id`/`version` is a
  422, never silently ignored.
- No applicable policy at resolution time → explicit `config_incomplete=True`, never a guessed
  default (WD-21).

## 14. Performance

- Policy resolution reuses the already-optimized `_scope_candidates` (one `get_assignment_as_of`
  call + one conditional `get_branch` call, not eight queries) plus one `find_effective` query
  per candidate scope — identical cost profile to the already-shipped W1 calendar resolution,
  which the architecture doc's own performance section already accepted.
- Indexes added only where an actual query pattern needs them (see §6) — no speculative
  indexing.
- No N+1 introduced: `list_*_versions` loads each version's child rows individually (matching
  `ShiftVersion`'s own `list_shift_versions` pattern exactly — an accepted, pre-existing
  trade-off in this codebase, not a new one).

## 15. Known limitations

- **Policy deactivation does not check for active `PolicyAssignment` references** (unlike
  `WorkCalendarDeactivationBlockedError`). Recorded as WD-25 point 7 — a deliberate scope
  decision, not an oversight, deferred because it requires the same cross-module query pattern
  used for existence validation, applied at a different call site.
- **No auto-created initial DRAFT version on policy identity creation** (unlike `Shift`) — see
  WD-25 point 6 for why this asymmetry with Shift is intentional, not a gap.
- **Policy Assignment's EMPLOYEE-scope picker is a free-text UUID input, not a search-as-you-type
  component** — no such employee-picker component exists elsewhere in this codebase, so none was
  invented here; the other 6 non-COMPANY scope types use a `NativeSelect` populated from the
  relevant org-master list instead.
- **No new frontend unit tests** were added for the new components/pages (existing 260 tests
  pass unchanged, and correctness was instead verified via a real E2E Playwright walkthrough
  against the live backend — a stronger signal for this kind of CRUD-heavy admin UI, but it means
  there is no fast, isolated regression harness for the new frontend code the way
  `validate-shift-version.test.ts` exists for Shift).
- **Band ordering validation checks non-overlap, not full 0..∞ coverage.** A gap between bands
  (e.g. 0–100 PRESENT, then 200–∞ HALF_DAY, nothing covering 101–199) is accepted at publish
  time — the architecture text only requires "ordered, non-overlapping," not gap-free; a
  worked-minutes value falling in a gap is a future attendance-engine concern (§19), not a W3
  concern, since W3 explicitly does not build that engine.

## 16. Deferred / open product decisions

None newly introduced by W3. The architecture's existing open list (§32 / PD-CAL-1 through
PD-BR14-SHIFT) is unaffected — W3 did not need to resolve any of them, since none concern policy
definition/resolution (they concern calendar behaviour, approval identity, and later slices).

## 17. Explicit exclusions (confirmed, per task brief §39)

Grepped for and confirmed absent: no `Punch`, `AttendanceDay`, `AttendanceRegularization`
workflow state machine, `OvertimeRequest`, `AttendanceLock`, `AttendancePeriodSummary`, leave, or
payroll model/service/route anywhere in the new code. `RegularizationPolicyVersion`/
`OvertimePolicyVersion` define the *contract* (who may request, caps, approval chain / eligibility,
caps, rate config) that a future workflow will read — no workflow itself was built, per WD-08.

## 18. Files created

Backend:
```
apps/api/src/hrms/modules/attendance/{__init__,models,schemas,exceptions,repository,service,
  resolution,router,permissions,dependencies}.py
apps/api/alembic/versions/20260819090000_widen_policy_assignment_kinds.py
apps/api/alembic/versions/20260819100000_attendance_policy.py
apps/api/alembic/versions/20260819110000_overtime_policy.py
apps/api/alembic/versions/20260819120000_regularization_policy.py
apps/api/tests/unit/modules/attendance/{__init__,test_policy_validation}.py
apps/api/tests/integration/modules/attendance/{__init__,conftest,test_attendance_policy,
  test_overtime_regularization_policy,test_policy_resolution}.py
```

Frontend:
```
apps/web/src/lib/attendance-policy/{types,validate-attendance-policy}.ts
apps/web/src/lib/overtime-policy/{types,validate-overtime-policy}.ts
apps/web/src/lib/regularization-policy/{types,validate-regularization-policy}.ts
apps/web/src/lib/policy-assignment/types.ts
apps/web/src/components/attendance-policy/{attendance-policy-form,
  attendance-policy-version-form,policy-bands-editor}.tsx
apps/web/src/components/overtime-policy/{overtime-policy-form,overtime-policy-version-form,
  overtime-policy-rate-rows-editor}.tsx
apps/web/src/components/regularization-policy/{regularization-policy-form,
  regularization-policy-version-form}.tsx
apps/web/src/components/common/policy-version-publish-dialog.tsx
apps/web/src/app/app/attendance-policies/{page,[id]/page}.tsx
apps/web/src/app/app/overtime-policies/{page,[id]/page}.tsx
apps/web/src/app/app/regularization-policies/{page,[id]/page}.tsx
apps/web/src/app/app/policy-assignments/page.tsx
apps/web/src/app/app/policy-resolution/page.tsx
```

Docs:
```
docs/modules/attendance-policy/00_W3_ATTENDANCE_POLICY_REPORT.md   (this file)
```

## 19. Files modified

```
apps/api/src/hrms/modules/organisation/service.py     (_validate_policy_reference widened;
                                                         register_company grants ATTENDANCE.
                                                         POLICY_MANAGE)
apps/api/src/hrms/modules/organisation/schemas.py      (_POLICY_KINDS widened)
apps/api/src/hrms/modules/organisation/router.py       (per-kind permission dispatch on
                                                         /policy-assignments)
apps/api/src/hrms/app.py                                (attendance_router registered)
apps/api/src/hrms/seed/bootstrap.py                     (ATTENDANCE_PERMISSIONS spliced in)
apps/api/tests/integration/modules/organisation/test_registration_flow.py
                                                         (expected permission set updated)
apps/web/src/components/layout/nav-items.ts             (5 new nav entries)
docs/architecture/WORKFORCE_ATTENDANCE_DECISION_LOG.md   (new WD-25 entry)
```

## 20. Confirmation

W4 (Punch/AttendanceDay/calculation engine) was **not** started — confirmed by grep (no `Punch`,
`AttendanceDay`, or calculation-engine model/service/route exists anywhere) and by scope
discipline throughout this session.

## 21. Recommended next step

**W4 — Punch (web/manual) + AttendanceDay + calculation engine (no OT approval, no devices) +
employee/team views**, per the architecture's own implementation sequence (§30). W3's
`resolve_attendance_policy`/`resolve_overtime_policy`/`resolve_regularization_policy` machinery,
the typed hour/late/early-departure bands, and the OT/regularization contracts are the exact
inputs W4's calculation pipeline (§19.1, steps 1–20) is designed to consume.
