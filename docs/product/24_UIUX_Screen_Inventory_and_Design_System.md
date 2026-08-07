# Document 24 — UI/UX Screen Inventory & Design System

*(Renumbered and updated from Document 11/12 for the Python/FastAPI backend architecture and single-developer/AI-assisted delivery model — see Document 00 for the full document map.)*

---

## 1. Design Principles for This Product

An HRMS is used daily by people who did not choose it and are not enthusiastic about it. The design
job is not delight — it is **removing friction from obligations**.

| # | Principle | What it means in practice |
|---|---|---|
| D1 | **Density where experts work, simplicity where employees work.** | HR screens are tables with 12 columns, filters and bulk actions. Employee screens have one action per card. Do not force one aesthetic across both. |
| D2 | **Show the answer, not the data.** | "You have 8.5 casual leave days" beats a ledger table. The ledger is one tap away for the person who wants it. |
| D3 | **Never let someone submit something that will be rejected.** | Validate balances, policy limits and overlaps *before* submission, and explain the number (see `POST /leave/calculate-days`). |
| D4 | **Every number is explainable.** | Any computed figure — leave balance, net pay, worked hours, LOP days — has a tap-through breakdown. This single behaviour eliminates most HR support tickets. |
| D5 | **Destructive and irreversible actions look different.** | Payroll finalise, exit confirmation and data deletion get a distinct treatment, a typed confirmation, and a plain statement of consequences. |
| D6 | **The mobile app is not the web app shrunk.** | Mobile handles punch, leave, approvals, payslip, directory. Everything else is web. |
| D7 | **Speed is a feature.** | A manager approving 20 requests should never wait. Optimistic UI with rollback on failure. |
| D8 | **Empty states teach.** | A first-time HR user opening Payroll should see what to set up and why, not a blank table. |

### 1.1 Interface Copy Rules

Words are design material. Applied to this product:

- **Name things as people control them, not as the system stores them.** "Attendance" not
  "Attendance day record". "My leave" not "Leave application entity".
- **Buttons state what happens:** "Apply for leave", "Approve request", "Finalise March payroll" —
  never "Submit", "OK", "Confirm" alone.
- **An action keeps its name through the whole flow.** The button says "Publish payslips"; the
  toast says "Payslips published"; the audit entry says "Published payslips".
- **Errors say what happened and what to do.** Not "Validation failed" but "You have 2.5 casual
  leave days. Reduce this request to 2.5 days or choose a different leave type."
- **Empty states invite action.** Not "No records found" but "No pay runs yet. Set up salary
  components first — then you can run payroll for March."
- **No apologies, no filler.** Errors are direct and unemotional. Nothing says "Oops!"
- **Sentence case throughout.** Plain verbs. One job per element.

### 1.2 Visual Direction

The brief does not pin down a visual identity, so it must be chosen deliberately rather than
defaulted. Direction to develop in Sprint 0:

- **Palette:** one restrained neutral scale for the vast quantity of tabular UI, one confident
  brand hue reserved for primary actions, and a semantic set (approved / pending / rejected /
  absent / on-leave / holiday) that is legible **without relying on colour alone** — attendance
  calendars must carry pattern or glyph as well as hue, both for accessibility and for
  photocopied printouts, which HR teams genuinely still use.
- **Typography:** a body face optimised for numerals and tabular alignment (payroll and attendance
  are number-dense; lining tabular figures are non-negotiable), paired with a distinct display face
  used sparingly in headers and empty states. Avoid the default system-font-everywhere look — this
  product will sit beside competitors that all look identical.
- **Signature element:** the **attendance calendar and the payslip breakdown** are the two screens
  employees see most and screenshot most. These are where the product earns its identity. Invest
  disproportionate design effort there rather than spreading polish evenly.
- **Restraint:** motion limited to state transitions and loading; no ambient animation. This is a
  tool people open forty times a month.

Deliverable from Sprint 0: a design token file (colour, type scale, spacing, radius, elevation,
motion) plus a component library in Figma, mirrored in code.

