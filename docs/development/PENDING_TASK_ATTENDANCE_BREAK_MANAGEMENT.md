# PENDING TASK — Attendance Break Management V1 (resume here)

Status: **paused after Stage 4 (backend overrides). Nothing is committed, staged, pushed or deployed.**
Approved design: separate `attendance_break_event` table + `employee_break_override` table (3-table architecture), all 8 stages in one cycle with a checkpoint/test report after each. Do not commit until the user explicitly approves.

## How to run the tests (the repo's own `apps/api/.venv` is broken — it points at a missing path)

Env helper (outside the repo): `/tmp/claude-1000/-media-varun-varun15-work-staff-spectrum-HRMS/80f224b4-12da-4b75-b465-a7a276103dc9/scratchpad/env.sh`
If /tmp was cleaned, recreate:
```
cd apps/api
UV_PROJECT_ENVIRONMENT=<some dir>/venv uv sync --frozen
export PATH=<that dir>/venv/bin:$PATH
export DATABASE_URL="postgresql://hrms:hrms_dev_password@localhost:5433/hrms_break_test?schema=public"      # owner role: suite teardown needs it
export MIGRATIONS_DATABASE_URL="$DATABASE_URL"
export REDIS_URL="redis://localhost:6380/7"                                                                    # isolation guard refuses the shared dev redis db
# fresh test DB (never touch hrms_dev): docker exec ... psql -U hrms -d hrms_dev -c "create database hrms_break_test owner hrms"
#   then 001_extensions.sql, `alembic upgrade head`, and infra/docker/postgres/init/002_app_role.sh (see run_full_tests.py)
```
Scratch DBs created in the docker postgres: `hrms_break_test` (test DB, already migrated to head 20261103090000), `hrms_break_mig` (migration up/down/up check). `hrms_dev` was NOT modified. Drop both when finished.

Baseline before my changes (attendance unit+integration): 931 passed, 13 skipped, 3 failed — the 3 failures need `cv2` (not installed): `test_liveness.py` x2, `test_opensource_face_evaluation.py` x1. They are environmental, not mine.
Checkpoint after Stages 1+2 (+ organisation shift tests): 1017 passed, 13 skipped, same 3 `cv2` failures.

## Done

**Stage 1 — schema** (`apps/api/alembic/versions/20261103090000_break_management.py`, verified upgrade → downgrade → upgrade)
- `shift_break` + `mode` (NULL = legacy gap-matched), `break_type`, `is_enabled`, `excess_outcome`, `auto_deduct_full`, `optional_recorded_deducts`, `optional_scheduled_fallback`
- new `attendance_break_event` (append-only; trigger rejects UPDATE except a link column being nulled by ON DELETE SET NULL; unique idempotency key; unique `supersedes_event_id`; RLS)
- new `employee_break_override` (REPLACE/ADD/DISABLE, effective-dated, revoke instead of edit, GiST no-overlap per employee+lower(name), RLS)
- `attendance_break` (+name, kind, rule_source, override_id, scheduled/excess/deducted minutes, needs_review, is_approved, start/end_event_id), `attendance_day` (+actual_break, auto_deducted_break, unresolved_break_count, has_unresolved_break, has_active_break, has_excess_break_exception, gross_elapsed), `attendance_period_summary` (+6 nullable break totals), `attendance_regularization_request` (+break_start_event_id, requested_break_end, requested_break_minutes) and `BREAK_CORRECTION` added to both request-type CHECKs.
- Models updated in `attendance/models.py` and `organisation/models.py`.

**Stage 2 — engine** (`attendance/calculation.py`, `ENGINE_VERSION = 3`; legacy `mode=None` breaks calculate exactly as before)
- `BreakEventData`, extended `ShiftBreakData`/`MatchedBreak`/result fields; helpers `effective_break_events`, `pair_break_events`, `compute_breaks`, `summarize_breaks`, `evaluate_presence_and_breaks` (shared by FIXED/FLEX and SPLIT).
- Rules implemented: recorded event replaces the scheduled deduction; deductions are unioned over presence (no double deduction); auto deduction = min(configured duration, presence inside window) or full if `auto_deduct_full`; unresolved START → credit cut at the START, status INCOMPLETE (never half-day/absent), no auto-END; excess outcomes RECORD_ONLY/EXCEPTION/REQUIRE_APPROVAL/DEDUCT (DEDUCT only affects paid breaks; approved clears); OT compares against the net schedule (`scheduled_unpaid_break_minutes`); open START is "active" only while `day_open`.
- Tests: `tests/unit/modules/attendance/test_break_management.py` (37 passing), `test_break_rules.py` (11 passing), `tests/integration/modules/attendance/test_break_management_schema.py` (4 passing).

