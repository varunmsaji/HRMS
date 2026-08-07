# 04 — User Personas

**UI Sprint 0 — Design Foundation, Document 5 of 5**
Status: Foundational. Every screen's design decisions should be traceable to at least one persona
below.

**Grounded in:** the permission matrix in `docs/product/19` §4 (what each role can actually do), the
dashboard and screen inventory in `docs/product/24` §3.2–§3.10, and the data-scope model in `docs/product/19` §5.
Personas are written as **job roles**, not individuals — an HRMS is bought and configured by
organizations, so the design target is "the Company Admin function," not a fictional named
individual with a backstory. This keeps personas verifiable against the permission matrix rather
than drifting into narrative fiction.

---

## How to use this document

Each persona lists a **primary dashboard** (from `docs/product/24` §3.2's six dashboard variants:
Company Admin, HR, Manager, Employee, Finance, Recruiter) and **most-used screens** (drawn from the
185-screen inventory in `docs/product/24` §3). When two personas share a dashboard or screen set, that's
intentional — it's a signal the design must satisfy both without compromise (e.g., HR Manager and
HR Executive share almost everything, differentiated mainly by approval authority, not by screen).

---

## 1. Super Admin

**Who they are:** the platform operator — not a customer employee. Runs the multi-tenant system
itself: provisioning, plans, monitoring, break-glass support access (`docs/product/19` §3.6, §7).

| | |
|---|---|
| **Responsibilities** | Tenant provisioning and lifecycle, subscription/plan management, feature-flag rollout, platform health monitoring, approved break-glass access for support |
| **Daily tasks** | Check platform health dashboards, review new tenant provisioning requests, respond to escalated support tickets requiring elevated access, monitor background job queues (Celery) for stuck/failed jobs |
| **Primary dashboard** | Platform Console (separate shell — [`02_Information_Architecture.md`](02_Information_Architecture.md) §8), not a tenant dashboard |
| **Most-used screens** | Tenant list/detail, plan & feature-flag management, system monitoring, impersonation launcher, audit log (platform-level) |
| **Common workflows** | Provision a new tenant → assign plan → verify setup checklist completes; investigate a support ticket → time-boxed impersonation → resolve → mandatory post-incident note |
| **Pain points this UI must solve** | Needs to distinguish "my own platform action" from "acting as a tenant" at a glance — ambiguity here is a security incident waiting to happen, hence the mandatory persistent impersonation banner (`03_Navigation_System.md` §11). Also needs fast triage across potentially hundreds of tenants without opening each one — the platform console's tenant list must support the same density/filter patterns as any other admin table in the product. |

---

## 2. Company Admin

**Who they are:** the tenant-side owner of the whole system — typically a founder, CHRO, or Head
of HR Operations at a company that has bought the product. Near-full permissions within their
tenant (`docs/product/19` §4: ● across almost every row).

| | |
|---|---|
| **Responsibilities** | Company-wide configuration (legal entities, branches, departments), role and user management, payroll approval and finalization authority, ultimate accountability for statutory compliance and data governance |
| **Daily tasks** | Review dashboard exceptions (pending approvals across the org, compliance deadlines), approve high-value or sensitive actions escalated from HR Manager, spot-check reports, manage user access as staff join/leave the HR/admin team itself |
| **Primary dashboard** | Company Admin dashboard (`docs/product/24` §3.2) — company-wide KPIs: headcount trend, attrition, pending compliance items, payroll status, open requisitions |
| **Most-used screens** | Company settings, Roles & Permissions matrix editor, User list, Pay run approval/finalization, Reports catalogue, Audit log |
| **Common workflows** | Set up a new legal entity or branch during expansion; define a new role and assign permissions when the org restructures; review and finalize a pay run HR Manager has computed and validated; respond to an auditor's data request |
| **Pain points this UI must solve** | Holds the most consequential, least-frequent actions in the product (payroll finalize, role changes) — needs unambiguous irreversibility signaling (`00_UI_Vision.md` §4 principle 4) precisely because they don't do these often enough to have muscle memory. Also needs a company-wide view that doesn't require drilling into every module to know "is anything on fire today" — this is what the dashboard's exception-first design (`00_UI_Vision.md` §2) exists for. |

---

## 3. HR Manager

**Who they are:** runs HR operations day to day. The most permission-dense role after Company
Admin (`docs/product/19` §4: ● across nearly the entire operational matrix — employee management,
attendance, leave, payroll compute/approve, recruitment, onboarding/exit, performance) and the role
most screens in the product are implicitly designed around.