---

## 2. Information Architecture

### 2.1 Web — HR / Admin
```
Dashboard
Employees ─ Directory · Add employee · Org chart · Bulk import · Letters · Confirmations
Recruitment ─ Requisitions · Job openings · Candidates · Interviews · Offers · Careers page · Analytics
Attendance ─ Today · Calendar · Matrix · Regularisations · Overtime · Shifts · Rosters · Devices · Lock period
Leave ─ Applications · Balances · Leave types · Policies · Holidays · Year-end
Payroll ─ Pay runs · Salary components · Structures · Statutory setup · Payslips · Loans · Tax · Reports · F&F
Onboarding ─ Joiners · Templates · Tasks · Document verification
Exit ─ Resignations · Clearance · Exit interviews · F&F · Analytics
Performance ─ Cycles · Goals · Reviews · Calibration · PIP
Reports ─ Standard · Custom · Scheduled · Compliance calendar
Settings ─ Company · Entities · Branches · Departments · Designations · Grades ·
           Roles & permissions · Users · Workflows · Notification templates ·
           Custom fields · Integrations · Audit log
```

### 2.2 Web — Employee (ESS)
```
Home · My attendance · My leave · My payslips · My tax · My profile ·
My documents · My team (if manager) · Approvals (if manager) · Directory · Policies · Helpdesk
```

### 2.3 Mobile (bottom navigation, five items maximum)
```
[ Home ] [ Attendance ] [ Punch ⏱ ] [ Approvals ] [ More ]
```
The punch button is centre, elevated and always one tap from anywhere. For a field worker in
logistics or construction, this is the entire product.

---

## 3. Screen Inventory

Approximately **185 screens** in Phase 1. Counted here for estimation purposes; each row is a
distinct design and build item.

### 3.1 Authentication & Onboarding to the Platform (12)
Login · Mobile OTP · MFA challenge · MFA enrolment · Forgot password · Reset password ·
Company selector · First-login password change · Invitation acceptance · Session management ·
Company registration wizard (5 steps) · Setup checklist

### 3.2 Dashboards (6)
Company Admin · HR · Manager · Employee · Finance · Recruiter

### 3.3 Employee Management (24)
Directory (table + card view) · Filters panel · Employee 360° (9 tabs: Profile, Job, Compensation,
Attendance, Leave, Documents, Assets, Performance, Timeline) · Add employee (4-step wizard) ·
Edit employee · Transfer · Promotion · Salary revision · Confirmation · Document upload ·
Document verification queue · Bulk import (upload → validate → preview → commit, 4 screens) ·
Import history · Letter generation · Letter templates · Org chart · Profile change requests ·
Employee export

### 3.4 Attendance (22)
Today's overview · Attendance matrix · Employee calendar · Day detail with punch timeline ·
Manual mark/override · Regularisation list · Regularisation request form · Regularisation approval ·
OT requests list · OT request form · Shift list · Shift form · Roster calendar · Roster bulk assign ·
Roster pattern generator · Device list · Device detail & health · Device employee mapping ·
Geofence list · Geofence map editor · Lock period · Attendance exceptions queue

### 3.5 Leave (16)
My leave · Apply leave · Leave detail · Balance statement (ledger) · Team calendar ·
Applications list (HR) · Application detail & approval · Leave types list · Leave type form ·
Leave policy list · Leave policy form · Holiday calendar · Holiday form · Accrual run ·
Year-end processing (preview + commit) · Comp-off ledger

### 3.6 Payroll (30)
Pay run list · Create pay run · Pay run detail with step progress · Input review ·
Validation report · Variance report · Variance acknowledgement · Employee payslip preview ·
Approve run · Finalise confirmation · Payslip list · Payslip detail (with the breakdown drawer) ·
Bank advice generation · Statutory file generation · Journal voucher · Salary component list ·
Salary component form (with formula builder) · Formula builder modal · Salary structure list ·
Salary structure form · CTC breakup calculator · Statutory master (PF/ESI/PT/TDS/LWF, 5 screens) ·
Loan list · Loan form · Loan schedule · Tax declaration form · Tax proof submission ·
Tax computation view · Regime comparison · F&F settlement

