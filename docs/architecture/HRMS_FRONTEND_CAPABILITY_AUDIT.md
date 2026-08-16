# HRMS Frontend Capability Audit — Real User Experience

**Status:** Audit only. No application code, migrations, backend code, UI redesign, or git
commits were created or modified to produce this document.

**Date:** 2026-08-15

**Question this document answers:** *What can a real HR/Admin user actually DO through the
frontend today?*

**Scope of inspection:** `apps/web/src/**` (source only; `.next` build artifacts ignored),
plus backend routers under `apps/api/src/hrms/modules/` solely to compare shipped API vs UI.
Evidence is from current source, not from product docs as a substitute for code.

**Legend**

| Label | Meaning |
|---|---|
| **FACT** | Observed directly in frontend (or, for backend columns of matrices, in API routers). |
| **VERIFIED** | Confirmed by reading the implementing page/form and its API call sites. |
| **PARTIAL** | UI exists and calls a real API, but a requested capability is missing, incomplete, or degraded. |
| **MISSING** | No frontend route, page, nav item, or component for this capability. |
| **BLOCKED** | Workflow cannot continue from the UI (typically because a later screen does not exist). |
| **UNKNOWN** | Not independently verified in a live browser. |

---

## 1. Executive Summary

**FACT / VERIFIED:** The current frontend is a Next.js 14 App Router application that lets an
authenticated company admin **register/login**, **view a dashboard and subscription**, **edit
the company profile**, and **fully CRUD (soft-deactivate/reactivate) Organisation master data**:
Legal Entity, Branch, Department, Designation, Grade, and Shift.

**FACT / MISSING:** There is **no Employee UI**. A glob of `apps/web/src` shows zero
`employee` routes, components, or API client calls to `/employees`. Sidebar `NAV_ITEMS` has no
Employees/Employment/Assignment/Compensation/Statutory/Banking/Attendance/Leave/Payroll items.

**FACT / BLOCKED:** A real HR/Admin can configure the organisation through the UI and then
**must stop**. They cannot hire, assign, pay, or terminate anyone without using the API,
database, or developer tools.

**Verdict:** Organisation usable / Employee unavailable.

---

## 2. Current Frontend Architecture

Inspected: `apps/web/package.json`, `apps/web/src/app/**`, `apps/web/src/components/**`,
`apps/web/src/lib/**`, `apps/web/src/hooks/**`.

| Concern | What exists | Evidence | Status |
|---|---|---|---|
| Framework | Next.js `^14.2.28`, React `^18.3.1`, TypeScript, Tailwind `^3.4.17` | `apps/web/package.json` | **FACT** |
| Routing | App Router file-based routes under `src/app` | 19 `page.tsx` files; no `createBrowserRouter` | **FACT** |
| Layouts | Root layout (`app/layout.tsx`) wraps `Providers`. `/app/*` uses client `app/app/layout.tsx` → `AppShell`. Auth pages use `AuthLayout`. | Those files | **FACT** |
| Authentication | JWT in `localStorage` (`hrms.session`). Login `POST /v1/auth/login`. Register `POST /v1/companies/register` then `applyTokenResponse`. Refresh on 401 via `POST /v1/auth/token/refresh`. Logout `POST /v1/auth/logout` (best-effort). `/auth/me` for profile. | `auth-context.tsx`, `token-storage.ts`, `client.ts` | **FACT** |
| Protected routes | Everything under `/app` redirects to `/login` when `status === "unauthenticated"`. No Next.js `middleware.ts`. Guard is client-side only. | `app/app/layout.tsx`; glob found 0 `middleware.ts` | **FACT** |
| Public routes | `/` (dev health), `/login`, `/register` | `app/page.tsx`, `app/login/page.tsx`, `app/register/page.tsx` | **FACT** |
| Navigation | Static `NAV_ITEMS` rendered by `SidebarNav`. Not filtered by role/permission. | `nav-items.ts`, `sidebar-nav.tsx` | **FACT** |
| Role handling | None in UI. | No role types/guards in `apps/web/src` | **MISSING** |
| Permission handling | `UserProfile.permissions: string[]` is loaded from `/auth/me` and **never read** to hide/disable controls. 403 is handled after the API returns. | Grep: no `user.permissions` / `hasPermission` / `PermissionGate` / `usePermission` | **MISSING** (proactive); **FACT** (reactive 403 copy) |
| API client | `apiClient.get/post/patch/delete` → `fetch(`${API_BASE}/v1${path}`)`. Attaches `Authorization`, `X-Company-Id`, `X-Request-Id`, optional `If-Match`. Unwraps `DataEnvelope.data`. | `lib/api/client.ts` | **FACT** |
| Error handling | `ApiError` / `NetworkError`; `getFieldError`; `describeApiError`; `ErrorState` with retry; toasts on mutations | `lib/api/errors.ts`, page files | **FACT** |
| Loading states | `LoadingState` spinner (`Loader2`). `useApiResource` loading flag. Full-page spinner while auth resolves. | `loading-state.tsx` | **FACT** |
| Skeletons | `components/ui/skeleton.tsx` exists | Grep: `Skeleton` is only defined, never imported by pages | **PARTIAL** (unused) |
| Form infrastructure | Controlled forms + `FormField` + per-module `validate-*.ts`. No React Hook Form / Zod. | `form-field.tsx`, `lib/*/validate-*.ts` | **FACT** |
| Reusable UI | shadcn-style: Button, Card, Dialog, Sheet, DropdownMenu, Badge, Input, Label, NativeSelect, ScrollArea, Separator, Tooltip | `components/ui/*` | **FACT** |
| Tables/lists | Organisation lists are `<ul>` rows, not a table component. No shared `DataTable`. | list pages | **FACT** |
| Dialogs / modals | Radix Dialog for create forms and deactivate/reactivate confirmations | list + `[id]` pages | **FACT** |
| Tabs | None | Grep `Tabs` unused except no component | **MISSING** |
| Pagination | None in UI. `lib/api/types.ts` has no list pagination fields. | types + list pages | **MISSING** |
| Filtering / search | None on any list | list pages | **MISSING** |
| Toast | Custom `ToastProvider` / `useToast`, 5s auto-dismiss, success/danger/default | `toast.tsx` | **FACT** |
| Confirmation | Deactivate/reactivate via Dialog (not AlertDialog). Copy states recovery is possible. | `[id]` pages | **FACT** |
| Optimistic concurrency UI | PATCH/DELETE send `ifMatch: String(entity.version)`. 409 `STALE_RESOURCE` shows banner + Reload / Cancel. `getStaleResourceCurrent` exists but is unused (company page imports it, never calls it). | `[id]` pages, `client.ts`, `errors.ts` | **VERIFIED** / **PARTIAL** (no apply-current-from-error) |
| Empty states | Shared `EmptyState` with icon, copy, CTA on org lists | list pages | **FACT** |
| Responsive | `AppShell`: sidebar `hidden … md:block`; hamburger + left `Sheet` below `md` (768px). Forms `grid-cols-1 sm:grid-cols-2`. Comment in `app-shell.tsx` claims ≥1024px; CSS uses `md`. | `app-shell.tsx` | **FACT** / **PARTIAL** (breakpoint mismatch vs comment) |
| `BackendPendingNotice` | Component exists for honest “API not shipped” | **never imported** by any page | **FACT** (dead code) |

