# Attendance — Release Acceptance Criteria — 16 November 2026

**Status:** criteria only. Nothing is implemented. These are the conditions each remediation in
`ATTENDANCE_REMEDIATION_PRIORITY_PLAN.md` must meet before it merges, and the conditions for the
release as a whole.

---

## 1. Standard for every remediation (the six gates)

A remediation is **not done** until all six are shown, with the evidence attached to the change.

| Gate | Requirement | Evidence |
|---|---|---|
| G1 Red first | A test that **fails on today's tree for the stated reason**, committed before the fix. For API-level findings this is the audit's probe turned into an integration test (`xfail(strict=True)` until the fix lands, so a fix that does not fix, or a test that never failed, is caught) | Commit or CI run showing the failure and its message |
| G2 Green after | The same test passes with the `xfail` marker removed | CI run |
| G3 Layers | Engine (pure unit), service/repository (integration with real Postgres and the runtime role), API (HTTP contract) tests for every layer the fix touches | List in the PR |
| G4 Clients | If a response shape, error code, label or setting changes: web test and Dart test (or contract fixture) updated; every new blocker or error code has a label in both clients | Test names |
| G5 Database | If schema, index or grant changes: migration upgrade from the previous head on a copy, downgrade, upgrade again; runtime-role grant test; RLS test; duplicates pre-check query empty | Rehearsal log |
| G6 No collateral change | Evidence that unrelated attendance behaviour did not move (section 3) | Golden-matrix diff, impact diff |

A fix that changes a **result** (status, paid, LOP, overtime, balance) additionally needs G7:
the pre/post impact diff from the historical plan (section 3 there), reviewed and signed.

---

## 2. Per-finding acceptance tests

Each row gives the red test (G1/G2) and the extra regression guards. IDs match the plan.

### Phase 1

| Item | Red test (must fail today) | Extra regression tests |
|---|---|---|
| 1.1 MA-01/NF-2 publish | Publishing hour bands `HALF_DAY 240–479, PRESENT 480+` returns a validation error; so does `ABSENT 0–239, PRESENT 300+`; a band set not starting at 0 | Standard templates publish; contiguous custom sets publish; draft save still allowed; overlap still refused; client shows the error |
| 1.2 MA-01 engine | Uncovered minutes give `CONFIG_ERROR`, not `PRESENT` (engine probes 1 and 3 of verification) | `_base_input` fixture changed to a band starting at 0 (the existing fixture encodes the bug); no existing result with a covering band changes |
| 1.3 MA-02 | IP2: zero-punch day under `TREAT_PRESENT` is **not** paid 1.00 after the owner's H-02 rule | IN-only day under each of three behaviours; zero punch under each of three; half-day leave with no punches; frozen summary totals |
| 1.4 MA-04 | IP3: roster week-off for an employee with shift-scoped calendar and policy resolves (no `CONFIG_ERROR`), with and without punches; overtime on that day under a shift-scoped overtime policy | Company-scope case (AR-01) unchanged; employee with no assignment shift still `CONFIG_ERROR`; policy by employee/designation/grade/department/branch/legal entity unchanged |
| 1.5 MA-08/H-07 | Half-day leave on holiday, roster week-off, weekly off: LOP 0.00 under the owner's H-08 rule | Half-day leave on working days unchanged; reconciliation after calendar change; `WORK_ON_LEAVE_UNRESOLVED` unaffected |
| 1.6 MA-03 | IP10: 180 min credits 0.38; overtime removed → balance returns to 0 (or per H-03); 30 min detected → 0.06 total, not 0.44 | Cap-after-credit, reopen-after-credit, lock-withdrawal-after-credit; concurrent sweeps credit once (existing); credit already used by leave; expiry; negative balance rule |
| 1.7 policy-shape rules | One test per owner decision: 4-hour shift worked fully is `PRESENT`; arrival 59 minutes beyond grace; 230/231 boundary scan; work before start; H-29 | Boundary scans at every band edge (min−1, min, min+1) for grace 0, 10, 30; three timezones |

### Phase 2

| Item | Red test | Extra |
|---|---|---|
| 2.1 MA-07 | IP7c: after a roster change on Monday, Tuesday is recalculated and no punch is listed on two days | Assignment change, roster delete, roster publish; neighbours that are locked are skipped and reported |
| 2.2 MA-10 | `PATCH pay_basis` queues a request from the joining date; legal-entity change refused when a closed period owns a date | Employment without closed periods still editable; terminated employment still refused |
| 2.3 MA-29 | Night-shift missing checkout regularized: both dates recalculated | Same-date case unchanged |
| 2.4 MA-30 | Revoke override recalculates its full range | Create, update unchanged |
| 2.5 MA-12 | Five overlapping requests produce one calculation per day; abandoned request visible to HR | Retry up to the limit; ordering by date |
| 2.6 MA-06 | IP9b: a punch owned by a locked day is reported, locked row unchanged | Orphan report unchanged for true orphans; dismissal |
| 2.7 MA-17 | Single-day calculate on a future date returns a validation error | Today and past still work |
| 2.9 MA-33 | Recalculating an unchanged pending record leaves `version` and action rows unchanged | A changed value still writes |
| 2.10 AR-17 | Recalculation run lists dates and engine versions; locked dates skipped | Dry run mode |

### Phase 3

