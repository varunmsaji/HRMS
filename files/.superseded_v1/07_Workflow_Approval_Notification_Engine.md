# Document 07 — Workflow, Approval & Notification Engine Specification

This engine is the backbone the client's blueprint calls the "Core Automation Flow":
`Employee Action → Workflow Engine → Business Rules → Approval Engine → Notification Engine →
Database Update → Dashboard Refresh`

Build it **once, generically**. Every module that needs approvals plugs into it. The alternative —
per-module approval logic — produces eleven inconsistent implementations and eleven sets of bugs.

---

## 1. Concepts

| Concept | Meaning |
|---|---|
| **Workflow Definition** | A named, versioned graph attached to an entity type (e.g. `LEAVE_APPLICATION`) |
| **Workflow Version** | An immutable published snapshot of the graph. In-flight requests stay on their version. |
| **Node** | A step in the graph |
| **Approval Request** | A running instance bound to one business entity |
| **Approval Step** | One node execution assigned to one or more approvers |
| **Context** | A snapshot of the entity attributes taken at submission, used for all condition evaluation |

**Why context is snapshotted:** if a leave request is routed based on `days > 5`, and the employee
later edits the request, the routing must not silently change under the approver's feet. Editing a
submitted request either restarts the workflow or is forbidden — configurable, defaulting to restart.

---

## 2. Node Types

| Node | Purpose | Configuration |
|---|---|---|
| `START` | Entry point | — |
| `APPROVAL` | Requires a human decision | approver rule, mode (ALL/ANY/QUORUM n), SLA hours, reminder schedule, escalation target, allow-delegate, reject-behaviour (terminate / return to requester) |
| `CONDITION` | Branch on context | expression, true-edge, false-edge (or n-way switch) |
| `PARALLEL` | Fork into concurrent branches | join policy (ALL / ANY / n-of-m) |
| `NOTIFICATION` | Send a message, no wait | event code, recipients |
| `SYSTEM_ACTION` | Perform an internal operation | action code + parameters |
| `WEBHOOK` | Call an external endpoint | url, retry policy, timeout, continue-on-failure |
| `DELAY` | Wait until a time or duration | duration or date expression |
| `END` | Terminal | outcome (APPROVED / REJECTED / CANCELLED) |

### 2.1 Approver Resolution Rules
| Rule | Resolves to |
|---|---|
| `REPORTING_MANAGER_L1/L2/L3` | Walk up the reporting tree n levels |
| `DEPARTMENT_HEAD` | `department.head_employee_id` of the requester's department |
| `BRANCH_HR` | Users with role HR_MANAGER scoped to the requester's branch |
| `SPECIFIC_USER` | A named employee |
| `ROLE` | Any/all holders of a role within a scope |
| `AMOUNT_SLAB` | Approver determined by a value in the context (expense/loan amount) |
| `REQUESTER_CHOICE` | Requester picks from an eligible list at submission |
| `PREVIOUS_APPROVER_MANAGER` | Manager of whoever approved the previous step |

**Resolution failure handling** (this is where real systems break):
- If no approver resolves (manager not set, department head vacant), route to the configured
  **fallback approver** (default: Branch HR), log a `WORKFLOW_APPROVER_UNRESOLVED` warning, and
  notify the HR admin. **Never** silently auto-approve, and never leave the request in limbo.
- If the resolved approver **is** the requester, skip that level (BR-02) and record the skip reason.
- If the approver is inactive/exited, route to their replacement or manager and alert HR.
- If the approver is on approved leave, route to their delegate (BR-03).

---

## 3. Default Workflow Templates (seeded per industry)

### 3.1 Leave Application
```
START
 └─▶ CONDITION: total_days <= 2 ?
       ├─true──▶ APPROVAL [L1: Reporting Manager, SLA 24h] ──▶ SYSTEM_ACTION[post_leave_ledger]
       │                                                    ──▶ SYSTEM_ACTION[recompute_attendance]
       │                                                    ──▶ NOTIFICATION[leave.approved] ──▶ END(APPROVED)
       └─false─▶ APPROVAL [L1: Reporting Manager, SLA 24h]
                  └─▶ CONDITION: total_days > 10 ?
                        ├─true──▶ APPROVAL [L2: Department Head, SLA 48h]
                        │           └─▶ APPROVAL [L3: HR Manager, SLA 48h] ──▶ (post + notify) ──▶ END
                        └─false─▶ APPROVAL [L2: HR Manager, SLA 48h] ──▶ (post + notify) ──▶ END
Any REJECT ──▶ NOTIFICATION[leave.rejected] ──▶ END(REJECTED)
```