### 3.7 Recruitment (26)
Requisition list · Requisition form · Requisition approval · Job opening list · Job opening form ·
Job opening detail · Careers page (public) · Job detail (public) · Application form (public) ·
Candidate list · Candidate profile · Resume viewer with parsed-field overlay · Bulk resume upload ·
Application kanban · Application detail · Stage move modal · Bulk reject · Interview calendar ·
Schedule interview · Interview detail · Feedback form · Scorecard summary · Offer list ·
Offer form with CTC breakup · Offer approval · Offer acceptance (public, candidate)

### 3.8 Onboarding & Exit (18)
Joiner list · Onboarding detail with task board · Task detail · Template list · Template form ·
Pre-boarding portal (candidate, 4 steps) · Document verification · Induction schedule ·
No-show handling · Resignation form · Resignation approval · Exit list · Exit detail ·
Clearance checklist · Clearance item completion · Exit interview form · Exit document issue ·
Attrition analytics

### 3.9 Workflow, Approvals & Notifications (12)
Unified approval inbox · Approval detail (per entity type, 6 variants) · Bulk approve ·
Workflow definition list · Workflow visual builder · Workflow simulator · Delegation ·
Notification inbox · Notification preferences · Notification template list · Template editor

### 3.10 Reports & Settings (19)
Report catalogue · Report viewer (generic, parameterised) · Report builder · Scheduled reports ·
Compliance calendar · Export job list · Company settings · Legal entity list/form ·
Branch list/form (with map) · Department tree · Designation list · Grade list · User list ·
Role list · Role editor with permission matrix · Custom fields · Integration list ·
Integration configuration · Audit log viewer

---

## 4. Key Screen Specifications

### 4.1 Employee 360° Profile
The single most-used HR screen. Gets a persistent header (photo, name, code, designation,
department, manager, status, quick actions) with tabbed content below. Tabs load lazily.
Permission-gated tabs (Compensation) are **absent**, not disabled-and-visible — showing a locked
tab tells the user something exists that they cannot see, which invites social-engineering
requests to HR.

**Quick actions in the header:** Apply leave on behalf · Mark attendance · Generate letter ·
Initiate transfer · Initiate exit · View audit trail.

### 4.2 Attendance Matrix
Employees down, dates across, one cell per employee-day. The screen HR lives in during payroll week.

- Sticky first column and header row; virtualised rows for 1,000+ employees
- Cell shows a status glyph + colour; hover/tap reveals in/out times, hours, shift, and any flags
- Inline edit for permitted roles, with a mandatory reason
- Filters: department, branch, shift, status, exception type
- Bulk actions: mark present, mark on-duty, apply shift, regularise
- Legend always visible; print stylesheet that keeps status legible in greyscale
- Column footer: per-day present/absent counts; row footer: per-employee monthly totals

### 4.3 Payslip
Two audiences with different needs on one artefact.

- **Employee view:** net pay large and first; earnings and deductions as two clean columns;
  every line tappable to reveal the calculation trace (D4); YTD toggle; download PDF; "Something
  looks wrong?" opens a helpdesk ticket pre-filled with the payslip reference
- **PDF:** company-branded, statutory-compliant layout, password-protected, printable in one page
- The tap-to-explain behaviour on every line is the feature that stops the "why is my salary less
  this month" ticket at source. Build it properly.

### 4.4 Pay Run Wizard
A linear, gated flow with a persistent step indicator: Select period → Review inputs →
Compute (progress) → Validation report → Variance report → Approve → Finalise.

- The user cannot skip a step; exceptions must be acknowledged before advancing
- The finalise screen states plainly what becomes irreversible and requires typing the period name
- Progress during compute shows employees processed, ETA and a live error count
- If compute fails, the screen shows what failed, for which employees, and offers a resume action

