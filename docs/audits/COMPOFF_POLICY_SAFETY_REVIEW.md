# Comp-off Policy Safety Review (Step 2, decision 13)

| Field | Value |
|---|---|
| Date | 2026-09-23 |
| Scope | Decision 13 (`BUS-015`) in [`PAYROLL_BUSINESS_DECISIONS.md`](./PAYROLL_BUSINESS_DECISIONS.md): the 0 / 0.5 / 1-day comp-off step rule, existing balances, idempotency, expiry |
| Product call | 2026-09-23, varun: **defer the step rule**, fix the expiry race, add safety tests, document the decisions still needed |
| Status | **NOT READY — BUSINESS DECISION REQUIRED** (for the step rule). The changes delivered here are safe on their own; see §18 |

---

## 1. Current comp-off architecture

```
Punches ─▶ Attendance engine (calculation.py)
             detect_overtime: excess = max(0, worked − scheduled shift minutes)
                              → min-OT, rounding, daily/weekly/monthly caps
             comp_off_minutes = detected OT   (only when policy.comp_off_instead_of_pay)
         ─▶ overtime_record  (status, minutes_detected, comp_off_minutes,
                              comp_off_expiry_date = date + expiry_days (default 60),
                              overtime_policy_version_id)
             terminal statuses (AUTO_APPROVED / APPROVED / REJECTED) are frozen on recompute
         ─▶ OvertimeRecordService.list_comp_off_facts  (read-only seam, LD-07/LD-14)
             terminal + comp_off_minutes > 0,
             day length = COALESCE(policy_version.comp_off_day_length_minutes,
                                   attendance_day.scheduled_minutes)
         ─▶ leave.run_comp_off_credit_sweep (hourly) → LeaveCompOffService.credit_company
             amount = comp_off_minutes ÷ day length, 2 dp, ROUND_HALF_UP
             one COMP_OFF_CREDIT ledger row, reference_id = overtime_record.id,
             effective_date = attendance date
         ─▶ leave.run_comp_off_expiry_sweep (daily 01:30 IST) → expire_company
             expiry date reached AND current balance ≥ credit amount
             → ADJUSTMENT −amount, reference_id = credit id
         ─▶ Redemption: an ordinary leave application against the is_comp_off leave type
```

Balance is always `SUM(leave_ledger.amount)` (`numeric(6,2)`), and the ledger is append-only (LD-03).

## 2. Current behaviour: answers to the data-model questions

| Question | Answer |
|---|---|
| Stored as days or minutes? | **Both.** Minutes on `overtime_record.comp_off_minutes`, days on `leave_ledger.amount`. |
| Arbitrary fractional days? | **Yes.** 2 dp; e.g. 60 min ÷ 480 = `0.13`. |
| Historical credits as ledger rows? | **Yes.** One immutable `COMP_OFF_CREDIT` per overtime record. |
| Can balances be `0.13`, `0.25`, `0.75`…? | **Yes.** From proportional credits and from HR `ADJUSTMENT`s. |
| Original worked duration retained? | **Yes.** `attendance_day.worked_minutes`, `overtime_record.minutes_detected` / `comp_off_minutes`. |
| Source record retained / audit trail? | **Yes.** `leave_ledger.reference_id` → `overtime_record.id` → `attendance_day_id`. The OT side also writes a `COMP_OFF_EARNED` audit row. |
| Can a credit be reversed? | Not automatically. Terminal OT records are frozen and have no revoke path, so the source never changes. HR can offset a credit with a manual `ADJUSTMENT`. |
| Can expiry run more than once? | Yes, and a re-run is a no-op (an "already offset?" check). Before this review it was **not** safe for concurrent runs (§9). |
| Is the credit idempotent? | **Yes, DB-enforced.** The partial unique index `uq_leave_ledger_comp_off_credit` on `(company_id, reference_id) WHERE entry_type = 'COMP_OFF_CREDIT'`, with `INSERT … ON CONFLICT DO NOTHING` (DAT-001). |

## 3. Problems identified

