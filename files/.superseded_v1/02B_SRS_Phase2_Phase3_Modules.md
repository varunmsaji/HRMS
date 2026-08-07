# Document 02B — SRS: Phase 2 & Phase 3 Modules

These modules are specified at a lower resolution than Phase 1 deliberately — they will be
re-specified in detail at the start of their phase, informed by real usage of the MVP. What is
fixed here is **scope boundary, data model impact and integration points**, so that Phase 1
architecture does not paint us into a corner.

---

# 1. Performance Management (PRF) — Phase 2

## 1.1 Supported Methodologies
The product must support at least three, because the eight target industries do not share one:
- **KRA/KPI with weighted scoring** (manufacturing, retail, logistics — measurable output)
- **OKR** (IT, startups)
- **Competency-based rating** (healthcare, education, hospitality)
- Plus **360° feedback** and **continuous check-ins** as overlays on any of the above.

| ID | Requirement | Pri |
|----|-------------|-----|
| FR-PRF-001 | Appraisal cycle master: name, period, applicability (department/grade/location/tenure), phases with dates (goal-setting, self-review, manager review, calibration, HR review, release), eligibility rule (min N months of service). | M |
| FR-PRF-002 | Goal library per designation, cascading from company → department → individual, with weightage summing to 100%, target values, measurement basis and due dates. | M |
| FR-PRF-003 | Goal lifecycle: draft → employee submitted → manager approved → in progress → self-rated → manager-rated → finalised. Mid-cycle goal addition/modification with approval and audit. | M |
| FR-PRF-004 | Rating scales configurable (3/4/5/10-point) with labels and descriptors; support decimal ratings and forced non-integer prevention. | M |
| FR-PRF-005 | Self-appraisal, manager appraisal, skip-level (L2) review, peer & subordinate feedback with anonymity controls and a minimum-responses threshold before anonymised results display. | M |
| FR-PRF-006 | Calibration: normalisation across managers, bell-curve distribution targets per band (configurable and **optional** — forced ranking is legally and culturally contentious; must be switchable off), calibration meeting workspace with before/after tracking. | M |
| FR-PRF-007 | Final rating → outcome mapping: increment %, promotion eligibility, bonus multiplier, PIP trigger — as a rules table, with the increment feeding the compensation-revision workflow and thence payroll. | M |
| FR-PRF-008 | Performance Improvement Plan: objectives, duration, review checkpoints, outcome (closed successfully / extended / exit), with confidentiality restricted to employee, manager and HR. | M |
| FR-PRF-009 | Continuous feedback: 1:1 check-in notes, praise/recognition, real-time feedback requests, visible on the appraisal form as evidence. | S |
| FR-PRF-010 | Analytics: rating distribution, manager leniency/severity index, goal-completion rate, high-potential and low-performer identification, correlation of rating with attrition. | S |
| FR-PRF-011 | Increment letter generation and bulk increment processing with an effective date, feeding arrears if backdated. | M |

**Integration points:** compensation revision (EMP), payroll arrears (PAY), succession & promotion
(EMP), learning recommendations (LMS), attrition prediction (AI).

---

# 2. Task & Checklist (TSK) — Phase 2 (partially in Phase 1 for onboarding/exit)

| ID | Requirement | Pri |
|----|-------------|-----|
| FR-TSK-001 | Generic task entity: title, description, assignee (user/role), requester, due date, priority, status, checklist items, attachments, comments, linked entity (employee/candidate/asset/ticket). | M |
| FR-TSK-002 | Task templates and packs, instantiable by any module (onboarding, exit, event, compliance). | M |
| FR-TSK-003 | Recurring tasks (compliance filings, periodic reviews) with a schedule and auto-creation. | S |
| FR-TSK-004 | Reminders, overdue escalation to the assignee's manager, and a personal "My Tasks" view across all modules. | M |
| FR-TSK-005 | Task dependency (B starts after A completes) and blocking indicators. | S |

---

# 3. Communication (COM) — Phase 2

| ID | Requirement | Pri |
|----|-------------|-----|
| FR-COM-001 | Announcements: rich content, target audience by org filter, schedule, expiry, pin, read-receipt tracking, acknowledgement-required flag for policy communications. | M |
| FR-COM-002 | Policy document library with versioning, mandatory acknowledgement tracking, and reminder to non-acknowledgers. | M |
| FR-COM-003 | Company events calendar, birthdays and work anniversaries with automated greetings (opt-out available). | S |
| FR-COM-004 | Broadcast messaging via WhatsApp/SMS/email to filtered employee groups with consent and rate-limit checks. | M |
| FR-COM-005 | Employee suggestion box with optional anonymity and a response workflow. | C |

