# Master Policy Decision Register

**Status:** Audit document — consolidated register of every unresolved or explicitly-flagged decision surfaced across all other documents in this audit set, plus decisions already open in the pre-existing attendance business-rule documentation that remain unresolved as of 2026-09-07. No option was invented where the implementation/documentation doesn't already support one.

**Decision-type legend:**
- **Client Business Decision** — needs an answer from the client/business owner (e.g. "should X be allowed")
- **Product Decision** — needs an answer from the product owner about scope/priority
- **Technical Decision** — needs an engineering call about implementation approach, not business meaning
- **Implementation Verification** — needs someone to confirm current behaviour is/isn't intentional before it's signed off as policy

---

## Carried-forward decisions already open in existing Attendance documentation (pre-dating this audit)

| Decision ID | Module | Policy Area | Decision Required | Options | Priority | Status |
|---|---|---|---|---|---|---|
| PD-CAL-1 | Attendance | Optional/Restricted holiday default | Should optional/restricted holidays be off-by-default? | Working-until-Leave (current) / Off-by-default | Medium | ⚠️ Open |
| PD-CAL-2 | Attendance | Holiday-on-weekly-off | Should the system auto-substitute a holiday landing on a weekly-off day? | No auto-substitute (current) / Auto-substitute to next working day | Medium | ⚠️ Open |
| PD-POL-1 | Attendance | Engine precedence configurability | Should the fixed evaluation order in `calculation.py` ever be exposed as a reorderable UI setting? | Keep locked (current) / Expose reorder UI | Low | ⚠️ Open |
| PD-SHIFT-1 | Attendance | Intra-day shift change | Should an employee be able to have more than one schedule per attendance date? | Not supported (current) / Support intra-day change | Low | ⚠️ Open |
| PD-LOCK-1 | Attendance | Lock grain | Should period lock be scoped to legal entity instead of company? | Company-wide (current) / Legal-entity-scoped | Low | ⚠️ Open |
| PD-LOCK-2 | Attendance | Post-lock correction | Should a controlled post-lock correction/arrears mechanism exist, short of a full reopen? | No mechanism (current) / Build `AttendanceAdjustment`/arrears path | **High** | ⚠️ Open — flows directly into the Leave-side PD-LEAVE-LOCK-2 below |
| PD-WFH-1 | Attendance | WFH auto-detection | Should WFH auto-derive from assignment location? | No (current) | Low | ⚠️ Open |
| PD-OT-1 | Attendance | OT terminal-record revision | Should a terminal (approved/rejected) overtime record ever become revisable/voidable? | No revision path (current) / Add a supervised revision flow | Medium | ⚠️ Open |
| PD-OT-2 | Attendance | OT pre-approval enforcement | `requires_pre_approval` is stored but never enforced — should it be wired up? | Leave dormant (current) / Implement enforcement | Medium | ⚠️ Open (= HD-018 in Hidden Decisions Audit) |
| PD-SCOPE-1 | Attendance | Branch-HR RBAC scope | Should branch-level HR roles get BRANCH-level data scope instead of COMPANY? | COMPANY for HR roles (current) | Low | ⚠️ Open |
| PD-REG-1 | Attendance | WRONG_STATUS/EXCESS_BREAK representability | Should these regularization types be representable without a calculation-engine extension? | Not supported until scoped (current) | Medium | ⚠️ Open |

## New decisions surfaced by this cross-module audit

