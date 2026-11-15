# Performance Management: HRMS Audit and Implementation Blueprint

**Date:** 2026-11-14
**Status:** Original Phase 0 audit and blueprint. Kept as the full product and architecture reference.
**Precedence:** where this document disagrees with an approved decision, **[`PERFORMANCE_ARCHITECTURE_GATE.md`](PERFORMANCE_ARCHITECTURE_GATE.md) wins**. Points later changed by a decision are marked **⟶ Superseded by Pxx**. The reasoning behind each decision is in [`01_PHASE0_DECISION_LOG.md`](01_PHASE0_DECISION_LOG.md).

File references are repository paths, with line numbers as of commit `2bc5e25`.

---

## 1. Executive Summary

When this audit was written, **no performance management code existed**: no tables, routes, screens or permissions. It existed only as requirements:
- `docs/product/18_SRS_Phase2_Phase3_Modules.md` §1 (FR-PRF-001 to FR-PRF-011);
- `PERFORMANCE.*` codes in `docs/product/19_RBAC_and_Permission_Matrix.md:103`.

The platform is strong enough to reuse most of the hard infrastructure:
- tenant isolation through row-level security, with the company taken from the signed token;
- permissions with data scopes (`SELF`, `REPORTEES`, `REPORTEE_TREE`, `BRANCH`, `COMPANY`);
- an effective-dated reporting hierarchy;
- an append-only audit log and database triggers that lock finalised records;
- in-app notifications and an email outbox;
- Celery beat scheduling, MinIO file storage, field encryption, and `version`/`If-Match` concurrency checks.

**The gaps:**
- no generic approval engine; each module implements its own staged approvals;
- access is role-scoped only, with no per-record relationship access;
- no team entity and no department scope, and the dotted-line manager is unused;
- no push notifications or escalation, and no audit viewer for companies;
- payroll has no bonus or variable-pay input.

**Recommendation:** one new backend module, `performance`, delivered in phases 0–6.
- Goals, check-ins and a basic review cycle first.
- Attendance and leave out of scoring.
- Payroll decoupled: an outcome only ever produces a recommendation that a person must approve.

---

## 2. Current HRMS Integration Audit

### 2.1 Employee and organisation structure

| Area | What exists (verified) | Fit for performance |
|---|---|---|
| Employee identity | `Employee` with `status` (PRE_JOINING, PROBATION, ACTIVE, ON_NOTICE, SUSPENDED, ON_LONG_LEAVE, EXITED, ABSCONDING, RETIRED, DECEASED): `employee/models.py`, `employee/schemas.py:52` | Eligibility rules |
| Employment spell | `Employment` with `joining_date`, `probation_end_date`, `last_working_day`; rehires keep the same employee ID | Joiners and leavers mid-cycle; minimum-service rules |
| Placement | `EmployeeAssignment`: branch, department, designation, grade, `reporting_manager_id`, `dotted_line_manager_id`, with `effective_from`/`effective_to` | "Who was the manager on date X" |
| Departments | `Department` with `parent_id` (up to 5 levels) and `head_employee_id` | Department goals, department-head view |
| Designations and grades | `Designation.grade_id`, `next_designation_id`; `Grade.level`, `min_ctc`/`max_ctc` | Competency frameworks, career paths |
| Teams | **No team entity** | v1: "team" = a manager's direct reports (P41) |
| Dotted-line manager | Stored and validated (`employee/service.py:1892`) but **no workflow uses it** | Matrix reviewer source later |
| Hierarchy safety | The reportee tree is capped by depth; loops are cut off, not rejected (`employee/repository.py:652`) | Check for loops at cycle launch (R9) |

### 2.2 Roles and permissions

- **How permissions work:** `role` → `role_permission(data_scope)` → `user_role` → `user_company`.
  - `require_permission(code)` returns the caller's scope levels (`core/rbac/dependencies.py`).
  - `EmployeeService.resolve_visible_employee_ids` (`employee/service.py:176`) turns those levels into concrete employees. This is the reuse point for other modules.