---

# 4. Employee Experience (EXP) — Phase 3

| ID | Requirement | Pri |
|----|-------------|-----|
| FR-EXP-001 | Survey engine: templates (engagement, eNPS, pulse, onboarding, exit), question types, anonymity settings, targeting, scheduling, reminders. | M |
| FR-EXP-002 | Anonymity guarantee: results shown only when the response count in a segment ≥ 5, enforced server-side, with no drill-down that could re-identify. | M |
| FR-EXP-003 | Recognition & rewards: peer-to-peer badges, points, redemption catalogue, manager awards, leaderboard (opt-in). | S |
| FR-EXP-004 | Engagement analytics: eNPS trend, driver analysis, department heatmap, action planning with owners. | S |
| FR-EXP-005 | Wellness: initiatives, challenges, mental-health resources, EAP contact — with strict confidentiality (no employer visibility of individual participation in health-related items). | C |

---

# 5. Learning & Development (LMS) — Phase 3

| ID | Requirement | Pri |
|----|-------------|-----|
| FR-LMS-001 | Course catalogue: internal courses (video, document, SCORM, link), external/classroom sessions, cost, duration, prerequisites, validity period. | M |
| FR-LMS-002 | Enrolment: self, manager-nominated, HR-assigned, auto-assigned by rule (designation, new joiner, compliance mandate). | M |
| FR-LMS-003 | Training calendar, batch/session management, trainer, venue, capacity, attendance marking. | M |
| FR-LMS-004 | Assessments & quizzes with pass criteria, retakes, and certificate generation with expiry. | M |
| FR-LMS-005 | **Compliance training tracking** — mandatory for healthcare/manufacturing: assign, track, escalate, and produce an audit-ready evidence report per employee per requirement. | M |
| FR-LMS-006 | Skill/competency matrix: required vs actual per role, gap analysis, learning recommendation. | S |
| FR-LMS-007 | Training budget, cost per employee, effectiveness feedback (Kirkpatrick L1/L2), and ROI reporting. | S |
| FR-LMS-008 | Certification & licence expiry tracking with alerts (healthcare registration, driving licence, safety certification). | M |

---

# 6. Asset Management (AST) — Phase 2

| ID | Requirement | Pri |
|----|-------------|-----|
| FR-AST-001 | Asset master: category, sub-category, make/model, serial number, asset tag, purchase date, cost, vendor, warranty expiry, AMC, depreciation method, current value, condition, location, status (`IN_STOCK`, `ASSIGNED`, `UNDER_REPAIR`, `LOST`, `SCRAPPED`). | M |
| FR-AST-002 | Assignment to an employee with an issue date, acknowledgement (e-sign), and an issue note; return with a condition assessment. | M |
| FR-AST-003 | Asset request workflow by employees, approval, and fulfilment. | M |
| FR-AST-004 | Integration with onboarding (auto-request per template) and exit (auto-add to the clearance checklist, damage/loss deduction to F&F). | M |
| FR-AST-005 | Maintenance/repair log, service requests, downtime tracking. | S |
| FR-AST-006 | Bulk import, QR/barcode tag generation and mobile scan for physical verification/audit. | S |
| FR-AST-007 | Reports: asset register, assignment register, ageing, warranty expiring, unreturned assets of exited employees, depreciation schedule. | M |

---

# 7. Expense & Reimbursement (EXP-C) — Phase 2

| ID | Requirement | Pri |
|----|-------------|-----|
| FR-EXC-001 | Expense categories with per-category policy: limits by grade, receipt-mandatory threshold, allowed payment modes, GST-claimable flag, taxability. | M |
| FR-EXC-002 | Claim creation with multiple line items, receipt upload/photo, OCR extraction of amount/date/vendor/GST, currency, project/cost-centre tagging. | M |
| FR-EXC-003 | Policy violation detection at submission (over limit, missing receipt, duplicate receipt hash, outside travel dates) with a warning or hard block. | M |
| FR-EXC-004 | Multi-level approval by amount slab; finance verification stage; rejection with reason and re-submission. | M |
| FR-EXC-005 | Travel request & advance: pre-trip request, advance disbursement, post-trip settlement against the advance with a refund or additional payment. | M |
| FR-EXC-006 | Payment via payroll or a separate payment run; status tracking to the employee. | M |
| FR-EXC-007 | Mileage claims with distance from GPS/route and a per-km rate by vehicle type. | S |
| FR-EXC-008 | Reports: expense by category/department/employee/project, policy-violation log, pending liability, GST input register. | M |