---

## 3. Route Inventory

**FACT:** All product pages under `/app` are `"use client"` and render only after the auth
layout admits the user. No placeholder pages that render static mock entity lists were found.
Dashboard explicitly renders `"—"` for `null` counts rather than fabricating zeros.

| Route | Page | Authentication | Role/Permission | Real functionality | Status |
|---|---|---|---|---|---|
| `/` | Local-dev API health | Public | None | `GET {API}/health` (not `/v1`). Shows backend URL/status. Not a product home. | **FACT** — usable, not HR product |
| `/login` | Sign in | Public | None | `POST /v1/auth/login` → dashboard. Client validation; 401/423/429 messages. **No** redirect if already authenticated. | **VERIFIED** |
| `/register` | Company + admin signup | Public | None | `POST /v1/companies/register` → session → `/app/setup`. Field + 409/422 handling. | **VERIFIED** |
| `/app` | Redirect | Protected | None | `redirect("/app/dashboard")` | **FACT** |
| `/app/dashboard` | Dashboard | Protected | Reactive 403 only | `GET /dashboards/company`, `/companies/current/subscription`, `/companies/current`. View company, plan, seat limit, branch/dept counts. Employee count always `"—"` because API returns `employee_count=None`. | **VERIFIED** / **PARTIAL** |
| `/app/company` | Company profile | Protected | Reactive 403 | View + edit `GET/PATCH /companies/current` with If-Match. Currency locked after trial. | **VERIFIED** |
| `/app/setup` | Setup progress | Protected | Reactive 403 | `GET /companies/current/setup-progress`. Only `COMPANY_PROFILE` has a destination. | **VERIFIED** / **PARTIAL** |
| `/app/legal-entities` | LE list + create dialog | Protected | Reactive 403 | `GET/POST /legal-entities` | **VERIFIED** |
| `/app/legal-entities/[id]` | LE detail/edit/status | Protected | Reactive 403 | `GET/PATCH/DELETE` + reactivate PATCH `{is_active:true}` | **VERIFIED** |
| `/app/branches` | Branch list + create | Protected | Reactive 403 | `GET/POST /branches`; also loads legal entities for picker. Blocks create if no LE. | **VERIFIED** |
| `/app/branches/[id]` | Branch detail/edit/status | Protected | Reactive 403 | Full address + geofence fields; deactivate blocked if dependents (API 409) | **VERIFIED** |
| `/app/departments` | Dept list + create | Protected | Reactive 403 | `GET/POST /departments`; loads branches. **Flat list**, not a tree. | **VERIFIED** |
| `/app/departments/[id]` | Dept detail/edit/status | Protected | Reactive 403 | Parent/branch pickers; cycle/depth 409 mapped to inline errors | **VERIFIED** |
| `/app/designations` | Designation list + create | Protected | Reactive 403 | `GET/POST /designations`; loads departments + grades | **VERIFIED** |
| `/app/designations/[id]` | Designation detail/edit/status | Protected | Reactive 403 | Department + Grade selects | **VERIFIED** |
| `/app/grades` | Grade list + create | Protected | Reactive 403 | `GET/POST /grades`; duplicate code → inline error | **VERIFIED** |
| `/app/grades/[id]` | Grade detail/edit/status | Protected | Reactive 403 | Level, CTC band, notice/probation, approval limit | **VERIFIED** |
| `/app/shifts` | Shift list + create | Protected | Reactive 403 | `GET/POST /shifts` | **VERIFIED** |
| `/app/shifts/[id]` | Shift detail/edit/status | Protected | Reactive 403 | Timings, breaks, grace, half/full-day hours, flags | **VERIFIED** |
| `/app/employees` (any) | — | — | — | No `page.tsx` | **MISSING** |
| Attendance / Leave / Payroll routes | — | — | — | No pages | **MISSING** |