### 3.2 Attendance Regularisation
`START → APPROVAL[Reporting Manager, SLA 48h] → SYSTEM_ACTION[recompute_attendance_day] → END`
With a rule: more than 3 regularisations in a calendar month adds an HR approval step.

### 3.3 Manpower Requisition
`START → APPROVAL[Department Head] → CONDITION[is_new_position] → (true) APPROVAL[Finance: budget]
→ APPROVAL[HR Manager] → SYSTEM_ACTION[create_job_opening_draft] → END`

### 3.4 Offer Approval
`START → APPROVAL[Hiring Manager] → CONDITION[ctc > band_max] → (true) APPROVAL[HR Manager]
→ APPROVAL[Company Admin] → SYSTEM_ACTION[generate_offer_letter] → NOTIFICATION[offer.ready] → END`

### 3.5 Resignation / Exit
`START → APPROVAL[Reporting Manager: accept/negotiate LWD] → APPROVAL[HR Manager]
→ SYSTEM_ACTION[create_clearance_checklist] → SYSTEM_ACTION[schedule_access_revocation]
→ NOTIFICATION[exit.accepted] → END`

### 3.6 Salary Revision
`START → APPROVAL[Department Head] → APPROVAL[HR Manager] → CONDITION[increment_pct > 20]
→ (true) APPROVAL[Company Admin] → SYSTEM_ACTION[create_compensation_record]
→ SYSTEM_ACTION[flag_arrears_if_backdated] → END`

### 3.7 Expense Claim (Phase 2)
`START → CONDITION[amount ≤ 5,000] → (true) APPROVAL[Manager] → APPROVAL[Finance verify] → END`
`(false) → APPROVAL[Manager] → APPROVAL[Department Head] → APPROVAL[Finance verify] → END`

### 3.8 Profile Change Request
`START → CONDITION[field ∈ controlled_fields] → (true) APPROVAL[HR Executive]
→ SYSTEM_ACTION[apply_change] → END; (false) SYSTEM_ACTION[apply_change] → END`

---

## 4. Condition Expression Language

Safe, sandboxed, non-Turing-complete. **No `eval`, no arbitrary code execution** — this is a
multi-tenant system and a tenant-authored expression must never be able to run code.

**Grammar:** comparison (`=, !=, >, >=, <, <=`), membership (`in`, `not in`), logic (`and, or, not`),
functions (`days_between`, `is_weekend`, `abs`, `round`, `coalesce`).

**Available context variables** (per entity type, published in the builder UI):
```
LEAVE_APPLICATION:  total_days, leave_type_code, is_backdated, balance_after,
                    employee.grade_level, employee.department_code, employee.branch_code,
                    employee.tenure_months, employee.employment_type
EXPENSE_CLAIM:      total_amount, category_code, has_receipt, is_policy_violation, project_code
OFFER:              annual_ctc, band_max, band_min, is_above_band, designation_code
SALARY_REVISION:    increment_percentage, new_ctc, old_ctc, is_backdated, revision_type
```

**Examples:**
```
total_days > 5 and employee.grade_level < 3
total_amount > 500000 or is_policy_violation = true
leave_type_code in ['MATERNITY','PATERNITY']
days_between(from_date, submitted_date) < 0        // backdated
```

**Validation at save time:** unknown variables, type mismatches and unreachable branches are
rejected. The builder provides a **simulator**: paste a sample entity, see the resolved path and
the resolved approvers, before publishing.

---

## 5. SLA, Reminders & Escalation