**Stage 3 — event API** (all new files under `apps/api/src/hrms/modules/attendance/`)
- `break_rules.py` (pure override resolution + `validate_rule_set`), `break_repository.py`, `break_schemas.py`, `break_service.py` (start/end/state/list/resolve, advisory lock per employee-day, idempotency, `utcnow()` clock hook), `break_router.py` (registered in `apps/api/src/hrms/app.py`).
- Endpoints (all under `/v1`): `GET /attendance/breaks/me/state`, `POST /attendance/breaks/me/start`, `POST /attendance/breaks/me/end` (ATTENDANCE.PUNCH); `GET /attendance/breaks/events`, `GET /attendance/breaks/day`, `GET /attendance/breaks/resolved-rules` (ATTENDANCE.VIEW); `POST /attendance/breaks/resolve` (ATTENDANCE.REGULARIZATION_APPROVE; employees cannot resolve their own break).
- `AttendanceDayService._build_calculation_input` now applies overrides, loads break events, sets `day_open`; break rows/day columns are written; `AttendanceBreakRead`/`AttendanceDayRead` carry the new fields.
- Shift config: `organisation/schemas.py` (ShiftBreakCreate/Read new fields, mode/type/outcome vocab) and `organisation/service.py` (unique names, duration rules, `_validate_break_durations`).
- Test helper `_build_wired_employee(..., breaks=...)` and `_cleanup_attendance_day` (new tables) edited in `test_attendance_day.py`.
- Tests: `test_break_events_api.py` — 11 passing.

**Stage 4 — overrides**
- `break_override_service.py` + routes `POST /attendance/break-overrides`, `GET /attendance/break-overrides?employee_id=&include_revoked=`, `POST /attendance/break-overrides/{id}/revoke` (ATTENDANCE.ROSTER_MANAGE / VIEW; no self-override; audited; closed-period guarded).
- Tests: `test_break_overrides_api.py` — 7 passing (last run). 

## Immediate next steps (in order)

1. **Fix a lint nit** in `tests/integration/modules/attendance/test_break_overrides_api.py` line ~215: the SQL string literal `"SELECT action FROM audit_log WHERE entity_type = 'employee_break_override'"` is >100 chars (E501). Split it in two string pieces. (My last edit attempt was rejected, so it is NOT applied.) **Do not run `ruff format` over whole directories** — it reformatted an unrelated test file once (reverted with `git checkout`); format only the files I created/changed.
2. Run the Stage 3+4 checkpoint: full `tests/unit/modules/attendance tests/integration/modules/attendance tests/integration/modules/organisation/*shift*` (≈7 min) and also check any RBAC route-matrix / permission-coverage tests still pass with the new routes (unknown whether such tests exist — look for failures mentioning routes/permissions).
3. **Stage 5 — exceptions, regularization, reports, period summary**
   - `BREAK_CORRECTION` regularization type: add to `_REGULARIZATION_TYPES` in `attendance/schemas.py`; request create schema (currently requires `requested_punches` or `requested_shift_id`) must accept `break_start_event_id` + `requested_break_end`/`requested_break_minutes`; on approval call `BreakEventService._apply_correction(...)` (already supports `regularization_request_id`); no self-approval (reuse existing regularization approval rules); locked/closed periods refused.
   - Exceptions list for HR/managers: active, unresolved, excess, auto-deducted, employee-recorded breaks (extend `attendance/overview.py` `is_exception` + the existing exception/overview endpoints; `idx attendance_day_unresolved_break_idx` already exists).
   - Reports: add paid/unpaid/auto-deducted/actual/excess minutes, unresolved count, exceptions by employee and by department/branch to existing report infrastructure (`attendance/overview.py`, period summary). 
   - Period summary: fill the 6 new `attendance_period_summary` columns when the period closes (live aggregate while OPEN; frozen snapshot at close; keep immutability); include unresolved-break indicator, approved corrections, `engine_version`/policy refs. Check `AttendancePeriodService` finalize/validate — an unresolved break day is INCOMPLETE so existing `incomplete_at_lock_behaviour` applies; confirm that is the desired behaviour.
   - Update `count_flagged_days_in_window` (`repository.py` ~line 1257, uses `excess_break_minutes > 0`) so RECORD_ONLY excess does not drive the cumulative half-day counter (engine already uses `counter_excess_minutes`).
   - Tests: auto-checkout with an unresolved break (check how `missing_punch_behaviour=AUTO_CLOSE`/`auto_closed` is handled — `auto_closed` is currently always False in the engine; make sure no work after the START is credited), locked day, period close keeps break totals, tenant isolation of reports, regularization approval by HR / self-approval refused.
