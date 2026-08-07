# Screen Spec — Employee List (People → Directory)

**Status:** Draft, screen-level design. Extends UI Sprint 0 (`../00_UI_Vision.md` –
`../04_User_Personas.md`) down to one screen. No visuals — layout, states and behavior only;
visual design is a downstream step against `../01_Design_System.md` tokens.

**Where this sits:** `People → Directory` in the IA (`../02_Information_Architecture.md` §2). Named
"Directory" in-product per the "people, not tables" naming rule (§3 of that document); this spec
uses "Employee List" and "Directory" interchangeably since that's how the request framed it.
Listed as **Directory (table + card view) · Filters panel** in the screen inventory
(`../../../files/24_UIUX_Screen_Inventory_and_Design_System.md` §3.3).

**Not a separate screen per role.** Per IA rule 4, this is one component with a data-scope filter
and a field-visibility mask applied server-side — Company Admin, HR Manager, a Reporting Manager
checking their tree, and an Employee browsing colleagues all land on the same Directory, seeing
different rows and columns. This spec describes that one component and calls out where behavior
branches by role/scope.

---

## 1. User goals

| Persona | Goal on this screen | Frequency |
|---|---|---|
| HR Manager / HR Executive | Find a specific employee fast; scan a department/branch for a status check; export or bulk-act on a filtered set (e.g. "everyone in Bangalore Sales" before a reorg) | Many times daily — this is a load-bearing screen, not a lookup they visit rarely (`../04_User_Personas.md` §3–4) |
| Company Admin | Spot-check headcount/org composition; jump into a specific record for an escalation | Occasional, exception-driven |
| Reporting Manager / Team Leader | Confirm who's on their team and where each person sits in the tree, before approving something or checking coverage | Frequent, but shallow — mostly a lookup, not a workspace |
| Recruiter | Confirm a converted candidate now exists as an employee (hired-only scope) | Rare, transactional |
| Employee (ESS) | Find a colleague's contact info or reporting line | Occasional, read-only |
| Auditor | Sample employee records for a compliance review, with confidence that masked fields are actually masked, not just hidden by CSS | Periodic, read-only |

**The one design goal every persona shares:** get to a specific person or a specific filtered set
in the fewest actions, with total confidence in what they're allowed to see. Everything below is in
service of that.

---

## 2. Required actions

### 2.1 Page-level (toolbar) actions
Rendered only if the permission exists — absent, not disabled (`../00_UI_Vision.md` §4 principle
8):

| Action | Permission | Notes |
|---|---|---|
| Add employee | `EMPLOYEE.CREATE` | Opens the 4-step wizard (separate screen) |
| Bulk import | `EMPLOYEE.IMPORT` ⚠ | Opens upload → validate → preview → commit flow |
| Export | `EMPLOYEE.EXPORT` ⚠ | Exports the **current filtered view**, not always the whole company — see §6 |
| Toggle table / card view | any `EMPLOYEE.VIEW*` | Persisted per user, not per session |
| Org chart | any `EMPLOYEE.VIEW*` | Link out to the Org chart screen, scoped identically to the list |
| Column configuration | any `EMPLOYEE.VIEW*` on table view only | Show/hide/reorder columns from the PUBLIC/INTERNAL/SENSITIVE set the role can see; a column the role can't see is never offered as a hideable-but-present option |

### 2.2 Row-level actions
Primary click target on a row/card opens the **Employee 360° profile** (`../04_User_Personas.md`
persona table; `../../../files/24_UIUX_Screen_Inventory_and_Design_System.md` §4.1) — this is the
one navigational shortcut allowed to bypass deeper nav (`../02_Information_Architecture.md` §4).

A secondary "⋯" menu per row surfaces contextual shortcuts, each permission-gated independently
(a row can show a subset):

- Generate letter (`EMPLOYEE.GENERATE_LETTER`)
- Initiate transfer (`EMPLOYEE.TRANSFER`)
- Initiate exit (`EXIT.INITIATE_OTHER`) — routes into the Exit module, never a Directory-native
  action; see §5 on why destructive/lifecycle actions are deliberately kept out of bulk-select
- View audit trail (`EMPLOYEE.VIEW_AUDIT`)

Nothing here duplicates the 360° profile's quick actions — it's the same permission-gated action
set, exposed one level earlier for someone who doesn't need to open the full profile just to, say,
print a letter.

---

## 3. Filters

Filters open in a **dedicated panel** (its own inventoried screen, not an inline row of dropdowns
— `files/24` §3.3 "Filters panel"), distinct from global search per the nav system's explicit rule
that in-module filtering and cross-system search are different components
(`../03_Navigation_System.md` §8).