| Setting | Default |
|---|---|
| SLA per approval node | 24 h (leave), 48 h (others) — business hours per the branch calendar |
| Reminder | At 50% and 90% of SLA, then daily after breach |
| Escalation on breach | Notify the approver's manager; after 2× SLA, auto-assign to the manager |
| Auto-approve on breach | **Disabled by default.** Available per node, but requires explicit tenant configuration and an acknowledgement of the risk. Never enable for payroll, offers or exits. |
| Business-hours calculation | Uses the branch working days and holiday calendar, not raw elapsed time |

**Reporting:** approval turnaround time per approver, per department, per entity type; SLA breach
rate; oldest pending request. This is a genuinely valuable HR analytics output and should be
surfaced on the HR dashboard, not buried in a report.

---

## 6. Actions Available to Approvers

| Action | Effect |
|---|---|
| `APPROVE` | Advance to the next node; comment optional |
| `REJECT` | Terminate (or return, per node config); **comment mandatory** |
| `REQUEST_INFO` | Pause the SLA clock, notify the requester, allow edit-and-resubmit; returns to the same approver |
| `FORWARD` | Reassign to another eligible approver with a reason; original approver remains on the audit trail |
| `DELEGATE` | Configured in advance for a date range |
| `WITHDRAW` | Requester-only, allowed until the first approval is recorded (configurable) |
| `BULK_APPROVE` | Multiple requests of the same type; each is still individually recorded and audited |

**Bulk approve caution:** allowed for leave and regularisation; **forbidden** for offers, salary
revisions, exits and expenses above a threshold. A manager approving 40 leave requests in one tap is
efficiency; a manager approving 40 salary revisions in one tap is a governance failure.

---

## 7. System Actions Catalogue

| Action code | Effect |
|---|---|
| `POST_LEAVE_LEDGER` | Write the ledger debit entry |
| `RECOMPUTE_ATTENDANCE` | Trigger attendance-day recompute for a date range |
| `CREATE_COMPENSATION_RECORD` | Insert the effective-dated compensation row |
| `FLAG_ARREARS` | Mark for arrears computation in the next pay run |
| `GENERATE_DOCUMENT` | Render a letter from a template and attach it |
| `CREATE_TASK_PACK` | Instantiate an onboarding/exit checklist |
| `SCHEDULE_ACCESS_REVOCATION` | Queue account disablement for the LWD |
| `UPDATE_ENTITY_STATUS` | Set the business entity's status field |
| `CREATE_JOB_OPENING` | From an approved requisition |
| `CALL_WEBHOOK` | External system trigger |
| `ASSIGN_ASSET` / `RECOVER_ASSET` | Asset module hooks |

System actions are **idempotent** and run in the same transaction as the step transition where
possible; where not possible (external calls), they use the outbox pattern with retry.

---

## 8. Engine Non-Functional Requirements

| Requirement | Target |
|---|---|
| Request submission → approver notified | < 5 s (p95) |
| Approval action → next step assigned | < 2 s |
| Concurrent approval of the same request by two approvers | Optimistic lock; second gets `409 ALREADY_ACTIONED` with the current state |
| Workflow version change | In-flight requests unaffected |
| Engine failure | Requests remain in their last consistent state; a resume job re-evaluates stuck instances hourly |
| Stuck-request detection | Any request with no state change for 7 days is flagged to HR admin |
| Audit | Every transition, every action, every skip, every escalation, with timestamps and durations |

---

## 9. Notification Engine

### 9.1 Architecture
```
Domain Event ──▶ Event Router ──▶ Recipient Resolver ──▶ Preference Filter
                                                              │
                                        ┌─────────────────────┼─────────────────┐
                                        ▼                     ▼                 ▼
                                  Template Renderer     Rate Limiter      Quiet Hours
                                        │
                     ┌──────────┬───────┴───────┬──────────┬─────────────┐
                     ▼          ▼               ▼          ▼             ▼
                  In-App     Email            Push        SMS        WhatsApp
                     └──────────┴───────────────┴──────────┴─────────────┘
                                        │
                                 Delivery Log + Provider Callbacks + Retry/DLQ
```

### 9.2 Event Catalogue (extract — full catalogue ~120 events)