- **Fixed roles:** five system roles are created when a company registers: `COMPANY_ADMIN`, `HR_ADMIN`, `REPORTING_MANAGER`, `BRANCH_MANAGER`, `EMPLOYEE` (`organisation/service.py:246-272`, grants at `:636-850`).
  - `PATCH /users/{id}/roles` replaces a user's roles from that fixed list only (`account_invite/service.py:535`, `ASSIGNABLE_ROLE_CODES` at `:59`).
  - **No custom roles.**
- **Being someone's manager didn't grant the manager role.** ⟶ **Superseded by P34** (derived manager rights).
- **Approvals check identity:** manager and department-head stages check identity against the request's recorded approver; the HR stage requires `COMPANY` scope; `BRANCH_MANAGER` alone can't approve.
- **New permissions need a backfill migration** for existing companies (precedents: `20260920090000_default_roles_backfill`, `20261020090000`). Migrations need a manual merge.

### 2.3 Other modules

| Module | Reusable assets | Coupling risk | Policy question |
|---|---|---|---|
| Attendance | Per-period totals (present, absent, leave, loss-of-pay, paid); daily records; late-arrival bands; overtime records | Attendance becoming a score | ⟶ **Decided by P21** |
| Leave | Applications, ledger; `statutory_category` (EARNED, SICK, CASUAL, MATERNITY, PATERNITY) | Penalising protected leave | ⟶ **P21** protected leave |
| Shifts and rosters | Shift assignment, swaps | Analytics misuse | KPI context only |
| Overtime | Overtime records with approvals | Rewarding overwork | Never in scoring (P21) |
| Approvals | Staged chains (`leave/approval_chain.py`): approver fixed at submission, action history, HR fallback, reassignment | Low if the pattern is copied | Goal approval, overrides, PIP approval |
| Notifications | `notification` table, type registry, de-duplication keys, approval helpers; metadata **forbids "score"** keys | Category list is fixed in code | Never put ratings in notifications |
| Email | Durable at-least-once outbox (`onboarding/email_outbox.py`) | Lives inside onboarding | ⟶ R7: move to core/shared |
| Payroll | Salary components (EARNING, DEDUCTION, EMPLOYER_CONTRIBUTION); pay runs; adjustments covering paid days only | **No bonus or variable-pay input** | Phase 6 only |
| Compensation | `EmployeeCompensation.revision_type` (JOINING, ANNUAL, PROMOTION, CORRECTION, MARKET), gated by `EMPLOYEE.UPDATE_COMPENSATION` | Silent pay changes | Recommendation-only flow |
| Documents and storage | `core/storage.py` (MinIO, presigned links); `EmployeeDocument` is separate | Mixing evidence with HR documents | Separate evidence table |
| Audit | `audit_log` with before/after, append-only (`20261009090000`); business events after commit | **No tenant audit viewer** | Who reads the performance audit? |
| Immutability | Finalised-payroll triggers (`20261013090000`) | — | Copy this pattern for finalised reviews |
| Field encryption | `PiiCryptoService` | Searching encrypted text | PIP narrative and private notes |
| Feature flags | `company_feature_flag`, `plan_feature`; only the seat limit uses them | Needs wiring | ⟶ R8 |
| Scheduler | Celery beat daily sweeps | — | Reminders |
| Concurrency | `version` + `If-Match`, idempotency keys | — | — |
| Web | Next.js; navigation filtered by `/me` permissions (`components/layout/nav-items.ts`) | Next.js version has breaking changes (`apps/web/AGENTS.md`) | — |
| Mobile | Flutter feature folders; **no push**; notifications fetched only while the app is open | — | Mobile scope (P43) |

---

## 3. Existing Capabilities That Can Be Reused

1. Row-level security with `company_id` and tenant context.
2. `require_permission` plus `resolve_visible_employee_ids`.
3. The effective-dated hierarchy: as-of queries, reportee and reportee-tree resolution, department heads.
4. Employment dates for eligibility, pro-rating and exits.
5. The approval pattern: approver fixed at submission, action table, pure stage functions, HR fallback, reassignment.
6. Notifications: type registry, de-duplication, forbidden-metadata guard, approval helpers.
7. The email outbox, after moving it (R7).
8. `AuditService.record`, the append-only `audit_log`, and the finalisation-trigger pattern.
9. Celery beat.
10. MinIO storage and the upload validation in `core/uploads.py`.
11. `PiiCryptoService`.
12. `version`/`If-Match` checks and idempotency keys.
13. The versioned-policy pattern (attendance, overtime and leave policy versions), reused for scales, templates and scoring rules.

