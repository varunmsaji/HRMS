# Staff Spectrum HRMS — Functional Gaps, Inconsistencies and Decisions Register

Back to [Functional documentation](STAFF_SPECTRUM_HRMS_FUNCTIONAL_DOCUMENTATION.md) · [Modules](STAFF_SPECTRUM_HRMS_MODULE_CATALOG.md) · [Workflows](STAFF_SPECTRUM_HRMS_WORKFLOW_CATALOG.md)

Prioritised by user impact and business risk. **V** = verified from code/DB in this review; **R** = potential risk, not reproduced; **D** = product-owner decision needed. Nothing here has been fixed; no code was changed.

## P1 — Blocks core use or carries financial/legal/security risk
| ID | Gap | Evidence | Type | Decision needed |
|---|---|---|---|---|
| G-A1 | **Default Employee role has no `ATTENDANCE.*` grants** → ordinary employees cannot punch, see own attendance, request regularization, or enrol face. HR Admin cannot view attendance, manage rosters/policies, lock periods, manage face enrolment. | `register_company`; dev DB `role_permission`; no role editor | V | D: intended grant set per role; whether a data fix exists out-of-band |
| G-P1 | **HR Admin default lacks `ORG.*`, `ONBOARDING.*`, `DASHBOARD.COMPANY.VIEW`** → HR cannot create org masters, run onboarding, or see the dashboard; list endpoints used by HR forms may 403. | same | V / R (form impact) | D |
| G-R1 | **No role/permission editor**; only 5 fixed roles; no multi-branch manager; no custom roles (e.g. Payroll Admin, Attendance Admin). | `ASSIGNABLE_ROLE_CODES` | V | D |
| G-PAY1 | **Statutory compliance unverified**: seeded PF/ESI/PT(MH,KA)/TDS rates are "verify before use"; HR can edit *and* verify its own rates; PT states other than MH/KA produce a warning and **no deduction**. | `DEFAULT_STATUTORY_RATES`, `statutory.py` | V | D: compliance owner + second-person verification |
| G-PAY2 | **TDS limited**: new regime only (old regime blocks run), no declarations/HRA/LTA, no prior-employer income, no surcharge, no marginal relief; whole gross treated taxable; no Form 16/24Q. | `income_tax.py` docstring | V | D |
| G-PAY3 | **Missing payroll scope**: F&F settlement (leave negative-balance recovery references it), reimbursements, loans/advances, bonuses, off-cycle runs, PF ECR/ESI returns, payment confirmation/reconciliation, payroll reports. | search of `modules/payroll` | V | D |
| G-PAY4 | **Control weakness**: same permission approves, finalises and marks paid; sole-admin tenants cannot satisfy maker≠checker. | `permissions.py`, `PayRunService.approve` | V | D |
| G-F1 | **Face attendance not production-ready**: anti-spoof thresholds uncalibrated, passive single-frame only, no active liveness, not tested on real devices/attacks; plain punch always available so face is advisory; retention periods unset; uncommitted hardening in tree. | liveness report; `face_service.py` | V | D: pilot scope, retention periods, enforcement policy |
| G-N1 | **No notifications of any kind** (leave/regularization/OT/payslip/onboarding review) except a few emails; approvers must poll. No push/in-app. | grep; mobile deps | V | D |