Per-route capability checklist (Organisation `[id]` pages share one pattern):

| Capability | Login/Register | Dashboard/Setup/Company | Org lists | Org details |
|---|---|---|---|---|
| Page actually renders | Yes | Yes | Yes | Yes |
| Calls real backend API | Yes | Yes | Yes | Yes |
| API integration complete for shipped fields | Yes | Company yes; setup only one step mapped; dashboard employee count null | Yes for list+create | Yes for view/edit/deactivate/reactivate |
| Placeholder / mock data | No | Dashboard copy says future modules; counts `"—"` not mock | No | No |
| Create | Register creates company | No (company already exists) | Yes (dialog) | No |
| Edit | No | Company yes | No | Yes |
| Deactivate / reactivate | No | No | No (status badge only) | Yes (confirm dialog) |
| Hard delete | No | No | No | No (**FACT**: DELETE is soft-deactivate) |
| View details | N/A | Yes | Link to `[id]` | Yes |
| Errors | Inline + banner | `ErrorState` + retry | `ErrorState` + retry; 422 inline; 403 toast | Same + stale banner |
| Loading | Submit button text | `LoadingState` | `LoadingState` | `LoadingState` |
| Empty | N/A | N/A | `EmptyState` + CTA | 404 message, no retry |

---

## 4. Navigation Inventory

### Current navigation

Source: `apps/web/src/components/layout/nav-items.ts` rendered by `sidebar-nav.tsx` in the
desktop aside and the mobile `Sheet`. **FACT:** every authenticated user sees the same list.
No permission/role condition.

| Label | URL | Icon (lucide-react) | Permission/role | Works? | Destination | Actual capabilities |
|---|---|---|---|---|---|---|
| Dashboard | `/app/dashboard` | `LayoutDashboard` | None | Yes | Company dashboard | View-only summary + subscription |
| Company | `/app/company` | `Building2` | None | Yes | Company profile | View/edit profile |
| Legal Entities | `/app/legal-entities` | `Landmark` | None | Yes | LE list | List/create; details via row |
| Branches | `/app/branches` | `Building` | None | Yes | Branch list | List/create; details via row |
| Departments | `/app/departments` | `Network` | None | Yes | Dept list | List/create; details via row |
| Designations | `/app/designations` | `Briefcase` | None | Yes | Designation list | List/create; details via row |
| Grades | `/app/grades` | `Layers` | None | Yes | Grade list | List/create; details via row |
| Shifts | `/app/shifts` | `Clock` | None | Yes | Shift list | List/create; details via row |
| Setup | `/app/setup` | `ListChecks` | None | Yes | Setup progress | Read progress; link to company profile |

### Requested items vs actual nav

| Item | In sidebar? | Status |
|---|---|---|
| Company | Yes | **FACT** |
| Legal Entities | Yes | **FACT** |
| Branches | Yes | **FACT** |
| Departments | Yes | **FACT** |
| Designations | Yes | **FACT** |
| Grades | Yes | **FACT** |
| Shifts | Yes (label “Shifts”, not “Shift Rules”) | **FACT** |
| Employees | **No** | **MISSING** |
| Employment | **No** | **MISSING** |
| Assignments | **No** | **MISSING** |
| Compensation | **No** | **MISSING** |
| Statutory | **No** | **MISSING** |
| Banking | **No** | **MISSING** |
| Attendance | **No** | **MISSING** |
| Leave | **No** | **MISSING** |
| Payroll | **No** | **MISSING** |

Header chrome (**FACT**): company name from `GET /v1/auth/companies/{id}` (`CompanyContext`);
user menu with email + Sign out. Session stores `companies[]` but there is **no company
switcher**.

---

## 5. Organisation Capabilities

### 5.1 Company