| Decision ID | Module | Policy Area | Decision Required | Options | Priority | Status | Type |
|---|---|---|---|---|---|---|---|
| PD-XMOD-001 | Cross-module | Leave vs. Overtime | Should approved leave suppress/reduce OT eligibility on the same day, or should the two remain fully independent? | (a) Leave zeroes OT entirely (b) Leave and OT coexist as independent facts (current) (c) Configurable per policy | **Critical** | ⚠️ Open | Client Business Decision |
| PD-XMOD-002 | Cross-module | Roster vs. SHIFT-scoped policy | Should policy resolution's SHIFT scope use the day's actual roster-assigned shift instead of the employee's base assignment shift? | (a) Keep base-assignment-only (current) (b) Align to roster, per original architecture intent | **High** | ⚠️ Open | Product Decision |
| PD-XMOD-003 | Cross-module | Leave submission vs. attendance lock | Should a leave application be blocked at **submission** time if its target date's attendance period is already closed, rather than only failing at approval? | (a) Keep current (fails late, at approval) (b) Block/warn at submission | **High** | ⚠️ Open | Product Decision |
| PD-XMOD-004 | Cross-module | Post-lock leave correction | Should any arrears/exception mechanism exist for leave approved after a period lock, short of a full attendance-period reopen? | (a) None (current — full reopen only) (b) Build a leave-specific arrears path | **High** | ⚠️ Open | Client Business Decision — tightly coupled to PD-LOCK-2 |
| PD-XMOD-005 | Cross-module | Sandwich rule scope | Should the sandwich rule look across multiple separately-submitted applications, or stay scoped to one application's date range (current)? | (a) Keep single-application scope (current) (b) Extend look-back across applications | Medium | ⚠️ Open | Client Business Decision |
| PD-XMOD-006 | Cross-module | Half-day leave vs. early departure | Does half-day leave interact with early-departure classification on the worked portion of the same day? | Undetermined — no rule exists either way | Medium | ⚠️ Open | Implementation Verification |
| PD-ATT-001 | Attendance | Two overlapping PolicyAssignments at the same scope | Should this be structurally prevented (DB constraint), or is a documented tie-break rule sufficient? | (a) Add DB constraint (b) Document first-match rule (c) Leave as-is | **High** | ⚠️ Open | Technical Decision |
| PD-ATT-002 | Attendance | Night OT classification | Should `night_ot_mode=WINDOW/BOTH` actually compare punch clock-time to `night_window_start/end`, instead of always deriving "night" from `shift.is_cross_midnight`? | (a) Implement real window check (b) Remove the unused enum values/fields | **High** | ⚠️ Open (= CD-001, HD-002) | Product Decision |
| PD-ATT-003 | Attendance | `blocked_when_locked` / `AUTO_CLOSE` mislabeled fields | Should these dormant/misleading fields be relabeled or removed? | (a) Relabel for clarity (b) Wire up real behaviour (c) Remove | Medium | ⚠️ Open (= HD-004, HD-005) | Technical Decision |
| PD-LEAVE-001 | Leave | Same-leave-type overlap | Should two overlapping applications of the *same* leave type be blocked, the way cross-type combination rules already block overlap between different types? | (a) No block (current) (b) Block same-type overlap by default | **High** | ⚠️ Open | Client Business Decision |
| PD-LEAVE-002 | Leave | Statutory minimum enforcement scope | Should publish-time enforcement use the strictest configured minimum across all states/establishment types (current), or only the minimum relevant to the policy's actual assigned scope? | (a) Strictest-always (current) (b) Scope-aware check | Medium | ⚠️ Open | Client Business Decision |
| PD-LEAVE-003 | Leave | Advance leave / negative balance | Should advance leave (negative balance) ever be supported, activating the currently-dormant `allow_negative_balance` field? | (a) Never (current) (b) Support under specific conditions | Low | ⚠️ Open | Client Business Decision |
| PD-LEAVE-004 | Leave | Approval delegation | Should a delegation/out-of-office/acting-approver mechanism be built? | (a) Not built (current) (b) Build delegation | Medium | ⚠️ Open | Product Decision |
| PD-LEAVE-005 | Leave | Leave Year Setting effective-dating | Should the Leave Year Setting be versioned/effective-dated like every other policy object, and what happens to an in-progress leave year if it changes mid-year? | Undetermined | Medium | ⚠️ Open | Technical Decision |
| PD-LEAVE-006 | Leave | Leave Combination Rule effective-dating | Should combination rules be effective-dated so past decisions can be explained by "the rule in force at the time"? | Undetermined | Low | ⚠️ Open | Technical Decision |
| PD-LEAVE-007 | Leave | Eligibility-check ordering | Is the current check order in `submit()` (on-behalf → probation → half-day → reason → backdating → monthly-cap → day-breakdown → combination → balance) an intentional business rule, or incidental code structure that could change? | Undetermined | Low | ⚠️ Open | Implementation Verification |
| PD-LEAVE-008 | Leave | Gender/tenure restriction | Neither gender-restricted nor minimum-tenure-restricted leave types exist today — is either required? | (a) Not required (current) (b) Add gender restriction (c) Add tenure restriction | Medium | ⚠️ Open | Client Business Decision |
| PD-LEAVE-009 | Leave | Withdrawal vs. cancellation distinction | The system has only "cancellation," no separate "withdrawal" concept, and no amend/modify-in-place for an existing application — is this sufficient? | (a) Current is sufficient (b) Add distinct withdrawal semantics (c) Add amend/modify | Low | ⚠️ Open | Product Decision |
| PD-DOC-001 | Attendance (docs only) | Documentation currency | Every attendance business-rule document still describes Leave as "a future module, not yet implemented" — should this entire document set be revised now that Leave exists and is the writer of `LeaveDayProjection`? | (a) Leave as-is (b) Revise attendance docs to reflect current Leave integration | **High** (client sign-off risk if left stale) | 🟠 Open | Technical Decision (documentation maintenance) |

## Priority summary

- **Critical:** 1 (PD-XMOD-001 — Leave vs. Overtime interaction)
- **High:** 8 (PD-LOCK-2, PD-XMOD-002, PD-XMOD-003, PD-XMOD-004, PD-ATT-001, PD-ATT-002, PD-LEAVE-001, PD-DOC-001)
- **Medium:** 12
- **Low:** 9
- **Total open decisions:** 30 (11 carried forward from pre-existing Attendance documentation + 19 newly surfaced by this audit)

## Decision-type breakdown

- **Client Business Decision:** PD-XMOD-001, PD-XMOD-004, PD-XMOD-005, PD-LEAVE-001, PD-LEAVE-002, PD-LEAVE-003, PD-LEAVE-008, plus carried-forward PD-CAL-1, PD-CAL-2
- **Product Decision:** PD-XMOD-002, PD-XMOD-003, PD-ATT-002, PD-LEAVE-004, PD-LEAVE-009, plus carried-forward PD-SHIFT-1, PD-WFH-1, PD-REG-1
- **Technical Decision:** PD-ATT-001, PD-ATT-003, PD-LEAVE-005, PD-LEAVE-006, PD-DOC-001, plus carried-forward PD-POL-1, PD-LOCK-1, PD-SCOPE-1
- **Implementation Verification:** PD-XMOD-006, PD-LEAVE-007, plus carried-forward PD-OT-1, PD-OT-2
