# Coverage summary

Design coverage only. Execution coverage is 0 of 120. `NOT_RUN` is not a pass.

## Cases

| Module | Cases |
|---|---|
| Leave | 48 |
| Attendance | 12 |
| Payroll | 12 |
| Identity | 10 |
| Journeys | 10 |
| Employee | 7 |
| Security | 6 |
| Onboarding | 5 |
| Organisation | 4 |
| Documents | 3 |
| Platform | 3 |
| **Total** | **120** |

| Type | Cases |
|---|---|
| Functional | 54 |
| Security | 35 |
| UI | 14 |
| Concurrency | 9 |
| Integration | 5 |
| Recovery | 3 |

Priority: 81 P0, 36 P1, 3 P2, 0 P3.

## Feature coverage

Implemented modules in the inventory each have at least one case: identity, organisation, employee, onboarding, attendance, leave, payroll, documents, platform.

Not given a case, on purpose or because the feature is missing:

- Face attendance, recruitment, loans, reimbursements, full-and-final settlement, in-app notifications.
- Leave approver reassign (API only, no case yet).
- Overtime as its own workflow.
- Rosters and break matching. Breaks were not confirmed as an implemented punch type in this pass.
- Combination-rule configuration has no standalone case. Overlap of the same type is LEV-C15.
- The HOD stage of `MANAGER_THEN_HOD_THEN_HR` has no case of its own. Missing-manager fallthrough is LEV-C24. Two-stage manager then HR is LEV-C25.

So every discovered implemented module has a case. Not every screen does. About 81 web pages exist; the catalogue walks the journeys and the permission boundaries, not each settings screen.

## Risk coverage

The permission boundaries in `02_ROLE_PERMISSION_MATRIX.md` each have an allow case and a deny case, except department scope, which is not implemented (BR-12).

Leave state table: 11 transitions, each mapped to a case. Duplicate execution is LEV-C19, LEV-C28, LEV-C35. Concurrent approve versus cancel is LEV-C29.

Boundary values present: balance exactly exhausted, one day over, half day 0.50, max consecutive plus one, reversed dates, zero consuming days, carry cap, encashment one day over the minimum remaining.

Concurrency and idempotency: 9 cases. Recovery: 3 cases. That is thin next to the functional set, and the execution plan keeps recovery in its own batch.

## Requirements without a source

BR-01 through BR-14 have no single product sentence that settles them. They are listed in `OPEN_BUSINESS_RULES.md` and are not counted as covered requirements.

## UI that cannot be exercised here

- Flutter, until the SDK is installed.
- Employee CSV import, leave reassign, and any missing cancel control: API or blocked.
- Playwright is not a dependency of `apps/web`. UI execution will be blocked if the host has no browser runner. The cases stay worded for the browser anyway.

## Historical suite

The October 25 register is not included in the 120 and was not rerun.