## 4. Missing Capabilities

| Missing | Build or modify |
|---|---|
| All performance entities | **New** |
| Per-record relationship access (reviewer, nominee, PIP participant) | **New** (`access.py`) |
| Department scope | **Modify** core RBAC ⟶ **P35** / R2 |
| Team entity | Decision ⟶ P41 (none in v1) |
| Using the dotted-line manager in workflows | **New**, Phase 4 |
| `PERFORMANCE` notification category and types | **Modify** `notification/types.py` |
| Email outbox reachable from other modules | **Modify** ⟶ R7 |
| Push notifications, escalation | **New**, deferred |
| Audit viewer for companies | **New**, Phase 6 |
| Turning the module on per company or plan | **Modify** ⟶ R8 |
| Custom roles | Deferred; reuse `HR_ADMIN` |
| Payroll one-time earnings | **New**, Phase 6+ |
| Hierarchy loop check | **New** ⟶ R9 |

---

## 5. Recommended Product Scope

**First release (Phases 1–3):**
- goals with cascading, KPIs, configurable scales;
- cycles with self-review, manager review, HR finalisation and acknowledgement;
- check-ins and recognition;
- in-app notifications and email digests.

**Later:** 360, competencies, calibration, PIP, development plans, analytics, reward recommendations.

**Never by default:** automatic salary changes, forced ranking, attendance scoring (permanently excluded, P21), AI-generated ratings.

**One engine supports all three methods from the requirements:**
- **KRA/KPI:** weighted goals with KPIs.
- **OKR:** objective with key results; scored on progress, optionally excluded from the rating (P6).
- **Competency-based:** ratings against a framework.

The scoring rule's components and weights select between them.

---

## 6. Complete Performance Architecture

The module layout and the boundaries with other modules are in **gate §6**.

**Configuration:**
- versioned and **frozen at cycle launch**;
- editing a template creates a new version and never changes a running cycle.

**Reviewer:**
- fixed at cycle launch from the manager on the reference date;
- later changes follow ⟶ **P19**.

**Scoring engine:** pure functions with no I/O (like `leave/approval_chain.py`), so it's testable and reproducible.

Performance writes to no other module's tables. Other modules never write to performance tables.

---

## 7. User Roles and Permissions Matrix

The final catalogue and default grants are in **gate §8**. They include:
- the derived `REPORTING_MANAGER` (P34) and `DEPARTMENT_HEAD` (P35) roles;
- the three-layer access check;
- field-level visibility for the employee being reviewed.

---

## 8. Goals and KPI System

**A goal has:**
- `title`, `description`, `owner_type` (EMPLOYEE, TEAM_MANAGER, DEPARTMENT, COMPANY) and `owner_id`;
- `parent_goal_id` (cascade, max 5 levels), optional `cycle_id`;
- `start_date`, `due_date`, `priority`, `weight` (decimal);
- `measurement_type`: MILESTONE, BINARY, QUANTITATIVE, PERCENTAGE or QUALITATIVE;
- `progress_pct` (computed for measured goals, otherwise entered by hand);
- `status`, plus `health` (ON_TRACK, AT_RISK, OFF_TRACK), which is separate from status;
- `visibility`: PRIVATE_TO_CHAIN, TEAM or COMPANY;
- `source`: SELF, ASSIGNED, CASCADED or LIBRARY.

**Where goals come from:**
- **Employee-created:** DRAFT → PENDING_APPROVAL (if required, P2) → ACTIVE.
- **Manager-assigned:** ACTIVE immediately, employee notified (acceptance rule: P3).
- **Shared:** one goal, several contributors (`goal_contributor`), each with a weight.
- **Cascaded:** a child links to its parent. Progress rolls up as a weighted average only if the parent is configured to.
- **Goal library:** per designation (FR-PRF-002).