| # | Problem | Severity | Status |
|---|---|---|---|
| P1 | **The step rule can't mean "hours worked" on today's input.** `comp_off_minutes` is overtime *beyond the shift*, even on a weekly off or holiday: the schedule window doesn't depend on day type. With an 8 h shift, working 5 h or 8 h on a weekly off gives **0** comp-off minutes, and 10 h gives 120. Decision 13's "≥ full shift worked = 1 day" is unreachable for off-day work unless the employee works two shifts. | High (business) | Open — decision D1 |
| P2 | **On today's input the step rule only ever lowers credits.** For any minutes *x* and day length *d*: step(*x*) ≤ *x*/*d*, equal only at exactly *d*/2 or *d*. For example, 2 h OT on a normal day is 0.25 today and 0 under the rule. Enabling it silently would cut future entitlement for everyone. | High (entitlement) | Deferred, not built |
| P3 | **Concurrent expiry sweeps could expire the same credit twice.** The check and the insert were not serialised (Celery Beat has no leader election, OPS-006). Reproduced: two overlapping sweeps each wrote an `ADJUSTMENT`. | High (entitlement) | **Fixed** |
| P4 | Expiry is all-or-nothing per credit. If the balance is below a credit's amount, that credit never expires (LD-14 heuristic; errs in the employee's favour). | Low | Documented; decision D7 |
| P5 | The balance is pooled. An expired credit can be spent until the next daily sweep. A leave application is not checked against the expiry dates of the credits it consumes. | Low | Documented |
| P6 | If HR assigns a leave policy with `LAPSE` or a carry-forward cap to the comp-off leave type, year-end processing can remove comp-off before its 60-day expiry. It never double-removes, because expiry skips when the balance is too low. | Medium (config) | Documented; decision D8 |
| P7 | Leave is applied in whole or half days, so a residual such as `0.13` can't be spent on its own until later credits bring it up to 0.5. | Low | Documented; decision D5 |

## 4. Recommended safest model

1. **Keep proportional crediting** until D1–D6 are decided. It is today's behaviour, and it never pays less than the step rule would.
2. When the step rule is approved, add it as an **opt-in, per-overtime-policy-version** setting (e.g. `comp_off_credit_mode = PROPORTIONAL | HALF_DAY_STEPS`, NOT NULL, default `PROPORTIONAL`). No extra threshold columns: half = day length ÷ 2 and full = day length, compared in integers (`2·x ≥ d`, `x ≥ d`). The existing `comp_off_day_length_minutes` (or the shift fallback) already sets the full-day threshold.
3. The credit engine reads the mode from the record's **own** `overtime_policy_version_id`. It already reads the day length this way, and that is proven by `test_later_policy_version_does_not_change_how_an_earlier_record_is_credited`.
4. The **effective date is the `effective_from` of the version HR publishes** with the new mode. No global cut-over date is needed or invented.
5. Decide the measurement basis (D1) *before* building step 2. Otherwise the rule ships with the P1 defect.
6. Overtime detection stays unchanged for comp-off purposes. If D1 needs off-day work counted in full, that change is to how overtime is detected, and it affects paid OT too. It needs its own decision and must not be slipped in through comp-off.

## 5. Existing-balance impact analysis

- **This change:** none. No credit amount, balance, or historical ledger row changed. The expiry fix changes *when* the sweep may write (serialised), not *what* it writes.
- **Dev database (read-only query, 2026-09-23):** 0 comp-off ledger rows. One creditable overtime record (2026-08-10, working day, 60 comp-off minutes, 540 scheduled), not credited because no comp-off leave type is designated. If one is designated later, it would be credited `0.11` under the unchanged rule.
- **Production:** not inspected here. Run this read-only query before any future switch:

  ```sql
  SELECT l.company_id, count(*) AS credits,
         count(*) FILTER (WHERE l.amount * 2 <> round(l.amount * 2)) AS not_half_multiples,
         sum(l.amount) AS total_days
  FROM leave_ledger l JOIN leave_type t ON t.id = l.leave_type_id
  WHERE t.is_comp_off AND l.entry_type = 'COMP_OFF_CREDIT'
  GROUP BY l.company_id;
  ```

- **Under the recommended model (§4):** historical credits and balances stay exactly as they are. Records produced by a pre-cut-over policy version, including uncredited backlog, are credited proportionally.

## 6. Migration decision

**No migration.** Nothing required one, and the step rule was not built. The future `comp_off_credit_mode` column (§4) would be additive only: a NOT NULL default of `PROPORTIONAL`, no data rewrite, and a reversible drop.

## 7. Policy effective-date decision

**Not decided. Not invented.** Recommended mechanism: the `effective_from` of the overtime-policy version that turns the step mode on, one decision per policy. Pending as D3.

## 8. Idempotency analysis