---

# 8. HR Helpdesk (HLP) — Phase 2

| ID | Requirement | Pri |
|----|-------------|-----|
| FR-HLP-001 | Ticket categories & sub-categories mapped to owning teams (payroll, leave, IT, admin, general HR), each with an SLA. | M |
| FR-HLP-002 | Ticket lifecycle: `NEW → ASSIGNED → IN_PROGRESS → PENDING_EMPLOYEE → RESOLVED → CLOSED / REOPENED`, with auto-close after N days of no response. | M |
| FR-HLP-003 | Auto-assignment by category + branch, load balancing, manual reassignment, internal notes vs employee-visible replies. | M |
| FR-HLP-004 | SLA tracking with breach alerts and escalation matrix; first-response and resolution SLAs measured separately. | M |
| FR-HLP-005 | Knowledge base with articles, search, and article suggestion at ticket creation to deflect tickets. | M |
| FR-HLP-006 | AI assistant answers common queries from the knowledge base and employee-specific data (leave balance, payslip) before creating a ticket — the primary deflection mechanism. | S |
| FR-HLP-007 | Satisfaction rating on closure; analytics on volume by category, resolution time, deflection rate, repeat issues. | M |
| FR-HLP-008 | Confidential category (grievance, POSH) visible only to a designated committee, excluded from general HR views and from analytics drill-down. | M |

---

# 9. Visitor Management (VIS) — Phase 3

| ID | Requirement | Pri |
|----|-------------|-----|
| FR-VIS-001 | Pre-registration by an employee with visitor details, purpose, expected time; invite with a QR code to the visitor. | M |
| FR-VIS-002 | Walk-in registration at reception: photo capture, ID proof scan, host selection, purpose, badge printing. | M |
| FR-VIS-003 | Host notification on arrival (app/SMS) with accept/decline. | M |
| FR-VIS-004 | Check-out, over-stay alerts, and a real-time "who is in the building" list for emergency evacuation. | M |
| FR-VIS-005 | Blacklist, NDA e-sign at check-in, and material inward/outward gate pass. | S |
| FR-VIS-006 | Contractor/vendor entry with document and safety-induction validity checks (manufacturing/construction). | S |
| FR-VIS-007 | Visitor data retention & privacy: auto-purge photos and ID data after a configured period. | M |

---

# 10. Advanced Analytics & Workforce Planning — Phase 3

| ID | Requirement | Pri |
|----|-------------|-----|
| FR-ANL-001 | Executive HR scorecard: headcount, cost, attrition, time-to-hire, absenteeism, span of control, diversity, trained %, engagement — with trend and target. | M |
| FR-ANL-002 | Headcount planning: budgeted vs actual positions per department, vacancy pipeline, hiring plan vs actual, cost projection. | M |
| FR-ANL-003 | Succession planning: critical roles, successors with readiness levels, 9-box grid, bench strength. | S |
| FR-ANL-004 | Compensation analytics: internal pay equity, compa-ratio vs band midpoint, gender pay gap, salary-range penetration. | S |
| FR-ANL-005 | What-if simulation: impact of an X% increment, a headcount change, or a policy change on total cost. | C |
| FR-ANL-006 | Benchmark/industry comparison (data source to be defined; may require a third-party dataset). | C |

---

# 11. Deferred Items Requiring Explicit Client Decision

| Item | Why deferred | Decision needed by |
|------|--------------|--------------------|
| Timesheets & project costing | Only IT/consulting need it; significant module | Phase 2 planning |
| Shift roster optimisation (auto-scheduling) | Constraint-solver work, expensive | Phase 3 planning |
| Multi-country payroll | Architecture allows it; each country is a project | When the first non-India customer signs |
| On-premise deployment | Fundamentally changes release, support and pricing | Before the first enterprise deal |
| Public developer API + marketplace | Needs stable contracts and rate-limiting infrastructure | Phase 3 |
| Biometric hardware resale/bundling | Commercial, not technical | Commercial team |
