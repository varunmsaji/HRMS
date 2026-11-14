# Performance Management: Phase 0 Decision Log

**Date:** 2026-11-14
**Status:** All seven architecture-shaping decisions APPROVED.
**Final, binding form:** [`PERFORMANCE_ARCHITECTURE_GATE.md`](PERFORMANCE_ARCHITECTURE_GATE.md) §2. This log keeps the *reasoning*: what was checked in the code, which options were compared, and what was refined during approval.

Decisions were taken in this order, because each one builds on the ones before:

1. P34
2. P35
3. P19
4. P9
5. P15
6. P21
7. P25

The order runs from access, to workflow ownership, to review policy, to scoring, to sensitive data.

---

## P34: automatic reporting-manager capability

**Question:** should having direct reports grant manager capabilities on its own, without someone assigning the `REPORTING_MANAGER` role?

**What the code showed:**
- Leave resolves the approving manager from the reporting hierarchy alone (`leave/service.py:3215-3219`). It never checks that the manager has a login or a role.
- To approve, the caller needs `LEAVE.APPLICATION_APPROVE` (`leave/router.py:832`) and must be the manager named on the request (`leave/service.py:3392`).
- Only `REPORTING_MANAGER`, `BRANCH_MANAGER`, `HR_ADMIN` and `COMPANY_ADMIN` hold that code. New logins get only `EMPLOYEE` (`account_invite/service.py:127`). Nothing assigns `REPORTING_MANAGER` automatically.
- So a manager without the role gets 403. The request waits until HR reassigns it. The approval screens are also hidden, because web and mobile filter by the `/me` permission list (`identity/service.py:341`).
- Regularization and overtime work the same way.

**Options compared:**

| | A. Manual (status quo) | B. Sync the role automatically | C. Derive when permissions are checked |
|---|---|---|---|
| Correctness | Depends on admins remembering | Can drift between syncs | Always matches the hierarchy (same query as the reportee scope) |
| Schema | None | `user_role.source` column, sync job, backfill | None (maybe an index) |
| Fixes leave/regularization/overtime | No | After sync | Immediately |
| Audit | Role-assignment audit | Sync audit | Assignment history (already audited) |

**Decision: C, approved.**
- Someone is treated as holding the company's `REPORTING_MANAGER` bundle when they have an active login linked to an employee who is the current `reporting_manager_id` on at least one active assignment.
- No narrower duplicate bundle. Manual and derived both feed effective permissions.
- Dotted-line managers get nothing automatic.
- Leave, regularization and overtime are included, as an **accepted change to shipped behaviour**: integration and regression tests, a release note and a security review.

**Accepted consequences:**
- Setting `reporting_manager_id` becomes an access-granting, security-sensitive action.
- Rights end the moment the last report moves. Open items follow their module's rules: leave uses HR reassignment; performance follows P19.

**Registered as separate work (not part of P34):**
- Approval resilience when the named approver has no login. This became R5 / P47 in the gate.
- An HR view of workflow items assigned to someone who can't act. This became R6.