## P2 — Material functional gaps and inconsistencies
| ID | Gap | Evidence | Type |
|---|---|---|---|
| G-A2 | **Attendance policy fields stored but not evaluated**: punch rounding, half_day_split/boundary, early_out_uses_core_end, excess_break_behaviour, auto-close fields and AUTO_CLOSE behaviour, WFH flags, split-shift mandatory/compensation, work_on_leave_behaviour (superseded); regularization `auto_approve_within_minutes`; OT `requires_pre_approval`. HR can configure them with no effect. | `calculation.py` usage search | V |
| G-A3 | Plain punch recorded as source `WEB` even from mobile; sources MOBILE/DEVICE/IMPORT/API never assigned; no geofence/device integration. | `router.py` | V |
| G-A4 | No attendance export/report download. | `reports-panel.tsx` | V |
| G-A5 | Regularization monthly cap uses UTC month, leave uses company month. | services | V |
| G-L1 | No default leave types/policies; a new tenant cannot take leave until configured; leave policy assignment requires `ORG.CALENDAR.MANAGE`+`ATTENDANCE.POLICY_MANAGE` (not LEAVE) so only Company Admin can assign. | `submit`, `_require_policy_assignment_permission` | V |
| G-L2 | Statutory-minimum check: docstring says NONE-accrual never blocks, code blocks when a floor exists. | `_annual_entitlement_days` | V (conflict) |
| G-L3 | Comment says payroll pays only system-written encashments; code pays **all** `ENCASHMENT` rows dated in the pay month (manual too). | `list_encashments_between` | V (conflict) |
| G-L4 | Monthly accrual only within first 5 days of month; no back-fill for late-created policies/employees; yearly accrual not prorated. | `tasks.py`, `LeaveAccrualService` | V |
| G-L5 | No edit/resubmit of leave; attachments are free-text references; half-day only for single-day requests; managers/branch managers cannot apply for leave without also holding EMPLOYEE role. | schemas, role grants | V |
| G-E1 | Employee status lifecycle incomplete: termination leaves `status` unchanged; ON_NOTICE/EXITED/etc. unused; no offboarding/exit workflow, notice period, asset return. | `terminate_employment` | V |
| G-E2 | No employee self-service profile edits; no server-side employee search/filter; Reporting Manager cannot list reportees; 100-row dropdown caps in web. | permissions, router | V |
| G-E3 | Bank account verification never performed (always PENDING). | `create_bank` | V |
| G-O1 | Company working days, business hours, fiscal-year month, locale/date-format stored but unused elsewhere; branch geofence, grade probation/notice/approval-limit unused. | grep | V |
| G-O2 | Bulk employee import has **no UI** (API only), no dry-run, no rollback, imports no statutory/bank/PAN/salary. | clients grep | V |
| G-ON1 | Onboarding: `ONBOARDING.CANCEL` unused, no cancel route, `EXPIRED`/`CANCELLED` unreachable, no reminders; activation does not carry grade/manager/shift/probation date/pay basis/salary assignment. | `OnboardingActivationService` | V |
| G-ON2 | **No recruitment/ATS** despite roadmap docs and any expectation of candidate sourcing/offers; no AI features. | search | V (Not implemented) |
| G-T1 | Trial expiry, plan change, billing, feature-flag gating not implemented (only seat limit). | `get_subscription_summary` | V |
| G-T2 | No audit-log viewer, no tenant/company switcher, no deactivation of non-employee users, no "last admin" safeguard. | routers | V |
| G-W1 | Web/mobile navigation not permission-filtered; users reach pages that return 403/empty states. | `nav-items.ts`, `settings_hub_screen.dart` | V |
| G-M1 | Mobile: no push, no offline, no app lock; iOS unverified; mobile dashboard tab shows permission error for non-admin users. | pubspec, dashboard screen | V |
| G-OPS1 | Alert destination for monitor undefined; thresholds provisional; restore drills not evidenced. | `hrms_monitor.sh` header | V / D |

## P3 — Test and verification gaps
| ID | Gap |
|---|---|
| T-1 | Default-role journeys are untested: integration tests build their own roles (e.g. `ATT_TEST_ROLE_*`), which is why G-A1 is invisible to CI. Add a role-matrix test against `register_company` roles (Leave has `test_leave_rbac_matrix.py`, other modules do not). |
| T-2 | No browser end-to-end or device tests were observed for web/mobile; mobile `live/` tests exist but their environment requirements were not exercised. |
| T-3 | Anti-spoofing effectiveness untested beyond 3 sample images; no calibration set. |
| T-4 | Statutory and TDS calculations are unit-tested for plumbing; no independent actuarial/compliance reconciliation was found. |
| T-5 | Statutory-minimum with NONE accrual and leave encashment payroll interplay lack explicit tests (not located). |

## Conflicting or ambiguous sources (resolve before relying on either)
| Topic | Source A | Source B |
|---|---|---|
| Payroll pays which encashments | comment in `leave/service.py` ("system-written only") | `list_encashments_between` (all) |
| NONE-accrual vs statutory minimum | docstring "never trips the floor" | enforcement code |
| Permission naming for shifts / legal entities | `docs/product/19_RBAC_and_Permission_Matrix.md` (`ATTENDANCE.SHIFT_MANAGE`, `ORG.ENTITY.MANAGE`) | code (`ORG.SHIFT.MANAGE`, `ORG.LEGAL_ENTITY.MANAGE`) — code authoritative |
| Product scope (recruitment, AI, performance…) | `docs/product/*` roadmap/PRD | repository contains none |

## Product-owner decisions required (summary)
1. Default permission set per role (esp. Employee attendance, HR org/onboarding/dashboard) and whether to allow custom roles (G-A1, G-P1, G-R1).
2. Compliance ownership and process for statutory rate verification; TDS scope; F&F and statutory filings roadmap (G-PAY1–3).
3. Payroll control model: separate finalise/pay approver; sole-admin tenants (G-PAY4).
4. Face attendance: pilot scope, enforcement vs optional, retention periods, calibration plan (G-F1).
5. Notification strategy: email/push/in-app for approvals and payslips (G-N1).
6. Which unevaluated attendance policy options should be implemented or removed from the UI (G-A2).
7. Employee lifecycle: statuses, offboarding, notice periods (G-E1).
8. Recruitment/AI: confirm out of scope for this release (G-ON2).
9. Subscription: trial expiry, billing, feature gating (G-T1).
10. Whether bulk import needs a UI and dry-run (G-O2).
