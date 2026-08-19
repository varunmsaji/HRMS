# W4 — Punch + Attendance Day + Calculation Engine: Implementation Report

**Status:** Implemented, uncommitted. This session continued a prior session that had already
built the bulk of the W4 backend (models, migrations, calculation engine, service, router,
schemas) before being rate-limited. This session's job was to audit that work against the W4
brief, close the gaps found, and complete the operational frontend that had not been started.

**Companion:** `docs/architecture/WORKFORCE_ATTENDANCE_ARCHITECTURE.md` §19–§30,
`docs/architecture/WORKFORCE_ATTENDANCE_DECISION_LOG.md` (WD-10/WD-11/WD-19/WD-26).

## 1. Audit findings (Phase 1–2)

Independently verified rather than trusted: ran the existing 71 attendance tests (all green),
ran `ruff`/`mypy`/`lint-imports` against the attendance package, inspected the router/schemas/
models against the architecture's AttendanceDay field list, and diffed the actual API surface
against architecture §25. No architectural contradiction was found — the prior session's work
matches WD-10 (pipeline order), WD-11 (version FKs + snapshot, immutable punches), WD-21 (fail
closed), and WD-26 (punch/attendance_day ship unpartitioned, documented). Gaps found were scope
gaps (missing tests, missing frontend), not design errors:

1. `ruff` flagged 2 `Union[]` usages in `resolution.py` (pre-existing style debt, not W4-specific
   but in a file W4 touches) — fixed.
2. Security tests covered `SELF` and `COMPANY` (implicitly) but not `REPORTEES`/`REPORTEE_TREE`,
   and had no dedicated forged-`X-Company-Id` test, despite the brief explicitly requiring all
   four scope levels — closed.
3. Migration upgrade/downgrade/upgrade had not been verified against the real dev DB this
   session (WD-26 states 0 rows existed, confirmed) — verified.
4. **The entire frontend (architecture §26) had not been started**: no dashboard, no employee
   attendance view, no team/daily view, no punch entry UI. This was the largest gap and the bulk
   of this session's new work.

## 2. What already existed (prior session, verified not rebuilt)

- **Migrations** `20260820090000_punch.py`, `20260820100000_attendance_day.py` — `punch`,
  `attendance_day`, `attendance_break` tables, each `company_id` FK'd, RLS `ENABLE`+`FORCE`, a
  `tenant_isolation` policy identical in shape to every other table (WD-26: ordinary tables, not
  partitioned — a documented, deliberate deferral).
- **Models** (`hrms/modules/attendance/models.py`): `Punch` (append-only, idempotency key,
  source enum WEB/MOBILE/DEVICE/IMPORT/ADMIN/API), `AttendanceDay` (the full field list the
  brief asked to "investigate and implement" — company/employee/date/timezone, shift+version,
  work_calendar, three policy version FKs, calendar_day_type + holiday flags, scheduled/actual
  times, worked/break minutes split paid vs unpaid vs excess, a typed `attendance_status` plus
  independent boolean flags per WD-07 (`is_late`/`is_early_out`/`is_overtime`/`is_regularized`/
  `is_pending_approval`/`worked_on_holiday`/`worked_on_weekly_off`/`missing_punch`), OT facts
  (detected/approved/pending/classification/comp-off), `paid_day_fraction`/`lop_fraction` as the
  leave/payroll contract surface, `calculation_version` + `computation_snapshot` (JSONB) +
  `calculated_at` for reproducibility, `is_locked`/`locked_at`/`locked_by`), `AttendanceBreak`
  (actuals against `ShiftBreak`, paid/unpaid/excess).
- **Calculation engine** (`calculation.py`, 1104 lines): pure functions, independently unit
  tested — timezone resolution (ShiftVersion → Branch → Company, WD-06), cross-midnight
  attribution to the shift start date, duplicate-punch collapsing, deterministic punch pairing
  (`PAIR_ALL`/`FIRST_IN_LAST_OUT` from policy, orphan detection — never fabricates time), break
  evaluation (paid added back, unpaid already excluded), hour-band lookup, late/early band
  lookup, missing-punch behaviour, overtime detection with daily cap, and the full
  `evaluate_day` pipeline (employment gate → assignment → shift → calendar → policies → punches
  → breaks → worked minutes → late/early → half-day/absence → overtime → facts) — matching
  WD-10's locked stage order exactly, fully replacing derived fields on every calculation.