**Implementation notes found while working on P19:**
- Derived roles must feed `RbacService.get_permission_codes` (used by `/me` and leave's `_approver_ineligibility`) as well as `resolve_data_scope`.
- "Current" must mean the assignment covering today (INV-1), not `effective_to IS NULL`.

---

## P35: department-head access

**Question:** does being `Department.head_employee_id` grant broad visibility, approval only, or both?

**What the code showed:**
- `head_employee_id` has exactly one consumer: leave's department-head approval stage (`leave/service.py:3233`). Attendance has no such stage.
- Setting a head only checks that the employee exists in the same company (`organisation/service.py:1579`). An exited employee can stay as head.
- Departments nest up to 5 levels deep and loops are rejected, but no helper returns a department with everything below it.
- `DEPARTMENT` scope deliberately doesn't exist (`core/rbac/types.py`).
- Two existing gaps in leave's department-head stage:
  - (a) a head without `LEAVE.APPLICATION_APPROVE` gets 403;
  - (b) the decision center lists requests for employees in the caller's *scope*, not requests waiting on them (`leave/router.py:754`), so a head-stage request from outside the head's reportee tree doesn't appear.

**Options compared:** A nothing / B approval only / C tiered / D same as a manager over the whole department.

**Decision: C, tiered, approved.**
- **New role and scope:** a new `DEPARTMENT_HEAD` role, derived at check time like P34, plus a new `DEPARTMENT` scope covering headed departments and **all sub-departments**, merged across several headships.
- **Leave:** department-head approval at `DEPARTMENT` scope, fixing both gaps.
- **Performance:**
  - manage department objectives (headed departments only);
  - **read-only** individual goals: title, description, status, progress, target or measurement, weight, due date;
  - cycle monitoring that shows status only;
  - aggregated analytics with a **minimum group of 5**.
- **Never through this relationship:** review narratives, ratings, self- or manager-assessment content, review evidence, PIPs, 360, private notes, compensation, rewards.

**Refinements added at approval:**
- The minimum-group rule applies **after any filtering** (team, demographics, role, location, dates). Combined filters must not let anyone infer hidden results.
- `DEPARTMENT` scope is a core capability, but **every module must opt in explicitly**.
- Inactive or exited heads are rejected for new assignments. Existing ones go to a cleanup report for HR; they are never silently cleared.

---

## P19: manager changes mid-cycle

**Question:** does an in-progress review follow the org chart, or stay with the manager it started with?

**What the code showed:**
- Changing a manager already needs a confirmation. `employee/service.py:2113-2131` and `_pending_manager_change_impact` (`:2214`) count pending leave, regularization and overtime that **stay with the old approver**. The writer must confirm with a token, and the confirmation is audited.
- Nothing moves automatically. HR can reassign only when the current approver can't act (`leave/service.py:3546` `_approver_ineligibility`: inactive, not employed, no login, or lacks the approve code). Because that check reads `get_permission_codes`, P34's derived rights fit it with no deadlock.
- **Found while checking:** a manager change closes the old row at `effective_from - 1` and inserts the new row with no end date (`employee/service.py:2143`). No check was found against future dates, so "current = no end date" may treat a future-dated change as already current. This is bug B3, *suspected*.

**Options compared:**
- A. Fixed at launch; only HR moves it.
- B. Always follow the org chart.
- C. Fixed at launch; reassigned by rule when the manager change is confirmed.

**Decision: C, approved.**
- **Reviewer at launch:** the manager on the cycle's reference date. If there is none, or they can't act, the review goes to the HR fallback queue.
- **Where it's confirmed:** the manager-change confirmation gains a fourth count, open performance reviews.
- **By review state:**
  - not started, self-review, or manager draft → moves to the new manager, and the old draft (with its P9 preliminary snapshot) becomes **previous-manager input**;
  - manager submitted or later → **stays** with the original reviewer.
- **Previous-manager input:** requested if the old manager supervised **≥ 30%** of the period so far (company-configurable; 30% is the system default). Optional, attributed, unchangeable once submitted, **hidden from the employee by default**.
- **Future-dated changes** take effect on their effective date through a daily job.
- **Reviewer can't act:** goes to the new eligible manager, otherwise HR.
- **HR reassignment:** `PERFORMANCE.REVIEW.REASSIGN` with a reason and audit.
- **Other rules:** self-review is never reset; skip-level is recalculated; shared check-in history is visible to the new manager; private notes stay with their author.
- **Schema:** `review_reviewer` history plus `review_action`.

**Refinement added at approval:** the "current assignment" rule was promoted to a cross-module invariant (INV-1) and a shared authorization audit (R3).

---

## P9: can managers see the self-review before writing their own?

**Insight:** the self-review *narrative* helps the manager recall achievements. The self-*ratings* anchor the manager's own numbers. So the two can be revealed separately.

**Options compared:**
- A. Open.
- B. Context first, numbers later.
- C. Blind until the manager submits.
- D. Revealed to both at the same time.

**Decision: B, approved.**
- Self-review drafts are never visible to the manager.
- The narrative is visible once the employee submits.
- Self-ratings are revealed only after a **complete preliminary assessment**: every required scored item plus the overall rating. Saving a draft isn't enough.
- The preliminary snapshot can't change and is never visible to the employee.
- A note is required when the final rating differs by **more than one band**, counted on the **ordered scale**.
- Template modes in v1: `CONTEXT_FIRST` (default) and `OPEN`. C and D are not built.
- Missing self-review: the manager proceeds, and the review is flagged `SELF_REVIEW_NOT_SUBMITTED`. A late self-review is accepted only through an authorised extension.
- Previous-manager input is written **without** seeing the self-review.
- `PRELIMINARY_RECORDED` is a milestone, not a state.
- The reveal is audited.

**Refinement added at approval:** HR sees submitted content subject to permissions. Skip-level visibility is **not** decided here; it waits for P12 and P13.

---

## P15: rating overrides

**Precedents found:**
- Append-only `leave_ledger`, `leave_application_action` and `audit_log` (migration `20261009090000`).
- Finalised-payroll triggers (`20261013090000`).
- Self-approval blocked with no exception (`leave/service.py:3389`).
- Payroll separation of duties: HR prepares, `COMPANY_ADMIN` approves (D9).

**Rating layers:** `COMPUTED` → `MANAGER_FINAL` → `CALIBRATED` → `OVERRIDE`.
- The P9 preliminary rating is reference only.
- The official rating is the most recent approved non-computed layer.

**Options for the manager's departure from the computed rating:**
- X. The computed rating rules.
- Y. The manager decides; the computed rating is advisory.
- Z. The manager decides within limits.

**Decision: Z, approved.**
- **Departures:** ≤ 1 band from the computed rating is allowed with a note. > 1 band needs HR approval before submission. Bands are counted on the ordered scale.
- **What can be overridden:** the overall rating only. A wrong component goes back through return or reopen and a recompute.
- **Codes:** `PERFORMANCE.RATING.OVERRIDE` and `PERFORMANCE.RATING.OVERRIDE_APPROVE`, always fully namespaced.
- **Separation, checked per record:** proposer ≠ approver; neither is the subject; the approver isn't the reviewer-of-record.
- **Reasons:** an internal reason, plus an employee-facing explanation whenever the official rating differs from the manager's final.
- **The employee sees:** the official rating, an "adjusted" indicator and the explanation. Not the original number, internal reason, identities or history.
- **Small companies:** single-approver mode only when exactly one **eligible active** approver exists. It is permanently flagged, audited and visible in analytics. Platform admins never approve.
- **Timing:**
  - after finalisation: only through reopen, which creates a new revision;
  - after the cycle closes: HR proposes and a different `COMPANY_ADMIN` approves.
- **No bulk overrides** in v1.
- **Storage:** an append-only `rating_decision` table.

**Principle established:** outcomes are corrected by adding new attributable decisions, never by rewriting history.

---

## P21: attendance in performance

**What the code showed:**
- `LeaveType.statutory_category` is one of `EARNED`, `SICK`, `CASUAL`, `MATERNITY`, `PATERNITY`, or none (`leave/schemas.py:42`). It exists to check legal minimum entitlements, **not** to mark leave as protected.
- `AttendanceDay` stores surveillance-grade detail: scheduled and actual times, worked minutes, breaks, plus punches, geofence and face attempts. So "information-only" has to be an allowed list, not a banned list.

**Options compared:**
- A. Fully separate.
- B. Separate scoring plus an optional information panel.
- C. A scored input.

**Decision: A in v1, B in Phase 6 (off by default), C never. Approved.**
- **Allowed in the panel:**
  - unplanned absence days (not covered by approved leave or a regularization);
  - late arrivals beyond the shift's grace period.
- **Early departures** are **excluded**; that's a later decision (P45).
- **Never shown:** approved leave, overtime, worked hours, punches, breaks, geofence, face data.
- **Who sees it:** reviewer-of-record and HR, during the manager phase. **The employee sees the same figures** and is told in advance.
- **Snapshot:** a reproducible reference (period, timestamp, policy version, access log). Raw attendance data is not copied.
- **Protected leave:**
  - `MATERNITY` and `PATERNITY` are always protected and can't be turned off;
  - `SICK` is protected by default and changeable only within legal and policy rules after legal review (P46);
  - companies can add other types.
- **Effects of protected leave:** counts toward eligibility, never reduces a rating, never appears as absence or lateness. Goals are adjusted only through an explicit HR action.
- **Attendance-related goals:** only from HR-approved KPI library entries flagged `ATTENDANCE_RELATED`, measured manually. No free-text attendance metrics. No attendance-to-KPI feed, ever.

**Principle established:** attendance is an operational record, performance is an assessment, and no hidden automatic path may connect them.

---

## P25: 360 anonymity

**What the code showed:**
- The `EMPLOYEE` role holds `EMPLOYEE.VIEW` at `SELF` scope and doesn't have `EMPLOYEE.VIEW_ALL` (`organisation/service.py:792-850`). Employees can't browse colleagues, so peer nomination needs a new, minimal picker.
- Anonymity has to be built into the schema. Matching a request's `submitted_at` to a response's `created_at` would reveal the author.

**Decision: approved.**
- **Anonymity per reviewer group:**
  - Manager: **Identified**.
  - Peers: **Confidential** (HR can link a response to its author).
  - Direct reports: **Anonymous with emergency reveal**.
  - External: not in v1.
  - Companies can only make a group stricter.
- **Minimum responses:**
  - **3** submitted responses per visible group, applied after filtering;
  - an "Others" group must itself reach 3;
  - direct-report results are never folded into another group;
  - totals come only from groups that are shown;
  - the subject sees "enough" or "not enough", never counts.
- **Comments:**
  - shown word for word, shuffled, unlinked from the respondent's ratings, without timestamps;
  - HR moderation is **required for direct reports** and optional for peers;
  - HR can release or hide (with a reason, audited, original kept), and never edits.
- **Emergency reveal:**
  - only on an abuse report;
  - HR proposes and a different `COMPANY_ADMIN` approves;
  - the respondent is notified;
  - **no single-approver mode**: if separation can't be met, identity can't be revealed.
- **Effect on rating:**
  - weight defaults to 0% with a 20% cap, ratings only;
  - groups below the minimum are excluded structurally;
  - **the weight is fixed before feedback opens.**
- **Reviewer-of-record access:** 360 results are revealed together with the self-ratings, after the preliminary assessment. Previous-manager input gets no 360 access.
- **Nomination:**
  - through a purpose-built colleague picker (name, designation, department; active, same company, eligible only), gated by `PERFORMANCE.FEEDBACK.NOMINATE`;
  - the manager approves and may add reviewers hidden from the subject;
  - declines are visible to HR only.
- **Schema:**
  - anonymous `feedback_response` rows have no responder ID and a date-only timestamp;
  - the author link sits in `feedback_respondent_link`, which the app's database role **can't read**, only the reveal function.
- **New code:** `PERFORMANCE.FEEDBACK.IDENTITY_REVEAL`.

---

## What happens next

1. **Sign off the gate document** (§15 of the gate).
2. **Sign off the PROPOSED register items** due by Phase 1:
   - P1–P3, P5, P7 (goals and scale);
   - P36 (branch manager access);
   - P40 (turning the module on);
   - P41 (team entity);
   - P43 (mobile scope).
3. **Build the Phase 1 prerequisites** as separate PRs:
   - R1: derived manager rights;
   - R2: department-head role and scope (has a migration that needs your manual merge);
   - R3: confirm B3 and apply INV-1;
   - R4: department-head validation and cleanup report;
   - R8: feature-flag wiring.
4. **Then Phase 1:** goals, KPIs, configuration, and the access layer.
