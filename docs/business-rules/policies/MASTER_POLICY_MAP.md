# Master Policy Map

**Status:** Audit document. Structure below is transcribed from actual evaluation order in code (`attendance/calculation.py::evaluate_day`, `leave/service.py::submit`/`_approve_internal`), not assumed.

## 1. Attendance Day — actual evaluation hierarchy

```
ATTENDANCE DAY EVALUATION (evaluate_day, highest wins)
│
├── 1. Employment Population Gate
│   └── NOT_JOINED / ACTIVE / EXITED  (from Employment.joining_date / last_working_day — NOT Employee.status)
│       └── if not ACTIVE: terminal, nothing below applies
│
├── 2. Config Resolution (fail-closed)
│   ├── Calendar unresolved → CONFIG_ERROR
│   └── Policy unresolved (8-level scope walk) → CONFIG_ERROR
│
├── 3. Roster Week-Off Override
│   └── published ShiftRoster.is_week_off_override → NOT_EXPECTED (wins even over calendar WORKING)
│
├── 4. Missing-Shift Handling
│   └── missing_shift_behaviour → ABSENT / INCOMPLETE (unless punches exist)
│
├── 5. Calendar Day-Type
│   ├── HOLIDAY / WEEKLY_OFF / SHUTDOWN → NOT_EXPECTED ...
│   └── ...unless shift.operates_on_holiday / operates_on_weekly_off / roster override says otherwise
│
├── 6. Punch-Derived Evaluation
│   ├── Worked minutes → Hour Bands → PRESENT / HALF_DAY / ABSENT (baseline)
│   ├── Late-Arrival Bands ────┐
│   ├── Early-Departure Bands ─┼── any one can force worse status (ABSENT beats HALF_DAY beats PRESENT); no mutual suppression
│   ├── Core-Hours Breach ─────┤
│   └── Cumulative Overrides ──┘   (lates-to-half-day, excess-break-days-to-half-day)
│
├── 7. Leave Overlay  (LEAVE_DAY_PROJECTION, owned by Attendance, written by Leave module)
│   └── Full-day approved leave WINS OUTRIGHT — even over step 5's NOT_EXPECTED
│       ├── work_on_leave_behaviour = KEEP_LEAVE (default) → status = LEAVE, late/early zeroed
│       └── work_on_leave_behaviour = PRESENT_CANCEL_LEAVE_HINT → keeps step 6's status, flags work_on_leave_flagged
│       (does NOT touch calendar_day_type; does NOT touch ot_minutes_detected — ⚠️ open decision)
│
└── 8. On-Duty Overlay
    └── Approved ON_DUTY regularization → status = ON_DUTY (loses to step 7 if leave also covers the date)

[Regularization is NOT a status branch — approved corrections re-enter as new immutable Punch rows
 (source=REGULARIZATION) + a full re-run of steps 1-8. Overtime is a SEPARATE, parallel computation
 (detect_overtime) that runs independent of this chain and is never overridden by it.]

[Period Lock sits outside this hierarchy entirely: once AttendancePeriod.status=CLOSED, NO step above
 can execute for dates in range — not punches, not roster, not regularization, not recompute, not
 leave-projection sync. It is the one rule that outranks everything else in the system.]
```

## 2. Leave Application — actual evaluation hierarchy