| Event code | Recipients | Default channels |
|---|---|---|
| `leave.applied` | Approver(s) | in-app, push, email |
| `leave.approved` / `leave.rejected` | Requester; manager cc | in-app, push, email |
| `leave.reminder_pending` | Approver | push, email |
| `leave.balance_low` | Employee | in-app |
| `attendance.missing_punch` | Employee; manager if repeated | push |
| `attendance.absent_unmarked` | Employee, manager, HR | push, email |
| `attendance.late_repeated` | Employee, manager | in-app |
| `attendance.device_offline` | HR admin, IT | email, in-app |
| `payslip.published` | Employee | push, email, WhatsApp |
| `payroll.run_completed` | Payroll owner | email, in-app |
| `payroll.validation_failed` | Payroll owner | email (high priority) |
| `payroll.statutory_due` | HR, Finance | email |
| `employee.joining_today` | Manager, IT, Admin, HR | email, in-app |
| `employee.probation_ending` | Manager, HR | email |
| `employee.birthday` / `.work_anniversary` | Team | in-app |
| `document.expiring` | Employee, HR | email, push |
| `candidate.applied` | Recruiter | in-app |
| `interview.scheduled` / `.reminder` | Panel, candidate | email, push, SMS |
| `offer.released` / `.accepted` / `.declined` | Recruiter, hiring manager | email, in-app |
| `onboarding.task_assigned` / `.overdue` | Task owner | push, email |
| `exit.initiated` / `.clearance_pending` | HR, managers, clearance owners | email, in-app |
| `approval.pending_sla_breach` | Approver's manager | email |
| `security.new_device_login` | User | email, push |
| `security.password_changed` | User | email |

### 9.3 Template Management
- Templates are per `event × channel × language`, tenant-overridable with fallback to the system default.
- Merge variables are declared per event and validated at save time — an unknown variable blocks
  saving (nothing worse than a payslip email reading "Dear {{employee_name}}").
- Rich HTML for email with a plain-text alternative; 160-char discipline for SMS; WhatsApp uses
  pre-approved Meta templates with variable slots.
- Preview and test-send to self before activation.

### 9.4 Delivery Guarantees
| Class | Behaviour |
|---|---|
| **Critical** (payslip, security, statutory, offer) | At-least-once, 5 retries, multi-channel fallback, cannot be muted by the user, alert on final failure |
| **Transactional** (approvals, tasks) | At-least-once, 3 retries, user may change channel but not disable |
| **Informational** (birthdays, announcements) | Best-effort, 1 retry, fully user-controllable, digestible |

### 9.5 Anti-Fatigue Controls
This matters more than it appears: a system that sends 40 notifications a day gets muted, and then
the payslip notification is missed too.
- Digest mode for informational events (one daily summary)
- Deduplication: identical event + recipient within 5 minutes collapses
- Quiet hours per tenant (default 21:00–07:00 local) for non-critical push/SMS
- Per-user weekly cap on informational notifications with an overflow digest
- One-click preference management from every email footer

### 9.6 Cost Controls
SMS and WhatsApp cost real money per message and are the main variable cost in a PEPM model.
- Per-tenant monthly quota by plan; usage dashboard; alert at 80%
- SMS reserved for: OTP, interview reminders to candidates, critical alerts to non-app users
- WhatsApp preferred over SMS where opted in (cheaper, richer, better delivery in India)
- Push and in-app are free — route everything possible there
- A weekly cost report per tenant to the platform team, so a runaway loop is caught in days, not
  at the end-of-month provider invoice

---

## 10. Dashboard Refresh (the last step of the client's automation flow)

- Dashboard widgets subscribe to a WebSocket/SSE channel scoped to `company_id` + `employee_id`.
- On a relevant domain event, the server pushes an invalidation message; the client refetches only
  the affected widget, not the whole dashboard.
- Fallback: polling every 60 s when the socket is unavailable (common on mobile networks).
- Heavy aggregate widgets (headcount cost, attrition) are computed by a scheduled job into a
  `dashboard_metric` table, not calculated live — nobody needs an attrition number to be real-time,
  and computing it live on every dashboard load will melt the database.