| | |
|---|---|
| **Responsibilities** | End-to-end ownership of the employee lifecycle for their scope, payroll processing (compute → validate → approve), leave and attendance policy administration, recruitment oversight, onboarding/exit execution |
| **Daily tasks** | Clear the HR approval queue (leave, regularisation, exit requests), review the attendance matrix during payroll week, process new joiners and exits, respond to employee queries escalated from HR Executive, run reports for management |
| **Primary dashboard** | HR dashboard (`docs/product/24` §3.2) — pending approvals, today's attendance exceptions, upcoming payroll deadline, open requisitions, onboarding/exit in progress |
| **Most-used screens** | Employee 360° profile, Attendance Matrix, Applications list (leave), Pay run detail with step progress, Directory, Onboarding task board, Exit clearance checklist |
| **Common workflows** | Full pay run cycle (`docs/product/24` §4.4): select period → review inputs → compute → resolve validation exceptions → review variance → approve; process a new joiner from offer acceptance through Day 1 task completion; process a resignation through clearance to F&F handoff |
| **Pain points this UI must solve** | Spends hours a day in dense tables (Attendance Matrix, Directory, Applications list) — density, virtualization and bulk actions (`01_Design_System.md` §10) are not optional polish for this persona, they're the difference between a usable and unusable tool. Also the primary audience for "every number is explainable" (`00_UI_Vision.md` §4 principle 3) — this is the person who fields "why is my leave balance wrong" questions and needs the system to answer them without a support ticket. |

---

## 4. HR Executive

**Who they are:** operational HR staff executing day-to-day transactions under an HR Manager's
policy authority. Broad **view** access, narrower **approve/finalize** authority (`docs/product/19` §4:
● on data entry and processing, ◐ or — on approval/finalization rows like Payroll finalise,
Leave policy config, Exit initiate-for-other).

| | |
|---|---|
| **Responsibilities** | Employee data entry and maintenance, first-line attendance/leave processing, document verification, onboarding task execution, assisting payroll compute (not approving/finalizing) |
| **Daily tasks** | Process employee data change requests, verify uploaded documents, mark attendance regularisations for approval, assist with payroll input review, handle Tier-1 employee queries |
| **Primary dashboard** | HR dashboard — same as HR Manager, filtered to their scope; a lighter-weight variant showing tasks assigned to them specifically rather than org-wide exceptions |
| **Most-used screens** | Employee 360° profile (edit-heavy), Document verification queue, Bulk import (upload/validate/preview), Regularisation list, Input review (payroll), Letter generation |
| **Common workflows** | Verify a batch of newly uploaded onboarding documents; process a bulk employee data import (upload → validate → preview → commit); prepare payroll inputs for HR Manager to review and approve |
| **Pain points this UI must solve** | Does high-volume, repetitive data work — form efficiency (smart defaults, minimal re-entry, clear validation before submit per `00_UI_Vision.md` §4 principle 2) matters more here than anywhere else in the product. Needs a visible, correct boundary between "what I can finalize" and "what I can only prepare for someone else to approve" so they're never confused about whether an action is actually complete — addressed by the design system's absent-not-disabled rule making the boundary structural, not just a tooltip. |

---

## 5. Recruiter