| Action | Usable? | Evidence | Label |
|---|---|---|---|
| View company | Yes | `/app/company` + `CompanyProfileView`; dashboard also shows name/status | **VERIFIED** |
| Edit company | Yes | Inline edit, `PATCH /companies/current` + If-Match | **VERIFIED** |
| Manage company settings | Partially | Profile covers locale, working days, hours, branding URLs. No separate settings/app-config UI. Currency locked after `TRIAL`. | **PARTIAL** |
| See company information | Yes | Identity, contact, address, localization, schedule, branding, status, subdomain, trial dates | **VERIFIED** |
| See subscription/plan | Yes, read-only | Dashboard `GET /companies/current/subscription` (plan, status, trial, seats, feature flags). Cannot change plan. | **VERIFIED** / **PARTIAL** |
| Other | Setup tracker | `/app/setup` only links `COMPANY_PROFILE` | **PARTIAL** |

### 5.2 Legal Entity

| Action | Usable? | Label |
|---|---|---|
| List | Yes — includes inactive (`is_active` badge). API list does not filter `is_active`. | **VERIFIED** |
| Create | Yes — dialog; client + 422 field errors | **VERIFIED** |
| Open details | Yes — `/app/legal-entities/[id]` | **VERIFIED** |
| Edit | Yes — If-Match PATCH | **VERIFIED** |
| Deactivate | Yes — confirmed DELETE (soft) | **VERIFIED** |
| Reactivate | Yes — PATCH `{is_active: true}` | **VERIFIED** |
| Select related entities | N/A on create (LE is root). No “related entities” picker. | **MISSING** (not in UI) |
| Validation errors | Client (name required; PAN/GSTIN format in `validate-legal-entity.ts`) + 422 inline | **VERIFIED** |
| Concurrency | 409 STALE_RESOURCE banner + reload/cancel | **VERIFIED** |
| Signature image URL | In TS type / API; **not** on the form | **PARTIAL** |
| Blocked deactivate | 409 `LEGAL_ENTITY_HAS_ACTIVE_BRANCHES` toast | **VERIFIED** |

### 5.3 Branch

| Action | Usable? | Label |
|---|---|---|
| List | Yes | **VERIFIED** |
| Create | Yes; disabled/empty-state if no legal entities | **VERIFIED** |
| Edit | Yes | **VERIFIED** |
| Deactivate / reactivate | Yes; 409 when dependents exist | **VERIFIED** |
| Assign legal entity | Yes — required `NativeSelect` | **VERIFIED** |
| Enter address | Yes — lines, city, IN state codes, PIN, timezone text | **VERIFIED** |
| Geofence | Lat/long/radius numeric fields. Copy says map editor + enforcement ship with Attendance. No map. | **PARTIAL** |
| Errors | Client + 422 inline | **VERIFIED** |

### 5.4 Department

| Action | Usable? | Label |
|---|---|---|
| List | Yes — **flat `<ul>`**, parent name as subtitle text | **VERIFIED** |
| Create | Yes | **VERIFIED** |
| Edit | Yes | **VERIFIED** |
| Deactivate / reactivate | Yes | **VERIFIED** |
| Select branch | Optional picker | **VERIFIED** |
| Select parent | Optional picker; on edit, self+descendants excluded (`descendantIds`) | **VERIFIED** |
| Create hierarchy | Yes via parent_id | **VERIFIED** |
| See hierarchy | **No tree view**. Comment in `validate-department.ts`: “no `/tree` endpoint this slice… flat picker instead of a tree combobox.” | **FACT** — flat only |
| Cycle / depth | Client prevents picking descendants. Server 409 `DEPARTMENT_CYCLE_DETECTED` / `DEPARTMENT_MAX_DEPTH_EXCEEDED` (depth 5) shown inline **on edit**. Create page toasts generic 409, does not map those codes to `parentId`. | **PARTIAL** |

### 5.5 Designation

| Action | Usable? | Label |
|---|---|---|
| List / create / edit / deactivate / reactivate | Yes | **VERIFIED** |
| Select department | Optional | **VERIFIED** |
| Select Grade | Optional (`grade.name (grade.code)`) | **VERIFIED** |

### 5.6 Grade

| Action | Usable? | Label |
|---|---|---|
| List / create / edit / deactivate / reactivate | Yes | **VERIFIED** |
| Configure level | Optional number | **VERIFIED** |
| CTC range | Min/max CTC in whole rupees; converted to minor units (ADR-0006) | **VERIFIED** |
| Notice / probation | Optional days | **VERIFIED** |
| Approval limit | Optional rupees → minor units | **VERIFIED** |
| Duplicate code | Create maps 409 `GRADE_CODE_ALREADY_EXISTS` to inline code error | **VERIFIED** |
| Select Grade from Designation | Yes on designation form | **VERIFIED** |

### 5.7 Shift Rules

Nav label is **Shifts**. Form covers the shift-rule fields the API exposes.