4. **Stage 6 — web** (`apps/web`): extend `src/components/shift/shift-breaks-editor.tsx`, `shift-version-form.tsx`, `src/lib/shift/types.ts`, `validate-shift-version.ts` (mode, type, paid, enabled, excess outcome, optional flags, reorder, midnight-crossing, unique names, min/max/scheduled rules, overlap); employee override UI (create/revoke, inherited-vs-overridden badge from `resolved-rules`); HR exception views (unresolved/excess + resolve dialog); report columns. Tests next to existing `*.test.ts(x)` files; run the web test command from `apps/web/package.json`.
5. **Stage 7 — Flutter** (`apps/mobile/lib/features/attendance/`): repository methods for `/attendance/breaks/me/*`; `domain` model for `BreakStateRead`; Start/End Break control + active-break indicator (name, start time, running duration) in `presentation/attendance_self_screen.dart` / `employee_attendance_panel.dart`; hide controls for automatic-only shifts; idempotency key per attempt, reused on retry; state re-fetched from backend on launch/resume; error mapping (`BREAK_ALREADY_ACTIVE` → just refresh). Widget tests in `apps/mobile/test/` (start, end, active display, failure handling, app-restart state). Run `flutter test`.
6. **Stage 8 — docs**: update `docs/modules/attendance` and `docs/business-rules/attendance` (break modes, resolution order, unresolved/excess rules, endpoints, schema, limitations), and write the final report.

## Final report must include
Files created/modified; DB changes; endpoints added/changed; tests passed/failed (call out the 3 `cv2` failures as pre-existing); known limitations; security review; commit-readiness.

## Known limitations / decisions to mention
- `attendance_break_event.attendance_day_id` is filled only when the day row already exists (events are immutable so it cannot be backfilled).
- `MANDATORY_PUNCH` break never recorded → no deduction and no exception (only noted in `computation_snapshot.breaks.mandatory_not_recorded`); revisit if the business wants it to raise an exception.
- A break event that ends after check-out is refused for the employee (HR corrects via `/attendance/breaks/resolve`).
- Overrides are not auto-recomputed for past days; the daily sweep/range calculation or a manual recompute picks them up.
- FLEXIBLE_DURATION break windows cannot cross midnight (pre-existing rule kept); FIXED_WINDOW can.
- The immediate recalculation after an event targets the shift-attributed date (not the punch-local date).
- Pre-existing: the DB CHECK for `request_type` lacked `EARLY_DEPARTURE_APPROVAL` (listed in the schema but not in the constraint); I did not change that.
- `day_open` makes a recompute depend on the current time (active → unresolved once the punch window has closed); documented in the engine.

## Files changed so far (git status; none staged)
Modified: `apps/api/src/hrms/app.py`, `attendance/{calculation,models,schemas,service}.py`, `organisation/{models,schemas,service}.py`, `tests/integration/modules/attendance/test_attendance_day.py`
New: `alembic/versions/20261103090000_break_management.py`, `attendance/break_{repository,router,rules,schemas,service,override_service}.py`, tests `test_break_management.py`, `test_break_rules.py`, `test_break_management_schema.py`, `test_break_events_api.py`, `test_break_overrides_api.py`
