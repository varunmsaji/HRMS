# Attendance Remediation Priority Plan — 16 November 2026

**Status:** plan only. Nothing here has been implemented, committed or pushed.
**Basis:** `MASTER_AUDIT_INDEPENDENT_VERIFICATION.md` (verdicts) and
`ATTENDANCE_OWNER_DECISIONS_REQUIRED.md` (decisions this plan waits on).
**Rule that shapes the order:** a change that alters an attendance result must reach a recalculation
of unlocked days, and must never reach a locked day. So every engine change is preceded by a
read-only impact report and followed by a controlled recalculation (see
`ATTENDANCE_HISTORICAL_DATA_IMPACT_PLAN.md`).

---

## 1. Principles

1. **One writer per shared file.** `attendance/calculation.py` (3,499 lines),
   `attendance/service.py` (8,970 lines), `attendance/repository.py`, `leave/service.py` and
   `leave/reconciliation.py` are each changed by **one work item at a time**, merged before the
   next starts. Items that only touch other files may run beside them.
2. **One engine version per release train.** Do not bump `ENGINE_VERSION` for every item. Land all
   engine-behaviour items for a train, then bump once (17), so one controlled recalculation
   covers them. Engine 16 itself must be committed first (Phase 0).
3. **Validation before behaviour.** Where a fix has a "refuse bad configuration at publish" half and
   an "engine reacts to bad configuration" half, ship the publish half first. The engine half
   changes existing results and waits for the impact report.
4. **Failing test first.** Each item starts with a test that fails on today's tree, taken from the
   audit's probe or from section 3 of the verification (acceptance criteria doc).
5. **Defects before decisions.** Items marked **D** wait for an owner decision; defects with no
   decision can go first. Nothing in a decision row may be built from a recommendation alone.
6. **Locked days are never rewritten.** Corrections to locked periods are separate, approved,
   audited operations (historical plan section 4), never a side effect of a code fix.

---

## 2. Phase 0 — Baseline (before any fix; no behaviour change)

