# 00 — UI Vision

**UI Sprint 0 — Design Foundation, Document 1 of 5**
Status: Foundational. Every future screen, component and design decision traces back to this
document or is wrong.

**Source of truth this extends:** [`docs/product/01_Product_Vision.md`](../product/01_Product_Vision.md)
(product pillars), [`docs/product/24_UIUX_Screen_Inventory_and_Design_System.md`](../product/24_UIUX_Screen_Inventory_and_Design_System.md)
(design principles D1–D8, copy rules). This document does not repeat those — it converts them into
a design charter a designer or AI agent can build against without re-deriving intent each time.

---

## 1. Why this document exists

Sprint 0 (backend) and Sprint B1 (identity, multi-tenancy) are complete. The API, RBAC model and
data model are stable enough to design against. Before a single screen is drawn, the product needs
a **design constitution** — the set of decisions that are expensive to reverse later (visual
language, navigation model, accessibility floor, mobile posture) made deliberately, once, in
writing.

This is UI Sprint 0. Its output is judgment, not pixels: no React, no Tailwind, no Figma files.
Everything downstream — the component library, the screen designs for 185 Phase-1 screens, the
frontend implementation — is a derivative of the five documents in this folder.

---

## 2. Product philosophy

> *"HR software that does the work, not just stores the records."* — `docs/product/01` §1

The product exists to convert HR from **data entry operators into exception handlers**. Every
design decision is tested against one question: *does this screen reduce the number of humans a
routine transaction has to pass through, or does it just move a paper form onto glass?*

Three consequences for design specifically:

- **The system should look like it's doing work, not waiting to be told what to do.** Dashboards
  lead with what needs a decision today, not with a static summary of what already happened.
- **Configuration, not code, is the escape hatch.** Leave rules, approval chains, salary
  structures and letter templates are tenant data. The UI for configuring them is a first-class
  product surface — Settings is not an afterthought screen, it's where the product adapts to eight
  different industries without a single conditional in application code.
- **Correctness is a design feature, not just an engineering one.** Payroll, statutory compliance
  and access control get visibly different treatment in the UI — confirmation friction,
  irreversibility warnings, audit visibility — proportional to the cost of getting them wrong.

## 3. Design philosophy

An HRMS is opened by people who did not choose it and derive no joy from opening it. Delight is
not the design goal; **removing friction from obligations** is (`docs/product/24` D1). This produces a
different set of values than a consumer product:

| We optimize for | Over |
|---|---|
| Predictability — the same action always looks and behaves the same way, everywhere | Novelty or per-screen cleverness |
| Getting to zero — an empty inbox, a cleared approval queue, a reconciled pay run | Engagement, streaks, or anything that makes the user linger |
| Trust through transparency — every number explains itself on tap | Trust through reassuring copy or animation |
| Getting out of the way for daily/weekly tasks (punch, approve, apply) | Getting out of the way for rare, high-stakes tasks (finalize payroll), where the product should visibly slow the user down |

Two audiences live inside one product, and they get two different design postures, deliberately
(`docs/product/24` D1):

- **HR/admin surfaces** are dense, tabular, filter-heavy, keyboard-friendly — built for someone who
  does this task fifty times a day and wants throughput.
- **Employee (ESS) surfaces** are sparse, card-based, one primary action per screen — built for
  someone who opens the app four times a month and should never have to think about it.

Forcing one aesthetic across both is the single most common HRMS design failure and is explicitly
rejected here.

## 4. UX principles

These operationalize `docs/product/24` §1 (D1–D8) as day-to-day design rules:

1. **Show the answer, not the data.** "8.5 casual leave days left" beats a ledger table. The
   ledger is one tap away for the person who wants it, never the default view.
2. **Never let someone submit something that will be rejected.** Validate balances, policy limits,
   overlaps and blackout periods *before* the submit button is even enabled, and state the reason
   inline, not as a post-submit error.
