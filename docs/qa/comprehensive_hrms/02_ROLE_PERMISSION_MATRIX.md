# 02 — Role and permission matrix

Source: `OrganisationService.register_company` grant lists, and the scope stored on `role_permission`. Out-of-scope resources return not-found rather than 403. The web navigation is not filtered by these grants (G-W1). A hidden button is not evidence of enforcement. Every negative case calls the API as well as opening the page.

There is no custom-role builder. DEPARTMENT and LEGAL_ENTITY scopes are not in use.

## Default roles

| Role | Scope on its grants | Intended person |
|---|---|---|
| COMPANY_ADMIN | COMPANY | Founder and payroll approver |
| HR_ADMIN | COMPANY | HR operations. Not payroll approver. Not org-master editor. Not leave-type editor |
| REPORTING_MANAGER | REPORTEE_TREE | The manager named on the employee. Leave stage approval also requires that identity |
| BRANCH_MANAGER | BRANCH | Branch visibility. A manager stage still needs the snapshotted person |
| EMPLOYEE | SELF | The person themselves |

## Actions

| Action | Admin | HR | Reporting manager | Branch manager | Employee | Negative case |
|---|---|---|---|---|---|---|
| Register company | creator becomes admin | — | — | — | — | AUTH-010 |
| Org masters | allow | deny | deny | deny | deny | ORG-002 |
| Create employee | allow | allow | deny | deny | deny | EMP-001, EMP-004 |
| See employees | company | company | tree | branch | self | EMP-004, SEC-002 |
| Punch | allow | view | tree where granted | branch where granted | self, current code | ATT-003, ATT-012 |
| Lock attendance period | allow | deny | deny | deny | deny | ATT-009 |
| Regularisation approve | allow | allow | tree | branch only if also the named manager | deny | ATT-008 |
| Leave type and policy | allow | deny | deny | deny | deny | LEV-C01 |
| Submit leave | allow | on behalf where granted | — | — | self | LEV-C22 |
| Approve leave manager stage | only if they are the snapshotted manager | HR stage, company scope | snapshotted manager | not unless they are that manager | deny | LEV-C20, LEV-C21, LEV-C22 |
| Cancel approved leave after start | if they hold the cancel grant | grant is on HR | deny | deny | deny | LEV-C33, LEV-C34 |
| Adjust leave balance | allow | allow | deny | deny | deny | LEV-C38, LEV-C39 |
| Read another person's balance | allow | allow | tree | branch | deny | LEV-C44, LEV-C45 |
| Salary setup and compute | allow | allow | deny | deny | deny | PAY-001 |
| Approve, finalise, mark paid | allow, and not if they computed it | deny | deny | deny | deny | PAY-003, PAY-004 |
| Own payslip | allow | allow | — | — | self | PAY-006, PAY-007 |
| Bank advice | allow | deny | deny | deny | deny | PAY-011 |
| Onboarding case | allow | allow | deny | deny | deny | ONB-001 |
| Document download | company where granted | where granted | — | — | self | DOC-001, DOC-003 |

## Tenant rules

- Missing company context: AUTH-008.
- Foreign company id: AUTH-009.
- Foreign resource id on read and write: SEC-002.
- Worker payload company id: SEC-005.
- Two live companies: JRN-009.

## Audit

Leave decisions, payroll transitions, punches, and employee creates are expected to record the actor user id. Where a service does not write an audit row, the case says so and the result is recorded as not applicable rather than passed by assumption. There is no audit-log screen in the product, so evidence is the database row.
