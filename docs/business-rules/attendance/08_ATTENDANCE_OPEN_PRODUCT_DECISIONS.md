# 08 — Open Product Decisions & Recommended Business Rules

This document separates **current behaviour** from **recommendations**.  
Recommendations do **not** change architecture silently; they require product sign-off before implementation.

---

## Part A — Existing open decisions (from architecture §32 / decision log)

| ID | Topic | Current default in code | Notes |
|---|---|---|---|
| PD-CAL-1 | Optional/RH off-by-default vs working-until-Leave | Working until Leave; WorkCalendar flag can harden | Flag implemented |
| PD-CAL-2 | Auto-substitute holiday on WO | No auto-substitute | Manual exceptions only |
| PD-APR-1 | Approver as-of attendance date vs current | As-of attendance date (assignment on that date) | Implemented for manager snapshot |
| PD-POL-1 | Configurable engine precedence in V1 | Engine order locked | Do not expose reorder UI |
| PD-POL-2 | Keep grace on Shift as well | Evaluation grace on Attendance Policy only | Legacy Shift columns unused by engine |
| PD-SHIFT-1 | Intra-day shift change | Not supported | One schedule per attendance date |
| PD-LOCK-1 | Lock grain LE vs company | Company period; legal_entity_id unused | |
| PD-WFH-1 | Auto WFH from assignment location | No | |
| PD-OT-1 | OT post-approval default | requires_post_approval=true | |
| PD-SCOPE-1 | Branch HR without BRANCH scope | COMPANY for HR roles (RBAC reality) | |
| PD-BR14-SHIFT | Default-shift cascade | Still deferred (DEC-018) | NULL shift fail-closed path |

---

## Part B — New decisions surfaced by implementation audit

### ND-01 — Fate of stored-but-unused policy fields

**Problem:** Many W3 fields are editable in UI but ignored by the engine → false confidence.  
**Choices:** (1) Implement behaviour, (2) Hide/disable in UI until implemented, (3) Remove columns later.  
**Recommended:** (2) short-term + backlog for true product needs (rounding, late-count, WFH).  
**Impact:** Employees—none until implemented; HR—honest config; Payroll—fewer surprise gaps.  
**Implementation:** UI/docs first; no silent engine guesses.

### ND-02 — Roster vs SHIFT policy scope

**Problem:** Roster changes schedule but SHIFT-scoped policies still key off assignment.shift_id.  
**Choices:** (1) Resolve SHIFT scope using roster shift for that date, (2) Document as intentional, (3) Disallow SHIFT scope.  
**Recommended:** (1) align with architecture comment “shift resolved for that date, including roster”.  
**Impact:** Correct policy when people temporarily change shift; HR fewer mismatches.  
**Implementation:** Change `_scope_candidates` / policy resolution input only; record WD entry.

### ND-03 — Night OT classification

**Problem:** Default `night_ot_mode=SHIFT_FLAG` never emits day_class NIGHT; windows unused.  
**Choices:** (1) Fix classify so SHIFT_FLAG + is_cross_midnight → NIGHT, (2) Implement WINDOW properly, (3) Drop NIGHT class until designed.  
**Recommended:** (1) + document WINDOW as future; keep no money.  
**Impact:** Correct OT classification for night plants; payroll handoff clearer.  
**Implementation:** One-line classify fix + tests; WINDOW later.

### ND-04 — Leave overlay residual OT / worked minutes

**Problem:** KEEP_LEAVE sets status LEAVE but leaves worked_minutes/OT fields from punch path.  
**Choices:** (1) Zero OT/worked on KEEP_LEAVE, (2) Keep as audit of presence on leave, (3) Force hint mode only when punches exist.  
**Recommended:** (1) for payroll-facing columns; retain raw punches immutable.  
**Impact:** Cleaner payroll facts; HR still sees punches separately.  
**Implementation:** Extend `_apply_leave_overlay` replace fields; snapshot retains detail.

### ND-05 — AUTO_CLOSE missing punch

**Problem:** Enum value suggests auto OUT; code does not create one.  
**Choices:** (1) Implement synthetic OUT at shift end / after N minutes, (2) Remove/rename enum, (3) Map AUTO_CLOSE → INCOMPLETE in UI.  
**Recommended:** (3) now; (1) only if clients demand with explicit rules.  
**Impact:** Avoid HR believing days auto-closed.  

### ND-06 — WFH / ON_DUTY