3. **Every number is explainable.** Leave balance, net pay, worked hours, LOP days — every computed
   figure has a tap-through breakdown. This is the single behavior that prevents most HR support
   tickets, and it is treated as a cross-cutting requirement, not a payroll-specific feature.
4. **Destructive and irreversible actions look different.** Payroll finalization, exit
   confirmation, permission grants and bulk deletion get a distinct visual treatment (color,
   iconography, placement), a typed confirmation for the highest-stakes actions, and a plain-English
   statement of consequences before the point of no return.
5. **Speed is a feature.** A manager clearing twenty approvals should never wait on a network
   round trip to see the next item. Optimistic UI everywhere an action is reversible or
   correctable; pessimistic-safe patterns reserved for irreversible actions only.
6. **Empty states teach.** A first-time HR user opening Payroll sees what to configure and why —
   never a blank table with no path forward.
7. **The interface never lies about state.** No spinner that hangs with no explanation, no silent
   failure. Offline, queued, processing, failed and succeeded are always distinguishable states in
   the UI, not folded into "loading."
8. **Permission-gated content is absent, not disabled-and-visible.** A locked tab or greyed-out
   button that a user can see but not use invites social-engineering requests to HR staff. If a
   user lacks the permission, the affordance does not render.

## 5. Product personality

If this product were a person, they would be: **the operations lead who has done this job for
fifteen years, is unfailingly precise, and never makes you feel stupid for asking.**

| Trait | Expressed as |
|---|---|
| Precise | Numbers align, statuses are exact ("Approved by Priya Sharma, 14 Feb, 10:42"), never vague ("recently") |
| Calm | No exclamation points, no "Oops!", no celebratory confetti on routine actions |
| Direct | Buttons state what will happen; errors state what happened and what to do next (`docs/product/24` §1.1) |
| Quietly confident | Restraint over decoration; the brand hue is spent on the few things that matter (primary actions), not spread thin |
| Respectful of time | Defaults are smart, forms are short, nothing asks twice for information the system already has |

This personality is a filter, not a mood board. When two copy options or two layouts are both
defensible, the one that a precise, calm, direct colleague would choose wins.

## 6. Enterprise design goals

The product is sold into SMEs, mid-size companies and enterprise organizations simultaneously
(`docs/product/01` §1). The design system must not fork by customer size — one system, configured by
data (roles, plan, feature flags), not by a different UI per tier.

| Goal | What it requires of the design system |
|---|---|
| **Multi-tenant coherence** | Every tenant sees the same information architecture and interaction patterns; only branding tokens (logo, accent within guardrails) and enabled modules vary. No customer-specific UI forks. |
| **Scale from 50 to 5,000+ employees** | Every list/table screen is designed virtualization-first (`docs/product/24` §4.2) — the design must not visually assume "a handful of rows" and break under real enterprise data volume. |
| **Nine concurrent roles, one shell** | The same navigation shell, component library and interaction vocabulary serve a Super Admin and a first-day Employee. Role determines *what's visible*, never *how it behaves*. See [`04_User_Personas.md`](04_User_Personas.md). |
| **Auditability as a visible property** | Anywhere data can change, "who changed what, when" is a first-class, discoverable UI affordance — not something only visible in a database. |
| **Compliance-legible** | Screens that produce statutory artifacts (payslips, tax filings, F&F) are designed to be correct when printed or exported, not just correct on a laptop screen — HR teams genuinely still print things. |
| **Extend without redesign** | New modules (industry-specific verticals, new statutory jurisdictions) must be able to adopt the existing shell, tokens and components without a design system version bump. |

## 7. Accessibility goals

Accessibility is a floor, not a stretch goal, because an enterprise HRMS is a mandatory tool for
employees who did not choose it and cannot opt out.