**Weights:** scored goal weights must total 100 before self-review starts. This is checked at the phase change. Limits on count and per-goal weight come from the template (P5).

**KPIs are separate from goals:**
- A `kpi_definition` has `code`, `name`, `unit`, `direction` (higher, lower, or a target band), `aggregation` (sum, average, last, max), `data_source` (MANUAL, IMPORT, later connectors), `applicable_to`, and the `ATTENDANCE_RELATED` flag (P21).
- A `kpi_target` has a period, target, threshold and stretch values, and a scoring curve (linear capped, step bands, or a band around the target).
- `kpi_measurement` is append-only and records the actual value, period, who entered it, evidence and source. A correction is a new row that supersedes the old one.
- **Qualitative KPIs** are rated on the scale, not measured.
- **Automatic updates:** v1 is manual plus CSV import (following the employee-import pattern). Connectors come later. Every imported value records its source and import batch. **No attendance feed, ever (P21).**
- **Locking:** once manager review starts, scored goals and targets are locked. Changes go through `goal_change_request`, approved by the manager (and HR if policy says so) and audited (P4).

---

## 9. Review Cycle Workflow

| Stage | Performed by | Edits | Submits | Reopens | Overrides | Mandatory |
|---|---|---|---|---|---|---|
| Cycle created | HR | HR | — | — | — | yes |
| Participants | HR (rules plus manual) | HR until launch, then add or exclude with a reason | — | — | HR | yes |
| Goal setting | employee and manager | until the phase ends | employee submits, manager approves | manager or HR | HR | configurable |
| Goals and KPIs gathered | system snapshot | — | — | — | — | yes |
| Self-assessment | employee | until submitted or deadline | employee | manager or HR return | — | configurable (default on) |
| Manager assessment | reviewer-of-record | until submitted | reviewer | HR | HR reassigns (P19) | yes |
| Skip-level | manager's manager | read, comment, endorse, return | skip-level | HR | — | optional (P12, default off) |
| Peer / 360 | nominated reviewers | each response until the deadline | responder | HR invalidates | — | optional (P25) |
| Calibration | HR plus managers | adjustments with a reason | facilitator | HR | HR approves | optional (P13) |
| Finalisation | HR | — | HR (single or bulk) | `REVIEW.REOPEN` | ⟶ **P15** | yes |
| Release | HR | — | — | — | — | yes |
| Acknowledgement | employee | comment only | employee (may disagree) | — | auto after N days (P22) | configurable |
| Development plan | manager and employee | both | — | — | — | optional |

- **Visibility of the self-review to the manager:** ⟶ **P9** (context first, numbers later).
- **Weekly and monthly check-ins are not cycles** (see §12). Cycle types: ANNUAL, HALF_YEARLY, QUARTERLY, PROBATION, PROJECT.
- **Eligibility:**
  - Default: ACTIVE or PROBATION (ON_NOTICE per P18), joined before the cutoff (P17), not EXITED.
  - Leavers become `WITHDRAWN`, with partial data kept read-only.
  - Long leave follows P20 and P21: protected leave counts toward eligibility.
- **Probation reviews:** a `PROBATION` cycle started per employee from `probation_end_date`. The outcome is a **recommendation** into `EMPLOYEE.CONFIRM`, never automatic (P42).

---

## 10. Performance Scoring Strategy

**Versioned rule:**

```
Final = Σ (component_weight × normalised_component_score)
components: GOALS_KPIS | COMPETENCIES | MANAGER_OVERALL | SELF (default 0) | FEEDBACK (default 0, cap 20%, P25)
```

There is **no attendance component type (P21).**

- **Scale-independent:** every component is normalised to 0–1, then mapped onto the cycle's scale (3, 4, 5 or 10 points, labels and descriptions, optional decimals; FR-PRF-004). Bands are compared **by order** (P9, P15).
- **Rules can differ by role:** assigned by designation, grade or department; one version is frozen per participant.
- **Rounding:** decimal maths; only the final displayed value is rounded (configurable mode, half-up by default); unrounded values are stored.
- **Missing data, per component:**
  - `REDISTRIBUTE` (default): spread the weight across components that have data;
  - `TREAT_AS_ZERO`: never the default;
  - `BLOCK_FINALISATION`.

  The behaviour used is recorded in the explanation.