| Operation | Key | Enforcement | Tests |
|---|---|---|---|
| Credit | `(company_id, reference_id = overtime_record.id)` for `COMP_OFF_CREDIT` | Partial unique index + `ON CONFLICT DO NOTHING` (DAT-001) | Re-run: `test_credit_converts_minutes_to_days_and_is_idempotent`. Concurrent: `test_concurrent_credit_sweeps_credit_a_record_once` |
| Expiry | `reference_id = credit.id` on the offsetting `ADJUSTMENT` | Read check, now under the per-employee comp-off balance advisory lock | Re-run: `test_expiry_offsets_full_amount_when_balance_still_covers_it`, `test_default_60_day_expiry_boundary_and_late_catch_up`. Concurrent: `test_concurrent_expiry_sweeps_expire_a_credit_once` |

This uses existing domain identifiers only. No second ledger or key table was added.

## 9. Expiry analysis

- **Policy-driven:** `overtime_policy_version.comp_off_expiry_days`, defaulting to 60 (decision 13). It is stamped onto `overtime_record.comp_off_expiry_date` when the OT decision is made.
- **Date basis:** the attendance date + N days. The credit is usable through the day before the expiry date and expires on it. With the default, a credit earned on 2026-08-10 is usable through 2026-10-08 and expires on 2026-10-09 (tested). A sweep that first runs late still expires the credit, once (tested).
- **No reuse after expiry:** the offset takes the amount out of the pooled balance (see P5 for the window before the sweep).
- **Negative balances:** never touched. The sweep skips when the balance is below the credit (tested at `-0.87`).
- **Concurrency (fixed):** `expire_company` now takes `LeaveLedgerRepository.lock_balance(employee, comp-off type)` before the "already offset?" check and the balance read. This is the same transaction-scoped advisory lock leave approval takes (PAY-010). Under READ COMMITTED, a second sweep blocks until the first commits and then sees its offset. An approval can't spend the balance between the check and the offset. `list_credits_for_expiry` orders by employee, effective date, and id, so concurrent sweeps take locks in the same order (no deadlock). A unique index was rejected: it would also constrain leave-cancel `ADJUSTMENT`s (`reference_id` = application id) and need a migration.
- **Auditability:** historical rows stay append-only. Each expiry is its own `ADJUSTMENT`, with a reason naming the earn date.

## 10. Tests added / updated

New file: `apps/api/tests/integration/modules/leave/test_leave_comp_off_safety.py`

| Test | Covers |
|---|---|
| `test_fractional_balances_are_never_rounded_by_the_sweeps` | Balances of 0.13 / 0.25 / 0.50 / 0.75 unchanged by repeated credit and not-yet-due expiry sweeps; the original credit row is still `0.13` |
| `test_later_policy_version_does_not_change_how_an_earlier_record_is_credited` | Historical calculation preserved: an uncredited record is credited from its own version (60/480 = 0.13, not 60/240), and an existing credit is never recomputed |
| `test_default_60_day_expiry_boundary_and_late_catch_up` | Day before expiry, late first run, duplicate run |
| `test_concurrent_expiry_sweeps_expire_a_credit_once` | Deterministic overlap: sweep A holds an uncommitted offset while sweep B starts. **Failed before the fix with `(1, 1)`** (double expiry) and passes after |
| `test_concurrent_credit_sweeps_credit_a_record_once` | Concurrent credit gives one ledger row |
| `test_expiry_never_touches_a_negative_comp_off_balance` | A negative balance is untouched by expiry and credit sweeps |

Existing tests cover the exact expiry boundary (`test_expiry_offsets_full_amount_when_balance_still_covers_it`, 90 days) and credit idempotency.

**Not added:** threshold tests (< half → 0, = half → 0.5, … > full → 1). The step rule was deliberately not built, and adding tests for unbuilt behaviour would be misleading. They belong with the step-mode implementation.

## 11. Test results

- `tests/integration/modules/leave/test_leave_comp_off_safety.py` + `test_leave_comp_off.py`: **12 passed**.
- `tests/integration/modules/leave`, `tests/integration/modules/attendance`, `tests/unit/modules/attendance`: **417 passed**.
- Full API suite: see §11a.
- `ruff check`: clean on touched files. `mypy` on `leave/service.py` and `leave/repository.py`: clean. `ruff format` applied to the new test file only. The two source files have formatter drift in untouched code, which was left alone on purpose.

### 11a. Full suite

