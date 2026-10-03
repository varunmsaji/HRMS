# Mobile feature-parity audit

Audited 2026-10-03: `main` (83e4d2c) vs `feature/flutter-mobile-app` (8b5fda9).
Goal: the Flutter app (`apps/mobile`) exposes the same features as the web app, on the same backend.

## Backend parity

- Outside `apps/mobile`, the two branches are tree-identical (API, web, migrations, tests). No backend drift.
- The face-attendance commits exist on both branches with different SHAs but the same content.
- **Pending on main (uncommitted):** `FacePunchRead.liveness_score` becomes `Decimal | None`. The mobile `FacePunchResult` parsed it as a required double and would crash on null. Fixed on the mobile branch as an uncommitted change in `attendance_repository.dart`. Land both together.
- `apps/mobile` on main is untracked build output only. The Dart source lives on the branch.

## Coverage summary

Path-level comparison. The backend has 304 routes and the mobile app calls about 90 of them. The web app has 73 pages and mobile has about 50 routes. Methods were checked by reading the repositories, not exhaustively. Neither UI was run.

## Covered in mobile

Auth (login, register, forgot/reset password, verify email, accept invite) · dashboard · company, branches, departments, designations, grades, legal entities · shifts, work/holiday calendars, weekly-off patterns · attendance, overtime and regularization policies (list, create, versions, publish) · policy assignments and resolution · self punch, face punch, face self-enrollment · regularizations and overtime (apply, approve, reject, cancel) · rosters (list, create), roster calendar · attendance periods (validate, finalize, reopen) · leave types, combination rules, year setting, statutory minimums, balances, applications · pay-run lifecycle, salary components and structures (list, create), statutory rates, my payslips · employees (list, create), personal-field profile · onboarding cases (send invite, request changes, activate), setup, users and roles.

## Gaps (work checklist, in suggested order)

### 1. Fix first
- [ ] Land the `liveness_score` nullable fix (mobile) together with the backend change.

### 2. Employee record (largest gap)
Web `/app/employees/[id]` and `/app/me` tabs; mobile shows personal fields only.
- [ ] Employments (list, create, edit, terminate), confirm employee
- [ ] Assignments (list, create, detail)
- [ ] Bank (list, create, detail)
- [ ] Compensation (list, create, detail)
- [ ] Statutory IDs (list, create, detail)
- [ ] Identity (get, patch)
- [ ] Education, experience, dependents (list, create, detail, delete)
- [ ] Employee invite (`POST /employees/{id}/invite`)
- [ ] Employee import: upload, template, reference data, errors (5 endpoints)

### 3. Onboarding
- [ ] Public employee form `/public/onboarding/{token}`: get, section patch, submit
- [ ] Public document upload, list, delete
- [ ] HR section review and document review, document list
- [ ] Case detail screen

### 4. Leave
- [ ] Leave application detail
- [ ] Leave ledger, manual adjustments, encashments
- [ ] Leave projections (list, create, detail, cancel)
- [ ] Leave policy edit, version CRUD, publish, resolve

### 5. Payroll
- [ ] Pay-run detail, edit, delete, rollback
- [ ] Per-employee pay-run detail, variance acknowledge, payslip view
- [ ] Payslip PDF and bank-advice download (file download support)
- [ ] Employee salary assign, breakup, bulk assignment
- [ ] Adjustments (list, create, delete)
- [ ] Payroll settings (get, put)
- [ ] Salary structure detail, edit, version create, lines, preview, publish, delete version
- [ ] Salary component edit, statutory rate edit

### 6. Attendance
- [ ] Day detail, calculate, calculate-range, recompute, keep-leave on work-on-leave
- [ ] Punch list and manual punch
- [ ] Period detail and summary
- [ ] Regularization and overtime detail screens
- [ ] Roster get, edit, delete, publish, bulk
- [ ] HR face-profile admin: list, approve, reject, review photo, open/close enrollment window, delete profile
- [ ] Policy identity edit, version edit/delete/resolve (verify what the shared policy repository already covers)

### 7. Org and calendar edits
- [ ] Holiday calendar get/edit/delete, holiday edit
- [ ] Work calendar get/edit/delete, exceptions (list, create, edit), day-type
- [ ] Weekly-off pattern get/edit/delete
- [ ] Shift get/edit/delete, versions CRUD, publish, resolve

### Not needed on mobile
`/health*`, `/auth/admin/users-check`, `/auth/companies/{id}` (internal or ops endpoints; confirm before dropping).

## Housekeeping
- Before merging the mobile branch into main, expect duplicate-content history for the face commits. Rebase the branch onto main first.
- Add a CI or script check that diffs the backend route list against the routes the mobile app calls, so drift shows up automatically.