| Target | Detail |
|---|---|
| **Conformance level** | WCAG 2.1 AA minimum across all web surfaces; AAA color contrast targeted (not mandated) for body text where it doesn't compromise density. |
| **Color is never the only signal** | Status (approved/pending/rejected/absent/on-leave/holiday) always pairs color with a glyph, pattern, or label — required for the attendance calendar and payslip specifically (`docs/product/24` §1.2), applied as a system-wide rule. |
| **Keyboard-complete** | Every action reachable by mouse is reachable by keyboard, with a visible focus state and a logical tab order, on HR/admin surfaces especially — dense tables are where keyboard users suffer most if this is skipped. |
| **Screen-reader-correct semantics** | Data tables use real table semantics; status pills, badges and icons carry accessible names, not just visual meaning. Documented per-screen as "accessibility annotations" (`docs/product/24` §7). |
| **Motion respects preference** | All transition/loading motion honors `prefers-reduced-motion`; nothing essential to understanding the UI is conveyed by motion alone. |
| **Touch targets** | Minimum 44×44px on mobile and tablet, including within dense approval cards. |
| **Language and locale** | Copy is written for translation from the start (no baked-in string concatenation); numerals, dates and currency respect locale formatting rules per tenant. |

Accessibility annotations (focus order, ARIA roles, labels) ship with every screen spec, not as a
retrofit pass before launch (`docs/product/24` §7).

## 8. Mobile strategy

**The mobile app is not the web app shrunk** (`docs/product/24` D6). Mobile is a purpose-built surface for
a narrow, high-frequency job list:

- Punch in / punch out (the single most time-critical interaction in the product)
- Apply for and check leave
- Approve/reject requests from a manager's pocket
- View payslip
- Browse the employee directory

Everything else — payroll processing, recruitment pipelines, org settings, report building — is
explicitly **out of scope for mobile** and redirects to "Open on desktop" if reached (`docs/product/24`
§6). This is a deliberate constraint, not a phase-1 limitation to be lifted later: trying to fit
admin-density workflows onto a phone produces a worse experience in both places at once.

Mobile navigation is five items maximum, bottom-anchored, with punch as a centered, elevated,
always-one-tap action (`docs/product/24` §2.3) — see [`03_Navigation_System.md`](03_Navigation_System.md)
for the full specification.

Mobile must degrade gracefully on connectivity: punches queue offline and say so explicitly
(`docs/product/24` §4.6). A spinner that hangs with no explanation is treated as a defect, not a loading
state.

## 9. Desktop-first strategy

HR and admin work is explicitly **desktop-first**, stated plainly rather than left implicit
(`docs/product/24` §6), because the alternative — vague "responsive everywhere" ambition — reliably
produces a late, expensive "can we run payroll on a phone?" conversation.

| Surface | Primary device | Rationale |
|---|---|---|
| HR/Admin (People, Recruitment, Payroll, Reports, Settings) | Desktop (1024–1440px+) | Dense tables, multi-column filters, bulk actions and formula builders need screen real estate and a keyboard. Tablet gets a degraded but usable read/approve experience; phone gets a "open on desktop" redirect for most admin screens. |
| Employee Self-Service (ESS) | Mobile-first, desktop-compatible | The employee's daily/weekly touchpoints (punch, apply, approve, check payslip) are mobile-native. The same flows work on desktop web without redesign, since some employees only ever use a browser. |
| Manager approvals | Mobile-first | A Reporting Manager or Team Leader approving requests between meetings needs this on a phone; the swipe-based inbox (`docs/product/24` §4.5) is designed mobile-first and works identically on desktop. |

This is the one place the product deliberately optimizes two different device classes for two
different roles rather than chasing a single universal breakpoint story. See
[`03_Navigation_System.md`](03_Navigation_System.md) §6 for the full responsive behavior table.

## 10. Performance principles

Performance is treated as a design constraint, not a post-hoc engineering optimization, because
the product's core promise — "does the work" — is undermined by a UI that makes people wait.

- **Perceived speed over raw speed.** Skeleton loading states, optimistic UI for reversible
  actions, and progressive disclosure (lazy-loaded tabs on Employee 360°, `docs/product/24` §4.1) matter
  as much as backend latency.