- **Self-rating weight 0 by default** (P8). A self-rating is shown as context only.
- **Overrides and manager departures:** ⟶ **P15** (layered `rating_decision` history, model Z, separation of duties).
- **Explanations:** every `performance_score` stores the inputs, rule version, engine version, intermediate values, missing-data handling and output. The UI's "How was this calculated?" view is built from that record. Re-running the same engine version on the same inputs must give a byte-identical result, and a test checks it.
- **Recompute vs freeze:** recomputed while in progress, frozen at finalisation.

---

## 11. 360 Feedback Strategy

⟶ **Superseded in detail by P25** (gate §2). The blueprint's original default was "confidential for all groups, minimum 3, feedback weight 0". P25 replaced it with modes per reviewer group, the emergency reveal, comment moderation, protection against timing leaks, and anonymity built into the schema.

**Risks still relevant:**

| Risk | Mitigation |
|---|---|
| Retaliation | Anonymity by group; the manager never sees nominees they didn't add; audited access |
| Re-identification in small teams | Minimum 3, "Others" rule, no counts or timestamps |
| Abuse in free text | Report flag; HR moderation; hide with a reason; never delete |
| Collusion or friends-only nominations | Manager approval; may add reviewers |
| Bias | Weight 0 by default; structured questions; calibration |

---

## 12. Continuous Performance and Check-Ins

**A `check_in` has:**
- employee, manager, scheduled time, cadence template (weekly, biweekly, monthly; question set);
- `employee_update` (wins, blockers, goal progress snapshot) and `manager_notes_shared`;
- `manager_notes_private`, encrypted and **author-only** (HR access only in formal disputes, P28);
- `action_items[]` with owner, due date and status;
- a status: SCHEDULED, IN_PROGRESS, COMPLETED or MISSED.

**Other rules:**
- `goal_progress_update` is append-only, with a comment and an optional attachment. It appears in the review as dated evidence (FR-PRF-009).
- Private notes move with their author, not the role. A new manager doesn't inherit them (P19). Retention follows P38.
- Check-ins **never create a score**.

---

## 13. PIP and Development Plans

### PIP

PIPs are deliberately **not** task tickets.

**Entities:**
- `pip`: employee, manager, HR partner, reason category, concern summary, start and end dates, status;
- `pip_objective`: expectation, measure, support provided;
- `pip_checkpoint`: date, notes, progress, employee comment;
- `pip_outcome`: SUCCESSFUL, EXTENDED or UNSUCCESSFUL_FURTHER_ACTION, with HR approval.

**Access:**
- Only the employee, the current manager, the HR partner, and `PIP.APPROVE` holders in scope.
- **Never** skip-level managers or department heads (P35) through scope.
- Notification wording is neutral, e.g. "A document needs your review".

**Process rules:**
- HR approval is required before ACTIVE.
- The employee acknowledges receipt, not agreement.
- Evidence goes under a restricted storage prefix.
- Narrative text is encrypted.
- **Never created automatically** from a rating; a rating can only suggest one (P33).
- If the employee leaves during a PIP, it closes as WITHDRAWN.

### Development

- **Entities:** `development_plan` (optional link to a review), `development_goal` (skill, current vs target level, actions, due date), `development_action` (training, mentoring, stretch assignment; owner; status), `career_aspiration` (employee-owned, visibility the employee controls).
- **Skill gaps:** competency ratings below the level expected for the role become suggestions, which the manager and employee choose to adopt.
- **No LMS exists**, so training is free text or a link in v1.

---

## 14. Attendance, Leave and Overtime Integration Policy

⟶ **Decided by P21** (gate §2).
- v1 is fully separate.
- An optional Phase 6 panel is off by default and limited to an allowed list (unplanned absences and late arrivals beyond grace).
- Attendance is never a scoring input.
- Maternity and paternity are always protected; sick leave is protected by default.
- Attendance-related goals only come from HR-approved KPI library entries, measured manually.

