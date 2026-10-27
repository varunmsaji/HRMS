# Staff Spectrum HRMS — Cross-Module Workflow Catalog

Back to [Functional documentation](STAFF_SPECTRUM_HRMS_FUNCTIONAL_DOCUMENTATION.md) · [Modules](STAFF_SPECTRUM_HRMS_MODULE_CATALOG.md) · [Gaps](STAFF_SPECTRUM_HRMS_FUNCTIONAL_GAPS.md)

Only workflows that the code supports are listed as operational; missing links are called out explicitly.

## W1 — Tenant start-up
**Actors:** prospective admin. **Entry:** `POST /companies/register`. **Steps:** register (trial FREE, 5 seats) → admin configures legal entity, branches, departments, designations, grades → shifts + versions → holiday calendars, weekly-off, work calendar → policy assignments (work calendar, attendance/OT/regularization policies, leave types/policies/assignments, leave year) → payroll components/structures/statutory rates (verify) → attendance period creation. **Source of truth:** each master table. **Failure paths:** anything unconfigured fails closed (attendance `CONFIG_ERROR`, leave `POLICY_NOT_RESOLVED`, calendar not resolved). **Manual:** all of it; no templates/wizard beyond the single-step setup tracker. **Gap:** leave policy assignment needs ORG.CALENDAR + ATTENDANCE.POLICY permissions (Company Admin only). Modules: [01](modules/01_PLATFORM_IDENTITY_RBAC.md), [02](modules/02_ORGANISATION.md).

## W2 — Hire → onboarding → employee → login
**Actors:** CA (HR lacks grants), candidate, system. **Path A (onboarding):** create case → send invite (email, 7 days) → candidate fills 8 sections/uploads → submit → admin reviews sections/docs (reject → request changes → resubmit) → auto `VERIFIED` → activate (single transaction: employee, employment→PROBATION, assignment, bank, statutory, optional CTC, experience/education/dependants, documents copied) → activation email → auto account invite → candidate sets password → EMPLOYEE role + linked employee. **Path B:** HR creates employee manually (`PRE_JOINING`), starts employment (`PROBATION`), assignment, CTC, then invites. **Path C:** CSV import (API only). **States:** case DRAFT…ACTIVATED; employee PRE_JOINING→PROBATION→(confirm)ACTIVE. **Failure:** activation is atomic; invite email failure leaves a copyable link; seat limit blocks creation. **Missing:** case cancel/expiry, reminders, offer letter, checklist, probation end date/grade/manager/shift/salary assignment carried from the case (HR must set afterwards), recruitment before onboarding. Modules 03, 04.

## W3 — Employee setup for payroll eligibility
Employment (pay basis) → CTC (`employee_compensation`) → statutory profile (PF/ESI/PT state/LWF/regime) → bank → PAN/UAN (identity) → **salary assignment** (structure or daily rate; requires CTC) → leave eligibility needs only employment + resolved policy; attendance needs calendar + attendance policy (+shift). **Dependencies enforced:** salary assignment refuses without employment/CTC; pay-run lock reports `SALARY_MISSING`, `CTC_MISSING`, `BANK_MISSING`. **Gap:** nothing guides HR through this order.

## W4 — Leave → approval → attendance → payroll
1. Employee submits (needs policy resolved, calendar resolved, balance, period open) → approval chain (manager snapshot → HOD → HR; unresolved stages dropped; HR backstop) → final approval: employment re-check, balance lock, optional LOP split, **projection per day to Attendance** (attendance day recalculated to LEAVE/HALF_DAY), ledger `APPLICATION` debit.
2. Cancel (employee before start; HR after) → offsetting ledger entry + projection cancel.
3. Period close freezes attendance; **LOP days flow into paid/LOP fractions**; payroll prorates salary by paid days (no separate LOP line). Year-end encashment / manual encashment entries dated in the month are paid by payroll at Basic ÷ days.
**Async/eventual:** accrual and year-end via Celery; attendance recalculation is synchronous inside approval. **Failure:** if attendance refuses a day (period closed) the whole approval rolls back. **No notifications** at any step. Modules 05, 06, 07.

