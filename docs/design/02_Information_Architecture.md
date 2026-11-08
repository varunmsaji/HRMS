# 02 — Information Architecture

**UI Sprint 0 — Design Foundation, Document 3 of 5**
Status: Foundational. This is the sitemap every route, sidebar and breadcrumb in the product
derives from.

**Reconciles two existing sources into one canonical tree:** the web IA in `docs/product/24` §2.1–2.2
(Dashboard/Employees/Recruitment/… as originally scoped) and the full module/permission catalogue
in `docs/product/19` §3 (which additionally defines Onboarding, Exit, Workflow, Asset, Expense, Helpdesk,
Learning as first-class modules). This document is the merged, current answer — supersede
`docs/product/24` §2 for navigation purposes; `docs/product/24` remains authoritative for screen-level detail and
copy rules.

---

## 1. Design rules behind this IA

1. **Nav reflects how people think about their job, not how tables are named in the database.**
   "People" not "Employee records"; "Leave" not "Leave application entity" (`docs/product/24` §1.1).
2. **Lifecycle modules nest under the object they act on.** Onboarding and Exit are moments in an
   employee's lifecycle, not independent destinations — they live inside **People**, reachable both
   from the People section and contextually from an individual's Employee 360° profile
   (`docs/product/24` §4.1).
3. **Cross-cutting concerns are not top-level nav items.** Approvals and Notifications touch every
   module (leave, expense, asset, recruitment, exit all generate approvals) so they live in the
   **top bar**, not the sidebar — see [`03_Navigation_System.md`](03_Navigation_System.md) §4–5.
   Putting them in the sidebar would force a false choice about which single module they belong to.
4. **What a role sees is a filter on this same tree, never a different tree.** The IA is one
   structure; RBAC (`docs/product/19`) determines which branches render for a given user. There is no
   "HR version" and "employee version" of the sitemap — see §7.
5. **The Super Admin (platform operator) surface is architecturally separate**, not a branch of the
   tenant sidebar — see §8. A platform operator managing tenants is not "using the HRMS," they're
   operating the system the HRMS runs on.

---

## 2. The complete tree

```
Dashboard                              (role-specific — see 04_User_Personas.md)

People
├─ Directory                           (table + card view, filters, org chart toggle)
├─ Employee 360°                       (Profile · Job · Compensation · Attendance · Leave ·
│                                        Documents · Assets · Performance · Timeline)
├─ Add employee                        (4-step wizard)
├─ Bulk import                         (upload → validate → preview → commit)
├─ Org chart
├─ Letters & templates
├─ Onboarding                          (joiners · task boards · pre-boarding portal · induction)
└─ Exit                                (resignations · clearance · exit interviews · F&F · attrition)

Recruitment
├─ Requisitions
├─ Job openings                        (+ public careers page, unauthenticated)
├─ Candidates
├─ Applications                        (kanban by stage)
├─ Interviews
├─ Offers
└─ Analytics

Attendance
├─ Today
├─ Matrix                              (the HR "lives here during payroll week" screen)
├─ Employee calendar
├─ Regularisations
├─ Overtime
├─ Shifts & Rosters
├─ Devices & Geofences
└─ Lock period

Leave
├─ My leave / Apply                    (employee-facing entry point)
├─ Applications                        (HR queue)
├─ Balances & Ledger
├─ Team calendar
├─ Leave types & Policies
├─ Holiday calendar
└─ Accrual & Year-end processing

Payroll
├─ Pay runs                            (wizard: select period → review → compute → validate →
│                                        variance → approve → finalise)
├─ Payslips
├─ Salary components & Structures      (+ formula builder)
├─ Statutory setup                     (PF · ESI · PT · TDS · LWF)
├─ Loans
├─ Tax                                 (declarations · proofs · computation · regime comparison)
├─ Bank & Statutory files
├─ Full & Final settlement
└─ Reports

Performance
├─ Cycles
├─ Goals
├─ Reviews
├─ Calibration
└─ PIP

Learning
├─ Course catalogue
├─ My learning / Enrolments
├─ Nominations
└─ Completion reports

Assets
├─ Asset register
├─ Assignments
├─ Requests
└─ Audit

Expenses
├─ My claims / Submit claim
├─ Approvals queue
├─ Policy
└─ Reports & Export

Reports
├─ Standard report catalogue
├─ Report builder                      (custom, parameterised)
├─ Scheduled reports
├─ Compliance calendar
└─ Export jobs

Settings
├─ Company & Legal entities
├─ Branches                            (+ map)
├─ Departments & Designations & Grades
├─ Roles & Permissions                 (matrix editor)
├─ Users
├─ Workflows                           (visual builder + simulator)
├─ Notification templates
├─ Custom fields
├─ Integrations
└─ Audit log

── Not in the sidebar, always reachable from the top bar ──
Global Search
Approvals inbox                        (unified, cross-module)
Notifications
Profile menu                           (My profile · My payslips · Preferences · Sign out)
Helpdesk                               (ticket submission — icon-level entry; full module is Phase 2)
```

