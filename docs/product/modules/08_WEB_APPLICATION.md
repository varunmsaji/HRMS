# Module 08 — Web Application (Next.js)

> Part of [Staff Spectrum HRMS Functional Documentation](../STAFF_SPECTRUM_HRMS_FUNCTIONAL_DOCUMENTATION.md) · [Catalog](../STAFF_SPECTRUM_HRMS_MODULE_CATALOG.md) · [Mobile app](09_MOBILE_APPLICATION.md)

**Status:** Implemented; 63 Vitest test files (component/lib level). End-to-end browser behaviour was not exercised by this review.

## 1. Overview
`apps/web` — Next.js 16 (App Router), React 18, Tailwind, TypeScript; a pure client of the `/v1` API (no server-side data access). Middleware sets a **strict CSP** with per-request nonce (`script-src 'self' 'nonce-…' 'strict-dynamic'`, `frame-ancestors 'none'`, `connect-src` limited to self + API origin). Auth state in `AuthProvider` (see Platform §4.2): access token and session metadata in `localStorage`, refresh cookie HttpOnly; automatic 401→refresh→retry with a **cross-tab single-flight lock**; client timeouts and distinct offline/timeout errors; route error boundaries.

## 2. Navigation (`components/layout/nav-items.ts`)
Primary sidebar (same for every user): Dashboard, My Profile* , My Payslips* (*only if the user has a linked employee), Employees, Onboarding, Shift Rosters, Attendance, Regularizations, Overtime, Leave, Leave Balances, Payroll, Settings. Settings hub groups: Organisation (Company Profile, Companies, Branches, Departments, Designations, Grades); Attendance & Time (Shifts, Attendance Periods, Work Calendars, Holiday Calendars, Weekly-Off Patterns, Attendance/Overtime/Regularization Policies); Leave (Types, Policies, Combination Rules, Leave Year, Statutory Minimums); Payroll (Components, Structures, Statutory Rates); Policies (Assignments, Resolution); Administration (Setup, Users).
**The sidebar is not permission-filtered.** Pages read `usePermissions()` (the flat list from `/auth/me`) to hide actions or show a permission message; the API is the authority (`403`/`404`). Post-login landing: `DASHBOARD.COMPANY.VIEW` → `/app/dashboard`; else linked employee → `/app/me`.

## 3. Role-relevant behaviour (default roles)
| User | What works end-to-end on web (by permission) |
|---|---|
| Employee | My Profile (read), My Payslips, Leave (apply, withdraw, view balances, own applications). **Attendance self-view/punch and regularization require `ATTENDANCE.*` grants the default Employee role lacks** (Attendance A-1). |
| Reporting Manager | Team leave applications (if named approver), regularization/overtime review, single employee records; cannot list employees |
| Branch Manager | Employee list and attendance view for the branch |
| HR Admin | Employees (full), leave admin, payroll setup/run (not approve), onboarding **not** available (no grants), org setup **not** available |
| Company Admin | Everything |

## 4. Screen inventory
Public: login, register, forgot/reset password, verify email, accept invite, candidate onboarding wizard. App routes: see each module doc (`/app/dashboard`, `/app/me`, `/app/me/payslips`, `/app/employees`, `/app/onboarding`, `/app/attendance*`, `/app/regularizations*`, `/app/overtime*`, `/app/rosters*`, `/app/leave-*`, `/app/payroll/**`, `/app/settings`, `/app/setup`, `/app/users`, and the Organisation/policy configuration pages). Company dashboard (`/app/dashboard`) shows setup progress, subscription and counts (Organisation §4). Attendance page is a rich analytics dashboard (KPIs, who's-in, needs-attention, trend, heatmap, department breakdowns, reports table; no export).

## 5. Web-only vs shared
Web-only: payslip **print** view, onboarding review with document preview, full statutory/structure editors. Shared with mobile: auth flows, leave, attendance viewing, payroll pay runs/payslips, employee records, onboarding candidate wizard. Mobile-only: face enrolment and face punch, camera capture.

## 6. Limitations
Dropdown loads cap at 100 employees (`per_page: 100`) on several pages; no server-side employee search; attendance export unavailable; no tenant switcher; no notifications UI; permission-based hiding is cosmetic.

## 7. Evidence
`apps/web/src/{app,components,lib,hooks,middleware.ts}`, `vitest.config.ts`, CI job "Web — lint, typecheck, vitest, build" in `.github/workflows/ci.yml`. Frontend capability audit: `docs/architecture/HRMS_FRONTEND_CAPABILITY_AUDIT.md`.
