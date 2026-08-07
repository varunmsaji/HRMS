# 03 — Navigation System

**UI Sprint 0 — Design Foundation, Document 4 of 5**
Status: Foundational. Specifies how the tree in [`02_Information_Architecture.md`](02_Information_Architecture.md)
is exposed across devices.

---

## 1. Navigation model overview

Three coordinated surfaces carry the entire IA, consistently across the product:

| Surface | Carries | Present on |
|---|---|---|
| **Sidebar** | Primary IA — the top-level nav items and their sub-sections | Desktop, tablet (collapsible) |
| **Top bar** | Cross-cutting, always-available actions: global search, approvals, notifications, profile — plus breadcrumbs | Desktop, tablet, mobile (condensed) |
| **Bottom nav** | The five highest-frequency actions only | Mobile only |

The rule from [`02_Information_Architecture.md`](02_Information_Architecture.md) §1.3 governs the
split: anything that belongs to one module lives in the sidebar; anything that cuts across every
module (search, approvals, notifications, identity) lives in the top bar, on every device.

---

## 2. Desktop (≥1024px) — primary target for HR/Admin

Layout: **persistent left sidebar + top bar + content area**, per `files/24` §6 (1024–1440px is
"standard desktop; primary target for HR/admin"; >1440px removes max-width constraints on dense
data screens).

```
┌─────────────────────────────────────────────────────────────────┐
│ [Logo]  Breadcrumb › Breadcrumb › Page      [Search] [🔔] [👤]   │  ← Top bar, 56px
├───────────┬─────────────────────────────────────────────────────┤
│           │                                                     │
│  Sidebar  │                Content area                        │
│  (240px,  │        (max 1280px on forms/dashboards,             │
│  collaps- │         full-bleed on dense tables ≥1440px)         │
│  ible to  │                                                     │
│  64px)    │                                                     │
│           │                                                     │
└───────────┴─────────────────────────────────────────────────────┘
```

**Sidebar behavior:**
- Two states: expanded (240px, icon + label) and collapsed (64px, icon + tooltip on hover) — user
  preference, persisted per user, not per session, since HR staff live in this sidebar all day and
  will set it once.
- Top-level items per [`02_Information_Architecture.md`](02_Information_Architecture.md) §2, filtered
  by role per §7 of that document — items the role cannot access are absent from the DOM entirely.
- The active top-level item expands inline to show its sub-sections (accordion, one open at a
  time) — not a flyout, so keyboard and screen-reader users get a predictable, always-visible
  structure rather than a hover-triggered menu.
- Sub-items under the active section are always visible when that section is active; sub-items
  under inactive sections are collapsed, keeping the sidebar scannable even with twelve top-level
  modules.

**Content area:**
- Forms, dashboards, detail views: centered, max 1280px (§3 of [`01_Design_System.md`](01_Design_System.md)).
- Tables (Directory, Attendance Matrix, Payroll reports): full width, sticky header row and first
  column, virtualized for 1,000+ rows (`files/24` §4.2), no max-width above 1440px.

---

## 3. Tablet (640–1024px)

Per `files/24` §6: two-column forms collapse to one column; tables scroll horizontally with a
sticky first column.

- **Sidebar collapses by default** to the icon-only 64px rail, expandable on tap with an
  overlay (not a permanent push of content) — screen width can't sustain both an expanded sidebar
  and a usable table.
- **Top bar** keeps search, approvals, notifications and profile — these are the highest-value
  actions and must not be demoted to a hidden menu at this breakpoint.
- **Admin-heavy screens degrade to read-and-approve, not full editing** where a workflow genuinely
  needs desktop space (formula builder, roster pattern generator, workflow visual builder) — these
  specific screens show an explicit "Best viewed on desktop" notice rather than rendering a broken
  layout, consistent with the "interface never lies about state" rule (§4 principle 7,
  [`00_UI_Vision.md`](00_UI_Vision.md)).
- Manager approval flows (`files/24` §4.5) and ESS screens work fully at this breakpoint — they're
  designed mobile-first and simply gain breathing room here.

---

## 4. Mobile (<640px)

Per `files/24` §6 and §2.3: mobile carries **ESS and manager-approval patterns**; most HR/admin
screens redirect to "Open on desktop" rather than attempting a cramped port.

```
┌───────────────────────────┐
│ [≡]  Page title      [🔔] │  ← condensed top bar, 48px
├───────────────────────────┤
│                            │
│      Content (single       │
│      column, card-based)   │
│                            │
├───────────────────────────┤
│ [Home][Attend][ ⏱ ][Appr][More] │  ← bottom nav, 56px + safe area
└───────────────────────────┘
```