---

## 15. Future Payroll and Reward Integration

```
Final rating (released)
  → Outcome rule table (rating band → suggested increment %, bonus multiplier, promotion eligibility)
  → reward_recommendation  (DRAFT → PROPOSED → APPROVED/REJECTED → APPLIED/VOIDED)
       ├─ increment → a person records the EmployeeCompensation revision (revision_type=ANNUAL)
       │              through the existing route (EMPLOYEE.UPDATE_COMPENSATION)
       ├─ promotion → proposal for EmployeeAssignment change_type=PROMOTION (EMPLOYEE.PROMOTE)
       └─ bonus     → needs a NEW payroll "one-time earning" input (does not exist today)
```

`EmployeeCompensation` has no draft status today. Phase 6 must decide between a proposal entity in performance and pending revisions in the employee module (gate §6.2).

**Guardrails:**
- Every application needs approval by **someone other than the proposer**, with a budget check.
- Every recommendation references the score explanation it was based on.
- A reopen or override invalidates pending recommendations.
- Payroll **reads** approved decisions; performance never calls payroll.
- Grade salary bands (`min_ctc`/`max_ctc`) produce warnings, never silent blocks.
- Increment letters (FR-PRF-011) come from the approved recommendation, not the rating.

---

## 16. Data Architecture

The final entity list, relationship diagram, append-only and finalisation-lock markers are in **gate §7**.

**Indexes to plan for:**
- `(company_id, cycle_id, status)`;
- `(company_id, employee_id)`;
- `(company_id, reviewer_employee_id, status)`.

---

## 17. State Machines

The final matrix is in **gate §9**. It covers cycle, review, goal, rating decision, feedback request, reveal, PIP and reward recommendation.

---

## 18. Audit and Security Requirements

- **Audit every write:** `AuditService.record` with before/after, plus per-entity append-only action tables.
- **Audit sensitive reads:** other people's reviews, PIPs, raw 360 responses, the operational-context panel, exports, reveals (gate §8.5).
- **Locked after finalisation:** assessments, item ratings, scores, calibration entries, rating decisions, submitted feedback, acknowledgements, PIP outcomes. Enforced by the application **and** database triggers (INV-5).
- **Scope boundaries:** department scope per P35; relationship checks per gate §8.1.
- **Notifications:** no ratings, scores, PIP wording, feedback text or respondent names (INV-4).
- **Encryption:** private notes and PIP narrative use `PiiCryptoService`.
- **Retention (P38):** reviews 7 years after exit; raw 360 text 2 years; private notes 1 year after the author changes role. Scheduled like the existing face-data retention job.
- **Exports:** `PERFORMANCE.EXPORT` only, watermarked, audited, never including respondent identities.
- **Required tests:** cross-tenant and cross-employee access tests for every endpoint.

---

## 19. UI/UX and User Journey Recommendations

**Employee:**
```
My Performance (home card) ─→ My Goals (list/tree, progress, update with evidence)
  ─→ Active Review (self-assessment wizard: goals → competencies → achievements → challenges → submit;
     the form states what the manager sees and when — P9)
  ─→ Waiting (status timeline: Self ✓ → Manager ⏳ → HR → Released)
  ─→ Outcome (official rating + "adjusted" indicator/explanation if any — P15 — + "How was this calculated?"
     + manager comments) → Acknowledge / add comment
  ─→ Development Plan
```

**Manager:**
```
Team Performance (reviews waiting on me, overdue, goal health — names, never rankings)
  → Employee → Goals & evidence timeline (check-ins, progress, recognition)
  → Evaluate: narrative visible → record preliminary ratings → self-ratings + 360 revealed (P9, P25)
  → Final ratings (note if >1 band from preliminary; departure >1 band from computed needs HR — P15)
  → Strengths / improvements / development recommendations → Submit
```

**HR:**
```
Cycles → New cycle wizard (type, dates, phases, eligibility preview, template/rule versions, 360 weight fixed)
  → Participants (include/exclude with reason) → Launch
  → Monitor (completion by department/manager, nudges, reviewer-cannot-act queue)
  → Calibration board (distribution, before/after) → Finalise (bulk) → Release (scheduled) → Close
```