| Action | Usable? | Label |
|---|---|---|
| List / create / edit / deactivate / reactivate | Yes | **VERIFIED** |
| Timings | Start/end as `HH:mm` text (not `type="time"`) | **VERIFIED** / **PARTIAL** (mobile time pickers unused) |
| Breaks | Paid/unpaid minutes | **VERIFIED** |
| Grace | In/out minutes | **VERIFIED** |
| Full-day / half-day hours | Optional thresholds | **VERIFIED** |
| Cross-midnight / night / OT | Checkboxes | **VERIFIED** |
| Validation | Client `TIME_PATTERN` + server 422 | **VERIFIED** |

Lists have **no search, filter, or pagination**. Inactive records remain visible with a badge
(**FACT** from list pages + backend `deleted_at IS NULL` without `is_active` filter).

---

## 6. Employee Capabilities

### Search results in `apps/web/src`

Grep for employee/employment/assignment/compensation/statutory/banking/employee code/status/
reporting manager/shift assignment hits **copy and Organisation fields only**:

- Dashboard tile “Employees” bound to `employee_count` (API currently returns `null` → `"—"`).
- Grade/designation/department marketing copy (“employees will hold…”).
- Legal Entity “Statutory identifiers” (PF/ESI/PAN of the **legal entity**, not the person).
- Grade “Compensation band”.
- Branch geofence note about Attendance.

**FACT / MISSING:** There is no `apps/web/src/app/app/employees` directory, no employee
components, no `lib/employee`, and no `apiClient` calls to `/employees*`.

| Route | Purpose | API calls | Capabilities | Completeness | Reachable from nav |
|---|---|---|---|---|---|
| *(none)* | — | — | — | — | No |

### Employee Foundation

| Can a real HR/Admin… | UI today |
|---|---|
| Create an employee | **NO** — **MISSING** |
| Enter identity details | **NO** |
| Generate employee code | **NO** in UI. Backend allocates on `POST /employees` (**FACT** in API schemas). |
| View / list / edit | **NO** |
| Deactivate / reactivate | **NO** |

### Employment

Create, history, terminate, rehire, timeline, effective dates: **NO UI**. Backend routes exist
(`POST/GET/PATCH …/employments`, `POST …/terminate`). **MISSING** frontend / **FACT** backend.

### Assignment

Branch, department, designation, grade, reporting manager, shift, change, history: **NO UI**.
Backend `GET/POST …/assignments` including `shift_id` and `SHIFT_CHANGE`. **MISSING** frontend.

### Compensation

Create, view, salary history, effective dates, revise: **NO UI**. Backend
`GET/POST …/compensation`. **MISSING** frontend.

### Statutory (person-level)

**NO UI.** Backend `EmployeeCreate`/`EmployeeUpdate` **explicitly exclude** PAN/Aadhaar/UAN
write paths (`schemas.py` module docstring). Columns exist on the model. **MISSING** UI;
**PARTIAL** backend (columns, no write API).

### Banking

**NO UI.** No employee banking router/module under `apps/api/src/hrms/modules/`. **MISSING**
frontend and backend.

---

## 7. Backend vs Frontend Matrix

Backend column = mounted in `apps/api/src/hrms/app.py` (`health`, `identity`, `organisation`,
`employee`). Attendance/Leave/Payroll modules are absent from `modules/`.

| Feature | Backend | API | Frontend | User can use it? |
|---|---|---|---|---|
| Register company + admin | YES | YES `POST /companies/register` | YES `/register` | YES |
| Login / logout / refresh / me | YES | YES `/auth/*` | YES | YES |
| Company profile | YES | YES `GET/PATCH /companies/current` | YES | YES |
| Setup progress | YES | YES | YES (one step linked) | PARTIAL |
| Subscription view | YES | YES | YES dashboard (read-only) | PARTIAL |
| Company dashboard | YES | YES | YES | PARTIAL (employee_count null) |
| Legal Entity | YES | YES | YES | YES |
| Branch | YES | YES | YES | YES |
| Department | YES | YES | YES (flat, not tree) | YES |
| Designation | YES | YES | YES | YES |
| Grade | YES | YES | YES | YES |
| Shift Rules | YES | YES | YES | YES |
| Employee | YES | YES `/employees` | **NO** | **NO** |
| Employment | YES | YES `…/employments` | **NO** | **NO** |
| Assignment | YES | YES `…/assignments` | **NO** | **NO** |
| Shift assignment | YES (via assignment `shift_id` / `SHIFT_CHANGE`) | YES | **NO** | **NO** |
| Compensation | YES | YES `…/compensation` | **NO** | **NO** |
| Statutory (employee PAN/Aadhaar/UAN) | Columns only; no write API | NO write | **NO** | **NO** |
| Banking | NO module | NO | **NO** | **NO** |
| Attendance | NO module | NO | **NO** | **NO** |
| Leave | NO module | NO | **NO** | **NO** |
| Payroll | NO module | NO | **NO** | **NO** |
| PermissionGate / usePermission | `require_permission` on API | YES (403) | **NO** | N/A (API-only) |

---

## 8. Real User Workflows