## W5 — Attendance capture → regularization → period close → payroll input
Punch (web/mobile/face/admin) → immediate best-effort calculation + 09:30 sweep (3 trailing days) → employee requests regularization (policy-allowed type; one active per date) → manager/HR approval applies synthetic punches/roster change and recalculates → overtime detected; review if post-approval required → 10:00 reminders for INCOMPLETE days → HR validates period (blockers: config errors, incomplete, pending regularization/OT, unpublished roster, work-on-leave) → finalize (resolves INCOMPLETE per policy, freezes summary, locks days) → payroll lock reads the **frozen** summary. **Reopen** allowed until a pay run is finalised. **Missing integrations:** no attendance export; default roles lack grants (A-1). Modules 06, 07.

## W6 — Salary configuration → pay run → payslip
Components → structure draft → publish (effective date) → assign to employees → create run (entity+month) → lock inputs (requires CLOSED attendance period for exactly that month; snapshot incl. arrears) → compute (maker) → acknowledge variances (>15 % default) → approve (checker ≠ maker, no errors, inputs unchanged) → finalise (immutable; attendance reopen blocked) → mark paid (manual) → employees read payslips; Company Admin downloads bank advice. **Corrections:** pay adjustments / backdated salary changes become arrears in the next run; before finalisation use rollback. **Failure paths:** inputs changed → rollback to DRAFT and relock; arrears stale → recompute. **Missing:** payment confirmation, F&F, reimbursements, statutory filings. Module 07.

## W7 — Termination → access revocation → leave/payroll consequences
HR terminates employment with last working day → blocked if leave exists after LWD → closes assignment/CTC/statutory rows at LWD → login ends the day after LWD (immediate if past; hourly sweep otherwise) → final month pays by employment-span proration and attendance `EXITED` days; leave balance remains (no encashment/recovery automatically; negative balances "recovered in F&F" has no F&F implementation) → **employee.status unchanged**, no exit checklist, no document generation. Modules 03, 05, 07.

## W8 — Face enrolment → face punch
HR opens 48 h window → employee consents and captures 5 poses on mobile → server liveness per capture, provider enrol, angle consistency → PENDING_APPROVAL → HR (not the employee) approves/rejects with photo review → ENROLLED → punch: server challenge (120 s) → N frames → liveness all frames → identity match all frames ≥ 0.90 → FACE punch → calculation. **Failure:** every rejection logged; 5 failures/10 min lockout. **Dependency:** provider + engine configured. **Policy:** once ENROLLED, plain self-punch is refused (403 `FACE_VERIFICATION_REQUIRED`); recovery is the HR on-behalf correction (audited). Employees with no profile, PENDING_APPROVAL or rejected/revoked enrolment keep the plain punch. Module 06 §4.8.

## W9 — Account access lifecycle
Invite → accept (new or existing account with password) → roles via fixed set → deactivate employee (immediate cutoff) or terminate (after LWD) → rehire reopens membership. Password reset revokes all sessions. No deactivation for non-employee users. Module 01.

## State summary
| Record | States |
|---|---|
| Onboarding case | DRAFT, INVITED, IN_PROGRESS, SUBMITTED, UNDER_REVIEW, CHANGES_REQUESTED, VERIFIED, ACTIVATED (EXPIRED, CANCELLED unused) |
| Employee | PRE_JOINING, PROBATION, ACTIVE (others unused) |
| Leave application | SUBMITTED, APPROVED, REJECTED, CANCELLED |
| Regularization | SUBMITTED, APPROVED, REJECTED, CANCELLED |
| Overtime | PENDING, AUTO_APPROVED, APPROVED, REJECTED |
| Attendance period | OPEN, CLOSED |
| Pay run | DRAFT, INPUTS_LOCKED, COMPUTED, APPROVED, FINALISED, PAID |
| Face profile | PENDING_APPROVAL, ENROLLED, REJECTED, REVOKED |
| Import batch | PENDING, PROCESSING, COMPLETED, COMPLETED_WITH_ERRORS, FAILED |
