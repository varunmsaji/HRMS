# Document 19 — RBAC, Permission Catalogue & Role Matrix

*(Renumbered and updated from Document 06/07 for the Python/FastAPI backend architecture — see Document 00 for the full document map.)*

---

## 1. The Access Control Equation

```
CAN_ACCESS = module_enabled_on_plan
           ∧ role_has_permission (with no explicit DENY)
           ∧ record_within_data_scope
           ∧ field_visible_to_role
           ∧ (not blocked by state, e.g. locked payroll period)
```

All five conditions are evaluated **server-side**. The UI hides what the user cannot do, but the UI
is never the enforcement point.

---

## 2. Permission Code Structure

`<MODULE>.<RESOURCE>.<ACTION>` — e.g. `PAYROLL.PAY_RUN.FINALISE`

Standard actions: `VIEW`, `VIEW_ALL`, `CREATE`, `UPDATE`, `DELETE`, `APPROVE`, `EXPORT`,
`IMPORT`, plus module-specific verbs (`FINALISE`, `PUBLISH`, `LOCK`, `OVERRIDE`).

`VIEW` = within own data scope. `VIEW_ALL` = company-wide, ignoring the reporting tree.
This distinction is what separates a Reporting Manager from an HR Manager.

---

## 3. Permission Catalogue

### 3.1 Employee (EMPLOYEE)
| Code | Description | Sensitive |
|---|---|:--:|
| `EMPLOYEE.VIEW` | View employees within scope | |
| `EMPLOYEE.VIEW_ALL` | View all employees in the company | |
| `EMPLOYEE.CREATE` | Create employee | |
| `EMPLOYEE.UPDATE` | Edit employee basic details | |
| `EMPLOYEE.UPDATE_SENSITIVE` | Edit PAN/Aadhaar/bank/statutory | ⚠ |
| `EMPLOYEE.DEACTIVATE` | Deactivate an employee record | |
| `EMPLOYEE.VIEW_COMPENSATION` | View CTC and salary structure | ⚠ |
| `EMPLOYEE.UPDATE_COMPENSATION` | Revise salary | ⚠ |
| `EMPLOYEE.VIEW_DOCUMENTS` / `.UPLOAD_DOCUMENTS` / `.VERIFY_DOCUMENTS` | | |
| `EMPLOYEE.VIEW_PERSONAL_CONTACT` | Personal email/phone/address | ⚠ |
| `EMPLOYEE.TRANSFER` / `.PROMOTE` / `.CONFIRM` | Lifecycle actions | |
| `EMPLOYEE.IMPORT` / `.EXPORT` | Bulk operations | ⚠ |
| `EMPLOYEE.GENERATE_LETTER` | Issue letters | |
| `EMPLOYEE.VIEW_AUDIT` | View change history | |
| `EMPLOYEE.BACKDATE_OVERRIDE` | Change records in a closed payroll period | ⚠ |

### 3.2 Attendance (ATTENDANCE)
`ATTENDANCE.PUNCH` · `.VIEW_OWN` · `.VIEW_TEAM` · `.VIEW_ALL` · `.EDIT` · `.OVERRIDE` ·
`.REGULARISE_REQUEST` · `.REGULARISE_APPROVE` · `.LOCK` · `.UNLOCK` · `.RECOMPUTE` ·
`.SHIFT_MANAGE` · `.ROSTER_MANAGE` · `.OT_APPROVE` · `.DEVICE_MANAGE` · `.GEOFENCE_MANAGE` ·
`.IMPORT` · `.EXPORT` · `.PUNCH_ON_BEHALF` ⚠

### 3.3 Leave (LEAVE)
`LEAVE.APPLY` · `.VIEW_OWN` · `.VIEW_TEAM` · `.VIEW_ALL` · `.APPROVE` · `.APPROVE_L2` ·
`.CANCEL_OWN` · `.CANCEL_ANY` · `.TYPE_MANAGE` · `.POLICY_MANAGE` · `.BALANCE_ADJUST` ⚠ ·
`.ACCRUAL_RUN` · `.YEAR_END_PROCESS` ⚠ · `.ENCASHMENT_APPROVE` · `.EXPORT`

