# W9 — Leave Projection Adapter: Implementation Report

**Date:** 2026-08-20
**Companion documents:** `docs/architecture/WORKFORCE_ATTENDANCE_ARCHITECTURE.md` §21 (the
`LeaveDayProjection` contract), §19.1/§19.3/§19.4 (calculation pipeline + overlay precedence),
§11.4 (paid/LOP fractions), §12.3 (comp-off, the closest existing precedent), §22 (payroll
contract), §25 (event/adapter mechanics), §30 (W9's own scope line), decision log
`docs/architecture/WORKFORCE_ATTENDANCE_DECISION_LOG.md` **WD-31** (new entry added by this
slice), WD-22 (Leave/Payroll scope boundary).

---

## 1. Status

**W9 is implemented, tested, and live-verified end to end**, against the scope §30 names for it:
"Leave projection adapter (mocked until Leave exists) + recompute-on-event." Backend (model,
migration, repository, service, router, permissions, exceptions, and a real leave-overlay branch
in the calculation engine), frontend (leave overlay/provenance surfaced on the existing attendance
day detail page — no new Leave UI), and tests (22 new backend integration tests plus 2 new
frontend tests, both fully passing) are all in place.

A full live pass was performed against a real running API server, real Postgres, and a real
headless-Chromium browser — covering sync → LEAVE status/fractions → punches don't override
(`KEEP_LEAVE`) → period finalize/lock → sync/cancel refused while closed → reopen → cancel →
day reverts to its punch-derived outcome. See §19.

---

## 2. Pre-implementation audit

Before writing any code, the architecture document (§21, §19.1/§19.3/§19.4, §11.4, §12.3, §22,
§25, §30, §7.2, §8.2), the decision log (WD-01 through WD-30), every prior W1-W8 implementation
report, and the actual repository state (models, migrations, `calculation.py`, `service.py`,
`schemas.py`, tests, and the live dev database) were audited directly — via two parallel research
passes (one doc-only, one code-only) whose findings were cross-checked against each other rather
than trusted independently. Key findings that shaped the design:

- **The `LeaveDayProjection` contract is already fully specified** in architecture §21: field
  list (`employee_id, date, leave_application_id, leave_type_id, leave_type_code, fraction, half,
  is_paid, status`), the overlay precedence table, and the fraction/LOP mapping. Architecture's
  own words: *"a read model published by Leave (service method, not table sharing)."*
- **`calculation.py`'s own docstrings confirm the leave overlay is a documented no-op seam**,
  verbatim: *"Leave/regularization overlays (§19.1 steps 14-15) are no-op seams in W4... Leave and
  AttendanceRegularization do not exist yet."* This is not "already wired, just needs data" — W9
  is the slice that makes the overlay mechanism itself real, not merely a data source behind an
  existing slot.
- **`AttendancePolicyVersion.work_on_leave_behaviour`** (W3, `KEEP_LEAVE`/`PRESENT_CANCEL_LEAVE_
  HINT`) already exists as a real column, plumbed through schemas/service/frontend policy form,
  but nothing in the calc engine had ever read it — confirmed by grep, not assumed.
- **`attendance_status` already reserves `LEAVE`/`ON_DUTY`/`WFH`** at the DB CHECK/schema/
  frontend level, but the engine never produces any of the three (confirmed: `evaluate_day`/
  `_resolve_primary_status`/`_paid_lop_fraction` only ever assign `NOT_JOINED, EXITED,
  NOT_EXPECTED, ABSENT, INCOMPLETE, CONFIG_ERROR, PRESENT, HALF_DAY`). Only the `LEAVE` tier is
  in W9's named scope — `ON_DUTY`/`WFH` remain a separate, still-unimplemented seam (WD-17),
  untouched by this slice.
- **`AttendancePeriodSummary.leave_days`** (W8) already exists as a column with existing
  aggregation code (`elif row.attendance_status == "LEAVE": agg["leave_days"] += 1`) — confirmed
  dead in practice before this slice, since nothing ever produced `LEAVE`.
- **No leave table, package, service, or UI exists anywhere** in the repository — confirmed
  independently by a full-repo grep, not inferred from any prior report's own claim.
- **WD-22 (LOCKED)** bounds scope precisely: implement the read/event contract, never leave
  calculation, sandwich rules, leave types, or pay-day math.
- **The comp-off precedent (§12.3)** is the closest existing analogue for "Attendance stores a
  fact for a future module that doesn't exist yet, without inventing that module's ledger" —
  directly informed decision 1 below.
- **PD-LOCK-2 (W8, still OPEN)**: no `AttendanceAdjustment`/arrears mechanism exists, so §21's own
  "leave approved after payroll lock... HR exception creates arrears" has no implementable target
  beyond the "refuse" half — matching how W8 itself scoped the identical problem.

No architectural contradiction was found. No W1-W8 code was redesigned; `_ensure_date_open`,
`AttendanceDayService.calculate()`, and every other W1-W8 seam are reused exactly as they were.
Two genuinely unresolved product decisions — how to back the "mocked until Leave exists" adapter,
and whether it needs a real HTTP surface — were put to the user **before** any code was written
(recorded in full in §21 below and in WD-31), not silently chosen.

---

## 3. Existing leave seams discovered

| Seam | State before W9 |
|---|---|
| `AttendancePolicyVersion.work_on_leave_behaviour` (W3) | Real column, real schema/UI plumbing, never read by the calc engine |
| `attendance_status` enum values `LEAVE`/`ON_DUTY`/`WFH` | Reserved at DB/schema/frontend level, never produced |
| `AttendanceDay.paid_day_fraction`/`lop_fraction` | Real columns; `_paid_lop_fraction()` had no `LEAVE` branch |
| `AttendancePeriodSummary.leave_days` (W8) | Real column, real (but dead-in-practice) aggregation code |
| `calculation.py`'s leave-overlay docstring markers | Documentation-only "no-op seam" notes, zero executable branches |
| `_ensure_date_open` (W8) | Live, reusable period-lock check — exactly what §21 says a leave-approval-after-lock must consult |
| Comp-off fact pattern (§12.3, W7) | The only precedent for "store a fact for a future module without inventing its ledger" |
| `employee.ON_LONG_LEAVE` status | An unrelated, coarse employment-status flag — not day-level attendance/leave |

**Nothing pre-existing was a usable adapter** — every seam above was either a destination field
with no producer, or a documentation marker. W9 built the producer.

---

## 4. Exact W9 scope

**Built:**
- `LeaveDayProjection` contract (Pydantic schemas: `LeaveProjectionSync`, `LeaveProjectionCancelInput`,
  `LeaveDayProjectionRead`), fail-closed validated (fraction ∈ {0.50, 1.00}, half required iff 0.50).
- `leave_day_projection` table — the attendance-owned, temporary mirror of the contract (§21).
- A real leave-overlay branch in `calculation.py` (`_apply_leave_overlay`), wired into `evaluate_day`.
- `LeaveProjectionService` (sync/cancel/list/get), consuming `_ensure_date_open` and triggering
  `AttendanceDayService.calculate()` as the "recompute-on-event" mechanism.
- `ATTENDANCE.LEAVE_PROJECTION_SYNC` permission code; reads reuse `ATTENDANCE.VIEW`/`.VIEW_ALL`.
- Four routes: `POST /leave-projections`, `GET /leave-projections`, `GET /leave-projections/{id}`,
  `POST /leave-projections/{id}/cancel`.
- `work_on_leave_flagged` column on `AttendanceDay` (additive) — the one small, directly-required
  schema addition beyond the new table, consuming the previously-dead `work_on_leave_behaviour`
  policy field's `PRESENT_CANCEL_LEAVE_HINT` case.
- Frontend: leave overlay/provenance surfaced on the existing attendance-day detail page; no new
  Leave UI, page, or route.

**Not built (per WD-22 / task's strict scope rules):** leave types, balances, entitlement,
accrual, leave application/approval workflow, sandwich rules, RH/optional-holiday consumption
logic, `AttendanceAdjustment`/arrears, any Leave UI, WFH/ON_DUTY overlay completion (separate
unimplemented seam, out of W9's named scope), a generic rules engine, a new `DataScopeLevel`.

---

## 5. Leave → Attendance contract

### Leave-owned responsibilities (untouched by W9)
Leave type, balance, entitlement, accrual, application, approval/rejection, cancellation
business rules, sandwich policy, restricted-holiday consumption, half-day leave *rules* (Leave
decides whether/how much leave to grant; Attendance only consumes the resulting fraction),
leave-balance deduction.

### Attendance-owned responsibilities (what W9 built)
Determine the applicable calendar day (unchanged, Calendar's own concern); resolve shift and
attendance policy (unchanged); **consume** an approved leave projection; determine how leave
affects `attendance_status` per §19.4's precedence; calculate `paid_day_fraction`/`lop_fraction`;
preserve provenance (`leave_application_id`, `leave_type_code`, `half`, `is_paid`, `status`,
`source_version`); include leave-derived days in `AttendancePeriodSummary`.

### Payroll-owned responsibilities (untouched)
Salary calculation, statutory deductions, LOP monetary deduction, payroll rates, payslips —
`AttendancePeriodSummary`/`AttendanceDay` still only carry facts, never rupees.

---

## 6. Domain model

```text
leave_day_projection   (attendance-owned, temporary mirror of Leave's projection — NOT the ledger)
  id, company_id, employee_id, attendance_date
  leave_application_id (opaque external reference, no FK — Leave doesn't exist)
  leave_type_id, leave_type_code (opaque/informational)
  fraction (0.50 | 1.00), half (FIRST | SECOND | null), is_paid
  status (APPROVED | CANCELLED)
  source_version, synced_at, cancelled_at, cancelled_reason
  created_by_user_id, version
  UNIQUE (company_id, employee_id, attendance_date, leave_application_id)

attendance_day
  + work_on_leave_flagged   (new — set only for the PRESENT_CANCEL_LEAVE_HINT + punches case)
```

`leave_day_projection` is explicitly documented (model docstring, WD-31) as a **temporary,
replaceable mirror** — not the leave ledger. ADR-0004 (Leave owns the ledger) is untouched.

---

## 7. Projection lifecycle

```text
(sync) ──▶ APPROVED ──cancel (ATTENDANCE.LEAVE_PROJECTION_SYNC)──▶ CANCELLED
    ▲                                                                  │
    └──────────────── resync (same leave_application_id) ─────────────┘
```

- **Sync** (`POST /leave-projections`): validates the caller may act on the target employee
  (`_ensure_employee_visible` — cross-tenant/forged ids 404, never 403), refuses if the date's
  period is `CLOSED` (`_ensure_date_open`), fails closed if active fractions for the employee-date
  would sum above 1.00 (`LEAVE_PROJECTION_OVERLAP`, 409), then inserts (or, for an already-known
  `leave_application_id`, updates in place — an idempotent correction, reviving a cancelled row
  rather than duplicating it) and triggers `AttendanceDayService.calculate()`.
- **Cancel**: `status → CANCELLED` (never a delete — provenance preserved), same lock check, same
  recompute trigger.
- **Multiple active projections per employee-date are supported** (§21's half-day-AM-plus-PM
  case) — fractions sum, mixed paid/unpaid entries are each weighted by their own fraction.

---

## 8. Attendance calculation integration

`_apply_leave_overlay(result, inputs)` is applied once inside `evaluate_day`, at the single
funnel point every branch returns through — for every outcome except the population gate
(`NOT_JOINED`/`EXITED`, which ranks above `LEAVE` in §19.4) and `CONFIG_ERROR` (nothing
well-defined to overlay onto, fail-closed skip). It never touches `calendar_day_type`, the
employee's shift, punches (no fake punches are ever created), or the leave ledger (there is none
to write to). `AttendanceCalculationInput` gained one new field, `leave_entries: list[
LeaveOverlayEntry]`, resolved in `service.py::_build_calculation_input` by querying active
(`APPROVED`) `LeaveDayProjection` rows — the exact same shape the W5 roster-override fields
already established (DB resolution in `service.py`, pure consumption in `calculation.py`).

---

## 9. Leave precedence rules

Per §19.4's literal precedence (`NOT_JOINED/EXITED > full-day LEAVE > ON_DUTY/WFH >
calendar NOT_EXPECTED > punch-derived`):

| Case | Behaviour | Verified |
|---|---|---|
| Full-day paid leave, no punches | `LEAVE`, `paid_day_fraction=1.00` | Test + live |
| Full-day unpaid leave, no punches | `LEAVE`, `lop_fraction=1.00` | Test + live |
| Half-day paid leave, no punches | `LEAVE`, `paid=0.50`/`lop=0.50` | Test |
| Half-day unpaid leave + full punches on the other half | `HALF_DAY`, `paid=0.50`/`lop=0.50` (§19.4's own worked example) | Test |
| Leave on a holiday/weekly-off (via roster week-off override) | `LEAVE` wins over `NOT_EXPECTED`; `calendar_day_type` unchanged | Test |
| Leave + full punches, `work_on_leave_behaviour=KEEP_LEAVE` (default) | Stays `LEAVE`, late/early zeroed | Test + live |
| Leave + full punches, `work_on_leave_behaviour=PRESENT_CANCEL_LEAVE_HINT` | Punch-derived outcome (`PRESENT`) kept; `work_on_leave_flagged=True` | Test |
| Leave + missing punch | `LEAVE` (not `ABSENT`/`INCOMPLETE`) | Covered by full-day-no-punch cases |
| Leave + regularization (AUTO-approved synthetic punches) | Overlay applies identically regardless of what triggered recompute | Test |
| Leave + overtime | Not overlay-affected — OT detection runs earlier in the pipeline, independent of the overlay | Non-interference by construction, not separately tested |
| Multiple projections (AM paid + PM unpaid) | Fractions and paid/unpaid mix both sum correctly | Test |
| Leave cancelled after attendance calculated | Recompute reverts to the punch-derived outcome | Test + live |
| Leave arriving after attendance already calculated | `sync` always triggers a fresh `calculate()` | Implicit in every sync test |
| Leave arriving after period finalization | Refused (`ATTENDANCE_PERIOD_CLOSED`), matching PD-LOCK-2 | Test + live |

**Half-day granularity is a documented simplification** (WD-31 decision 4): the non-leave half of
a half-day-leave day is treated as a flat 0.50 contribution from the ordinary punch-derived
outcome, not re-evaluated minute-by-minute — the same block-level-not-finer-grained posture
`_evaluate_split` already applies to SPLIT shift duty blocks.

---

## 10. Paid/LOP handling

`_paid_lop_fraction`'s pre-existing punch-derived mapping (§11.4) is unchanged; the overlay
computes its own fractions on top, per the table in §9 above. Full-day: `paid_day_fraction` =
sum of paid entries' fractions, `lop_fraction` = sum of unpaid entries' fractions. Half-day:
leave's own paid/unpaid split, plus a flat 0.50 from the worked/unworked remainder. `AttendancePeriodSummary.leave_days`'s existing (previously dead) aggregation now fires correctly — verified
by test and live pass.

---

## 11. Historical/versioning behaviour

`AttendanceDay` continues to fully re-derive on every `calculate()` call (WD-10 — no incremental
patching); the leave overlay participates in that same reproducibility model, not a separate one.
`leave_day_projection.source_version` increments on every resync, giving a simple provenance
counter without inventing a second snapshot mechanism — `AttendanceDay.computation_snapshot`
already captures the punch/version inputs a given calculation run used; the leave projection's own
row *is* its history (never deleted, `CANCELLED` not overwritten-away). A later edit to a leave
projection does not retroactively change a historical `AttendanceDay` unless a fresh `calculate()`
is actually run — exactly the same "recompute always re-resolves by date" posture every other W1-W8
input already has.

---

## 12. Period-lock interaction

No new lock mechanism. `sync`/`cancel` both call the exact, unmodified `_ensure_date_open` W8
built — refusing with the existing `ATTENDANCE_PERIOD_CLOSED` (409) against a `CLOSED` period,
before any row is written. §21's "leave approved after payroll lock... default refuse" is
implemented in full; its "HR exception creates arrears" half is **not** implemented, since
`AttendanceAdjustment` doesn't exist (PD-LOCK-2, still OPEN — W9 adds no new information here).
The only correction path for a locked date remains a full `ATTENDANCE.UNLOCK` period reopen,
verified live (§19).

---

## 13. API surface

```text
POST   /leave-projections                    sync (create or correct) an approved projection
GET    /leave-projections                     list, scope-filtered
GET    /leave-projections/{id}                 get
POST   /leave-projections/{id}/cancel          cancel (If-Match), never a delete
```

A deliberately narrow adapter surface (four routes for one entity), not a Leave CRUD API — no
leave type, balance, application, or approval endpoint exists. Isolated as an internal
integration seam: gated by its own permission code (`ATTENDANCE.LEAVE_PROJECTION_SYNC`), intended
for a future Leave module or an authorized internal/test caller, not employee self-service.

---

## 14. Security / RLS / DataScope

`leave_day_projection` has `company_id` + `ENABLE`/`FORCE ROW LEVEL SECURITY` + `tenant_isolation`
policy, identical clause to every other tenant table in this codebase — confirmed on the real dev
Postgres instance (`relrowsecurity`/`relforcerowsecurity` both `true`). `ATTENDANCE.LEAVE_
PROJECTION_SYNC` is COMPANY-scoped, mirroring `ATTENDANCE_LOCK`'s static-gate posture; reads reuse
`ATTENDANCE.VIEW`/`.VIEW_ALL` (SELF/REPORTEES/REPORTEE_TREE/COMPANY all work via the existing
`_resolve_visible_employee_ids` mechanism — no new `DataScopeLevel`). Cross-tenant `employee_id`
(real in another tenant) and forged/nonexistent `employee_id` both resolve to `404`, identical
shape, never `403` — verified by test. A cross-tenant projection id on `GET`/`cancel` also 404s.

---

## 15. Frontend changes

`apps/web/src/lib/leave-projection/types.ts` (new) mirrors the backend contract. `apps/web/src/
lib/attendance/types.ts` gained `work_on_leave_flagged`. The existing `/app/attendance/[id]`
detail page now: shows a "Flagged for Leave review" badge when `work_on_leave_flagged` is true,
and — only when at least one projection exists for the day — a "Leave overlay" card listing each
active/cancelled projection's `leave_application_id`, fraction, half, paid flag, and status, with
an explicit "provenance only, Attendance does not own these facts" note. The projection fetch is
best-effort (a caller without read access, or simply no projections for the day, degrades to an
empty section, never a blocking error on the attendance day itself). **No new Leave page, route,
or fake demonstration UI was built.**

---

## 16. Database migrations

One new migration, `20260825090000_leave_day_projection.py`, chained onto W8's
`20260824090000_attendance_period`. Creates `leave_day_projection` (RLS + FORCE RLS + tenant
policy, CHECK constraints on `fraction`/`half`/`status`, a natural-key `UNIQUE` constraint) and
adds `attendance_day.work_on_leave_flagged` (`BOOLEAN NOT NULL DEFAULT false`) via the same
migration. No W1-W8 migration was modified.

---

## 17. Tests

**Backend — `apps/api/tests/integration/modules/attendance/test_leave_projection.py`, 22 tests,
all passing** against a real Postgres 16 instance (real RLS, real HTTP through the ASGI app):

- **Projection contract (8):** full-day paid/unpaid leave with no punches, half-day paid leave,
  multiple half-day (AM+PM) projections summing to a full day, invalid fraction rejected, half
  required for a 0.50 fraction, overlapping fractions rejected (`LEAVE_PROJECTION_OVERLAP`),
  forged employee id rejected (404), cross-tenant projection/employee rejected (404).
- **Calculation integration (6):** half-day unpaid leave + full punches (§19.4's own worked
  example), full-day leave `KEEP_LEAVE` overrides punches, full-day leave
  `PRESENT_CANCEL_LEAVE_HINT` flags and keeps the punch-derived status, leave overrides a roster
  week-off `NOT_EXPECTED` day, leave + an AUTO-approved regularization's synthetic punches.
- **Recalculation (2):** cancelling a projection reverts the day to its punch-derived outcome on
  recompute; resyncing the same `leave_application_id` updates in place, not a duplicate.
- **Locking (2):** sync refused against a `CLOSED` period; cancel refused against a `CLOSED`
  period (`ATTENDANCE_PERIOD_CLOSED`, both).
- **Payroll-facing facts (1):** `AttendancePeriodSummary.leave_days`/`lop_days` correctly reflect
  a finalized, leave-derived day.
- **Security (3):** SELF-scope list filtering, sync without permission rejected (403), stale
  `If-Match` on cancel rejected (`STALE_RESOURCE`).

Also ran the **full attendance module suite** together with the new file and the corrected
`test_registration_flow.py` assertion (§14/§17): **140 passed**, plus the same pre-existing,
teardown-only test-infrastructure cascade already documented in W8's report §21.4 (confirmed
identical, unrelated to W9). The **full backend test suite** (`pytest tests/`): **927 passed, 0
failed** (905 W1-W8 baseline + 22 new), same teardown-only-error pattern.

**mypy:** `Success: no issues found in 85 source files`. **ruff check:** all checks passed, whole
`src/`+`tests/` tree. **ruff format:** clean on every file this slice touched (the one
pre-existing, untouched formatting drift in `repository.py` — flagged in W8's own report — was
left alone, not reformatted as a side effect). **import-linter:** 1 contract kept, 0 broken.

**Frontend — 2 new tests, all passing.** Full suite: **335/335** (`npx vitest run`).
- `app/app/attendance/[id]/page.test.tsx`: shows the leave overlay card when a projection covers
  the day; shows the flagged-for-review badge when `work_on_leave_flagged` is set. Existing tests
  in this file and the sibling list page were updated only to add the new required
  `work_on_leave_flagged` field to their fixtures and to route the two `apiClient.get` calls the
  page now makes.

**tsc --noEmit:** exit 0. **`next build`:** compiles successfully; no new routes were added (no
Leave UI), only the existing `/app/attendance/[id]` route changed size slightly.

---

## 18. Migration verification

`20260825090000_leave_day_projection.py` verified on the real dev Postgres 16 instance:

```text
upgrade 20260824090000 -> 20260825090000   OK
downgrade 20260825090000 -> 20260824090000  OK  (leave_day_projection dropped, work_on_leave_flagged column dropped)
upgrade 20260824090000 -> 20260825090000   OK  (re-applied cleanly)
```

RLS/FORCE RLS confirmed directly via `pg_class` on the live dev database: `leave_day_projection`
→ `(true, true)`; `attendance_day.work_on_leave_flagged` confirmed present via
`information_schema.columns`.

**Not performed this session:** a full from-scratch migration chain verification against a
throwaway empty database (W8's report did this as an extra check). The incremental
upgrade/downgrade/upgrade cycle above was run against the existing dev database instead — honestly
disclosed as a smaller verification surface than W8's, not implied as equivalent.

---

## 19. Live verification

Both servers were started for real (`uvicorn entrypoints.api:app --port 8000`, `next dev --port
3000`) against the real Postgres dev stack.

**Live API pass** (`httpx` against the real running server, real HTTP): registered a real
company, built a real org/employee/shift/calendar/attendance-policy graph via real HTTP calls,
synced a real full-day paid leave projection for a date with no punches — **real `attendance_
status=LEAVE`, `paid_day_fraction=1.00`, `lop_fraction=0.00`, `work_on_leave_flagged=false`** —
punched a full day anyway and recomputed — **status stayed `LEAVE`** (default `KEEP_LEAVE`
behaviour, verified live, not just by test) — created and finalized a real attendance period —
**real `200`, `status=CLOSED`**, confirmed `AttendancePeriodSummary.leave_days="1.00"`,
`frozen=true` — attempted a new sync and a cancel against the now-closed period — **both real
`409 ATTENDANCE_PERIOD_CLOSED`** — reopened the period, cancelled the projection — **real `200`,
`status=CANCELLED`** — recomputed and confirmed the day reverted to **`attendance_
status=PRESENT`, `paid_day_fraction=1.00`** (the ordinary punch-derived outcome, leave no longer
in effect). Every step's actual HTTP status and response body was asserted, not assumed.

**Live browser pass** (Python `playwright`, real headless Chromium): a real browser session was
authenticated by writing a real token pair into `localStorage` (the same shape `token-storage.ts`
itself writes, matching W6/W8's identical technique), then navigated to the real attendance-day
detail page for a day with an active full-day paid leave projection. Confirmed, via a real
screenshot: the **"On leave"** status badge, a **"Missing punch"** badge (accurate — the
punch-derived `missing_punch` flag is untouched by the overlay, an honest secondary fact), the
**"Leave overlay (W9 — approved leave projections for this date)"** card rendering the real
`leave_application_id`/fraction/half/paid/status row, the pay-facts card showing `Paid day
fraction: 1.00` / `LOP fraction: 0.00`, and the provenance disclaimer text. **Zero browser console
errors or page errors.**

**Demo data left in the dev database:** live verification created two demo companies (`W9 Live
Verify …`, `W9 Browser Verify …`) — harmless, RLS-isolated test-scoped data, matching W6/W8's own
precedent. Not cleaned up given the time budget; flagged for whoever next resets that database.
Both local dev servers were stopped cleanly at the end of this session.

---

## 20. Known limitations

### 20.1 Half-day granularity is block-level, not minute-level (documented simplification)

See §9/§10, WD-31 decision 4. The non-leave half of a half-day-leave day is a flat 0.50
contribution from the ordinary punch-derived outcome, not a re-evaluation restricted to one half
of the shift's actual clock time. This reproduces architecture §19.4's own worked example exactly
and mirrors an existing, accepted simplification (`_evaluate_split`'s block-level SPLIT-shift
check) — not a new kind of gap.

### 20.2 `AttendanceAdjustment`/arrears path not built (PD-LOCK-2, still OPEN)

See §12. Leave-approved-or-cancelled-after-lock is refused outright; the only correction path is a
full `ATTENDANCE.UNLOCK` reopen. Unchanged from W8 — W9 adds no new information to this open
question.

### 20.3 `leave_day_projection`'s eventual relationship to a real Leave module is undecided
(new, PD-LEAVE-1)

See WD-31. A real Leave module could either replace this table wholesale (switching Attendance's
read to an actual in-process service call, matching §21's literal "service method, not table
sharing") or become this table's writer. Architecture doesn't specify which; not resolved here.

### 20.4 Leave + overtime interaction not separately tested

OT detection runs earlier in the calculation pipeline than the leave overlay and reads
`worked_minutes`/`scheduled_minutes`, which the overlay never touches — non-interference by
construction, not by a dedicated test. Stated honestly as an interpretation, not implied as
directly verified.

### 20.5 Migration verification scope smaller than W8's

See §18 — no fresh-from-scratch throwaway-database chain check this session.

---

## 21. Open product decisions

| ID | Question | Status |
|---|---|---|
| **PD-LOCK-2** (pre-existing, W8) | Should `AttendanceAdjustment`/an `APPROVED_PENDING_ARREARS` path ever exist for controlled post-lock leave correction? | Still open — refuse + full-period reopen only |
| **PD-LEAVE-1** (new) | When a real Leave module ships, does it replace `leave_day_projection` wholesale, or become its writer? | Open — flagged for whoever builds Leave |

Two further design points — how to back the "mocked" adapter, and whether it needs a real HTTP
surface — were **resolved explicitly by the user before implementation** (not left open): a
minimal owned mirror table, and a narrow internal HTTP endpoint. Recorded in full in WD-31.

---

## 22. Explicit exclusions

Per WD-22 and this task's own scope rules, none of the following were touched:

- **Leave types, balances, entitlement, accrual, application/approval workflow, sandwich rules,
  RH/optional-holiday consumption logic** — all remain entirely Leave's, whenever it ships.
- **Payroll, payslips, statutory calculations, LOP monetary deduction.**
- **`AttendanceAdjustment`/arrears** (§20.2/§21, PD-LOCK-2 unchanged).
- **WFH/ON_DUTY overlay completion** — a separate, still-unimplemented seam (WD-17's own scope),
  not named in W9's §30 line, left untouched.
- **Any Leave application/approval/balance UI.**
- **A generic JSON leave-rules engine** (WD-22 forbids this outright).

---

## 23. Recommended next step

**W10 (Device ingestion) can safely begin** — W9 does not touch, block, or leave in an
inconsistent state anything W10 would depend on.

Before a real Leave module or Payroll begins, three things are worth flagging to the team:

1. **PD-LEAVE-1** (§21): whoever builds the real Leave module needs to decide whether it takes
   over `leave_day_projection` as its own write surface or replaces it with a genuine in-process
   service call, per §21's original wording. This is a real design fork, not a blocking defect.
2. **PD-LOCK-2** (§21, unchanged from W8): still no arrears path for post-lock corrections
   (leave-specific or otherwise). Worth a real product decision before Payroll goes live, since
   Payroll will be the first consumer that actually cares about locked-day correctness under
   real-world "oops, approved late" scenarios.
3. **Migration verification scope** (§20.5): a fresh-from-scratch chain check (W8's own extra
   step) wasn't repeated this session — worth doing before this migration ships to a shared
   environment, even though the incremental up/down/up cycle and RLS checks both passed cleanly.

### Test counts (exact)

- Backend: **22/22** new (`test_leave_projection.py`), **140 passed** across the full attendance
  module suite (new + pre-existing + the corrected registration-flow assertion), **927 passed / 0
  failed** across the *entire* backend suite (905 W1-W8 baseline + 22 new) — plus the
  pre-existing, unrelated, teardown-only cascade documented in W8's report §21.4 (confirmed
  identical before this session's W9 code existed, by direct reproduction on an unrelated test
  file).
- Frontend: **2/2** new, **335/335** full suite.
- mypy: 0 issues (85 source files). ruff: 0 issues (whole `src/`+`tests/`). import-linter: 1
  contract kept, 0 broken. tsc: 0 errors. `next build`: succeeds.
- Migration: upgrade/downgrade/upgrade verified against the real dev database; RLS + FORCE RLS
  confirmed on `leave_day_projection`; `attendance_day.work_on_leave_flagged` confirmed present.
- Live verification: full sync→LEAVE→punches-don't-override→finalize→lock→refuse→reopen→cancel→
  revert cycle confirmed against a real running server and real Postgres (API pass) and a real
  headless browser with zero console errors (browser pass) — both documented in full in §19.