| # | Item | Why first | Output |
|---|---|---|---|
| 0.1 | Commit engine 16, its 3 migrations, SQL reports, tests, fixtures as one reviewed change (needs the owner's go-ahead, since this pass may not commit) | Every later diff must be against a clean baseline; the dev DB is 4 migrations behind | Clean `git status` |
| 0.2 | Provision a disposable Postgres + Redis for integration tests (init scripts first, as CI does) | The suite refuses the shared dev stack; the 72 runtime-role and RLS tests fail without the init scripts | Documented command |
| 0.3 | Turn the audit's API probes IP1–IP10 and C1-* into **failing integration tests**, one file per finding group, marked `xfail(strict=True)` with the finding id | Converts tier-A evidence to tier-R and gives each fix a red test | 16 xfail tests |
| 0.4 | Run the read-only impact reports (historical plan) against dev, then against any pilot data | Tells us which fixes touch real rows | Report outputs filed under `docs/audits/` |
| 0.5 | Run Flutter analyze and test in CI or on a machine that has it | Mobile is unverified | Green or findings |

Exit: baseline committed, 16 strict-xfail tests in CI, reports run.

---

## 3. Phase 1 — Incorrect pay and attendance results

Goal: no configuration the API accepts can pay for work not done, or withhold pay for work done,
without a blocker. Highest consequence first.

| Order | ID | Change | Files (single writer) | Needs decision | Migration | Test (red first) |
|---|---|---|---|---|---|---|
| 1.1 | MA-01 / NF-2 (publish half) | Refuse publish unless hour bands start at 0 and are contiguous (no gap, no overlap); same check on draft save warning | `attendance/service.py` `_validate_bands`; web and mobile policy editors show the error | Confirm H-01 | None | Gap at start, gap in middle, open-ended last band; existing templates still publish |
| 1.2 | MA-01 (engine half) | "No band matched" becomes `CONFIG_ERROR`, never `PRESENT` | `calculation.py` `_resolve_primary_status` | H-01 | None | Probes 1 and 3 give `CONFIG_ERROR`; **do not ship until 1.1 is live and the impact report shows zero affected versions, or HR has republished them** |
| 1.3 | MA-02 | Zero-punch expected day: apply the owner's H-02 choice. `TREAT_PRESENT` limited to days with ≥1 punch, or zero-punch becomes `ABSENT` after the ownership window | `calculation.py`, `service.py` `_apply_incomplete_lock_resolution` | **H-02** | None; maybe a backfill note | Zero-punch under each of the three lock behaviours; IN-only day under `TREAT_PRESENT` |
| 1.4 | MA-04 | A roster off day resolves calendar and policy by the assignment's shift | `organisation/calendar_resolution.py` (`_scope_candidates`), `calculation.py` order | **H-04** | None | IP3 with and without punches; overtime on shift-scoped overtime policy |
| 1.5 | MA-08 / H-07 | Half-day leave on a day with nothing to lose leaves nothing to lose; decide the no-show half | `calculation.py` `_apply_leave_overlay` | **H-08, H-07** | None | Probe 13/14 outcomes |
| 1.6 | MA-03 | Comp-off credit reconciled to the current record: reverse the difference, reverse in full when the record is gone, rejected or pending; credit once per source key | `leave/service.py` (`LeaveCompOffService`), `attendance/repository.py` `_comp_off_facts` | **H-03** | None expected: reuse the existing reversal pattern (an `ADJUSTMENT` entry referencing the credit); the ledger CHECK has no reversal kind, so confirm first | IP10 sequence plus cap, reopen, lock-withdrawal paths |
| 1.7 | MA-05, MA-09, MA-13, MA-20, H-29 | Policy-shape rules (short shifts, ceiling measured beyond grace, grace at band edges, before-start work) | `calculation.py` | **P-05, D-01a/b, R-2, H-05, P-04, H-29** | Possibly a policy-version column for P-05 | One test per decision, plus boundary scans (229/230/231, 09:59/10:09) |

Dependencies inside Phase 1:
- 1.1 → 1.2 (do not change engine results until configurations are clean).
- 1.2, 1.3, 1.4, 1.5, 1.7 all edit `calculation.py`: **strictly serial, in the order shown**, one PR each, one engine bump (17) at the end.
- 1.6 lives in leave plus one repository function; it can run **in parallel** with the engine lane once `attendance/repository.py` is claimed by it alone.
- 1.7 is last because it depends on five decisions and changes the largest number of results.

Exit gate: every row of the section 8 matrix of the verification has a passing regression test; the
impact reports show no unreviewed affected employee-date; controlled recalculation (historical plan
section 3) completed on unlocked days for each company.

---

## 4. Phase 2 — Stale calculations, reconciliation and recalculation triggers

Goal: a stored result is never older than the inputs that determine it, and nothing is lost silently.

| Order | ID | Change | Files | Decision | Notes |
|---|---|---|---|---|---|
| 2.1 | MA-07 | Roster and assignment changes queue the ownership neighbourhood (two days each side) | `attendance/service.py` `ShiftRosterService._queue_recalc`, `create_assignment` | None | Sizes the queue: coalesce first (2.5) |
| 2.2 | MA-10 | `update_employment` queues from the joining date on pay-basis change; refuses a legal-entity change when any closed period owns a date of the spell | `employee/service.py` | None for pay basis; **C-04/MA-10 for legal entity** (refuse or require reopen) | Business rule: legal entity moves period ownership |
| 2.3 | MA-29 | Regularization approval recalculates every date the inserted punches can touch, oldest first | `attendance/service.py` | None (defect once ±1 day stays) | Check C-15 |
| 2.4 | MA-30 | Revocation of a break override recalculates from the override's start | `break_override_service.py` | None | |
| 2.5 | MA-12 | Coalesce overlapping pending requests; expose abandoned requests (list endpoint and a close blocker or HR warning) | `attendance/recalc.py`, `_run_validation` | **C-02** (blocker or warning) | Prerequisite for 2.1 at scale |
| 2.6 | MA-06 | Report punches owned by a locked day but absent from its snapshot; new blocker on the next period or an HR list | `attendance/service.py`, orphan report | **C-05** | Never rewrite the locked day |
| 2.7 | MA-17 | Single-day calculate refuses future dates (as range and regularization already do) | `attendance/service.py` | C-13 | One call site |
| 2.8 | C-17 | Break-correction recalculation failure queues a durable request | `break_service.py` | None | |
| 2.9 | MA-33 | Rewrite a `PENDING` overtime record only when a value changed | `attendance/repository.py`, `service.py` | O-21 | |
| 2.10 | AR-17 | A mechanism for "engine version N rows older than the current version": a controlled queued recalculation, run on demand, unlocked days only | `attendance/recalc.py`, a script | Owner approval of each run | Replaces manual re-runs after Phase 1 |

Serialisation: 2.1, 2.3, 2.6, 2.7, 2.9 all edit `attendance/service.py` → one at a time. 2.2,
2.4, 2.5, 2.8 touch other files and can run in parallel with one `service.py` item.

---

## 5. Phase 3 — Operational HR workflows and period-close blockers

Goal: every blocker has a remedy HR can use without calling the API.

| Order | ID | Change | Files / surfaces | Decision |
|---|---|---|---|---|
| 3.1 | MA-27 / L-14 | Cancelling or withdrawing leave closes its open shortfalls; `list_open_shortfalls` joins the application status; reconciliation always runs the obsolete-shortfall pass; **fix the blocker text** | `leave/service.py` (`cancel`), `leave/reconciliation.py` | None: a defect |
| 3.2 | MA-11 | Accrual, carry-forward and comp-off credit run the shortfall pass | `leave/service.py` | **L-09** |
| 3.3 | MA-34 / NF-1 | HR (company scope) may act on a manager-stage record, or reassign like leave; applies to overtime **and** regularization | `attendance/service.py`, router, schemas | **O-19** (and its regularization twin) |
| 3.4 | MA-36 | Web and mobile screens: leave reconciliation (preview, apply) and orphan-punch handling; until built, change the "run leave reconciliation" text | `apps/web`, `apps/mobile` | None |
| 3.5 | MA-35 | Labels for all 13 blocker codes in web and mobile; a test asserting every API code has a label | `apps/web/src/lib/attendance-period/types.ts`, Dart equivalent | None |
| 3.6 | MA-31 | Refuse a second ON_DUTY or early-departure request for one date at submit | `attendance/service.py`, `repository.py` | **C-16** |
| 3.7 | MA-28 / H-30 | Deactivation of a linked calendar refused, or made effective from a date | `organisation/calendar_setup.py`, `calendar_overlay.py` | **H-30** |
| 3.8 | MA-23 / C-12 | Blocker or warning for an excess-break exception awaiting approval | `_run_validation` | **C-12** |
| 3.9 | MA-21 / C-11 | Termination or joining inside a closed period refused, or requires reopen | `employee/service.py` | **C-11** |
| 3.10 | MA-32 / O-20 | Lock withdrawal reallocates cap budget | `attendance/service.py` `finalize` | **O-20** |
| 3.11 | C-14 | Revoke for an approved regularization (open period only) | regularization service | **C-14** |

Serialisation: 3.1 and 3.2 share `leave/service.py` → serial. 3.3, 3.6, 3.8, 3.10 share
`attendance/service.py` → serial. 3.4 and 3.5 are client-only and can run in parallel with any
backend item, but must follow the API contract of 3.1 and 3.3.

---

## 6. Phase 4 — Database integrity, security, concurrency, performance

| Order | ID | Change | Files | Notes |
|---|---|---|---|---|
| 4.1 | MA-18 | Revoke `UPDATE`, `DELETE`, `TRUNCATE` from the runtime role on `punch`, `overtime_action`, `punch_dismissal`, `attendance_period_action`; extend `test_runtime_role_grants.py` | New migration, init script note | Needs decision D11 (observability architecture). **Verify first that no code path updates these tables** (the `punch` table has `supersedes_punch_id`, which suggests append-only intent, but check every `UPDATE` and `DELETE`) |
| 4.2 | MA-18 | Unique partial index: one `APPLICATION` ledger debit per leave application | New migration | Pre-check with a duplicate query; fails if duplicates exist |
| 4.3 | MA-31 | Unique partial index for one approved ON_DUTY and early-departure request per employee-date | New migration, paired with 3.6 | Pre-check for duplicates |
| 4.4 | MA-22 | Take the period-close lock (shared side) in punch ingestion, regularization approval and overtime decision, or prove by test that the committed-state check suffices | `core/db/locks.py`, callers | Two-session race tests |
| 4.5 | MA-26 | Measure: 500 employees × 31 days; time a cascade, a company-wide calendar change, `_run_validation`, `finalize`. Then decide changes | Benchmark script | Do not optimise before measuring |
| 4.6 | MA-24 | Replace remaining `date.today()` with the company's business date, or document why harmless | four files | |
| 4.7 | Calendar versioning (V-03) | Decide whether work calendars, holiday lists, patterns and rosters need effective-dated versions for explainability | Design only | Owner decision V-03 |

Migration order: 4.2 and 4.3 (indexes, reversible) before 4.1 (grants, which can lock the app out
if code still writes). Each is its own revision with a downgrade.

---

## 7. Phase 5 — Full regression and production readiness

1. All 16 strict-xfail tests now pass and the `xfail` markers are removed.
2. Full backend (`run_full_tests.py --backend`), security suite with init scripts applied, web
   (`tsc`, `vitest`, `eslint`, `next build`), Flutter analyze and test, `lint-imports`.
3. Timezone invariance: engine probes identical under `UTC`, `Asia/Kolkata`, `America/New_York`.
4. Migration rehearsal on a copy: upgrade from the production head to the new head, downgrade each
   new revision, upgrade again.
5. Impact reports re-run: zero unexplained differences between pre-recalculation snapshot and
   post-recalculation state on unlocked days; zero changes on locked days.
6. A payroll-audit dry run (acceptance criteria doc section 8).

---

## 8. Dependency summary

```
Phase 0 (baseline, tests, reports)
   └─ 1.1 publish validation ─► 1.2 engine CONFIG_ERROR
   └─ 1.3 MA-02 ─► 1.4 MA-04 ─► 1.5 MA-08 ─► 1.7 policy-shape rules ─► engine 17 bump ─► controlled recalc
   └─ 1.6 comp-off (parallel lane, leave + one repository fn)
Phase 2 ── 2.5 coalesce ─► 2.1 widen roster recalc; 2.10 version recalc mechanism needs Phase 1 done
Phase 3 ── 3.1 ─► 3.2 ;  3.3 ─► 3.4 (screens need the API)
Phase 4 ── 4.2, 4.3 ─► 4.1
Phase 5 after everything
```

Items that look independent but are not: 1.2 and the impact report; 3.6 and 4.3 (code and index
must land in the same release); 3.4 and 3.1/3.3 (screens follow API shape).

## 9. Risks of implementing this plan

| Risk | Consequence | Control |
|---|---|---|
| Engine changes alter results on recalculation of unlocked days | An employee's attendance for the open month changes after a deploy | Pre-recalc snapshot, diff report, owner sign-off per company before bulk recalc |
| 1.2 turns existing days `CONFIG_ERROR` | Blocks close for employees on a gapped policy | Ship 1.1 first, run report, HR republishes versions before 1.2 |
| `ENGINE_VERSION` bump recalculates nothing (AR-17) | A deployed fix appears not to work | Explicit recalculation step with named dates |
| Comp-off reversal reduces balances | Employees see balances drop | Decision on notice, reversal reason text, one-off HR report before running |
| Grants migration (4.1) breaks a code path that updates `punch` | Outage | Grep every write, run full integration, rehearse on a copy |
| Merge conflicts on `service.py` | Lost changes | One writer rule |
| Other Claude sessions share this working tree | Lost work | Never `git stash`; commit per item (per memory) |
| Many open decisions | Plan stalls | Section 1 order puts defect-only items first |

## 10. What can start now, without any decision

0.1–0.5, 1.1, 2.1, 2.3, 2.4, 2.5 (warning variant), 2.7, 2.8, 2.9, 3.1, 3.4 (text change), 3.5,
4.2, 4.3, 4.5, 4.6. Everything else waits for the decisions named in its row.