### Settings as built (web, 2026-11)

`/app/settings` shows one card per area, with that area's progress from the setup checklist. Each
area has its own page at `/app/settings/<area>` that lists everything for it as numbered steps in
setup order, so an admin never has to leave the area to finish it:

| Area | Page | Steps |
|---|---|---|
| Company & structure | `/app/settings/organisation` | Company · People structure |
| Attendance | `/app/settings/attendance` | When people work · Where people punch · Attendance rules · Who follows which rules · Closing the month |
| Leave | `/app/settings/leave` | Leave types and rules · Who follows which rules |
| Payroll | `/app/settings/payroll` | Pay setup |
| Access & setup | `/app/settings/access` | Users · Setup checklist |

"Who follows which rules" shows what the whole company follows today for that area's policies,
with each policy linking to its own **Who follows this** tab. Every assignable policy (attendance,
overtime, regularization, leave, work calendar, weekly-off pattern) has that tab, where the admin
adds or ends the groups and people who follow it. **Rules by Group** (`/app/policy-assignments`)
stays as the by-group view (everything one group follows, side by side) and **Check a Person's
Rules** as the per-person check; both are linked from each area's "Who follows" step. Each card on
an area page also shows a live status, e.g. "3 shifts" or "2 policies · 1 not assigned". The source of truth for the areas is
`SETTINGS_MODULES` in `apps/web/src/components/layout/nav-items.ts`.

---

## 3. Why "People" and not "Employees"

The user-facing prompt for this sprint asks for **People** as the top-level label, which we adopt
over `docs/product/24`'s original "Employees" for the same reason `docs/product/24` §1.1 states directly: name
things as people control them, not as the system stores them. "People" reads as the department;
"Employees" reads as the table. Everything that was under `docs/product/24}`'s Employees section, plus the
Onboarding and Exit modules from `docs/product/19`, consolidates here because they all act on the same
underlying object — a person's record and lifecycle.

---

## 4. Module relationships

The IA is not twelve independent silos — data and workflows cross module boundaries constantly.
These are the relationships that must stay visible in the UI (via cross-links, quick actions, and
contextual navigation), not just in the database:

```
Recruitment ──"Convert to employee"──► People
People ──"Compensation, assignment"──► Payroll
People ──"Reporting line, department"──► Attendance, Leave, Performance (defines data scope)
Attendance ──"LOP days, OT"──► Payroll (pay run inputs)
Leave ──"LOP days, encashment"──► Payroll (pay run inputs)
People (Onboarding) ──"Asset issuance"──► Assets
People (Exit) ──"Asset return, clearance"──► Assets
People (Exit) ──"Final settlement"──► Payroll (F&F)
Performance ──"Calibration outcome"──► People (compensation review trigger, manual)
Learning ──"Completion records"──► People (Employee 360° → Performance tab, informational)
Expenses ──"Approved claims"──► Payroll (reimbursement in next run) or Finance export
Everything with an approval step ──► Workflow engine ──► Approvals inbox (top bar, cross-module)
Everything that changes a record ──► Audit log (Settings, and per-record "View audit trail")
```

**Design implication:** the Employee 360° profile (`docs/product/24` §4.1) is the hub these relationships
converge on — its quick actions ("Apply leave on behalf," "Initiate transfer," "Initiate exit,"
"Generate letter") are effectively shortcuts into other modules pre-scoped to this one person. Any
screen that shows a person's name should offer a path back to their 360° profile; this is the one
navigational shortcut allowed to bypass the sidebar hierarchy, because it mirrors how HR actually
works — starting from a person and looking at everything about them, not starting from a module.

---

## 5. Public / unauthenticated surfaces

Two branches of the tree are reachable without a login and sit outside the tenant application
shell entirely:

| Surface | Purpose | Entry point |
|---|---|---|
| **Careers page + job detail + public application form** | Candidate-facing job board | `Recruitment → Job openings → Publish` generates a public URL |
| **Offer acceptance portal** | Candidate accepts/declines an offer | Emailed link, token-scoped |
| **Pre-boarding portal** | New joiner completes forms before day one | Emailed link, token-scoped |

These are visually related to the product (same design system) but are **not** the same
application shell — no sidebar, no authenticated nav, single-purpose layouts. Treated as their own
mini information architecture in the navigation spec ([`03_Navigation_System.md`](03_Navigation_System.md)
§7).

---

## 6. Employee Self-Service (ESS) — a subset view, not a separate tree

Per `docs/product/24` §2.2, employees do not get a different sitemap — they get a **reduced view of the
same tree**, scoped to their own data:

