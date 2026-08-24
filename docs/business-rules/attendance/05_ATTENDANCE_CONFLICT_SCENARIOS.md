# 05 — Attendance Conflict Scenarios

For each conflict: winning rule, status, worked minutes, paid/LOP, OT, actor views, correction, recalc, audit.

Legend answers use **current code**.

---

## 1. Calendar conflicts

### C1 — Holiday + Weekly Off
1. Rule: WD-05 hard holiday on WO. 2. Priority: WO wins type. 3. Status: NOT_EXPECTED (no work). 4–6. Worked 0; paid 1; lop 0. 7. OT 0. 8–9. Employee/HR see WEEKLY_OFF + holiday flag. 10. Correction: exception SUBSTITUTE if needed. 11. Recalc if unlocked. 12. Audit on calendar mutate only.

### C2 — Holiday + Roster Working
1. roster_holiday_working_override or operates_on_holiday. 2. Expectation override wins vs not_expected. 3. Evaluated PRESENT/…. 4. Worked from punches. 5–6. Per status. 7. OT may classify HOLIDAY if worked_on_holiday. 8–9. Working holiday attendance. 10. Reg/roster while open. 11. Yes on change. 12. Roster + day audit.

### C3 — Holiday + Roster Off
1. Week-off override. 2. Override expectation. 3. NOT_EXPECTED if no punches. 4–7. 0 / paid 1. 8–9. Off. 10–12. Roster edits while open.

### C4 — Holiday + Leave
1. Leave overlay + calendar HOLIDAY. 2. Status LEAVE; type HOLIDAY. 3. LEAVE. 4. Usually 0. 5–6. From leave paid flags. 7. OT columns may residual — see gap. 8–9. Leave on holiday date. 10. Cancel projection / leave module FUTURE. 11. Sync triggers calc. 12. Projection audit.

### C5 — Holiday + Punch (no operate)
1. Punches on not-expected day without operate → still evaluated (not short-circuit NOT_EXPECTED). 2. Presence path. 3. PRESENT/INCOMPLETE/…. 4. Worked >0. 5–6. Per status. 7. May set worked_on_holiday + OT. 8–9. Worked on holiday. 10. Reg. 11. Yes. 12. Punch audit.

---

## 2. Shift / roster conflicts

### C6 — Assignment Shift A + Roster Shift B
Winner: **B for schedule**. Policy SHIFT scope may still be A. Status per B schedule. Recalc on publish. Audit roster.

### C7 — Roster Shift + Holiday
Calendar HOLIDAY unchanged; expectation via operate/override. See C2/C5.

### C8 — Roster Shift + Weekly Off
Same pattern as holiday.

### C9 — Roster Shift + Leave
Leave overlay after schedule eval. Full leave → LEAVE.

### C10 — Roster + Regularization WRONG_SHIFT
Approval may publish roster to requested_shift_id then recalc. Winner: applied roster + synthetic punches.

---

## 3. Attendance conflicts

### C11 — Late + Leave (KEEP)
Leave wins status; late zeroed.

### C12 — Late + WFH
WFH status not produced; late rules N/A for WFH overlay.

### C13 — Late + Regularization
After approve, new punches recalc late.

### C14 — Early + Leave
Same as late under KEEP_LEAVE.

### C15 — Early + OT
Early reduces worked; OT from remaining excess only.

### C16 — Missing Punch + Leave
Full leave → LEAVE (even if incomplete punches). Half leave + missing → HALF_DAY or LEAVE per work minutes.

### C17 — Missing Punch + Regularization
Intended path: add OUT/IN via request → PRESENT/….

### C18 — Multi-punch + Regularization
Adds more punches; pairing uses full set; duplicates may collapse.

---

## 4. OT conflicts

### C19 — Holiday + OT
day_class HOLIDAY when worked_on_holiday.

### C20 — Weekly-off + OT
day_class WEEKLY_OFF when worked_on_weekly_off.

### C21 — Leave + OT
KEEP_LEAVE does not clear OT fields in overlay replace — **edge**. Product should decide.

### C22 — Night + OT
Classification NIGHT only under WINDOW/BOTH + is_cross_midnight; windows unused.

### C23 — Split + OT
OT vs required_minutes; late not computed.

### C24 — OT + Lock
Approve/reject blocked; pending blocks finalize.

### C25 — OT + Regularization
Recalc may change detected OT if still PENDING; terminal OT frozen (WD-29).

---

## 5. Leave conflicts

### C26 — Leave + Holiday — See C4
### C27 — Leave + Weekly Off — Status LEAVE; type WEEKLY_OFF
### C28 — Leave + Punch — KEEP vs HINT
### C29 — Leave + WFH — WFH not implemented
### C30 — Leave + Regularization — Reg still punch-based; leave overlay reapplies after calc
### C31 — Leave + OT — See C21
### C32 — Leave + Lock — Sync refused

---

## 6. Period conflicts

### C33 — Regularization + Finalization
SUBMITTED → BLOCKED finalize. Approve/reject first.

### C34 — OT Approval + Finalization
PENDING OT → BLOCKED.

### C35 — Punch + Finalization
Missing days → EMPLOYEES_WITHOUT_ATTENDANCE. After CLOSED punches refused.

### C36 — Roster Change + Finalization
DRAFT roster → UNPUBLISHED_ROSTER blocker. After close, mutation refused.

### C37 — Leave Projection + Finalization
Not a named blocker by itself; affects day status. After close, sync refused. CONFIG_ERROR/INCOMPLETE still apply.

---

## 7. Matrix (compact)

| ID | Winner | Status | Worked | Paid/LOP | OT | Emp/HR see | Correct? | Recalc? | Audit? |
|---|---|---|---|---|---|---|---|---|---|
| C1 Holiday+WO | WO type | NOT_EXPECTED | 0 | 1/0 | 0 | WO+flag | Exception | if open | calendar |
| C2 Hol+Roster work | Expectation | Present-like | >0 | per status | HOLIDAY class | worked holiday | Yes open | Yes | roster/day |
| C6 A vs B roster | Roster sched | per B | per B | per | per | Shift B | Yes | Yes | roster |
| C11 Late+Leave | Leave | LEAVE | may remain | leave | residual? | Leave | Leave/reg | Yes | leave/day |
| C17 Miss+Reg | Reg punches | Present-like | fixed | per | per | Corrected | Via reg | On approve | reg+punch |
| C24 OT+Lock | Lock | unchanged | — | — | frozen/block | Locked | Reopen/FUTURE | No while closed | period |
| C33 Reg+Finalize | Validation | — | — | — | — | Blocked close | Resolve regs | — | period validate |