```
LEAVE APPLICATION SUBMISSION (submit(), code order)
│
├── 1. Policy Resolution (8-level scope walk, same engine as Attendance) → fail-closed if unresolved
├── 2. Calendar Resolution (per date in range) → fail-closed if unresolved
├── 3. On-Behalf Permission Gate (self / manager-on-behalf / hr-on-behalf)
├── 4. Probation Restriction (Employee.status == PROBATION vs allowed_during_probation)
├── 5. Half-Day Validity (single-date only, half_day_allowed)
├── 6. Reason / Attachment Required
├── 7. Backdating Window (max_backdated_days; no future-date limit)
├── 8. Monthly Request Cap (max_requests_per_month)
├── 9. Day-Breakdown Computation
│   ├── WORKING / SPECIAL_WORKING → consumes leave
│   ├── WEEKLY_OFF / HOLIDAY / SHUTDOWN → does not consume ...
│   └── ...UNLESS Sandwich Rule brackets it between two consuming days (same application only)
├── 10. Leave Combination Rule (blocks overlap with a DIFFERENT type only if an explicit deny rule exists)
└── 11. Balance Sufficiency (optionally net of reserved/pending balance) → hard block, negative balance NEVER allowed

LEAVE APPROVAL (multi-stage, chain-dependent)
│
AUTO ──────────────► immediately approved, no stage
MANAGER ───────────► resolved-manager approval → FINAL
MANAGER_THEN_HR ───► manager → HR → FINAL
MANAGER_THEN_HOD_THEN_HR ─► manager → HOD → HR → FINAL   (any unresolved identity stage is DROPPED;
HR ────────────────► HR approval → FINAL                  if ALL identity stages unresolved, falls back to single HR stage)
│
└── On FINAL approval only:
    ├── Ledger debit (APPLICATION entry, unless requires_balance=False)
    └── Sync LeaveDayProjection → Attendance (SAME transaction)
        └── Attendance period CLOSED for that date? → sync refused → ENTIRE approval transaction rolls back
            (application stays SUBMITTED, not partially approved)

Self-approval: BLOCKED UNCONDITIONALLY at every stage, no policy field can re-enable it.
```

## 3. Cross-Module Map

```
                        ┌─────────────────────────────┐
                        │   8-LEVEL POLICY RESOLUTION   │   (SHARED-POL-001)
                        │  EMPLOYEE > SHIFT > DESIGNATION│
                        │  > GRADE > DEPARTMENT > BRANCH │
                        │  > LEGAL_ENTITY > COMPANY      │
                        └──────────┬──────────┬─────────┘
                                   │          │
                     resolves     │          │     resolves
              AttendancePolicy/   │          │   LeavePolicyVersion
              OvertimePolicy/     │          │   (per leave_type)
              RegularizationPolicy│          │
                                   ▼          ▼
                        ┌──────────────┐  ┌──────────────┐
                        │  ATTENDANCE   │  │    LEAVE      │
                        │    MODULE     │  │    MODULE     │
                        └──────┬───────┘  └──────┬───────┘
                               │                  │
              owns:            │                  │  owns:
        LeaveDayProjection ◄───┼──── writes ──────┤   LeaveApplication
        (mirror table)         │   (sync/cancel,   │   LeaveLedgerEntry (append-only)
                               │    same txn as     │   LeavePolicyVersion
                               │    approval)        │
                               │                  │
        reads (facts only) ────┼──────────────────┤   reads (facts only, via
        OvertimeRecord             comp_off_minutes    list_comp_off_facts — read-only,
        .comp_off_minutes          / expiry_date         Leave never writes Attendance tables)
        .comp_off_expiry_date  ─────────────────────►
                               │
        AttendancePeriod       │
        lock state ────────────┼──── gates ───────►   Leave approval / cancellation
        (OPEN/CLOSED)             (CLOSED = refuse,      (transaction rolls back on refusal)
                                    no arrears path,
                                    PD-XMOD-004 open)

        Employment.joining_date/last_working_day
                │
                ├──► Attendance population_status (NOT_JOINED/ACTIVE/EXITED)
                └──► Leave accrual proration + ANNIVERSARY leave-year anchor

        Employee.status (PROBATION/ACTIVE)
                │
                └──► read ONLY by Leave (probation eligibility/accrual gate) — Attendance never reads this field
```

## 4. What this map deliberately does NOT show

- No "money"/payroll layer exists in either module — both stop at paid/LOP fractions or ledger day-counts; a Payroll module is out of scope for this audit (confirmed absent in both source trees).
- Overtime's interaction with Leave is drawn as absent on purpose — there genuinely is no rule connecting the two boxes for OT (PD-XMOD-001), which is why no arrow is drawn between Overtime and Leave above.