**Filter fields** (each renders only if the underlying field is visible to the role per the
field-classification table in §9):

- Department (multi-select, includes sub-departments)
- Branch / Location (multi-select)
- Legal entity (multi-select, Company Admin/HR Manager only — most tenants are single-entity and
  this filter is hidden entirely when the tenant has only one)
- Designation / Grade (multi-select)
- Employment type (Full-time / Part-time / Contract / Intern)
- Employment status (Active / On leave / Notice period / Exited) — **defaults to Active only**;
  exited employees are opt-in, never mixed into the default view
- Reporting manager (typeahead, single-select — "show me X's reports," distinct from the
  data-scope filter, which the user cannot widen past their own permission)
- Joining date (range)
- Custom fields (tenant-configured; rendered dynamically per `ORG.CUSTOM_FIELD.MANAGE` config,
  same "configuration, not code" principle as the rest of the product — `00_UI_Vision.md` §2)

**Behavior:**
- Filters combine with AND logic across fields, OR logic within a multi-select field's own values
- Active filter count shows as a badge on the toolbar's Filters button; each active filter is also
  removable as an individual chip above the list, so the user never has to reopen the panel just to
  clear one thing
- Filters, sort and the search term are all reflected in the URL query string, so a filtered view is
  bookmarkable and shareable between HR staff ("here's everyone in the Bangalore office —
  [link]") — this matters specifically for the HR persona's "scan a department" goal in §1
- Clearing all filters is a single, always-visible action once any filter is active

---

## 4. Search

Two distinct mechanisms, not one — mirroring the nav system's explicit distinction
(`../03_Navigation_System.md` §8):

**In-list search** (this screen only):
- A single search box scoped to the currently filtered/scoped result set — searches name, employee
  code, and (if visible to the role) work email/phone
- Debounced, updates the list without a page reload; matched substrings highlighted in results
- Does **not** search fields the role can't see — a search term matching someone's PAN, for
  instance, is not how a search box should ever leak a restricted field's existence
- Empty query returns the full scoped/filtered list (search is a narrowing tool, not a gate)

**Global search** (top bar, everywhere in the product, `Cmd/Ctrl+K`):
- Also returns people among its federated results, permission-aware at the query level
- The faster path for someone who already knows exactly who they want and doesn't want to land on
  Directory first — this screen doesn't try to replace that; in-list search exists for the
  "browsing/narrowing a set" case, global search for the "I know their name" case

---

## 5. Bulk actions

Bulk actions are first-class per the performance/interaction principles (`00_UI_Vision.md` §10) —
approving or acting on many records must complete in one interaction, not one-by-one. Row
checkboxes appear on table view only (card view has no multi-select — it's the browsing layout, not
the working layout).

**In scope for Directory bulk-select**, each gated by its own permission and shown in a bulk-action
bar that appears once ≥1 row is selected:

| Action | Permission | Confirmation |
|---|---|---|
| Export selected | `EMPLOYEE.EXPORT` ⚠ | None — reversible, generates a file |
| Generate letter (batch) | `EMPLOYEE.GENERATE_LETTER` | Preview list of recipients before generating |
| Bulk field update (non-sensitive only — e.g. department/branch move during a reorg) | `EMPLOYEE.UPDATE` | Plain-English summary of what changes, per-record, before applying; every change lands in the audit log individually, not as one opaque batch entry (`00_UI_Vision.md` §6 goal "auditability as a visible property") |
| Add to / notify via announcement | `NOTIFICATION.BROADCAST.SEND` ⚠ | Standard send confirmation |

**Deliberately excluded from bulk-select**, and why:

- **Deactivate / initiate exit** — these are lifecycle actions with clearance, F&F, and legal
  consequences (`../02_Information_Architecture.md` §4: Exit is a full module with its own
  workflow). Firing that from a lightweight multi-select checkbox would violate the product's
  explicit rule that destructive/irreversible actions get *distinct*, slower treatment, never the
  same gesture as a routine bulk action (`00_UI_Vision.md` §4 principle 4). These stay
  single-record entry points into the Exit module.
- **Compensation edits** — never available from a list screen at all, bulk or otherwise; salary
  revision is its own permissioned, individually-audited flow.

Selection state persists across a paginated/virtualized scroll (see §7) up to a sane cap (e.g.
2,000 rows); beyond that the bulk-action bar switches from "N selected" to a filter-scoped "act on
all N matching the current filter" pattern so the user isn't forced to manually scroll-select
thousands of rows.

---

## 6. Sorting

- **Table view:** click a sortable column header to sort ascending, click again for descending,
  a third click clears back to default. Only one sort column active at a time for v1 — see
  Deferred (§11) for multi-column sort.
- **Default sort:** Name, ascending.
- **Sortable columns:** Name, Employee code, Department, Designation, Joining date, Status. Columns
  the role can't see are, as everywhere else, never offered as a sort option.
- Sort state shown with a directional glyph in the header (not color alone — accessibility rule,
  §10) and exposed via `aria-sort` on the `<th>`.
- **Card view has no sort control of its own** — it inherits whatever sort is set on table view, so
  switching views mid-session doesn't silently reorder what the user was just looking at.

---

## 7. Pagination

Directory is explicitly one of the screens the performance principles name as needing
**virtualization-first, not classic pagination** — designed assuming 1,000+ rows as the baseline,
not the edge case (`00_UI_Vision.md` §10, `files/24` §4.2 pattern reused here).

- **Table view:** windowed/virtualized rendering over a cursor-paginated API — the user scrolls, the
  list fetches the next page transparently as they approach the bottom, sticky header stays pinned.
  No page-number picker; instead a persistent "Showing 240 of 3,180" style count so the user always
  knows the scale of what they're scrolling, without the false precision of a page count that shifts
  under real-time headcount changes.
- **Card view:** same cursor pagination, exposed as "Load more" (explicit tap) rather than
  auto-fetch-on-scroll — cards are heavier to render than table rows, and this is the
  browse-casually layout where an explicit action fits the slower pace better.
- **Export bypasses pagination entirely** — it always operates on the full filtered/scoped result
  set server-side, generated as a background job with progress, not a client-side dump of only the
  rows currently loaded in the viewport (consistent with "no blocking spinners on multi-step
  operations," `00_UI_Vision.md` §10).

---

## 8. Empty states

Per the cross-cutting rule that empty states teach rather than show a blank table
(`00_UI_Vision.md` §4 principle 6), Directory distinguishes three distinct empty conditions —
collapsing them into one generic "No data" message would be a defect, not a simplification:

| Condition | What's shown |
|---|---|
| **Zero employees in the company** (brand-new tenant) | Not a blank table — a guided empty state pointing at "Add employee" and "Bulk import," the two ways data enters the system, with a one-line explanation of each. This is a new-tenant's literal first impression of the product. |
| **Filters/search produce zero matches** | "No employees match these filters" plus the active filter chips and a one-click "Clear filters" — never the same copy or layout as the zero-employees case, so the user isn't left wondering whether the company data disappeared |
| **Scoped role with zero visible records** (e.g. a Reporting Manager with no direct/tree reports yet) | A scope-aware message ("You don't have any direct reports yet") rather than a generic empty table — this is a legitimate, expected state for that role, not an error |

---

## 9. Error states

Per the rule that the interface never lies about state (`00_UI_Vision.md` §4 principle 7):

| Condition | Behavior |
|---|---|
| **List fails to load** | Distinct error panel (not a hung skeleton) with the reason if known and a retry action; existing filter/search state is preserved so retry doesn't discard what the user set up |
| **Partial load** (e.g. one page of a virtualized scroll fails mid-scroll) | The already-rendered rows stay; a small inline "Couldn't load more — retry" affordance appears at the point of failure, not a full-screen error over data that loaded fine |
| **Export job fails or times out** | User is notified (via the Notifications system, not a silent failure) with a retry, especially since export runs as a background job and the user may have navigated away |
| **Bulk action partially fails** (e.g. bulk field update: 18 of 20 succeed) | Never reported as a single pass/fail — the result summary states exactly which records failed and why, per-record, so HR can fix and retry just those |
| **Stale data-scope cache** | The `REPORTEE_TREE` scope resolution is cached server-side for 60s (`files/19` §5) — if a manager's reporting line just changed, the list may lag up to a minute. Not surfaced as an error; a manual refresh always re-resolves scope, so this is a documented eventual-consistency window, not a bug to design around defensively in the UI |
| **Offline (mobile/tablet read-only use)** | Last-loaded results remain visible, clearly labeled stale ("Showing cached results — reconnect to refresh"), actions requiring network are disabled with an explanation rather than failing silently on tap |

---

## 10. Permissions

Enforced server-side per the access equation in `files/19` §1
(`module_enabled ∧ role_has_permission ∧ record_within_data_scope ∧ field_visible_to_role ∧ not
blocked_by_state`) — the UI's job is to faithfully reflect that, never to be the actual gate
(`00_UI_Vision.md` §12).

**Row-level (which employees appear at all)** — data scope per `files/19` §5, summarized for this
screen from the permission matrix (`files/19` §4 "Employee view" row):

| Role | Scope |
|---|---|
| Super Admin, Company Admin, HR Manager, HR Executive | `COMPANY` — full list |
| Recruiter | Hired-only subset (converted candidates) |
| Reporting Manager | `REPORTEE_TREE` — recursive, all levels |
| Team Leader | `REPORTEES` — direct reports only |
| Employee | `SELF` for edit context, but Directory read view is company-wide at PUBLIC/INTERNAL field level (see IA §6 — the Directory the Employee sees is scoped by *field visibility*, not row exclusion; they can see colleagues exist, just not their sensitive data) |
| Finance, Auditor | `COMPANY`, read-only (`○`) |

**Column-level (which fields appear per visible row)** — per the field classification in
`files/19` §6:

| Classification | Example fields on this screen | Who sees them here |
|---|---|---|
| `PUBLIC` | Photo, name, employee code, designation, department, work email/phone | Everyone with any `EMPLOYEE.VIEW*` |
| `INTERNAL` | Joining date, reporting manager, branch, shift | Roles with `EMPLOYEE.VIEW` (i.e., not the plain-Directory-browsing Employee persona for these specific columns, though they remain in the IA-listed set for HR) |
| `SENSITIVE` | Personal mobile/email, address, DOB | HR roles and self only — never a Directory list column, only surfaced inside the 360° profile even for roles allowed to see it, to keep the list itself lower-risk to glance at over someone's shoulder |
| `RESTRICTED` | CTC, bank details, PAN, Aadhaar | Never rendered on this screen under any role — restricted fields live only behind their own explicit-permission views (Compensation tab, etc.), not in a list |

Masked, not omitted-as-null, per `files/19` §6: if a column configuration would otherwise show a
field the role can partially see, it renders in the standard masked format (e.g. bank account
`******7890`) rather than a blank cell that could be mistaken for missing data.

**Action-level:** every toolbar, row-menu and bulk action in §2 and §5 is independently
permission-gated and **absent, not disabled** — a Recruiter never sees a greyed-out "Add employee"
button, they see no button at all (`00_UI_Vision.md` §4 principle 8). This is also why the row
"⋯" menu can legitimately show a different set of options per row for the same viewing user, if
scope or state (e.g. a locked payroll period affecting `BACKDATE_OVERRIDE`) differs per record.

---

## 11. Accessibility

Floor is WCAG 2.1 AA per `00_UI_Vision.md` §7, applied concretely to this screen:

- **Table semantics:** table view uses real `<table>`/`role="table"` semantics with `<th scope>`
  and `aria-sort` on sortable headers — not a `<div>` grid styled to look like a table. This matters
  more here than almost anywhere else in the product per the accessibility goals table's explicit
  callout that dense tables are where keyboard/screen-reader users suffer most if skipped.
- **Keyboard-complete:** every action reachable by mouse — row open, row-menu, bulk-select, sort,
  filter panel, view toggle, column configuration — is reachable by keyboard with a visible focus
  ring and a logical tab order (row → row-menu → next row, not a tab trap inside the menu).
- **Virtualization does not break the DOM.** Off-screen virtualized rows are removed from the
  accessibility tree correctly (not just visually hidden), and the live region announces list-length
  changes as filters/search change results, so a screen-reader user isn't left guessing whether a
  filter did anything.
- **Status pills** (Active / On leave / Notice period / Exited) pair color with a label/glyph, never
  color alone — the system-wide rule from `00_UI_Vision.md` §7, applied identically to how it's
  applied on the Attendance Matrix.
- **Bulk-select bar** is announced on appearance/change ("3 employees selected") via a live region,
  since it's a dynamically-inserted control a screen-reader user could otherwise miss entirely.
- **Touch targets:** 44×44px minimum on the tablet-degraded view (table screens get a degraded but
  usable tablet experience per `03_Navigation_System.md` responsive rules, not a phone redirect —
  Directory specifically is one of the few HR/admin screens worth keeping usable on tablet, since
  "who's on my team" is a legitimate walk-the-floor lookup).
- **Motion:** virtualized scroll and row-select transitions respect `prefers-reduced-motion`;
  nothing here conveys meaning through motion alone.

---

## 12. What's deferred to later sprints

- **Saved filter views** ("My usual: Bangalore + Active + Sales") — valuable for the HR persona's
  repeat-filter workflow but not required for a functional v1; URL-shareable filters (§3) cover the
  "send someone this exact view" case in the meantime.
- **Multi-column sort** — v1 ships single-column sort only (§6); revisit if HR usage data shows a
  real need for e.g. "Department, then Name."
- **Per-role default column sets** — v1 gives every role a sensible default and manual
  show/hide/reorder (§2.1); a curated default per role is a refinement, not a launch blocker.
- **Org-chart-integrated Directory browsing** (navigating the list *as* a tree view inline, rather
  than linking out to the separate Org chart screen) — out of scope; Org chart remains its own
  screen per the inventory.
