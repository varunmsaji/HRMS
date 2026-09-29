# HRMS Screen Atlas

**Purpose:** a structural catalogue of every screen in the HRMS web app — what each one shows, what
a user can do on it, and how the pieces relate — written so a design agent can restyle the product
without reading the codebase.

**Relationship to the rest of `docs/design/`:** the existing `00_UI_Vision.md` –
`04_User_Personas.md` set and `screens/01_Employee_List_Directory.md` describe a broader,
partly-aspirational product vision (org chart, bulk import/export toolbar actions, a "360° profile,"
etc.) that doesn't fully match what's built today. This document is different in kind: it is a
1:1 transcription of the **current, working** `/app/*` routes, compiled directly from the frontend
source in `apps/web/src/app` and `apps/web/src/components`. Where the two disagree, treat this
atlas as authoritative for "what exists today," and the other docs as "where the product may be
headed."

## How to use this document

**This is a visual redesign brief, not a rebuild.** Every route, field, label, table column, button
and workflow below already exists and works in production. Nothing here is a proposal — it's a
transcription of the current app. The job for whoever (or whatever) reads this is to give it a
considered visual identity — color, type, spacing, elevation, iconography, micro-interaction — while
keeping the information architecture, navigation structure, field names and flows exactly as
described.

Screens are grouped by module. Five recurring structural patterns (list, detail,
policy-versioning, approval-workflow, effective-dated-record) cover roughly 40 of the ~55 screens —
read [Recurring screen patterns](#recurring-screen-patterns) first, then treat each screen entry as
"follows Pattern X, plus these specifics" rather than a one-off layout.

Status colors named below (warning/success/danger/info/outline/secondary) are **semantic
categories** used consistently across the whole app, not literal hex values to copy — map them to
whatever palette you choose, but keep the mapping consistent everywhere a given semantic appears.

---

## App shell & navigation

Every authenticated screen (everything except the six auth screens and the public onboarding
wizard) renders inside one persistent shell.

### Shell structure

Desktop (≥1024px): a fixed **240px left sidebar** (app wordmark/logo at top, primary nav below)
plus a **56px top bar** spanning the remaining width, holding a company-context indicator (left)
and a user menu (right — avatar/name → account actions, sign out). Content area is a centered
column, max-width ~1280px, with generous outer padding (16–32px depending on breakpoint).

Below 1024px: the sidebar collapses entirely; a hamburger button in the top bar opens it as a
slide-over drawer.

### Primary sidebar navigation

13 items, always visible — items the current build doesn't support are simply absent, not disabled:

1. Dashboard
2. My Profile *(only shown to users with a linked employee record)*
3. My Payslips *(same condition)*
4. Employees
5. Onboarding
6. Shift Rosters
7. Attendance
8. Regularizations
9. Overtime
10. Leave
11. Leave Balances
12. Payroll
13. Settings *(also highlights as active while on any settings sub-page)*

### Settings hub — six groups

Reached via the "Settings" nav item, not shown directly in the sidebar:

| Organisation | Attendance & Time | Leave | Payroll | Policies | Administration |
|---|---|---|---|---|---|
| Company | Shifts | Leave Types | Salary Components | Policy Assignments | Setup |
| Branches | Attendance Periods | Leave Policies | Salary Structures | Policy Resolution | Users |
| Departments | Work Calendars | Leave Combination Rules | Statutory Rates | | |
| Designations | Holiday Calendars | Leave Year | | | |
| Grades | Weekly-Off Patterns | Statutory Minimums | | | |
| | Attendance Policies | | | | |
| | Overtime Policies | | | | |
| | Regularization Policies | | | | |

This two-tier structure (13 "day-to-day" items directly in the sidebar; ~26 "configuration" items
tucked behind a Settings hub of six grouped cards) is deliberate — it's the single biggest IA
signal for how to prioritize visual weight: primary nav items deserve prominent icons and generous
tap targets, Settings-hub items can be denser, list-style rows.

---

## Shared UI primitives

A small set of components composes literally every screen in the app. Restyling these well
automatically restyles ~90% of the product.

**Page header** — every screen opens with: page title (h1) + optional one-line description, and
right-aligned primary action button(s). On detail pages, a "← Back to [list]" link sits above it.

**The four-state content shell** — every data-bearing screen is one of: **Loading** (centered
spinner + label) · **Error** (icon, "Something went wrong" or a specific 403/404 message, "Try
again" button) · **Empty** (icon, title, one-line description, optional CTA button — every module
has its own icon and copy) · **Content** (table or list). Design all four as one coherent family,
not as after-thoughts.

**Status badges** — semantic vocabulary used everywhere:

| Semantic | Meaning |
|---|---|
| Warning | pending / submitted / draft-attention |
| Success | approved / active / published / current |
| Danger | rejected / blocked / error |
| Info | informational flag (overtime, locked, on-duty) |
| Outline | cancelled / inactive / ended / historical |
| Secondary | neutral current-state marker |

**Tables vs. simple lists** — screens with multiple sortable/filterable columns (Attendance,
Attendance Periods, Regularizations, Overtime, Rosters, Leave Applications, Employees, Policy
Assignments, Pay Runs) use a bordered, scrollable `<table>` with an uppercase, muted-background
header row and hover highlight per row. Reference/identity lists (policy families, Shifts,
Weekly-Off Patterns, Work/Holiday Calendars, Leave Policies, Users) use a simpler divided `<ul>` of
full-row links — title left, one status badge right.

**Forms & dialogs** — create/edit actions open in modal dialogs for short forms, or swap the detail
page's read-only view (definition-list style, label/value pairs) into an inline edit form for
longer ones — there is no separate "edit page" route anywhere in the app. Fields are grouped into
labelled sections (e.g. "Identity", "Address", "Compensation band") with 2-column grids on wide
screens collapsing to 1 column on mobile. Required fields carry an asterisk; validation errors
render inline beneath the field.

**Money, dates, pagination** — all currency is right-aligned with tabular figures, formatted with
the currency symbol (₹ for INR). Server-paginated tables show a "Showing X–Y of Z" caption with
Previous/Next controls. Optimistic-concurrency conflicts (two people editing the same record) show
an inline warning banner with "Reload latest" / "Cancel" actions — design this as a distinct,
noticeable-but-not-alarming inline state, not a modal interruption.

---

## Recurring screen patterns

Five shapes account for most of the app. Each screen entry later in this document references one
of these by letter.

### Pattern A — Simple reference list + detail

No versioning — what you see is what's live. Used by Legal Entities, Branches, Departments,
Designations, Grades, Weekly-Off Patterns, Work Calendars, Holiday Calendars.

1. List: rows link to detail, one status badge each, "Add" button opens a create dialog with the
   same fields as the edit form.
2. Detail: header actions (Edit, Deactivate/Reactivate); read view is a sectioned definition list;
   Edit swaps it for the same sectioned form inline.
3. Deactivation is sometimes blocked (e.g. a branch with active departments) with a specific toast
   explaining why.

### Pattern B — Policy list → versioned detail

The app's most complex recurring shape. Used by Attendance Policies, Overtime Policies,
Regularization Policies, Leave Policies, and Shifts (schedule instead of "policy").

1. List: identity-only rows (name + code + active badge). "Add" only captures name/code — the
   actual rules are configured after creation.
2. Detail has two tabs: **Overview** (identity, active/inactive) and **Versions**.
3. Versions tab stacks three cards: *Currently published* (read-only, what's live today), *Draft*
   (an editable long rules form with Save draft / Publish / Discard actions), *History* (past
   superseded versions with their effective date ranges).
4. Publishing opens a confirm dialog (optional reason) — publishing closes the previous version and
   is immutable once done.

### Pattern C — Approval workflow

Used by Regularizations, Overtime, Leave Applications — near-identical anatomy across all three.

1. List: a "My / Team" toggle (Team only for approvers), a filter card (date range, status, type,
   employee), a table with a Status badge and Stage column.
2. Detail: status badges row → primary-facts card → domain-specific breakdown card (e.g. requested
   punch correction, day-by-day leave breakdown) → review card (reviewer comment, rejection reason)
   → append-only activity timeline.
3. Approve/Reject open a small dialog; reject always requires a reason, approve sometimes has
   special-case sub-flows (e.g. leave balance shortfall offers "approve as loss-of-pay").

### Pattern D — Effective-dated record

Used across five tabs of the Employee profile (Employment, Assignment, Compensation, Statutory,
Banking) and Salary.

1. "Current" card showing today's values plus an effective-date badge.
2. "History" list of past periods, each with its own date range.
3. "Record a change/revision" button opens a dialog capturing new values + effective date +
   (usually required) reason — old values are never edited in place, only superseded.

### Pattern E — Tiny master-data list

Used by Leave Types, Leave Combination Rules, Statutory Leave Minimums. No detail route at all —
rows open a small edit dialog directly, or are simply removed and recreated rather than edited.

---

## Module: Auth & Access

Six standalone screens, all sharing one minimal-chrome shell: a centered card (max ~420px wide)
with a wordmark-only header — no sidebar, no nav. This is the one part of the app that should feel
calm and uncluttered rather than dense.

### Login — `/login`

**Purpose:** any user signs in with email and password.

- **Fields:** `Email`; `Password` (show/hide toggle)
- **Actions:** Sign in (primary); Forgot password? (link); Register (footer link)
- **States:** invalid credentials / account locked / rate-limited — distinct error banners;
  unverified email — amber banner + "Resend verification email" button; submitting — button shows
  "Signing in…"

### Register — `/register`

**Purpose:** a prospective customer creates a brand-new company workspace and its first admin
account.

- **Fields — Company details:** `Company name*`; `Industry`; `Country code` + `Currency` (2-up);
  `Timezone` + `Financial year starts` (2-up); `Company size`
- **Fields — Admin account:** `First name` + `Last name` (2-up); `Work email*`; `Password*` — "at
  least 8 characters, with a letter and a digit"; `Confirm password*`
- **States:** two fieldsets, grouped under legends; field-level errors map onto every field above;
  duplicate-email case highlights admin email specifically; submitting: "Creating your
  workspace…"

### Forgot password — `/forgot-password`

**Purpose:** requests a password-reset email.

- **Fields:** `Email*`
- **Actions:** Send reset link
- **States:** success replaces the whole card with a "Check your email" confirmation —
  deliberately identical whether or not the account exists

### Reset password — `/reset-password/[token]`

**Purpose:** sets a new password from an emailed link.

- **Fields:** `New password*`; `Confirm password*`
- **States:** expired/invalid token → explanatory error, prompts a new request; success screen:
  "Password updated" + "Go to sign in" button

### Verify email — `/verify-email/[token]`

**Purpose:** auto-confirms an email address the moment the link is opened — no form.

- **States (3-state machine):** Verifying — "One moment…"; Success — checkmark, "Email verified",
  CTA to sign in; Error — expired/invalid message, link to request a new one

### Accept invite — `/accept-invite/[token]`

**Purpose:** a user invited into an existing company accepts — either authenticating an existing
account or creating a new one.

- **Fields — new account:** `First/Last name`; `Password*` + `Confirm*`
- **Fields — existing account:** only `Password*` ("your existing account password")
- **States:** full-page loading while invite resolves; "Invite not available" terminal screen
  (expired/revoked); title/description show the inviting company name and invitee email
  dynamically

---

## Module: Onboarding

Two audiences, three screens: the candidate fills a public multi-step wizard (no login), HR reviews
and activates the case in the authenticated app.

### Public onboarding wizard — `/onboarding/[token]`

**Purpose:** the candidate, with no account, self-fills their own employee record data via a
token-authenticated link HR sends them. Progress autosaves per step.

**Layout:** minimal header (wordmark only) + centered card. Inside: a progress header ("Step X of
12" + "Y% complete" + a progress bar), a step heading (icon + title + one-line description), the
step's fields, then Back / Continue (or Save & Continue) buttons. Footer: "Having trouble? Contact
your HR team."

**Per-step verification banner:** each data step can show a green "Verified by HR — no changes
needed" banner, or a red "HR requested changes: {reason}" banner, depending on HR's review status
for that section.

**Notable:** the review step (last, before submit) is an editable summary — one row per section
with a computed one-line recap and an Edit (pencil) button jumping back to that step, not a static
printout.

**Steps:**

1. **Welcome** — no fields; a checklist of what to have ready (bank details, PF/ESI info, photo
   ID) + "~10 minutes" note + "Get started".
2. **Personal info** — First/Middle/Last name, Date of birth, Gender, Blood group, Marital status,
   Nationality, Father's/husband's name, PAN number, Aadhaar number. 2-column grid.
3. **Address** — Present address (line 1/2, city, state, pincode, country) + a "Same as present"
   checkbox that conditionally reveals a mirrored Permanent address block.
4. **Emergency contact** — Contact name*, Relationship, Phone number*.
5. **Bank details** — Payment mode*, Account holder name, Account number (masked input), Bank
   name, IFSC, Branch name.
6. **Statutory details** — Tax regime*. Provident Fund section (PF applicable / opted-out-of-ceiling
   checkboxes, PF number, UAN, VPF amount/%). ESI & LWF section (checkboxes + ESI IP number, PT
   state code). Other (Is a director / International worker checkboxes).
7. **Compensation** — Annual CTC*, Currency*.
8. **Previous employment** — repeatable rows ("Add employer", zero allowed for freshers): Company
   name*, Designation, From/To dates, Last drawn CTC, Reason for leaving; a "PF member here"
   checkbox conditionally reveals UAN/PF number/ESI number for that employer.
9. **Education** — repeatable rows: Qualification*, Institution, Year of passing.
10. **Nominees & family** — repeatable rows: Name*, Relationship*, DOB, Gender, Aadhaar +
    Minor/PF-nominee/Gratuity-nominee/ESI-family checkboxes; Minor conditionally reveals Guardian
    name/relationship; PF-or-Gratuity-nominee reveals share % fields. A running total banner shows
    "PF nominee share: X% of 100% allocated" (and same for Gratuity), turning to a danger state past
    100%.
11. **Documents** — list of uploaded docs (type, filename, size, remove) + an upload row (Document
    type select, File picker, Upload button).
12. **Review & submit** — one summary row per prior section with an Edit shortcut, then a final
    Submit button.

### Onboarding cases (admin) — `/app/onboarding`

**Purpose:** HR's list of every onboarding case they've started, with a way to start a new one.

- **Table columns:** Candidate (links to detail); Personal email; Proposed joining date; Status
  badge
- **"Start onboarding" dialog:** Candidate — First name*, Last name, Personal email*, Personal
  mobile; Proposed placement — Joining date*, Branch, Department, Designation (all pre-set by HR,
  never chosen by the candidate)
- **Status badges:** Draft/Expired/Cancelled — outline; Invited/In progress — info;
  Submitted/Under review — warning; Changes requested — danger; Verified/Activated — success

### Onboarding case review — `/app/onboarding/[id]`

**Purpose:** HR reviews everything a candidate submitted, section by section, verifies or rejects
each one and each document, then activates the case into a real employee record.

**Layout:** a status card (candidate/placement facts + contextual action button + invite-link
banner) followed by one card per onboarding section (Personal, Address, Emergency, Bank,
Statutory, Compensation, Previous Employment, Education, Nominee), each independently
verify/reject-able, plus a Documents card.

- **Status-card actions (contextual):** Send/Resend Invite / Get Link — reveals a copyable
  invite-link banner; Request Changes — only once under review with ≥1 rejected item; Activate —
  only once fully verified, creates the employee record; "View employee record →" once activated
- **Per-section & per-document:** Verify — immediate; Reject — opens a small dialog, reason
  required
- **Notable:** section cards render whatever fields exist as generic label/value pairs
  (auto-titleized from snake_case) — the layout needs to gracefully handle a variable,
  sometimes-long number of rows per card, and array-shaped sections (previous employment,
  education, nominees) render one bordered sub-card per item.

---

## Module: Home & Setup

### Dashboard — `/app/dashboard`

**Purpose:** company-level landing page: snapshot of setup status, org size, subscription.

**Layout:** conditional setup-progress banner (green "Setup complete", or a progress bar if not) →
a 5-tile stat grid → two cards side by side.

- **Stat tiles:** Employees; Branches; Departments; Seat limit; Plan
- **Subscription card:** Plan name/code, Status badge, Trial ends, Seat limit; Feature list — code,
  on/off icon, source, limit value
- **Company card:** Initials avatar, name, id, status badge; Branches / Departments / Employees
  counts

### Company profile — `/app/company` — *Pattern A*

**Purpose:** the org's registered/contact/locale/branding profile.

- **Sections:** Basic info — name*, legal name, registration no., industry, size, country,
  currency (locked post-trial), timezone; Contact — email, phone, website; Address — line 1/2,
  city, state, postal code, country; Localization — language, date format, fiscal year start;
  Working schedule — 7 day-of-week checkboxes; Business hours — start/end (HH:mm); Branding —
  logo URL, primary color
- **Read-only metadata:** Status badge, Version, Subdomain, Onboarded at, Trial ends at

### Setup checklist — `/app/setup`

**Purpose:** tracks completion of company-onboarding steps — a checklist, not an editor.

**Layout:** a status badge ("Setup complete" or "N of M complete") in the header, an optional
"Next step" callout (label + description + CTA to that step), then the step list itself as a
read-only checklist.

---

## Module: Organisation

Five screens sharing Pattern A exactly — described once above, only distinguishing fields given
per screen below. Plus Users & roles and the Settings hub itself.

### Legal entities — `/app/legal-entities` — *Pattern A*

**Purpose:** the legally registered companies that actually employ people — top of the org chain.

- **Fields:** Identity — Legal entity name*, Registered address; Statutory IDs — PAN, GSTIN, TAN,
  CIN, PF establishment code, ESI code, LWF registration; Authorized signatory — name, designation
- **Notable:** deactivation is blocked if the entity still has active branches, with a specific
  explanatory toast.

### Branches — `/app/branches` — *Pattern A*

**Purpose:** physical work locations under a legal entity.

- **Fields:** Identity — Legal entity, Branch name*, Branch code; Address — line 1/2, city, state,
  PIN, timezone (default "inherit from company"); Geofence (optional, for future attendance
  enforcement) — latitude, longitude, radius
- **Notable:** first-run quick-setup — if zero legal entities exist yet, the empty state offers a
  mini "Get started" flow that silently creates one (just a name) before reopening Add Branch —
  avoids sending a first-time user on a detour.

### Departments — `/app/departments` — *Pattern A*

**Purpose:** org units, optionally nested and optionally scoped to a branch.

- **Fields:** Identity — Department name*, code; Hierarchy — Branch, Parent department
  (self/descendants excluded when editing); Leadership — Department head (employee picker; drives
  Leave's HOD-approval stage)

### Designations — `/app/designations` — *Pattern A*

**Purpose:** job titles, optionally scoped to a department and a compensation grade.

- **Fields:** Identity — Designation title*, code; Department & grade — both optional selects

### Grades — `/app/grades` — *Pattern A*

**Purpose:** compensation grades/bands referenced by designations.

- **Fields:** Identity — Grade code*, name*, Level; Compensation band — Min CTC, Max CTC, Approval
  limit; Overrides — Notice period (days), Probation (days)

### Users & roles — `/app/users`

**Purpose:** who has login access, and what roles they hold.

- **List:** simple divided rows — name (+ "Primary" badge where relevant), email, wrapped role
  badges ("No roles" outline badge if empty), "Manage roles" button
- **Dialogs:** Invite user — Email*, Role* (Company Admin / HR Admin / Reporting Manager / Branch
  Manager / Employee); Manage roles — checkbox list of the same five roles
- **Notable:** both Invite and Manage-roles controls are permission-gated by *disappearing
  entirely*, not by disabling — consistent with the rest of the app's convention.

### Settings hub — `/app/settings`

Pure navigation — a responsive grid of six cards (one per group listed in App shell & navigation
above), each a vertical list of icon+label links into a config screen. No data of its own.

---

## Module: Employee

Three screens: a directory, the full HR-facing profile (8 tabs), and its self-service mirror (7
tabs, same components, view-oriented). Design the profile's tab system and its five Pattern-D
sub-tabs first — nearly a third of the app's total surface area lives here.

### Employee directory — `/app/employees`

**Purpose:** company-wide employee list for HR/admins.

- **Table columns:** Employee (name, links to profile); Code; Personal email; Personal mobile;
  Status badge; Active/Inactive badge
- **Actions:** Add Employee (dialog capturing just first name + personal email; everything else is
  added afterward on the profile) → redirects straight to the new profile, toasts the generated
  employee code
- **States:** server-side pagination; seat-limit-exceeded toast on create

### Employee profile — `/app/employees/[id]`

**Purpose:** one employee's complete record — the HR/admin working view.

- **Header:** name/code title, status badges (employment status + active/inactive); action buttons
  — Confirm (probation → active), Invite, Deactivate/Reactivate, Edit — each independently
  permission-gated
- **8 tabs:** Overview, Employment, Assignment, Compensation, Salary, Statutory, Banking,
  Attendance

**Overview** — two cards: Identity (code, name, DOB, gender, marital status, blood group,
nationality, personal email/mobile) and Current work information (employment status, legal entity,
department, designation, branch, reporting manager, shift, work location — with a nudge to the
Employment tab if empty).

**Employment** *(Pattern D)* — Current: legal entity, joining date, probation end date, pay basis,
status. Actions: Hire/Rehire, Edit, Terminate (destructive, requires last working day + irreversible
warning). History: past employment episodes.

**Assignment** *(Pattern D)* — Current: branch, department, designation, grade, reporting manager,
shift, work location, effective from. "Record a change" dialog covers Transfer / Promotion /
Manager change / Shift change (gated by separate Transfer vs. Promote permissions) — placement,
reporting, and shift fields, each "blank = no change."

**Compensation** *(Pattern D)* — Current: Annual CTC, revision type, effective from, reason.
Revision dialog requires all fields fresh every time (CTC, currency, revision type, reason —
nothing carries forward).

**Salary** — a "Salary as of" date picker + a full CTC breakup table (component / monthly / annual,
gross + employer-contribution + cost-to-company totals) driven by whichever salary structure or
daily rate is assigned. "Assign salary" dialog picks structure-vs-daily-rate, separate from editing
CTC itself (done on Compensation).

**Statutory** *(Pattern D, sensitive)* — visible only with a specific permission (shown via an
explicit banner). Current: tax regime, PF/ESI/LWF applicability + numbers, director/international-
worker flags. Revision dialog mirrors the onboarding wizard's statutory step almost exactly.

**Banking** *(Pattern D, sensitive)* — account numbers always masked, even to admins ("visible
only to the employee and permission-holders"). Verification status badge. Revision dialog: account
number field never shows its full value again once saved.

**Attendance** — embeds the employee-scoped attendance panel (shared with the Attendance module).

> **Not present in the codebase today** — despite being natural to expect: there is no
> Nominee/Dependent, Education, Previous-Employment or Document tab on the employee profile. That
> data only exists inside the onboarding wizard record. Don't add these tabs; it would be a
> functional change, not a visual one.

### My profile (self-service) — `/app/me`

**Purpose:** the same record and the same panels as the Employee profile, scoped to the signed-in
user's own data.

- **Differences from the admin profile:** no Edit / Deactivate / Invite / Confirm buttons —
  view-oriented; 7 tabs, not 8 — no Salary tab; Compensation/Statutory/Banking/Attendance tabs are
  each individually hidden (not just their content) if the viewer lacks the matching view
  permission
- **Distinct empty state:** "No employee record linked to your account" — for user accounts that
  exist but were never linked to an employee record. Worth its own visual treatment; it's a
  different situation from every other empty state in the app.

---

## Module: Attendance & Time

Thirteen screens. Attendance Policies is the fullest example of Pattern B; Regularizations and
Overtime are Pattern C; most of the rest are variations on Pattern A/B.

### Attendance dashboard — `/app/attendance`

**Purpose:** daily/team attendance overview with drill-down and correction actions.

**Layout:** a 7-tile stat grid (Present, Absent, Half day, Weekly-off/Holiday, Missing punch,
Overtime, Config error) → a filter card (date, employee, status, plus three exception checkboxes) →
results table.

- **Table columns:** Employee; Status badge; Calendar day; Worked; OT; Exceptions
- **Actions:** Record punch (dialog)

### Attendance day detail — `/app/attendance/[id]`

**Purpose:** everything about one employee's one day: schedule, punches, overtime, leave overlay,
and the calculation that produced today's status.

- **Badges:** up to a dozen possible flags — Late, Early departure, Overtime, Regularized, Pending
  approval, Worked on holiday/weekly-off, Missing punch, Worked-on-leave decision needed, Core-
  hours breach, On duty, Locked. Design a badge system that scales to several simultaneous flags
  without looking chaotic.
- **Cards:** Schedule; Punches & worked time (+ breaks sub-table); Overtime & pay facts; Leave
  overlay (conditional); Calculation & audit — includes a collapsible raw computation-snapshot JSON
  block, worth a distinct "developer detail" visual treatment
- **Actions:** Regularize, Keep leave (conditional), Recompute (disabled once locked)

### Attendance periods — `/app/attendance-periods`

**Purpose:** open/close/lock a legal entity's monthly attendance — the payroll cutoff boundary.

- **List columns:** Label, Legal entity, Range, Status badge, Last validation
- **Detail:** Period card, conditional Validation card (Ready/Blocked + reasons), per-employee
  Summary table (labelled live-preview vs. frozen), append-only Timeline
- **Header actions (open period):** Calculate attendance, Validate, Finalize & lock (shows blocking
  reasons on failure)
- **Header actions (closed period):** Reopen — destructive, reason required

### Attendance policies — `/app/attendance-policies` — *Pattern B (template)*

**Purpose:** the rules engine for how punches turn into a daily status.

- **Version-form distinguishing fields:** Grace in/out minutes; Missing-punch / missing-shift
  behaviour; Multi-punch mode + duplicate-punch window; Core-hours-breach / split-shift behaviour,
  On-duty-requires-punch; Lates→half-day count, excess-break-days→half-day count, incomplete-at-
  lock behaviour; three tiered-band editors — Hour bands, Late bands, Early-departure bands (each
  row: min/max minutes → status)

### Regularizations — `/app/regularizations` — *Pattern C*

**Purpose:** employee/manager/HR corrections to attendance, submitted for approval.

- **Request dialog:** Employee (if on-behalf), Attendance date, Request type, Correction kind
  (punch times / shift), conditional punch-time or shift fields, Reason, Attachment reference
- **Detail extras:** Requested correction card (shift or punch-times table)

### Regularization policies — `/app/regularization-policies` — *Pattern B*

- **Version-form distinguishing fields:** Approval chain; Who may request — Employee/Manager/HR
  checkboxes; Max backdated days, Max requests/month; Reason required / Attachment required /
  Blocked-when-period-locked checkboxes; Allowed exception types — a checkbox grid

### Overtime — `/app/overtime` — *Pattern C*

**Purpose:** system-detected overtime, routed for approval — there is no manual "submit" flow, only
approve/reject.

- **Table columns:** Date, Employee, Day class, Detected, Approved, Status badge, Approval chain
- **Detail extras:** Rate (classification + multiplier), minutes detected vs. approved, conditional
  comp-off + expiry

### Overtime policies — `/app/overtime-policies` — *Pattern B*

- **Version-form distinguishing fields:** Eligibility, Min OT minutes, Rounding mode/minutes;
  Approval chain, requires-post-approval checkbox, Daily/Weekly/Monthly cap minutes; Comp-off-
  instead-of-pay + expiry days + day-length minutes; Night OT mode + window start/end; Rate rows
  editor — day class / classification / multiplier (repeatable, informational)

### Shifts — `/app/shifts` — *Pattern B variant*

**Purpose:** work schedules — same list→tabs→draft/publish shape as policies, but versioning a
schedule rather than a rule set.

- **Schedule types (drives the rest of the form):** Fixed — start/end time; Flexible — window
  start/end, required minutes, optional core hours; Split — an ordered duty-blocks editor,
  add/reorder/remove, minimum 2 blocks
- **Also in the version form:** Timezone (inherit-from-branch default); Flags — night shift,
  overtime-eligible, operates-on-holidays, operates-on-weekly-off; Weekly-off pattern override;
  Breaks editor — repeatable, fixed-window or flexible-duration, paid/mandatory/allows-split flags

### Rosters (list) — `/app/rosters`

**Purpose:** which shift (or day-off) each employee is rostered for, on which date — list view,
with a link to the calendar view.

- **Table columns:** Date, Employee, Day (shift / week-off / working holiday), Status badge
  (Published/Draft), row actions (Publish/Edit/Remove)

### Roster calendar — `/app/rosters/calendar`

**Purpose:** the one true interactive month-calendar view in the whole app.

**Layout:** employee selector (required) + month prev/next controls + a conditional "Publish N
drafts" button, then a true 7-column × up-to-6-row month grid. Each day cell shows the day number
and, if rostered, a status badge (solid border = published, dashed = draft) labelled "Week off" /
"Holiday working" / the shift name. Leading/trailing days from neighbouring months fill out each
week row.

**Interaction:** clicking a day cell opens a dialog to assign a shift, mark week-off, or mark
working-holiday for that employee/date.

### Weekly-off patterns — `/app/weekly-off-patterns` — *Pattern A*

**Purpose:** rules for which days are an employee's default days off — no draft/publish
versioning, direct edit.

- **Fields:** Pattern name, code, Pattern kind (drives extra fields); repeatable Rules list —
  weekday, conditional occurrence (1st/2nd/…/last), conditional "starting from" date + parity, Off
  amount (full/half day)

### Work calendars — `/app/work-calendars`

**Purpose:** composes a weekly-off pattern with one or more holiday calendars into a single
reference calendar.

- **Detail — 3 tabs:** Overview — composition summary (linked holiday calendars, weekly-off
  pattern, holiday defaults); Exceptions — paginated list + "Add Exception" dialog (date, type,
  name, reason); Day-type lookup — a date input + "Check" button returning the resolved day type
  and applicable flags

### Holiday calendars — `/app/holiday-calendars`

**Purpose:** a named, region-scoped list of holidays.

- **Detail:** one Overview card (kind, state code, holiday count) plus a separate paginated
  Holidays card — each row: name, type, date, active badge, edit/deactivate. "Edit Holiday" locks
  the date field (immutable; must deactivate + recreate to change a date).

---

## Module: Leave

### Leave applications — `/app/leave-applications` — *Pattern C*

**Purpose:** requesting and approving time off.

- **Apply dialog:** Employee (if on-behalf), Leave type, Start/End date, conditional Half-day
  select (single-day only), Reason, Attachment reference, Expected delivery date (maternity,
  informational)
- **Detail extras:** day-by-day breakdown table — date, fraction, half, sandwich-rule flag, pay
  treatment (LOP vs. balance), attendance-sync status
- **Notable — balance shortfall flow:** if an approval would exceed the available balance, the
  review dialog shows a warning panel (available vs. shortfall days) and swaps the primary action
  to "Approve, uncovered days as loss of pay." Worth a distinct visual treatment as a genuine
  decision point, not a generic error.

### Leave balances — `/app/leave-balances`

**Purpose:** current balance per leave type, plus the append-only ledger behind it.

**Layout:** My/Team toggle → Balances table (leave type, available, reserved/pending, conditional
Encash button) → Ledger card (date, type, amount, reason, recorded-at) with pagination.

**Notable:** explicitly append-only — a correction is always a new ledger entry, never an edit to
an old one. The ledger view should read like a statement, not an editable table.

### Leave combination rules — `/app/leave-combination-rules` — *Pattern E*

**Purpose:** which leave types can/can't be taken back-to-back.

- **Fields:** Leave type A, "Combined with" type B, Allowed checkbox, Reason
- **Notable:** "No rule for a pair means allowed" — stated explicitly in the page copy; the design
  should make an empty list read as a deliberate default, not a missing-data state.

### Leave policies — `/app/leave-policies` — *Pattern B*

**Purpose:** the most field-dense of the five policy families.

- **Version-form sections:** Who can submit — self/manager/HR checkboxes; Max backdated days, Max
  requests/month, Approval chain; 7 flags — reason required, attachment required, half-day allowed,
  sandwich rule, reserve-on-submission, allowed-during-probation, accrue-during-probation; Accrual
  — frequency, rate per cycle, max carry-forward, year-end action, encashment-allowed, allow-
  negative-balance (+ floor); Encashment — max days, min balance after, frequency, calculation
  basis; Maternity entitlement — pre/post-delivery day split

### Leave types — `/app/leave-types` — *Pattern E*

- **Fields:** Code (immutable once created), Name; Paid by default / Requires a balance / "Is the
  company's comp-off type" checkboxes; Statutory category — classifies against legal minimums

### Leave year setting — `/app/leave-year-setting`

**Purpose:** one setting, company-wide — structurally the simplest screen in the app.

- **Fields:** Leave year type — Calendar (Jan–Dec) / Financial (Apr–Mar) / Employee anniversary /
  Custom, with conditional start month/day for Custom

### Statutory leave minimums — `/app/statutory-leave-minimums` — *Pattern E*

**Purpose:** legal floors a leave policy can't be published below.

- **Fields:** Leave category, Minimum days/year, State (optional), Establishment type (optional),
  Note

---

## Module: Payroll

The Pay Run detail screen is the single densest, most workflow-heavy screen in the entire app —
give it real design attention.

### Pay runs (list) — `/app/payroll/pay-runs`

- **Table columns:** Month, Legal entity, Status badge, Employees, Net pay (blank until computed),
  Pay date
- **Status badges:** Draft — outline; Inputs locked / Approved — info; Computed — warning;
  Finalised — success; Paid — secondary

### Pay run detail — `/app/payroll/pay-runs/[id]`

**Purpose:** one legal entity's monthly pay run — lock inputs, compute, approve, finalise, pay —
with a strict maker-checker split (the person who computes a run cannot approve it).

- **Layout:** header with a dynamic action button set driven entirely by current status; summary
  card — 5-stat grid (Employees, Gross, Deductions, Net pay, Employer contributions), blank until
  computed; conditional amber notice — outstanding errors / unacknowledged variances, plus the
  fixed maker-checker reminder; employee lines table with an issues filter (All / With issues /
  Flagged variance); "Day corrections" card — only once corrections exist, post-finalisation
- **Employee line columns:** Employee (+ daily-wage suffix where relevant), Paid days, LOP, Gross,
  Net, Variance (badge, with an inline Acknowledge action when unresolved), Issue badges (auto-
  humanised from error codes)
- **Employee detail dialog:** full line-item breakdown grouped Earnings / Deductions / Rounding /
  Employer contributions, each row showing the formula that produced it, footed by Net pay
- **Lifecycle actions (status-dependent):** Draft → Lock inputs; Locked/Computed → Compute /
  Recompute; Computed → Approve (different permission than Compute — enforces maker≠checker);
  Approved → Finalise (irreversible, confirm dialog); Finalised → Mark paid; Computed/Approved/
  Locked → Roll back (reason required); Finalised/Paid → Bank advice CSV download (audited); Draft
  only → Delete
- **Per-employee post-finalisation:** Correct days — adjusts paid days, paid as arrears in a future
  run, with a Pending/Paid-as-arrears status and a Withdraw option while pending
- **Notable:** server-supplied block reasons render as multi-reason toasts, not generic errors —
  design a toast variant that can hold a short bulleted list. All money right-aligned with tabular
  figures.

### Salary components — `/app/payroll/salary-components`

**Purpose:** reusable earnings/deductions/employer-contribution building blocks.

- **Table columns:** Component (name + code, "system" tag for seeded ones), Type, Treatment
  (comma-joined flags), Status
- **Create fields:** Code*, Name*, Type; Treatment flags — Taxable, Counts as PF wage, Counts as
  ESI wage, Prorated by paid days, Shown on payslip; Display order

### Salary structures — `/app/payroll/salary-structures`

**Purpose:** CTC structures (e.g. Standard, Standard-Metro) built from salary components, with the
same draft/publish lifecycle as policies.

- **List:** Structure (name/code/description), In effect since, Status (Inactive / Draft pending /
  Published); "Assign to employees" — bulk-assign dialog (structure + effective date; auto-skips
  daily-wage employees and anyone without CTC, listing why)
- **Detail — draft line editor:** repeatable rows — Component, Calculation type (Fixed / % of CTC /
  % of gross / % of another component / Balancing), the matching amount/percentage field, optional
  monthly cap, "Applies" condition. Exactly one earning line must be the balancing "rest of gross"
  line.
- **CTC preview:** Annual CTC input + PF-applies checkbox + Calculate → a breakup table (component
  / monthly / annual, Gross and Cost-to-company totals)

### Statutory rates — `/app/payroll/statutory-rates`

**Purpose:** PF/ESI/PT/LWF/TDS configuration — each rate effective-dated and requiring explicit
verification before payroll can use it.

- **Layout:** a conditional warning banner ("N current rates are not verified — a pay run using one
  can't be approved") sits above the table — this cross-links to the Pay Run screen's approval gate
  and deserves a strong, persistent visual treatment.
- **Table columns:** Scheme (+ state, + notes), In force dates, Figures (computed summary), Status
  (Verified / Not verified), Edit / Verify actions
- **Scheme-specific forms:** PF — employee/employer %, pension %, wage ceiling, EDLI %, admin
  charges %, no-pension-from age; ESI — employee/employer %, wage ceiling, no-employee-share daily
  wage floor; TDS — standard deduction, rebate threshold, cess %, surcharge-warn threshold, plus a
  slab editor (from/to/percent rows); PT — slab editor only (from/to/tax, gender scope,
  month-specific override); LWF — deduction months + slab editor (from/to/employee/employer)
- **Notable:** editing an already-verified rate resets it to unverified — the edit dialog's copy
  says so explicitly; make sure the UI doesn't let this feel like a silent side effect.

### My payslips — `/app/me/payslips`

**Purpose:** employee self-service payslip list and a printable single payslip.

- **List:** simple row list — month, paid-on date, net pay amount, View link
- **Payslip detail:** "Preview — not finalised yet" banner when applicable; header — legal entity
  name/address, pay month; two-column facts — employee/code/designation/department/DOJ/masked PAN
  vs. UAN/ESI/bank(masked)/paid-days/LOP/pay date; Earnings (with a "full month" reference column)
  and Deductions tables, each with a Total row; Net pay banner + amount-in-words; conditional
  Employer contributions section, conditional Leave balance summary
- **Notable:** the one screen in the app explicitly meant to be printed/saved as a PDF — design it
  to also work well as a static, chrome-free printable document, not just as an in-app card.

---

## Module: Cross-cutting

### Policy assignments — `/app/policy-assignments`

**Purpose:** assigns a policy (of six kinds — Attendance/Overtime/Regularization/Leave Policy, Work
Calendar, Weekly-Off Pattern) to a scope, with a fixed precedence order.

**Precedence order (shown in the page description):** Employee > Shift > Designation > Grade >
Department > Branch > Legal Entity > Company

- **List:** a flat, filterable, paginated list of assignment rows — "{policy kind} → {scope}", not
  a grid/matrix despite what the concept might suggest.
- **Create dialog:** a cascading form — Policy kind → (Leave type, if applicable) → Policy → Scope
  type → Scope target (or a free-text Employee ID for employee scope) → Effective from → Reason.

### Policy resolution — `/app/policy-resolution`

**Purpose:** a read-only "explain" tool: for this employee, on this date, which policy actually
applies and why.

**Layout:** Employee + Date + Policy kind (limited to Attendance/Overtime/Regularization) →
Resolve button → a result card showing the resolved policy and, notably, which precedence level it
matched through (as a badge). An empty result state explains that no fallback exists and a
company-level assignment is required.

---

*Compiled from the live codebase (`apps/web/src/app/app/*`, `apps/web/src/components/*`) for a
visual-redesign handoff. Field names, routes and workflows reflect the application as built.*