**Who they are:** owns the hiring pipeline. Full authority within Recruitment, near-zero access
outside it (`docs/product/19` §4: ● on Recruitment, ◐ "hired only" on Employee view, ◐ "offer only" on
Compensation view — sees CTC only in the context of an offer they're building).

| | |
|---|---|
| **Responsibilities** | Requisition intake, job posting, candidate sourcing and pipeline management, interview coordination, offer creation, conversion of accepted candidates to employees |
| **Daily tasks** | Triage new applications, move candidates through pipeline stages, schedule interviews, collect and review interview feedback, draft and route offers for approval |
| **Primary dashboard** | Recruiter dashboard (`docs/product/24` §3.2) — open requisitions, applications awaiting triage, interviews scheduled this week, offers pending approval |
| **Most-used screens** | Application kanban, Candidate profile, Resume viewer with parsed-field overlay, Interview calendar, Feedback form, Offer form with CTC breakup |
| **Common workflows** | Move a candidate from application through interview stages to offer (`docs/product/24` §7, core flow 5); bulk-review and reject a batch of unqualified applications; build an offer with CTC breakup and route it for approval |
| **Pain points this UI must solve** | Works against time pressure (candidates have competing offers) — the pipeline kanban needs to make "what's stalled and needs action today" obvious at a glance, not buried in a flat list. Also the primary user of AI-assisted matching/parsing features (`docs/product/01` §3 "AI that assists, never decides") — needs AI suggestions (resume-to-requisition match, parsed fields) visually distinct from verified data, per the AI-pattern rule in `00_UI_Vision.md` §11, so they never mistake a model's guess for a confirmed fact when making a hiring call. |

---

## 6. Reporting Manager

**Who they are:** any employee with direct or indirect reports in the formal reporting tree —
could be a department head, a team of team leads, or a senior individual contributor with a small
team. Data scope is `REPORTEE_TREE` (`docs/product/19` §5) — everyone below them recursively, not just
direct reports.

| | |
|---|---|
| **Responsibilities** | Approving requests from their entire reporting tree (leave, regularisation, expense, exit-initiate for their people is *not* granted — that stays with HR), performance review conduct across the tree, team-level reporting |
| **Daily tasks** | Clear approvals (leave, regularisation), check team attendance/coverage before approving time off, conduct or review performance evaluations during cycles, monitor team-level metrics |
| **Primary dashboard** | Manager dashboard (`docs/product/24` §3.2) — team coverage today, pending approvals across the tree, upcoming performance cycle deadlines |
| **Most-used screens** | Approval inbox (unified, cross-module), Team calendar (leave), Attendance calendar (team, read-only), Directory (scoped to tree), Performance review screens (tree-wide) |
| **Common workflows** | Clear a batch of mixed approval types in one sitting (`docs/product/24` core flow 2 — approving five mixed requests on mobile); check team coverage before approving a leave request that would leave a shift short-staffed; run a calibration or review pass across the whole tree during a performance cycle |
| **Pain points this UI must solve** | Approves from a phone, often between meetings — the swipe-based inbox with the "one number that matters" per card (`docs/product/24` §4.5) exists specifically for this persona. Managing a multi-level tree (not just direct reports) means list/filter screens must make "which layer of my org is this person in" clear, or a Reporting Manager can lose track of who they're actually looking at in a large org. |

---

## 7. Team Leader

**Who they are:** first-line supervisor with **direct reports only** (`REPORTEES` scope, one level
— `docs/product/19` §5), distinct from Reporting Manager's recursive tree. Common in shift-based
industries (manufacturing, logistics, retail) where a Team Leader supervises a fixed shift crew.

| | |
|---|---|
| **Responsibilities** | Direct-report approvals (leave, regularisation, overtime), shift-level attendance oversight, first-line performance input |
| **Daily tasks** | Approve/reject direct reports' time-off and regularisation requests, monitor same-day attendance for their shift/crew, escalate exceptions to HR |
| **Primary dashboard** | Manager dashboard, functionally identical to Reporting Manager's but scoped to one level — same component, narrower data |
| **Most-used screens** | Approval inbox, Today's overview (attendance), Attendance calendar (direct reports), Overtime request form/approval |
| **Common workflows** | Approve a shift-swap or overtime request quickly enough that the shift isn't left short; review same-day attendance each morning to know who's present for the shift |
| **Pain points this UI must solve** | Often the least tech-comfortable persona in the product — frequently a frontline supervisor, not an office worker, and frequently on a low-end Android device with inconsistent connectivity (shared context with the Employee persona's field-worker segment, §8 below). The mobile-first approval and attendance screens must degrade gracefully on poor connections and never assume a large screen, fast network, or extensive onboarding/training time. |

---

## 8. Employee

**Who they are:** every person in the organization, including the roles above — everyone is an
Employee first. The highest-volume user by headcount, the lowest-frequency user by session depth
(`docs/product/24` §1: "the mobile app is not the web app shrunk" exists because of this persona).

| | |
|---|---|
| **Responsibilities** | None administratively — this is the "using HR software as an obligation, not a job" persona the whole product philosophy is built around (`00_UI_Vision.md` §3) |
| **Daily tasks** | Punch in/out (if applicable to their role), occasionally apply for leave, occasionally check a payslip, rarely update profile information |
| **Primary dashboard** | Employee dashboard (`docs/product/24` §3.2) — today's status (punched in/out, leave balance), recent payslip, quick links to apply for leave or view the team directory |
| **Most-used screens** | Punch screen (mobile), Apply leave, Payslip detail with breakdown drawer, Employee directory (read-only), My profile |
| **Common workflows** | Punch in at the start of a shift, possibly from a site with poor connectivity (`docs/product/24` core flow 6); apply for leave and see the day-count preview and balance impact before submitting (`docs/product/24` §4.7); open a payslip and tap a line to understand a deduction |
| **Pain points this UI must solve** | Opens the app a handful of times a month with zero desire to learn it — every screen this persona touches must be self-explanatory with no training, per the product's core measurable goal of ≥80% monthly active employees on ESS/mobile (`docs/product/01` §4). Connectivity cannot be assumed — the punch flow's explicit offline-queue behavior (`docs/product/24` §4.6) is not an edge case for this persona, it's Tuesday for a field worker in logistics or construction. Every payslip deduction must be tap-to-explain (`docs/product/24` §4.3) because this is the single highest-friction moment in the relationship between an employee and HR — "why is my salary less this month" is the ticket this screen exists to prevent. |

---

## 9. Auditor

**Who they are:** internal or external compliance/audit function. Strictly read-only across
**everything**, including the audit log itself, with no export of salary-level detail unless
explicitly granted — and every read they perform is itself logged (`docs/product/19` §4, §6).

| | |
|---|---|
| **Responsibilities** | Independent verification of process compliance, statutory filing accuracy, access-control correctness, and data governance — produces findings, never edits records |
| **Daily tasks** | Sample-review employee records, attendance/leave transactions, payroll runs and statutory filings for compliance; review the audit log for anomalous access patterns; verify RBAC configuration matches policy |
| **Primary dashboard** | A read-only variant of the Reports view (`docs/product/24` §3.2 does not name a dedicated Auditor dashboard — this persona's entry point is the Reports catalogue and Audit log, not a bespoke dashboard) |
| **Most-used screens** | Audit log viewer, Report viewer (generic, parameterised), Compliance calendar, Employee 360° (read-only, RESTRICTED fields masked per `docs/product/19` §6), Pay run detail (read-only) |
| **Common workflows** | Trace a specific record's full change history via "View audit trail"; sample a set of pay runs against statutory filing records; verify a role's permission grants against documented policy |
| **Pain points this UI must solve** | Needs airtight confidence that **read-only actually means read-only** in the interface, not just server-side — any edit-affording control (even one that would 403 on submit) visible to an Auditor undermines trust in the whole access model, so the absent-not-disabled rule (`00_UI_Vision.md` §4 principle 8) is load-bearing specifically for this persona. Also needs field-level masking (PAN, Aadhaar, bank account per `docs/product/19` §6) to be visually unambiguous — a masked field must look deliberately masked, not like a rendering bug, so the Auditor never has to guess whether they're seeing redacted or broken data. |

---

## Cross-persona design implications

A few patterns recur across personas above and should be treated as system requirements, not
one-off observations:

| Pattern | Personas it serves | Where it's specified |
|---|---|---|
| Mobile-first, poor-connectivity-tolerant approval/punch flows | Team Leader, Reporting Manager, Employee | `00_UI_Vision.md` §8, `03_Navigation_System.md` §4 |
| Dense, virtualized, bulk-action-capable tables | HR Manager, HR Executive, Company Admin | `01_Design_System.md` §3–4, `00_UI_Vision.md` §10 |
| Tap-to-explain on every computed number | Employee, HR Manager, HR Executive, Auditor | `00_UI_Vision.md` §4 principle 3 |
| Absent-not-disabled permission gating | Auditor, Recruiter, Employee, every scoped role | `00_UI_Vision.md` §4 principle 8, `02_Information_Architecture.md` §7 |
| Distinct irreversible-action treatment | Company Admin, HR Manager | `00_UI_Vision.md` §4 principle 4 |
| AI-suggestion visual distinction from verified data | Recruiter (resume matching), HR Manager (attrition risk) | `00_UI_Vision.md` §11 |

---

## What's deferred to later sprints

- Persona-specific onboarding/tutorial flows — decided once the core screens exist to onboard
  someone into.
- Quantitative usage data (session length, feature adoption) to validate these personas — this
  document is the design-time hypothesis; `docs/product/24` §7 already schedules usability testing against
  five real users per core flow (three of them actual HR practitioners) before build, which is
  where these personas get tested against reality.
