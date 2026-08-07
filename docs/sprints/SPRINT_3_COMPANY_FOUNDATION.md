# Sprint 3 — Company Foundation

**Status:** Planning complete, ready for implementation.
**Type:** Implementation guide / engineering backlog — every task below is scoped to be picked up and completed independently by an AI coding session with zero architectural decisions left open.
**Depends on:** Sprint 0 (`docs/SPRINT0_FOUNDATION.md`, complete), Sprint 2/B1 (`docs/SPRINT_B1_IDENTITY.md`, complete — auth, JWT, refresh rotation, RBAC engine, multi-tenancy, audit foundation).
**Governs:** `docs/product/VERSION_1_ROADMAP.md` §14 Sprint 3 ("RBAC completion & Org setup"), scoped down per the brief below to **Company Foundation only** — RBAC catalogue growth is folded into this sprint's org modules rather than a separate epic, since every new module registers its own permissions per `docs/architecture/01_Backend_Structure.md` §5.
**Read before starting any task:** `docs/README.md` read order, plus this document's §0 Scope Decisions in full — every task below assumes those decisions are already made and does not re-justify them.

---

## 0. Scope Decisions (binding — do not relitigate mid-implementation)

These are judgment calls made once, here, so no implementation session has to make an architectural decision on its own. Each is a deliberate resolution of an ambiguity in the source specs (`files/17`, `files/08`, `files/24`, `docs/product/VERSION_1_ROADMAP.md`).