**Problem:** Types and statuses promised; engine never produces statuses.  
**Choices:** (1) Implement WD-17 overlays, (2) Remove from allowed regularization until ready, (3) Map WFH reg to punches-only documentation.  
**Recommended:** (2) in product copy + (1) scheduled slice.  
**Impact:** Honest employee/manager expectations.

### ND-07 — GRADE_VIA_ASSIGNMENT OT eligibility

**Problem:** Behaves like ALWAYS.  
**Choices:** (1) Implement grade flag/table, (2) Remove enum value, (3) Alias to ALWAYS in docs.  
**Recommended:** (2) or implement (1) if grade OT is a real India manufacturing need.  

### ND-08 — Period reopen recompute policy

**Problem:** Reopen unlocks without recalc → stale days possible.  
**Choices:** (1) Mandatory bulk recompute on reopen, (2) Explicit HR action checklist, (3) Version stamp “stale” flag.  
**Recommended:** (2) for V1; (1) optional gated job.  
**Impact:** Payroll safety after unlock.

### ND-09 — Half-day leave FIRST/SECOND

**Problem:** Stored but not used to limit evaluation window.  
**Choices:** (1) Evaluate only that half of shift, (2) Keep flat 0.50, (3) Drop half enum.  
**Recommended:** Keep (2) documented until Leave module defines contract; then (1).  

### ND-10 — Post-lock corrections

**Problem:** No AttendanceAdjustment; reopen is blunt.  
**Choices:** (1) Build WD-18 adjustment with payroll arrears, (2) Always reopen+recalc, (3) Manual payroll only.  
**Recommended:** (1) before first paid customer close.  

---

## Part C — Recommended Business Rules Requiring Product Decision

Format: Problem → Choices → Recommended → Why → Impacts → Implementation consequence.

### R1 — Holiday on weekly-off stays WO
**Problem:** Clients often expect next-day substitute automatically.  
**Choices:** Keep WD-05; or auto-create SUBSTITUTE.  
**Recommended:** Keep WD-05; provide HR playbook for exception pairs.  
**Why:** Matches locked decision; avoids silent calendar mutation.  
**Employees:** No surprise off; HR: manual substitute.  
**Payroll:** Predictable NOT_EXPECTED.  
**Impl:** None (docs/training).

### R2 — Fail closed on missing calendar/policy
**Problem:** Temptation to default WORKING/PRESENT.  
**Recommended:** Keep CONFIG_ERROR.  
**Why:** WD-21; wrong paid days worse than blocked close.  
**Impl:** None.

### R3 — Missing punch defaults to INCOMPLETE not ABSENT
**Recommended:** Keep default INCOMPLETE; ABSENT explicit.  
**Why:** Architecture §11.5.  
**Impl:** None.

### R4 — Regularization never deletes punches
**Recommended:** Keep additive punches only.  
**Why:** WD-18/WD-28 auditability.  
**Impl:** None.

### R5 — OT never computes money
**Recommended:** Keep facts + informational multiplier only.  
**Why:** ADR-0006.  
**Impl:** Payroll module later.

### R6 — Align SHIFT policy scope with roster
See ND-02 — **recommended change** after sign-off.

### R7 — Honest config surface
See ND-01 — hide unused fields until behaviour exists.

### R8 — Night OT semantics
See ND-03 — fix SHIFT_FLAG classification after sign-off.

### R9 — Leave day payroll columns
See ND-04 — zero OT/worked on KEEP_LEAVE after sign-off.

### R10 — Comp-off redemption is Leave’s job
**Recommended:** Attendance only emits facts (current).  
**Why:** ADR-0004.  
**Impl:** Leave module.

---

## Part D — Sign-off package (business, not technical)

Ask the client/product owner to confirm:

1. Calendar conflict rules (esp. holiday-on-WO, optional holidays).  
2. Shift vs Policy vs OT vs Regularization split.  
3. Fail-closed CONFIG_ERROR.  
4. INCOMPLETE vs ABSENT philosophy.  
5. Leave overlay KEEP vs hint.  
6. OT approval default and caps.  
7. Period close blockers and reopen behaviour.  
8. Whether unused policy fields should be hidden.  
9. Whether roster should drive SHIFT-scoped policies.  
10. WFH/ON_DUTY timeline.  
11. Post-lock correction approach.  
12. India patterns: alternate Saturdays, regional calendars, comp-off as fact only.

No approval is requested for ORM column names, permission string spellings, or migration IDs.