### Workflow A — Configure organisation

**VERIFIED — yes**, for an admin who can call the Organisation APIs (typical company creator).

Exact usable flow:

1. Open `/login` or `/register`.
2. After auth, land on `/app/dashboard` (login) or `/app/setup` (register).
3. Sidebar: Company → edit profile (name, locale, working days, hours, branding URLs).
4. Legal Entities → Add → open row → edit / deactivate / reactivate.
5. Branches → Add (requires a legal entity) → address + optional geofence numbers → edit / status.
6. Departments → Add (optional branch + parent) → edit / status. Hierarchy is parent picker +
   flat list, not a tree.
7. Grades → Add (code/name/level/CTC/notice/probation/approval) → edit / status.
8. Designations → Add (optional department + grade) → edit / status.
9. Shifts → Add (timings, breaks, grace, hours, flags) → edit / status.

Order is not enforced by the UI except Branch requiring a Legal Entity. Setup page does not
walk the user through steps 4–9.

### Workflow B — Add an employee

**BLOCKED.**

Login → Organisation setup (Workflow A) → **STOP — no Employees nav item, route, or form.**

Do not treat `POST /v1/employees` as a user-facing capability.

### Workflow C — Hire employee

**BLOCKED** at employee creation. Employment, assignment, shift assignment, and compensation
screens do not exist.

### Workflow D — Terminate employee

**BLOCKED.** No terminate control. API `POST …/employments/{id}/terminate` is unused by UI.

### Workflow E — Rehire employee

**BLOCKED.** No UI. API rehire is `POST …/employments` on an existing employee.

---

## 9. Permissions UX

**FACT:** `/auth/me` returns `user.permissions: string[]`. Auth context stores `user` including
permissions. **No consumer** checks them.

**FACT:** Nav is unconditional. Create/Edit/Deactivate buttons always render for anyone who
can open `/app`.

**FACT:** Pages map HTTP 403 to copy (“You do not have permission to view …”) and create
actions toast then close the dialog. There is no dedicated `/403` page. 404 on detail pages
shows “could not be found” without retry.

Classification: **B. Reactive only (API returns 403)**, with a small amount of 403-specific
copy. Not mixed-proactive: there is no PermissionGate / usePermission (architecture baseline
gap, confirmed still absent).

Example: Legal Entities list always shows “Add Legal Entity” when the list is non-empty; a
user without create permission discovers that only after submit (`legal-entities/page.tsx`).

---

## 10. UX Completeness

Pattern is consistent across Organisation pages. Evaluated from the actual page files.

### Loading

Blocking `LoadingState` spinner + label. No skeletons in product pages. Auth layout: full-page
spinner “Loading your workspace…”.

### Empty state

Org lists: titled explanation + CTA. Branch: extra empty state if no legal entities, linking
to Legal Entities. Dashboard: not an empty-list pattern.

### Error state

`ErrorState` with message + Try again (except 404 on details). Mutation failures: toast and/or
inline field errors. 403 list/detail: permission sentence.

### Forms

Client validation on submit; server 422 mapped to fields (subset of fields per page). Required
markers via `FormField`. **No dirty-state / unsaved-changes guard** (grep found no
`beforeunload` / dirty handling). Cancel on edit discards without prompt.

### Concurrency

If-Match on PATCH/DELETE. Stale: message + reload latest + cancel. Does not auto-apply
`context.current` from the error (`getStaleResourceCurrent` unused).

### Destructive actions

Deactivate/reactivate confirmed. Copy says the record can be reactivated. Hard delete is not
offered. Dependent-block 409s explained in toasts for LE/branch.

### Navigation

No breadcrumb component. Detail pages have a `← {List}` link. Deep links to `/app/.../[id]`
work if the user is authenticated (client guard). Refresh re-fetches. Login does not bounce
authenticated users away from `/login`.

---

## 11. Responsive / Mobile State

Do not equate “Tailwind is present” with a designed mobile HRMS.

| Surface | What the code actually does | Assessment |
|---|---|---|
| Navigation | Sidebar hidden below `md` (768px). Hamburger opens Radix `Sheet` with the same `SidebarNav`. | **FACT** — collapse exists |
| Comment vs CSS | `app-shell.tsx` comment says ≥1024px; class is `md:block` (768px) | **PARTIAL** |
| Forms | `grid-cols-1` then `sm:grid-cols-2` (640px). Dialogs `max-w-2xl` + `max-h-[60vh] overflow-y-auto`. | Usable; long create forms scroll inside the dialog |
| Lists | Horizontal flex row (name + badge). No `overflow-x` table. Long names wrap via flex. | Likely OK; not tested in a browser |
| Dialogs | Radix Dialog/Sheet — touch overlay close supported by Radix | **FACT** (component), **UNKNOWN** (device) |
| Detail pages | Same grids as forms | Desktop-first, stacks on small screens |
| Time fields | Text `HH:mm`, not native time inputs | Weaker on mobile |
| Touch | Icon buttons in header (`size="icon"`) | Present; no dedicated touch targets audit |