| # | Decision | Rationale |
|---|---|---|
| D1 | **"Work Locations" is not a separate table or module. It is the existing `branch` table.** `files/17` §3.1's own hierarchy diagram writes the node as "Branch / Location" — one concept. `docs/product/VERSION_1_ROADMAP.md` §5 row 9 lists them as one module ("Branches / Work Locations"). The **Branch Management** screen is the only screen built; "Work Locations" in the sprint brief's screen list is an alias for the same screen, not a second CRUD surface. Do not create a `work_location` table. | Avoids a duplicate table holding the same address/geofence/state data, which would immediately desync. |
| D2 | **Grade is built alongside Designation, not deferred**, even though the sprint brief's flow list doesn't name it separately. `files/17` FR-ORG-006/007 makes Designation reference `grade_id`, and the existing `designation`/`grade` stub tables are already FK-linked in the current schema. Building Designation without Grade would leave a dangling FK the UI can't populate. | Designation's grade reference is not optional in the data model already in the repo. |
| D3 | **Leave Policy in this sprint is configuration only — type master, policy bundles, and org-segment assignment rules.** No `leave_ledger`, no accrual job, no application/approval flow, no balance computation. Those depend on Employee Management (Sprint 4) and the approval-routing core (Sprint 5) per `docs/product/VERSION_1_ROADMAP.md` §6's hard sequencing constraints — an employee-less company cannot accrue or apply for leave. | Matches the sprint brief's own instruction: "Configure Leave Policies," not "Apply for leave." Building the ledger now would create a leave-balance UI with nothing to display. |
| D4 | **Payroll Policy in this sprint is pay-cycle/cut-off/pay-date configuration only** (`files/17` FR-ORG-009) — no salary components, no salary structures, no formula builder, no statutory master. Those are Sprint 9 (`docs/product/VERSION_1_ROADMAP.md` §14) and depend on Employee Management for CTC assignment. | Same reasoning as D3 — "Configure Payroll Policies" in the brief means the cycle/date rules, not the computation engine. |
| D5 | **Shift in this sprint is the shift master only** (`files/17` FR-ATT-001) — name, timings, breaks, grace, OT eligibility flag. No shift **assignment**, no roster, no rotation-pattern generator (FR-ATT-002). Assignment requires employees to assign shifts to, which don't exist until Sprint 4. | A shift definition is organization config; assigning it to a person is an Attendance-module concern per `docs/product/VERSION_1_ROADMAP.md` §6. |
| D6 | **Custom Fields (`files/17` FR-ORG-012) are deferred to Sprint 4.** The spec defines them as extra fields on Employee/Candidate/Asset — none of which exist yet. Building the custom-field engine with nothing to attach it to has no demo value this sprint. | Explicitly listed as a documentation follow-up risk in `docs/product/VERSION_1_ROADMAP.md` §17 if skipped silently — flagging it here instead. |
| D7 | **Number Series is built, scoped to exactly one series type: `EMPLOYEE_CODE`.** `files/17` FR-ORG-011 lists five series types (employee, candidate, offer, asset, ticket); only Employee Management (next sprint) needs one immediately, and Recruitment is out of V1 entirely. The `number_series` table and race-safe allocator are built generically so Sprint 4 adds new `entity_type` rows without a schema change. | Building the generic mechanism now avoids Sprint 4 needing a migration for something that could have shipped now; scoping usage to one row avoids speculative UI for series that will never fire in V1. |
| D8 | **Industry-specific template seeding (`files/17` FR-ORG-002) is scoped down to one static default template, not per-industry variants.** On company creation, seed: 12 Indian statutory leave types (FR-LEV-002), one default general shift (09:00–18:00), a default `PERMANENT` + `PROBATION` employment type pair, and an empty current-year holiday calendar the admin populates in the wizard. No industry-selection-driven branching logic. | True industry templating needs a content library (multiple shift patterns, leave sets, designation lists per vertical) that doesn't exist yet and isn't specified beyond the one-line FR. Shipping one sensible default unblocks the wizard without inventing unspecified content. |
| D9 | **The Company Setup Wizard is a guided, resumable, but not strictly enforced sequence.** A Company Admin can complete steps out of order or skip to the dashboard early (`ORG.COMPANY.MANAGE` grants access to every step's screen directly via the nav, not only via the wizard). The wizard is a first-run UX affordance, not an access gate — this matches `docs/design/00_UI_Vision.md`'s "interface never lies about state" principle: a step marked incomplete is informational, never a hard block, because a real company may legitimately want to configure Departments before Branches. | Hard-gating step order would contradict the existing IA, where every org screen (`docs/design/02_Information_Architecture.md` §2, Settings section) is independently reachable from the sidebar once setup begins. |
| D10 | **`head_employee_id` on `department` and `next_designation_id` on `designation` are built as nullable FK columns but have no UI control this sprint.** Both reference the `employee` table, which has no real rows until Sprint 4. The columns exist now so Sprint 4 doesn't need a migration to add them. | Same forward-compatible-schema-now, feature-later pattern as D7. |
| D11 | **Company Registration is self-service and creates a brand-new tenant** (`Company` + first `User` + `UserCompany` + a company-scoped `COMPANY_ADMIN` role seeded with every permission this sprint introduces). This is distinct from Sprint B1's seed script, which only pre-populates two demo companies for local dev/tests — that script is untouched. | `docs/product/VERSION_1_ROADMAP.md` §5 row 4 ("Company Setup") is explicitly "Not started" — B1 shipped login against pre-seeded tenants only, never a public registration endpoint. |
| D12 | **Roles beyond `COMPANY_ADMIN` are not built this sprint.** Every permission introduced below is granted to the seeded Company Admin role only. `HR_MANAGER`, `HR_EXECUTIVE`, etc. (`files/19` §4) are deferred — there's no HR staff to invite until Sprint 4's user management screens exist, and no non-admin workflow in this sprint's scope needs a second role to demonstrate. | Keeps RBAC catalogue growth tied to modules that actually ship this sprint, per `docs/architecture/01_Backend_Structure.md` §5's "create only when building that block" rule. |

---

## 1. Sprint Goal & Definition of Done

**Demo script at sprint close** (this is the acceptance test — every epic below exists to make this script work, end to end, no mocked steps):

1. A visitor with no account registers a new company (name, industry, country, currency, timezone, FY start, admin email + password) → lands authenticated, on the Setup Checklist.
2. They complete each wizard step in any order: Company Profile → Branches → Departments → Designations & Grades → Employment Types → Holiday Calendar → Shifts → Leave Policies → Payroll Policies.
3. Each step persists independently (closing the browser mid-wizard and returning resumes from real server state, not client memory).
4. They open the Company Dashboard and see real counts (branches, departments, designations, employees = 0) and a setup-completion indicator, not placeholder data.
5. Logging out and back in returns them to the dashboard directly (wizard is a first-run affordance per D9, not a permanent gate).

**Definition of Done for the sprint** (all must be true, not "mostly true"):

- [ ] Every endpoint listed in §5 exists, is permission-gated, is tenant-isolated (RLS + repository predicate), and returns the standard envelope (`files/09` §1.3).
- [ ] Every table listed in §4 exists via Alembic migration with RLS enabled (`docs/database/Database_Architecture.md` §2–3) and required indexes (§4.8 below).
- [ ] Every screen listed in §3 is built, wired to real APIs (no mock data), and matches its Empty/Loading/Error/Success states.
- [ ] `pytest`, `mypy --strict`, `ruff check`, `ruff format --check`, `lint-imports` all pass in CI (existing gates, unchanged).
- [ ] New frontend has an equivalent quality gate wired into CI (Epic 6, Feature 6.4) — this sprint introduces it since `apps/web` had none.
- [ ] The demo script above runs against a fresh database with zero manual DB intervention.
- [ ] Cross-tenant isolation tests (Epic 6, Feature 6.1) pass for every new table and endpoint, following the existing pattern in `apps/api/tests/integration/auth/test_auth_security.py`.

---

## 2. Epics

| Epic | Name | Why this order |
|---|---|---|
| 1 | Frontend Application Foundation | `apps/web` currently has no shadcn/ui, no API client, no auth pages, no layout — every other epic's frontend feature depends on this existing first. |
| 2 | Company Domain & Registration | The tenant must exist before anything else can be configured; also delivers the wizard shell every other epic's frontend plugs into. |
| 3 | Organization Structure | Legal Entity → Branch → Department → Designation/Grade → Employment Type, in FK dependency order (`docs/database/Database_Architecture.md` §4). |
| 4 | Scheduling & Policy Foundation | Holiday Calendar, Shift, Leave Policy, Payroll Policy — all configuration-only per D3–D5, all depend on Organization Structure existing (holiday calendars attach to branches; leave/payroll policies can reference grades). |
| 5 | Company Dashboard | Needs real data from Epics 2–4 to aggregate; built last so it has something real to show. |
| 6 | Testing & Quality Gates | Cross-cutting — individual features carry their own unit/integration tests as they're built (this is a hard gate per task, not deferred); this epic covers the suite-level and E2E work that only makes sense once every piece exists. |

---

## Epic 1 — Frontend Application Foundation

**Goal:** `apps/web` goes from a bare Next.js scaffold to a working authenticated app shell with a component library, API client, and form infrastructure, so every subsequent epic's frontend feature is a screen, not a platform.

### Feature 1.1 — Design tokens & Tailwind theme

**Objective:** Encode `docs/design/01_Design_System.md`'s token decisions (color, type, spacing, radius, elevation, motion) as Tailwind config + CSS variables, in both light and dark mode.

#### Task 1.1.1 — Tailwind theme config
- **Objective:** Implement the neutral scale, brand indigo (`#4F46E5` family, 5–6 tonal steps), and semantic set (success/warning/danger/info + HRMS states: on-leave, holiday, half-day, WFH) as Tailwind `theme.extend.colors`, with light/dark pairs per `docs/design/01_Design_System.md` §9–10.
- **Dependencies:** None (first task in the sprint).
- **Backend Work:** None.
- **Frontend Work:** `apps/web/tailwind.config.ts` — extend `colors`, `spacing` (4px scale, `space-1`…`space-16`), `borderRadius` (`sm`4px/`md`8px/`lg`12px/`full`), `fontSize` (type scale `text-xs`…`text-3xl`, base 14px), `transitionDuration` (100/150/200/300ms per `motion-*` tokens). Add `apps/web/src/app/globals.css` CSS custom properties for the light/dark pairs, toggled via a `data-theme` attribute (or `prefers-color-scheme` + manual override class) on `<html>`.
- **Database Work:** None.
- **API Work:** None.
- **Testing Requirements:** Visual smoke check only (no automated test for token values) — confirm `text-tabular-nums` utility works for numeric columns (tabular lining figures per `01_Design_System.md` §2.1).
- **Acceptance Criteria:** Both light and dark mode render with correct token values; toggling theme does not require a page reload; all colors defined as light/dark pairs, never a single value with a filter.
- **Estimated Complexity:** S

#### Task 1.1.2 — Font loading
- **Objective:** Load a grotesk sans with true tabular lining figures (Inter or IBM Plex Sans per `01_Design_System.md` §2.2) as the body/UI font, self-hosted via `next/font` (no external font CDN request, consistent with the "self-contained" performance principle in `docs/design/00_UI_Vision.md` §10).
- **Dependencies:** 1.1.1
- **Backend Work:** None.
- **Frontend Work:** `apps/web/src/app/layout.tsx` — `next/font/google` or local font files under `apps/web/src/fonts/`; apply as the default `font-sans` in Tailwind config.
- **Database Work:** None.
- **API Work:** None.
- **Testing Requirements:** None beyond visual check.
- **Acceptance Criteria:** Numeric columns in any table render with equal-width digits; no FOUT/FOIT flash beyond Next.js's built-in font optimization.
- **Estimated Complexity:** XS

---

### Feature 1.2 — shadcn/ui component installation

**Objective:** Install and configure shadcn/ui as the component primitive layer, matching `files/24` §5's component library list where shadcn provides a direct equivalent, and establish the project's convention for components shadcn doesn't cover (Money display, Employee picker, Permission-gated wrapper — built in later features as needed).

#### Task 1.2.1 — shadcn/ui base install
- **Objective:** Run `shadcn` init against the Tailwind config from 1.1.1, add the base primitive set needed by Epics 2–5: Button, Input, Select, Checkbox, RadioGroup, Switch, Textarea, Label, Form (react-hook-form wrapper), Table, Card, Tabs, Dialog, Sheet (drawer), DropdownMenu, Popover, Tooltip, Toast (Sonner), Badge, Avatar, Skeleton, Separator, Breadcrumb, Pagination, Command (for search), Calendar, Combobox pattern.
- **Dependencies:** 1.1.1
- **Backend Work:** None.
- **Frontend Work:** `apps/web/components.json`, `apps/web/src/components/ui/*` (generated). `package.json` gains `class-variance-authority`, `clsx`, `tailwind-merge`, `lucide-react` (single icon set per `01_Design_System.md` §7 — outline style, 16/20px, 1.5–2px stroke), `sonner`.
- **Database Work:** None.
- **API Work:** None.
- **Testing Requirements:** None (generated primitives, not project logic) — but confirm the project's component test setup (Task 1.2.2) can render one of them.
- **Acceptance Criteria:** Every primitive listed renders in a scratch page with no console errors; icon set is `lucide-react` exclusively, no second icon package added anywhere in the sprint.
- **Estimated Complexity:** S

#### Task 1.2.2 — Frontend test tooling
- **Objective:** Wire up Vitest + React Testing Library + Playwright, since `apps/web` currently has zero test infrastructure.
- **Dependencies:** 1.2.1
- **Backend Work:** None.
- **Frontend Work:** `apps/web/vitest.config.ts`, `apps/web/playwright.config.ts`, `apps/web/src/test/setup.ts` (jsdom, `@testing-library/jest-dom` matchers). `package.json` scripts: `test`, `test:e2e`. One smoke test (`apps/web/src/app/page.test.tsx`) rendering the existing placeholder page to prove the harness works.
- **Database Work:** None.
- **API Work:** None.
- **Testing Requirements:** The smoke test itself is the requirement — must pass in CI.
- **Acceptance Criteria:** `npm run test` and `npm run test:e2e` both execute (Playwright can target a local dev server) and the smoke test is green.
- **Estimated Complexity:** S

#### Task 1.2.3 — Composite components shadcn doesn't cover
- **Objective:** Build the product-specific components `files/24` §5 lists that have no shadcn equivalent: **Money display** (currency + minor-unit aware, per `shared/value_objects/money.py`'s shape), **Status pill** (semantic color + glyph pair, never color alone, per `01_Design_System.md` §1.4), **Empty state** (icon + message + primary action slot), **Permission-gated wrapper** (renders children only if a permission code is present in the current user's permission set — absent, not disabled, per `docs/design/00_UI_Vision.md` §4 principle 8), **Data table** (wraps shadcn Table with sort/filter/pagination/column-visibility, built once here and reused by every list screen in Epics 3–4).
- **Dependencies:** 1.2.1
- **Backend Work:** None.
- **Frontend Work:** `apps/web/src/components/hrms/money-display.tsx`, `status-pill.tsx`, `empty-state.tsx`, `permission-gate.tsx`, `data-table.tsx` (+ `data-table-column-header.tsx`, `data-table-pagination.tsx` following the standard shadcn data-table recipe, extended with server-side pagination since every list API in this sprint is cursor/offset-paginated per `files/09` §1.5).
- **Database Work:** None.
- **API Work:** None.
- **Testing Requirements:** Component tests for `PermissionGate` (renders/hides correctly given a mock permission set) and `MoneyDisplay` (formats minor units + currency correctly, including negative amounts) — these two carry real logic, unlike the purely presentational ones.
- **Acceptance Criteria:** `PermissionGate` with a missing permission renders nothing (not a disabled state) — matches the IA's "absent, not disabled" rule; `DataTable` supports sort, column show/hide, and server-side pagination via props, reused unmodified by every Epic 3/4 list screen (no per-screen table reimplementation).
- **Estimated Complexity:** M

---

### Feature 1.3 — API client & data-fetching layer

**Objective:** A typed HTTP client matching `files/09` §1's conventions (envelope unwrapping, required headers, error mapping), plus TanStack Query for server-state caching.

#### Task 1.3.1 — Typed API client
- **Objective:** Build `apps/web/src/lib/api-client.ts` — a `fetch` wrapper that attaches `Authorization: Bearer`, `X-Company-Id`, `X-Request-Id` (generated per request), reads `DataEnvelope`/`ListEnvelope`/`ErrorEnvelope` shapes matching `apps/api/src/hrms/shared/pagination.py` exactly, and throws a typed `ApiError` (code, message, details, request_id) on the error envelope shape.
- **Dependencies:** None (parallel to 1.1/1.2).
- **Backend Work:** None — this consumes the existing envelope contract, does not change it.
- **Frontend Work:** `apps/web/src/lib/api-client.ts`, `apps/web/src/lib/api-error.ts`. Base URL from `NEXT_PUBLIC_API_URL` env var (`apps/web/.env.local.example` already exists — extend it).
- **Database Work:** None.
- **API Work:** None (client only).
- **Testing Requirements:** Unit tests mocking `fetch`: successful envelope unwraps to `.data`; error envelope throws `ApiError` with correct fields; 401 triggers the token-refresh flow (Task 1.5.3) before retrying once.
- **Acceptance Criteria:** A component calling `apiClient.get<CompanyDetail>('/companies/current')` receives the unwrapped `data` object, typed, with no manual envelope handling in the calling code.
- **Estimated Complexity:** M

#### Task 1.3.2 — TanStack Query setup
- **Objective:** Wire TanStack Query as the server-state layer, with query-key conventions so every Epic 3/4 feature follows one pattern instead of inventing its own caching.
- **Dependencies:** 1.3.1
- **Backend Work:** None.
- **Frontend Work:** `apps/web/src/lib/query-client.ts`, `apps/web/src/app/providers.tsx` (QueryClientProvider wrapping the app). Establish the query-key convention: `[resource, companyId, ...filters]` e.g. `['branches', companyId, { status: 'ACTIVE' }]`, documented in a short comment block other sessions will copy.
- **Database Work:** None.
- **API Work:** None.
- **Testing Requirements:** None beyond the provider rendering without error in the Task 1.2.2 harness.
- **Acceptance Criteria:** A `useQuery` call against a mocked API client returns loading → success states correctly in a component test.
- **Estimated Complexity:** S

---

### Feature 1.4 — App shell: layout, sidebar, top bar

**Objective:** Implement the desktop layout from `docs/design/03_Navigation_System.md` §2 — persistent sidebar + top bar + content area — driven by the IA tree in `docs/design/02_Information_Architecture.md` §2, filtered to only the sections this sprint's modules populate (everything else absent, not greyed out, per D-rule below).

**Scope note:** The full IA (§2 of that doc) has 12 top-level sections; this sprint's RBAC catalogue (§6 below) only covers Dashboard and Settings-adjacent org config. The sidebar renders **only** the nav items this sprint's permissions unlock — Dashboard and Settings (Company, Branches, Departments, Designations, Employment Types, Holiday Calendar, Shifts, Leave Policies, Payroll Policies). Every other IA section (People, Recruitment, Attendance, Leave, Payroll, etc.) is correctly absent this sprint because no permission exists yet for them — this is the IA's own rule (`02_Information_Architecture.md` §7) applied honestly, not a shortcut.

#### Task 1.4.1 — Sidebar component
- **Objective:** Build the collapsible sidebar (240px expanded / 64px collapsed, user-preference persisted) per `03_Navigation_System.md` §2 and §5.
- **Dependencies:** 1.2.1, 1.3.2
- **Backend Work:** None.
- **Frontend Work:** `apps/web/src/components/layout/sidebar.tsx`, `sidebar-nav-item.tsx`. Nav tree defined as a typed constant (`apps/web/src/config/navigation.ts`) filtered at render time by the current user's permission set (via `PermissionGate` composition or an equivalent `useHasPermission` hook). Collapse state persisted to `localStorage`, keyed per user id.
- **Database Work:** None.
- **API Work:** Consumes `GET /v1/auth/me` (existing) for the permission set.
- **Testing Requirements:** Component test — sidebar renders only items the mock permission set allows; collapse toggle persists across remount.
- **Acceptance Criteria:** A user with only `ORG.BRANCH.MANAGE` sees Branches in the sidebar and nothing else under Settings; collapse state survives a page reload.
- **Estimated Complexity:** M

#### Task 1.4.2 — Top bar component
- **Objective:** Build the top bar — logo/company name, breadcrumbs, profile menu — per `03_Navigation_System.md` §6. Global search, Approvals inbox, and Notifications icons are rendered but visibly disabled/absent this sprint (no backing module yet) — **specifically:** omit them entirely rather than rendering broken icons, since those modules don't exist until later sprints.
- **Dependencies:** 1.2.1
- **Backend Work:** None.
- **Frontend Work:** `apps/web/src/components/layout/topbar.tsx`, `breadcrumb-trail.tsx` (derived from the current route + `02_Information_Architecture.md`'s tree, per `03_Navigation_System.md` §7 pattern), `profile-menu.tsx` (avatar, name, role, Sign out — Switch company only rendered if `>1` membership).
- **Database Work:** None.
- **API Work:** Consumes `GET /v1/auth/me`; `POST /v1/auth/logout` (existing) wired to Sign out.
- **Testing Requirements:** Component test for breadcrumb generation given a sample route; Sign out calls the logout endpoint and redirects to `/login`.
- **Acceptance Criteria:** Breadcrumb never points somewhere the sidebar wouldn't (per nav-system rule); Sign out clears local session state and redirects.
- **Estimated Complexity:** M

#### Task 1.4.3 — Authenticated layout shell + route groups
- **Objective:** Compose sidebar + top bar + content area into the persistent authenticated shell, using Next.js App Router route groups to separate public (`/login`, `/register`) from authenticated (`/(app)/...`) routes.
- **Dependencies:** 1.4.1, 1.4.2, 1.5.1 (auth guard)
- **Backend Work:** None.
- **Frontend Work:** `apps/web/src/app/(app)/layout.tsx` (shell + auth guard), `apps/web/src/app/(public)/layout.tsx` (minimal, no chrome, per `03_Navigation_System.md` §13). Content area respects the 1280px-centered / full-bleed-above-1440px rule from `01_Design_System.md` §3 via a `<PageContainer dense?: boolean>` wrapper component.
- **Database Work:** None.
- **API Work:** None (composition only).
- **Testing Requirements:** E2E smoke: unauthenticated visit to `/(app)/dashboard` redirects to `/login`; authenticated visit renders the shell.
- **Acceptance Criteria:** Table-heavy screens (Epic 3/4 list views) can opt into full-bleed via `dense`; form screens default to centered 1280px max-width.
- **Estimated Complexity:** M

---

### Feature 1.5 — Auth pages & session handling

**Objective:** Login page, token storage/refresh, and route guarding — the frontend half of Sprint B1's already-complete backend auth.

#### Task 1.5.1 — Session store & route guard
- **Objective:** Client-side session state (access token, active company id, permission set) with automatic silent refresh, and a route guard redirecting unauthenticated users to `/login`.
- **Dependencies:** 1.3.1
- **Backend Work:** None — consumes existing `/v1/auth/login`, `/v1/auth/token/refresh`, `/v1/auth/me`.
- **Frontend Work:** `apps/web/src/lib/session.ts` (a small client store — Zustand or React Context, project's choice at implementation time, consistent with whichever is used elsewhere once chosen) holding `accessToken`, `companyId`, `permissions`; refresh token held **only** as an httpOnly cookie set by the backend (never in JS-readable storage — matches the existing `hrms_refresh` cookie handling already referenced in `identity/router.py`'s `request.cookies.get("hrms_refresh")`). Access token kept in memory only (not `localStorage`), re-acquired via silent refresh on load.
- **Database Work:** None.
- **API Work:** None (consumes existing).
- **Testing Requirements:** Unit test: expired access token triggers exactly one refresh attempt before the original request retries; a failed refresh clears session and redirects to `/login`.
- **Acceptance Criteria:** Reloading the app with a valid refresh cookie re-establishes a session without a visible login flash; an invalid/expired refresh cookie lands cleanly on `/login`.
- **Estimated Complexity:** M

#### Task 1.5.2 — Login page
- **Objective:** Build `/login` per `files/24` §3.1 screen inventory item "Login."
- **Dependencies:** 1.4.3 (public layout), 1.5.1, 1.6.1 (form infra)
- **Backend Work:** None.
- **Frontend Work:** `apps/web/src/app/(public)/login/page.tsx` — email + password form (react-hook-form + zod), calls `POST /v1/auth/login`, on success writes session state and redirects to `/dashboard` (or the wizard, per Task 2.4's resume logic). Multi-company response (`companies[]` in `TokenResponseData`) triggers a company-picker step inline if `>1` membership, matching the existing login response shape — **no new backend field needed.**
- **Database Work:** None.
- **API Work:** None (consumes existing `POST /v1/auth/login`).
- **Testing Requirements:** Component test: invalid credentials show the server's error message inline (not a generic toast, since `files/09` error envelope carries a display-safe message); valid credentials redirect.
- **Acceptance Criteria:** Matches Empty/Loading/Error/Success states defined in §3 screen spec for Login below.
- **Estimated Complexity:** M

#### Task 1.5.3 — Silent refresh + 401 interceptor
- **Objective:** Wire the API client (1.3.1) to the session store (1.5.1) so any `401 UNAUTHORIZED` response triggers exactly one silent-refresh-and-retry before surfacing an error.
- **Dependencies:** 1.3.1, 1.5.1
- **Backend Work:** None.
- **Frontend Work:** Interceptor logic inside `apps/web/src/lib/api-client.ts` (or a thin wrapper) — must de-duplicate concurrent 401s into a single in-flight refresh call, not one refresh per failed request.
- **Database Work:** None.
- **API Work:** None (consumes existing `POST /v1/auth/token/refresh`).
- **Testing Requirements:** Unit test: three concurrent requests failing with 401 trigger exactly one `/token/refresh` call.
- **Acceptance Criteria:** No infinite refresh loop if the refresh itself returns 401 (must clear session and redirect instead of retrying indefinitely).
- **Estimated Complexity:** M

---

### Feature 1.6 — Form infrastructure

**Objective:** One standard pattern for every form in Epics 2–4, so 20+ CRUD screens don't each reinvent validation/error display.

#### Task 1.6.1 — Form field primitives
- **Objective:** Standardize on react-hook-form + zod, with a `<FormField>` wrapper (label, help text, error message, required indicator) composing shadcn's Form primitive from 1.2.1.
- **Dependencies:** 1.2.1
- **Backend Work:** None.
- **Frontend Work:** `apps/web/src/components/form/*` — `form-field.tsx`, `form-section.tsx` (grouped fields with a heading, used heavily in Epic 3/4's multi-section forms like Legal Entity), `server-error-banner.tsx` (renders an `ApiError`'s field-level `details[]` mapped onto the matching form fields, plus a top-level banner for non-field errors — implements `files/09` §1.3's error envelope `details[].field` mapping generically, once).
- **Database Work:** None.
- **API Work:** None.
- **Testing Requirements:** Component test: a mocked `ApiError` with `details: [{field: 'code', message: '...'}]` correctly sets the `code` field's error state, not just a generic banner.
- **Acceptance Criteria:** Every Epic 3/4 create/edit form reuses this without duplicating validation-error-mapping logic.
- **Estimated Complexity:** M

#### Task 1.6.2 — Optimistic mutation + confirmation dialog pattern
- **Objective:** Standard `useMutation` wrapper (toast on success/error, cache invalidation by resource key) and a reusable `<ConfirmDialog>` for destructive/irreversible actions (deactivate branch, delete draft policy, etc.) per `docs/design/00_UI_Vision.md` §4 principle 4 (irreversible actions get distinct, slower treatment).
- **Dependencies:** 1.3.2, 1.2.1
- **Backend Work:** None.
- **Frontend Work:** `apps/web/src/lib/use-app-mutation.ts`, `apps/web/src/components/hrms/confirm-dialog.tsx`.
- **Database Work:** None.
- **API Work:** None.
- **Testing Requirements:** Component test: `ConfirmDialog` requires explicit confirm click before the destructive callback fires; Escape/backdrop click cancels without firing it.
- **Acceptance Criteria:** No Epic 3/4 deactivate/delete action fires directly from a button click without this dialog in between.
- **Estimated Complexity:** S


## Epic 2 — Company Domain & Registration

**Goal:** A visitor can create a new tenant, land authenticated, and progress through a resumable Setup Wizard whose steps are real screens from Epic 3/4, not a hardcoded stepper with dead ends.

### Feature 2.1 — Company registration (backend)

#### Task 2.1.1 — `company` table migration + registration fields
- **Objective:** Extend the existing `company` table (already has `id, name, legal_name, subdomain, country_code, currency, timezone, status, ...` per `apps/api/scripts/sql/001_init_schema.sql`) with the remaining `files/08` §3.1 columns not yet present: `industry_code VARCHAR(40)`, `fy_start_month SMALLINT DEFAULT 4`, `logo_url TEXT`, `theme_json JSONB`, `onboarded_at TIMESTAMPTZ`, `trial_ends_at TIMESTAMPTZ`, `data_region VARCHAR(20)`.
- **Dependencies:** None.
- **Backend Work:** Alembic migration `apps/api/alembic/versions/<rev>_company_registration_fields.py` (autogenerate against updated `Company` model, review before applying per `docs/database/Database_Architecture.md` §9). Update `hrms/core/db/models/identity.py::Company` with the new `Mapped[...]` columns.
- **Frontend Work:** None (schema only).
- **Database Work:** As above. No RLS change needed (`company` has no `company_id` — it is the tenant root, already correctly excluded from RLS per `scripts/sql/002_row_level_security.sql`).
- **API Work:** None (this task only).
- **Testing Requirements:** Migration up/down test (existing pattern — confirm `alembic downgrade -1` then `upgrade head` is clean).
- **Acceptance Criteria:** `Company` model has every column `files/08` §3.1 specifies; mypy strict passes on the updated model.
- **Estimated Complexity:** S

#### Task 2.1.2 — `modules/organisation/` package scaffold
- **Objective:** Create the `organisation` module package (British spelling per `docs/architecture/01_Backend_Structure.md` §2 mapping table) following the standard module layout (`docs/architecture/02_Module_Standard.md` §1): `__init__.py`, `router.py`, `service.py`, `repository.py`, `models.py`, `schemas.py`, `permissions.py`, `exceptions.py`, `dependencies.py`. This is the home for **every** Epic 2–4 org/policy entity — one module, not one per entity, since they share the org-setup bounded context and the module-standard's "split only past 15 tables" rule (`01_Backend_Structure.md` §3) keeps them together until then.
- **Dependencies:** 2.1.1
- **Backend Work:** Scaffold files per the standard layout; register `organisation_router` in `hrms/app.py` under `/v1`, mirroring how `identity_router` is registered.
- **Frontend Work:** None.
- **Database Work:** None (this task).
- **API Work:** None (this task — router file created empty, populated by later tasks).
- **Testing Requirements:** `apps/api/tests/unit/modules/organisation/` directory created with an `__init__.py`; import-linter passes with the new module present.
- **Acceptance Criteria:** `uv run lint-imports` passes; app starts with the empty router mounted.
- **Estimated Complexity:** XS

#### Task 2.1.3 — Company registration endpoint
- **Objective:** `POST /v1/companies/register` (public, unauthenticated) — creates `Company`, `User` (the registering admin), `UserCompany` (`is_primary=true`), a company-scoped `Role` (code `COMPANY_ADMIN`, `is_system=true`), grants it every permission code registered by this sprint's modules (see §6 catalogue), links via `RolePermission` + `UserRole`, then returns the same `TokenResponseData` shape `POST /v1/auth/login` returns (immediate authenticated session — no separate login step required post-registration, matching the sprint demo script's step 1→2 transition).
- **Dependencies:** 2.1.2, all permission codes from Epics 3–4 must be registered in the permission catalogue seed (this task references them by constant, so implement it **last** within Epic 2, after Epic 3/4's `permissions.py` modules exist — or seed a placeholder subset now and extend the grant list as later tasks land; either is acceptable, but the final state must grant 100% of this sprint's permission codes to `COMPANY_ADMIN`).
- **Backend Work:** `modules/organisation/schemas.py::CompanyRegistrationRequest` (name, industry_code, country_code, currency, timezone, fy_start_month, admin_email, admin_password, admin_full_name — wait, no `full_name` field exists on `User` yet; add `first_name`/`last_name VARCHAR(100)` nullable columns to `user` in this task's migration, matching `files/08` §3.2's implied profile fields not yet modeled). `modules/organisation/service.py::OrganisationService.register_company()` — orchestrates: subdomain uniqueness check (`ConflictError` on duplicate), password strength validation (reuse `core/auth/passwords.py` hashing, add a minimum-strength check consistent with whatever B1 already enforces at login, if any — if none exists, add a simple length+complexity check here since this is the first path that creates a password), transactional creation of all rows, calls `AuditService.record()` with `action="COMPANY_REGISTERED"`, then delegates to `IdentityService`'s token-issuance logic (extract the existing `_issue_tokens` private method on `IdentityService` into a shared/importable form, or call it via a public method — do not duplicate JWT-issuance logic between modules). `modules/organisation/repository.py::OrganisationRepository` — inserts for `Company`, `User`, `UserCompany`, `Role`, `RolePermission`, `UserRole` (reuse patterns already established in `seed/bootstrap.py`'s `_ensure_*` helpers, but as real repository methods, not seed-script helpers). `modules/organisation/router.py` — `POST /register`, no `Depends(require_permission(...))` (public), but still runs through the standard exception handlers.
- **Frontend Work:** None (this task).
- **Database Work:** Migration for `user.first_name`, `user.last_name` (nullable `VARCHAR(100)`).
- **API Work:** `POST /v1/companies/register` per above. Request/response documented in §5.1.
- **Testing Requirements:** Integration test: full registration → assert `Company`, `User`, `UserCompany`, `Role`, `RolePermission`, `UserRole` rows all exist and are correctly linked; assert returned tokens work against a subsequent authenticated call; duplicate subdomain returns `409 CONFLICT`; weak password returns `422 VALIDATION_ERROR` with a field-level detail on `admin_password`.
- **Acceptance Criteria:** A single `POST` call results in a fully working, immediately-authenticated tenant with zero manual follow-up (matches demo script step 1).
- **Estimated Complexity:** L

---

### Feature 2.2 — Company registration (frontend)

#### Task 2.2.1 — Registration page
- **Objective:** Build `/register` per `files/24` §3.1 "Company registration wizard (5 steps)" — scoped down to a **single-page form** for this sprint (name, industry, country, currency, timezone, admin name/email/password), not a 5-step wizard, since `files/17` FR-ORG-001's field list is short enough for one screen and the *actual* multi-step wizard experience the sprint brief describes is the **post-registration Setup Wizard** (Feature 2.4), not registration itself. This resolves an apparent overlap between `files/24`'s "registration wizard" framing and the sprint brief's distinct "Company Registration" → "Company Setup Wizard" two-step flow: registration is one form, setup is the wizard.
- **Dependencies:** 1.5.1, 1.6.1, 2.1.3
- **Backend Work:** None.
- **Frontend Work:** `apps/web/src/app/(public)/register/page.tsx` — form per Task 1.6.1 pattern, calls `POST /v1/companies/register`, on success stores session and redirects to `/setup` (Task 2.4.2). Industry/country/currency/timezone as `<Select>` with a small static option list (industry: a fixed ~15-value list per common verticals — IT/ITES, Manufacturing, Retail, Healthcare, Construction, etc.; country/currency/timezone: standard ISO lists, a small static JSON asset, not an API call).
- **Database Work:** None.
- **API Work:** None (consumes 2.1.3).
- **Testing Requirements:** E2E: fill form → submit → land on `/setup`; component test for client-side validation (email format, password confirmation match, required fields) firing before the API call.
- **Acceptance Criteria:** Matches Empty/Loading/Error/Success states in §3 screen spec for Company Registration below.
- **Estimated Complexity:** M

---

### Feature 2.3 — Company Setup Wizard state machine (backend)

#### Task 2.3.1 — `company_setup_progress` table + tracking service
- **Objective:** Persist wizard progress server-side (per D9 — resumable, not a client-only stepper) so returning after closing the browser shows real completion state.
- **Dependencies:** 2.1.2
- **Backend Work:** `modules/organisation/models.py::CompanySetupProgress` — `id, company_id (unique), steps_completed JSONB (array of step codes), current_step VARCHAR(40), status VARCHAR(20) [IN_PROGRESS/COMPLETE], started_at, completed_at`. `service.py::OrganisationService.get_setup_progress()` / `mark_step_complete(step_code)` — a step is marked complete not by user click but by **derived state**: querying whether that step's underlying entity has ≥1 row for the company (e.g., "Branches" step is complete iff `branch` count > 0). This avoids a separate "did the user click Next" flag desyncing from actual data — the wizard reflects reality, matching D9's "interface never lies about state." `repository.py` — the count queries per step, plus the progress row CRUD.
- **Frontend Work:** None.
- **Database Work:** Migration for `company_setup_progress` + RLS (tenant table, `company_id` present → gets the standard RLS policy per `docs/database/Database_Architecture.md` §3).
- **API Work:** `GET /v1/companies/current/setup-progress` (§5.1).
- **Testing Requirements:** Unit test: progress derivation for each step code against a company with 0 vs ≥1 rows of the relevant entity; `status` flips to `COMPLETE` only when every step's derived condition is true.
- **Acceptance Criteria:** Progress is never stored as a client-trusted flag — every "complete" state is re-derivable from real table counts at any time, including for a company that configured things outside the wizard entirely (per D9).
- **Estimated Complexity:** M

---

### Feature 2.4 — Company Setup Wizard (frontend)

#### Task 2.4.1 — Setup Checklist screen
- **Objective:** Build the checklist/overview screen (`files/24` §3.1 "Setup checklist") listing all 9 steps (Company Profile, Branches, Departments, Designations & Grades, Employment Types, Holiday Calendar, Shifts, Leave Policies, Payroll Policies) with completion state from Task 2.3.1, each linking to its real screen (built in Epic 3/4).
- **Dependencies:** 2.3.1, 1.4.3
- **Backend Work:** None.
- **Frontend Work:** `apps/web/src/app/(app)/setup/page.tsx` — reads `GET /v1/companies/current/setup-progress`, renders a `Stepper`-style checklist (not a locked linear stepper per D9 — every step is a direct link, always clickable regardless of prior-step completion), a "Go to Dashboard" affordance always visible (D9 — never a hard gate), and a completion banner once all steps are done.
- **Database Work:** None.
- **API Work:** Consumes 2.3.1's `GET`.
- **Testing Requirements:** Component test: steps render with correct complete/incomplete visual state from mocked progress data; every step link navigates correctly regardless of order.
- **Acceptance Criteria:** Matches Empty/Loading/Error/Success states in §3 screen spec for Company Setup Wizard below.
- **Estimated Complexity:** M

#### Task 2.4.2 — Post-registration redirect + resume logic
- **Objective:** Wire the redirect chain: registration success → `/setup`; subsequent logins for a company with `status != COMPLETE` also land on `/setup` (not `/dashboard`) until finished, per D9's "guided but not gated" — this is a **default landing preference**, not an access restriction (the user can still navigate to `/dashboard` manually at any time).
- **Dependencies:** 2.4.1, 1.5.2
- **Backend Work:** None (consumes 2.3.1's progress `status`).
- **Frontend Work:** Login success handler (Task 1.5.2) checks setup `status` (one extra `GET` call, or embed a `setup_status` summary field in `GET /v1/auth/me`'s response if cheaper — **implementation choice, not architectural**: prefer embedding in `/me` to avoid a second round-trip, extending `MeResponseData` with an optional `setup_status: 'IN_PROGRESS' | 'COMPLETE' | null` field, `null` reserved for future non-admin roles this doesn't apply to).
- **Database Work:** None.
- **API Work:** If embedding in `/me`: extend `modules/identity/schemas.py::MeResponseData` and `IdentityService.get_me()` to include `setup_status` (calls into `OrganisationService`, a cross-module call from `identity` → `organisation` — **allowed** per `docs/architecture/02_Module_Standard.md` §2's "other_module.service" rule, but note the reverse direction, `organisation` importing `identity`, is what's typical; confirm no import cycle results, and if one would, keep this as a separate frontend `GET` call instead rather than forcing an awkward dependency).
- **Testing Requirements:** E2E: fresh registration → land on `/setup`; login as a user whose company has `status=COMPLETE` → land on `/dashboard` directly.
- **Acceptance Criteria:** No company is ever forced back into the wizard after completion; an incomplete company's user can still reach `/dashboard` via direct nav.
- **Estimated Complexity:** S

---

### Feature 2.5 — Company Profile & Settings (backend + frontend)

#### Task 2.5.1 — Company profile update endpoints
- **Objective:** `GET/PATCH /v1/companies/current` (extends the existing stub `get_company` read path in `identity/router.py` — **move this endpoint's ownership to `organisation` module**, since company profile management is an org-setup concern, not an identity concern; identity keeps only what's session/auth-scoped). Fields: name, legal_name, industry_code, country_code, currency, timezone, fy_start_month, logo_url.
- **Dependencies:** 2.1.1, 2.1.2
- **Backend Work:** `organisation/schemas.py::CompanyProfileUpdate`, `organisation/service.py::update_company_profile()` (optimistic locking via `version` column per `files/09` §1.7 — `PATCH` requires `If-Match` header, `409 STALE_RESOURCE` on mismatch), `organisation/repository.py::update_company()`. Audit every field change (`AuditService.record` with before/after JSON). Deprecate/remove the now-redundant `GET /v1/auth/companies/{id}` from `identity/router.py` **only if** nothing else depends on it — check for frontend usage before removing; if kept for backward compatibility within this same sprint, that's acceptable since nothing external consumes it yet.
- **Frontend Work:** `apps/web/src/app/(app)/settings/company/page.tsx` — the "Company Profile" screen (`files/24` §3.10 "Company settings"), a single form using Task 1.6.1 patterns, `ETag`/`If-Match` handled transparently inside the `useAppMutation` wrapper (Task 1.6.2) so individual screens don't hand-roll concurrency handling.
- **Database Work:** None beyond 2.1.1.
- **API Work:** `GET/PATCH /v1/companies/current` per §5.1.
- **Testing Requirements:** Integration test: concurrent `PATCH` with stale `If-Match` returns `409`; successful update produces an audit log entry with correct before/after.
- **Acceptance Criteria:** Screen matches Empty/Loading/Error/Success states in §3 spec for Company Profile below.
- **Estimated Complexity:** M

---

### Feature 2.6 — Legal Entity management

#### Task 2.6.1 — Legal Entity backend
- **Objective:** Expand the existing `legal_entity` stub table (currently `id, company_id, name, pan, gstin` per `scripts/sql/001_init_schema.sql`) to the full `files/08` §4 shape and build full CRUD.
- **Dependencies:** 2.1.2
- **Backend Work:** Migration adding: `registered_address TEXT`, `tan VARCHAR(20)`, `cin VARCHAR(30)`, `pf_code VARCHAR(30)`, `esi_code VARCHAR(30)`, `lwf_reg VARCHAR(30)`, `signatory_name VARCHAR(150)`, `signatory_designation VARCHAR(150)`, `signature_image_url TEXT`, `is_active BOOLEAN DEFAULT true`, `version INTEGER DEFAULT 1` (optimistic locking, consistent with `company`). `organisation/models.py::LegalEntity`. `organisation/schemas.py::LegalEntityCreate/Update/Read`. `organisation/service.py::LegalEntityService`-equivalent methods on `OrganisationService` (or a dedicated nested service class if the module grows large — implementer's call, consistent with keeping `service.py` as the module's one public interface per `02_Module_Standard.md`). `organisation/repository.py` — CRUD with `company_id` predicate on every query. `organisation/permissions.py::ORG_LEGAL_ENTITY_MANAGE = "ORG.LEGAL_ENTITY.MANAGE"`. Deactivation (soft delete via `is_active=false` / `deleted_at`) blocked if any active `branch` references it (FR-ORG-014 — "never hard-delete," blocking list returned in the error `details[]`).
- **Frontend Work:** None (this task).
- **Database Work:** Migration + RLS for `legal_entity` (already has `company_id`, confirm existing RLS block in `002_row_level_security.sql` still applies — it does, already listed).
- **API Work:** `GET/POST /v1/legal-entities`, `GET/PATCH/DELETE /v1/legal-entities/{id}` per §5.2.
- **Testing Requirements:** Unit: service-layer validation (PAN format regex, GSTIN format regex). Integration: full CRUD; deactivation blocked when a branch references it, with the blocking branch listed in the response.
- **Acceptance Criteria:** All `files/08` §4 `legal_entity` columns present; cross-tenant access to another company's legal entity returns 404.
- **Estimated Complexity:** M

#### Task 2.6.2 — Legal Entity frontend
- **Objective:** Build the Legal Entity list + form screens (`files/24` §3.10 "Legal entity list/form").
- **Dependencies:** 2.6.1, 1.2.3, 1.6.1
- **Backend Work:** None.
- **Frontend Work:** `apps/web/src/app/(app)/settings/legal-entities/page.tsx` (list, using `DataTable` from 1.2.3), `.../legal-entities/new/page.tsx`, `.../legal-entities/[id]/page.tsx` (edit). This screen is embedded as **part of** the "Configure Company" wizard step (Feature 2.4) — a company typically has exactly one legal entity at setup time, so the wizard step shows an inline single-entity form with an "Add another legal entity" affordance for multi-entity companies, rather than forcing every company through a separate list screen first.
- **Database Work:** None.
- **API Work:** Consumes 2.6.1.
- **Testing Requirements:** Component test for the form; E2E: create → appears in list → edit → deactivate blocked when referenced.
- **Acceptance Criteria:** Matches Empty/Loading/Error/Success states in §3 spec for Company Profile (Legal Entity is a sub-section of that screen spec, not separately specified, per the wizard-embedding decision above).
- **Estimated Complexity:** M


## Epic 3 — Organization Structure

**Goal:** Branch, Department, Designation, Grade, Employment Type — the org substrate every future module (Employee, Attendance, Leave, Payroll) keys against, per `docs/product/VERSION_1_ROADMAP.md` §6's hard sequencing constraint #2.

### Feature 3.1 — Branch (= Work Location, per D1) management

#### Task 3.1.1 — Branch backend
- **Objective:** Expand the existing `branch` stub (`id, company_id, legal_entity_id, name, state, timezone` per current schema) to the full `files/08` §4 shape and build full CRUD.
- **Dependencies:** 2.6.1 (branch FKs to legal_entity)
- **Backend Work:** Migration adding: `code VARCHAR(30)`, `address_line1 VARCHAR(200)`, `address_line2 VARCHAR(200)`, `city VARCHAR(100)`, `state_code VARCHAR(10)` (replaces free-text `state` — write a data migration step converting existing `state` values or, since this is pre-launch with only seed data, drop and recreate the column), `pincode VARCHAR(10)`, `latitude NUMERIC(9,6)`, `longitude NUMERIC(9,6)`, `geofence_radius_m INTEGER`, `holiday_calendar_id UUID NULL` (FK, added once `holiday_calendar` is expanded in Feature 4.1 — sequence this FK addition as a **follow-up migration in Feature 4.1**, not here, to avoid a forward reference; `branch` ships in this task without the FK, Feature 4.1 adds it), `week_off_pattern_id UUID NULL` (FK to new `week_off_pattern` table — same forward-reference handling: added when `week_off_pattern` is created in Task 3.1.3), `is_active BOOLEAN DEFAULT true`, `version INTEGER DEFAULT 1`. `organisation/models.py::Branch`. Full CRUD in `service.py`/`repository.py`. `permissions.py::ORG_BRANCH_MANAGE = "ORG.BRANCH.MANAGE"`. Deactivation blocked if referenced by an active `department` or (later) employee (FR-ORG-014).
- **Frontend Work:** None (this task).
- **Database Work:** Migration + confirm RLS (already covered).
- **API Work:** `GET/POST /v1/branches`, `GET/PATCH/DELETE /v1/branches/{id}` per §5.2.
- **Testing Requirements:** Unit: `state_code` validated against the ISO 3166-2:IN state list (a static constant — needed because state drives PT slab and holiday calendar per FR-ORG-004, even though PT/statutory computation itself is out of scope this sprint). Integration: full CRUD; geofence fields accept null (not every branch needs geofencing yet) and a valid radius when present.
- **Acceptance Criteria:** All `files/08` §4 `branch` columns present (holiday_calendar_id/week_off_pattern_id land via Feature 4.1/3.1.3 follow-ups); cross-tenant isolation verified.
- **Estimated Complexity:** M

#### Task 3.1.2 — Branch frontend
- **Objective:** Build Branch Management — list + form, doubling as the "Work Locations" screen per D1 (same component, no separate route needed beyond a possible `/settings/branches` being the canonical path; do not build `/settings/work-locations` as a duplicate route).
- **Dependencies:** 3.1.1, 1.2.3, 1.6.1
- **Backend Work:** None.
- **Frontend Work:** `apps/web/src/app/(app)/settings/branches/page.tsx` (list), `.../branches/new/page.tsx`, `.../branches/[id]/page.tsx`. Map-based address entry (`files/24` §3.10 "Branch list/form (with map)") — scoped down for this sprint to **manual lat/long entry fields** with a static map preview image (e.g., an embedded OpenStreetMap tile via a static URL pattern, no interactive map picker library) rather than a full interactive geofence-radius map editor (`files/24` §3.4 "Geofence map editor" is a separate, more complex screen scheduled for the Attendance sprint where geofencing is actually enforced against punches) — this sprint just needs to **store** the coordinates correctly.
- **Database Work:** None.
- **API Work:** Consumes 3.1.1.
- **Testing Requirements:** Component test for form validation (pincode format, lat/long range); E2E: create branch → appears in Departments' branch picker (cross-feature check with 3.2).
- **Acceptance Criteria:** Matches Empty/Loading/Error/Success states in §3 spec for Branch Management below.
- **Estimated Complexity:** M

#### Task 3.1.3 — Week-off pattern backend (supporting entity)
- **Objective:** Build `week_off_pattern` (`files/08` §4: `id, company_id, name, pattern JSONB, is_active`) since `branch` references it. Minimal CRUD, no dedicated screen this sprint — surfaced as a simple pattern picker (fixed weekly-off, e.g. "All Saturdays + Sundays off") inline within the Branch form, with only 2–3 pre-seeded patterns (Sun-only, Sat+Sun, Alternate-Saturdays) rather than a full pattern builder UI.
- **Dependencies:** 3.1.1
- **Backend Work:** `organisation/models.py::WeekOffPattern`. `organisation/service.py` — `list_week_off_patterns()` (read-only from the frontend's perspective this sprint; patterns are seeded, not user-authored, per the scope-down above), seeded on company registration (Task 2.1.3) alongside the other D8 defaults. Add the deferred `branch.week_off_pattern_id` FK from Task 3.1.1 in this task's migration.
- **Frontend Work:** A `<Select>` of the 2–3 seeded patterns embedded in the Branch form (Task 3.1.2) — no standalone screen.
- **Database Work:** Migration for `week_off_pattern` + the `branch.week_off_pattern_id` FK.
- **API Work:** `GET /v1/week-off-patterns` (list only, per §5.2).
- **Testing Requirements:** Unit: seed produces exactly the 2–3 documented patterns, idempotently.
- **Acceptance Criteria:** Branch form's week-off selector is populated and persists correctly.
- **Estimated Complexity:** S

---

### Feature 3.2 — Department management

#### Task 3.2.1 — Department backend
- **Objective:** Expand the existing `department` stub (`id, company_id, branch_id, name, code, parent_id`) to support the hierarchy rules in FR-ORG-005 (cycle rejection, max 5 levels) and the remaining `files/08` §4 columns.
- **Dependencies:** 3.1.1, 2.1.2
- **Backend Work:** Migration adding: `head_employee_id UUID NULL` (FK to `employee`, per D10 — no UI this sprint), `cost_centre_id UUID NULL` (FK to new `cost_centre` table — see Task 3.2.2), `is_active BOOLEAN DEFAULT true`, `version INTEGER DEFAULT 1`. `organisation/models.py::Department` — self-referential `parent_id` FK. `service.py::create_department()`/`update_department()` — **cycle detection**: before setting `parent_id`, walk up the candidate parent's ancestor chain (recursive query, depth-capped at 5 per FR-ORG-005) and reject if the new department's own id appears (`409 CONFLICT`, code `DEPARTMENT_CYCLE_DETECTED`); reject if depth would exceed 5. `GET /v1/departments/tree` — returns the full hierarchy as a nested structure (single recursive CTE query in `repository.py`, not N+1 application-side tree-walking). `permissions.py::ORG_DEPARTMENT_MANAGE`.
- **Frontend Work:** None (this task).
- **Database Work:** Migration.
- **API Work:** `GET/POST /v1/departments`, `GET/PATCH/DELETE /v1/departments/{id}`, `GET /v1/departments/tree` per §5.2.
- **Testing Requirements:** Unit: cycle-detection rejects a self-parent, a 2-hop cycle, and a 6th nesting level; accepts valid 5-level nesting. Integration: `tree` endpoint returns correctly nested JSON for a 3-level sample hierarchy.
- **Acceptance Criteria:** No department hierarchy can ever contain a cycle at the database-query level (defense in service layer; the FK itself cannot prevent cycles, so this is a mandatory application-level guard, tested explicitly).
- **Estimated Complexity:** L

#### Task 3.2.2 — Cost Centre backend (supporting entity)
- **Objective:** Build `cost_centre` (`files/08` §4: `id, company_id, code, name, gl_code`) since `department` references it. Minimal CRUD, no dedicated screen — a simple inline creatable `<Combobox>` within the Department form (create-on-the-fly, matching how lightweight lookups are typically handled, rather than a separate settings screen for what's a thin 3-field entity this sprint).
- **Dependencies:** 3.2.1
- **Backend Work:** `organisation/models.py::CostCentre`, minimal `service.py` methods (`list_cost_centres`, `create_cost_centre`). `permissions.py::ORG_COST_CENTRE_MANAGE`. Add the deferred `department.cost_centre_id` FK.
- **Frontend Work:** Inline creatable combobox in the Department form (Task 3.2.3).
- **Database Work:** Migration for `cost_centre` + `department.cost_centre_id` FK.
- **API Work:** `GET/POST /v1/cost-centres` per §5.2.
- **Testing Requirements:** Integration: create-on-the-fly from the department form's combobox round-trips correctly.
- **Acceptance Criteria:** No standalone Cost Centre screen exists — deliberately, per the scope-down above.
- **Estimated Complexity:** S

#### Task 3.2.3 — Department frontend
- **Objective:** Build the Department tree screen (`files/24` §3.10 "Department tree") — this is one of the two places (with Org Chart, deferred to Sprint 4 since it visualizes reporting lines that don't exist yet) where a tree visualization is the primary UI, not a flat table.
- **Dependencies:** 3.2.1, 3.2.2, 1.2.3
- **Backend Work:** None.
- **Frontend Work:** `apps/web/src/app/(app)/settings/departments/page.tsx` — tree view (expand/collapse per node, per `files/24` §4.1-style density patterns) built on `GET /v1/departments/tree`, with inline "Add sub-department" per node and a form drawer (shadcn `Sheet`) for create/edit rather than a full page navigation, since department edits are typically quick single-field changes made while looking at the tree.
- **Database Work:** None.
- **API Work:** Consumes 3.2.1, 3.2.2.
- **Testing Requirements:** Component test: tree renders correct nesting from a sample API response; attempting to drag/assign a parent that would create a cycle is prevented client-side too (defense in depth — the real guard is server-side per 3.2.1, but the UI should not offer an obviously-invalid option in the parent picker, i.e. a department's own descendants are excluded from its own "choose parent" combobox options).
- **Acceptance Criteria:** Matches Empty/Loading/Error/Success states in §3 spec for Department Management below.
- **Estimated Complexity:** L

---

### Feature 3.3 — Designation & Grade management

#### Task 3.3.1 — Grade backend
- **Objective:** Expand the existing `grade` stub (`id, company_id, code, name, rank`) to the full `files/08` §4 shape. **Built before Designation** since Designation FKs to it (per D2).
- **Dependencies:** 2.1.2
- **Backend Work:** Migration adding: `level INTEGER` (rename/repurpose `rank` → `level` if semantically identical, or add `level` alongside and deprecate `rank` — implementer's call; prefer a clean rename via `op.alter_column` since `rank` has no real data yet), `min_ctc BIGINT NULL` (minor units per ADR-0006, nullable since grade can exist before compensation bands are decided), `max_ctc BIGINT NULL`, `notice_period_days INTEGER NULL`, `probation_days INTEGER NULL`, `leave_policy_id UUID NULL` (FK — added as a follow-up in Feature 4.3 once `leave_policy` exists, same forward-reference pattern as branch/holiday_calendar), `approval_limit BIGINT NULL` (minor units), `is_active BOOLEAN DEFAULT true`, `version INTEGER DEFAULT 1`. `organisation/models.py::Grade`. Full CRUD. `permissions.py::ORG_GRADE_MANAGE`.
- **Frontend Work:** None (this task).
- **Database Work:** Migration.
- **API Work:** `GET/POST /v1/grades`, `GET/PATCH/DELETE /v1/grades/{id}` per §5.2.
- **Testing Requirements:** Unit: `min_ctc <= max_ctc` validated at the service layer when both present. Integration: full CRUD.
- **Acceptance Criteria:** `leave_policy_id` FK deferred correctly to Feature 4.3 without blocking this task.
- **Estimated Complexity:** M

#### Task 3.3.2 — Designation backend
- **Objective:** Expand the existing `designation` stub (`id, company_id, department_id, title`) to the full `files/08` §4 shape.
- **Dependencies:** 3.3.1, 3.2.1
- **Backend Work:** Migration adding: `code VARCHAR(30)`, `grade_id UUID NULL` (FK to `grade`), `next_designation_id UUID NULL` (self FK, per D10 — no UI this sprint; `jd_document_id` explicitly **not** added — no document-management module exists to reference, deferred to whenever that module ships, not tracked as a forward-reference placeholder since unlike the others there's no concrete near-term consumer), `is_active BOOLEAN DEFAULT true`, `version INTEGER DEFAULT 1`. `organisation/models.py::Designation`. Full CRUD. `permissions.py::ORG_DESIGNATION_MANAGE`. Deactivation blocked if referenced by an active employee (future) — for now, blocked if `next_designation_id` of another designation points to it (can't remove a career-path target still in use).
- **Frontend Work:** None (this task).
- **Database Work:** Migration.
- **API Work:** `GET/POST /v1/designations`, `GET/PATCH/DELETE /v1/designations/{id}` per §5.2.
- **Testing Requirements:** Integration: full CRUD; `department_id` optional (per `files/17` FR-ORG-006 "department (optional)" — a designation can be department-agnostic, e.g. "CEO").
- **Acceptance Criteria:** `department_id` is genuinely nullable end-to-end (schema, service, form).
- **Estimated Complexity:** M

#### Task 3.3.3 — Designation & Grade frontend
- **Objective:** Build both list screens (`files/24` §3.10 "Designation list," "Grade list") as one combined wizard step ("Designations & Grades") since they're tightly coupled and configured together in practice.
- **Dependencies:** 3.3.1, 3.3.2, 1.2.3
- **Backend Work:** None.
- **Frontend Work:** `apps/web/src/app/(app)/settings/designations/page.tsx` (list + create/edit drawer, includes an inline Grade sub-tab or split-pane so both are configured without leaving the screen — implementer's call on exact layout, but both entities must be reachable from one wizard step per the sprint goal's flow).
- **Database Work:** None.
- **API Work:** Consumes 3.3.1, 3.3.2.
- **Testing Requirements:** Component test for both forms; E2E: create grade → immediately selectable in designation form's grade picker.
- **Acceptance Criteria:** Matches Empty/Loading/Error/Success states in §3 spec for Designation Management below.
- **Estimated Complexity:** M

---

### Feature 3.4 — Employment Types management

#### Task 3.4.1 — Employment Type backend
- **Objective:** Build the new `employment_type` table per `files/08` §4 (`id, company_id, code, name, is_pf_applicable, is_esi_applicable, is_gratuity_eligible, is_leave_eligible, is_ot_eligible`) — this table does not exist yet in any form (unlike the others, which were Prisma-era stubs).
- **Dependencies:** 2.1.2
- **Backend Work:** Migration creating `employment_type` (add `is_active BOOLEAN DEFAULT true`, `version INTEGER DEFAULT 1` per the standard column conventions, plus `deleted_at`). `organisation/models.py::EmploymentType`. Full CRUD. `permissions.py::ORG_EMPLOYMENT_TYPE_MANAGE`. Seed two rows on registration per D8 (`PERMANENT`, `PROBATION`) with sensible statutory-flag defaults (`is_pf_applicable=true, is_esi_applicable=true, is_gratuity_eligible=true, is_leave_eligible=true, is_ot_eligible=false` for `PERMANENT`; same but `is_gratuity_eligible=false` for `PROBATION` — gratuity eligibility typically starts post-confirmation).
- **Frontend Work:** None (this task).
- **Database Work:** New migration + RLS (new tenant table → add to the `FOREACH tbl IN ARRAY [...]` list in a new RLS migration script, following the existing `002_row_level_security.sql` pattern — **every new tenant table this epic and Epic 4 introduce must be added to this array**, tracked centrally in §4.3 below).
- **API Work:** `GET/POST /v1/employment-types`, `GET/PATCH/DELETE /v1/employment-types/{id}` per §5.2.
- **Testing Requirements:** Integration: seed produces exactly `PERMANENT` + `PROBATION` on registration; full CRUD; the five boolean statutory flags round-trip correctly.
- **Acceptance Criteria:** Table is a clean new build (not a stub expansion) — should reflect current model conventions from day one (typed `Mapped[...]`, all standard audit columns).
- **Estimated Complexity:** M

#### Task 3.4.2 — Employment Type frontend
- **Objective:** Build the Employment Types screen — a simple list + form, no hierarchy or complex relationships.
- **Dependencies:** 3.4.1, 1.2.3
- **Backend Work:** None.
- **Frontend Work:** `apps/web/src/app/(app)/settings/employment-types/page.tsx` — list with the 5 boolean flags shown as compact badges/icons in the table (not 5 separate columns of checkmarks, which would be visually noisy — a single "Statutory applicability" column expandable on hover/click showing the breakdown), create/edit in a drawer.
- **Database Work:** None.
- **API Work:** Consumes 3.4.1.
- **Testing Requirements:** Component test for the form; E2E: seeded `PERMANENT`/`PROBATION` visible immediately after registration without manual creation.
- **Acceptance Criteria:** Matches Empty/Loading/Error/Success states in §3 spec for Employment Types below.
- **Estimated Complexity:** S


## Epic 4 — Scheduling & Policy Foundation

**Goal:** Holiday Calendar, Shift master, Leave Policy config, Payroll Policy config — the configuration layer Attendance/Leave/Payroll (Sprints 7–9) will consume, built here as pure setup with no processing engine (per D3–D5).

### Feature 4.1 — Holiday Calendar management

#### Task 4.1.1 — Holiday Calendar backend
- **Objective:** Expand the existing `holiday_calendar` (`id, company_id, name`) and `holiday` (`id, calendar_id, date, name, is_optional`) stubs to the full `files/08` §4 shape.
- **Dependencies:** 3.1.1
- **Backend Work:** Migration: `holiday_calendar` adds `year INTEGER NOT NULL`, `state_code VARCHAR(10) NULL` (per-state calendars, per FR-ORG-008), `is_active BOOLEAN DEFAULT true`. `holiday` replaces `is_optional BOOLEAN` with `type VARCHAR(20)` (`FIXED`/`OPTIONAL`/`RESTRICTED`, `CHECK` constraint per `docs/database/Database_Architecture.md` §1 rule 4 — StrEnum mapped to VARCHAR+CHECK, never a native PG enum) and adds `is_paid BOOLEAN DEFAULT true`. `organisation/models.py::HolidayCalendar`, `Holiday`. `service.py::create_calendar()`, `add_holiday()`, `remove_holiday()` — reject duplicate dates within the same calendar. Add the deferred `branch.holiday_calendar_id` FK from Task 3.1.1 in this task's migration. `permissions.py::ORG_HOLIDAY_MANAGE`.
- **Frontend Work:** None (this task).
- **Database Work:** Migration + RLS for both tables (already tenant tables via `company_id`/parent join per existing RLS script pattern — `holiday` has no direct `company_id`, relies on `calendar_id` join + app predicate, matching the documented exception in `docs/database/Database_Architecture.md` §3 for tables "one join away").
- **API Work:** `GET/POST /v1/holiday-calendars`, `POST /v1/holiday-calendars/{id}/holidays`, `GET /v1/holidays?year=&branch_id=` per §5.3.
- **Testing Requirements:** Unit: duplicate-date rejection within a calendar. Integration: `AC-ORG-008.1` from `files/17` — a Kerala branch and a Karnataka branch each see their own state holidays plus shared national ones (verify via the `GET /v1/holidays?branch_id=` query resolving through `branch.holiday_calendar_id` → `holiday_calendar.state_code` correctly, plus a company-wide/`state_code IS NULL` calendar unioned in for national holidays).
- **Acceptance Criteria:** The `AC-ORG-008.1` acceptance test from the source SRS passes as an automated integration test, not just manually verified.
- **Estimated Complexity:** L

#### Task 4.1.2 — Default holiday calendar seed
- **Objective:** On company registration, seed one empty current-year, company-wide (`state_code NULL`) holiday calendar per D8, so the wizard step opens with something to add to rather than a cold "no calendar exists" state.
- **Dependencies:** 4.1.1, 2.1.3
- **Backend Work:** Extend `OrganisationService.register_company()` (or a dedicated `seed_defaults()` called from it) to create the calendar. Do **not** pre-populate actual national holiday dates (no reliable static source committed to the repo for this) — the calendar exists, empty, ready for the admin to populate; this is explicitly narrower than "seed India's national holidays," which is out of scope this sprint (flag as a candidate content-data task for a future sprint, not silently implied as done).
- **Frontend Work:** None.
- **Database Work:** None beyond 4.1.1.
- **API Work:** None (internal to registration).
- **Testing Requirements:** Integration test (extends 2.1.3's test): registration produces exactly one `holiday_calendar` row, `year = current_year`, zero `holiday` rows.
- **Acceptance Criteria:** Explicit in code/comments that holiday dates are NOT pre-seeded — avoids a future session assuming national holidays already exist.
- **Estimated Complexity:** XS

#### Task 4.1.3 — Holiday Calendar frontend
- **Objective:** Build the Holiday Calendar screen (`files/24` §3.5 "Holiday calendar," "Holiday form").
- **Dependencies:** 4.1.1, 4.1.2, 1.2.3
- **Backend Work:** None.
- **Frontend Work:** `apps/web/src/app/(app)/settings/holiday-calendar/page.tsx` — calendar-year view (a simple date-list grouped by month is acceptable for v1, a full calendar-grid widget is a nice-to-have, not required) with an "Add holiday" form (date, name, type, is_paid) and a state-code selector to create additional per-state calendars beyond the default company-wide one.
- **Database Work:** None.
- **API Work:** Consumes 4.1.1.
- **Testing Requirements:** Component test for the add-holiday form; E2E: add a holiday → appears in the list, correctly attributed to its calendar's year/state.
- **Acceptance Criteria:** Matches Empty/Loading/Error/Success states in §3 spec for Holiday Calendar below.
- **Estimated Complexity:** M

---

### Feature 4.2 — Shift management (master only, per D5)

#### Task 4.2.1 — Shift backend
- **Objective:** Build the new `shift` table per FR-ATT-001, scoped to the master definition only (no assignment/roster, per D5).
- **Dependencies:** 3.1.1 (shift references `week_off_pattern`)
- **Backend Work:** New table (this module owns it as org-setup config; the future `attendance` module will own roster/assignment and reference `shift` by id, an allowed cross-module FK since it's a read reference, not a repository import): `id, company_id, name VARCHAR(100), code VARCHAR(30), start_time TIME, end_time TIME, break_minutes_paid INTEGER DEFAULT 0, break_minutes_unpaid INTEGER DEFAULT 0, grace_in_minutes INTEGER DEFAULT 0, grace_out_minutes INTEGER DEFAULT 0, half_day_threshold_hours NUMERIC(4,2), min_hours_full_day NUMERIC(4,2), is_night_shift BOOLEAN DEFAULT false, is_cross_midnight BOOLEAN DEFAULT false, week_off_pattern_id UUID NULL FK, is_ot_eligible BOOLEAN DEFAULT false, is_active BOOLEAN DEFAULT true, deleted_at, version`. `organisation/models.py::Shift`. Full CRUD. `permissions.py::ORG_SHIFT_MANAGE`. Validation: `end_time` before `start_time` is **valid** (represents a cross-midnight shift) only if `is_cross_midnight=true`, otherwise rejected as `422`.
- **Frontend Work:** None (this task).
- **Database Work:** New migration + RLS.
- **API Work:** `GET/POST /v1/shifts`, `GET/PATCH/DELETE /v1/shifts/{id}` per §5.3.
- **Testing Requirements:** Unit: cross-midnight validation rule; half-day threshold must be less than min-hours-full-day when both present. Integration: full CRUD.
- **Acceptance Criteria:** No roster/assignment table or endpoint exists this sprint — confirmed absent, not just unbuilt (i.e., don't accidentally create `shift_roster` as a side effect of following the DB architecture doc too literally; that table is explicitly Sprint 7 per D5).
- **Estimated Complexity:** M

#### Task 4.2.2 — Default shift seed
- **Objective:** Seed one default "General Shift" (09:00–18:00, standard) on registration per D8.
- **Dependencies:** 4.2.1, 2.1.3
- **Backend Work:** Extend the registration seeding from Task 4.1.2's pattern.
- **Frontend Work:** None.
- **Database Work:** None beyond 4.2.1.
- **API Work:** None (internal).
- **Testing Requirements:** Integration test: registration produces exactly one `shift` row with the documented defaults.
- **Acceptance Criteria:** Seed is idempotent if registration logic is ever re-run for the same company (defensive, matching `seed/bootstrap.py`'s existing idempotency pattern).
- **Estimated Complexity:** XS

#### Task 4.2.3 — Shift frontend
- **Objective:** Build the Shift Management screen (`files/24` §3.4 "Shift list," "Shift form" — master only, roster/roster-calendar/roster-pattern-generator screens explicitly **not** built this sprint per D5).
- **Dependencies:** 4.2.1, 4.2.2, 1.2.3
- **Backend Work:** None.
- **Frontend Work:** `apps/web/src/app/(app)/settings/shifts/page.tsx` — list + form with a visual timeline preview of the shift window (start/end/breaks as a simple horizontal bar, not a complex scheduling widget).
- **Database Work:** None.
- **API Work:** Consumes 4.2.1.
- **Testing Requirements:** Component test for cross-midnight form validation (client-side mirror of the server rule); E2E: seeded General Shift visible post-registration.
- **Acceptance Criteria:** Matches Empty/Loading/Error/Success states in §3 spec for Shift Management below.
- **Estimated Complexity:** M

---

### Feature 4.3 — Leave Policy setup (configuration only, per D3)

#### Task 4.3.1 — Leave Type backend
- **Objective:** Build `leave_type` per FR-LEV-001/002, full field set, no ledger/accrual-job logic (that's Sprint 8).
- **Dependencies:** 3.3.1 (leave types can reference grades for applicability), 3.4.1 (and employment types)
- **Backend Work:** New table: `id, company_id, code, name, is_paid BOOLEAN, accrual_method VARCHAR(20) [MONTHLY/QUARTERLY/YEARLY/ON_JOINING/NONE], accrual_rate NUMERIC(6,3), pro_rata_on_joining BOOLEAN, pro_rata_on_exit BOOLEAN, max_balance_cap NUMERIC(6,2) NULL, carry_forward_allowed BOOLEAN, carry_forward_cap NUMERIC(6,2) NULL, encashable BOOLEAN, encashment_basis VARCHAR(20) NULL [BASIC/BASIC_DA/GROSS], lapse_rule VARCHAR(20) NULL, negative_balance_allowed BOOLEAN DEFAULT false, negative_balance_limit NUMERIC(6,2) NULL, applicable_gender VARCHAR(10) NULL [ANY/MALE/FEMALE], applicable_employment_type_ids UUID[] NULL, applicable_grade_ids UUID[] NULL, min_days_per_application NUMERIC(4,2) NULL, max_days_per_application NUMERIC(4,2) NULL, notice_days_required INTEGER NULL, backdated_allowed BOOLEAN DEFAULT false, backdated_limit_days INTEGER NULL, requires_document_after_days INTEGER NULL, counts_sandwich_holidays BOOLEAN DEFAULT false, half_day_allowed BOOLEAN DEFAULT true, hourly_leave_allowed BOOLEAN DEFAULT false, is_active, deleted_at, version`. **Note on array columns:** `applicable_employment_type_ids`/`applicable_grade_ids` as native Postgres `UUID[]` is an accepted deviation from "no arrays for core business data" since these are simple applicability filters, not relational data requiring joins/reports — equivalent in spirit to `scope_ref_ids UUID[]` already used on `user_role` (`files/08` §3.4). `organisation/models.py::LeaveType`. Full CRUD. `permissions.py::LEAVE_TYPE_MANAGE = "LEAVE.TYPE.MANAGE"` (namespaced `LEAVE.*` per `files/19` §3.3 even though the `leave` module itself doesn't exist until Sprint 8 — the permission catalogue is forward-consistent with the eventual module boundary, living in `organisation` module's `permissions.py` for now with an explicit code comment noting the future home).
- **Frontend Work:** None (this task).
- **Database Work:** New migration + RLS.
- **API Work:** `GET/POST /v1/leave-types`, `GET/PATCH/DELETE /v1/leave-types/{id}` per §5.4.
- **Testing Requirements:** Integration: full CRUD; array-field filters round-trip correctly.
- **Acceptance Criteria:** No `leave_ledger`, `leave_application`, or accrual-job code exists as a side effect of building this — confirmed scoped to master data only.
- **Estimated Complexity:** L

#### Task 4.3.2 — Seeded Indian leave types
- **Objective:** Seed the 12 statutory/common Indian leave types from FR-LEV-002 on registration, per D8: Casual (CL), Sick (SL), Earned/Privilege (EL/PL), Loss of Pay (LOP), Maternity (26 weeks), Paternity, Bereavement, Marriage, Comp-off, Restricted Holiday, Sabbatical, Vacation.
- **Dependencies:** 4.3.1, 2.1.3
- **Backend Work:** A static seed-data constant (`organisation/seed_data.py::DEFAULT_LEAVE_TYPES`) with sensible defaults per type (e.g., CL: 12/year monthly accrual, non-encashable; EL/PL: 15/year, carry-forward up to 30, encashable; LOP: unpaid, no accrual; Maternity: 182 days (26 weeks) fixed, ON_JOINING-equivalent one-time grant model — flagged as `accrual_method=NONE` with a manual-grant note, since true maternity eligibility logic is a Leave-module concern, not this sprint's). Wired into `register_company()`'s default-seeding step alongside 4.1.2/4.2.2.
- **Frontend Work:** None.
- **Database Work:** None beyond 4.3.1.
- **API Work:** None (internal).
- **Testing Requirements:** Integration: registration produces exactly the 12 documented leave types with the documented default field values — this is a content-correctness test, not just a count check.
- **Acceptance Criteria:** All 12 types from FR-LEV-002 present by exact name/code; no 13th "just in case" type added.
- **Estimated Complexity:** S

#### Task 4.3.3 — Leave Policy (bundle) + assignment backend
- **Objective:** Build `leave_policy` and its assignment mechanism per `files/08` §7.2 ("`leave_policy` / `leave_policy_assignment`") — a named bundle of leave types (with optional per-policy overrides) assignable to org segments (grade/employment-type/department/company-wide).
- **Dependencies:** 4.3.1
- **Backend Work:** New tables: `leave_policy (id, company_id, name, description, is_default BOOLEAN, is_active, deleted_at, version)`; `leave_policy_item (id, leave_policy_id FK, leave_type_id FK, override_accrual_rate NUMERIC NULL, override_max_balance_cap NUMERIC NULL, UNIQUE(leave_policy_id, leave_type_id))`; `leave_policy_assignment (id, company_id, leave_policy_id FK, scope_type VARCHAR(20) [COMPANY/GRADE/EMPLOYMENT_TYPE/DEPARTMENT], scope_ref_id UUID NULL, effective_from DATE, is_active)`. `organisation/service.py` — `create_leave_policy()`, `add_leave_type_to_policy()`, `assign_policy()` (reject overlapping assignments for the same `scope_type`+`scope_ref_id` combination with `effective_from` overlap — simpler than full effective-dating since this is a config-time assignment, not a payroll-grade time-series; a straightforward "one active assignment per scope at a time" uniqueness check is sufficient this sprint, not a full `EXCLUDE USING gist` — flagged as an acceptable simplification since assignment *history* isn't a requirement yet). Add the deferred `grade.leave_policy_id` FK from Task 3.3.1 here **if** the single-FK-per-grade model is kept — re-evaluate at implementation time whether `grade.leave_policy_id` (single) or `leave_policy_assignment` (flexible, multi-scope) is the actual assignment mechanism; **decision: use `leave_policy_assignment` as the real mechanism** (matches `files/08`'s own naming) and treat `grade.leave_policy_id` from the source table spec as **not implemented** — drop it from Task 3.3.1's deferred-FK list rather than adding two competing assignment mechanisms. Document this override inline in Task 3.3.1 when implemented.
- **Frontend Work:** None (this task).
- **Database Work:** New migrations + RLS for all three tables.
- **API Work:** `GET/POST /v1/leave-policies`, `GET/PATCH/DELETE /v1/leave-policies/{id}`, `POST /v1/leave-policies/{id}/items`, `POST /v1/leave-policies/{id}/assignments` per §5.4.
- **Testing Requirements:** Integration: create policy → add 3 leave types with one override → assign to a grade → assert `GET` on the policy returns the resolved (overridden) values; overlapping assignment to the same scope rejected.
- **Acceptance Criteria:** `grade.leave_policy_id` is explicitly **not** added as a column (superseded by `leave_policy_assignment`) — this must be reflected as a correction note against Task 3.3.1's original deferred-column list, not silently diverge from it.
- **Estimated Complexity:** L

#### Task 4.3.4 — Leave Policy frontend
- **Objective:** Build Leave Types + Leave Policy screens (`files/24` §3.5 "Leave types list," "Leave type form," "Leave policy list," "Leave policy form") as one wizard step ("Leave Policies") covering both, since a policy is meaningless without its constituent types.
- **Dependencies:** 4.3.1, 4.3.2, 4.3.3, 1.2.3
- **Backend Work:** None.
- **Frontend Work:** `apps/web/src/app/(app)/settings/leave-policies/page.tsx` — tabbed or split view: "Leave Types" tab (list of the 12 seeded + custom ones, edit form with the full field set from 4.3.1 grouped into `FormSection`s per Task 1.6.1: Eligibility, Accrual, Balance & Carry-forward, Application Rules), "Policies" tab (policy list, item picker, assignment UI — a simple "assign to: [scope type] [scope value]" form, not a drag-and-drop builder).
- **Database Work:** None.
- **API Work:** Consumes 4.3.1, 4.3.3.
- **Testing Requirements:** Component tests for both forms (the leave-type form is the most field-dense form in this sprint — prioritize solid section grouping and validation test coverage here). E2E: seeded types visible, create a policy, assign to a grade.
- **Acceptance Criteria:** Matches Empty/Loading/Error/Success states in §3 spec for Leave Policy below.
- **Estimated Complexity:** L

---

### Feature 4.4 — Payroll Policy setup (configuration only, per D4)

#### Task 4.4.1 — Payroll Policy backend
- **Objective:** Build `payroll_policy` per FR-ORG-009 — pay cycle, cut-off, pay-date rule. No salary components/structures (Sprint 9).
- **Dependencies:** 2.1.2
- **Backend Work:** New table: `id, company_id, name VARCHAR(100), pay_cycle VARCHAR(20) [CALENDAR_MONTH/26_TO_25/CUSTOM], custom_cycle_start_day INTEGER NULL (used only if pay_cycle=CUSTOM), payroll_cutoff_day INTEGER, pay_date_rule VARCHAR(20) [LAST_WORKING_DAY/FIXED_DAY], fixed_pay_day INTEGER NULL (used only if pay_date_rule=FIXED_DAY), holiday_shift_rule VARCHAR(20) [BEFORE/AFTER] NULL, is_active BOOLEAN DEFAULT true, deleted_at, version`. Exactly one active `payroll_policy` per company enforced at the service layer (partial unique index `WHERE is_active AND deleted_at IS NULL`) — multiple *inactive/historical* policies may exist, but only one governs at a time (this sprint doesn't need multi-policy-per-segment like Leave Policy does; payroll cycle is typically company-wide). `organisation/models.py::PayrollPolicy`. `permissions.py::PAYROLL_POLICY_MANAGE = "PAYROLL.POLICY.MANAGE"` (namespaced `PAYROLL.*` per the same forward-consistency reasoning as Task 4.3.1's `LEAVE.*` codes).
- **Frontend Work:** None (this task).
- **Database Work:** New migration + RLS + the partial unique index.
- **API Work:** `GET/PUT /v1/payroll-policy` (singular resource per company, `PUT` not `POST` since it's create-or-replace-the-one-active-policy — a deliberate deviation from the standard `POST` collection pattern, justified because this is genuinely a singleton config resource, not a list) per §5.5.
- **Testing Requirements:** Unit: `CUSTOM` cycle requires `custom_cycle_start_day`; `FIXED_DAY` pay-date rule requires `fixed_pay_day`; both validated as mutually-conditional-required fields. Integration: only one active policy per company enforced even under concurrent creation attempts.
- **Acceptance Criteria:** No `salary_component`, `salary_structure`, or `statutory_master` table created as scope creep from reading `files/08` §8 too broadly — confirmed absent.
- **Estimated Complexity:** M

#### Task 4.4.2 — Payroll Policy frontend
- **Objective:** Build the Payroll Policy screen — a single settings form (not a list, per the singleton design in 4.4.1).
- **Dependencies:** 4.4.1, 1.6.1
- **Backend Work:** None.
- **Frontend Work:** `apps/web/src/app/(app)/settings/payroll-policy/page.tsx` — one form, conditional fields shown/hidden based on `pay_cycle`/`pay_date_rule` selection (matching the backend's mutually-conditional validation).
- **Database Work:** None.
- **API Work:** Consumes 4.4.1.
- **Testing Requirements:** Component test: conditional field visibility toggles correctly; E2E: save → reload → values persist.
- **Acceptance Criteria:** Matches Empty/Loading/Error/Success states in §3 spec for Payroll Policy below.
- **Estimated Complexity:** S

---

### Feature 4.5 — Number Series (supporting, per D7)

#### Task 4.5.1 — Number Series backend
- **Objective:** Build the race-safe `number_series` allocator per `files/08` §4's explicit note: "allocation uses `UPDATE ... RETURNING` inside the same transaction... never `SELECT max()+1`."
- **Dependencies:** 2.1.2
- **Backend Work:** New table: `id, company_id, entity_type VARCHAR(30) [seeded with EMPLOYEE_CODE only, per D7], prefix VARCHAR(10), separator VARCHAR(3) DEFAULT '-', current_number INTEGER DEFAULT 0, padding INTEGER DEFAULT 4, reset_rule VARCHAR(10) [NEVER/YEARLY], last_reset_at TIMESTAMPTZ NULL`. `organisation/repository.py::allocate_next_number(entity_type)` — implemented as `UPDATE number_series SET current_number = current_number + 1 WHERE company_id = :cid AND entity_type = :type RETURNING current_number`, executed via SQLAlchemy Core `Update(...).returning(...)` against the async session, **not** the ORM identity-map path, exactly per the documented pattern. `permissions.py::ORG_NUMBER_SERIES_MANAGE`. Seed one `EMPLOYEE_CODE` row on registration (default prefix `"EMP"`, separator `"-"`, padding `4` → produces `EMP-0001`).
- **Frontend Work:** None (this task) — this sprint exposes only a settings form to view/edit the prefix/padding/reset-rule, not the allocation call itself (that's consumed by Sprint 4's employee-creation flow).
- **Database Work:** New migration + RLS.
- **API Work:** `GET/PATCH /v1/number-series` per §5.1.
- **Testing Requirements:** **Concurrency test** (matches `AC-ORG-011.1` from `files/17`): 50 concurrent `allocate_next_number()` calls against the same series produce 50 unique, sequential, gap-free numbers — implemented with `asyncio.gather` over 50 concurrent session/transaction pairs against a real (testcontainer) Postgres, not mocked, since this is precisely the kind of race the `SELECT max()+1` anti-pattern would fail.
- **Acceptance Criteria:** `AC-ORG-011.1` passes as an automated test, exactly as specified in the source SRS.
- **Estimated Complexity:** M

#### Task 4.5.2 — Number Series settings (frontend, minimal)
- **Objective:** A small settings panel to view/edit the `EMPLOYEE_CODE` series' prefix/separator/padding — embedded as a section within the Company Profile screen (2.5.1), not a standalone wizard step (it's a minor, rarely-touched setting, doesn't warrant its own step in the sprint goal's flow, which doesn't mention it).
- **Dependencies:** 4.5.1, 2.5.1
- **Backend Work:** None.
- **Frontend Work:** A `<FormSection title="Employee ID Format">` block added to `apps/web/src/app/(app)/settings/company/page.tsx`.
- **Database Work:** None.
- **API Work:** Consumes 4.5.1.
- **Testing Requirements:** Component test: editing prefix/padding persists and reflects in a preview string (e.g., "Preview: EMP-0001").
- **Acceptance Criteria:** No allocation-triggering UI this sprint — view/edit config only.
- **Estimated Complexity:** XS


## Epic 5 — Company Dashboard

**Goal:** The Company Admin dashboard variant (`files/24` §3.2, one of six) with real aggregates from Epics 2–4 — the screen the sprint demo script ends on.

### Feature 5.1 — Dashboard backend

#### Task 5.1.1 — Dashboard summary endpoint
- **Objective:** One aggregation endpoint returning the counts and setup-completion state the dashboard needs, computed server-side (not N+1 client calls to every list endpoint).
- **Dependencies:** Every Epic 3/4 backend task (counts branches, departments, designations, employment types, holiday calendars, shifts, leave types, leave policies, whether a payroll policy exists), 2.3.1 (setup progress)
- **Backend Work:** `organisation/schemas.py::CompanyDashboardSummary` (`branch_count, department_count, designation_count, employment_type_count, holiday_calendar_count, shift_count, leave_type_count, leave_policy_count, has_payroll_policy: bool, employee_count: int` — hardcoded `0` this sprint via a direct count against the (currently unused) `employee` table, correct and forward-compatible once Sprint 4 populates it, `setup_progress: CompanySetupProgressSummary`). `service.py::get_dashboard_summary()` — a handful of `SELECT COUNT(*)` queries, each with the standard `company_id` predicate; acceptable as separate queries (not a mega-join) since these are cheap indexed counts, not a performance-sensitive path this sprint.
- **Frontend Work:** None (this task).
- **Database Work:** None (read-only aggregation over existing tables).
- **API Work:** `GET /v1/dashboards/company` per §5.6.
- **Testing Requirements:** Integration test: seed a company with known counts of each entity, assert the summary response matches exactly; verify cross-tenant isolation (a second company's data never leaks into the count).
- **Acceptance Criteria:** `employee_count` is always `0` this sprint (correct, not a bug) since Employee Management doesn't exist until Sprint 4 — documented in the response schema's field description so it isn't mistaken for a defect.
- **Estimated Complexity:** M

---

### Feature 5.2 — Dashboard frontend

#### Task 5.2.1 — Company Admin dashboard screen
- **Objective:** Build `/dashboard` per `files/24` §3.2 "Company Admin" dashboard variant, scoped to what this sprint's data supports — headcount/attrition/compliance/payroll-status widgets from the full spec are **not** buildable yet (no employees, no attendance, no payroll) and are explicitly deferred; this sprint's dashboard shows **org-setup completion and structure counts** instead, which is the honest available content.
- **Dependencies:** 5.1.1, 1.4.3, 1.2.3
- **Backend Work:** None.
- **Frontend Work:** `apps/web/src/app/(app)/dashboard/page.tsx` — a card grid: setup-completion progress card (links back to `/setup`), and one stat card per count from 5.1.1 (Branches, Departments, Designations, Employment Types, Holiday Calendars, Shifts, Leave Types, Leave Policies, Payroll Policy configured Y/N), each card linking to its respective settings screen. Uses the `MoneyDisplay`/`StatusPill` primitives from 1.2.3 where relevant (e.g., a status pill for "Payroll Policy: Configured/Not configured").
- **Database Work:** None.
- **API Work:** Consumes 5.1.1.
- **Testing Requirements:** Component test: cards render correct counts from mocked data; zero-state (brand-new company, all counts effectively at their seeded defaults) doesn't look broken. E2E: this is the final screen of the sprint's demo script — confirm the full registration → wizard → dashboard flow lands here correctly with live data.
- **Acceptance Criteria:** Matches Empty/Loading/Error/Success states in §3 spec for Company Dashboard below. No placeholder/mock numbers anywhere on the screen.
- **Estimated Complexity:** M

---

## Epic 6 — Testing & Quality Gates

**Goal:** Suite-level and cross-cutting testing that only makes sense once every feature above exists — individual unit/integration tests are already mandatory per-task (`docs/development/FastAPI_Development_Standards.md` §6 coverage rule) and are not repeated here.

### Feature 6.1 — Backend test suite completion

#### Task 6.1.1 — RBAC permission-matrix test for this sprint's catalogue
- **Objective:** Extend the RBAC test suite (`files/19` §8 requirement 1) to cover every permission code introduced in §6 below — for every (role, endpoint) pair, assert expected allow/deny. This sprint only has one role (`COMPANY_ADMIN`, per D12), so the matrix is narrow but must still be explicit and automated, not assumed.
- **Dependencies:** All Epic 2–5 backend tasks complete.
- **Backend Work:** `apps/api/tests/security/test_permission_matrix_sprint3.py` — parametrized test iterating every new endpoint × `COMPANY_ADMIN` (expect allow) × a user with zero permissions (expect deny, `403`).
- **Frontend Work:** None.
- **Database Work:** None.
- **API Work:** None (test only).
- **Testing Requirements:** This task **is** the testing requirement.
- **Acceptance Criteria:** Every endpoint in §5's catalogue appears in the matrix exactly once; no endpoint is reachable without its declared permission.
- **Estimated Complexity:** M

#### Task 6.1.2 — Cross-tenant isolation suite for new tables
- **Objective:** Extend the cross-tenant leakage suite (pattern established in `apps/api/tests/integration/auth/test_auth_security.py`) to cover every new tenant table from §4.
- **Dependencies:** All Epic 2–4 backend tasks complete.
- **Backend Work:** `apps/api/tests/security/test_tenant_isolation_sprint3.py` — for each new resource type, create data under Company A, attempt access as a Company B user, assert `404` (never `403`, per `files/09` §1.4).
- **Frontend Work:** None.
- **Database Work:** None (verifies RLS + repository predicates from §4).
- **API Work:** None (test only).
- **Testing Requirements:** This task **is** the testing requirement.
- **Acceptance Criteria:** Every new table with `company_id` is proven RLS-enforced, not just assumed from the migration script's inclusion in the RLS array.
- **Estimated Complexity:** M

#### Task 6.1.3 — Coverage gate check
- **Objective:** Confirm the sprint's new backend code meets the project's existing coverage bar (`docs/development/FastAPI_Development_Standards.md` §6: ≥80% overall) — RBAC/tenancy-adjacent code in this sprint (permission checks, RLS-dependent repository methods) targets the ≥95% bar since it falls under "RBAC, tenancy" per that same rule.
- **Dependencies:** All Epic 2–5 backend tasks complete.
- **Backend Work:** Run `uv run pytest --cov` (or equivalent existing coverage tooling — confirm what's already configured in `pyproject.toml`/CI; add `pytest-cov` if not already a dependency), fix any gaps.
- **Frontend Work:** None.
- **Database Work:** None.
- **API Work:** None.
- **Testing Requirements:** This task **is** the testing requirement.
- **Acceptance Criteria:** Coverage report shows ≥80% overall for `organisation` module, ≥95% for any RLS/permission-check code paths within it.
- **Estimated Complexity:** S

---

### Feature 6.2 — Frontend testing

#### Task 6.2.1 — Component test completion pass
- **Objective:** Confirm every screen built in Epics 2–5 has the component tests specified in its own task (this is a verification/gap-fill pass, not new test design — individual tasks already specify what to test).
- **Dependencies:** All Epic 2–5 frontend tasks complete.
- **Backend Work:** None.
- **Frontend Work:** Gap-fill any missing component tests identified against each task's stated testing requirements.
- **Database Work:** None.
- **API Work:** None.
- **Testing Requirements:** This task **is** the testing requirement.
- **Acceptance Criteria:** `npm run test` passes with every Epic 2–5 screen's component tests present and green.
- **Estimated Complexity:** M

#### Task 6.2.2 — Accessibility check
- **Objective:** Zero critical `axe` violations across the sprint's screen set, per `docs/product/VERSION_1_ROADMAP.md` §16's go-live checklist item, applied at sprint scope now rather than deferred entirely to hardening.
- **Dependencies:** All Epic 2–5 frontend tasks complete.
- **Backend Work:** None.
- **Frontend Work:** Add `@axe-core/playwright` to the E2E suite (1.2.2's Playwright setup), run against every screen in §3, fix violations (focus order, labels, `aria-sort` on sortable table headers per the Directory screen spec's pattern, color-not-alone on status pills).
- **Database Work:** None.
- **API Work:** None.
- **Testing Requirements:** This task **is** the testing requirement.
- **Acceptance Criteria:** Zero critical/serious `axe` violations on every screen listed in §3.
- **Estimated Complexity:** M

---

### Feature 6.3 — End-to-end sprint journey

#### Task 6.3.1 — Full demo-script E2E test
- **Objective:** Automate the exact demo script from §1 as one Playwright E2E test — the single test that proves the sprint goal, not just its parts.
- **Dependencies:** Every task in Epics 1–5.
- **Backend Work:** None (test-only; may require a test-specific seed/reset endpoint or DB truncation helper for E2E isolation — reuse whatever pattern `apps/api/tests/conftest.py` already establishes for test DB isolation, exposed to the Playwright run via a test-only setup script, not a production endpoint).
- **Frontend Work:** `apps/web/e2e/sprint3-company-foundation.spec.ts` — register → land on setup → complete all 9 steps in the order given in the sprint goal → open dashboard → assert real counts → log out → log back in → assert direct dashboard landing (setup already complete).
- **Database Work:** None.
- **API Work:** None (drives the real API through the real UI).
- **Testing Requirements:** This task **is** the testing requirement — it is the sprint's acceptance test, run in CI.
- **Acceptance Criteria:** Passes against a freshly-migrated, freshly-seeded-nothing database (no manual DB intervention, per the sprint's Definition of Done).
- **Estimated Complexity:** L

---

### Feature 6.4 — CI wiring

#### Task 6.4.1 — Frontend CI job
- **Objective:** `apps/web` currently has no CI job at all (`.github/workflows/ci.yml` only has the `api` job) — add one, mirroring the API job's structure.
- **Dependencies:** 1.2.2, 6.2.1, 6.3.1
- **Backend Work:** None.
- **Frontend Work:** None beyond what's already built.
- **Database Work:** None.
- **API Work:** None.
- **CI Work:** New `web` job in `.github/workflows/ci.yml`: `npm ci`, `npm run lint` (Next.js's existing `next lint` script), `npm run test` (Vitest), `npx tsc --noEmit` (type check — `apps/web/tsconfig.json` already exists), `npm run build` (production build must succeed), and a separate `e2e` job (or step, gated behind the API job succeeding and a docker-compose-started backend + Postgres + Redis, mirroring how the API job already provisions `DATABASE_URL`/`REDIS_URL`) running `npm run test:e2e` including Task 6.3.1's journey test.
- **Testing Requirements:** This task **is** the testing requirement — CI itself is the deliverable.
- **Acceptance Criteria:** A PR touching only `apps/web` triggers and must pass the new `web` job; a PR touching both triggers both jobs; the E2E job runs Task 6.3.1's test against a real ephemeral backend, not mocks.
- **Estimated Complexity:** M


---

## 3. UI Roadmap & Screen Specifications

### 3.1 Roadmap table

Per-screen summary — Purpose, User, Priority, Dependencies, and the two orderings requested (Design order = when visual/UX design should be finalized; Implementation order = when the build task actually lands, which follows Epic order above and is not always identical to design order since design can run one step ahead per `files/24` §7's "one sprint ahead of the build" rule).

| # | Screen | Purpose | Primary User | Priority | Dependencies | Design Order | Implementation Order |
|---|---|---|---|---|---|:--:|:--:|
| 1 | Login | Authenticate an existing user into their tenant | All roles | P0 | Epic 1 (auth infra) | 1 | 1 |
| 2 | Company Registration | Create a brand-new tenant + first admin user | Prospective Company Admin | P0 | Epic 2 (registration backend) | 2 | 2 |
| 3 | Company Setup Wizard (Setup Checklist) | Guide the new admin through org configuration, resumable | Company Admin | P0 | Epic 2.3–2.4, Epics 3–4 (linked steps) | 3 | 3 |
| 4 | Company Profile | View/edit company + legal entity details | Company Admin | P0 | Epic 2.5–2.6 | 4 | 4 |
| 5 | Branch Management (= Work Locations, D1) | Configure branches/locations | Company Admin | P0 | Epic 3.1 | 5 | 5 |
| 6 | Department Management | Configure department hierarchy | Company Admin | P0 | Epic 3.2 | 6 | 6 |
| 7 | Designation Management (incl. Grades) | Configure designations and grade bands | Company Admin | P0 | Epic 3.3 | 7 | 7 |
| 8 | Employment Types | Configure employment type catalogue | Company Admin | P1 | Epic 3.4 | 8 | 8 |
| 9 | Holiday Calendar | Configure per-year/per-state holiday calendars | Company Admin | P0 | Epic 4.1 | 9 | 9 |
| 10 | Shift Management | Configure shift master definitions | Company Admin | P1 | Epic 4.2 | 10 | 10 |
| 11 | Leave Policy | Configure leave types and policy bundles | Company Admin | P0 | Epic 4.3 | 11 | 11 |
| 12 | Payroll Policy | Configure pay cycle and pay-date rules | Company Admin | P0 | Epic 4.4 | 12 | 12 |
| 13 | Company Dashboard | Landing page showing setup completion + org counts | Company Admin | P0 | Epic 5 (needs data from all above) | 13 | 13 |

**Note on ordering:** unlike a typical sprint where design runs ahead of build, this sprint's design and implementation orders are identical because there is no separate design team/phase in this AI-driven workflow — each screen's design decisions (empty/loading/error/success states, field lists, validation) are specified in this same document, consumed directly by the implementing session. This collapses `files/24` §7's "one sprint ahead" gap intentionally for this project's operating model.

---

### 3.2 Per-screen specifications

Each screen below follows the same 14-attribute template. Screens that share states/permissions with an already-specified screen reference it rather than repeating identical text (e.g., every Settings CRUD screen shares the same permission-denial and RLS-driven 404 behavior).

---

#### Screen 1 — Login

| Attribute | Specification |
|---|---|
| **Purpose** | Authenticate an existing user against an existing tenant (or select among multiple, if the account has cross-company membership) |
| **Primary User** | Any role (this screen predates role resolution) |
| **Navigation Entry** | Direct URL `/login`; redirect target for any unauthenticated route access (Task 1.4.3's guard) |
| **Required Permissions** | None (public) |
| **Required APIs** | `POST /v1/auth/login` (existing, unchanged) |
| **Database Tables** | `user`, `user_company`, `session`, `refresh_token` (read/write via existing B1 code, untouched this sprint) |
| **Components Needed** | `FormField` (email, password), `Button`, `Alert` (error banner), company-picker `RadioGroup` (shown only if `companies.length > 1` in the response) |
| **Validation Rules** | Email format (client-side, mirrors `EmailStr` server validation); password non-empty; no client-side password-strength check on login (only on registration/change) |
| **Empty State** | N/A (form screen, not a list) |
| **Loading State** | Submit button shows a spinner, disabled during request; no skeleton needed (single-action form) |
| **Error State** | Invalid credentials → inline banner with the server's `message` (not a generic "something went wrong" — the error envelope's message is display-safe per `files/09` §1.3); account locked → distinct message surfacing the lockout, no countdown timer required this sprint; network failure → distinct "couldn't reach the server" message with retry |
| **Success State** | Redirect to `/setup` or `/dashboard` per Task 2.4.2's resume logic |
| **Accessibility Requirements** | Form labeled correctly (`<label>` associated via `htmlFor`), error banner announced via `aria-live="assertive"`, focus moves to the first invalid field on submit failure, submit reachable via Enter key from either field |
| **Future Extension Points** | Mobile OTP, MFA challenge, "Forgot password," invitation acceptance — all listed in `files/24` §3.1 but explicitly out of scope this sprint (no backend for any of them exists; not started here) |

---

#### Screen 2 — Company Registration

| Attribute | Specification |
|---|---|
| **Purpose** | Create a new tenant, its first admin user, and land authenticated |
| **Primary User** | Prospective Company Admin (unauthenticated visitor) |
| **Navigation Entry** | Direct URL `/register`; linked from `/login`'s "New company? Register" affordance |
| **Required Permissions** | None (public) |
| **Required APIs** | `POST /v1/companies/register` (Task 2.1.3) |
| **Database Tables** | `company`, `user`, `user_company`, `role`, `permission`, `role_permission`, `user_role` (writes); plus every default-seed table from D8 (`employment_type`, `holiday_calendar`, `shift`, `leave_type`, `number_series`, `week_off_pattern`) |
| **Components Needed** | `FormField` × (name, industry `Select`, country `Select`, currency `Select`, timezone `Select`, fy_start_month `Select`, admin first/last name, admin email, admin password + confirm), `ServerErrorBanner` |
| **Validation Rules** | Company name required (1–200 chars); subdomain implicitly derived or optionally set, must be unique (server-checked, `409` surfaced inline on the relevant field); email format + uniqueness (server-checked); password: minimum length + complexity (exact rule defined in Task 2.1.3's implementation, surfaced to the user as inline help text before submission, not just on failure) |
| **Empty State** | N/A (form screen) |
| **Loading State** | Submit disabled + spinner during the (multi-row-insert, slightly slower than login) request; no partial-progress indicator needed since it's a single atomic call |
| **Error State** | Duplicate subdomain/email → field-level error via `ServerErrorBanner`'s field-mapping (Task 1.6.1); weak password → field-level error with the specific rule violated; generic 500 → top-level banner, form state preserved (no data loss on retry) |
| **Success State** | Immediately authenticated, redirect to `/setup` |
| **Accessibility Requirements** | Multi-field form grouped into logical `fieldset`/`legend` sections (Company Info vs. Admin Account); same focus/announce rules as Login |
| **Future Extension Points** | Logo upload, subdomain custom picker with live-availability check, SSO/social sign-up — none in scope this sprint |

---

#### Screen 3 — Company Setup Wizard (Setup Checklist)

| Attribute | Specification |
|---|---|
| **Purpose** | Single hub showing all 9 setup steps and their real completion state, linking to each step's actual screen |
| **Primary User** | Company Admin, first-run |
| **Navigation Entry** | Default post-registration/post-login landing while setup is incomplete (Task 2.4.2); always reachable via a persistent "Setup" sidebar/topbar affordance while incomplete |
| **Required Permissions** | `ORG.COMPANY.MANAGE` (the wizard itself; each linked step is separately gated by its own permission per §6) |
| **Required APIs** | `GET /v1/companies/current/setup-progress` (Task 2.3.1) |
| **Database Tables** | `company_setup_progress` (read); implicitly reflects counts across every Epic 3/4 table |
| **Components Needed** | Step list (icon + label + completion badge + "Configure" link) × 9, overall progress bar, "Go to Dashboard" button (always enabled per D9) |
| **Validation Rules** | N/A (read-only hub) |
| **Empty State** | N/A — always shows all 9 steps regardless of progress; "0 of 9 complete" is a valid, correctly-rendered state, not an empty state |
| **Loading State** | Skeleton rows for the 9 steps while progress loads |
| **Error State** | Progress fetch failure → inline retry, step links remain functional even if the completion-badge data failed to load (degrade gracefully — links are static, only badges depend on the API) |
| **Success State** | N/A (navigational hub, not a mutation) |
| **Accessibility Requirements** | Step list as a real ordered/unordered list (`<ol>`/`<ul>`) with each item's completion state conveyed via text + icon, not color alone |
| **Future Extension Points** | Guided tooltips, video walkthrough per step, "Invite a teammate to help set up" — none in scope |

---

#### Screen 4 — Company Profile

| Attribute | Specification |
|---|---|
| **Purpose** | View/edit company-level settings and the primary legal entity |
| **Primary User** | Company Admin |
| **Navigation Entry** | Sidebar → Settings → Company; wizard step "Company Profile" |
| **Required Permissions** | `ORG.COMPANY.MANAGE` (company fields), `ORG.LEGAL_ENTITY.MANAGE` (legal entity section) |
| **Required APIs** | `GET/PATCH /v1/companies/current` (Task 2.5.1), `GET/POST/PATCH /v1/legal-entities` (Task 2.6.1), `GET/PATCH /v1/number-series` (Task 4.5.1, embedded section per 4.5.2) |
| **Database Tables** | `company`, `legal_entity`, `number_series` |
| **Components Needed** | `FormSection` × (Company Info, Legal Entity, Employee ID Format), `FormField`s throughout, inline "Add another legal entity" affordance |
| **Validation Rules** | PAN format regex (`[A-Z]{5}[0-9]{4}[A-Z]{1}`), GSTIN format regex, required-field rules per `files/17` FR-ORG-001/003 |
| **Empty State** | Legal entity section shows an inline empty prompt ("No legal entity yet — add one") if none exists (shouldn't happen post-registration if 2.1.3 seeds one, but must degrade correctly if it doesn't) |
| **Loading State** | Skeleton form while both `GET` calls resolve |
| **Error State** | `409 STALE_RESOURCE` on concurrent edit → banner offering to reload latest values (discarding local unsaved changes, with an explicit confirm since this is a data-loss action per the irreversibility principle) |
| **Success State** | Toast confirmation, form reflects saved values (no stale local state after save) |
| **Accessibility Requirements** | Standard form rules; PAN/GSTIN fields get format hints in visible help text, not placeholder-only (placeholders disappear on input, failing a common accessibility trap) |
| **Future Extension Points** | Logo upload with cropping, theme/branding override (per `01_Design_System.md` §11's tenant branding boundary), multi-legal-entity list view if a company grows beyond one entity |

---

#### Screen 5 — Branch Management (= Work Locations, per D1)

| Attribute | Specification |
|---|---|
| **Purpose** | CRUD for branches/locations, the operational sites employees will eventually be assigned to |
| **Primary User** | Company Admin |
| **Navigation Entry** | Sidebar → Settings → Branches; wizard step "Branches" |
| **Required Permissions** | `ORG.BRANCH.MANAGE` |
| **Required APIs** | `GET/POST /v1/branches`, `GET/PATCH/DELETE /v1/branches/{id}`, `GET /v1/legal-entities` (for the parent picker), `GET /v1/week-off-patterns` |
| **Database Tables** | `branch`, `legal_entity` (read, for FK picker), `week_off_pattern` (read) |
| **Components Needed** | `DataTable` (list), create/edit `Sheet` drawer, `ConfirmDialog` (deactivate) |
| **Validation Rules** | `state_code` from the fixed ISO 3166-2:IN list; pincode 6-digit numeric; lat/long within valid ranges when present; `legal_entity_id` required |
| **Empty State** | Zero-branch guided empty state pointing at "Add branch," per the same pattern as the Directory screen spec's zero-employee case (`docs/design/screens/01_Employee_List_Directory.md` §8) |
| **Loading State** | `DataTable` skeleton rows |
| **Error State** | List load failure → error panel + retry, preserving any filter state; deactivation blocked (referenced by an active department) → the blocking list shown in the confirm dialog itself, not a separate error page |
| **Success State** | Toast on create/update/deactivate; new/edited row reflected in the table without a full reload |
| **Accessibility Requirements** | Real `<table>` semantics per the Directory screen spec's established pattern (`docs/design/screens/01_Employee_List_Directory.md` §11); sortable columns get `aria-sort` |
| **Future Extension Points** | Interactive geofence map editor (`files/24` §3.4), bulk branch import, multi-branch week-off pattern builder |

---

#### Screen 6 — Department Management

| Attribute | Specification |
|---|---|
| **Purpose** | Configure the department hierarchy (tree, not flat list) |
| **Primary User** | Company Admin |
| **Navigation Entry** | Sidebar → Settings → Departments; wizard step "Departments" |
| **Required Permissions** | `ORG.DEPARTMENT.MANAGE`, `ORG.COST_CENTRE.MANAGE` (inline cost-centre creation) |
| **Required APIs** | `GET /v1/departments/tree`, `GET/POST /v1/departments`, `GET/PATCH/DELETE /v1/departments/{id}`, `GET/POST /v1/cost-centres`, `GET /v1/branches` (parent-branch picker) |
| **Database Tables** | `department`, `cost_centre`, `branch` (read) |
| **Components Needed** | Tree view component (expand/collapse), create/edit `Sheet` drawer, parent-department `Combobox` (excludes the node's own descendants, per Task 3.2.3), cost-centre creatable `Combobox` |
| **Validation Rules** | Cycle rejection and max-5-levels enforced server-side (Task 3.2.1) and mirrored client-side in the parent picker's option filtering |
| **Empty State** | Zero-department guided empty state |
| **Loading State** | Tree skeleton (indented placeholder rows) |
| **Error State** | Cycle-rejection error surfaces inline on the parent-picker field, not a generic banner; tree load failure → retry, preserving expand/collapse state |
| **Success State** | Toast; tree re-renders with the new/edited node in place, expand state preserved for unaffected branches of the tree |
| **Accessibility Requirements** | Tree implemented with `role="tree"`/`role="treeitem"`/`aria-expanded` semantics, keyboard-navigable (arrow keys to move, Enter to expand) |
| **Future Extension Points** | Drag-and-drop re-parenting, bulk reorg move (mirrors the Directory screen's "bulk field update" pattern once Employee Management exists to move people along with departments) |

---

#### Screen 7 — Designation Management (incl. Grades)

| Attribute | Specification |
|---|---|
| **Purpose** | Configure designations and their grade/band assignments together |
| **Primary User** | Company Admin |
| **Navigation Entry** | Sidebar → Settings → Designations; wizard step "Designations & Grades" |
| **Required Permissions** | `ORG.DESIGNATION.MANAGE`, `ORG.GRADE.MANAGE` |
| **Required APIs** | `GET/POST /v1/designations`, `GET/PATCH/DELETE /v1/designations/{id}`, `GET/POST /v1/grades`, `GET/PATCH/DELETE /v1/grades/{id}`, `GET /v1/departments` (optional department picker) |
| **Database Tables** | `designation`, `grade`, `department` (read) |
| **Components Needed** | Two `DataTable`s (or split-pane/tabs — implementer's layout call per Task 3.3.3), create/edit `Sheet` drawers for each |
| **Validation Rules** | `min_ctc <= max_ctc` on Grade; Designation's `department_id` genuinely optional |
| **Empty State** | Zero-designation and zero-grade guided empty states, independently (a company might seed grades before designations or vice versa) |
| **Loading State** | `DataTable` skeletons for both |
| **Error State** | Standard list/form error patterns per Branch Management above |
| **Success State** | Toast; newly-created Grade immediately appears in the Designation form's grade picker without a manual refresh (shared query-cache invalidation, Task 1.3.2's convention) |
| **Accessibility Requirements** | Standard table/form rules |
| **Future Extension Points** | Career-path visualization using `next_designation_id` (D10 — column exists, no UI yet), job-description document attachment |

---

#### Screen 8 — Employment Types

| Attribute | Specification |
|---|---|
| **Purpose** | Configure the employment-type catalogue and each type's statutory applicability flags |
| **Primary User** | Company Admin |
| **Navigation Entry** | Sidebar → Settings → Employment Types; wizard step "Employment Types" |
| **Required Permissions** | `ORG.EMPLOYMENT_TYPE.MANAGE` |
| **Required APIs** | `GET/POST /v1/employment-types`, `GET/PATCH/DELETE /v1/employment-types/{id}` |
| **Database Tables** | `employment_type` |
| **Components Needed** | `DataTable` with a compact "Statutory applicability" summary column (expandable), create/edit `Sheet` drawer with 5 `Switch` toggles |
| **Validation Rules** | Code uniqueness per company (server-enforced, surfaced as a field error) |
| **Empty State** | Not typically empty (seeded with `PERMANENT`/`PROBATION` per D8) — if a company somehow has zero (e.g., both deactivated), show the standard guided empty state |
| **Loading State** | `DataTable` skeleton |
| **Error State** | Standard patterns per Branch Management above |
| **Success State** | Toast; table updates in place |
| **Accessibility Requirements** | Each `Switch` labeled explicitly (not relying on adjacent text alone) |
| **Future Extension Points** | Per-type default leave policy linkage, per-type default probation/notice periods (currently on Grade, could migrate here if product feedback suggests it) |

---

#### Screen 9 — Holiday Calendar

| Attribute | Specification |
|---|---|
| **Purpose** | Configure per-year, optionally per-state, holiday calendars and their holidays |
| **Primary User** | Company Admin |
| **Navigation Entry** | Sidebar → Settings → Holiday Calendar; wizard step "Holiday Calendar" |
| **Required Permissions** | `ORG.HOLIDAY.MANAGE` |
| **Required APIs** | `GET/POST /v1/holiday-calendars`, `POST /v1/holiday-calendars/{id}/holidays`, `GET /v1/holidays?year=&branch_id=` |
| **Database Tables** | `holiday_calendar`, `holiday` |
| **Components Needed** | Calendar/year selector, month-grouped holiday list, "Add holiday" form (date picker, name, type `Select`, is_paid `Switch`) |
| **Validation Rules** | Duplicate date within the same calendar rejected (server-side, Task 4.1.1); date must fall within the calendar's `year` |
| **Empty State** | The seeded default calendar (D8) exists but is empty — guided empty state explaining "Add your first holiday," distinct from a missing-calendar state |
| **Loading State** | List skeleton grouped by month placeholder |
| **Error State** | Duplicate-date rejection surfaces inline on the date field |
| **Success State** | Toast; new holiday appears in its correct month group immediately |
| **Accessibility Requirements** | Date picker keyboard-operable; month groupings use proper heading semantics (`<h3>` per group, not just styled `<div>`s) |
| **Future Extension Points** | Bulk-import a standard national holiday set (flagged as deferred in Task 4.1.2), optional/restricted-holiday "pick N of M" employee-facing selection (requires Employee Management + ESS) |

---

#### Screen 10 — Shift Management

| Attribute | Specification |
|---|---|
| **Purpose** | Configure shift master definitions (master only, per D5 — no roster/assignment) |
| **Primary User** | Company Admin |
| **Navigation Entry** | Sidebar → Settings → Shifts; wizard step "Shifts" |
| **Required Permissions** | `ORG.SHIFT.MANAGE` |
| **Required APIs** | `GET/POST /v1/shifts`, `GET/PATCH/DELETE /v1/shifts/{id}`, `GET /v1/week-off-patterns` |
| **Database Tables** | `shift`, `week_off_pattern` (read) |
| **Components Needed** | `DataTable`, create/edit `Sheet` drawer with a visual shift-window timeline preview |
| **Validation Rules** | `end_time` before `start_time` valid only when `is_cross_midnight=true` (Task 4.2.1); half-day threshold `<` min-hours-full-day when both present |
| **Empty State** | The seeded "General Shift" (D8) exists post-registration — true zero-shift state only reachable if deactivated, standard guided empty state applies then |
| **Loading State** | `DataTable` skeleton |
| **Error State** | Cross-midnight validation error surfaces inline on the time fields |
| **Success State** | Toast; table updates in place |
| **Accessibility Requirements** | Time pickers keyboard-operable; the timeline preview is decorative (has an `aria-hidden` equivalent text summary alongside it, not the sole conveyor of the shift window) |
| **Future Extension Points** | Rotation-pattern generator, roster calendar, shift-to-employee assignment (all explicitly Sprint 7, D5) |

---

#### Screen 11 — Leave Policy

| Attribute | Specification |
|---|---|
| **Purpose** | Configure leave types (full rule set) and policy bundles assignable to org segments — configuration only, no ledger/application (D3) |
| **Primary User** | Company Admin |
| **Navigation Entry** | Sidebar → Settings → Leave Policies; wizard step "Leave Policies" |
| **Required Permissions** | `LEAVE.TYPE.MANAGE`, `LEAVE.POLICY.MANAGE` |
| **Required APIs** | `GET/POST /v1/leave-types`, `GET/PATCH/DELETE /v1/leave-types/{id}`, `GET/POST /v1/leave-policies`, `GET/PATCH/DELETE /v1/leave-policies/{id}`, `POST /v1/leave-policies/{id}/items`, `POST /v1/leave-policies/{id}/assignments`, `GET /v1/grades`, `GET /v1/employment-types`, `GET /v1/departments` (assignment scope pickers) |
| **Database Tables** | `leave_type`, `leave_policy`, `leave_policy_item`, `leave_policy_assignment` |
| **Components Needed** | Tabbed layout ("Leave Types" / "Policies"), the most field-dense form in this sprint (leave type edit) organized into `FormSection`s (Eligibility, Accrual, Balance & Carry-forward, Application Rules), policy item picker (multi-select leave types with per-item override fields), assignment form (`scope_type` `Select` + conditional scope-value picker) |
| **Validation Rules** | Full field set per Task 4.3.1's model; overlapping assignment to the same scope rejected server-side, surfaced inline |
| **Empty State** | 12 seeded leave types exist post-registration (D8) — zero-policy state (no bundles created yet) gets its own distinct guided empty state on the Policies tab |
| **Loading State** | Skeletons per tab independently (switching tabs while the other loads doesn't block) |
| **Error State** | Field-dense form → per-field error mapping is critical here (Task 1.6.1's `ServerErrorBanner` must handle multiple simultaneous field errors cleanly, not just one) |
| **Success State** | Toast; policy list/type list update in place |
| **Accessibility Requirements** | Long form broken into `FormSection` landmarks so screen-reader users can navigate by section, not just linearly through 20+ fields |
| **Future Extension Points** | Accrual job scheduling UI, leave ledger/balance statement, application/approval flow (all Sprint 8) |

---

#### Screen 12 — Payroll Policy

| Attribute | Specification |
|---|---|
| **Purpose** | Configure the company's pay cycle, cut-off day, and pay-date rule — a singleton settings form, not a list (D4, Task 4.4.1) |
| **Primary User** | Company Admin |
| **Navigation Entry** | Sidebar → Settings → Payroll Policy; wizard step "Payroll Policies" |
| **Required Permissions** | `PAYROLL.POLICY.MANAGE` |
| **Required APIs** | `GET/PUT /v1/payroll-policy` |
| **Database Tables** | `payroll_policy` |
| **Components Needed** | Single form with conditional fields (`pay_cycle=CUSTOM` reveals `custom_cycle_start_day`; `pay_date_rule=FIXED_DAY` reveals `fixed_pay_day`) |
| **Validation Rules** | Mutually-conditional-required fields per Task 4.4.1 |
| **Empty State** | No policy configured yet → form renders with sensible pre-filled defaults (`CALENDAR_MONTH`, `LAST_WORKING_DAY`) rather than a blank/empty-state pattern, since this is a singleton settings form, not a list — first save creates the row |
| **Loading State** | Form skeleton while the current policy (if any) loads |
| **Error State** | Standard field validation errors; conflicting-active-policy race (two admins saving simultaneously) → `409`, reload-latest banner |
| **Success State** | Toast; form reflects saved values |
| **Accessibility Requirements** | Conditional field reveal announced via `aria-live="polite"` so screen-reader users know new fields appeared |
| **Future Extension Points** | Salary components, structures, formula builder, statutory master (Sprint 9, D4) |

---

#### Screen 13 — Company Dashboard

| Attribute | Specification |
|---|---|
| **Purpose** | Landing page after setup — org-structure counts and setup-completion state (scoped-down Company Admin dashboard variant, per Task 5.2.1) |
| **Primary User** | Company Admin |
| **Navigation Entry** | Sidebar → Dashboard (top item); default landing once setup is complete (Task 2.4.2) |
| **Required Permissions** | Implicit — any authenticated user with `ORG.COMPANY.MANAGE` this sprint (only role is `COMPANY_ADMIN` per D12); a future `DASHBOARD.COMPANY.VIEW` permission code is registered now (§6) so non-admin roles can be granted view-only access in a later sprint without a new endpoint |
| **Required APIs** | `GET /v1/dashboards/company` (Task 5.1.1) |
| **Database Tables** | Read-only aggregation over `branch`, `department`, `designation`, `employment_type`, `holiday_calendar`, `shift`, `leave_type`, `leave_policy`, `payroll_policy`, `employee`, `company_setup_progress` |
| **Components Needed** | Setup-completion progress card, stat card × 9 (one per count), each linking to its settings screen |
| **Validation Rules** | N/A (read-only) |
| **Empty State** | A brand-new company (all D8 defaults present, nothing else configured) still shows real, correct numbers (e.g., "1 Holiday Calendar, 0 Holidays," "1 Shift," "12 Leave Types, 0 Policies") — this is not an empty state, it's the honest zero/default state, rendered normally |
| **Loading State** | Card-grid skeleton |
| **Error State** | Summary fetch failure → error panel + retry, dashboard shell (sidebar/topbar) remains usable |
| **Success State** | N/A (read-only landing page) |
| **Accessibility Requirements** | Stat cards use real heading hierarchy (card title as `<h3>`), numbers are not the sole content of a card (each paired with a label) |
| **Future Extension Points** | Headcount/attrition/compliance/payroll-status widgets once Employee Management, Attendance, Leave, and Payroll modules exist (`files/24` §3.2's full Company Admin dashboard spec) |


---

## 4. Database Catalogue

Conventions throughout (unchanged from `docs/database/Database_Architecture.md`): UUID PKs via `gen_random_uuid()`; every tenant table carries `company_id NOT NULL` + RLS; soft delete via `deleted_at`; optimistic locking via `version INTEGER DEFAULT 1` on any table exposed through a `PATCH`/`PUT` endpoint; money as `BIGINT` minor units; every FK indexed.

### 4.1 Tables — expanded (existing stubs, this sprint completes them)

| Table | New/changed columns this sprint | Owning module |
|---|---|---|
| `company` | `+industry_code, +fy_start_month, +logo_url, +theme_json, +onboarded_at, +trial_ends_at, +data_region` | `organisation` (writes), root tenant table |
| `user` | `+first_name, +last_name` | `identity` (unchanged ownership) |
| `legal_entity` | `+registered_address, +tan, +cin, +pf_code, +esi_code, +lwf_reg, +signatory_name, +signatory_designation, +signature_image_url, +is_active, +version` | `organisation` |
| `branch` | `+code, +address_line1, +address_line2, +city, state→state_code, +pincode, +latitude, +longitude, +geofence_radius_m, +holiday_calendar_id (FK, added in 4.1.1), +week_off_pattern_id (FK, added in 3.1.3), +is_active, +version` | `organisation` |
| `department` | `+head_employee_id (FK→employee, nullable, D10), +cost_centre_id (FK, added in 3.2.2), +is_active, +version` | `organisation` |
| `designation` | `+code, +grade_id (FK), +next_designation_id (self FK, nullable, D10), +is_active, +version` | `organisation` |
| `grade` | `rank→level, +min_ctc, +max_ctc, +notice_period_days, +probation_days, +approval_limit, +is_active, +version` — **`leave_policy_id` explicitly NOT added, superseded by `leave_policy_assignment` (Task 4.3.3 override)** | `organisation` |
| `holiday_calendar` | `+year, +state_code, +is_active` | `organisation` |
| `holiday` | `is_optional→type (VARCHAR CHECK, FIXED/OPTIONAL/RESTRICTED), +is_paid` | `organisation` |

### 4.2 Tables — new this sprint

| Table | Purpose | Owning module | Partitioned? |
|---|---|---|---|
| `company_setup_progress` | Derived wizard completion tracking (Task 2.3.1) | `organisation` | No |
| `week_off_pattern` | Named weekly-off patterns referenced by `branch`/`shift` (Task 3.1.3) | `organisation` | No |
| `cost_centre` | Referenced by `department` (Task 3.2.2) | `organisation` | No |
| `employment_type` | Employment type catalogue (Task 3.4.1) | `organisation` | No |
| `shift` | Shift master definitions, no roster (Task 4.2.1, D5) | `organisation` | No |
| `leave_type` | Leave type master (Task 4.3.1, D3) | `organisation` (permission namespace `LEAVE.*`) | No |
| `leave_policy` | Named policy bundle (Task 4.3.3) | `organisation` | No |
| `leave_policy_item` | Leave type ↔ policy junction with overrides (Task 4.3.3) | `organisation` | No |
| `leave_policy_assignment` | Policy → org-segment assignment (Task 4.3.3) | `organisation` | No |
| `payroll_policy` | Singleton-per-company pay cycle config (Task 4.4.1, D4) | `organisation` (permission namespace `PAYROLL.*`) | No |
| `number_series` | Race-safe code allocator, `EMPLOYEE_CODE` only (Task 4.5.1, D7) | `organisation` | No |

None of this sprint's tables are high-volume (no punches, no payslip lines) — none require partitioning per `docs/database/Database_Architecture.md` §1 rule 7's list, which names only `punch`, `attendance_day`, `notification_log`, `audit_log`, `payslip_line`.

### 4.3 Relationships (FK graph, build order)

```
company (root)
 ├─ legal_entity (company_id)
 │   └─ branch (company_id, legal_entity_id)
 │       ├─ department (company_id, branch_id?)
 │       │   ├─ cost_centre (company_id)          [referenced, not owned by department]
 │       │   └─ department (parent_id, self-FK — cycle-guarded in service layer)
 │       ├─ holiday_calendar (company_id)          [branch.holiday_calendar_id → this]
 │       │   └─ holiday (calendar_id)
 │       └─ week_off_pattern (company_id)          [branch.week_off_pattern_id → this]
 ├─ grade (company_id)
 │   └─ designation (company_id, grade_id, department_id?, next_designation_id? self-FK)
 ├─ employment_type (company_id)
 ├─ shift (company_id, week_off_pattern_id?)
 ├─ leave_type (company_id)
 │   └─ leave_policy_item (leave_policy_id, leave_type_id)
 ├─ leave_policy (company_id)
 │   ├─ leave_policy_item (← above)
 │   └─ leave_policy_assignment (leave_policy_id, scope_ref_id → grade/employment_type/department, polymorphic by scope_type)
 ├─ payroll_policy (company_id)
 ├─ number_series (company_id)
 └─ company_setup_progress (company_id, unique)
```

**Migration/build order this sprint** (respects the graph above — each task's migration must land no earlier than its dependencies'): `company` fields (2.1.1) → `user` fields (2.1.3) → `legal_entity` (2.6.1) → `branch` core (3.1.1) → `week_off_pattern` + `branch.week_off_pattern_id` (3.1.3) → `department` core (3.2.1) → `cost_centre` + `department.cost_centre_id` (3.2.2) → `grade` (3.3.1) → `designation` (3.3.2) → `employment_type` (3.4.1) → `holiday_calendar`/`holiday` + `branch.holiday_calendar_id` (4.1.1) → `shift` (4.2.1) → `leave_type` (4.3.1) → `leave_policy`/`leave_policy_item`/`leave_policy_assignment` (4.3.3) → `payroll_policy` (4.4.1) → `number_series` (4.5.1) → `company_setup_progress` (2.3.1, can land any time after `company`, listed last here only because it's an ambient tracking table, not a hard dependency of anything else).

### 4.4 Indexes required (beyond automatic PK/FK indexes)

Every FK column is indexed per `docs/database/Database_Architecture.md` §1 rule 6 — not re-listed individually below; this table covers **additional** composite/lookup indexes:

| Table | Index | Reason |
|---|---|---|
| `branch` | `(company_id, state_code)` | Holiday-calendar-by-state resolution (`AC-ORG-008.1`) |
| `department` | `(company_id, parent_id)` | Tree-walk queries |
| `holiday` | `(calendar_id, date)` UNIQUE | Duplicate-date rejection (Task 4.1.1) enforced at the DB level, not just service-layer |
| `leave_policy_item` | `(leave_policy_id, leave_type_id)` UNIQUE | Prevents duplicate item rows |
| `leave_policy_assignment` | `(company_id, scope_type, scope_ref_id)` partial UNIQUE `WHERE is_active` | One active assignment per scope (Task 4.3.3) |
| `payroll_policy` | `(company_id)` partial UNIQUE `WHERE is_active AND deleted_at IS NULL` | Singleton-per-company enforcement (Task 4.4.1) |
| `number_series` | `(company_id, entity_type)` UNIQUE | One series per entity type per company |
| `company_setup_progress` | `(company_id)` UNIQUE | One progress row per company |

### 4.5 Row-Level Security

Every table in §4.2 (new) and every table in §4.1 that already has `company_id` gets the standard `tenant_isolation` policy, added to the `FOREACH tbl IN ARRAY [...]` block via a new migration `scripts/sql/004_org_module_rls.sql` (additive, following `002_row_level_security.sql`'s pattern exactly — do not edit the original file, which is already applied in earlier environments):

```
week_off_pattern, cost_centre, employment_type, shift, leave_type, leave_policy,
payroll_policy, number_series, company_setup_progress
```

`leave_policy_item` and `leave_policy_assignment` follow the documented exception for tables one join away (`holiday`, `role_permission` precedent) — `leave_policy_item` has no direct `company_id` (joins through `leave_policy_id`), relies on parent RLS + application predicate; `leave_policy_assignment` **does** carry `company_id` directly (per its schema in Task 4.3.3) and gets its own policy, added to the array above.

### 4.6 Effective dating

**None of this sprint's tables are effective-dated.** `docs/database/Database_Architecture.md` §5's pattern (`effective_from`/`effective_to` + `EXCLUDE USING gist`) applies to `employee_assignment`/`employee_compensation` (Sprint 4+) — nothing in this sprint's scope changes over time in a way that needs history preserved at the row level; org-structure changes here are direct mutations with `updated_at`/audit-log history instead, which is sufficient for configuration data (as opposed to compensation/assignment data, where historical accuracy has legal/payroll consequences).

### 4.7 Audit requirements

Every `CREATE`/`UPDATE`/`DELETE` (soft) across every table in §4.1–4.2 must call `AuditService.record()` (existing service, `hrms/core/audit/service.py`, unchanged) with `entity_type` set to the table name and `action` ∈ `{CREATED, UPDATED, DEACTIVATED}`. This is not optional per-table — it's a standing rule from `docs/development/FastAPI_Development_Standards.md` §9's code-review checklist ("Mutations audited") and is called out explicitly here because every Epic 2–4 service method that mutates state must include this call; it is not separately itemized as a task per table to avoid 20+ near-duplicate task entries, but **is** part of every CRUD task's Definition of Done and will be checked in Epic 6's coverage/review pass.

### 4.8 SQLAlchemy model / migration file map

| Table | Model file | Migration landing task |
|---|---|---|
| `company` (fields) | `hrms/core/db/models/identity.py::Company` | 2.1.1 |
| `user` (fields) | `hrms/core/db/models/identity.py::User` | 2.1.3 |
| `company_setup_progress` | `hrms/modules/organisation/models.py::CompanySetupProgress` | 2.3.1 |
| `legal_entity` | `hrms/modules/organisation/models.py::LegalEntity` | 2.6.1 |
| `branch` | `hrms/modules/organisation/models.py::Branch` | 3.1.1, 3.1.3 (FK), 4.1.1 (FK) |
| `week_off_pattern` | `hrms/modules/organisation/models.py::WeekOffPattern` | 3.1.3 |
| `department` | `hrms/modules/organisation/models.py::Department` | 3.2.1, 3.2.2 (FK) |
| `cost_centre` | `hrms/modules/organisation/models.py::CostCentre` | 3.2.2 |
| `grade` | `hrms/modules/organisation/models.py::Grade` | 3.3.1 |
| `designation` | `hrms/modules/organisation/models.py::Designation` | 3.3.2 |
| `employment_type` | `hrms/modules/organisation/models.py::EmploymentType` | 3.4.1 |
| `holiday_calendar` | `hrms/modules/organisation/models.py::HolidayCalendar` | 4.1.1 |
| `holiday` | `hrms/modules/organisation/models.py::Holiday` | 4.1.1 |
| `shift` | `hrms/modules/organisation/models.py::Shift` | 4.2.1 |
| `leave_type` | `hrms/modules/organisation/models.py::LeaveType` | 4.3.1 |
| `leave_policy` | `hrms/modules/organisation/models.py::LeavePolicy` | 4.3.3 |
| `leave_policy_item` | `hrms/modules/organisation/models.py::LeavePolicyItem` | 4.3.3 |
| `leave_policy_assignment` | `hrms/modules/organisation/models.py::LeavePolicyAssignment` | 4.3.3 |
| `payroll_policy` | `hrms/modules/organisation/models.py::PayrollPolicy` | 4.4.1 |
| `number_series` | `hrms/modules/organisation/models.py::NumberSeries` | 4.5.1 |

All models live in one `models.py` under the `organisation` module per `docs/architecture/01_Backend_Structure.md` §3's "sub-packages not used" rule and `02_Module_Standard.md` §1's "split to `models/` only past ~15 tables" threshold — this sprint's 19 new/changed tables technically crosses that line, so **implementer note:** at Task 4.2.1 or whenever `models.py` exceeds ~600–800 lines / becomes hard to navigate, split into `hrms/modules/organisation/models/` as a package (`company.py`, `branch.py`, `department.py`, `designation.py`, `scheduling.py`, `leave_policy.py`, `payroll_policy.py`, `number_series.py`, re-exported via `models/__init__.py` so `from hrms.modules.organisation import models` call sites don't change) — this is a mechanical refactor decision left to whichever task first feels the pain, not pre-decided here, since the module standard explicitly frames it as a size-triggered judgment call.


---

## 5. API Endpoint Catalogue

Conventions unchanged from `files/09_API_Standards.md`: every response wrapped in `DataEnvelope`/`ListEnvelope`; every mutating endpoint requires `X-Company-Id` (resolved via existing `get_tenant_context`); list endpoints support `page`/`per_page`/`sort`/`filter[...]`/`search` per §1.5 where noted; `PATCH` endpoints on versioned resources require `If-Match`. Base path `/v1`.

### 5.1 Company, Registration & Number Series

| Method | Path | Request | Response | Permission |
|---|---|---|---|---|
| `POST` | `/companies/register` | `CompanyRegistrationRequest` (name, industry_code, country_code, currency, timezone, fy_start_month, admin_first_name, admin_last_name, admin_email, admin_password) | `DataEnvelope<TokenResponseData>` | Public |
| `GET` | `/companies/current` | — | `DataEnvelope<CompanyProfile>` | `ORG.COMPANY.MANAGE` |
| `PATCH` | `/companies/current` | `CompanyProfileUpdate` (partial) + `If-Match` | `DataEnvelope<CompanyProfile>` | `ORG.COMPANY.MANAGE` |
| `GET` | `/companies/current/setup-progress` | — | `DataEnvelope<CompanySetupProgress>` | `ORG.COMPANY.MANAGE` |
| `GET` | `/number-series` | — | `ListEnvelope<NumberSeriesRead>` | `ORG.NUMBER_SERIES.MANAGE` |
| `PATCH` | `/number-series/{id}` | `NumberSeriesUpdate` (prefix, separator, padding, reset_rule) | `DataEnvelope<NumberSeriesRead>` | `ORG.NUMBER_SERIES.MANAGE` |

### 5.2 Organization Structure

| Method | Path | Request | Response | Permission |
|---|---|---|---|---|
| `GET` | `/legal-entities` | filters, pagination | `ListEnvelope<LegalEntityRead>` | `ORG.LEGAL_ENTITY.MANAGE` |
| `POST` | `/legal-entities` | `LegalEntityCreate` | `DataEnvelope<LegalEntityRead>` | `ORG.LEGAL_ENTITY.MANAGE` |
| `GET` | `/legal-entities/{id}` | — | `DataEnvelope<LegalEntityRead>` | `ORG.LEGAL_ENTITY.MANAGE` |
| `PATCH` | `/legal-entities/{id}` | `LegalEntityUpdate` + `If-Match` | `DataEnvelope<LegalEntityRead>` | `ORG.LEGAL_ENTITY.MANAGE` |
| `DELETE` | `/legal-entities/{id}` | — (soft-delete/deactivate) | `204` | `ORG.LEGAL_ENTITY.MANAGE` |
| `GET` | `/branches` | filters (`legal_entity_id`, `state_code`, `status`), pagination, search | `ListEnvelope<BranchRead>` | `ORG.BRANCH.MANAGE` |
| `POST` | `/branches` | `BranchCreate` | `DataEnvelope<BranchRead>` | `ORG.BRANCH.MANAGE` |
| `GET` | `/branches/{id}` | — | `DataEnvelope<BranchRead>` | `ORG.BRANCH.MANAGE` |
| `PATCH` | `/branches/{id}` | `BranchUpdate` + `If-Match` | `DataEnvelope<BranchRead>` | `ORG.BRANCH.MANAGE` |
| `DELETE` | `/branches/{id}` | — | `204` (blocked if referenced, `409` with blocking list) | `ORG.BRANCH.MANAGE` |
| `GET` | `/week-off-patterns` | — | `ListEnvelope<WeekOffPatternRead>` | `ORG.BRANCH.MANAGE` (read-only consumer permission, list-only endpoint) |
| `GET` | `/departments` | filters (`branch_id`, `parent_id`, `status`) | `ListEnvelope<DepartmentRead>` | `ORG.DEPARTMENT.MANAGE` |
| `GET` | `/departments/tree` | `?root_department_id=` (optional) | `DataEnvelope<DepartmentTreeNode>` | `ORG.DEPARTMENT.MANAGE` |
| `POST` | `/departments` | `DepartmentCreate` | `DataEnvelope<DepartmentRead>` | `ORG.DEPARTMENT.MANAGE` |
| `GET` | `/departments/{id}` | — | `DataEnvelope<DepartmentRead>` | `ORG.DEPARTMENT.MANAGE` |
| `PATCH` | `/departments/{id}` | `DepartmentUpdate` + `If-Match` | `DataEnvelope<DepartmentRead>` | `ORG.DEPARTMENT.MANAGE` |
| `DELETE` | `/departments/{id}` | — | `204` (blocked if has active children or is referenced) | `ORG.DEPARTMENT.MANAGE` |
| `GET` | `/cost-centres` | — | `ListEnvelope<CostCentreRead>` | `ORG.COST_CENTRE.MANAGE` |
| `POST` | `/cost-centres` | `CostCentreCreate` | `DataEnvelope<CostCentreRead>` | `ORG.COST_CENTRE.MANAGE` |
| `GET` | `/designations` | filters (`department_id`, `grade_id`, `status`) | `ListEnvelope<DesignationRead>` | `ORG.DESIGNATION.MANAGE` |
| `POST` | `/designations` | `DesignationCreate` | `DataEnvelope<DesignationRead>` | `ORG.DESIGNATION.MANAGE` |
| `GET` | `/designations/{id}` | — | `DataEnvelope<DesignationRead>` | `ORG.DESIGNATION.MANAGE` |
| `PATCH` | `/designations/{id}` | `DesignationUpdate` + `If-Match` | `DataEnvelope<DesignationRead>` | `ORG.DESIGNATION.MANAGE` |
| `DELETE` | `/designations/{id}` | — | `204` | `ORG.DESIGNATION.MANAGE` |
| `GET` | `/grades` | — | `ListEnvelope<GradeRead>` | `ORG.GRADE.MANAGE` |
| `POST` | `/grades` | `GradeCreate` | `DataEnvelope<GradeRead>` | `ORG.GRADE.MANAGE` |
| `GET` | `/grades/{id}` | — | `DataEnvelope<GradeRead>` | `ORG.GRADE.MANAGE` |
| `PATCH` | `/grades/{id}` | `GradeUpdate` + `If-Match` | `DataEnvelope<GradeRead>` | `ORG.GRADE.MANAGE` |
| `DELETE` | `/grades/{id}` | — | `204` | `ORG.GRADE.MANAGE` |
| `GET` | `/employment-types` | — | `ListEnvelope<EmploymentTypeRead>` | `ORG.EMPLOYMENT_TYPE.MANAGE` |
| `POST` | `/employment-types` | `EmploymentTypeCreate` | `DataEnvelope<EmploymentTypeRead>` | `ORG.EMPLOYMENT_TYPE.MANAGE` |
| `GET` | `/employment-types/{id}` | — | `DataEnvelope<EmploymentTypeRead>` | `ORG.EMPLOYMENT_TYPE.MANAGE` |
| `PATCH` | `/employment-types/{id}` | `EmploymentTypeUpdate` + `If-Match` | `DataEnvelope<EmploymentTypeRead>` | `ORG.EMPLOYMENT_TYPE.MANAGE` |
| `DELETE` | `/employment-types/{id}` | — | `204` | `ORG.EMPLOYMENT_TYPE.MANAGE` |

### 5.3 Holiday Calendar & Shifts

| Method | Path | Request | Response | Permission |
|---|---|---|---|---|
| `GET` | `/holiday-calendars` | filters (`year`, `state_code`) | `ListEnvelope<HolidayCalendarRead>` | `ORG.HOLIDAY.MANAGE` |
| `POST` | `/holiday-calendars` | `HolidayCalendarCreate` | `DataEnvelope<HolidayCalendarRead>` | `ORG.HOLIDAY.MANAGE` |
| `GET` | `/holiday-calendars/{id}` | — | `DataEnvelope<HolidayCalendarRead>` | `ORG.HOLIDAY.MANAGE` |
| `POST` | `/holiday-calendars/{id}/holidays` | `HolidayCreate` (date, name, type, is_paid) | `DataEnvelope<HolidayRead>` | `ORG.HOLIDAY.MANAGE` |
| `DELETE` | `/holiday-calendars/{id}/holidays/{holiday_id}` | — | `204` | `ORG.HOLIDAY.MANAGE` |
| `GET` | `/holidays` | `?year=&branch_id=` | `ListEnvelope<HolidayRead>` (resolved: branch's state calendar ∪ company-wide calendar) | `ORG.HOLIDAY.MANAGE` |
| `GET` | `/shifts` | filters (`status`) | `ListEnvelope<ShiftRead>` | `ORG.SHIFT.MANAGE` |
| `POST` | `/shifts` | `ShiftCreate` | `DataEnvelope<ShiftRead>` | `ORG.SHIFT.MANAGE` |
| `GET` | `/shifts/{id}` | — | `DataEnvelope<ShiftRead>` | `ORG.SHIFT.MANAGE` |
| `PATCH` | `/shifts/{id}` | `ShiftUpdate` + `If-Match` | `DataEnvelope<ShiftRead>` | `ORG.SHIFT.MANAGE` |
| `DELETE` | `/shifts/{id}` | — | `204` | `ORG.SHIFT.MANAGE` |

### 5.4 Leave Policy Configuration

| Method | Path | Request | Response | Permission |
|---|---|---|---|---|
| `GET` | `/leave-types` | filters (`status`) | `ListEnvelope<LeaveTypeRead>` | `LEAVE.TYPE.MANAGE` |
| `POST` | `/leave-types` | `LeaveTypeCreate` (full field set, Task 4.3.1) | `DataEnvelope<LeaveTypeRead>` | `LEAVE.TYPE.MANAGE` |
| `GET` | `/leave-types/{id}` | — | `DataEnvelope<LeaveTypeRead>` | `LEAVE.TYPE.MANAGE` |
| `PATCH` | `/leave-types/{id}` | `LeaveTypeUpdate` + `If-Match` | `DataEnvelope<LeaveTypeRead>` | `LEAVE.TYPE.MANAGE` |
| `DELETE` | `/leave-types/{id}` | — | `204` | `LEAVE.TYPE.MANAGE` |
| `GET` | `/leave-policies` | — | `ListEnvelope<LeavePolicyRead>` | `LEAVE.POLICY.MANAGE` |
| `POST` | `/leave-policies` | `LeavePolicyCreate` (name, description, is_default) | `DataEnvelope<LeavePolicyRead>` | `LEAVE.POLICY.MANAGE` |
| `GET` | `/leave-policies/{id}` | — | `DataEnvelope<LeavePolicyRead>` (includes resolved items) | `LEAVE.POLICY.MANAGE` |
| `PATCH` | `/leave-policies/{id}` | `LeavePolicyUpdate` + `If-Match` | `DataEnvelope<LeavePolicyRead>` | `LEAVE.POLICY.MANAGE` |
| `DELETE` | `/leave-policies/{id}` | — | `204` | `LEAVE.POLICY.MANAGE` |
| `POST` | `/leave-policies/{id}/items` | `LeavePolicyItemCreate` (leave_type_id, override_accrual_rate?, override_max_balance_cap?) | `DataEnvelope<LeavePolicyItemRead>` | `LEAVE.POLICY.MANAGE` |
| `DELETE` | `/leave-policies/{id}/items/{item_id}` | — | `204` | `LEAVE.POLICY.MANAGE` |
| `POST` | `/leave-policies/{id}/assignments` | `LeavePolicyAssignmentCreate` (scope_type, scope_ref_id?, effective_from) | `DataEnvelope<LeavePolicyAssignmentRead>` | `LEAVE.POLICY.MANAGE` |
| `DELETE` | `/leave-policies/{id}/assignments/{assignment_id}` | — | `204` | `LEAVE.POLICY.MANAGE` |

### 5.5 Payroll Policy Configuration

| Method | Path | Request | Response | Permission |
|---|---|---|---|---|
| `GET` | `/payroll-policy` | — | `DataEnvelope<PayrollPolicyRead>` (`404` if none configured yet) | `PAYROLL.POLICY.MANAGE` |
| `PUT` | `/payroll-policy` | `PayrollPolicyUpsert` (name, pay_cycle, custom_cycle_start_day?, payroll_cutoff_day, pay_date_rule, fixed_pay_day?, holiday_shift_rule?) | `DataEnvelope<PayrollPolicyRead>` | `PAYROLL.POLICY.MANAGE` |

### 5.6 Dashboard

| Method | Path | Request | Response | Permission |
|---|---|---|---|---|
| `GET` | `/dashboards/company` | — | `DataEnvelope<CompanyDashboardSummary>` | `DASHBOARD.COMPANY.VIEW` |

**Total new/changed endpoints this sprint: 68** (2 modified from B1 — `GET/PATCH /companies/current` relocated from `identity` to `organisation` module ownership per Task 2.5.1 — the rest net-new).


---

## 6. RBAC & Permission Catalogue

Per D12, every code below is granted **only** to the seeded `COMPANY_ADMIN` role this sprint. Codes are namespaced per `files/19` §2 (`<MODULE>.<RESOURCE>.<ACTION>`) and registered in each owning module's `permissions.py`, following the existing `identity/permissions.py` pattern (`B1_PERMISSIONS` list of `(code, domain, description)` tuples consumed by the seed/registration path).

| Code | Domain | Description | Granted at |
|---|---|---|---|
| `ORG.COMPANY.MANAGE` | ORG | Manage company profile settings (already exists from B1 — reused, not redefined) | Registration (2.1.3) |
| `ORG.LEGAL_ENTITY.MANAGE` | ORG | Manage legal entities | Registration |
| `ORG.BRANCH.MANAGE` | ORG | Manage branches / work locations | Registration |
| `ORG.DEPARTMENT.MANAGE` | ORG | Manage department hierarchy | Registration |
| `ORG.COST_CENTRE.MANAGE` | ORG | Manage cost centres | Registration |
| `ORG.DESIGNATION.MANAGE` | ORG | Manage designations | Registration |
| `ORG.GRADE.MANAGE` | ORG | Manage grades/bands | Registration |
| `ORG.EMPLOYMENT_TYPE.MANAGE` | ORG | Manage employment types | Registration |
| `ORG.HOLIDAY.MANAGE` | ORG | Manage holiday calendars | Registration |
| `ORG.SHIFT.MANAGE` | ORG | Manage shift master | Registration |
| `ORG.NUMBER_SERIES.MANAGE` | ORG | Manage numbering series config | Registration |
| `LEAVE.TYPE.MANAGE` | LEAVE | Manage leave type master (namespace pre-registered for the future `leave` module, per Task 4.3.1's note) | Registration |
| `LEAVE.POLICY.MANAGE` | LEAVE | Manage leave policy bundles & assignments | Registration |
| `PAYROLL.POLICY.MANAGE` | PAYROLL | Manage payroll cycle/pay-date policy (namespace pre-registered for the future `payroll` module) | Registration |
| `DASHBOARD.COMPANY.VIEW` | DASHBOARD | View the Company Admin dashboard | Registration |

**15 new permission codes** (`ORG.COMPANY.MANAGE` reused from B1, not counted as new). Every endpoint in §5 maps to exactly one of these codes except the two public endpoints (`POST /companies/register`, and implicitly `POST /v1/auth/login`/`refresh` from B1).

**Role → Permission matrix this sprint** (trivial — one role):

| Permission | COMPANY_ADMIN |
|---|:--:|
| All 15 codes above | ● |

**Data scope for every endpoint this sprint:** `COMPANY` (per `hrms/core/rbac/types.py::DataScopeLevel.COMPANY`, the only scope level meaningfully exercised — `TEAM`/`SELF` scoping has no meaning yet since no employee-linked user exists). No field-level masking rules apply this sprint (`files/19` §6's `RESTRICTED`/`SENSITIVE` classifications govern employee/compensation data, none of which is in scope).

**Forward-compatibility note:** `LEAVE.*` and `PAYROLL.*` codes are introduced now, living in the `organisation` module's `permissions.py`, so that Sprint 8/9's `leave`/`payroll` modules can import and reuse these exact codes rather than redefining them — when those modules are scaffolded, move the constant definitions (not the semantics) into the new module's own `permissions.py` and update imports; this is a mechanical relocation, not a new design decision.


---

## 7. Backend Catalogue

Consolidated index — full detail lives in each task above; this section is the "what exists where" lookup for an implementing session that already knows which piece it's building.

### 7.1 Modules

| Module | Package | Status after this sprint |
|---|---|---|
| `identity` | `hrms/modules/identity/` | Existing (B1) — gains `first_name`/`last_name` on `User`; `GET/PATCH /companies/current` ownership moves out to `organisation` |
| `organisation` | `hrms/modules/organisation/` | **New this sprint** — owns every table in §4, every endpoint in §5.1–5.6 except registration's token-issuance delegation |
| `health` | `hrms/modules/health/` | Existing, untouched |

No other module packages are created this sprint (`employee`, `attendance`, `leave`, `payroll`, `workflow`, `notification` remain future-sprint scaffolds per `docs/architecture/01_Backend_Structure.md` §3's target catalogue).

### 7.2 SQLAlchemy models (`hrms/modules/organisation/models.py`, split to package if it grows past ~15 tables per §4.8)

`Company` fields (in `identity/models.py`, unchanged location), `LegalEntity`, `Branch`, `WeekOffPattern`, `Department`, `CostCentre`, `Designation`, `Grade`, `EmploymentType`, `HolidayCalendar`, `Holiday`, `Shift`, `LeaveType`, `LeavePolicy`, `LeavePolicyItem`, `LeavePolicyAssignment`, `PayrollPolicy`, `NumberSeries`, `CompanySetupProgress` — 18 models, full column lists in §4.1–4.2.

### 7.3 Repositories (`hrms/modules/organisation/repository.py`)

One `OrganisationRepository` class (or split by sub-domain if it grows unwieldy — implementer's call, consistent with `02_Module_Standard.md`'s single-file-per-layer default) with methods grouped by entity: `legal_entity_*`, `branch_*`, `department_*` (incl. `get_tree()` recursive CTE), `designation_*`, `grade_*`, `employment_type_*`, `holiday_calendar_*`, `holiday_*`, `shift_*`, `leave_type_*`, `leave_policy_*`, `payroll_policy_*`, `number_series_allocate_next()` (the race-safe `UPDATE...RETURNING`), `setup_progress_*`. Every method takes `company_id` explicitly and filters on it — no method ever trusts a caller-supplied row without the tenant predicate, per `02_Module_Standard.md` §5.

### 7.4 Services (`hrms/modules/organisation/service.py`)

One `OrganisationService` class — the module's sole public interface, per `02_Module_Standard.md` §2. Public methods (one group per entity, matching the repository grouping): registration orchestration (`register_company`), company profile (`get/update_company_profile`), setup progress (`get_setup_progress`, derived per Task 2.3.1 — no explicit `mark_step_complete` needed since it's fully derived), and full CRUD service methods per entity (legal entity, branch, department incl. cycle detection, designation, grade, employment type, holiday calendar/holiday, shift, leave type, leave policy/item/assignment, payroll policy, number series). Cross-cutting: every mutating method calls `AuditService.record()` (§4.7); every deactivation method checks referential blockers (FR-ORG-014) before soft-deleting.

### 7.5 Routers (`hrms/modules/organisation/router.py`)

One `APIRouter(prefix="", tags=["organisation"])` (sub-paths as listed in §5, no `/organisation` prefix — resources are top-level per `files/09` §1.1's flat resource convention) mounted in `hrms/app.py` alongside `identity_router` and `health_router`. Thin per `02_Module_Standard.md` §3's router example — one service call per endpoint, no business logic.

### 7.6 Schemas (`hrms/modules/organisation/schemas.py`)

One `Create`/`Update`/`Read` triad per entity (18 entities × up to 3 schemas ≈ 45–50 Pydantic models), plus the composite response schemas: `CompanyDashboardSummary`, `CompanySetupProgress`, `DepartmentTreeNode` (recursive schema, `children: list["DepartmentTreeNode"]`). All money fields typed as the shared `Money`/`MoneyAmount` value object per ADR-0006 (`grade.min_ctc`/`max_ctc`/`approval_limit`, `payroll_policy` has none this sprint). All follow the existing `build_meta()` helper pattern from `identity/schemas.py` for envelope construction.

### 7.7 Permissions (`hrms/modules/organisation/permissions.py`)

15 constants + a module-level list (mirroring `identity/permissions.py::B1_PERMISSIONS`) — call it `ORGANISATION_PERMISSIONS` — consumed by the registration flow (Task 2.1.3) to grant the full set to the seeded `COMPANY_ADMIN` role. Full list in §6.

### 7.8 Migrations (`apps/api/alembic/versions/`)

One migration per task as itemized in §4.3's build order — approximately 16 migration files this sprint (some tasks combine a table + a deferred FK addition from an earlier task into one file where sequencing allows; exact file count is an implementation detail, not a fixed requirement — what's fixed is the **order**, which must not be violated). Each reviewed for lock behavior per `docs/database/Database_Architecture.md` §9 (none of this sprint's migrations touch high-volume tables, so lock risk is low, but the review step is not skipped).

### 7.9 Background tasks (Celery)

**None this sprint.** No `tasks.py` is added to the `organisation` module. Every module scaffold task (2.1.2) still creates an empty `tasks.py` per the standard layout for structural consistency, but it stays empty — nothing in this sprint's scope is async/deferred work (no accrual jobs, no notification sends, no report generation). The first real `organisation`-owned task will likely be industry-template content expansion (a future sprint, out of scope here).

### 7.10 Import-linter contract

No change to `apps/api/.importlinter` — `organisation` is a `hrms.modules.*` package like `identity`/`health`, already covered by the existing `layers` contract (`hrms.modules → hrms.shared → hrms.core`). The one deliberate cross-module call flagged in Task 2.4.2 (`identity` importing `organisation.service` to embed `setup_status` in `/me`) is a `modules → modules` same-layer call, which the current single-contract `.importlinter` config does **not** yet restrict (it only enforces modules-depend-on-shared-and-core, not modules-depend-on-modules) — if that call is implemented, confirm `uv run lint-imports` still passes; if a stricter same-layer contract is desired, that's a separate architectural decision outside this sprint's scope, not something to add unilaterally here.


---

## 8. Frontend Catalogue

### 8.1 Pages (Next.js App Router, `apps/web/src/app/`)

| Route | Screen | Task |
|---|---|---|
| `(public)/login` | Login | 1.5.2 |
| `(public)/register` | Company Registration | 2.2.1 |
| `(app)/setup` | Setup Checklist | 2.4.1 |
| `(app)/settings/company` | Company Profile (+ Legal Entity, + Number Series section) | 2.5.1, 2.6.2, 4.5.2 |
| `(app)/settings/legal-entities`, `.../new`, `.../[id]` | Legal Entity list/form (standalone, linked from Company Profile) | 2.6.2 |
| `(app)/settings/branches`, `.../new`, `.../[id]` | Branch Management (= Work Locations) | 3.1.2 |
| `(app)/settings/departments` | Department Management (tree) | 3.2.3 |
| `(app)/settings/designations` | Designation & Grade Management | 3.3.3 |
| `(app)/settings/employment-types` | Employment Types | 3.4.2 |
| `(app)/settings/holiday-calendar` | Holiday Calendar | 4.1.3 |
| `(app)/settings/shifts` | Shift Management | 4.2.3 |
| `(app)/settings/leave-policies` | Leave Policy (Types + Policies tabs) | 4.3.4 |
| `(app)/settings/payroll-policy` | Payroll Policy | 4.4.2 |
| `(app)/dashboard` | Company Dashboard | 5.2.1 |

### 8.2 Layouts

| Layout | Scope | Task |
|---|---|---|
| `(public)/layout.tsx` | Minimal chrome (logo only), no sidebar/topbar | 1.4.3 |
| `(app)/layout.tsx` | Sidebar + top bar + content area, auth-guarded | 1.4.3 |
| `<PageContainer dense?>` | Centered 1280px vs. full-bleed content wrapper | 1.4.3 |

### 8.3 Core components (`apps/web/src/components/`)

| Category | Components | Task |
|---|---|---|
| Layout | `Sidebar`, `SidebarNavItem`, `Topbar`, `BreadcrumbTrail`, `ProfileMenu` | 1.4.1, 1.4.2 |
| shadcn primitives | Button, Input, Select, Checkbox, RadioGroup, Switch, Textarea, Label, Form, Table, Card, Tabs, Dialog, Sheet, DropdownMenu, Popover, Tooltip, Toast, Badge, Avatar, Skeleton, Separator, Breadcrumb, Pagination, Command, Calendar | 1.2.1 |
| HRMS composite | `MoneyDisplay`, `StatusPill`, `EmptyState`, `PermissionGate`, `DataTable` (+ column-header, pagination) | 1.2.3 |
| Form infra | `FormField`, `FormSection`, `ServerErrorBanner` | 1.6.1 |
| Interaction | `ConfirmDialog`, `useAppMutation` hook | 1.6.2 |

### 8.4 Forms (create/edit, all built on Form infra §8.3)

Registration form, Company Profile form, Legal Entity form, Branch form, Department form (+ inline cost-centre create), Designation form (+ inline grade create), Grade form, Employment Type form, Holiday Calendar/Holiday forms, Shift form, Leave Type form (largest — grouped into 4 `FormSection`s), Leave Policy form (+ item picker + assignment form), Payroll Policy form (singleton, conditional fields), Number Series section (embedded in Company Profile) — **15 distinct forms**, all sharing the Task 1.6.1 pattern.

### 8.5 Tables (all built on the shared `DataTable`, §1.2.3)

Branch list, Department tree (custom tree component, not `DataTable` — the one list screen that isn't a flat table), Designation list, Grade list, Employment Type list, Holiday list (grouped by month), Shift list, Leave Type list, Leave Policy list, Legal Entity list — **9 `DataTable` instances + 1 custom tree view**.

### 8.6 Dialogs / Drawers

`Sheet` (drawer) used for every create/edit form except the two full-page forms (Registration, Company Profile — both are primary-navigation destinations, not quick-edit overlays). `Dialog` used only for `ConfirmDialog` (deactivate/delete confirmations). No full-screen modal wizards this sprint (the Setup Wizard is a checklist-of-links pattern per D9, not a locked modal stepper).

### 8.7 Cards

Setup-completion progress card, 9× dashboard stat cards (§5.2.1) — all built once as a generic `<StatCard>` composable, not 9 bespoke components.

### 8.8 Filters & Search

In-list filtering only (per-`DataTable` filter props: status, and entity-specific fields like `state_code` on Branch, `department_id` on Designation) — **no global search this sprint** (the top bar's search icon is correctly absent per Task 1.4.2, since no cross-module search index exists yet; deferred until enough modules exist to federate results meaningfully).

### 8.9 Navigation

`apps/web/src/config/navigation.ts` — the typed nav tree (Task 1.4.1), permission-filtered at render. This sprint's tree is a strict subset of the full IA (`docs/design/02_Information_Architecture.md` §2): `Dashboard`, `Settings → {Company, Legal Entities, Branches, Departments, Designations, Employment Types, Holiday Calendar, Shifts, Leave Policies, Payroll Policy}`.

### 8.10 State management

- **Server state:** TanStack Query exclusively (Task 1.3.2) — no entity data duplicated into client-side global state.
- **Session state:** a small client store (Zustand or Context, Task 1.5.1) for `accessToken` (memory-only), `companyId`, `permissions`.
- **Form state:** react-hook-form, local to each form component — never lifted into global state.
- **UI state** (sidebar collapse, active tab): `localStorage` (sidebar) or local component state (tabs) — no global UI store needed at this sprint's scale.


---

## 9. Testing Catalogue

Per-task unit/integration testing requirements are specified inline in every task above and are not repeated here — this section consolidates the suite-level view an implementing or reviewing session can check against.

### 9.1 Unit tests

| Area | Coverage | Task(s) |
|---|---|---|
| Service-layer validation | PAN/GSTIN regex, cycle detection, min/max CTC, mutually-conditional required fields (payroll policy, shift cross-midnight), duplicate-date rejection | 2.6.1, 3.2.1, 3.3.1, 4.2.1, 4.4.1, 4.1.1 |
| Setup progress derivation | Each of 9 steps' completion condition against 0-row / ≥1-row states | 2.3.1 |
| Seed content correctness | 12 leave types, 2 employment types, 1 shift, 1 empty holiday calendar, 1 number series — exact expected values, not just counts | 4.1.2, 4.2.2, 4.3.2 |

### 9.2 Integration tests (real Postgres via testcontainers, existing pattern)

| Area | Coverage | Task(s) |
|---|---|---|
| Full CRUD per entity | Create → read → update (incl. `If-Match`/`409`) → deactivate (incl. referential-block) for every entity in §4 | Every 2.x/3.x/4.x backend task |
| Registration end-to-end | Full row graph created correctly; tokens work; duplicate subdomain/weak password rejected | 2.1.3 |
| Department tree | Cycle rejection at every depth; correct nested-JSON tree output | 3.2.1 |
| Holiday resolution | `AC-ORG-008.1` — state-specific + national holidays correctly unioned per branch | 4.1.1 |
| Number series concurrency | `AC-ORG-011.1` — 50 concurrent allocations, zero gaps/duplicates | 4.5.1 |
| Leave policy resolution | Override values correctly resolved through `leave_policy_item`; overlapping assignment rejected | 4.3.3 |
| Dashboard aggregation | Counts match seeded data exactly, cross-tenant isolated | 5.1.1 |

### 9.3 Security tests

| Suite | Coverage | Task |
|---|---|---|
| Permission matrix | Every (role, endpoint) pair in §5/§6 — `COMPANY_ADMIN` allowed, zero-permission user denied (`403`) | 6.1.1 |
| Cross-tenant isolation | Every new table — Company B cannot read/write Company A's rows (`404`, never `403`) | 6.1.2 |
| Existing B1 suite | `apps/api/tests/integration/auth/test_auth_security.py` — unchanged, must still pass (regression check, not new work) | Continuous |

### 9.4 UI (component) tests

| Area | Coverage | Task(s) |
|---|---|---|
| `PermissionGate`, `MoneyDisplay` | Logic-bearing composites | 1.2.3 |
| `ApiError`/refresh interceptor | Envelope unwrapping, error mapping, single-flight refresh | 1.3.1, 1.5.3 |
| Every form | Client-side validation, server-error field-mapping | Every Epic 2–4 frontend task |
| Sidebar permission filtering | Correct nav items per mock permission set | 1.4.1 |
| Tree components | Correct nesting, cycle-prevention in parent picker | 3.2.3 |

### 9.5 API contract tests

No dedicated OpenAPI-snapshot CI exists yet (flagged as a still-open follow-up in `docs/SPRINT0_FOUNDATION.md` §4, "Add after auth stabilises" — auth stabilised in B1, so this sprint is a reasonable point to pick it up, but it is **not** itemized as a task above since it wasn't named in the sprint brief; flagging here as a candidate for Epic 6 if capacity allows, not a hard requirement of this sprint's Definition of Done). In its absence, the integration test suite (§9.2) against real request/response schemas is the de facto contract check.

### 9.6 End-to-end tests

| Test | Coverage | Task |
|---|---|---|
| Full sprint journey | Register → Setup Wizard (all 9 steps) → Dashboard → logout/login resume | 6.3.1 |
| Auth guard | Unauthenticated access redirects to `/login` | 1.4.3 |
| Login flow | Valid/invalid credentials, redirect targets | 1.5.2 |
| Accessibility | Zero critical `axe` violations across all 13 screens | 6.2.2 |

### 9.7 Test-to-screen coverage matrix

Every screen in §3.2 has: ≥1 component test (form/list rendering + validation), ≥1 integration test (its backing endpoint(s)), and is included in the E2E journey (6.3.1) at least once. No screen ships with only manual verification.

---

## 10. Sprint Closeout

This document is complete when every checkbox in §1's Definition of Done is checked. At that point:

1. Update `docs/README.md`'s "Sprint deliverables" list to add a link to this document (matching the existing pattern for Sprint 0 and B1).
2. Update `docs/product/VERSION_1_ROADMAP.md` §5 (Module Breakdown) and §14 (Sprint Breakdown) status columns for the modules this sprint delivers (rows 4, 8–16 move from "⏳ Not started" to "✅ Delivered"; Sprint 3's row moves from "⏳ Next" to "✅ Complete").
3. Do **not** retroactively edit this document's task list to match what was actually built if scope shifted during implementation — instead, write a short `docs/SPRINT_3_COMPANY_FOUNDATION_SUMMARY.md` (mirroring `docs/SPRINT_B1_IDENTITY.md`'s format) capturing what actually shipped, deltas from this plan, and carried-forward risks — the same pattern already established for Sprints 0 and B1. This document (`SPRINT_3_COMPANY_FOUNDATION.md`) stays as the historical plan; the summary is the historical record of execution.
4. Sprint 4 (Employee Management, per `docs/product/VERSION_1_ROADMAP.md` §14) can begin — it consumes: `branch`, `department`, `designation`, `grade`, `employment_type` (assignment targets), `number_series` (`EMPLOYEE_CODE` allocation), `leave_policy_assignment` (policy resolution per new hire), and the `organisation` module's established patterns (module structure, RLS, permission-namespacing convention) as its own starting template.