### 4.5 Manager Approval Inbox (mobile-first)
- One list, all entity types, sorted by urgency (SLA proximity)
- Each card shows requester photo/name, request summary, and the **one number the approver needs**
  (days remaining, balance after, amount, team coverage that day)
- Swipe to approve, swipe to reject (reject opens the mandatory comment sheet)
- Bulk select for leave and regularisation only
- Optimistic UI: the card animates away immediately; a failure restores it with an explanation

### 4.6 Punch Screen (mobile)
- Opens to a single large button whose label states the next action: "Punch in" / "Punch out"
- Above it: shift timing, current status, hours worked today
- Below: this week at a glance
- On tap: acquire location → validate geofence → capture selfie if required → submit → confirm with
  the recorded time and any flag (late by 12 minutes)
- Offline: the button still works, the punch queues, and the UI says so explicitly — "Saved.
  Will sync when you're back online." Never a silent failure and never a spinner that hangs.

### 4.7 Leave Application
- Type → dates → the **day-count preview appears immediately** showing which dates count and why
  (holiday, weekly off, sandwich rule), balance before and after, and who will approve it
- Blocking issues are shown before the submit button is enabled, with the fix stated
- Attachment prompt appears only when the policy requires one, with the threshold explained

---

## 5. Component Library

**Foundations:** colour tokens, type scale, spacing scale (4 px base), radius, elevation, motion
durations, breakpoints, iconography.

**Components (build once, use everywhere):**
Button (primary/secondary/ghost/danger) · Input, Select, Multi-select, Date picker, Date-range
picker, Time picker, File upload · Form field with label/help/error · Data table (sort, filter,
column chooser, pagination, virtualisation, bulk select, export) · Filter panel · Search ·
Card · Tabs · Accordion · Modal · Drawer · Toast · Inline alert · Confirmation dialog ·
Empty state · Loading skeleton · Error boundary · Avatar · Badge/status pill · Progress bar ·
Stepper · Breadcrumb · Pagination · Tooltip · Popover · Calendar · Timeline · Org chart node ·
Approval card · Money display (with currency and minor-unit handling) · Employee picker ·
Permission-gated wrapper.

**Rule:** any component built twice in two modules is a design-system failure. Weekly component
review during the build phase.

---

## 6. Responsive Behaviour

| Breakpoint | Behaviour |
|---|---|
| < 640 px | Mobile app patterns; admin screens are read-only or redirect to "Open on desktop" |
| 640–1024 px | Tablet: two-column forms collapse to one; tables scroll horizontally with sticky first column |
| 1024–1440 px | Standard desktop; primary target for HR/admin |
| > 1440 px | Wider tables, more columns visible; no max-width stretching of dense data screens |

HR admin screens are explicitly **desktop-first**. Attempting full admin functionality on a phone
produces a worse experience on both. This decision should be made explicit early — it will otherwise
surface as a late "can we do payroll on mobile?" request.

---

## 7. Design Deliverables & Process

| Deliverable | When |
|---|---|
| Design tokens + component library (Figma + code) | Sprint 0–1 |
| Wireframes for Phase 1 flows | Sprint 0–2 |
| High-fidelity screens, module by module | One sprint ahead of the build |
| Interactive prototype for the 6 core flows | Before UAT |
| Accessibility annotations (focus order, labels, roles) | With each screen set |
| Design QA checklist | Per module |
| Style guide + copy guide handed to engineering | Sprint 2 |

**Core flows to prototype and usability-test before building** (5 users each, 3 of them actual HR
practitioners):
1. Employee applies for leave on mobile
2. Manager approves five mixed requests on mobile
3. HR runs monthly payroll end to end
4. HR onboards a new joiner from offer to day one
5. Recruiter moves a candidate from application to offer
6. Employee punches in at a site with poor connectivity

Usability testing here costs a week and saves months. The payroll flow in particular is where a
misunderstanding becomes a production incident with real money attached.