**UNKNOWN** without device testing: actual overflow, iOS keyboard covering dialog footers,
and tablet mid-widths.

---

## 12. Test Coverage

**FACT:** Vitest + Testing Library + jsdom (`apps/web/package.json` `test`: `vitest run`).
30 test files under `apps/web/src`.

| Area | Tests | Type | API |
|---|---|---|---|
| `apiClient` | `client.test.ts` | Unit | Real `fetch` stub, not live server |
| Auth context / login validation / registration validation | yes | Unit/component | Mocked client |
| App layout guard | `layout.test.tsx` | Component | Auth mocked |
| Login / register pages | yes | Component | Client mocked |
| Dashboard, company, setup | page tests | Component | `vi.mock("@/lib/api/client")` |
| LE, Branch, Dept, Designation, Grade, Shift list + `[id]` | page tests | Component | Mocked; cover list, 403, create, If-Match save, STALE_RESOURCE, deactivate/reactivate |
| Form validators | `validate-*.test.ts` | Unit | None |
| `loading-state` | yes | Component | N/A |
| PermissionGate / usePermission | **none** (hooks do not exist) | — | — |
| Responsive | **none** | — | — |
| Playwright / Cypress / live API e2e | **none** in `apps/web` | — | — |

Passing component tests with mocked `apiClient` **do not prove** end-to-end usability against
a running API.

---

## 13. Browser Verification

MCP tool catalog for this session returned **no servers**. No browser automation was available.

**Manual browser verification not performed.**

Findings above are from source inspection and existing component tests, not a live
click-through. Do not treat this section as a substitute for QA on a running stack.

---

## 14. Current Product Capability Matrix

| Business Area | Backend | Frontend | User Can Use? | Completeness |
|---|---|---|---|---|
| Company | YES | YES | YES | High for profile view/edit; no plan change; setup checklist incomplete vs org modules |
| Legal Entity | YES | YES | YES | High; no signature upload; no search/pagination |
| Branch | YES | YES | YES | High; geofence is numeric-only, no map |
| Department | YES | YES | YES | Medium-high; **flat list**, not tree; create-path cycle/depth UX weaker than edit |
| Designation | YES | YES | YES | High for master-data CRUD |
| Grade | YES | YES | YES | High for master-data CRUD |
| Shift Rules | YES | YES | YES | High for rule CRUD; times are text |
| Employee | YES | **NO** | **NO** | None |
| Employment | YES | **NO** | **NO** | None |
| Assignment | YES | **NO** | **NO** | None |
| Shift Assignment | YES (assignment field) | **NO** | **NO** | None |
| Compensation | YES | **NO** | **NO** | None |
| Statutory | PARTIAL (columns, no write API) | **NO** | **NO** | None |
| Banking | NO | **NO** | **NO** | None |
| Attendance | NO | **NO** | **NO** | None |
| Leave | NO | **NO** | **NO** | None |
| Payroll | NO | **NO** | **NO** | None |

---

## 15. What a Real HR/Admin Can Do Today

If given this application with no API/DB/CLI access, they can:

1. Register a company (or sign in).
2. See a dashboard (company, plan, seats, branch/department counts; employees shown as “—”).
3. Edit the company profile (identity, contact, address, locale, working days/hours, branding URLs).
4. Track setup progress for the company-profile step.
5. Create, view, edit, deactivate, and reactivate legal entities (statutory IDs on the entity).
6. Create, view, edit, deactivate, and reactivate branches (including address and geofence numbers), after a legal entity exists.
7. Create, view, edit, deactivate, and reactivate departments, including a parent/branch relationship, in a **flat** list.
8. Create, view, edit, deactivate, and reactivate grades (level, CTC band, notice/probation, approval limit).
9. Create, view, edit, deactivate, and reactivate designations, optionally linked to department and grade.
10. Create, view, edit, deactivate, and reactivate shifts (timings, breaks, grace, hours, night/OT/cross-midnight).
11. Sign out.

That is the entire product surface.

---

## 16. What They Cannot Do

- Create, list, view, or edit employees (identity, code, status).
- Hire, terminate, or rehire (employment lifecycle).
- Assign branch/department/designation/grade/manager/shift to a person.
- Record or revise compensation.
- Capture employee PAN/Aadhaar/UAN or bank accounts.
- Run attendance, leave, or payroll.
- Search, filter, or paginate master-data lists.
- See a department tree.
- Change subscription plan.
- Rely on the UI to hide actions they are not allowed to perform (403 only after click).
- Switch companies if the token lists more than one.
- Use Employees/Attendance/Leave/Payroll navigation (it is not there).

---

## 17. Frontend Gaps