**1558 passed, 1 failed, 22 errors** (328 s). All 23 are the known pre-existing baseline and none is related to this change:
`test_account_invite.py::test_invite_employee_accept_and_login_success` has a stale hardcoded permission set, and the 22 errors in `tests/integration/auth/*` come from leftover dev-DB `onboarding_case` rows for the shared fixed test user.

## 12. Documentation changes

- `docs/audits/PAYROLL_BUSINESS_DECISIONS.md`: decision 13 row notes the deferred step rule; new progress row; expiry follow-up marked fixed; step-rule follow-up explains the deferral.
- `docs/architecture/LEAVE_DECISION_LOG.md`: LD-14 amendments (shift-minutes fallback, credit uses the record's own version, expiry locking, step rule deferred).
- `docs/business-rules/attendance/01_ATTENDANCE_BUSINESS_RULES.md` §15: documents that off-day OT is still measured beyond the shift, and what that means for comp-off.
- This report.

## 13. Remaining business decisions

| ID | Question | Recommended default |
|---|---|---|
| D1 | **What does the step rule measure?** (a) today's comp-off minutes (OT beyond the shift); (b) all minutes worked on a weekly off or holiday; (c) something else. Option (b) means either changing off-day OT detection (which also changes paid OT) or adding a new comp-off source event outside overtime records. | (b), designed as its own change, since that matches the wording "full shift hours worked" |
| D2 | Does comp-off still accrue from overtime on **normal working days**? Under the step rule, 2 h OT = 0. | Comp-off from off-day/holiday work only; working-day OT paid |
| D3 | Effective-date mechanism | Per overtime-policy version (`effective_from`), opted in per policy |
| D4 | Historical credits | Preserved exactly as written (confirm) |
| D5 | Existing fractional balances (e.g. `0.13`) | Kept exactly and never rounded. Any consolidation or payout only with explicit approval and reconciliation |
| D6 | More than 2× a shift on one off day: cap at 1 day or allow 1.5 / 2? | Cap at 1, consistent with the decision text (confirm) |
| D7 | Expiry of a partly-spent credit: keep all-or-nothing (LD-14) or build FIFO lots? | Keep, since it errs in the employee's favour |
| D8 | Should year-end lapse or carry-forward rules be allowed on the comp-off leave type? | No: exclude `is_comp_off` from year-end processing, with 60-day expiry as the only removal |

## 14. Remaining technical risks

- P5: the pooled balance allows spending expired comp-off until the next daily sweep.
- P6: a year-end `LAPSE` misconfigured on the comp-off type (until D8).
- The expiry sweep holds per-employee advisory locks until its transaction commits. Leave approvals for those employees wait for that sweep, which is a short batch at 01:30 IST.
- Full-table scan of `COMP_OFF_CREDIT` rows on every sweep (LD-14 known scaling boundary).
- The off-day OT behaviour (P1) also affects **paid** OT on off days. This needs its own review before Payroll.

## 15. Exact files changed

| File | Change |
|---|---|
| `apps/api/src/hrms/modules/leave/service.py` | `LeaveCompOffService.expire_company`: per-credit `lock_balance`, `get_balance` for the comp-off type, docstring |
| `apps/api/src/hrms/modules/leave/repository.py` | `list_credits_for_expiry`: deterministic `ORDER BY` |
| `apps/api/tests/integration/modules/leave/test_leave_comp_off_safety.py` | New (6 tests) |
| `docs/audits/PAYROLL_BUSINESS_DECISIONS.md` | See §12 |
| `docs/architecture/LEAVE_DECISION_LOG.md` | See §12 |
| `docs/business-rules/attendance/01_ATTENDANCE_BUSINESS_RULES.md` | See §12 |
| `docs/audits/COMPOFF_POLICY_SAFETY_REVIEW.md` | New (this report) |

No frontend change: no configuration was added, and the existing comp-off field descriptions are accurate. `leave/service.py`, `leave/repository.py` and `PAYROLL_BUSINESS_DECISIONS.md` already held **uncommitted step-2 work** from the earlier batch. A commit of only this review must be split by hunk.

## 16. Migration created?

**No.**

## 17. Existing balances untouched?

**Yes.** No ledger row was written, rewritten, rounded or deleted by this change. No data migration ran against any database. The dev DB was only read.

## 18. Commit readiness

**NOT READY — BUSINESS DECISION REQUIRED** for decision 13's step rule (D1–D6).

The delivered changes (the expiry concurrency fix, the tests, the docs) are complete and tested, and they don't change any credit amount. They are safe to commit on their own, together with or split from the earlier step-2 batch. Nothing has been committed or staged.