### 3.4 Payroll (PAYROLL) — the most tightly held module
| Code | Description | Sensitive |
|---|---|:--:|
| `PAYROLL.COMPONENT.MANAGE` | Salary component master | ⚠ |
| `PAYROLL.STRUCTURE.MANAGE` | Salary structures | ⚠ |
| `PAYROLL.STATUTORY.MANAGE` | Statutory master rates | ⚠ |
| `PAYROLL.PAY_RUN.VIEW` / `.CREATE` / `.COMPUTE` | | ⚠ |
| `PAYROLL.PAY_RUN.APPROVE` | Approve a computed run | ⚠ |
| `PAYROLL.PAY_RUN.FINALISE` | Irreversible finalisation | ⚠⚠ |
| `PAYROLL.PAY_RUN.CANCEL` | | ⚠ |
| `PAYROLL.PAYSLIP.VIEW_OWN` | Own payslip | |
| `PAYROLL.PAYSLIP.VIEW_ALL` | Anyone's payslip | ⚠⚠ |
| `PAYROLL.BANK_FILE.GENERATE` / `.DOWNLOAD` | | ⚠⚠ |
| `PAYROLL.STATUTORY_FILE.GENERATE` | ECR/ESI/24Q | ⚠ |
| `PAYROLL.JOURNAL.EXPORT` | Accounting JV | |
| `PAYROLL.INPUT.MANAGE` | Ad-hoc earnings/deductions | ⚠ |
| `PAYROLL.LOAN.MANAGE` / `.APPROVE` | | ⚠ |
| `PAYROLL.TAX.VIEW_OWN` / `.MANAGE` / `.VERIFY_PROOF` | | ⚠ |
| `PAYROLL.FNF.CREATE` / `.APPROVE` | Full & final | ⚠ |
| `PAYROLL.REPORT.VIEW` / `.EXPORT` | | ⚠ |

**Separation of duties (mandatory control):** the same user must not hold both
`PAYROLL.PAY_RUN.COMPUTE` and `PAYROLL.PAY_RUN.FINALISE` in a default configuration. The system
warns on such a role assignment and records an acknowledgement. Enterprises will be audited on this.

### 3.5 Recruitment (RECRUITMENT)
`RECRUITMENT.REQUISITION.CREATE|VIEW|APPROVE` · `.OPENING.MANAGE|PUBLISH` ·
`.CANDIDATE.VIEW|CREATE|UPDATE|MERGE|EXPORT` · `.APPLICATION.VIEW|MOVE_STAGE|REJECT` ·
`.INTERVIEW.SCHEDULE|VIEW_FEEDBACK|SUBMIT_FEEDBACK` · `.OFFER.CREATE|APPROVE|SEND|VIEW_CTC` ⚠ ·
`.CONVERT_TO_EMPLOYEE` · `.ANALYTICS.VIEW`

### 3.6 Other Modules (abbreviated)
| Module | Representative codes |
|---|---|
| ORG | `ORG.COMPANY.MANAGE`, `.LEGAL_ENTITY.MANAGE`, `.BRANCH.MANAGE`, `.DEPARTMENT.MANAGE`, `.DESIGNATION.MANAGE`, `.GRADE.MANAGE`, `.HOLIDAY.MANAGE`, `.CUSTOM_FIELD.MANAGE` |
| ONBOARDING | `.TEMPLATE.MANAGE`, `.VIEW`, `.TASK.COMPLETE`, `.DOCUMENT.VERIFY` |
| EXIT | `.INITIATE_SELF`, `.INITIATE_OTHER` ⚠, `.ACCEPT`, `.CLEARANCE.MANAGE`, `.INTERVIEW.CONDUCT`, `.DOCUMENT.ISSUE` |
| PERFORMANCE | `.CYCLE.MANAGE`, `.GOAL.VIEW_TEAM`, `.REVIEW.SUBMIT`, `.REVIEW.MANAGER`, `.CALIBRATE` ⚠, `.RATING.VIEW_ALL` ⚠, `.PIP.MANAGE` ⚠ |
| WORKFLOW | `.DEFINITION.MANAGE`, `.APPROVE`, `.DELEGATE`, `.OVERRIDE` ⚠ |
| ASSET | `.VIEW`, `.MANAGE`, `.ASSIGN`, `.REQUEST`, `.AUDIT` |
| EXPENSE | `.CLAIM.CREATE`, `.APPROVE`, `.FINANCE_VERIFY`, `.POLICY.MANAGE`, `.EXPORT` |
| HELPDESK | `.TICKET.CREATE`, `.VIEW_ASSIGNED`, `.VIEW_ALL`, `.RESOLVE`, `.CONFIDENTIAL.VIEW` ⚠⚠ |
| LEARNING | `.COURSE.MANAGE`, `.ENROL_SELF`, `.NOMINATE`, `.ATTENDANCE.MARK`, `.REPORT.VIEW` |
| REPORT | `.STANDARD.VIEW`, `.BUILDER.USE`, `.SCHEDULE`, `.EXPORT_SENSITIVE` ⚠ |
| NOTIFICATION | `.TEMPLATE.MANAGE`, `.BROADCAST.SEND` ⚠ |
| SETTINGS | `.ROLE.MANAGE` ⚠⚠, `.USER.MANAGE` ⚠, `.INTEGRATION.MANAGE` ⚠, `.AUDIT.VIEW`, `.DATA_EXPORT` ⚠⚠ |
| PLATFORM (Super Admin only) | `.TENANT.MANAGE`, `.PLAN.MANAGE`, `.IMPERSONATE` ⚠⚠, `.FEATURE_FLAG.MANAGE`, `.SYSTEM.MONITOR` |