| Gap | Kind |
|---|---|
| Entire Employee workspace (list, create, detail) | **MISSING** — P0 |
| Employment / terminate / rehire UI | **MISSING** — P1 |
| Assignment + shift assignment UI | **MISSING** — P1 |
| Compensation UI | **MISSING** — P1 |
| `PermissionGate` / `usePermission` / nav filtering | **MISSING** — P2 |
| Department tree view | **MISSING** — P2 |
| List search / filter / pagination | **MISSING** — P2 |
| Authenticated redirect away from `/login` | **MISSING** — P2 |
| Unsaved-changes guard | **MISSING** — P2 |
| Proactive disable of unauthorized buttons | **MISSING** — P2 |
| Setup wizard covering org modules, not only company profile | **PARTIAL** — P2 |
| Geofence map | Documented as later (Attendance) — P3 |
| Signature image / logo file upload (URL text only) | **PARTIAL** — P3 |
| Skeletons instead of spinners | Unused component — P3 |
| Native time inputs | **PARTIAL** — P3 |
| Employee statutory + banking | Backend incomplete + UI missing — not a frontend-only gap |
| Attendance / Leave / Payroll UI | Planned/documented; no backend module either |

---

## 18. P0 / P1 / P2 / P3 Priorities

### P0 — Blocks basic HRMS usage

1. **Employee Foundation UI (E-01):** list, create (identity), detail, edit, deactivate/reactivate; display system-generated employee code; wire to existing `/employees` APIs.
2. **Navigation + routes** so an HR user can reach employees without guessing URLs (there are none to guess today).

Without P0 the app is an organisation master-data admin, not an HRMS.

### P1 — Needed for a usable Employee workflow

1. Employment create / history / terminate / rehire (effective dates, timeline).
2. Assignment create / history (branch, department, designation, grade, reporting manager, shift).
3. Compensation create / history / revise (effective dates).
4. Hire wizard or a documented screen sequence: Employee → Employment → Assignment → Compensation.

### P2 — Important operational UX

1. Permission-aware UI (`usePermission` / `PermissionGate`, hide nav the role cannot use).
2. List search, filter (active/inactive), pagination when volumes grow.
3. Department tree (or indented list) for hierarchy.
4. Unsaved-changes protection; login redirect if already authenticated.
5. Setup/onboarding that points at Legal Entity → Branch → … → Shifts, not only company profile.
6. Map 409 codes on department **create** the same way as edit.

### P3 — Polish

1. Skeletons; native date/time controls; file upload for logo/signature.
2. Company switcher if multi-company tokens become real.
3. Apply stale-resource `current` payload instead of reload-only.
4. Dashboard employee count once backend stops returning `null`.
5. Mobile QA pass on dialogs and lists.

---

## 19. Recommended Frontend Build Sequence

1. **Employee Foundation frontend (E-01)** — list/create/detail/edit/status, nav item, same UX patterns as Organisation (loading/empty/error, If-Match, confirm deactivate).
2. **Employment UI (E-03)** — hire + history + terminate + rehire.
3. **Assignment UI (E-04)** — including shift and reporting manager.
4. **Compensation UI (E-06)** — first CTC and revisions.
5. Permission-aware chrome (so ESS vs Admin does not share one unfiltered sidebar).
6. List/tree/search operational UX on Organisation + Employee lists.
7. Do not start Attendance/Leave/Payroll UI until those APIs exist (they do not).

---

## 20. Risks

- **False product completeness:** Organisation screens look like an HRMS; a stakeholder may assume employees are “in the next menu.” They are not.
- **API/UI drift:** Employee APIs can evolve while remaining invisible; first UI slice must re-read current contracts.
- **Security UX:** Any authenticated session that can load `/app` sees mutate buttons; authorization is server-side only. A 403 after save is easy to misread as a bug.
- **Client-only route guard:** No `middleware.ts`; a flash of protected layout depends on client JS.
- **Tokens in localStorage:** Documented XSS tradeoff in `token-storage.ts`.
- **Dashboard `employee_count=None`:** Even after employees exist via API, the dashboard will still show “—” until organisation dashboard is updated (**FACT** `organisation/service.py` sets `employee_count=None`).
- **Tests ≠ e2e:** Mocked page tests will stay green while the live API is down or incompatible.

---

## 21. Explicit Non-Goals

This audit did **not**:

- Implement any frontend or backend code.
- Redesign navigation or visual language.
- Create migrations or Employee UI tickets beyond a recommended sequence.
- Run a live browser session or create test employees.
- Treat documentation or ADRs as proof that a screen exists.
- Equate backend OpenAPI routes with user-facing features.

---

## 22. Final Verdict

**FACT:** Today’s frontend is a **working Organisation master-data console** with real API
integration, loading/empty/error states, optimistic concurrency, and soft deactivation — plus
auth (register/login).

**FACT:** It is **not** an HRMS for workforce operations. Employee, employment, assignment,
compensation, statutory (person), banking, attendance, leave, and payroll are **unavailable
from the UI**. Employee/employment/assignment/compensation APIs exist and are unused by
`apps/web`.

**Status:** Organisation usable / Employee unavailable.

**If I give this application to an HR/Admin user today, they can configure the company and
org structure, then they stop. They cannot put a single person on the books without leaving
the product.**