**Bottom navigation — five items maximum** (`files/24` §2.3):

| Slot | Item | Notes |
|---|---|---|
| 1 | Home | Role-appropriate dashboard summary |
| 2 | Attendance | This week at a glance, calendar |
| 3 | **Punch** | Center, visually elevated above the bar, always one tap from anywhere in the app — the single most time-critical action in the product (`00_UI_Vision.md` §8) |
| 4 | Approvals | Only populated/visible if the user has reportees; badge count for pending SLA-at-risk items |
| 5 | More | Leave, payslips, tax, profile, documents, directory, policies, helpdesk — everything else, in a simple list, not a nested menu |

**Why punch is centered and elevated, not just "in the row":** for a field worker in logistics or
construction, this is functionally the entire product (`files/24` §2.3). It gets a visually
distinct treatment (raised circular button, brand-colored) so it's findable without reading labels,
the same pattern camera apps use for the shutter button.

**Admin redirect pattern:** if a user with admin permissions opens the app on a phone and navigates
toward a desktop-only screen (Payroll setup, Report builder, Role editor, etc.), the screen shows a
plain-language notice — "This works best on a bigger screen. Open [tool name] on your computer to
continue." — never a broken, half-functional attempt at the layout.

---

## 5. Sidebar — interaction detail

- **Active state:** brand-hue text/icon + brand-hue-tinted background on the active top-level item
  and its active sub-item, consistent with reserving the brand hue for the thing that matters most
  on screen (`01_Design_System.md` §1.2).
- **Badge counts:** reserved for items with genuine action-required state (e.g., a pending count on
  "Applications" if the user is a recruiter with items awaiting triage) — not applied decoratively
  to every item, or the signal is lost.
- **Keyboard:** fully navigable — arrow keys move between top-level items, Enter expands/activates,
  matching the accessibility floor in `00_UI_Vision.md` §7.

---

## 6. Top bar

Present, in some form, on every breakpoint — the one navigational constant.

| Element | Desktop/tablet | Mobile |
|---|---|---|
| Logo / company switcher | Left-aligned, opens company selector if the user has cross-company access | Collapsed into the "≡" menu |
| Breadcrumbs | Center-left, see §3 below | Replaced by a single page title (no breadcrumb trail — insufficient width) |
| Global search | Persistent input, expands on focus | Icon only, opens full-screen search overlay on tap |
| Approvals | Icon with badge count, opens the unified inbox (`files/24` §4.5) | Present as a bottom-nav item instead, not duplicated in the top bar |
| Notifications | Icon with badge count, opens a dropdown panel | Icon only, opens full-screen panel |
| Profile menu | Avatar, opens dropdown | Avatar, opens dropdown (same content, full-width) |

---

## 7. Breadcrumbs

Breadcrumbs exist for one reason: HR/admin screens are deep (Payroll → Pay runs → Pay run detail →
Employee payslip preview is four levels), and a user arriving from a notification or a search
result needs to know **where they are and how to get back up**, not just what page they're on.