- **Virtualize by default for dense data.** Any list or table screen is designed assuming
  1,000+ rows; sticky headers/columns and row virtualization are baseline requirements for the
  Attendance Matrix, Directory, and every report viewer, not an enhancement added under load
  (`docs/product/24` §4.2).
- **No blocking spinners on multi-step operations.** Long-running operations (payroll compute,
  bulk import, statutory file generation) show live progress — items processed, ETA, error count —
  never an opaque wait (`docs/product/24` §4.4).
- **Bulk actions are first-class, not a power-user add-on.** Approving twenty requests, marking
  attendance for a department, or bulk-rejecting applications must complete in one interaction, not
  twenty repeated ones — directly serving "speed is a feature" (§4 principle 5 above).
- **Motion has a budget.** Animation is limited to state transitions and loading feedback; no
  ambient or decorative motion, both for a tool opened dozens of times a month and for reduced
  cognitive load on dense screens.

## 11. Future scalability

The design foundation is built to absorb growth the product roadmap already anticipates, without a
system rewrite:

| Growth vector | How the foundation absorbs it |
|---|---|
| **New modules** (Learning, Assets, Expenses and future verticals) | The navigation and component system (see [`02_Information_Architecture.md`](02_Information_Architecture.md), [`03_Navigation_System.md`](03_Navigation_System.md)) is a pattern, not a fixed list — a new module adopts the existing top-level nav slot, page shell, table pattern and permission-gating convention with no new design primitives. |
| **New industry verticals** | Because configuration lives in tenant data, not code (`docs/product/01` §3), the UI for a manufacturing shift roster and a tech company's flexible leave policy is the *same components* rendering different tenant configuration — not a fork. |
| **New roles** | The RBAC model (`docs/product/19`) is data-driven; a new role is a new row in the permission matrix, not a new UI. The design system's rule that gated content is *absent, not disabled* (§4 principle 8) is what makes this scale without per-role screen variants. |
| **New jurisdictions / statutory regimes** | Statutory-facing screens (payslip, tax, F&F) are designed around a breakdown/explain pattern (§4 principle 3) that is jurisdiction-agnostic — the calculation trace UI doesn't change when the underlying statutory rules do. |
| **Design system versioning** | Tokens (color, type, spacing, radius, elevation, motion — see [`01_Design_System.md`](01_Design_System.md)) are the seam between design intent and code. They are versioned independently of any single screen so the system can evolve (e.g., a future dark-mode refinement) without touching every screen that consumes it. |
| **AI-assisted and AI-native features** | Per `docs/product/01` §3 ("AI that assists, never decides"), any AI-surfaced content (resume matching, attrition risk, suggested approvals) uses a consistent, clearly-labeled "AI suggestion" visual pattern, distinct from system-of-record data, defined once and reused everywhere AI output appears. |

---

## 12. What this document is not

- Not a color palette, type scale, or spacing scale — those are [`01_Design_System.md`](01_Design_System.md).
- Not a sitemap — that is [`02_Information_Architecture.md`](02_Information_Architecture.md).
- Not a component inventory — that remains `docs/product/24` §5 until a dedicated component spec is
  written in a later sprint.
- Not permission logic — that is owned by `docs/product/19` and is enforced server-side; the UI vision
  simply commits to reflecting it faithfully (§6, §4 principle 8).

## 13. Document map

| Document | Purpose |
|---|---|
| **00 — UI Vision** *(this document)* | Why the product looks and behaves the way it will |
| [01 — Design System](01_Design_System.md) | The visual and interaction language, with rationale |
| [02 — Information Architecture](02_Information_Architecture.md) | The complete navigation hierarchy and module relationships |
| [03 — Navigation System](03_Navigation_System.md) | How the IA is exposed across desktop, tablet and mobile |
| [04 — User Personas](04_User_Personas.md) | Who each screen is designed for, in detail |
