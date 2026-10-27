# Test data catalogue

Synthetic only. Domain `qa.invalid`. No real names, government ids, or bank accounts. Account numbers below are obvious fakes.

All of this data is loaded into a disposable database during an approved execution batch. Nothing here is loaded by the design phase.

## Tenants

| Marker | Company | Purpose |
|---|---|---|
| TEN-A | QA Foundry | Primary journeys |
| TEN-B | QA Northwind | Isolation. Every person and branch name is prefixed `B-` |

Unique marker strings that must never appear in the other tenant's API bodies: `MARKER-FOUNDRY` and `MARKER-NORTHWIND`, stored in each company's display name.

## People in tenant A

| Id | Email | Role | Placement |
|---|---|---|---|
| founder | founder.a@qa.invalid | COMPANY_ADMIN | — |
| hr | hr.a@qa.invalid | HR_ADMIN | — |
| maya | maya.a@qa.invalid | REPORTING_MANAGER | manager of Alice |
| neil | neil.a@qa.invalid | REPORTING_MANAGER | other tree, used after a manager change |
| north-mgr | north.mgr.a@qa.invalid | BRANCH_MANAGER | branch North, not Alice's manager |
| alice | alice.a@qa.invalid | EMPLOYEE | North, Engineering, reports to Maya, joined 2026-04-01, basic 30000.00 |
| bob | bob.a@qa.invalid | EMPLOYEE | North, reports to Maya, used for termination |
| dana | dana.a@qa.invalid | EMPLOYEE | South, other manager |
| charlie | charlie.a@qa.invalid | EMPLOYEE | North, reports to Neil |
| hire | new.hire@qa.invalid | candidate | created by onboarding |
| admin-2 | admin2.a@qa.invalid | COMPANY_ADMIN | second approver so maker-checker can succeed |

Tenant B repeats founder, hr, and one employee with the `B-` prefix and different fixed UUIDs. UUIDs are assigned by the seed script at execution time and written into the evidence folder. They are stable for a run, not hardcoded in this document, because the schema generates them.

## Calendar

- Time zone Asia/Kolkata.
- Working days Monday to Friday.
- 2026-06-06 and 2026-06-07 are weekly off.
- Fixture holiday on 2026-06-12 only for LEV-C06, where that date is WEEKLY_OFF and the days on either side are WORKING. If one calendar cannot represent both the normal weekend and that sandwich fixture, use a second assignment and say which employee has it.
- Employee with no calendar, used only by LEV-C08.

## Leave opening ledger

| Person | Type | Sum |
|---|---|---|
| Alice | QA Casual | 10.00, unless a case sets 2.00 or 8.00 for that case only |
| Alice | Comp-off | 0.00 until LEV-C43 credits 1.00 |
| Bob | QA Casual | 4.00 |

Policy QA Casual: entitlement 12, accrual NONE for application cases, monthly only in LEV-C41, max consecutive 5, half day on, sandwich on, reserve off except LEV-C14, negative off, reason required, chain MANAGER except where a case names AUTO or MANAGER_THEN_HR, carry cap 5.

## Payroll

- Basic 30000.00 from 2026-04-01.
- June 2026 period.
- Statutory rates either all off, or a copied rate card whose expected paise are calculated from `compute_employee` and written into the evidence before the assertion.
- Bank account `999000111222`, IFSC `TEST0000001`.

## Documents

`qa.txt` containing the single line `synthetic-document`.

## Cleanup

Drop the disposable database, flush the disposable Redis DB, and delete the disposable bucket. Do not run cleanup against any name that was not printed in the `ISOLATION PROVED` line for that batch.