Total catalogue: **~250 permission codes**, seeded in the database (Doc 08 §14).

---

## 4. Default Role → Permission Matrix

Legend: ● full · ◐ own/team scope only · ○ read-only · — none

| Permission Group | Super Admin | Company Admin | HR Manager | HR Executive | Recruiter | Reporting Mgr | Team Leader | Employee | Finance | Auditor |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| **Org setup** | ● | ● | ○ | ○ | — | — | — | — | ○ | ○ |
| **Roles & permissions** | ● | ● | — | — | — | — | — | — | — | ○ |
| **User management** | ● | ● | ● | ◐ | — | — | — | — | — | ○ |
| **Employee view** | ● | ● | ● | ● | ◐ (hired only) | ◐ tree | ◐ direct | ◐ self | ○ | ○ |
| **Employee create/edit** | ● | ● | ● | ● | — | — | — | ◐ request | — | — |
| **Compensation view** | ● | ● | ● | — | ◐ offer only | — | — | ◐ self | ● | ○ |
| **Compensation edit** | ● | ● | ● | — | — | — | — | — | — | — |
| **Attendance view** | ● | ● | ● | ● | — | ◐ tree | ◐ direct | ◐ self | ○ | ○ |
| **Attendance edit/override** | ● | ● | ● | ● | — | — | — | — | — | — |
| **Attendance approve (regularisation)** | — | ● | ● | ◐ | — | ● tree | ● direct | — | — | — |
| **Leave apply** | — | ● | ● | ● | ● | ● | ● | ● | ● | — |
| **Leave approve** | — | ● | ● | ◐ | — | ● tree | ● direct | — | — | — |
| **Leave policy config** | ● | ● | ● | — | — | — | — | — | — | ○ |
| **Payroll setup** | ● | ● | ● | — | — | — | — | — | ○ | ○ |
| **Payroll compute** | — | ● | ● | ◐ assist | — | — | — | — | — | — |
| **Payroll approve** | — | ● | ● | — | — | — | — | — | ○ | — |
| **Payroll finalise** | — | ● | ●* | — | — | — | — | — | — | — |
| **Bank file download** | — | ● | ● | — | — | — | — | — | ● | — |
| **Payslip view** | — | ● | ● | ○ | — | — | — | ◐ self | ● | ○ |
| **Statutory filing** | — | ● | ● | ◐ | — | — | — | — | ● | ○ |
| **Recruitment** | — | ● | ● | ◐ | ● | ◐ own reqs | — | ◐ referral | — | ○ |
| **Offer approve** | — | ● | ● | — | — | ◐ own reqs | — | — | ○ budget | — |
| **Onboarding** | — | ● | ● | ● | ◐ | ◐ tasks | ◐ tasks | ◐ self | ◐ tasks | ○ |
| **Exit initiate (self)** | — | ● | ● | ● | ● | ● | ● | ● | ● | — |
| **Exit initiate (other)** | — | ● | ● | — | — | — | — | — | — | — |
| **F&F settlement** | — | ● | ● | — | — | — | — | ◐ view own | ● | ○ |
| **Performance** | — | ● | ● | ◐ | — | ● tree | ● direct | ◐ self | — | ○ |
| **Reports (standard)** | ● | ● | ● | ◐ | ◐ recruitment | ◐ team | ◐ team | ◐ self | ◐ finance | ● read |
| **Reports (sensitive/salary)** | — | ● | ● | — | — | — | — | — | ● | ○ |
| **Audit log** | ● | ● | ○ | — | — | — | — | — | ○ | ● |
| **Data export (bulk)** | ● | ● | ● | — | ◐ | — | — | — | ◐ | ○ |
| **Announcements** | — | ● | ● | ◐ | — | — | — | ○ | — | — |
| **Integrations** | ● | ● | ○ | — | — | — | — | — | ○ | ○ |
| **Impersonation** | ● | — | — | — | — | — | — | — | — | — |

`*` Payroll finalise for HR Manager is configurable per tenant; some organisations restrict it to
Company Admin or a dedicated Payroll Manager role. Default: enabled with the separation-of-duties
warning in §3.4.

**Auditor** is strictly read-only across everything, including the audit log, with **no** export of
salary-level detail unless explicitly granted — and every read is itself logged.

---