- Pattern: `Module › Section › Record`, e.g. `Payroll › Pay runs › March 2026 › Priya Sharma`.
- Every segment except the last is a link, navigating up the tree exactly as
  [`02_Information_Architecture.md`](02_Information_Architecture.md) defines it — breadcrumbs are a
  rendering of the IA, never an independent path (no breadcrumb ever points somewhere the sidebar
  wouldn't).
- The Employee 360° hub (`files/24` §4.1) is the one place breadcrumbs may show a person's name as
  a mid-trail segment even when arrived at via a shortcut (§4 of
  [`02_Information_Architecture.md`](02_Information_Architecture.md)) — reflecting that the
  underlying navigation model treats a person as a valid pivot point, not just a leaf record.
- Not shown on: the dashboard (nothing above it), first-level module landing pages (redundant with
  the active sidebar state), and any full-screen wizard (pay run creation, employee onboarding
  wizard) — wizards use a step indicator instead (`files/24` §4.4), which serves the "where am I"
  need more precisely than a breadcrumb would for a linear flow.

---

## 8. Global search

One search, reachable from every screen, not a per-module search box.

- **Scope:** people, requisitions/candidates, pay runs, policies, settings pages — everything the
  user has permission to see, federated into one result list grouped by type.
- **Permission-aware at the query level**, not filtered after the fact — a user never sees a result
  they don't have access to and then hits a 403 on click; results outside the user's data scope
  simply never appear (same "absent, not disabled" principle as gated nav items,
  `00_UI_Vision.md` §4 principle 8).
- **Keyboard-first:** a global shortcut (e.g. `/` or `Cmd/Ctrl+K`) opens search from anywhere on
  desktop, landing focus directly in the input — this is the fastest path through a 185-screen
  product for a power user (HR Manager, Recruiter) who knows what they want and doesn't want to
  navigate the tree.
- **Recent + suggested** when the query is empty: last-viewed records and, for managers, "people
  whose approvals are pending" — turning search into a second, faster entry point into daily work,
  not just a lookup tool.
- Distinguished from module-local **filtering** (e.g., filtering the Directory table, or the
  Attendance Matrix filter panel in `files/24` §4.2) — global search finds *records across the
  whole system*; in-module filters narrow a list you're already looking at. They are visually and
  behaviorally different components, never conflated.

---

## 9. Notifications

- **Bell icon, badge count of unread**, opens a panel (dropdown on desktop/tablet, full-screen on
  mobile) listing recent notifications grouped by recency (Today / Earlier).
- Each notification is actionable where possible — a leave-approved notification links directly to
  the leave detail, not just to a generic "Leave" landing page.
- **Distinct from the Approvals inbox.** Notifications are informational ("Your leave was
  approved"); Approvals are actionable work items awaiting a decision ("Approve/reject Priya's leave
  request"). Conflating them into one list would bury actionable work inside a stream of FYI
  messages — a common HRMS design failure this product deliberately avoids.
- Preferences (channel, frequency, per-category opt-out) live in Settings → Notification templates
  for admins and a personal Notification preferences screen for every user (`files/24` §3.9).

---

## 10. Approvals inbox

The unified, cross-module inbox specified in `files/24` §4.5, surfaced from the top bar (desktop/
tablet) and as a bottom-nav item (mobile) — deliberately **not** nested inside any single module's
sidebar section, because approvals span Leave, Attendance (regularisation), Expenses, Assets,
Recruitment (offers) and Exit (resignations) simultaneously.

- **One list, all entity types**, sorted by SLA proximity — not grouped by module first, because a
  manager's mental model when clearing an inbox is urgency, not taxonomy.
- Each card surfaces the one number the approver needs (days remaining, balance after, amount, team
  coverage that day) inline, so no tap-through is required to make routine decisions.
- Swipe-to-approve / swipe-to-reject on mobile, with bulk-select on desktop for leave and
  regularisation specifically (the two request types with the highest volume).
- Optimistic UI on every action — the card animates away immediately, restored with an explanation
  only on failure (`files/24` §4.5, `00_UI_Vision.md` §4 principle 5).

---

## 11. Profile menu

Avatar-triggered dropdown, identical structure on every device:

```
[Avatar] Full name
         Role · Company (if multi-company access)
─────────────────────────
My profile
My payslips
Preferences (theme, notification settings, language)
Switch company (only if the user has access to more than one)
─────────────────────────
Help & documentation
Sign out
```

Impersonation (Super Admin only, per `files/19` §7) adds a persistent, unmissable banner above the
top bar for the duration of the session — never folded into the profile menu, because it must be
impossible to forget you're impersonating someone.

---

## 12. Responsive behavior summary

Restated from `files/24` §6 for direct reference alongside the mechanics above:

| Breakpoint | Sidebar | Admin screens | ESS / approval screens |
|---|---|---|---|
| < 640px | Removed — replaced by bottom nav | Redirect to "Open on desktop" for most screens | Full, mobile-first experience |
| 640–1024px | Collapsed rail, expandable overlay | Read/approve where possible; explicit desktop notice for a small set of layout-intensive screens | Full experience, more breathing room |
| 1024–1440px | Expanded by default | Full experience — primary target | Full experience |
| > 1440px | Expanded by default | Full experience, full-bleed on dense tables, no artificial width cap | Full experience, centered (no benefit to stretching card-based ESS layouts) |

---

## 13. Public surfaces (no sidebar, no top bar)

Careers page, offer acceptance, pre-boarding portal (§5 of
[`02_Information_Architecture.md`](02_Information_Architecture.md)) use a minimal header (logo +
company name only) and no sidebar/top bar/bottom nav at all — these are single-purpose, often
single-session flows for people who are not yet system users, and the full navigation chrome would
misrepresent what's available to them.