```
Home
My attendance          → Attendance, scoped to SELF
My leave               → Leave, scoped to SELF
My payslips            → Payroll, scoped to SELF (PAYROLL.PAYSLIP.VIEW_OWN only)
My tax                 → Payroll → Tax, scoped to SELF
My profile              → People → Employee 360°, own record, editable fields only
My documents            → People → Employee 360° → Documents tab, own record
My learning             → Learning, scoped to SELF
My assets               → Assets, scoped to SELF
My expenses              → Expenses, scoped to SELF
My team (if manager)    → People → Directory, scoped to REPORTEE_TREE
Approvals (if manager)   → top-bar Approvals inbox, populated only if reportees exist
Directory                → People → Directory, read-only, PUBLIC/INTERNAL fields only
Policies                 → Settings-authored content, read-only
Helpdesk                 → ticket submission
```

This is a data-scope filter (`docs/product/19` §5), not a UI fork — the same Directory component renders
for HR and for an employee; only the query scope and visible columns differ. This is the mechanism
that keeps "Future scalability" (§11 of [`00_UI_Vision.md`](00_UI_Vision.md)) real: a new role
never needs a new screen, only a new scope resolution.

---

## 7. Role-based visibility of top-level nav

Full detail lives in `docs/product/19` §4 (the permission matrix) and
[`04_User_Personas.md`](04_User_Personas.md); this is the IA-level summary — which top-level items
a role's sidebar renders at all (● = full section, ◐ = scoped subset only, — = absent, not
disabled):

| Nav item | Super Admin | Company Admin | HR Mgr | HR Exec | Recruiter | Reporting Mgr | Team Leader | Employee | Auditor |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| Dashboard | ● | ● | ● | ● | ● | ● | ● | ● | ● |
| People | ● | ● | ● | ● | ◐ hired only | ◐ tree | ◐ direct | ◐ self | ◐ read |
| Recruitment | — | ● | ● | ◐ | ● | ◐ own reqs | — | ◐ referral | ◐ read |
| Attendance | — | ● | ● | ● | — | ◐ tree | ◐ direct | ◐ self | ◐ read |
| Leave | — | ● | ● | ● | ◐ self only | ◐ tree | ◐ direct | ◐ self | ◐ read |
| Payroll | — | ● | ● | ◐ | — | — | — | ◐ self only | ◐ read |
| Performance | — | ● | ● | ◐ | — | ◐ tree | ◐ direct | ◐ self | ◐ read |
| Learning | — | ● | ● | ◐ | — | ◐ tree | ◐ direct | ◐ self | ◐ read |
| Assets | — | ● | ● | ◐ | — | — | — | ◐ self | ◐ read |
| Expenses | — | ● | ● | ◐ | — | ◐ approve | ◐ approve | ◐ self | ◐ read |
| Reports | ● | ● | ● | ◐ | ◐ recruitment | ◐ team | ◐ team | ◐ self | ● |
| Settings | ● | ● | ◐ | — | — | — | — | — | ◐ read |

**Rule this table exists to enforce:** the sidebar component queries the permission set and
renders only the items marked above — a `—` means the nav item does not exist in the DOM for that
role, never a disabled/greyed link (§4 principle 8 of [`00_UI_Vision.md`](00_UI_Vision.md)).

---

## 8. Super Admin: a separate shell, not a branch

The **Super Admin** role operates the platform itself (`docs/product/19` §3.6 `PLATFORM.*` permissions:
tenant management, plan management, impersonation, feature flags, system monitoring) — this is not
"using the HRMS as an admin," it's operating the multi-tenant system the HRMS runs on.

This surface is designed as its **own application shell**:

```
Platform Console (separate from any tenant's sidebar)
├─ Tenants                  (list, provision, suspend)
├─ Plans & Feature flags
├─ System monitoring         (health, jobs, queues)
├─ Impersonation             (time-boxed, fully logged — docs/product/19 §7)
└─ Support tools
```

A Super Admin who needs to view a specific tenant's data does so via **logged, time-boxed
impersonation** into that tenant's normal shell (rendering the standard Company Admin view with an
impersonation banner) — never a special "super view" bolted onto the tenant IA. This keeps the
tenant-facing information architecture (§2) uncontaminated by platform-operator concerns, which
matters because most engineering and design attention goes to the tenant IA and it must never carry
complexity that only exists for a handful of internal operators.

---

## 9. What's deferred to later sprints

- Exact route/URL structure (`/people/:id`, `/payroll/pay-runs/:id`, etc.) — an implementation
  detail for the frontend routing sprint, though it should mirror this tree directly.
- Per-screen breadcrumb copy — mechanics are defined in
  [`03_Navigation_System.md`](03_Navigation_System.md) §3; exact strings are written screen-by-screen
  alongside the 185-screen build (`docs/product/24` §3).
- Helpdesk as a full top-level module — flagged Phase 2 per the confidentiality rules in `docs/product/19`
  §7 (POSH/grievance visibility) and kept as a lightweight top-bar entry point until then.