| Item | Red test | Extra |
|---|---|---|
| 3.1 MA-27 | C1-SHORTFALL-CANCEL: after cancel, the shortfall is closed and the period validates; blocker text no longer says "cancel the leave" while it does not work | Shortfall remains when leave still approved; withdrawal; reconcile and apply paths |
| 3.2 MA-11 | Accrual covering an open shortfall closes it (if L-09 approves) | Not covered: stays open |
| 3.3 MA-34/NF-1 | HR with company scope can reassign or decide a manager-stage overtime and regularization record; manager who left no longer blocks close; every action audited | Self-approval still refused; manager still can act; non-HR refused |
| 3.4 MA-36 | Screens for preview/apply reconciliation and orphan punches; calendar-setup text matches | Digest staleness handled; permissions |
| 3.5 MA-35 | A test that every blocker code the API can emit has a label in web and mobile | New code added later fails the test |
| 3.6 MA-31 | C1-DOUBLE-ON-DUTY: a second request for a date with an approved one is refused at submit (no 500) | Early-departure twin; different dates unaffected |
| 3.7 MA-28 | Per H-30: deactivating a linked calendar refused (or effective from a date); leave counting follows | Unlinked calendar can still be deactivated |
| 3.8–3.11 | One test per decision (C-12, C-11, O-20, C-14) | |

### Phase 4

| Item | Red test | Extra |
|---|---|---|
| 4.1 MA-18 | Runtime role cannot `UPDATE` or `DELETE` the four tables (extend `test_runtime_role_grants.py`) | Full integration suite green with the grant revoked (proves no code path writes them) |
| 4.2 / 4.3 | A duplicate `APPLICATION` debit, or a second approved ON_DUTY, is rejected by the database | Duplicates pre-check query empty before upgrade |
| 4.4 MA-22 | Two-session test: punch and finalize race leaves a consistent result | Overtime decision and finalize race |
| 4.5 MA-26 | Timings recorded for the four scenarios in the plan; thresholds agreed with the owner before any optimisation | Re-measure after change |

---

## 3. Evidence that unrelated behaviour did not regress

1. **Golden engine matrix.** Freeze the engine probe set (the audit's 86 scenarios plus the 18 of
   this verification) into a checked-in table of inputs and expected `(status, paid, LOP, worked,
   overtime)`. Every engine change must show a diff of that table with each changed row explained
   by a named finding. Rows the change should not touch must be byte-identical.
2. **Timezone invariance.** The same matrix under `TZ=UTC`, `Asia/Kolkata`, `America/New_York`,
   `Pacific/Kiritimati`: identical.
3. **Order invariance.** The same month calculated in forward order, reverse order and per-day
   random order gives identical rows (cascade correctness).
4. **Existing suites.** Unit (2,301 expected passing, one known `.env`-dependent failure), integration
   and security (2,595 passed, 40 skipped, 1 xfailed at the audit; initialised as CI does), web
   (1,045), Flutter analyze and test, `ruff`, `mypy`, `lint-imports`.
5. **Impact diff** on a copy of any real data: unlocked days only, locked rows byte-identical
   (hash the locked set before and after).
6. **Leave and payroll boundaries:** payroll's read query for a closed period returns the same
   figures before and after for every period whose inputs the change was not meant to touch.

---

## 4. Database and migration verification

For each migration: (a) upgrade from current head on a copy of production-like data; (b) downgrade
one step and confirm schema equality with the previous head; (c) upgrade again; (d) RLS forced on
any new tenant table, with the existing RLS test extended; (e) runtime role privileges verified
after the init script is applied *before* migrations (as CI does); (f) pre-check queries for any
new unique index return zero rows; (g) one head only (`alembic heads`).

## 5. Client contract verification

- Each API change updates the OpenAPI snapshot and the web types; mobile contract fixtures under
  `apps/mobile/test/fixtures/contract` updated and the Dart contract test run (Flutter is not on this
  machine: CI or another host must run it).
- No client recomputes status or pay (existing property); a test keeps it so.
- Every user-facing rule text (templates, screens) is generated from or checked against the engine
  constant it describes (mark ceiling, grace, cliff), so text and behaviour cannot drift again.

## 6. Release-level exit criteria ("attendance may feed a payroll audit")

All must be true, with evidence:

1. No open finding rated High (MA-01 to MA-05, MA-27, MA-34/NF-1) and no Medium finding that changes
   a paid fraction or balance without a blocker (MA-06, MA-07, MA-08, MA-09, MA-10, MA-13, MA-20).
2. Every decision in Group A of `ATTENDANCE_OWNER_DECISIONS_REQUIRED.md` has a recorded answer,
   and every Group C default has a recorded keep or change.
3. All 16 strict-xfail tests converted to passing; no skipped test related to attendance without a
   written reason.
4. R1–R15 run on the target database; each returns zero rows or every row has an accepted
   explanation signed by the owner.
5. Engine 16 (or its successor) and all migrations committed; dev, staging and production at the
   same migration head; Flutter run.
6. Controlled recalculation completed; diff approved; locked rows unchanged.
7. Every period-close blocker has a remedy in the product (screens or documented HR action), and
   labels in both clients.
8. A **payroll-audit dry run**: pick one closed month for a pilot company; for 20 employees chosen
   across shift types (fixed, overnight, split, flexible), pay bases, leave, overtime, comp-off,
   regularization and a mid-month joiner; compute pay inputs by hand from punches and policies and
   compare with the frozen period summary. Zero unexplained differences.
9. The load test of item 4.5 meets the agreed thresholds, or the owner accepts the measured figures.

## 7. Stop-ship conditions

Stop and do not release if: a locked row changes in any impact diff; a migration downgrade fails;
a new test passes before the fix; the golden matrix shows an unexplained changed row; any blocker
has no remedy; any R-report row is unexplained.