## 5. Data Scope Definitions

| Scope | Resolves to |
|---|---|
| `SELF` | Only the user's own employee record |
| `REPORTEES` | Direct reports only (one level) |
| `REPORTEE_TREE` | All descendants in the reporting tree (recursive CTE, depth-capped at 20 to prevent cycles from hanging queries) |
| `DEPARTMENT` | All employees in the specified department(s), including sub-departments |
| `BRANCH` | All employees at the specified branch(es) |
| `LEGAL_ENTITY` | All employees in the specified legal entity |
| `COMPANY` | All employees in the tenant |
| `ALL_COMPANIES` | Cross-tenant — Super Admin only |

**Reference implementation of scope resolution:**
```sql
WITH RECURSIVE tree AS (
  SELECT employee_id FROM employee_assignment
   WHERE company_id = $1 AND reporting_manager_id = $2 AND effective_to IS NULL
  UNION
  SELECT ea.employee_id FROM employee_assignment ea
    JOIN tree t ON ea.reporting_manager_id = t.employee_id
   WHERE ea.company_id = $1 AND ea.effective_to IS NULL
)
SELECT employee_id FROM tree;
```
Result cached in Redis for 60 s keyed by `scope:{company}:{user}:{version}`, invalidated on any
`employee_assignment` write.

---

## 6. Field-Level Security

| Classification | Examples | Visible to |
|---|---|---|
| `PUBLIC` | Name, employee code, designation, department, work email, work phone, photo | Everyone in the company |
| `INTERNAL` | Joining date, reporting manager, branch, shift, blood group | Roles with `EMPLOYEE.VIEW` |
| `SENSITIVE` | Personal mobile, personal email, address, DOB, emergency contact, dependents | HR roles + self |
| `RESTRICTED` | CTC, salary components, bank account, PAN, Aadhaar, tax declarations, disciplinary records, PIP, background-check results, medical, POSH complaints | Explicit permission only, always logged |

**Implementation:** the response serialiser (a Pydantic v2 response model applying a
permission-aware field mask) omits fields the caller's permission set does not allow. Masked
fields are **omitted** from the JSON (not sent as `null`), so that a client bug cannot leak
them and so that response shape reveals nothing.

Masking format for partially visible fields:
- PAN: `ABCDE****F`
- Aadhaar: `XXXX XXXX 1234`
- Bank account: `******7890`
- Salary in a list view where the user has aggregate but not individual rights: bucketed range

---

## 7. Special Access Rules

| Rule | Behaviour |
|---|---|
| **Self-approval** | A user can never approve their own request. Resolution skips to the next level (BR-02). |
| **Manager sees salary?** | **No** by default. This is deliberate and will be questioned by clients — the default protects the employee, and the tenant may override per role. |
| **HR sees own record?** | An HR Manager cannot edit their own compensation, leave balance or attendance. Self-service actions only; changes route to Company Admin. Enforced as a hard rule, not a policy. |
| **Confidential helpdesk** | POSH/grievance tickets are visible only to designated committee members, excluded from all standard reports and analytics, and never surfaced in AI features. |
| **Exited employees** | Auto-assigned the `EX_EMPLOYEE` role with read-only access to payslips, Form 16, F&F and experience letter for 12 months. |
| **Candidate portal** | Token-scoped access to their own application only; no login-based role. |
| **Break-glass** | Platform ops may gain temporary elevated production access via an approved, time-boxed, fully logged break-glass procedure with a mandatory post-incident review. |
| **Deactivated user** | Sessions revoked within 60 seconds; pending approvals reassigned; API keys created by them revoked. |

---

## 8. Testing Requirements for RBAC

Non-negotiable automated test suites (Doc 15 §6), implemented with pytest + pytest-asyncio +
httpx.AsyncClient:

1. **Permission matrix test** — for every (role, endpoint) pair, assert the expected allow/deny.
   Generated from this document's matrix as a data-driven test. ~250 permissions × 10 roles.
2. **Cross-tenant leakage test** — for every list and detail endpoint, create data in tenant A,
   authenticate as tenant B, assert 404 and zero rows. Runs on every CI build.
3. **Data-scope test** — build a 4-level reporting tree; assert each scope returns exactly the
   expected employee set, including the cycle-protection case.
4. **Field-masking test** — assert that RESTRICTED fields are absent from responses for roles
   without the permission, checked on the **raw JSON**, not through a client.
5. **Privilege-escalation test** — assert a user cannot grant themselves a permission they lack,
   cannot assign a role above their own level, and cannot widen their own data scope.
6. **Self-action test** — assert self-approval and self-compensation-edit are blocked.

A failing RBAC test blocks the release. No exceptions, no "we'll fix it in the next sprint".