- **Service/repository/router/schemas**: `POST /v1/attendance/punches` (self vs on-behalf
  permission dispatch, mirroring `employee/router.py::create_assignment`'s pattern),
  `GET /v1/attendance/punches`, `GET /v1/attendance/days`, `GET /v1/attendance/days/{id}`,
  `POST /v1/attendance/days/calculate` (`ATTENDANCE.VIEW_ALL`), `POST
  /v1/attendance/days/{id}/recompute` (`ATTENDANCE.RECOMPUTE`, refuses on `is_locked`).
- **Permissions** (WD-19): `ATTENDANCE.VIEW`, `ATTENDANCE.VIEW_ALL`, `ATTENDANCE.PUNCH`,
  `ATTENDANCE.PUNCH_ON_BEHALF`, `ATTENDANCE.RECOMPUTE` (plus W3's `ATTENDANCE.POLICY_MANAGE`).
- **71 tests** (43 unit / 28 integration) covering the pipeline stages, policy resolution,
  idempotent punches, cross-tenant isolation, `SELF` scope, locked-day refusal, config-error
  fail-closed paths.

## 3. What this session added

### Backend

- Fixed the 2 `ruff` `UP007` findings in `resolution.py` (`Union[]` → `X | Y`).
- Added 3 new security tests to `test_attendance_security.py`
  (`test_reportees_scope_sees_direct_reports_only`,
  `test_reportee_tree_scope_sees_descendants_not_unrelated_branch`,
  `test_forged_company_id_header_rejected`), plus a shared `_add_reportee_employee`/
  `_calculate_day` helper that extends `_build_wired_employee`'s org graph with a reporting
  hierarchy without re-creating the COMPANY-scope calendar/policy assignments (which would
  overlap). `test_attendance_security.py` now covers all four DataScope levels
  (`SELF`/`REPORTEES`/`REPORTEE_TREE`/`COMPANY`), cross-tenant isolation (punch list +
  attendance day get), a forged `X-Company-Id` header, unauthorized recompute, and unauthorized
  on-behalf punch — the full list the brief's Security Tests section asked for.
- Fixed 2 pre-existing line-length lint findings in `test_attendance_policy.py` and
  `test_policy_validation.py` (unrelated to this session's changes but in the same package, now
  clean) so the module-wide `ruff` run is unconditionally green.
- Verified migration reversibility: confirmed 0 rows in `punch`/`attendance_day`/
  `attendance_break` (matching WD-26's stated rationale), ran
  `alembic downgrade 20260819120000` → `alembic upgrade head` (and, by an intermediate mistake
  during this check, one migration further back to `20260819100000` and forward again — also
  clean), confirmed `relrowsecurity`/`relforcerowsecurity` still `true` on all three tables
  post-cycle, then ran the full backend suite (817/817 passed) to prove the cycle didn't corrupt
  anything.

### Frontend (new — architecture §26)

The entire operational Attendance UI, following the existing app's established patterns
(`apiClient`, `usePermissions`, `PageHeader`/`Card`/`EmptyState`/`ErrorState`/`LoadingState`,
`NativeSelect`/`FormField`, the tab pattern from `employees/[id]/page.tsx`):

- `lib/attendance/types.ts` — `Punch`, `AttendanceDay`, `AttendanceBreak` and their enums,
  mirroring `hrms.modules.attendance.schemas` field-for-field.
- `lib/attendance/format.ts` — display-only minute/time formatters (no calculation logic).
- `components/attendance/attendance-status-badge.tsx` — `attendance_status` → tone, mirroring
  `EmployeeStatusBadge`'s unknown-value fallback (never throws on a status the frontend doesn't
  know about yet).
- `components/attendance/punch-entry-dialog.tsx` — reusable punch-entry dialog; locked to one
  employee (self or the employee whose tab it's opened from) or, when no `employeeId` prop is
  given, a full employee picker (admin on-behalf entry from the dashboard). Calls
  `POST /v1/attendance/punches` — the router, not this dialog, decides self vs on-behalf.
- `components/attendance/employee-attendance-panel.tsx` — new **Attendance** tab on the existing
  Employee detail page (`employees/[id]/page.tsx`): date-range table of `AttendanceDay` rows
  (status, scheduled vs actual time, worked minutes, late/early, OT, exceptions), a "Record
  punch" action, and (permission-gated) a "Calculate today" action.
- `app/app/attendance/page.tsx` — the **Attendance dashboard + daily/team list**: summary tiles
  (present/absent/half-day/weekly-off-or-holiday/missing-punch/overtime/config-error) computed
  client-side from the scope-filtered day list for the selected date, filters (date, employee,
  status, plus client-side exception checkboxes for missing-punch/config-error/pending-approval),
  and a "Record punch" action.
- `app/app/attendance/[id]/page.tsx` — **Attendance day detail**: every `AttendanceDay` field
  grouped into Schedule / Punches & worked time (+ breaks table) / Overtime & pay facts /
  Calculation & audit (+ a collapsible raw `computation_snapshot` viewer), status/flag badges,
  and a permission-gated Recompute action (disabled when `is_locked`) with a confirmation dialog.
- `components/layout/nav-items.ts` — added the **Attendance** nav entry.
- 10 new frontend tests (`app/app/attendance/page.test.tsx`,
  `app/app/attendance/[id]/page.test.tsx`) covering loading/empty/403/summary-tile/punch-dialog
  states on the dashboard and loading/render/locked-disables-recompute/404/recompute-success on
  the detail page, following the existing `ShiftsPage`/`ShiftDetailPage` test pattern exactly
  (mocked `apiClient`, mocked `useAuth`, `next/navigation`).

### Known limitation introduced by this session's design choice

`GET /v1/attendance/days` has no `department_id`/`branch_id`/`designation_id`/`shift_id`/
`exception` query parameters (only `employee_id`/`date_from`/`date_to`/`attendance_status`) — so
the dashboard's team filters are limited to what the backend actually supports, plus purely
client-side filtering (exception checkboxes) over whatever page of data was fetched. The brief's
"Daily/team attendance... filtering by department/branch/designation/shift" was **not**
implemented as a backend capability — adding it would mean extending
`AttendanceDayRepository.list` with joins through `EmployeeAssignment`, which is a real, scoped
piece of work this session chose not to invent silently (mirroring WD-12: don't add undocumented
behaviour). Flagged here rather than silently narrowing the brief.

## 4. Calculation pipeline (unchanged from prior session, re-verified)

Employment gate → assignment → timezone → shift → calendar day type → attendance policies →
punches → breaks → worked minutes → (leave overlay contract present as typed fields, no Leave
module to populate it yet) → late → early departure → required hours → missing punch → half day
→ absence → overtime → `AttendanceDay` → payroll facts (`paid_day_fraction`/`lop_fraction`).
Every stage is a separately unit-tested pure function in `calculation.py`; `evaluate_day` composes
them without skipping any (WD-10).

## 5. Punch pairing / break / holiday / overtime behaviour

Unchanged from the prior session — re-verified by reading `calculation.py` and its 29 unit
tests: `PAIR_ALL`/`FIRST_IN_LAST_OUT` from `AttendancePolicyVersion.multi_punch_mode`, orphaned
IN/OUT punches produce a deterministic exception rather than fabricated time, unpaid break gaps
already excluded from the first-in/last-out span are not double-subtracted, paid break gaps are
added back, calendar day type comes from `organisation.calendar_resolution` (never duplicated),
`worked_on_holiday`/`worked_on_weekly_off` flags preserve the classification for future OT/
payroll, and overtime detection reads `OvertimePolicyVersion` (eligibility flag, minimum
minutes, daily cap) without computing any rupee amount (ADR-0006).

## 6. Leave / Payroll contracts

Unbuilt, as required — `AttendanceDay.paid_day_fraction`/`lop_fraction`/`comp_off_minutes_earned`
are the typed surface future Leave/Payroll modules read; nothing in this session added leave
balance, approval, sandwich rules, or money calculation.

## 7. RBAC / DataScope enforcement

All four DataScope levels now have a passing integration test against real attendance routes:
`SELF` (existing), `REPORTEES`/`REPORTEE_TREE` (new this session, direct-report and
descendant-vs-unrelated-branch cases), `COMPANY` (implicit via the default registering-admin
role in every other test, and explicit in `test_recompute_without_permission_rejected`'s
COMPANY-scope actor). Every route: authenticates (`get_current_user`), checks a permission
(`require_permission` or, for the dynamic self/on-behalf punch dispatch, an explicit
`rbac.resolve_data_scope` call), resolves `DataScope`, and returns 404 (never 403) for an
in-scope-permission-but-out-of-scope-target resource — verified by
`test_self_scope_sees_only_own_attendance_day`,
`test_reportees_scope_sees_direct_reports_only`, and
`test_reportee_tree_scope_sees_descendants_not_unrelated_branch`.

## 8. RLS verification

`punch`/`attendance_day`/`attendance_break` all have `ENABLE`+`FORCE ROW LEVEL SECURITY` and a
`tenant_isolation` policy (verified via `pg_class.relrowsecurity`/`relforcerowsecurity` after the
migration up/down/up cycle, not just read from the migration source). Every attendance
integration test runs through the app's normal `hrms_app`-role session, not the migration/admin
role (see each test file's module docstring). A dedicated cross-role RLS proof
(`tests/security/test_rls_runtime_role.py`) already exists generically for the same
`tenant_isolation` policy pattern on `employee`; it was not duplicated for `punch`/
`attendance_day` specifically this session (both tables use the identical, already-proven
policy shape) — flagged as a known gap rather than silently assumed equivalent.

## 9. Audit

Punch creation and attendance-day calculate/recompute already emit audit events via the existing
audit framework (verified by reading `service.py`'s use of the shared audit writer — no second
audit mechanism was introduced). Not independently re-verified with a dedicated audit-row-count
assertion this session beyond what the prior session's tests already assert.

## 10. Frontend screens delivered

Attendance dashboard + daily/team list, Employee attendance tab, Attendance day detail
(recompute), Punch entry (self and on-behalf) — see §3. Not delivered: a distinct "punch device
management" screen (explicitly excluded by the brief), a regularization workflow UI (W6), an OT
approval UI (W6/later), and department/branch/designation/shift server-side filters on the team
list (§3's known limitation).

## 11. Test counts

- Backend unit (attendance): **43**
- Backend integration (attendance): **31** (8 of which are the security suite:
  `SELF`/`REPORTEES`/`REPORTEE_TREE`/`COMPANY`, cross-tenant × 2, forged company ID,
  unauthorized recompute, unauthorized on-behalf punch, unauthenticated)
- Backend attendance total: **74** (up from 71 at session start)
- Full backend regression: **817 / 817 passed**
- Frontend total: **270 / 270 passed** (36 test files, including the 2 new attendance page test
  files, 10 tests)

## 12. Static analysis

- `ruff check src/ tests/` (backend, full repo): **All checks passed**
- `mypy src/` (backend, full repo, 85 files): **Success, no issues found**
- `lint-imports` (import-linter, `modules depend on shared and core only`): **1 contract kept, 0
  broken**
- `tsc --noEmit` (frontend, full repo): **0 errors**
- ESLint: not run — this project has no `eslint.config.js` yet (`next lint` prompts an
  interactive first-time setup wizard); introducing it was out of scope for this session and not
  requested.

## 13. Migration verification

`alembic downgrade 20260819120000` → `alembic upgrade head`: clean both directions, RLS flags
intact after, full backend suite green after. (An extra, unintended downgrade to
`20260819100000`/back up also happened mid-session while issuing the verification commands — also
clean, and re-confirms W3's migrations are equally reversible.)

## 14. Known limitations (carried forward + new)

- Team/daily attendance list has no department/branch/designation/shift server-side filter
  (§3) — client-side exception filters only operate on the already-fetched date's rows.
- No dedicated `hrms_app`-role RLS proof specific to `punch`/`attendance_day` (§8) — relies on
  the generic proof already covering the identical policy pattern via `employee`.
- `GET /v1/attendance/days`/`GET /v1/attendance/punches` have no pagination (matches the
  existing `GET /v1/employees` precedent — full scope-filtered result set only).
- No frontend E2E browser walkthrough was performed by the agent this session — the user asked
  to do the manual frontend verification themselves. All frontend correctness claims above rest
  on `tsc`, the 10 new component/page-level tests, and the unchanged 260 pre-existing frontend
  tests, not a live click-through.

## 15. Deferred decisions (unchanged from architecture, re-confirmed still open)

PD-CAL-1, PD-CAL-2, PD-APR-1, PD-POL-1, PD-POL-2, PD-SHIFT-1, PD-LOCK-1, PD-WFH-1, PD-OT-1,
PD-SCOPE-1, PD-BR14-SHIFT — none required a decision to complete W4; all remain open per the
decision log.

## 16. Explicitly excluded (per brief §"STRICT SCOPE", unchanged)

Leave module, Payroll calculations/statutory/payslips/bank payout, device/biometric/facial/GPS
integrations, full regularization workflow, generic workflow engine, new RBAC scope levels,
Stitch frontend redesign, attendance approval workflow.

## 17. Recommended next module

**W5 — ShiftRoster + NULL-shift behaviour + overnight tests**, per architecture §30's locked
sequence (`docs/architecture/WORKFORCE_ATTENDANCE_ARCHITECTURE.md:1729`), followed by **W6 —
Regularization + local approval + adjustments + audit**, which is what the "Missing punch" /
"Pending approval" / `is_regularized` facts this session's UI already surfaces are waiting for.
