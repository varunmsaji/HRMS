# Staff Spectrum HRMS — Module Catalog

Back to [Functional documentation](STAFF_SPECTRUM_HRMS_FUNCTIONAL_DOCUMENTATION.md) · [Workflows](STAFF_SPECTRUM_HRMS_WORKFLOW_CATALOG.md) · [Gaps](STAFF_SPECTRUM_HRMS_FUNCTIONAL_GAPS.md)

Roles: **EMP** Employee · **RM** Reporting Manager · **BM** Branch Manager · **HR** HR Admin · **CA** Company Admin (default roles). Status uses the requested vocabulary. "UI" = web/mobile screens exist.

## Modules and submodules
| Module → submodule | Roles (default) | Status | UI | Detail |
|---|---|---|---|---|
| **Platform** | | | | [01](modules/01_PLATFORM_IDENTITY_RBAC.md) |
| Company registration | public → CA | Implemented and verified | web, mobile | §4.1 |
| Login / refresh / logout / lockout | all | Implemented and verified | both | §4.2 |
| Password reset, email verification | all | Implemented and verified | both | §4.3–4.4 |
| User invite, user list, role assignment | CA (HR for employee invite) | Implemented and verified | both | §4.5 |
| Roles & permission model (5 fixed roles) | — | Implemented; no editor | none | §2 |
| Tenancy / RLS | — | Implemented and verified | — | §1.1 |
| Plans / seat limit | CA view | Partially implemented (no billing/expiry) | dashboard | §1.2 |
| Audit log | — | Backend-only (write only; no viewer) | none | §4.6 |
| Idempotency, rate limits, uploads, PII encryption | — | Implemented and verified | — | §4.7–4.10 |
| Email delivery | — | Implemented (best effort, no retry) | — | §4.11 |
| **Organisation** | CA | | | [02](modules/02_ORGANISATION.md) |
| Company profile, setup progress, dashboard | CA | Implemented; some fields unused | both | §4 |
| Legal entity, branch, department, designation, grade | CA | Implemented and verified | both | §4 |
| Shifts and versions | CA | Implemented and verified | both | §4 |
| Holiday calendars/holidays, weekly-off patterns, work calendars, exceptions | CA | Implemented and verified | both | §4 |
| Policy assignment & resolution | CA | Implemented and verified | both | §4 |
| **Employee** | HR, CA (+ scoped view) | | | [03](modules/03_EMPLOYEE.md) |
| Employee identity/profile, list | HR, BM, CA | Implemented; no search/filter | both | |
| Employment, rehire, confirm, terminate, access revocation | HR, CA | Implemented; status lifecycle partial | both | |
| Assignment, compensation, statutory, bank, identity | HR, CA | Implemented and verified | both | |
| Experience, education, dependants/nominees | HR, CA | Implemented and verified | both | |
| Employee documents | HR, CA; EMP read | Implemented and verified | both | |
| Offboarding / exit / F&F | — | Not implemented | — | |
| **Onboarding & import** | CA (HR lacks grants) | | | [04](modules/04_ONBOARDING_AND_BULK_IMPORT.md) |
| Onboarding cases, public wizard, review, activation | CA, candidate | Implemented; cancel/expiry absent | both | |
| Bulk employee import | HR, CA | Backend-only | none | |
| Recruitment / ATS | — | Not implemented | — | |
| **Leave** | EMP, RM, BM, HR, CA | | | [05](modules/05_LEAVE.md) |
| Leave types, policies/versions, combination rules, leave year, statutory minimums | CA | Implemented and verified | both | |
| Applications & approvals (AUTO/MANAGER/…/HR chains), cancel, reassign | all | Implemented and verified | both | |
| Ledger, balances, adjustments, encashment | HR, CA; EMP view | Implemented and verified | both | |
| Accrual (monthly/yearly), year-end, comp-off | system | Implemented and verified | — | |
| Leave notifications | — | Not implemented | — | |
| **Attendance** | EMP*, RM, BM, HR, CA (*needs grants) | | | [06](modules/06_ATTENDANCE.md) |
| Punches (plain/on-behalf) | EMP*, CA | Implemented and verified | both | |
| Daily calculation engine | system | Implemented; some policy fields unevaluated | — | |
| Rosters | CA | Implemented and verified | both | |
| Regularization | EMP*, RM, HR, CA | Implemented and verified | both | |
| Overtime review & comp-off feed | RM, HR, CA | Implemented and verified | both | |
| Attendance periods (validate/finalize/reopen/summary) | CA | Implemented and verified | both | |
| Incomplete-day reminders | system | Implemented | email | |
| Dashboards / reports | HR, BM, CA | Partially implemented (no export) | both | |
| Face attendance (enrol/punch/cleanup) | EMP*, CA | Disabled/unconfigured by default; not production-ready | mobile (+web HR card) | |
| Geofence, device/import punches | — | Not implemented | — | |
| **Payroll** | HR, CA, EMP | | | [07](modules/07_PAYROLL.md) |
| Components, structures, salary assignment | HR, CA | Implemented and verified | both | |
| Pay runs (create…paid, rollback) | HR process, CA approve | Implemented and verified | both | |
| Statutory rates (PF/ESI/PT/LWF/TDS) | HR, CA | Implemented; legal correctness unverified | both | |
| Payslips, bank advice, adjustments/arrears | EMP, HR, CA | Implemented and verified | both | |
| Reimbursements, loans, bonuses, F&F, Form 16/24Q, ECR, payment integration | — | Not implemented | — | |
| **Clients** | | | | |
| Web | all | Implemented, not E2E-verified | — | [08](modules/08_WEB_APPLICATION.md) |
| Mobile | all | Implemented, not E2E-verified | — | [09](modules/09_MOBILE_APPLICATION.md) |
| **Operations** | operators | Implemented; alert target unset | — | [10](modules/10_OPERATIONS_AND_DEPLOYMENT.md) |

## Role → what it can do (defaults)
| Role | Primary modules | Cannot (notably) |
|---|---|---|
| EMP | own profile, leave, payslips | attendance (no grant), edit profile |
| RM | approve leave/regularization/OT for named reportees; view reportee records | apply for leave (no grant), list employees |
| BM | branch employee list, branch attendance view | apply, approve unless also the named manager |
| HR | employees, leave admin, payroll setup/process | org setup, onboarding, attendance admin, payroll approve |
| CA | everything incl. payroll approve, bank advice | independent second approver if sole admin |