**Department head (P35):**
```
Department objectives → individual goal alignment (read-only) → cycle status → aggregated analytics (min group 5)
```

**Notes:**
- Web is primary for configuration and calibration.
- Mobile covers goals, check-ins, self-review and acknowledgement (P43).
- Navigation is gated by `/me` permissions and feature flags.
- The status timeline is the core UI pattern.
- Never default-sort a team by score.
- Show the score explanation inline.

---

## 20. Policy Decision Register

The current register (approved, set by an approved decision, proposed with the phase needed by) is in **gate §14**.

---

## 21. Phased Implementation Roadmap

Entry and exit criteria are in **gate §13**. Prerequisite remediation work is in **gate §5**.

| Phase | Scope | Main risks |
|---|---|---|
| 0. Audit and decisions | Gate approval; register sign-off | Decisions leaking into code |
| 1. Foundation | Module skeleton, RLS, permissions plus backfill, scales, templates, scoring rules, goals with cascading, KPIs (manual plus CSV), access layer, notification category, web goal pages, mobile "My goals" | Access model getting scope wrong |
| 2. Review cycles | Cycles, eligibility, reviewer-of-record (P19), self and manager assessment (P9), scoring with explanations, rating decisions (P15), finalise, release, acknowledge, triggers, reminders | State-machine edge cases |
| 3. Continuous | Check-ins, encrypted private notes, action items, recognition, evidence timeline, attachments | Private-note leaks |
| 4. Advanced | 360 (P25), competencies, skip-level (P12), calibration (P13), dotted-line reviewer | Re-identification; calibration complexity |
| 5. Development and PIP | Development plans, skill gaps, PIP with HR approval, restricted evidence, retention jobs | Legal sensitivity |
| 6. Analytics and integrations | Dashboards (min groups), operational-context panel (P21), reward recommendations, payroll one-time earnings, company audit viewer | Misleading charts; touching pay |

Every phase that adds tables has a migration PR that **you must merge manually** (AGENTS.md).

---

## 22. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Managers without the role can't review | High | High | ⟶ Resolved by **P34** (derived rights) |
| `REPORTEE_TREE` over-exposing reviews to skip-levels | High | High | Three-layer access; skip-level off by default (P12) |
| Loops in the reporting hierarchy | Low | Medium | R9 check at launch |
| Manager or department change mid-cycle | High | Medium | ⟶ **P19** |
| Future-dated assignments counted as current (B3) | Medium | High | ⟶ INV-1 / R3 |
| Scoring not reproducible | Medium | High | Pure engine, versioned rules, stored inputs |
| Attendance becoming a performance proxy | Medium | High | ⟶ **P21** |
| 360 re-identification or retaliation | Medium | High | ⟶ **P25** |
| PIP data leak | Low | Very high | Restricted access, encryption, neutral notifications, read audit |
| Silent pay changes | Low | Very high | Recommendation-only flow, separate approver |
| Forced ranking harm | Medium | High | Off by default (P14) |
| Email outbox coupled to onboarding | Certain | Low | R7 |
| Fixed roles too rigid for large customers | Medium | Medium | Plan custom roles separately |
| Notification noise | Medium | Low | Digests, de-duplication |
| Next.js version differences | Medium | Low | Follow `apps/web/AGENTS.md` |
| Migration PRs waiting on manual merge | Certain | Low | One migration PR per phase |

---

## 23. Final Recommendation

Build a dedicated `performance` module on the existing tenancy, permission, audit, notification and scheduling infrastructure, following its patterns:
- versioned configuration frozen at cycle launch;
- reviewers fixed at cycle launch;
- append-only action history;
- database triggers that lock finalised records.

Don't build a generic approval engine yet.

**Settle access first.** That is now done (P34, P35). Then the Phase 1 prerequisites (R1, R2, R3, R4, R8). Then Phase 1.

**Keep v1 conservative:**
- attendance separate;
- self-rating weight 0;
- calibration and forced distribution off;
- 360 protected by group;
- no payroll link.

Grow through company settings, not code changes.
